"""모델러 명령 (손). 인자는 이름·범위·상대값뿐이고 좌표는 도면에서 계산한다.

각 함수는 케이지를 복사해 바꾼 새 케이지와 변경 요약(dict)을 돌려준다. 값 범위를 벗어나면 HarnessError(= ERROR).
"""
import numpy as np

from .cage import K, M, Cage
from .measure import model_landmark, unique_edges
from .util import HarnessError, check_range

N_RANGE = (1.6, 5.0)
STRENGTH = (0.0, 1.0)
FALLOFF = (0.05, 0.6)
WIDTH = (0.3, 1.5)


def _ring_mask(cage, z):
    if z is None:
        return np.ones(cage.R, bool)
    z0, z1 = sorted(z)
    m = (cage.z >= z0 - 1e-6) & (cage.z <= z1 + 1e-6)
    if not m.any():
        raise HarnessError('높이 범위 %.3f~%.3f 안에 고리가 없다(고리 높이 %.3f~%.3f)' % (z0, z1, cage.z[0], cage.z[-1]))
    return m


# ---------------------------------------------------------------- init
def op_init(pack, rings=None, z=None, n=2.5):
    """윤곽 행에서 고리를 만든다(반폭·앞끝·뒤끝 = 도면 값). 첫 블록아웃이 이미 정면·옆 윤곽에 맞는다."""
    check_range('n', n, *N_RANGE)
    za, zb = (pack.roi_z if z is None else tuple(sorted(z)))
    if rings is None:
        zs = np.round(pack.z[(pack.z >= za - 1e-9) & (pack.z <= zb + 1e-9)], 6)
    else:
        if rings < 3:
            raise HarnessError('고리는 3개 이상이어야 한다')
        zs = np.round(np.linspace(za, zb, int(rings)), 6)
    if len(zs) < 3:
        raise HarnessError('고리가 3개 미만이다')
    a = np.array([pack.edge('front', 'hwt', v) for v in zs])
    yf = np.array([pack.edge('side', 'hi', v) for v in zs])
    yb = np.array([pack.edge('side', 'lo', v) for v in zs])
    cage = Cage(zs, yf, yb, a, n=n, top_z=pack.top_z, name=pack.name)
    return cage, {'고리': len(zs), '높이': [float(zs[0]), float(zs[-1])]}


# ---------------------------------------------------------------- fit
def op_fit(cage, pack, view, z=None, strength=1.0, blend=0):
    check_range('strength', strength, *STRENGTH)
    if view not in ('front', 'side', 'back', 'width'):
        raise HarnessError("view 는 front|side|back|width 중 하나다(width = 정면·뒤 반폭 평균)")
    m = _ring_mask(cage, z)
    c = cage.copy()
    da = np.zeros(c.R)
    dyf = np.zeros(c.R)
    dyb = np.zeros(c.R)
    for i in np.flatnonzero(m):
        yf, yb, hw = c.ring_extents(i)
        if view == 'side':
            dyf[i] = pack.edge('side', 'hi', c.z[i]) - yf
            dyb[i] = pack.edge('side', 'lo', c.z[i]) - yb
        else:
            tgt = pack.edge(view if view != 'width' else 'front', 'hwt' if view == 'width' else 'hw', c.z[i])
            da[i] = (tgt / max(hw, 1e-6) - 1.0) * c.a[i]
    for _ in range(int(blend)):                           # 이웃 고리로 부드럽게
        for arr in (da, dyf, dyb):
            p = np.pad(arr, 1, mode='edge')
            arr[:] = 0.25 * p[:-2] + 0.5 * p[1:-1] + 0.25 * p[2:]
    c.a = np.maximum(c.a + strength * da, 1e-4)
    c.yf = c.yf + strength * dyf
    c.yb = c.yb + strength * dyb
    if np.any(c.yf <= c.yb):
        raise HarnessError('fit 결과 앞끝이 뒤끝보다 뒤에 있는 고리가 생긴다')
    return c, {'바뀐_고리': [int(i) for i in np.flatnonzero(m)], '최대_이동': float(max(np.abs(da).max(), np.abs(dyf).max(), np.abs(dyb).max()))}


