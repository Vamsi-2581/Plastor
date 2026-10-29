//! 부위 비주얼 헐(파이썬 harness/hull.py build_hull·section_fill 을 같은 식으로).
//! 정면 실루엣을 앞뒤(Y)로, 옆 실루엣을 좌우(X)로 밀어 겹친 부피. section_n 을 주면 높이별 단면을 직사각형 대신
//! 꽉 찬 초타원으로 채운다(정면·옆 폭은 같아 실루엣은 그대로, M0 부피 개선 시도).
use crate::frame::Frame;
use crate::grid::{arange, gaussian3, Grid3, Mask2};
use crate::mesh::{marching_tets, signed_volume, Mesh};
use serde_json::{json, Value};

pub struct HullOpt {
    pub voxel: f64,
    pub smooth: f64,
    pub master_front: bool,
    pub section_n: Option<f64>,
}

fn runs(a: &[bool]) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut s: Option<usize> = None;
    for (i, &x) in a.iter().chain(std::iter::once(&false)).enumerate() {
        match (x, s) {
            (true, None) => s = Some(i),
            (false, Some(b)) => {
                out.push((b, i - 1));
                s = None
            }
            _ => {}
        }
    }
    out
}

/// inf[x][z], ins[y][z] → 칸. n 이 None 이면 직사각형(두 뷰 곱).
pub fn fill(inf: &[Vec<bool>], ins: &[Vec<bool>], nz: usize, n: Option<f64>) -> Grid3<bool> {
    let (nx, ny) = (inf.len(), ins.len());
    let mut vol = Grid3::<bool>::new([nx, ny, nz]);
    for z in 0..nz {
        let col_f: Vec<bool> = (0..nx).map(|x| inf[x][z]).collect();
        let col_s: Vec<bool> = (0..ny).map(|y| ins[y][z]).collect();
        match n {
            None => {
                for x in 0..nx {
                    if col_f[x] {
                        for y in 0..ny {
                            if col_s[y] {
                                vol.set(x, y, z, true);
                            }
                        }
                    }
                }
            }
            Some(n) => {
                for (x0, x1) in runs(&col_f) {
                    for (y0, y1) in runs(&col_s) {
                        let (cx, cy) = ((x0 + x1) as f64 / 2.0, (y0 + y1) as f64 / 2.0);
                        let (rx, ry) = ((x1 - x0 + 1) as f64 / 2.0, (y1 - y0 + 1) as f64 / 2.0);
                        let (ya, yb) = ((cy - y0 as f64).floor() as usize, (cy - y0 as f64).ceil() as usize);
                        let (xa, xb) = ((cx - x0 as f64).floor() as usize, (cx - x0 as f64).ceil() as usize);
                        for x in x0..=x1 {
                            let u = ((x as f64 - cx) / rx).abs().powf(n);
                            for y in y0..=y1 {
                                let v = ((y as f64 - cy) / ry).abs().powf(n);
                                let (ix, iy) = (x - x0, y - y0);
                                if u + v <= 1.0 || (iy >= ya && iy <= yb) || (ix >= xa && ix <= xb) {
                                    vol.set(x, y, z, true);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    vol
}

/// 헐 격자 축과 두 뷰 판정표. 반환 (inf[x][z], ins[y][z], xs, ys, zs, 빌린 높이 칸 수).
pub fn hull_axes(fr: &Frame, mf: &Mask2, ms: &Mask2, o: &HullOpt) -> Result<(Vec<Vec<bool>>, Vec<Vec<bool>>, Vec<f64>, Vec<f64>, Vec<f64>, usize), String> {
    let v = o.voxel;
    let pts = |m: &Mask2, view: &str| -> Vec<(f64, f64)> {
        let mut p = Vec::new();
        for r in 0..m.h {
            for c in 0..m.w {
                if m.get(r, c) {
                    p.push(fr.px_to_h(view, c as f64 + 0.5, r as f64 + 0.5));
                }
            }
        }
        p
    };
    let (pf, ps) = (pts(mf, "front"), pts(ms, "side"));
    if pf.is_empty() || ps.is_empty() {
        return Err("한 뷰에 부위가 없음".into());
    }
    let mm = |p: &Vec<(f64, f64)>, k: usize| {
        let it = p.iter().map(|q| if k == 0 { q.0 } else { q.1 });
        (it.clone().fold(f64::INFINITY, f64::min), it.fold(f64::NEG_INFINITY, f64::max))
    };
    let pad = 3.0 * v;
    let ((xfa, xfb), (zfa, zfb)) = (mm(&pf, 0), mm(&pf, 1));
    let ((ysa, ysb), (zsa, zsb)) = (mm(&ps, 0), mm(&ps, 1));
    let xs = arange(xfa - pad, xfb + pad, v);
    let ys = arange(ysa - pad, ysb + pad, v);
    let zs = if o.master_front { arange(zfa - pad, zfb + pad, v) } else { arange(zfa.max(zsa) - pad, zfb.min(zsb) + pad, v) };
    if zs.len() < 3 {
        return Err("두 뷰 높이가 겹치지 않음".into());
    }
    let nz = zs.len();
    let inf: Vec<Vec<bool>> = xs.iter().map(|&x| zs.iter().map(|&z| { let (px, py) = fr.h_to_px("front", x, z); mf.lookup(px, py) }).collect()).collect();
    let mut ins: Vec<Vec<bool>> = ys.iter().map(|&y| zs.iter().map(|&z| { let (px, py) = fr.h_to_px("side", y, z); ms.lookup(px, py) }).collect()).collect();
    let mut borrowed = 0;
    if o.master_front {
        // 옆 뷰에 없는 높이는 가장 가까운 옆 뷰 행의 앞뒤 폭을 빌린다(파이썬판과 같음)
        let has: Vec<bool> = (0..nz).map(|z| ins.iter().any(|c| c[z])).collect();
        let idx: Vec<usize> = (0..nz).filter(|&z| has[z]).collect();
        if !idx.is_empty() {
            for zi in 0..nz {
                if !has[zi] && inf.iter().any(|c| c[zi]) {
                    let src = *idx.iter().min_by_key(|&&i| (i as i64 - zi as i64).abs()).unwrap();
                    for c in ins.iter_mut() {
                        c[zi] = c[src];
                    }
                    borrowed += 1;
                }
            }
        }
    }
    Ok((inf, ins, xs, ys, zs, borrowed))
}

/// 반환 (메시, 정보). 마스크는 도면 전체 크기.
pub fn build_hull(fr: &Frame, mf: &Mask2, ms: &Mask2, o: &HullOpt) -> Result<(Mesh, Value), String> {
    let v = o.voxel;
    let (inf, ins, xs, ys, zs, borrowed) = hull_axes(fr, mf, ms, o)?;
    let nz = zs.len();
    let vol = fill(&inf, &ins, nz, o.section_n);
    let nvox = vol.d.iter().filter(|&&x| x).count();
    if nvox < 8 {
        return Err("헐이 비었음".into());
    }
    let [nx, ny, _] = vol.n;
    let mut f = Grid3::<f64>::new([nx, ny, nz]);
    for (i, &b) in vol.d.iter().enumerate() {
        f.d[i] = b as u8 as f64;
    }
    if o.smooth > 0.0 {
        f = gaussian3(&f, o.smooth);
    }
    let mut p = Grid3::<f64>::new([nx + 2, ny + 2, nz + 2]);
    for x in 0..nx {
        for y in 0..ny {
            for z in 0..nz {
                p.set(x + 1, y + 1, z + 1, f.get(x, y, z));
            }
        }
    }
    let mut m = marching_tets(&p, 0.5);
    for q in m.v.iter_mut() {
        *q = [xs[0] + (q[0] - 1.0) * v, ys[0] + (q[1] - 1.0) * v, zs[0] + (q[2] - 1.0) * v];
    }
    if signed_volume(&m) < 0.0 {
        for t in m.f.iter_mut() {
            t.swap(1, 2);
        }
    }
    let info = json!({"복셀": nvox, "정점": m.v.len(), "삼각형": m.f.len(), "옆폭_빌린_높이칸": borrowed});
    Ok((m, info))
}
