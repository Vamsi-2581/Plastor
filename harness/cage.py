"""고리 케이지: 매개변수 → 정점·면 (좌우 대칭, 닫힘).

고리 R개(높이 z_i). 고리당 반쪽 점 M+2개(앞 중심 j=0 → 뒤 중심 j=M+1, 코사인 간격).
단면은 초타원: x(t) = a · w(t) · (1 - |t|^n)^(1/n), t = 앞(+1) → 뒤(-1) 정규화 앞뒤 위치.
정점 = 매개변수 위치 + 조각 오프셋 d[i, j](고리·점 번호로 저장되어 매개변수를 바꿔도 유지).
"""
import copy

import numpy as np

from .util import sha

M = 15          # 반쪽 중간 점 수(홀수여야 t=0 점이 있다 → 최대 반폭이 정확히 a·w(0))
K = 9           # 앞뒤 방향 폭 배수 제어점 수
SIDE = 2 * (M + 1)      # 고리 하나의 전체 정점 수
T_HALF = np.cos(np.pi * np.arange(M + 2) / (M + 1))      # 반쪽 점의 t (앞 +1 → 뒤 -1)
T_CTRL = np.cos(np.pi * np.arange(K) / (K - 1))          # 제어점 t (앞 +1 → 뒤 -1)

# 고리 하나의 정점 순서: 오른쪽 반쪽 j=0..M+1(앞 중심 → 뒤 중심) 다음 왼쪽 반쪽 j=M..1
RING_J = np.concatenate([np.arange(M + 2), np.arange(M, 0, -1)])
RING_SGN = np.concatenate([np.ones(M + 2), -np.ones(M)])


