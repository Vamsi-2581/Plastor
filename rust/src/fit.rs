//! 추적(docs/추적_체계.md): R-001 R-003 R-033
//! 원형 연산자 맞추기(루프 항목 4, K2). 부위마다 연산자(덩어리·관·판)를 정해 정면·옆 도면 마스크에 맞추고,
//! 모든 도형을 SDF 합집합으로 조립해 닫힌 한 덩어리 메시를 낸다. 두 뷰 헐은 초기값으로만 쓴다(진단 1.2: 헐이 형상 생성의 중심이면 상자 단면).
//! 손실 = 그 부위 마스크와 투영의 불일치 픽셀 수(다른 부위로 그려진 픽셀은 '상관없음': 그 뒤에 숨어 있을 수 있음).
use crate::frame::Frame;
use crate::grid::{Grid3, Mask2};
use crate::hull::{fill, hull_axes, HullOpt};
use crate::scene::{gt_mesh, P};
use serde_json::{json, Value};
use std::collections::{BTreeMap, VecDeque};

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Kind {
    Blob,
    Tube,
    Plate,
}

/// 이름 → 연산자 기본값(LLM 선택은 K0 뒤에). 모르는 이름은 덩어리.
pub fn kind_of(part: &str) -> Kind {
    match part {
        "목" | "다리" | "꼬리" | "뿔" | "뿔 밑동" => Kind::Tube,
        "귀" => Kind::Plate,
        _ => Kind::Blob,
    }
}

/// 부모(붙는 곳). 관 뿌리를 부모 안으로 이어 준다.
pub fn parent_of(part: &str) -> Option<&'static str> {
    match part {
        "다리" | "꼬리" | "목" => Some("몸통"),
        "뿔" | "귀" | "뿔 밑동" => Some("머리"),
        _ => None,
    }
}

#[derive(Clone, Debug)]
pub struct Ell {
    pub c: [f64; 3],
    pub r: [f64; 3],
}

#[derive(Clone, Debug)]
pub enum Inst {
    Blob(Vec<Ell>),
    Tube { ctrl: Vec<[f64; 3]>, rad: Vec<f64> },
}

const TUBE_K: usize = 6;
/// 깊이 항 무게(픽셀 단위 손실에 더함). 상관 1 이면 0, 0 이면 DEPTH_W
const DEPTH_W: f64 = 1500.0;
const TUBE_S: usize = 40;

/// Catmull-Rom 중심선 위 S 점과 반지름(조절점 사이 선형).
fn tube_spheres(ctrl: &[[f64; 3]], rad: &[f64]) -> Vec<Ell> {
    let k = ctrl.len();
    // 구 개수는 길이에 맞춘다: 간격이 가장 가는 반지름의 절반을 넘으면 구슬처럼 끊겼다(dev_1002 꼬리 9조각)
    let len: f64 = ctrl.windows(2).map(|w| (0..3).map(|a| (w[1][a] - w[0][a]).powi(2)).sum::<f64>().sqrt()).sum();
    let rmin = rad.iter().cloned().fold(f64::INFINITY, f64::min).max(0.008);
    let n = ((len * 1.3 / (0.5 * rmin)).ceil() as usize).clamp(TUBE_S, 600);
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let t = i as f64 / (n - 1) as f64 * (k - 1) as f64;
        let j = (t.floor() as usize).min(k - 2);
        let u = t - j as f64;
        let p0 = ctrl[j.saturating_sub(1)];
        let (p1, p2) = (ctrl[j], ctrl[j + 1]);
        let p3 = ctrl[(j + 2).min(k - 1)];
        let c = [0, 1, 2].map(|a| {
            0.5 * ((2.0 * p1[a]) + (-p0[a] + p2[a]) * u + (2.0 * p0[a] - 5.0 * p1[a] + 4.0 * p2[a] - p3[a]) * u * u + (-p0[a] + 3.0 * p1[a] - 3.0 * p2[a] + p3[a]) * u * u * u)
        });
        let r = (rad[j] * (1.0 - u) + rad[j + 1] * u).max(0.008);
        out.push(Ell { c, r: [r, r, r] });
    }
    out
}