# ---------------------------------------------------------------- snap
def _clamp_extreme(c, L, tgt, skip):
    """극점 규칙의 랜드마크가 옮긴 점 하나만 극점으로 남게, 이웃이 목표 값을 넘으면 목표 바로 아래로 눌러 준다.
    (이웃이 더 튀어나오면 규칙이 다른 정점을 고르기 때문이다.)"""
    if L['rule'] == 'extreme':
        ax = 'xyz'.index(L['dir'][1].lower())
        sgn = 1.0 if L['dir'][0] == '+' else -1.0
        lim = tgt['xyz'[ax]]
        near = lambda P: True
        zwin = L.get('z')
        latwin = L.get('y' if L['view'] == 'side' else 'x')
        latax = 1 if L['view'] == 'side' else 0
    elif L['rule'] == 'contour_at':
        ax = 1 if L['view'] == 'side' else 0
        sgn = 1.0 if L['edge'] in ('front', 'out', '+') else -1.0
        lim = tgt['xyz'[ax]]
        zwin = [L['z'] - 1e-6, L['z'] + 1e-6]      # 그 높이의 고리만(이웃 고리 폭을 누르지 않게)
        latwin, latax = None, ax
    else:
        return
    G = np.stack([c.ring_half(i) for i in range(c.R)])
    for i in range(c.R):
        for j in range(M + 2):
            if (i, j) == skip:
                continue
            P = G[i, j]
            if zwin is not None and not (zwin[0] - 1e-9 <= P[2] <= zwin[1] + 1e-9):
                continue
            if latwin is not None and not (latwin[0] - 1e-9 <= P[latax] <= latwin[1] + 1e-9):
                continue
            if ax == 0 and j in (0, M + 1):
                continue
            over = sgn * P[ax] - (sgn * lim - 1e-4)
            if over > 0:
                c.d[i, j, ax] -= sgn * over


def op_snap(cage, pack, name, falloff=0.15, iters=4):
    check_range('falloff', falloff, *FALLOFF)
    if name not in pack.landmarks:
        raise HarnessError('랜드마크 %s 가 팩에 없다(있는 것: %s)' % (name, ', '.join(pack.landmarks)))
    tgt = pack.landmark_target(name)
    if 'error' in tgt:
        raise HarnessError('랜드마크 %s 목표를 못 구했다: %s' % (name, tgt['error']))
    c = cage.copy()
    L = pack.landmarks[name]
    moved = None
    for _ in range(iters):
        V, F, info = c.mesh()
        E = unique_edges(F)
        mm = model_landmark(name, L, tgt, V, E, (pack.roi_z[0], pack.top_z))
        if mm is None:
            raise HarnessError('모델에서 랜드마크 %s 규칙에 맞는 점을 못 찾았다' % name)
        pos = np.array(mm['pos'])
        delta = np.zeros(3)
        for ax in tgt['axes']:
            k = 'xyz'.index(ax)
            delta[k] = tgt[ax] - pos[k]
        if np.linalg.norm(delta) < 1e-5:
            break
        idx = mm['idx']
        ring, j, sgn = int(info['ring'][idx]), int(info['j'][idx]), info['sgn'][idx]
        ref = V[idx].copy()
        ref[0] = abs(ref[0])                              # 오른쪽 반쪽 기준으로 환산
        dparam = delta.copy()
        if sgn < 0:
            dparam[0] = -dparam[0]
        # 오른쪽 반쪽 점·꼭짓점의 현재 위치와 거리 → 코사인 감쇠 가중치
        G = np.stack([c.ring_half(i) for i in range(c.R)])        # (R, M+2, 3)
        dist = np.linalg.norm(G - ref, axis=2)
        w = np.where(dist < falloff, 0.5 * (1 + np.cos(np.pi * np.clip(dist / falloff, 0, 1))), 0.0)
        c.d = c.d + w[:, :, None] * dparam
        for attr, vi in (('dtop', c.R * 2 * (M + 1)), ('dbot', c.R * 2 * (M + 1) + 1)):
            if vi >= len(V):
                continue
            d_ = np.linalg.norm(V[vi] - ref)
            if d_ < falloff:
                setattr(c, attr, getattr(c, attr) + 0.5 * (1 + np.cos(np.pi * d_ / falloff)) * dparam)
        _clamp_extreme(c, L, tgt, (ring, j) if ring >= 0 else None)
        if moved is None:
            moved = {'정점': {'고리': ring, '점': j}, '이동': [round(float(v), 4) for v in delta]}
        if L['rule'] == 'manual':
            break
    if moved is None:
        moved = {'이동': [0.0, 0.0, 0.0], '메모': '이미 목표에 있다'}
    return c, moved


