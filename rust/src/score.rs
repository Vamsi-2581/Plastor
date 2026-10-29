//! 추적(docs/추적_체계.md): R-032
//! 채점기(파이썬 bench/m0.py score + harness/metrics.py 를 같은 식으로). 합성은 3D 정답 도형(타원체 목록), 실제는 트레이스 대비.
//! 항목: 실루엣 IoU, 부피 IoU, 몸 수, 거칠기 v2, 3/4 폭 비, 부위별 실루엣(가려진 픽셀 제외)·부피·3/4 폭 비, 랜드마크 잔차.
use crate::frame::Frame;
use crate::grid::{iou, Grid3, Mask2};
use crate::mesh::{load_obj, Mesh};
use crate::voxel::{project, voxelize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap};

#[derive(Clone, Debug)]
pub struct Prim {
    pub c: [f64; 3],
    pub r: [f64; 3],
    pub part: String,
}

pub fn load_prims(path: &str) -> Result<Vec<Prim>, String> {
    let v: Value = serde_json::from_str(&std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?).map_err(|e| e.to_string())?;
    let arr = v.as_array().ok_or("prims 는 목록")?;
    Ok(arr
        .iter()
        .map(|p| {
            let f = |k: &str| {
                let a = p[k].as_array().unwrap();
                [a[0].as_f64().unwrap(), a[1].as_f64().unwrap(), a[2].as_f64().unwrap()]
            };
            Prim { c: f("c"), r: f("r"), part: p["part"].as_str().unwrap_or("").to_string() }
        })
        .collect())
}

/// 연결 조각(면이 공유하는 정점 번호)마다 따로 복셀화해 합친다(파이썬 m0._voxelize_parts 와 같음).
pub fn voxelize_parts(m: &Mesh, voxel: f64) -> (Grid3<bool>, [f64; 3]) {
    let n = m.v.len();
    let mut par: Vec<usize> = (0..n).collect();
    fn find(p: &mut Vec<usize>, mut a: usize) -> usize {
        while p[a] != a {
            p[a] = p[p[a]];
            a = p[a];
        }
        a
    }
    for f in &m.f {
        let r: Vec<usize> = f.iter().map(|&x| find(&mut par, x as usize)).collect();
        for &x in &r[1..] {
            par[x] = r[0];
        }
    }
    let lab: Vec<usize> = m.f.iter().map(|f| find(&mut par, f[0] as usize)).collect();
    let mut mn = [f64::INFINITY; 3];
    let mut mx = [f64::NEG_INFINITY; 3];
    for p in &m.v {
        for k in 0..3 {
            mn[k] = mn[k].min(p[k]);
            mx[k] = mx[k].max(p[k]);
        }
    }
    let lo = [mn[0] - 2.0 * voxel, mn[1] - 2.0 * voxel, mn[2] - 2.0 * voxel];
    let shape = [0, 1, 2].map(|k| ((mx[k] + 2.0 * voxel - lo[k]) / voxel).ceil() as usize + 1);
    let mut occ = Grid3::<bool>::new(shape);
    let mut groups: BTreeMap<usize, Vec<[u32; 3]>> = BTreeMap::new();
    for (f, &l) in m.f.iter().zip(&lab) {
        groups.entry(l).or_default().push(*f);
    }
    for (_, fs) in groups {
        let sub = Mesh { v: m.v.clone(), f: fs };
        let (o, l) = voxelize_sub(&sub, voxel);
        let s = [0, 1, 2].map(|k| ((l[k] - lo[k]) / voxel).round() as i64);
        for x in 0..o.n[0] {
            for y in 0..o.n[1] {
                for z in 0..o.n[2] {
                    if o.get(x, y, z) {
                        let (a, b, c) = (x as i64 + s[0], y as i64 + s[1], z as i64 + s[2]);
                        if a >= 0 && b >= 0 && c >= 0 && (a as usize) < shape[0] && (b as usize) < shape[1] && (c as usize) < shape[2] {
                            occ.set(a as usize, b as usize, c as usize, true);
                        }
                    }
                }
            }
        }
    }
    (occ, lo)
}