impl Inst {
    pub fn ells(&self) -> Vec<Ell> {
        match self {
            Inst::Blob(v) => v.clone(),
            Inst::Tube { ctrl, rad } => tube_spheres(ctrl, rad),
        }
    }
    fn params(&self) -> Vec<f64> {
        match self {
            Inst::Blob(v) => v.iter().flat_map(|e| e.c.iter().chain(e.r.iter()).cloned()).collect(),
            Inst::Tube { ctrl, rad } => ctrl.iter().flat_map(|c| c.iter().cloned()).chain(rad.iter().cloned()).collect(),
        }
    }
    fn set(&mut self, p: &[f64]) {
        match self {
            Inst::Blob(v) => {
                for (i, e) in v.iter_mut().enumerate() {
                    e.c = [p[i * 6], p[i * 6 + 1], p[i * 6 + 2]];
                    e.r = [p[i * 6 + 3].max(0.01), p[i * 6 + 4].max(0.01), p[i * 6 + 5].max(0.01)];
                }
            }
            Inst::Tube { ctrl, rad } => {
                let k = ctrl.len();
                for i in 0..k {
                    ctrl[i] = [p[i * 3], p[i * 3 + 1], p[i * 3 + 2]];
                }
                for i in 0..k {
                    rad[i] = p[k * 3 + i].max(0.008);
                }
            }
        }
    }
    /// 매개변수마다 걸음 크기(위치 0.02H, 반지름 0.01H).
    fn steps(&self) -> Vec<f64> {
        match self {
            Inst::Blob(v) => v.iter().flat_map(|_| [0.02, 0.02, 0.02, 0.01, 0.01, 0.01]).collect(),
            Inst::Tube { ctrl, rad } => std::iter::repeat(0.02).take(ctrl.len() * 3).chain(std::iter::repeat(0.01).take(rad.len())).collect(),
        }
    }
}

/// 한 뷰 마스크 영역(부위 근처 상자)에서 도형들의 투영(픽셀 중심이 타원 안).
struct ViewTarget {
    view: &'static str,
    r0: usize,
    c0: usize,
    h: usize,
    w: usize,
    target: Vec<bool>,
    dont: Vec<bool>,
    lat: Vec<f64>, // 열마다 가로 H
    z: Vec<f64>,   // 행마다 높이 H
    /// 정면 깊이 근거(항목 4d, 단안 깊이 추정, 값이 클수록 가까움). 덩어리 부위에서만 씀
    depth: Option<Vec<f64>>,
}

impl ViewTarget {
    fn new(fr: &Frame, view: &'static str, tgt: &Mask2, occ: &Mask2, margin: usize) -> Option<Self> {
        let (mut rmin, mut rmax, mut cmin, mut cmax) = (usize::MAX, 0, usize::MAX, 0);
        for r in 0..tgt.h {
            for c in 0..tgt.w {
                if tgt.get(r, c) {
                    rmin = rmin.min(r);
                    rmax = rmax.max(r);
                    cmin = cmin.min(c);
                    cmax = cmax.max(c);
                }
            }
        }
        if rmin == usize::MAX {
            return None;
        }
        let r0 = rmin.saturating_sub(margin);
        let c0 = cmin.saturating_sub(margin);
        let r1 = (rmax + margin + 1).min(tgt.h);
        let c1 = (cmax + margin + 1).min(tgt.w);
        let (h, w) = (r1 - r0, c1 - c0);
        let mut target = vec![false; h * w];
        let mut dont = vec![false; h * w];
        for r in 0..h {
            for c in 0..w {
                target[r * w + c] = tgt.get(r0 + r, c0 + c);
                dont[r * w + c] = occ.get(r0 + r, c0 + c);
            }
        }
        let lat = (0..w).map(|c| fr.px_to_h(view, (c0 + c) as f64 + 0.5, 0.0).0).collect();
        let z = (0..h).map(|r| fr.px_to_h(view, 0.0, (r0 + r) as f64 + 0.5).1).collect();
        Some(ViewTarget { view, r0, c0, h, w, target, dont, lat, z, depth: None })
    }

    /// 그림 전체 크기 깊이 배열에서 이 상자 부분만(0 이나 NaN 은 없음으로).
    fn with_depth(mut self, full: &[f64], full_w: usize) -> Self {
        let mut d = vec![f64::NAN; self.h * self.w];
        for r in 0..self.h {
            for c in 0..self.w {
                let v = full[(self.r0 + r) * full_w + self.c0 + c];
                if v.is_finite() && v != 0.0 {
                    d[r * self.w + c] = v;
                }
            }
        }
        self.depth = Some(d);
        self
    }

    fn axis(&self) -> usize {
        if self.view == "side" { 1 } else { 0 }
    }

