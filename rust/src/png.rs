//! PNG 쓰기(RGB 8비트). 압축 크레이트 없이: zlib '저장(무압축)' 블록 + Adler-32 + CRC-32.
//! 파일은 커지지만(원본 크기 + 약간) 그림 확인·LLM 에게 보여 주기에는 충분하다. Blender 로 PNG 를 쓰던 의존(bench/npy2png.py)을 없앤다.
use std::io::Write;

fn crc32(data: &[u8]) -> u32 {
    let mut table = [0u32; 256];
    for i in 0..256u32 {
        let mut c = i;
        for _ in 0..8 {
            c = if c & 1 != 0 { 0xEDB8_8320 ^ (c >> 1) } else { c >> 1 };
        }
        table[i as usize] = c;
    }
    let mut c = 0xFFFF_FFFFu32;
    for &b in data {
        c = table[((c ^ b as u32) & 0xFF) as usize] ^ (c >> 8);
    }
    c ^ 0xFFFF_FFFF
}

fn adler32(data: &[u8]) -> u32 {
    let (mut a, mut b) = (1u32, 0u32);
    for chunk in data.chunks(5552) {
        for &x in chunk {
            a += x as u32;
            b += a;
        }
        a %= 65521;
        b %= 65521;
    }
    (b << 16) | a
}

fn chunk(out: &mut Vec<u8>, kind: &[u8], data: &[u8]) {
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    let mut c = kind.to_vec();
    c.extend_from_slice(data);
    out.extend_from_slice(&c);
    out.extend_from_slice(&crc32(&c).to_be_bytes());
}

/// rgb: 행 우선(위 행부터), 화소마다 R,G,B.
pub fn write_rgb(path: &str, w: usize, h: usize, rgb: &[u8]) -> Result<(), String> {
    if rgb.len() != w * h * 3 {
        return Err(format!("화소 수가 맞지 않음 {} != {}x{}x3", rgb.len(), w, h));
    }
    let mut raw = Vec::with_capacity(h * (w * 3 + 1));
    for r in 0..h {
        raw.push(0u8); // 줄마다 필터 없음
        raw.extend_from_slice(&rgb[r * w * 3..(r + 1) * w * 3]);
    }
    let mut z = vec![0x78u8, 0x01];
    let n = raw.len();
    let mut i = 0;
    while i < n || n == 0 {
        let len = (n - i).min(65535);
        z.push(if i + len >= n { 1 } else { 0 });
        z.extend_from_slice(&(len as u16).to_le_bytes());
        z.extend_from_slice(&(!(len as u16)).to_le_bytes());
        z.extend_from_slice(&raw[i..i + len]);
        i += len;
        if n == 0 {
            break;
        }
    }
    z.extend_from_slice(&adler32(&raw).to_be_bytes());
    let mut out = b"\x89PNG\r\n\x1a\n".to_vec();
    let mut ihdr = Vec::new();
    ihdr.extend_from_slice(&(w as u32).to_be_bytes());
    ihdr.extend_from_slice(&(h as u32).to_be_bytes());
    ihdr.extend_from_slice(&[8, 2, 0, 0, 0]); // 8비트, RGB
    chunk(&mut out, b"IHDR", &ihdr);
    chunk(&mut out, b"IDAT", &z);
    chunk(&mut out, b"IEND", &[]);
    std::fs::File::create(path).and_then(|mut f| f.write_all(&out)).map_err(|e| format!("{}: {}", path, e))
}