# ---------------------------------------------------------------- round / narrow / shift / smooth
def op_round(cage, z, n):
    check_range('n', n, *N_RANGE)
    m = _ring_mask(cage, z)
    c = cage.copy()
    c.n[m] = n
    return c, {'바뀐_고리': [int(i) for i in np.flatnonzero(m)]}


def _front_taper():
    """앞쪽 폭 배수의 적용 비중: 앞 3개 제어점은 전부, 4번째는 절반, 중앙(최대 폭 점)과 뒤쪽은 0.
    중앙 폭이 그대로라서 정면·옆 윤곽은 변하지 않는다."""
    f = np.zeros(K)
    f[:3] = 1.0
    f[3] = 0.5
    return f


def op_narrow(cage, pack, part=None, width=None, from_landmark=None, z=None):
    c = cage.copy()
    if part is not None:
        if part not in pack.parts:
            raise HarnessError('부위 %s 가 팩에 없다(있는 것: %s)' % (part, ', '.join(pack.parts)))
        zr = pack.parts[part]['z']
    elif z is not None:
        zr = z
    else:
        raise HarnessError('--part 또는 --z 가 필요하다')
    if z is not None and part is not None:
        zr = z
    m = _ring_mask(c, zr)
    if from_landmark is not None:
        tgt = pack.landmark_target(from_landmark)
        if tgt.get('x') is None:
            raise HarnessError('랜드마크 %s 는 정면 가로(X) 목표가 없다' % from_landmark)
        i = int(np.argmin(np.abs(c.z - tgt['z'])))
        width = float(np.clip(abs(tgt['x']) / max(c.ring_extents(i)[2], 1e-6), *WIDTH))
    if width is None:
        raise HarnessError('--width 또는 --from-landmark 가 필요하다')
    check_range('width', width, *WIDTH)
    f = _front_taper()
    c.w[m] = 1.0 + (width - 1.0) * f
    return c, {'바뀐_고리': [int(i) for i in np.flatnonzero(m)], 'width': round(float(width), 4)}


def op_shift(cage, z, dy=0.0, tilt=0.0):
    m = _ring_mask(cage, z)
    c = cage.copy()
    zc = 0.5 * (c.z[m].min() + c.z[m].max())
    c.cy[m] += dy + np.tan(np.radians(tilt)) * (c.z[m] - zc)
    return c, {'바뀐_고리': [int(i) for i in np.flatnonzero(m)]}


def op_smooth(cage, z, k=0.5):
    check_range('k', k, 0.0, 1.0)
    m = _ring_mask(cage, z)
    c = cage.copy()
    m[0] = m[-1] = False
    for name in ('yf', 'yb', 'a', 'n', 'cy', 'cx', 'w', 'd'):
        arr = getattr(c, name)
        src = arr.copy()
        for i in np.flatnonzero(m):
            arr[i] = src[i] + k * (0.5 * (src[i - 1] + src[i + 1]) - src[i])
    return c, {'바뀐_고리': [int(i) for i in np.flatnonzero(m)]}


def op_add_ring(cage, z):
    c = cage.copy()
    try:
        k = c.add_ring(float(z))
    except ValueError as e:
        raise HarnessError(str(e))
    return c, {'새_고리_번호': k, '고리_수': c.R}


def op_remove_ring(cage, i):
    c = cage.copy()
    try:
        c.remove_ring(int(i))
    except ValueError as e:
        raise HarnessError(str(e))
    return c, {'고리_수': c.R}