/// 쓰이는 정점만으로 범위를 잡아 복셀화(파이썬은 조각 F 만 넘겨도 V 전체 min/max 를 써서 같다 → 그대로 V 전체).
fn voxelize_sub(m: &Mesh, voxel: f64) -> (Grid3<bool>, [f64; 3]) {
    voxelize(m, voxel)
}

/// 정답 칸(타원체 합집합, names 의 부위만) — 칸 중심 lo + (i+0.5)*voxel.
pub fn gt_occ(prims: &[Prim], names: &[&str], lo: [f64; 3], shape: [usize; 3], voxel: f64) -> Grid3<bool> {
    let mut g = Grid3::<bool>::new(shape);
    for p in prims.iter().filter(|p| names.contains(&p.part.as_str())) {
        let a = [0, 1, 2].map(|k| (((p.c[k] - p.r[k] - lo[k]) / voxel - 1.0).floor().max(0.0)) as usize);
        let b = [0, 1, 2].map(|k| ((((p.c[k] + p.r[k] - lo[k]) / voxel + 1.0).ceil()) as usize).min(shape[k]));
        for x in a[0]..b[0] {
            for y in a[1]..b[1] {
                for z in a[2]..b[2] {
                    let q = [x, y, z];
                    let s: f64 = (0..3).map(|k| { let d = (lo[k] + (q[k] as f64 + 0.5) * voxel - p.c[k]) / p.r[k]; d * d }).sum();
                    if s <= 1.0 {
                        g.set(x, y, z, true);
                    }
                }
            }
        }
    }
    g
}

/// 모델 칸과 정답을 함께 담는 격자(파이썬 metrics.common_grid). 반환 (모델, 정답, 원점).
pub fn common_grid(occ: &Grid3<bool>, lo: [f64; 3], prims: &[Prim], names: &[&str], voxel: f64) -> (Grid3<bool>, Grid3<bool>, [f64; 3]) {
    let q: Vec<&Prim> = prims.iter().filter(|p| names.contains(&p.part.as_str())).collect();
    let mut glo = [0.0; 3];
    let mut ghi = [0.0; 3];
    for k in 0..3 {
        let pmin = q.iter().map(|p| p.c[k] - p.r[k]).fold(f64::INFINITY, f64::min);
        let pmax = q.iter().map(|p| p.c[k] + p.r[k]).fold(f64::NEG_INFINITY, f64::max);
        glo[k] = lo[k].min(pmin) - 2.0 * voxel;
        ghi[k] = (lo[k] + occ.n[k] as f64 * voxel).max(pmax) + 2.0 * voxel;
    }
    let gs = [0, 1, 2].map(|k| ((ghi[k] - glo[k]) / voxel).ceil() as usize);
    let mut mine = Grid3::<bool>::new(gs);
    let o = [0, 1, 2].map(|k| ((lo[k] - glo[k]) / voxel).round() as usize);
    for x in 0..occ.n[0] {
        for y in 0..occ.n[1] {
            for z in 0..occ.n[2] {
                if occ.get(x, y, z) && x + o[0] < gs[0] && y + o[1] < gs[1] && z + o[2] < gs[2] {
                    mine.set(x + o[0], y + o[1], z + o[2], true);
                }
            }
        }
    }
    let gt = gt_occ(prims, names, glo, gs, voxel);
    (mine, gt, glo)
}

pub fn vol_iou(a: &Grid3<bool>, b: &Grid3<bool>) -> f64 {
    let (mut i, mut u) = (0usize, 0usize);
    for (x, y) in a.d.iter().zip(&b.d) {
        i += (*x && *y) as usize;
        u += (*x || *y) as usize;
    }
    i as f64 / u.max(1) as f64
}