    /// 불일치 픽셀 수(FP: 그렸는데 마스크 아님·상관없음 아님, FN: 마스크인데 안 그림).
    fn loss(&self, ells: &[Ell], buf: &mut Vec<bool>) -> f64 {
        buf.clear();
        buf.resize(self.h * self.w, false);
        let la = self.axis();
        let lat_lo = self.lat[0].min(self.lat[self.w - 1]);
        let lat_step = (self.lat[self.w - 1] - self.lat[0]) / (self.w.max(2) - 1) as f64;
        let z_step = (self.z[self.h - 1] - self.z[0]) / (self.h.max(2) - 1) as f64;
        let _ = lat_lo;
        for e in ells {
            // 타원 상자 안의 행·열만
            let (cl, rl, cz, rz) = (e.c[la], e.r[la], e.c[2], e.r[2]);
            let ca = ((cl - rl - self.lat[0]) / lat_step).floor();
            let cb = ((cl + rl - self.lat[0]) / lat_step).ceil();
            let ra = ((cz + rz - self.z[0]) / z_step).floor();
            let rb = ((cz - rz - self.z[0]) / z_step).ceil();
            let (c_lo, c_hi) = (ca.min(cb).max(0.0) as usize, (ca.max(cb).max(0.0) as usize + 1).min(self.w));
            let (r_lo, r_hi) = (ra.min(rb).max(0.0) as usize, (ra.max(rb).max(0.0) as usize + 1).min(self.h));
            for r in r_lo..r_hi {
                let dz = (self.z[r] - cz) / rz;
                let dz2 = dz * dz;
                if dz2 > 1.0 {
                    continue;
                }
                for c in c_lo..c_hi {
                    let dl = (self.lat[c] - cl) / rl;
                    if dl * dl + dz2 <= 1.0 {
                        buf[r * self.w + c] = true;
                    }
                }
            }
        }
        let mut bad = 0usize;
        for i in 0..buf.len() {
            if buf[i] != self.target[i] && !(buf[i] && self.dont[i]) {
                bad += 1;
            }
        }
        let mut extra = 0.0;
        if let (Some(dp), "front") = (&self.depth, self.view) {
            // 깊이 항: 모델 앞면 Y 와 추정 깊이의 피어슨 상관(부위 픽셀만). 낮을수록 벌점(얇은 판 대 둥근 덩어리를 가름)
            let mut my = vec![f64::NAN; buf.len()];
            for e in ells {
                let (cl, rl, cz, rz) = (e.c[0], e.r[0], e.c[2], e.r[2]);
                for r in 0..self.h {
                    let dz = (self.z[r] - cz) / rz;
                    if dz * dz > 1.0 {
                        continue;
                    }
                    for c in 0..self.w {
                        let dl = (self.lat[c] - cl) / rl;
                        let q = dl * dl + dz * dz;
                        if q <= 1.0 {
                            let y = e.c[1] + e.r[1] * (1.0 - q).sqrt();
                            let i = r * self.w + c;
                            if !(my[i] >= y) {
                                my[i] = y;
                            }
                        }
                    }
                }
            }
            let (mut n, mut sa, mut sb, mut saa, mut sbb, mut sab) = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
            for i in 0..buf.len() {
                if self.target[i] && my[i].is_finite() && dp[i].is_finite() {
                    let (a, b) = (my[i], dp[i]);
                    n += 1.0;
                    sa += a;
                    sb += b;
                    saa += a * a;
                    sbb += b * b;
                    sab += a * b;
                }
            }
            if n > 30.0 {
                let cov = sab / n - sa * sb / n / n;
                let va = (saa / n - sa * sa / n / n).max(1e-12);
                let vb = (sbb / n - sb * sb / n / n).max(1e-12);
                extra = DEPTH_W * (1.0 - cov / (va * vb).sqrt());
            }
        }
        bad as f64 + extra
    }
}

/// 3D 연결 성분(26 이웃), 큰 순서, 최소 칸 수 이상.
fn components(vol: &Grid3<bool>, min_cells: usize) -> Vec<Vec<[usize; 3]>> {
    let n = vol.n;
    let mut seen = vec![false; vol.d.len()];
    let mut out = Vec::new();
    for x in 0..n[0] {
        for y in 0..n[1] {
            for z in 0..n[2] {
                let i = vol.idx(x, y, z);
                if !vol.d[i] || seen[i] {
                    continue;
                }
                let mut comp = Vec::new();
                let mut q = VecDeque::from([[x, y, z]]);
                seen[i] = true;
                while let Some(p) = q.pop_front() {
                    comp.push(p);
                    for dx in -1i64..=1 {
                        for dy in -1i64..=1 {
                            for dz in -1i64..=1 {
                                let a = [p[0] as i64 + dx, p[1] as i64 + dy, p[2] as i64 + dz];
                                if a.iter().zip(n.iter()).any(|(&v, &m)| v < 0 || v >= m as i64) {
                                    continue;
                                }
                                let j = vol.idx(a[0] as usize, a[1] as usize, a[2] as usize);
                                if vol.d[j] && !seen[j] {
                                    seen[j] = true;
                                    q.push_back([a[0] as usize, a[1] as usize, a[2] as usize]);
                                }
                            }
                        }
                    }
                }
                if comp.len() >= min_cells {
                    out.push(comp);
                }
            }
        }
    }
    out.sort_by_key(|c| std::cmp::Reverse(c.len()));
    out
}

fn ell_from_points(pts: &[[f64; 3]]) -> Ell {
    let mut lo = [f64::INFINITY; 3];
    let mut hi = [f64::NEG_INFINITY; 3];
    for p in pts {
        for k in 0..3 {
            lo[k] = lo[k].min(p[k]);
            hi[k] = hi[k].max(p[k]);
        }
    }
    Ell { c: [0, 1, 2].map(|k| (lo[k] + hi[k]) / 2.0), r: [0, 1, 2].map(|k| ((hi[k] - lo[k]) / 2.0).max(0.02)) }
}