class Cage:
    def __init__(self, z, yf, yb, a, n=2.5, w=None, cx=None, cy=None, d=None, top_z=None, cap=True, name=''):
        R = len(z)
        self.z = np.array(z, float)
        self.yf = np.array(yf, float)
        self.yb = np.array(yb, float)
        self.a = np.array(a, float)
        self.n = np.full(R, n, float) if np.isscalar(n) else np.array(n, float)
        self.w = np.ones((R, K)) if w is None else np.array(w, float).reshape(R, K)
        self.cx = np.zeros(R) if cx is None else np.array(cx, float)
        self.cy = np.zeros(R) if cy is None else np.array(cy, float)
        self.d = np.zeros((R, M + 2, 3)) if d is None else np.array(d, float).reshape(R, M + 2, 3)
        self.top_z = float(top_z if top_z is not None else self.z[-1] + 0.05)
        self.dtop = np.zeros(3)
        self.dbot = np.zeros(3)
        self.cap = bool(cap)
        self.name = name

    # ------------------------------------------------------------ 저장·복사
    @property
    def R(self):
        return len(self.z)

    def copy(self):
        return copy.deepcopy(self)

    def to_dict(self):
        r = lambda x: np.round(np.asarray(x, float), 9).tolist()
        return {'name': self.name, 'M': M, 'K': K, 'top_z': round(self.top_z, 9), 'cap': self.cap,
                'z': r(self.z), 'yf': r(self.yf), 'yb': r(self.yb), 'a': r(self.a), 'n': r(self.n), 'w': r(self.w),
                'cx': r(self.cx), 'cy': r(self.cy), 'd': r(self.d), 'dtop': r(self.dtop), 'dbot': r(self.dbot)}

    @staticmethod
    def from_dict(o):
        assert o['M'] == M and o['K'] == K, '케이지 해상도(M,K)가 다르다'
        c = Cage(o['z'], o['yf'], o['yb'], o['a'], o['n'], o['w'], o['cx'], o['cy'], o['d'], o['top_z'], o['cap'], o.get('name', ''))
        c.dtop = np.array(o['dtop'], float)
        c.dbot = np.array(o['dbot'], float)
        return c

    def hash(self):
        return sha(self.to_dict())

    # ------------------------------------------------------------ 반쪽 점 위치(오프셋 전)
    def ring_half(self, i):
        """고리 i 의 오른쪽 반쪽 점 (M+2, 3). 오프셋 포함."""
        t = T_HALF
        wt = np.interp(t, T_CTRL[::-1], self.w[i][::-1])          # np.interp 는 x 오름차순 필요
        x = self.a[i] * wt * np.clip(1.0 - np.abs(t) ** self.n[i], 0.0, None) ** (1.0 / self.n[i])
        y = self.yb[i] + (t + 1.0) * 0.5 * (self.yf[i] - self.yb[i]) + self.cy[i]
        P = np.stack([self.cx[i] + x, y, np.full(M + 2, self.z[i])], 1)
        D = self.d[i].copy()
        D[0, 0] = 0.0                  # 중심선 위 점은 X 로 움직이지 않는다(대칭 유지)
        D[M + 1, 0] = 0.0
        return P + D

    # ------------------------------------------------------------ 메시
    def mesh(self):
        """V(N,3), F(T,3), info. 정점: 고리 0..R-1 각 SIDE 개, 그다음 위 꼭짓점, (아래 덮개 중심)."""
        R = self.R
        V = np.zeros((R * SIDE + 2, 3))
        ring_of = np.full(len(V), -1)
        j_of = np.full(len(V), -1)
        sgn_of = np.zeros(len(V))
        for i in range(R):
            H = self.ring_half(i)
            left = H[M:0:-1].copy()
            left[:, 0] = 2 * self.cx[i] - left[:, 0]       # 대칭면 x=cx 기준 거울
            V[i * SIDE: i * SIDE + M + 2] = H
            V[i * SIDE + M + 2: (i + 1) * SIDE] = left
            ring_of[i * SIDE:(i + 1) * SIDE] = i
            j_of[i * SIDE:(i + 1) * SIDE] = RING_J
            sgn_of[i * SIDE:(i + 1) * SIDE] = RING_SGN
        top = R * SIDE
        bot = R * SIDE + 1
        last, first = R - 1, 0
        V[top] = [self.cx[last], 0.5 * (self.yf[last] + self.yb[last]) + self.cy[last], self.top_z] + self.dtop
        V[bot] = [self.cx[first], 0.5 * (self.yf[first] + self.yb[first]) + self.cy[first], self.z[first]] + self.dbot
        ring_of[top], ring_of[bot] = -2, -3
        j_of[top], j_of[bot] = -2, -3
        sgn_of[top] = sgn_of[bot] = 1
        F = []
        for i in range(R - 1):
            b0, b1 = i * SIDE, (i + 1) * SIDE
            k = np.arange(SIDE)
            kn = (k + 1) % SIDE
            a, b, c, d = b0 + k, b0 + kn, b1 + kn, b1 + k
            F.append(np.stack([a, d, c], 1))
            F.append(np.stack([a, c, b], 1))
        k = np.arange(SIDE)
        kn = (k + 1) % SIDE
        F.append(np.stack([last * SIDE + kn, last * SIDE + k, np.full(SIDE, top)], 1))
        if self.cap:
            F.append(np.stack([first * SIDE + k, first * SIDE + kn, np.full(SIDE, bot)], 1))
        F = np.concatenate(F).astype(int)
        if not self.cap:
            keep = np.ones(len(V), bool)
            keep[bot] = False
            remap = np.cumsum(keep) - 1
            V, ring_of, j_of, sgn_of = V[keep], ring_of[keep], j_of[keep], sgn_of[keep]
            F = remap[F]
        return V, F, {'ring': ring_of, 'j': j_of, 'sgn': sgn_of}

    # ------------------------------------------------------------ 고리 단위 값(오프셋 포함) — fit·measure 용
    def ring_extents(self, i):
        """(앞끝 Y, 뒤끝 Y, 최대 반폭) 고리 i 의 실제 값."""
        H = self.ring_half(i)
        return float(H[:, 1].max()), float(H[:, 1].min()), float(np.abs(H[:, 0]).max())

    # ------------------------------------------------------------ 고리 추가·삭제
    def add_ring(self, z):
        if z <= self.z[0] or z >= self.z[-1]:
            raise ValueError('고리는 기존 고리 범위(%.3f~%.3f) 안에 넣는다' % (self.z[0], self.z[-1]))
        if np.any(np.abs(self.z - z) < 1e-4):
            raise ValueError('같은 높이에 이미 고리가 있다')
        k = int(np.searchsorted(self.z, z))             # 새 고리는 k-1 과 k 사이
        lo, hi = k - 1, k
        f = (z - self.z[lo]) / (self.z[hi] - self.z[lo])
        ins = lambda arr, new: np.insert(arr, k, new, axis=0)
        lerp = lambda arr: arr[lo] * (1 - f) + arr[hi] * f
        self.z = ins(self.z, z)
        self.yf = ins(self.yf, lerp(self.yf))
        self.yb = ins(self.yb, lerp(self.yb))
        self.a = ins(self.a, lerp(self.a))
        self.n = ins(self.n, lerp(self.n))
        self.w = ins(self.w, lerp(self.w))
        self.cx = ins(self.cx, lerp(self.cx))
        self.cy = ins(self.cy, lerp(self.cy))
        self.d = ins(self.d, lerp(self.d))
        return k

    def remove_ring(self, k):
        if self.R <= 3:
            raise ValueError('고리는 3개 이상 남겨야 한다')
        if not 0 <= k < self.R:
            raise ValueError('고리 번호 %d 가 범위 0~%d 밖이다' % (k, self.R - 1))
        for name in ('z', 'yf', 'yb', 'a', 'n', 'w', 'cx', 'cy', 'd'):
            setattr(self, name, np.delete(getattr(self, name), k, axis=0))


# ---------------------------------------------------------------- 메시 검사 (구조)
def edge_counts(F):
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e.sort(axis=1)
    u, c = np.unique(e, axis=0, return_counts=True)
    return u, c


def is_closed(F):
    _, c = edge_counts(F)
    return bool(np.all(c == 2))


def signed_volume(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)


def _seg_cross(p, q):
    """폐곡선 p(n,2)의 인접하지 않은 변끼리 교차하는 쌍의 수."""
    n = len(p)
    a, b = p, np.roll(p, -1, axis=0)
    cnt = 0
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            d1 = _orient(a[i], b[i], a[j])
            d2 = _orient(a[i], b[i], b[j])
            d3 = _orient(a[j], b[j], a[i])
            d4 = _orient(a[j], b[j], b[i])
            if d1 * d2 < 0 and d3 * d4 < 0:
                cnt += 1
    return cnt


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def ring_self_intersections(cage, V):
    """각 고리 평면 다각형이 자기 교차하는 고리 번호 목록."""
    bad = []
    for i in range(cage.R):
        P = V[i * SIDE:(i + 1) * SIDE, :2]
        if _seg_cross(P, None) > 0:
            bad.append(i)
    return bad