/// 3/4 폭 비(파이썬 metrics.quarter_ratio).
pub fn quarter_ratio(occ: &Grid3<bool>, min_cells: usize) -> Option<f64> {
    let mut r = Vec::new();
    for z in 0..occ.n[2] {
        let (mut x0, mut x1, mut y0, mut y1, mut u0, mut u1, mut cnt) = (usize::MAX, 0, usize::MAX, 0, f64::INFINITY, f64::NEG_INFINITY, 0);
        for x in 0..occ.n[0] {
            for y in 0..occ.n[1] {
                if occ.get(x, y, z) {
                    cnt += 1;
                    x0 = x0.min(x);
                    x1 = x1.max(x);
                    y0 = y0.min(y);
                    y1 = y1.max(y);
                    let u = (x + y) as f64 / 2f64.sqrt();
                    u0 = u0.min(u);
                    u1 = u1.max(u);
                }
            }
        }
        if cnt < min_cells {
            continue;
        }
        let (wx, wy) = ((x1 - x0 + 1) as f64, (y1 - y0 + 1) as f64);
        r.push((u1 - u0 + 2f64.sqrt()) / ((wx + wy) / 2f64.sqrt()));
    }
    median(&mut r)
}

fn median(v: &mut Vec<f64>) -> Option<f64> {
    if v.is_empty() {
        return None;
    }
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    Some(if n % 2 == 1 { v[n / 2] } else { (v[n / 2 - 1] + v[n / 2]) / 2.0 })
}

/// 거칠기 v2(파이썬 metrics.roughness_v2): 반경 안 면들의 넓이 가중 평균 법선과의 각, 넓이 가중 평균. 이웃 찾기는 칸 해시.
pub fn roughness_v2(m: &Mesh, radius: f64) -> f64 {
    let nf = m.f.len();
    let mut nrm = vec![[0.0; 3]; nf];
    let mut area = vec![0.0; nf];
    let mut cen = vec![[0.0; 3]; nf];
    for (i, f) in m.f.iter().enumerate() {
        let (a, b, c) = (m.v[f[0] as usize], m.v[f[1] as usize], m.v[f[2] as usize]);
        let u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
        let w = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
        let n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
        let l = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
        area[i] = l;
        let d = l.max(1e-12);
        nrm[i] = [n[0] / d, n[1] / d, n[2] / d];
        cen[i] = [0, 1, 2].map(|k| (a[k] + b[k] + c[k]) / 3.0);
    }
    let key = |p: &[f64; 3]| [0, 1, 2].map(|k| (p[k] / radius).floor() as i64);
    let mut cells: HashMap<[i64; 3], Vec<usize>> = HashMap::new();
    for (i, c) in cen.iter().enumerate() {
        cells.entry(key(c)).or_default().push(i);
    }
    let (mut num, mut den) = (0.0, 0.0);
    let r2 = radius * radius;
    for i in 0..nf {
        let k = key(&cen[i]);
        let mut s = [0.0; 3];
        for dx in -1..=1 {
            for dy in -1..=1 {
                for dz in -1..=1 {
                    if let Some(v) = cells.get(&[k[0] + dx, k[1] + dy, k[2] + dz]) {
                        for &j in v {
                            let d2: f64 = (0..3).map(|q| (cen[j][q] - cen[i][q]).powi(2)).sum();
                            if d2 <= r2 {
                                for q in 0..3 {
                                    s[q] += nrm[j][q] * area[j];
                                }
                            }
                        }
                    }
                }
            }
        }
        let l = (s[0] * s[0] + s[1] * s[1] + s[2] * s[2]).sqrt().max(1e-12);
        let dot = (nrm[i][0] * s[0] + nrm[i][1] * s[1] + nrm[i][2] * s[2]) / l;
        num += dot.clamp(-1.0, 1.0).acos().to_degrees() * area[i];
        den += area[i];
    }
    num / den.max(1e-12)
}