fn inside(e: &Ell, p: [f64; 3], s: f64) -> bool {
    (0..3).map(|k| ((p[k] - e.c[k]) / (e.r[k] * s)).powi(2)).sum::<f64>() <= 1.0
}

/// 관 초기값: 뿌리(부모 중심에 가장 가까운 칸)에서 걸음 거리 띠마다 중심 → 조절점 K 개, 반지름은 띠 단면 넓이에서.
fn tube_init(pts: &[[f64; 3]], cells: &[[usize; 3]], voxel: f64, root_hint: [f64; 3]) -> Inst {
    let idx: BTreeMap<[usize; 3], usize> = cells.iter().enumerate().map(|(i, c)| (*c, i)).collect();
    let d0: Vec<f64> = pts.iter().map(|p| (0..3).map(|k| (p[k] - root_hint[k]).powi(2)).sum::<f64>()).collect();
    let dmin = d0.iter().cloned().fold(f64::INFINITY, f64::min).sqrt();
    let mut dist = vec![usize::MAX; pts.len()];
    let mut q = VecDeque::new();
    for i in 0..pts.len() {
        if d0[i].sqrt() <= dmin + 2.0 * voxel {
            dist[i] = 0;
            q.push_back(i);
        }
    }
    while let Some(i) = q.pop_front() {
        let c = cells[i];
        for dx in -1i64..=1 {
            for dy in -1i64..=1 {
                for dz in -1i64..=1 {
                    let a = [c[0] as i64 + dx, c[1] as i64 + dy, c[2] as i64 + dz];
                    if a.iter().any(|&v| v < 0) {
                        continue;
                    }
                    if let Some(&j) = idx.get(&[a[0] as usize, a[1] as usize, a[2] as usize]) {
                        if dist[j] == usize::MAX {
                            dist[j] = dist[i] + 1;
                            q.push_back(j);
                        }
                    }
                }
            }
        }
    }
    let dmax = dist.iter().filter(|&&d| d != usize::MAX).cloned().max().unwrap_or(0).max(1);
    let nb = (dmax / 2).max(TUBE_K);
    let mut sum = vec![[0.0; 3]; nb];
    let mut cnt = vec![0usize; nb];
    for (i, &d) in dist.iter().enumerate() {
        if d == usize::MAX {
            continue;
        }
        let b = (d * nb / (dmax + 1)).min(nb - 1);
        for k in 0..3 {
            sum[b][k] += pts[i][k];
        }
        cnt[b] += 1;
    }
    let cen: Vec<([f64; 3], usize)> = (0..nb).filter(|&b| cnt[b] > 0).map(|b| (sum[b].map(|s| s / cnt[b] as f64), cnt[b])).collect();
    let band_len = (dmax + 1) as f64 / nb as f64 * voxel;
    let mut ctrl = Vec::new();
    let mut rad = Vec::new();
    for i in 0..TUBE_K {
        let t = i as f64 / (TUBE_K - 1) as f64 * (cen.len() - 1) as f64;
        let j = (t.floor() as usize).min(cen.len().saturating_sub(2));
        let u = if cen.len() > 1 { t - j as f64 } else { 0.0 };
        let (a, b) = (cen[j], cen[(j + 1).min(cen.len() - 1)]);
        ctrl.push([0, 1, 2].map(|k| a.0[k] * (1.0 - u) + b.0[k] * u));
        let n = a.1 as f64 * (1.0 - u) + b.1 as f64 * u;
        rad.push((n * voxel.powi(3) / (std::f64::consts::PI * band_len.max(voxel))).sqrt().max(0.01));
    }
    Inst::Tube { ctrl, rad }
}

/// X 거울 사본.
pub fn mirror_inst(i: &Inst) -> Inst {
    match i {
        Inst::Blob(v) => Inst::Blob(v.iter().map(|e| Ell { c: [-e.c[0], e.c[1], e.c[2]], r: e.r }).collect()),
        Inst::Tube { ctrl, rad } => Inst::Tube { ctrl: ctrl.iter().map(|c| [-c[0], c[1], c[2]]).collect(), rad: rad.clone() },
    }
}

pub fn expand(insts: &[Inst], mirror: bool) -> Vec<Inst> {
    let mut v = insts.to_vec();
    if mirror {
        v.extend(insts.iter().map(mirror_inst));
    }
    v
}

pub fn insts_to_json(fitted: &BTreeMap<String, Vec<Inst>>) -> Value {
    let mut out = Vec::new();
    for (p, is) in fitted {
        for i in is {
            out.push(match i {
                Inst::Blob(v) => json!({"부위": p, "종류": "Blob", "타원체": v.iter().map(|e| json!({"c": e.c, "r": e.r})).collect::<Vec<_>>()}),
                Inst::Tube { ctrl, rad } => json!({"부위": p, "종류": "Tube", "조절점": ctrl, "반지름": rad}),
            });
        }
    }
    Value::Array(out)
}

