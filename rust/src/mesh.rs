//! 메시: OBJ 읽기·쓰기, 표면 뽑기(marching tetrahedra), 부호 부피.
//! 표면 뽑기는 skimage 의 Lewiner marching cubes 대신 정육면체를 사면체 6개(Kuhn 분할)로 나눠 뽑는다.
//! 큰 경우표 없이 맞게 짤 수 있고, 이웃 칸끼리 분할이 맞물려 닫힌 메시가 된다. 대신 삼각형이 더 많다.
use crate::grid::Grid3;
use std::collections::HashMap;
use std::io::Write;

pub struct Mesh {
    pub v: Vec<[f64; 3]>,
    pub f: Vec<[u32; 3]>,
}

pub fn load_obj(path: &str) -> Result<Mesh, String> {
    let s = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
    let (mut v, mut f) = (Vec::new(), Vec::new());
    for ln in s.lines() {
        if let Some(r) = ln.strip_prefix("v ") {
            let p: Vec<f64> = r.split_whitespace().take(3).map(|x| x.parse().unwrap_or(0.0)).collect();
            v.push([p[0], p[1], p[2]]);
        } else if let Some(r) = ln.strip_prefix("f ") {
            let idx: Vec<u32> = r.split_whitespace().map(|t| t.split('/').next().unwrap().parse::<u32>().unwrap() - 1).collect();
            for k in 1..idx.len() - 1 {
                f.push([idx[0], idx[k], idx[k + 1]]);
            }
        }
    }
    Ok(Mesh { v, f })
}

pub fn write_obj(path: &str, m: &Mesh) -> Result<(), String> {
    let mut out = String::with_capacity(m.v.len() * 40 + m.f.len() * 24);
    for p in &m.v {
        out.push_str(&format!("v {:.6} {:.6} {:.6}\n", p[0], p[1], p[2]));
    }
    for t in &m.f {
        out.push_str(&format!("f {} {} {}\n", t[0] + 1, t[1] + 1, t[2] + 1));
    }
    std::fs::File::create(path).and_then(|mut f| f.write_all(out.as_bytes())).map_err(|e| e.to_string())
}

pub fn signed_volume(m: &Mesh) -> f64 {
    m.f.iter()
        .map(|t| {
            let (a, b, c) = (m.v[t[0] as usize], m.v[t[1] as usize], m.v[t[2] as usize]);
            a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])
        })
        .sum::<f64>()
        / 6.0
}

/// 값 격자 g 에서 iso 를 넘는 쪽(안)의 겉면. 정점은 격자 칸 좌표(0..n-1)로 돌려준다. 면은 안 → 밖 방향.
pub fn marching_tets(g: &Grid3<f64>, iso: f64) -> Mesh {
    let n = g.n;
    // 정육면체 모서리 번호: 비트 0 = x, 1 = y, 2 = z
    const PERM: [[usize; 3]; 6] = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];
    let mut verts: Vec<[f64; 3]> = Vec::new();
    let mut faces: Vec<[u32; 3]> = Vec::new();
    let mut edge: HashMap<(usize, usize), u32> = HashMap::new();
    let lin = |p: [usize; 3]| (p[0] * n[1] + p[1]) * n[2] + p[2];
    for x in 0..n[0] - 1 {
        for y in 0..n[1] - 1 {
            for z in 0..n[2] - 1 {
                let corner = |b: usize| [x + (b & 1), y + ((b >> 1) & 1), z + ((b >> 2) & 1)];
                // 빠른 건너뛰기: 정육면체 8 꼭짓점이 모두 같은 쪽이면 면이 없다
                let mut cin = 0;
                for b in 0..8 {
                    let c = corner(b);
                    cin += (g.get(c[0], c[1], c[2]) > iso) as usize;
                }
                if cin == 0 || cin == 8 {
                    continue;
                }
                for p in PERM.iter() {
                    let b1 = 1 << p[0];
                    let b2 = b1 | (1 << p[1]);
                    let tet = [corner(0), corner(b1), corner(b2), corner(7)];
                    let val: Vec<f64> = tet.iter().map(|c| g.get(c[0], c[1], c[2])).collect();
                    let inside: Vec<usize> = (0..4).filter(|&i| val[i] > iso).collect();
                    let outside: Vec<usize> = (0..4).filter(|&i| val[i] <= iso).collect();
                    if inside.is_empty() || outside.is_empty() {
                        continue;
                    }
                    let mut vid = |a: usize, b: usize, verts: &mut Vec<[f64; 3]>| -> u32 {
                        let (ga, gb) = (lin(tet[a]), lin(tet[b]));
                        let t = (iso - val[a]) / (val[b] - val[a]);
                        // 경계가 격자점에 아주 가까우면(1e-4 칸) 그 격자점을 꼭짓점으로 공유한다. 이웃 변마다 따로 만들면
                        // 거의 같은 자리에 점이 여럿 생겨, 저장(소수 6자리) 뒤 합쳐지며 면 둘짜리 부스러기 72개가 생겼다(생성기 v2)
                        let (key, t) = if t < 1e-4 { ((ga, ga), 0.0) } else if t > 1.0 - 1e-4 { ((gb, gb), 1.0) } else { (if ga < gb { (ga, gb) } else { (gb, ga) }, t) };
                        if let Some(&i) = edge.get(&key) {
                            return i;
                        }
                        let pa = tet[a];
                        let pb = tet[b];
                        let q = [0, 1, 2].map(|k| pa[k] as f64 + t * (pb[k] as f64 - pa[k] as f64));
                        verts.push(q);
                        let i = (verts.len() - 1) as u32;
                        edge.insert(key, i);
                        i
                    };
                    let cen = |ids: &[usize]| {
                        let mut c = [0.0; 3];
                        for &i in ids {
                            for k in 0..3 {
                                c[k] += tet[i][k] as f64 / ids.len() as f64;
                            }
                        }
                        c
                    };
                    let dir = {
                        let (ci, co) = (cen(&inside), cen(&outside));
                        [co[0] - ci[0], co[1] - ci[1], co[2] - ci[2]]
                    };
                    let mut tris: Vec<[u32; 3]> = Vec::new();
                    if inside.len() == 1 || outside.len() == 1 {
                        let (one, rest) = if inside.len() == 1 { (inside[0], outside.clone()) } else { (outside[0], inside.clone()) };
                        tris.push([vid(one, rest[0], &mut verts), vid(one, rest[1], &mut verts), vid(one, rest[2], &mut verts)]);
                    } else {
                        let (i0, i1, o0, o1) = (inside[0], inside[1], outside[0], outside[1]);
                        let a = vid(i0, o0, &mut verts);
                        let b = vid(i0, o1, &mut verts);
                        let c = vid(i1, o1, &mut verts);
                        let d = vid(i1, o0, &mut verts);
                        tris.push([a, b, c]);
                        tris.push([a, c, d]);
                    }
                    for t in tris {
                        let (p0, p1, p2) = (verts[t[0] as usize], verts[t[1] as usize], verts[t[2] as usize]);
                        let u = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
                        let w = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];
                        let nrm = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]];
                        let dot = nrm[0] * dir[0] + nrm[1] * dir[1] + nrm[2] * dir[2];
                        if t[0] == t[1] || t[1] == t[2] || t[0] == t[2] {
                            continue;
                        }
                        faces.push(if dot >= 0.0 { t } else { [t[0], t[2], t[1]] });
                    }
                }
            }
        }
    }
    Mesh { v: verts, f: faces }
}