/// 몸 수: 같은 자리 정점을 합친 뒤 변을 공유하는 면끼리 이은 조각 수(trimesh split 과 같은 뜻, 면 둘이 공유하는 변만).
pub fn body_count(m: &Mesh) -> usize {
    let mut id: HashMap<[i64; 3], usize> = HashMap::new();
    let vid: Vec<usize> = m.v.iter().map(|p| { let k = p.map(|x| (x * 1e8).round() as i64); let n = id.len(); *id.entry(k).or_insert(n) }).collect();
    let nf = m.f.len();
    let mut par: Vec<usize> = (0..nf).collect();
    fn find(p: &mut Vec<usize>, mut a: usize) -> usize {
        while p[a] != a {
            p[a] = p[p[a]];
            a = p[a];
        }
        a
    }
    // trimesh 와 같게: 정확히 면 둘이 공유하는 변만 이웃으로 친다(면 셋 이상이 공유하는 비다양체 변은 잇지 않음)
    let mut edge: HashMap<(usize, usize), Vec<usize>> = HashMap::new();
    for (i, f) in m.f.iter().enumerate() {
        let v = [vid[f[0] as usize], vid[f[1] as usize], vid[f[2] as usize]];
        if v[0] == v[1] || v[1] == v[2] || v[0] == v[2] {
            continue;
        }
        for (a, b) in [(v[0], v[1]), (v[1], v[2]), (v[2], v[0])] {
            edge.entry(if a < b { (a, b) } else { (b, a) }).or_default().push(i);
        }
    }
    for fs in edge.values() {
        if fs.len() == 2 {
            let (ri, rj) = (find(&mut par, fs[0]), find(&mut par, fs[1]));
            par[ri] = rj;
        }
    }
    let mut roots = std::collections::HashSet::new();
    for (i, f) in m.f.iter().enumerate() {
        let v = [vid[f[0] as usize], vid[f[1] as usize], vid[f[2] as usize]];
        if v[0] == v[1] || v[1] == v[2] || v[0] == v[2] {
            continue;
        }
        roots.insert(find(&mut par, i));
    }
    roots.len()
}

fn cell_points(o: &Grid3<bool>, lo: [f64; 3], voxel: f64) -> Vec<[f64; 3]> {
    let mut p = Vec::new();
    for x in 0..o.n[0] {
        for y in 0..o.n[1] {
            for z in 0..o.n[2] {
                if o.get(x, y, z) {
                    p.push([lo[0] + (x as f64 + 0.5) * voxel, lo[1] + (y as f64 + 0.5) * voxel, lo[2] + (z as f64 + 0.5) * voxel]);
                }
            }
        }
    }
    p
}

fn mean(p: &[[f64; 3]]) -> [f64; 3] {
    let n = p.len().max(1) as f64;
    [0, 1, 2].map(|k| p.iter().map(|q| q[k]).sum::<f64>() / n)
}

/// 랜드마크(파이썬 metrics.landmarks): 코끝 = Y 최대 근처(0.015) 평균, 정수리 = Z 최대 근처, 뿔끝 = X 양·음 쪽에서 머리 중심에서 가장 먼 근처.
pub fn landmarks(head: &[[f64; 3]], horn: Option<&[[f64; 3]]>) -> BTreeMap<String, [f64; 3]> {
    let mut out = BTreeMap::new();
    if head.is_empty() {
        return out;
    }
    for (name, k) in [("코끝", 1usize), ("정수리", 2)] {
        let m = head.iter().map(|p| p[k]).fold(f64::NEG_INFINITY, f64::max);
        let sel: Vec<[f64; 3]> = head.iter().filter(|p| p[k] >= m - 0.015).cloned().collect();
        out.insert(name.to_string(), mean(&sel));
    }
    let hc = mean(head);
    if let Some(h) = horn {
        for (name, side) in [("뿔끝_오른", 1.0), ("뿔끝_왼", -1.0)] {
            let q: Vec<[f64; 3]> = h.iter().filter(|p| side * p[0] > 0.0).cloned().collect();
            if q.is_empty() {
                continue;
            }
            let d: Vec<f64> = q.iter().map(|p| ((p[0] - hc[0]).powi(2) + (p[1] - hc[1]).powi(2) + (p[2] - hc[2]).powi(2)).sqrt()).collect();
            let dm = d.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
            let sel: Vec<[f64; 3]> = q.iter().zip(&d).filter(|(_, &x)| x >= dm - 0.015).map(|(p, _)| *p).collect();
            out.insert(name.to_string(), mean(&sel));
        }
    }
    out
}