pub fn insts_from_json(v: &Value) -> BTreeMap<String, Vec<Inst>> {
    let f3 = |x: &Value| [x[0].as_f64().unwrap_or(0.0), x[1].as_f64().unwrap_or(0.0), x[2].as_f64().unwrap_or(0.0)];
    let mut out: BTreeMap<String, Vec<Inst>> = BTreeMap::new();
    for it in v.as_array().cloned().unwrap_or_default() {
        let p = it["부위"].as_str().unwrap_or("").to_string();
        let inst = if it["종류"] == "Tube" {
            Inst::Tube { ctrl: it["조절점"].as_array().unwrap().iter().map(f3).collect(), rad: it["반지름"].as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect() }
        } else {
            Inst::Blob(it["타원체"].as_array().unwrap().iter().map(|e| Ell { c: f3(&e["c"]), r: f3(&e["r"]) }).collect())
        };
        out.entry(p).or_default().push(inst);
    }
    out
}

/// 좌표 하강(모든 인스턴스의 매개변수를 한 벡터로).
fn descend(insts: &mut [Inst], views: &[ViewTarget], iters: usize, mirror: bool, prior: &dyn Fn(&[Inst]) -> f64) -> (f64, f64, usize) {
    let mut buf = Vec::new();
    // mirror: 짝 부위는 오른쪽(X>0)만 맞추고 왼쪽은 거울 사본으로 그린다(해부 규칙 짝_대칭, 항목 4b)
    let total = |insts: &[Inst], buf: &mut Vec<bool>| -> f64 {
        let all = expand(insts, mirror);
        let ells: Vec<Ell> = all.iter().flat_map(|i| i.ells()).collect();
        views.iter().map(|v| v.loss(&ells, buf)).sum::<f64>() + prior(insts)
    };
    let start = total(insts, &mut buf);
    let mut best = start;
    let mut scale = 1.0;
    let mut evals = 0usize;
    for _ in 0..iters {
        let mut improved = false;
        for ii in 0..insts.len() {
            let mut p = insts[ii].params();
            let st = insts[ii].steps();
            for k in 0..p.len() {
                for dir in [1.0, -1.0] {
                    let old = p[k];
                    p[k] = old + dir * st[k] * scale;
                    insts[ii].set(&p);
                    let l = total(insts, &mut buf);
                    evals += 1;
                    if l < best {
                        best = l;
                        improved = true;
                        break;
                    }
                    p[k] = old;
                    insts[ii].set(&p);
                }
            }
        }
        if !improved {
            scale *= 0.5;
            if scale < 0.1 {
                break;
            }
        }
    }
    (start, best, evals)
}

