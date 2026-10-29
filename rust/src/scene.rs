//! 3D 정답 크리처 생성기 v2(진단 우선순위 0: 평가 바로잡기). 머리·목·몸통·다리 넷·꼬리·뿔·귀를 타원체(관은 구 사슬)로 만들고,
//! 셀 셰이딩 정사영으로 정면·옆·뒤를 그린다. 정답은 3D 도형(prims.json)과 정답 메시(gt.obj), 정답 마스크(truth_all.npz).
//! 도면 오류 주입: 그 뷰를 그릴 때만 도형을 바꾼다(정답 3D 는 그대로) → 오류를 고친 모델이 이기는 과제.
//!   side_height: 옆 뷰에서 머리 묶음(머리·뿔·귀)을 위로 0.08~0.14H 올려 그림(뷰끼리 높이 어긋남)
//!   twin: 옆 뷰에 반대편 뿔을 앞뒤로 0.2~0.35H 비켜 한 번 더 그림(AI 도면이 반대편 짝을 비켜 그리는 실수)
//! 좌표: H, X 오른쪽 +, Y 앞 +, Z 위(발바닥 0).
use crate::mesh::{marching_tets, signed_volume, write_obj};
use crate::grid::Grid3;
use crate::npy::{write_npy, Arr, ArrData};
use crate::score::Prim;
use serde_json::{json, Value};
use std::collections::BTreeMap;

pub const W: usize = 400;
pub const H: usize = 400;
pub const PPH: f64 = 100.0;
pub const GROUND: f64 = 390.0; // 발바닥 행

/// 작은 결정적 난수(SplitMix64). numpy 와 같을 필요는 없다(새 과제 묶음).
pub struct Rng(u64);
impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) ^ 0xD1B5_4A32_D192_ED03)
    }
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    pub fn u(&mut self, a: f64, b: f64) -> f64 {
        a + (b - a) * ((self.next() >> 11) as f64 / (1u64 << 53) as f64)
    }
}

#[derive(Clone)]
pub struct P {
    pub c: [f64; 3],
    pub r: [f64; 3],
    pub part: &'static str,
    pub mat: &'static str,
}

fn ell(c: [f64; 3], r: [f64; 3], part: &'static str, mat: &'static str) -> P {
    P { c, r, part, mat }
}

/// 구 사슬(관): 점 목록과 반지름 목록.
fn chain(pts: &[[f64; 3]], rad: &[f64], part: &'static str, mat: &'static str) -> Vec<P> {
    pts.iter().zip(rad).map(|(c, &r)| ell(*c, [r, r, r], part, mat)).collect()
}

/// 2차 베지어 곡선 위 n 점.
fn bez(a: [f64; 3], b: [f64; 3], c: [f64; 3], n: usize) -> Vec<[f64; 3]> {
    (0..n).map(|i| { let t = i as f64 / (n - 1) as f64; [0, 1, 2].map(|k| (1.0 - t) * (1.0 - t) * a[k] + 2.0 * (1.0 - t) * t * b[k] + t * t * c[k]) }).collect()
}

pub struct Creature {
    pub prims: Vec<P>,
    pub pal: BTreeMap<&'static str, [f64; 3]>,
    pub head_group: Vec<usize>, // 머리·뿔·귀 도형 번호(오류 주입용)
    pub horn_left: Vec<usize>,
}

