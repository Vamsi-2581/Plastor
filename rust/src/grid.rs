//! 격자와 기본 연산: 2D 마스크, 3D 칸, numpy 와 같은 arange·searchsorted, scipy 와 같은 가우시안.

#[derive(Clone, Debug)]
pub struct Mask2 {
    pub h: usize,
    pub w: usize,
    pub d: Vec<bool>,
}

impl Mask2 {
    pub fn new(h: usize, w: usize) -> Self {
        Mask2 { h, w, d: vec![false; h * w] }
    }
    #[inline]
    pub fn get(&self, r: usize, c: usize) -> bool {
        self.d[r * self.w + c]
    }
    #[inline]
    pub fn set(&mut self, r: usize, c: usize, v: bool) {
        self.d[r * self.w + c] = v;
    }
    pub fn count(&self) -> usize {
        self.d.iter().filter(|&&x| x).count()
    }
    /// 픽셀 좌표(실수)를 floor 해서 본다. 밖이면 거짓(파이썬 hull._lookup).
    #[inline]
    pub fn lookup(&self, px: f64, py: f64) -> bool {
        let c = px.floor();
        let r = py.floor();
        if r < 0.0 || c < 0.0 || r >= self.h as f64 || c >= self.w as f64 {
            return false;
        }
        self.get(r as usize, c as usize)
    }
}

pub fn iou(a: &Mask2, b: &Mask2) -> f64 {
    let (mut i, mut u) = (0usize, 0usize);
    for (x, y) in a.d.iter().zip(&b.d) {
        i += (*x && *y) as usize;
        u += (*x || *y) as usize;
    }
    i as f64 / u.max(1) as f64
}

/// 3D 격자(x, y, z 순서, z 가 가장 빠름 = numpy C 순서).
#[derive(Clone, Debug)]
pub struct Grid3<T> {
    pub n: [usize; 3],
    pub d: Vec<T>,
}

impl<T: Copy + Default> Grid3<T> {
    pub fn new(n: [usize; 3]) -> Self {
        Grid3 { n, d: vec![T::default(); n[0] * n[1] * n[2]] }
    }
    #[inline]
    pub fn idx(&self, x: usize, y: usize, z: usize) -> usize {
        (x * self.n[1] + y) * self.n[2] + z
    }
    #[inline]
    pub fn get(&self, x: usize, y: usize, z: usize) -> T {
        self.d[self.idx(x, y, z)]
    }
    #[inline]
    pub fn set(&mut self, x: usize, y: usize, z: usize, v: T) {
        let i = self.idx(x, y, z);
        self.d[i] = v;
    }
}

/// numpy.arange(start, stop, step) 와 같은 값(버퍼 처음 두 값으로 delta 를 정하는 numpy 방식).
pub fn arange(start: f64, stop: f64, step: f64) -> Vec<f64> {
    let n = ((stop - start) / step).ceil().max(0.0) as usize;
    let second = start + step;
    let delta = second - start;
    (0..n).map(|i| if i == 0 { start } else if i == 1 { second } else { start + i as f64 * delta }).collect()
}

/// numpy.searchsorted(a, v, side='left')
pub fn searchsorted(a: &[f64], v: f64) -> usize {
    a.partition_point(|&x| x < v)
}

/// scipy.ndimage.gaussian_filter(차수 0, mode='reflect', truncate=4.0) 를 축마다.
pub fn gaussian3(g: &Grid3<f64>, sigma: f64) -> Grid3<f64> {
    let r = (4.0 * sigma + 0.5) as i64;
    let mut w: Vec<f64> = (-r..=r).map(|x| (-0.5 * (x * x) as f64 / (sigma * sigma)).exp()).collect();
    let s: f64 = w.iter().sum();
    w.iter_mut().for_each(|x| *x /= s);
    let mut cur = g.clone();
    for axis in 0..3 {
        let n = cur.n;
        let len = n[axis] as i64;
        let mut out = Grid3::<f64>::new(n);
        let refl = |i: i64| -> usize {
            // 'reflect': (d c b a | a b c d | d c b a)
            let p = 2 * len;
            let mut k = i.rem_euclid(p);
            if k >= len {
                k = p - 1 - k;
            }
            k as usize
        };
        for x in 0..n[0] {
            for y in 0..n[1] {
                for z in 0..n[2] {
                    let pos = [x, y, z];
                    let c = pos[axis] as i64;
                    let mut acc = 0.0;
                    for (k, wk) in w.iter().enumerate() {
                        let mut q = pos;
                        q[axis] = refl(c + k as i64 - r);
                        acc += wk * cur.get(q[0], q[1], q[2]);
                    }
                    out.set(x, y, z, acc);
                }
            }
        }
        cur = out;
    }
    cur
}