fn r4(x: f64) -> f64 {
    (x * 1e4).round() / 1e4
}

pub const GROUPS: [(&str, &[&str]); 4] = [("머리", &["머리"]), ("뿔", &["뿔", "뿔 밑동"]), ("귀", &["귀"]), ("갈기", &["갈기"])];

fn concat(meshes: &[Mesh]) -> Mesh {
    let mut v = Vec::new();
    let mut f = Vec::new();
    for m in meshes {
        let off = v.len() as u32;
        v.extend_from_slice(&m.v);
        f.extend(m.f.iter().map(|t| [t[0] + off, t[1] + off, t[2] + off]));
    }
    Mesh { v, f }
}

/// 채점. truth: 뷰·부위 마스크(합성은 목 포함 전체, 실제는 트레이스). prims: 합성 정답(실제는 None). ref_parts: 전체 실루엣에 넣을 부위(None = 전부).
pub fn score(fr: &Frame, obj: &str, truth: &BTreeMap<(String, String), Mask2>, prims: Option<&[Prim]>, ref_parts: Option<&[&str]>) -> Result<Value, String> {
    let m = load_obj(obj)?;
    // 채점 칸 0.5px(0.003~0.005H), 파이썬 bench/m0.py 와 같음(수정_기록 49)
    let voxel = (0.5 / fr.pp_h).max(0.003).min(0.005);
    let (occ, lo) = voxelize_parts(&m, voxel);
    let (h, w) = truth.values().next().map(|x| (x.h, x.w)).ok_or("마스크 없음")?;
    let mut row = json!({"실루엣": {}, "복셀": r4(voxel * 1e1) / 1e1});
    row["복셀"] = json!((voxel * 1e5).round() / 1e5);
    for v in ["front", "side"] {
        let mut r = Mask2::new(h, w);
        for ((vv, p), mm) in truth {
            if vv == v && ref_parts.map(|ps| ps.contains(&p.as_str())).unwrap_or(true) {
                for (a, b) in r.d.iter_mut().zip(&mm.d) {
                    *a |= *b;
                }
            }
        }
        if r.count() > 0 {
            row["실루엣"][v] = json!(r4(iou(&project(&occ, lo, voxel, fr, v, h, w), &r)));
        }
    }
    if let Some(p) = prims {
        let names: Vec<&str> = p.iter().map(|q| q.part.as_str()).collect::<std::collections::BTreeSet<_>>().into_iter().collect();
        let (a, b, _) = common_grid(&occ, lo, p, &names, voxel);
        row["부피"] = json!(r4(vol_iou(&a, &b)));
    } else {
        row["부피"] = json!("UNKNOWN");
    }
    row["몸_수"] = json!(body_count(&m));
    row["거칠기"] = json!((roughness_v2(&m, 0.03) * 100.0).round() / 100.0);
    row["3/4폭비"] = json!(quarter_ratio(&occ, 12).map(r4));
    // 부위(결과 폴더의 body.obj = 머리, part_<이름>.obj)
    let dir = std::path::Path::new(obj).parent().map(|d| d.to_path_buf()).unwrap_or_default();
    let mut parts = serde_json::Map::new();
    let mut occs: BTreeMap<&str, (Grid3<bool>, [f64; 3])> = BTreeMap::new();
    for (g, names) in GROUPS.iter() {
        let files: Vec<String> = if *g == "머리" { vec!["body.obj".into()] } else { names.iter().map(|n| format!("part_{}.obj", n)).collect() };
        let ms: Vec<Mesh> = files.iter().filter_map(|f| { let p = dir.join(f); if p.exists() { load_obj(p.to_str().unwrap()).ok() } else { None } }).collect();
        if ms.is_empty() {
            continue;
        }
        let (o, l) = voxelize_parts(&concat(&ms), voxel);
        let mut e = json!({"실루엣": {}});
        for v in ["front", "side"] {
            let mut r = Mask2::new(h, w);
            let mut dc = Mask2::new(h, w);
            for ((vv, p), mm) in truth {
                if vv != v {
                    continue;
                }
                let tgt = if names.contains(&p.as_str()) { &mut r } else { &mut dc };
                for (a, b) in tgt.d.iter_mut().zip(&mm.d) {
                    *a |= *b;
                }
            }
            if r.count() > 0 {
                let pm = project(&o, l, voxel, fr, v, h, w);
                let (mut i, mut u) = (0usize, 0usize);
                for k in 0..pm.d.len() {
                    let keep = !dc.d[k] || r.d[k];
                    let (a, b) = (pm.d[k] && keep, r.d[k] && keep);
                    i += (a && b) as usize;
                    u += (a || b) as usize;
                }
                e["실루엣"][v] = json!(r4(i as f64 / u.max(1) as f64));
            }
        }
        if let Some(p) = prims {
            if p.iter().any(|q| names.contains(&q.part.as_str())) {
                let (a, b, _) = common_grid(&o, l, p, names, voxel);
                e["부피"] = json!(r4(vol_iou(&a, &b)));
            }
        }
        e["3/4폭비"] = json!(quarter_ratio(&o, 12).map(r4));
        parts.insert(g.to_string(), e);
        occs.insert(g, (o, l));
    }
    if parts.is_empty() {
        row["부위"] = json!("UNKNOWN(부위 메시 없음)");
        return Ok(row);
    }
    row["부위"] = Value::Object(parts);
    if let Some((ho, hl)) = occs.get("머리") {
        let hp = cell_points(ho, *hl, voxel);
        let horn = occs.get("뿔").map(|(o, l)| cell_points(o, *l, voxel));
        let model = landmarks(&hp, horn.as_deref());
        let mut res = serde_json::Map::new();
        if let Some(p) = prims {
            let (_, gh, glo) = common_grid(ho, *hl, p, &["머리"], voxel);
            let th = cell_points(&gh, glo, voxel);
            let tn = match occs.get("뿔") {
                Some((o, l)) if p.iter().any(|q| q.part == "뿔" || q.part == "뿔 밑동") => {
                    let (_, gn, gl) = common_grid(o, *l, p, &["뿔", "뿔 밑동"], voxel);
                    Some(cell_points(&gn, gl, voxel))
                }
                _ => None,
            };
            let t = landmarks(&th, tn.as_deref());
            for (k, a) in &model {
                if let Some(b) = t.get(k) {
                    res.insert(k.clone(), json!(r4(((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt())));
                }
            }
        } else if let Some(mk) = truth.get(&("side".to_string(), "머리".to_string())) {
            let pj = project(ho, *hl, voxel, fr, "side", h, w);
            let tip = |mask: &Mask2| -> Option<(f64, f64)> {
                let cols: Vec<usize> = (0..w).filter(|&c| (0..h).any(|r| mask.get(r, c))).collect();
                if cols.is_empty() {
                    return None;
                }
                let c0 = if fr.panels["side"].sign < 0.0 { cols[0] } else { *cols.last().unwrap() };
                let rows: Vec<usize> = (0..h).filter(|&r| mask.get(r, c0)).collect();
                let rm = rows.iter().sum::<usize>() as f64 / rows.len() as f64;
                Some(fr.px_to_h("side", c0 as f64 + 0.5, rm + 0.5))
            };
            if let (Some(a), Some(b)) = (tip(&pj), tip(mk)) {
                res.insert("코끝(옆 2D)".into(), json!(r4(((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt())));
            }
        }
        row["랜드마크_잔차"] = Value::Object(res);
    }
    Ok(row)
}