pub fn creature(rng: &mut Rng) -> Creature {
    let mut p: Vec<P> = Vec::new();
    // 몸통
    let (bw, bl, bh) = (rng.u(0.38, 0.52), rng.u(0.75, 1.0), rng.u(0.42, 0.55));
    let leg_len = rng.u(0.7, 1.0);
    let bz = leg_len + bh * 0.7;
    p.push(ell([0.0, 0.0, bz], [bw, bl, bh], "몸통", "털"));
    p.push(ell([0.0, bl * 0.45, bz + bh * 0.25], [bw * 0.95, bl * 0.5, bh * 0.85], "몸통", "털")); // 어깨 혹
    // 다리 넷(몸통 아래에서 땅까지, 굵기 줄어듦)
    for (sx, sy) in [(1.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (-1.0, -1.0)] {
        let top = [sx * bw * 0.6, sy * bl * 0.62, bz - bh * 0.4];
        let knee = [sx * bw * 0.62, sy * bl * 0.62 + rng.u(-0.06, 0.06), leg_len * 0.5];
        let foot = [sx * bw * 0.62, sy * bl * 0.62, 0.06];
        let pts = bez(top, knee, foot, 24);
        let r0 = rng.u(0.11, 0.15);
        let rad: Vec<f64> = (0..24).map(|i| r0 * (1.0 - 0.45 * i as f64 / 23.0)).collect();
        p.extend(chain(&pts, &rad, "다리", "털"));
    }
    // 목·머리
    let neck_top = [0.0, bl + rng.u(0.15, 0.3), bz + bh + rng.u(0.15, 0.35)];
    let neck = bez([0.0, bl * 0.6, bz + bh * 0.5], [0.0, bl * 0.95, bz + bh * 0.9], neck_top, 16);
    let nr: Vec<f64> = (0..16).map(|i| 0.26 - 0.08 * i as f64 / 15.0).collect();
    p.extend(chain(&neck, &nr, "목", "털"));
    let (hw, hd, hh) = (rng.u(0.24, 0.32), rng.u(0.26, 0.36), rng.u(0.24, 0.32));
    let hc = [0.0, neck_top[1] + hd * 0.5, neck_top[2] + hh * 0.3];
    let h0 = p.len();
    p.push(ell(hc, [hw, hd, hh], "머리", "털"));
    p.push(ell([0.0, hc[1] + hd * 0.85, hc[2] - hh * 0.35], [hw * 0.6, hd * 0.6, hh * 0.5], "머리", "얼굴"));
    if rng.u(0.0, 1.0) < 0.6 {
        p.push(ell([0.0, hc[1], hc[2] + hh * 0.85], [hw * 0.35, hd * 0.4, hh * 0.4], "머리", "털"));
    }
    // 뿔: 옆으로 뻗다가 위로 휨, 오른쪽을 만들고 왼쪽은 거울
    let curl = rng.u(0.0, 1.0);
    let hr = rng.u(0.28, 0.4);
    let base = [hw * 0.7, hc[1] + rng.u(-0.05, 0.08), hc[2] + hh * 0.5];
    let mut horn_left = Vec::new();
    for sx in [1.0, -1.0] {
        let n = 60;
        let pts: Vec<[f64; 3]> = (0..n).map(|i| {
            let t = i as f64 / (n - 1) as f64;
            let a = t * (std::f64::consts::PI * 0.55 + curl);
            [sx * (base[0] + hr * a.sin()), base[1] + 0.08 * t, base[2] + hr * (1.0 - a.cos())]
        }).collect();
        // 끝 반지름 0.022H: 정답 메시 칸(0.01H) 두 개 폭보다 가늘면 표면 뽑기에서 끝이 끊겼다(조각 31개, 생성기 v2 1차)
        let rad: Vec<f64> = (0..n).map(|i| 0.065 * (1.0 - i as f64 / (n - 1) as f64) + 0.022).collect();
        let s = p.len();
        p.extend(chain(&pts, &rad, "뿔", "뿔"));
        if sx < 0.0 {
            horn_left = (s..p.len()).collect();
        }
    }
    // 귀
    let ez = hc[2] + rng.u(-0.04, 0.1);
    for sx in [1.0, -1.0] {
        p.push(ell([sx * (hw + 0.1), hc[1] - hd * 0.2, ez], [0.13, 0.04, 0.06], "귀", "털"));
    }
    let head_group: Vec<usize> = (h0..p.len()).collect();
    // 꼬리
    let tail = bez([0.0, -bl * 0.95, bz + bh * 0.3], [0.0, -bl - rng.u(0.2, 0.4), bz + rng.u(-0.1, 0.3)], [0.0, -bl - rng.u(0.35, 0.6), bz - rng.u(0.2, 0.5)], 24);
    let tr: Vec<f64> = (0..24).map(|i| (0.07 * (1.0 - 0.6 * i as f64 / 23.0)).max(0.03)).collect();
    p.extend(chain(&tail, &tr, "꼬리", "털"));
    let mut pal = BTreeMap::new();
    pal.insert("배경", [218.0, 218.0, 220.0]);
    pal.insert("털", [rng.u(70.0, 110.0), rng.u(50.0, 85.0), rng.u(45.0, 75.0)]);
    pal.insert("얼굴", [rng.u(135.0, 165.0), rng.u(95.0, 125.0), rng.u(80.0, 105.0)]);
    pal.insert("뿔", [rng.u(200.0, 225.0), rng.u(180.0, 200.0), rng.u(160.0, 180.0)]);
    Creature { prims: p, pal, head_group, horn_left }
}

/// 뷰: (가로축, 깊이축, 화면 x 부호, 깊이 부호). 정면 = 앞(+Y)에서 봄, 옆 = 오른쪽(+X)에서, 뒤 = -Y 에서.
fn axes(view: &str) -> (usize, usize, f64, f64) {
    match view {
        "front" => (0, 1, -1.0, 1.0),
        "side" => (1, 0, -1.0, 1.0),
        _ => (0, 1, 1.0, -1.0),
    }
}

/// 한 뷰 그리기. 반환 (RGB 바이트, 부위별 보이는 마스크).
pub fn render_view(prims: &[P], pal: &BTreeMap<&'static str, [f64; 3]>, view: &str) -> (Vec<u8>, BTreeMap<String, Vec<bool>>) {
    // 픽셀마다 4x4 점: 2x2 로는 '절반 이상'이 실제 덮인 넓이 25~75% 를 모두 넣어 정답 마스크가 뚱뚱했다(투영 v2 시험)
    let s = 4usize;
    let (hh, ww) = (H * s, W * s);
    let (la, da, sign, dsign) = axes(view);
    let cx = W as f64 / 2.0;
    let l = { let v = [0.45f64, 0.55, 0.7]; let n = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt(); [v[0] / n, v[1] / n, v[2] / n] };
    let tone = [0.72, 0.88, 1.06];
    let mut rgb = vec![[0.0f64; 3]; H * W];
    let mut part_cnt: BTreeMap<&str, Vec<u8>> = BTreeMap::new();
    for py in 0..hh {
        for px in 0..ww {
            let (fx, fy) = ((px as f64 + 0.5) / s as f64, (py as f64 + 0.5) / s as f64);
            let lat = sign * (fx - cx) / PPH;
            let z = (GROUND - fy) / PPH;
            let mut best: Option<(f64, usize, [f64; 3])> = None;
            for (i, p) in prims.iter().enumerate() {
                let (a, b, ra, rb) = (p.c[la], p.c[2], p.r[la], p.r[2]);
                let q = ((lat - a) / ra).powi(2) + ((z - b) / rb).powi(2);
                if q > 1.0 {
                    continue;
                }
                let dz = p.c[da] + dsign * p.r[da] * (1.0 - q).max(0.0).sqrt(); // 보는 쪽 표면
                let depth = dsign * dz;
                if best.map(|b| depth > b.0).unwrap_or(true) {
                    let mut pt = [0.0; 3];
                    pt[la] = lat;
                    pt[2] = z;
                    pt[da] = dz;
                    best = Some((depth, i, pt));
                }
            }
            let pix = (py / s) * W + px / s;
            let col = match best {
                None => pal["배경"],
                Some((_, i, pt)) => {
                    let p = &prims[i];
                    let n = [0, 1, 2].map(|k| (pt[k] - p.c[k]) / (p.r[k] * p.r[k]));
                    let nl = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt().max(1e-12);
                    let lam = (n[0] * l[0] + n[1] * l[1] + n[2] * l[2]) / nl;
                    let k = if lam > 0.55 { 2 } else if lam > 0.15 { 1 } else { 0 };
                    part_cnt.entry(p.part).or_insert_with(|| vec![0u8; H * W])[pix] += 1;
                    pal[p.mat].map(|c| (c * tone[k]).clamp(0.0, 255.0))
                }
            };
            for k in 0..3 {
                rgb[pix][k] += col[k] / (s * s) as f64;
            }
        }
    }
    let bytes: Vec<u8> = rgb.iter().flat_map(|c| c.map(|x| x.round().clamp(0.0, 255.0) as u8)).collect();
    // 픽셀은 전경이 절반 이상이면 가장 많이 차지한 부위에 넣는다. 부위마다 '절반 이상'으로 따로 자르면
    // 두 부위가 반씩 나눈 경계 픽셀(다리·몸통)이 어느 부위에도 안 들어가 합집합이 전경보다 작았다(생성기 v2, 396픽셀)
    let names: Vec<&str> = part_cnt.keys().cloned().collect();
    let mut masks: BTreeMap<String, Vec<bool>> = names.iter().map(|k| (k.to_string(), vec![false; H * W])).collect();
    for i in 0..H * W {
        let tot: usize = names.iter().map(|k| part_cnt[k][i] as usize).sum();
        if tot * 2 >= s * s {
            let best = names.iter().max_by_key(|k| part_cnt[*k][i]).unwrap();
            masks.get_mut(*best).unwrap()[i] = true;
        }
    }
    (bytes, masks)
}

/// 정답 메시: f = max_i (1 − ‖(p−c)/r‖), 0 등위면(반지름 방향으로 거의 선형이라 칸 사이 보간이 가는 부위를 덜 깎는다). 칸 크기 voxel.
pub fn gt_mesh(prims: &[P], voxel: f64) -> crate::mesh::Mesh {
    let mut lo = [f64::INFINITY; 3];
    let mut hi = [f64::NEG_INFINITY; 3];
    for p in prims {
        for k in 0..3 {
            lo[k] = lo[k].min(p.c[k] - p.r[k]);
            hi[k] = hi[k].max(p.c[k] + p.r[k]);
        }
    }
    let lo = lo.map(|x| x - 3.0 * voxel);
    let n = [0, 1, 2].map(|k| ((hi[k] + 3.0 * voxel - lo[k]) / voxel).ceil() as usize + 1);
    let mut g = Grid3::<f64>::new(n);
    for v in g.d.iter_mut() {
        *v = -1.0;
    }
    for p in prims {
        let a = [0, 1, 2].map(|k| ((p.c[k] - p.r[k] - lo[k]) / voxel).floor().max(0.0) as usize);
        let b = [0, 1, 2].map(|k| (((p.c[k] + p.r[k] - lo[k]) / voxel).ceil() as usize + 2).min(n[k]));
        for x in a[0]..b[0] {
            for y in a[1]..b[1] {
                for z in a[2]..b[2] {
                    let q = [x, y, z];
                    let s: f64 = (0..3).map(|k| ((lo[k] + q[k] as f64 * voxel - p.c[k]) / p.r[k]).powi(2)).sum();
                    let i = g.idx(x, y, z);
                    g.d[i] = g.d[i].max(1.0 - s.sqrt());
                }
            }
        }
    }
    field_to_mesh(g, lo, voxel)
}

/// 값 격자(안 > 0) → 닫힌 메시: 속 빈 주머니 메우기 → 표면 뽑기 → 면 방향 맞춤. 정답 메시·맞추기 조립이 같이 쓴다.
pub fn field_to_mesh(mut g: Grid3<f64>, lo: [f64; 3], voxel: f64) -> crate::mesh::Mesh {
    let n = g.n;
    // 속 빈 주머니 메우기: 바깥 경계에서 이어지지 않은 음수 칸은 안으로 친다(겹친 도형 사이에 갇힌 작은 빈칸이
    // 면 24개짜리 조각으로 따로 세졌다, 맞추기 dev_1000). 정답 메시에는 영향 없음(타원체 합집합엔 갇힌 빈칸이 거의 없다)
    {
        let mut out = vec![false; g.d.len()];
        let mut q = std::collections::VecDeque::new();
        for x in 0..n[0] {
            for y in 0..n[1] {
                for z in 0..n[2] {
                    if x == 0 || y == 0 || z == 0 || x == n[0] - 1 || y == n[1] - 1 || z == n[2] - 1 {
                        let i = g.idx(x, y, z);
                        if g.d[i] <= 0.0 && !out[i] {
                            out[i] = true;
                            q.push_back([x, y, z]);
                        }
                    }
                }
            }
        }
        while let Some(p) = q.pop_front() {
            for (dx, dy, dz) in [(1i64, 0i64, 0i64), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)] {
                let a = [p[0] as i64 + dx, p[1] as i64 + dy, p[2] as i64 + dz];
                if a.iter().zip(n.iter()).any(|(&v, &m)| v < 0 || v >= m as i64) {
                    continue;
                }
                let i = g.idx(a[0] as usize, a[1] as usize, a[2] as usize);
                if g.d[i] <= 0.0 && !out[i] {
                    out[i] = true;
                    q.push_back([a[0] as usize, a[1] as usize, a[2] as usize]);
                }
            }
        }
        for i in 0..g.d.len() {
            if g.d[i] <= 0.0 && !out[i] {
                g.d[i] = 0.5;
            }
        }
    }
    // 경계값을 0 에서 살짝 비킨다: 격자점 값이 정확히 0 이면 여러 변의 꼭짓점이 한 자리에 겹쳐 면 둘짜리 부스러기 71개가 생겼다
    let mut m = marching_tets(&g, 1e-9);
    for v in m.v.iter_mut() {
        *v = [lo[0] + v[0] * voxel, lo[1] + v[1] * voxel, lo[2] + v[2] * voxel];
    }
    if signed_volume(&m) < 0.0 {
        for t in m.f.iter_mut() {
            t.swap(1, 2);
        }
    }
    m
}