/// 맞추기 전체. masks: (뷰, 부위) → 마스크. 반환 (모든 도형, 정보).
pub fn fit_all(fr: &Frame, masks_in: &BTreeMap<(String, String), Mask2>, voxel: f64, iters: usize, rules: Option<&crate::anatomy::Rules>, depth_front: Option<&Vec<f64>>, kinds: Option<&BTreeMap<String, Kind>>) -> Result<(Vec<(String, Ell)>, Value, BTreeMap<String, Vec<Inst>>), String> {
    // 뷰 사이 세로 어긋남 보정(계획 A09 '뷰마다 작은 어긋남 허용', 항목 4b 2차): 손그림 모델 시트는 정면·옆 높이가
    // 다르게 그려진다(들소 13px). 강체 하나로 둘 다 맞추면 머리가 납작해지는 타협이 났다. 정면·옆 전경의 행 분포가
    // 가장 잘 겹치는 정수 이동(±30px)을 찾아 옆 마스크 전체를 옮기고, 그 값을 그림 모순으로 기록한다.
    let row_prof = |view: &str| -> Vec<bool> {
        let any = masks_in.values().next().unwrap();
        (0..any.h).map(|r| masks_in.iter().any(|((v, _), m)| v == view && (0..m.w).any(|c| m.get(r, c)))).collect()
    };
    let (pf, ps) = (row_prof("front"), row_prof("side"));
    let mut best = (0i64, -1.0f64);
    for k in -30i64..=30 {
        let (mut i, mut u) = (0usize, 0usize);
        for r in 0..pf.len() {
            let rs = r as i64 - k;
            let s = rs >= 0 && (rs as usize) < ps.len() && ps[rs as usize];
            i += (pf[r] && s) as usize;
            u += (pf[r] || s) as usize;
        }
        let j = i as f64 / u.max(1) as f64;
        if j > best.1 + 1e-12 || (j >= best.1 - 1e-12 && k.abs() < best.0.abs()) {
            best = (k, j);
        }
    }
    // 적용하지 않는다(추정만 기록): 들소에서 이동 0 으로 가설이 틀렸고, 옆 뷰 머리만 어긋난 과제(side_height)에서는
    // 뷰 전체를 옮겨 부피 0.881 → 0.774 로 망쳤다(항목 4c 진단, 4b (다) 회귀의 원인이었을 수 있음)
    let shift_est = best.0;
    let shift = 0i64;
    let masks: BTreeMap<(String, String), Mask2> = masks_in.iter().map(|((v, p), m)| {
        if v != "side" || shift == 0 {
            return ((v.clone(), p.clone()), m.clone());
        }
        let mut n = Mask2::new(m.h, m.w);
        for r in 0..m.h {
            let rs = r as i64 - shift;
            if rs >= 0 && (rs as usize) < m.h {
                for c in 0..m.w {
                    n.d[r * m.w + c] = m.get(rs as usize, c);
                }
            }
        }
        ((v.clone(), p.clone()), n)
    }).collect();
    let masks = &masks;
    // 정면·옆 중 한 뷰에라도 보이는 부위. 한 뷰에만 보이면(정면에서 몸통 뒤에 숨은 꼬리) 안 보이는 뷰는
    // '다른 부위 뒤 어딘가'로 초기값을 잡고, 그 뷰에서 다른 부위 밖으로 삐져나오면 벌점(빈 목표 + 상관없음 = 가린 부위들)
    let mut parts: Vec<String> = masks.keys().filter(|(v, _)| v == "front" || v == "side").map(|(_, p)| p.clone()).collect();
    parts.sort();
    parts.dedup();
    let any = masks.values().next().ok_or("마스크 없음")?;
    let empty = Mask2::new(any.h, any.w);
    let get = |v: &str, p: &str| -> Option<&Mask2> { masks.get(&(v.to_string(), p.to_string())).filter(|m| m.count() > 0) };
    let union = |view: &str, except: &str| -> Mask2 {
        let any = masks.values().next().unwrap();
        let mut m = Mask2::new(any.h, any.w);
        for ((v, p), mm) in masks {
            if v == view && p != except {
                for (a, b) in m.d.iter_mut().zip(&mm.d) {
                    *a |= *b;
                }
            }
        }
        m
    };
    // 1. 부위마다 헐 성분(초기값)
    let opt = HullOpt { voxel, smooth: 0.0, master_front: false, section_n: None };
    let mut comps: BTreeMap<String, Vec<Vec<[f64; 3]>>> = BTreeMap::new();
    let mut comp_cells: BTreeMap<String, Vec<Vec<[usize; 3]>>> = BTreeMap::new();
    for p in &parts {
        let uf = union("front", p);
        let us = union("side", p);
        let (mf, ms) = match (get("front", p), get("side", p)) {
            (Some(f), Some(s2)) => (f, s2),
            (Some(f), None) => (f, &us),
            (None, Some(s2)) => (&uf, s2),
            _ => continue,
        };
        let (inf, ins, xs, ys, zs, _) = match hull_axes(fr, mf, ms, &opt) { Ok(v) => v, Err(_) => continue };
        let vol = fill(&inf, &ins, zs.len(), None);
        let cs = components(&vol, 8);
        comps.insert(p.clone(), cs.iter().map(|c| c.iter().map(|q| [xs[q[0]], ys[q[1]], zs[q[2]]]).collect()).collect());
        comp_cells.insert(p.clone(), cs);
    }
    let center = |p: &str| -> Option<[f64; 3]> {
        let pts: Vec<&[f64; 3]> = comps.get(p)?.iter().flatten().collect();
        if pts.is_empty() { return None; }
        Some([0, 1, 2].map(|k| pts.iter().map(|q| q[k]).sum::<f64>() / pts.len() as f64))
    };
    // 2. 부위 순서: 덩어리(부모) → 관(뿔: 귀 규칙이 뿔 뿌리를 봄) → 판
    let mut order: Vec<String> = parts.clone();
    // 연산자: 설계도(LLM, MCP act_blueprint)가 정한 것이 있으면 그것, 없으면 이름표 기본값
    let kind_for = |p: &str| kinds.and_then(|k| k.get(p).copied()).unwrap_or_else(|| kind_of(p));
    order.sort_by_key(|p| match kind_for(p) { Kind::Blob => 0u8, Kind::Tube => 1, Kind::Plate => 2 });
    let mut fitted: BTreeMap<String, Vec<Inst>> = BTreeMap::new();
    let mut info = serde_json::Map::new();
    for p in &order {
        let Some(cs) = comps.get(p) else { continue };
        let kind = kind_for(p);
        let root = parent_of(p).and_then(|q| center(q)).unwrap_or([0.0, 0.0, 0.0]);
        let mk = |pts: &Vec<[f64; 3]>, cells: &Vec<[usize; 3]>| match kind {
            Kind::Tube => tube_init(pts, cells, voxel, root),
            _ => Inst::Blob(vec![ell_from_points(pts)]),
        };
        let is_pair = rules.map(|r| r.pairs.iter().any(|q| q == p)).unwrap_or(false);
        let mut insts: Vec<Inst> = if is_pair {
            // 짝 부위: 오른쪽(X>0) 성분 중 큰 것만(뿔·귀 1, 다리 2) 맞추고 왼쪽은 거울. 오른쪽이 없으면 왼쪽을 뒤집어 씀.
            // 두 뷰 헐이 만든 가짜 성분(들소 귀 4개)을 해부 규칙 짝_개수로 거른다
            let keep = if p == "다리" { 2 } else { 1 };
            let cx = |pts: &Vec<[f64; 3]>| pts.iter().map(|q| q[0]).sum::<f64>() / pts.len().max(1) as f64;
            let right: Vec<usize> = (0..cs.len()).filter(|&i| cx(&cs[i]) > 0.0).take(keep).collect();
            if !right.is_empty() {
                right.iter().map(|&i| mk(&cs[i], &comp_cells[p][i])).collect()
            } else {
                (0..cs.len()).take(keep).map(|i| mirror_inst(&mk(&cs[i], &comp_cells[p][i]))).collect()
            }
        } else {
            cs.iter().zip(&comp_cells[p]).map(|(pts, cells)| mk(pts, cells)).collect()
        };
        let ctx = fitted.clone();
        let pname = p.clone();
        let prior = move |is: &[Inst]| -> f64 { rules.map(|r| crate::anatomy::penalty(&pname, &expand(is, is_pair), &ctx, r)).unwrap_or(0.0) };
        let views: Vec<ViewTarget> = ["front", "side"].iter().filter_map(|v| {
            let occ = union(v, p);
            match get(v, p) {
                Some(m) => ViewTarget::new(fr, v, m, &occ, 12).map(|t| match (depth_front, kind, *v) {
                    (Some(d), Kind::Blob, "front") => t.with_depth(d, m.w),
                    _ => t,
                }),
                // 안 보이는 뷰: 목표는 비었고, 가린 부위들 위는 상관없음. 상자는 가린 부위 전체
                None => ViewTarget::new(fr, v, &occ, &occ, 12).map(|mut t| { t.target.iter_mut().for_each(|x| *x = false); t }),
            }
        }).collect();
        let _ = &empty;
        let (l0, mut l1, mut ev) = descend(&mut insts, &views, iters, is_pair, &prior);
        // 덩어리: 헐 칸 중 아직 안 덮인 큰 무리에 타원체를 하나씩 더함(최대 3개)
        if kind == Kind::Blob {
            for ci in 0..insts.len() {
                for _ in 0..2 {
                    let Inst::Blob(es) = &insts[ci] else { break };
                    let rest: Vec<[f64; 3]> = cs[ci].iter().filter(|q| !es.iter().any(|e| inside(e, **q, 1.0))).cloned().collect();
                    if rest.len() < cs[ci].len() / 12 || rest.len() < 30 {
                        break;
                    }
                    let mut es2 = es.clone();
                    es2.push(ell_from_points(&rest));
                    let backup = insts[ci].clone();
                    insts[ci] = Inst::Blob(es2);
                    let (_, l2, e2) = descend(&mut insts, &views, iters, is_pair, &prior);
                    ev += e2;
                    if l2 < l1 * 0.97 {
                        l1 = l2;
                    } else {
                        insts[ci] = backup;
                        break;
                    }
                }
            }
        }
        let insts = expand(&insts, is_pair);
        info.insert(p.clone(), json!({"연산자": format!("{:?}", kind), "개수": insts.len(), "짝_거울": is_pair, "손실_처음": l0, "손실_끝": l1, "평가": ev}));
        fitted.insert(p.clone(), insts);
    }
    // 3. 붙이기: 관 뿌리(조절점 0)를 부모 도형 안으로 잇는다. 목은 끝(마지막 조절점)도 머리로.
    let mut ells: Vec<(String, Ell)> = Vec::new();
    for (p, insts) in &fitted {
        for inst in insts {
            for e in inst.ells() {
                ells.push((p.clone(), e));
            }
        }
    }
    let mut links = 0;
    for (p, insts) in &fitted {
        let Some(par) = parent_of(p) else { continue };
        let pe: Vec<Ell> = ells.iter().filter(|(q, _)| q == par).map(|(_, e)| e.clone()).collect();
        if pe.is_empty() {
            continue;
        }
        for inst in insts {
            let Inst::Tube { ctrl, rad } = inst else { continue };
            let mut ends = vec![(ctrl[0], rad[0], &pe)];
            let he: Vec<Ell> = ells.iter().filter(|(q, _)| q == "머리").map(|(_, e)| e.clone()).collect();
            if p == "목" && !he.is_empty() {
                ends.push((ctrl[ctrl.len() - 1], rad[rad.len() - 1], &he));
            }
            for (a, r, tgt) in ends {
                if tgt.iter().any(|e| inside(e, a, 0.85)) {
                    continue;
                }
                // 가장 가까운 부모 도형 중심 쪽으로 구를 이어 안으로 들어갈 때까지
                let e = tgt.iter().min_by(|x, y| {
                    let d = |e: &Ell| (0..3).map(|k| ((a[k] - e.c[k]) / e.r[k]).powi(2)).sum::<f64>();
                    d(x).partial_cmp(&d(y)).unwrap()
                }).unwrap();
                // 연결 구 개수는 거리에 맞춘다: 20개 고정이면 먼 뿌리(꼬리)에서 구슬처럼 끊겼다(dev_1002)
                let dist = (0..3).map(|k| (e.c[k] - a[k]).powi(2)).sum::<f64>().sqrt();
                let steps = ((dist / (0.5 * r.max(0.008))).ceil() as usize).clamp(4, 400);
                for s in 1..=steps {
                    let t = s as f64 / steps as f64;
                    let q = [0, 1, 2].map(|k| a[k] + (e.c[k] - a[k]) * t);
                    ells.push((p.clone(), Ell { c: q, r: [r, r, r] }));
                    if inside(e, q, 0.85) {
                        break;
                    }
                }
                links += 1;
            }
        }
    }
    info.insert("_붙이기".into(), json!(links));
    info.insert("_뷰_어긋남_px".into(), json!({"옆_세로_이동_추정": shift_est, "적용": shift, "행_겹침": (best.1 * 1e4).round() / 1e4}));
    if let Some(r) = rules {
        info.insert("_해부".into(), crate::anatomy::check(&fitted, r));
    }
    Ok((ells, Value::Object(info), fitted))
}

