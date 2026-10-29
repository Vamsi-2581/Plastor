//! numpy .npy / .npz 읽기·쓰기. 하네스 파일(masks.npz 등)을 그대로 쓰기 위해 필요한 만큼만.
//! 지원: bool(|b1), uint8(|u1), float64(<f8), C 순서. 다른 형식은 오류로 돌려준다.
use std::collections::BTreeMap;
use std::io::{Read, Write};

#[derive(Clone, Debug)]
pub struct Arr {
    pub shape: Vec<usize>,
    pub data: ArrData,
}

#[derive(Clone, Debug)]
pub enum ArrData {
    Bool(Vec<bool>),
    U8(Vec<u8>),
    F64(Vec<f64>),
    I64(Vec<i64>),
}

impl Arr {
    pub fn as_bool(&self) -> Vec<bool> {
        match &self.data {
            ArrData::Bool(v) => v.clone(),
            ArrData::U8(v) => v.iter().map(|&x| x != 0).collect(),
            ArrData::F64(v) => v.iter().map(|&x| x != 0.0).collect(),
            ArrData::I64(v) => v.iter().map(|&x| x != 0).collect(),
        }
    }
}

fn header_value<'a>(h: &'a str, key: &str) -> Option<&'a str> {
    let i = h.find(&format!("'{}'", key))? + key.len() + 2;
    let rest = h[i..].trim_start().strip_prefix(':')?.trim_start();
    Some(rest)
}

pub fn parse_npy(b: &[u8]) -> Result<Arr, String> {
    if b.len() < 10 || &b[0..6] != b"\x93NUMPY" {
        return Err("npy 머리말이 아님".into());
    }
    let (hl, off) = if b[6] == 1 { (u16::from_le_bytes([b[8], b[9]]) as usize, 10) } else { (u32::from_le_bytes([b[8], b[9], b[10], b[11]]) as usize, 12) };
    let h = std::str::from_utf8(&b[off..off + hl]).map_err(|e| e.to_string())?;
    let descr = header_value(h, "descr").ok_or("descr 없음")?;
    let descr = &descr[1..descr[1..].find('\'').ok_or("descr 형식")? + 1];
    if header_value(h, "fortran_order").map(|s| s.starts_with("True")).unwrap_or(false) {
        return Err("fortran 순서는 지원하지 않음".into());
    }
    let sh = header_value(h, "shape").ok_or("shape 없음")?;
    let sh = &sh[1..sh.find(')').ok_or("shape 형식")?];
    let shape: Vec<usize> = sh.split(',').map(|s| s.trim()).filter(|s| !s.is_empty()).map(|s| s.parse().unwrap()).collect();
    let n: usize = shape.iter().product();
    let d = &b[off + hl..];
    let data = match descr {
        "|b1" => ArrData::Bool(d[..n].iter().map(|&x| x != 0).collect()),
        "|u1" => ArrData::U8(d[..n].to_vec()),
        "<f8" => ArrData::F64((0..n).map(|i| f64::from_le_bytes(d[i * 8..i * 8 + 8].try_into().unwrap())).collect()),
        "<i8" => ArrData::I64((0..n).map(|i| i64::from_le_bytes(d[i * 8..i * 8 + 8].try_into().unwrap())).collect()),
        o => return Err(format!("지원하지 않는 형식 {}", o)),
    };
    Ok(Arr { shape, data })
}

pub fn npy_bytes(a: &Arr) -> Vec<u8> {
    let descr = match a.data {
        ArrData::Bool(_) => "|b1",
        ArrData::U8(_) => "|u1",
        ArrData::F64(_) => "<f8",
        ArrData::I64(_) => "<i8",
    };
    let shape = if a.shape.len() == 1 { format!("({},)", a.shape[0]) } else { format!("({})", a.shape.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(", ")) };
    let mut h = format!("{{'descr': '{}', 'fortran_order': False, 'shape': {}, }}", descr, shape);
    while (10 + h.len() + 1) % 64 != 0 {
        h.push(' ');
    }
    h.push('\n');
    let mut out = b"\x93NUMPY\x01\x00".to_vec();
    out.extend_from_slice(&(h.len() as u16).to_le_bytes());
    out.extend_from_slice(h.as_bytes());
    match &a.data {
        ArrData::Bool(v) => out.extend(v.iter().map(|&x| x as u8)),
        ArrData::U8(v) => out.extend_from_slice(v),
        ArrData::F64(v) => v.iter().for_each(|x| out.extend_from_slice(&x.to_le_bytes())),
        ArrData::I64(v) => v.iter().for_each(|x| out.extend_from_slice(&x.to_le_bytes())),
    }
    out
}

pub fn read_npz(path: &str) -> Result<BTreeMap<String, Arr>, String> {
    let f = std::fs::File::open(path).map_err(|e| format!("{}: {}", path, e))?;
    let mut z = zip::ZipArchive::new(f).map_err(|e| e.to_string())?;
    let mut out = BTreeMap::new();
    for i in 0..z.len() {
        let mut e = z.by_index(i).map_err(|e| e.to_string())?;
        let name = e.name().map_err(|x| x.to_string())?.trim_end_matches(".npy").to_string();
        let mut buf = Vec::new();
        e.read_to_end(&mut buf).map_err(|e| e.to_string())?;
        out.insert(name, parse_npy(&buf)?);
    }
    Ok(out)
}

pub fn read_npy(path: &str) -> Result<Arr, String> {
    parse_npy(&std::fs::read(path).map_err(|e| format!("{}: {}", path, e))?)
}

pub fn write_npy(path: &str, a: &Arr) -> Result<(), String> {
    std::fs::File::create(path).and_then(|mut f| f.write_all(&npy_bytes(a))).map_err(|e| e.to_string())
}

/// npz 쓰기(무압축 zip). numpy.load 로 읽힌다.
pub fn write_npz(path: &str, items: &[(String, Arr)]) -> Result<(), String> {
    let f = std::fs::File::create(path).map_err(|e| format!("{}: {}", path, e))?;
    let mut z = zip::ZipWriter::new(f);
    let opt = zip::write::SimpleFileOptions::default().compression_method(zip::CompressionMethod::Stored);
    for (k, a) in items {
        z.start_file(format!("{}.npy", k), opt).map_err(|e| e.to_string())?;
        z.write_all(&npy_bytes(a)).map_err(|e| e.to_string())?;
    }
    z.finish().map_err(|e| e.to_string())?;
    Ok(())
}