pub fn to_score_prims(prims: &[P]) -> Vec<Prim> {
    prims.iter().map(|p| Prim { c: p.c, r: p.r, part: p.part.to_string() }).collect()
}

/// 과제 하나 만들기. 반환 정보.
pub fn make_task(out: &str, seed: u64, inject: &str) -> Result<Value, String> {
    std::fs::create_dir_all(out).map_err(|e| e.to_string())?;
    let mut rng = Rng::new(seed);
    let cr = creature(&mut rng);
    let views = ["front", "side", "back"];
    let mut full = vec![0u8; H * W * 3 * 3];
    let mut truth: BTreeMap<String, Vec<bool>> = BTreeMap::new();
    let mut drawn: BTreeMap<String, Vec<bool>> = BTreeMap::new(); // 실제로 그린 것(오류 주입 반영) = 이 도면의 이상적인 트레이스
    let mut inj_info = json!(null);
    for (vi, v) in views.iter().enumerate() {
        // 정답 마스크: 오류 없는 3D 그대로
        let (img_true, mk) = render_view(&cr.prims, &cr.pal, v);
        for (part, m) in &mk {
            truth.insert(format!("{}|{}", v, part), m.clone());
        }
        // 도면: 오류 주입 뷰만 바꾼 도형으로
        let img = if *v == "side" && inject != "none" {
            let mut q = cr.prims.clone();
            if inject == "side_height" {
                let dz = rng.u(0.08, 0.14);
                for &i in &cr.head_group {
                    q[i].c[2] += dz;
                }
                inj_info = json!({"종류": "side_height", "뷰": "side", "올림_H": dz});
            } else if inject == "twin" {
                let dy = rng.u(0.2, 0.35) * if rng.u(0.0, 1.0) < 0.5 { 1.0 } else { -1.0 };
                for &i in &cr.horn_left {
                    let mut p = cr.prims[i].clone();
                    p.c[1] += dy;
                    q.push(p);
                }
                inj_info = json!({"종류": "twin", "뷰": "side", "비킴_H": dy});
            } else {
                return Err(format!("모르는 오류 주입 {}", inject));
            }
            let (im, dm) = render_view(&q, &cr.pal, v);
            for (part, m) in dm {
                drawn.insert(format!("{}|{}", v, part), m);
            }
            im
        } else {
            for (part, m) in mk {
                drawn.insert(format!("{}|{}", v, part), m);
            }
            img_true
        };
        for r in 0..H {
            let dst = (r * W * 3 + vi * W) * 3;
            full[dst..dst + W * 3].copy_from_slice(&img[r * W * 3..(r + 1) * W * 3]);
        }
    }
    let p = |f: &str| format!("{}/{}", out, f);
    write_npy(&p("drawing.npy"), &Arr { shape: vec![H, W * 3, 3], data: ArrData::U8(full.clone()) })?;
    crate::png::write_rgb(&p("drawing.png"), W * 3, H, &full)?;
    // 마스크를 그림 전체 좌표로(뷰 칸 옮김): 정답(오류 없는 3D) 과 그린 것(오류 반영)
    for (name, src) in [("truth_all.npz", &truth), ("drawn_all.npz", &drawn)] {
        let mut npz = Vec::new();
        for (k, m) in src.iter() {
            let vi = views.iter().position(|v| k.starts_with(&format!("{}|", v))).unwrap();
            let mut full_m = vec![false; H * W * 3];
            for r in 0..H {
                for c in 0..W {
                    full_m[r * W * 3 + vi * W + c] = m[r * W + c];
                }
            }
            npz.push((k.clone(), Arr { shape: vec![H, W * 3], data: ArrData::Bool(full_m) }));
        }
        crate::npy::write_npz(&p(name), &npz)?;
    }
    let meta = json!({"px_per_H": PPH, "ground_row_grid": GROUND, "panels": {
        "front": {"중심선_x": W as f64 / 2.0, "x부호(화면x→캐릭터)": -1},
        "side": {"중심선_x": W as f64 * 1.5, "x부호(화면x→캐릭터)": -1},
        "back": {"중심선_x": W as f64 * 2.5, "x부호(화면x→캐릭터)": 1}}});
    std::fs::write(p("meta.json"), serde_json::to_string_pretty(&meta).unwrap()).map_err(|e| e.to_string())?;
    let pj: Vec<Value> = cr.prims.iter().map(|q| json!({"c": q.c, "r": q.r, "part": q.part, "mat": q.mat})).collect();
    std::fs::write(p("prims.json"), serde_json::to_string(&pj).unwrap()).map_err(|e| e.to_string())?;
    let gm = gt_mesh(&cr.prims, 0.01);
    write_obj(&p("gt.obj"), &gm)?;
    let parts: Vec<&str> = cr.prims.iter().map(|q| q.part).collect::<std::collections::BTreeSet<_>>().into_iter().collect();
    let task = json!({"이름": std::path::Path::new(out).file_name().map(|x| x.to_string_lossy().to_string()), "종류": "합성v2", "씨앗": seed,
        "오류_주입": inj_info, "부위": parts, "뷰": views,
        "정답": {"3D": "prims.json(타원체 합집합) · gt.obj", "마스크": "truth_all.npz(오류 없는 3D 를 그린 것)"}});
    std::fs::write(p("task.json"), serde_json::to_string_pretty(&task).unwrap()).map_err(|e| e.to_string())?;
    Ok(json!({"도형_수": cr.prims.len(), "정답_메시_정점": gm.v.len(), "오류_주입": task["오류_주입"]}))
}