/// 조립: SDF 합집합 → 표면(정답 메시와 같은 함수). 반환 메시.
/// 부드러운 합집합 조립(루프 항목 4c, Quilez smooth min 을 최댓값 쪽으로): 부위 안은 그냥 최댓값, 부위끼리는
/// 다항식 smooth max(이음 폭 k, H). 값은 거리 비슷하게 r_min·(1 − ‖(p−c)/r‖) 로 둔다(부위끼리 크기가 달라도 이음 폭이 같게).
pub fn assemble_smooth(ells: &[(String, Ell)], voxel: f64, k: f64) -> crate::mesh::Mesh {
    use crate::grid::Grid3;
    let mut lo = [f64::INFINITY; 3];
    let mut hi = [f64::NEG_INFINITY; 3];
    for (_, e) in ells {
        for a in 0..3 {
            lo[a] = lo[a].min(e.c[a] - e.r[a]);
            hi[a] = hi[a].max(e.c[a] + e.r[a]);
        }
    }
    let lo = lo.map(|x| x - 3.0 * voxel - k);
    let n = [0, 1, 2].map(|a| ((hi[a] + 3.0 * voxel + k - lo[a]) / voxel).ceil() as usize + 1);
    let mut parts: Vec<&str> = ells.iter().map(|(p, _)| p.as_str()).collect();
    parts.sort();
    parts.dedup();
    let mut total: Option<Grid3<f64>> = None;
    for part in parts {
        let mut g = Grid3::<f64>::new(n);
        g.d.iter_mut().for_each(|v| *v = -1.0);
        for (_, e) in ells.iter().filter(|(p, _)| p == part) {
            let rmin = e.r.iter().cloned().fold(f64::INFINITY, f64::min);
            let pad = k / rmin.max(1e-6) + 0.1;
            let a0 = [0, 1, 2].map(|a| ((e.c[a] - e.r[a] * (1.0 + pad) - lo[a]) / voxel).floor().max(0.0) as usize);
            let b0 = [0, 1, 2].map(|a| (((e.c[a] + e.r[a] * (1.0 + pad) - lo[a]) / voxel).ceil() as usize + 2).min(n[a]));
            for x in a0[0]..b0[0] {
                for y in a0[1]..b0[1] {
                    for z in a0[2]..b0[2] {
                        let q = [x, y, z];
                        let s: f64 = (0..3).map(|a| ((lo[a] + q[a] as f64 * voxel - e.c[a]) / e.r[a]).powi(2)).sum();
                        let i = g.idx(x, y, z);
                        g.d[i] = g.d[i].max(rmin * (1.0 - s.sqrt()));
                    }
                }
            }
        }
        total = Some(match total {
            None => g,
            Some(mut t) => {
                for (a, b) in t.d.iter_mut().zip(&g.d) {
                    let h = (k - (*a - *b).abs()).max(0.0) / k;
                    *a = a.max(*b) + h * h * k * 0.25;
                }
                t
            }
        });
    }
    crate::scene::field_to_mesh(total.unwrap(), lo, voxel)
}

pub fn assemble(ells: &[(String, Ell)], voxel: f64) -> crate::mesh::Mesh {
    let ps: Vec<P> = ells.iter().map(|(_, e)| P { c: e.c, r: e.r, part: "맞춤", mat: "털" }).collect();
    gt_mesh(&ps, voxel)
}
