//! 복셀화와 재투영. 파이썬 harness/model_check.py 의 voxelize·project 를 같은 연산 순서로 옮겼다(칸 단위로 같아야 함).
use crate::frame::Frame;
use crate::grid::{arange, searchsorted, Grid3, Mask2};
use crate::mesh::Mesh;

/// 닫힌 메시 → 칸. X 방향 광선 홀짝. 반환 (칸, 원점 lo).
pub fn voxelize(m: &Mesh, voxel: f64) -> (Grid3<bool>, [f64; 3]) {
    let mut mn = [f64::INFINITY; 3];
    let mut mx = [f64::NEG_INFINITY; 3];
    for p in &m.v {
        for k in 0..3 {
            mn[k] = mn[k].min(p[k]);
            mx[k] = mx[k].max(p[k]);
        }
    }
    let lo = [mn[0] - 2.0 * voxel, mn[1] - 2.0 * voxel, mn[2] - 2.0 * voxel];
    let hi = [mx[0] + 2.0 * voxel, mx[1] + 2.0 * voxel, mx[2] + 2.0 * voxel];
    // 광선을 격자에서 조금 비켜 쏜다(파이썬판과 같은 값: 모서리를 지나 홀짝이 뒤집히는 것을 막음)
    let ys: Vec<f64> = arange(lo[1], hi[1], voxel).iter().map(|&y| y + voxel * 0.5 + voxel * 0.0137).collect();
    let zs: Vec<f64> = arange(lo[2], hi[2], voxel).iter().map(|&z| z + voxel * 0.5 + voxel * 0.0291).collect();
    let nx = ((hi[0] - lo[0]) / voxel).ceil() as usize;
    let (ny, nz) = (ys.len(), zs.len());
    let mut hits: Vec<Vec<f64>> = vec![Vec::new(); ny * nz];
    for t in &m.f {
        let (p0, p1, p2) = (m.v[t[0] as usize], m.v[t[1] as usize], m.v[t[2] as usize]);
        let (x0, y0, z0) = (p0[0], p0[1], p0[2]);
        let (x1, y1, z1) = (p1[0], p1[1], p1[2]);
        let (x2, y2, z2) = (p2[0], p2[1], p2[2]);
        let d = (y1 - y0) * (z2 - z0) - (y2 - y0) * (z1 - z0);
        if d.abs() < 1e-12 {
            continue;
        }
        let j0 = searchsorted(&ys, y0.min(y1).min(y2));
        let j1 = searchsorted(&ys, y0.max(y1).max(y2));
        let k0 = searchsorted(&zs, z0.min(z1).min(z2));
        let k1 = searchsorted(&zs, z0.max(z1).max(z2));
        if j1 <= j0 || k1 <= k0 {
            continue;
        }
        for j in j0..j1 {
            let gy = ys[j];
            for k in k0..k1 {
                let gz = zs[k];
                let a = ((gy - y0) * (z2 - z0) - (y2 - y0) * (gz - z0)) / d;
                let b = ((y1 - y0) * (gz - z0) - (gy - y0) * (z1 - z0)) / d;
                if a >= 0.0 && b >= 0.0 && a + b < 1.0 {
                    hits[j * nz + k].push(x0 + a * (x1 - x0) + b * (x2 - x0));
                }
            }
        }
    }
    let mut occ = Grid3::<bool>::new([nx, ny, nz]);
    for j in 0..ny {
        for k in 0..nz {
            let xl = &mut hits[j * nz + k];
            if xl.len() < 2 {
                continue;
            }
            xl.sort_by(|a, b| a.partial_cmp(b).unwrap());
            for pr in xl.chunks_exact(2) {
                let i0 = ((pr[0] - lo[0]) / voxel - 0.5).ceil() as i64;
                let i1 = ((pr[1] - lo[0]) / voxel - 0.5).floor() as i64;
                if i1 >= i0 {
                    for i in i0.max(0)..=i1.min(nx as i64 - 1) {
                        occ.set(i as usize, j, k, true);
                    }
                }
            }
        }
    }
    (occ, lo)
}

/// 칸 → 도면 마스크(정사영, 투영 v2: 파이썬 model_check.project 와 같은 식).
/// 칸 기둥의 사각 발자국이 픽셀을 덮는 넓이를 더해 절반 이상이면 칠한다. v1(3x3 점)은 칸 ≈ 1px 에서 가장자리를 부풀렸다(수정_기록 47·48).
pub fn project(occ: &Grid3<bool>, lo: [f64; 3], voxel: f64, fr: &Frame, view: &str, h: usize, w: usize) -> Mask2 {
    let front = view == "front" || view == "back";
    let [nx, ny, nz] = occ.n;
    let nl = if front { nx } else { ny };
    let mut sil = vec![false; nl * nz];
    for x in 0..nx {
        for y in 0..ny {
            for z in 0..nz {
                if occ.get(x, y, z) {
                    sil[(if front { x } else { y }) * nz + z] = true;
                }
            }
        }
    }
    let lat0 = if front { lo[0] } else { lo[1] };
    // 파이썬과 같은 순서로 더한다: 칸 목록(가로칸 → 높이칸) 을 오프셋(dx, dy) 마다 한 바퀴씩
    let cells: Vec<(f64, f64, f64, f64)> = (0..nl)
        .flat_map(|li| (0..nz).map(move |zi| (li, zi)))
        .filter(|&(li, zi)| sil[li * nz + zi])
        .map(|(li, zi)| {
            let (xa, ya) = fr.h_to_px(view, lat0 + li as f64 * voxel, lo[2] + zi as f64 * voxel);
            let (xb, yb) = fr.h_to_px(view, lat0 + (li + 1) as f64 * voxel, lo[2] + (zi + 1) as f64 * voxel);
            (xa.min(xb), xa.max(xb), ya.min(yb), ya.max(yb))
        })
        .collect();
    let mut cov = vec![0.0f64; h * w];
    let k = cells.iter().map(|c| c.1 - c.0).fold(0.0f64, f64::max);
    let k = if cells.is_empty() { 2 } else { k.ceil() as i64 + 1 };
    for dx in 0..k {
        for dy in 0..k {
            for &(x0, x1, y0, y1) in &cells {
                let c = x0.floor() as i64 + dx;
                let r = y0.floor() as i64 + dy;
                let ox = x1.min((c + 1) as f64) - x0.max(c as f64);
                let oy = y1.min((r + 1) as f64) - y0.max(r as f64);
                if ox > 0.0 && oy > 0.0 && r >= 0 && (r as usize) < h && c >= 0 && (c as usize) < w {
                    cov[r as usize * w + c as usize] += ox * oy;
                }
            }
        }
    }
    Mask2 { h, w, d: cov.iter().map(|&v| v >= 0.5 - 1e-9).collect() }
}
