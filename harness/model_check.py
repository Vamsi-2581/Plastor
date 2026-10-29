# -*- coding: utf-8 -*-
"""3D 모델 검사: 만든 메시를 도면 뷰에 다시 비춰(재투영) 부위·뷰마다 트레이스와 비교하고, 틀린 원인을 3D 모델링 말로 나눈다.
일반 최적화 루프(숫자 하나 줄이기)와 다른 점: 오차가 '그림 모순'(뷰끼리 안 맞음, 모델이 둘 다 맞출 수 없음)인지,
'모델링 오차'인지, '상자 단면'(헐이 판자처럼 됨, 3/4 에서만 보임)인지, '떠 있는 조각'인지 가른다.
근거: ModelSheetTo3D(Eurographics 2026, 손그림 뷰 불일치), 3DCodeBench(2026, 떠 있는 조각이 흔한 실패),
비주얼 헐 단면 한계(Kim 외 2013). docs/자유조사_2026-10-29.md.
메시는 X 오른쪽·Y 앞·Z 위(H 단위). 복셀은 X 방향 광선의 교차 홀짝으로 채운다(닫힌 메시 가정).
"""
import os

import numpy as np

from . import vendor  # noqa: F401
from .vendor import ndi

TOL_PX = 3            # 높이 일치 허용(trace_loop 과 같은 값)
OK_IOU = 0.95         # 재투영 IoU 이 이상이면 통과
BOX_FILL = 0.90       # 단면 채움비(단면 넓이 ÷ 두 뷰 폭의 곱). 타원 0.785, 상자 1.0
LONG = 2.5            # 이 길쭉함(가장 긴 축 ÷ 나머지 평균) 이상인 부위만 단면을 본다(뿔·꼬리 같은 관)


def load_obj(path):
    V, F = [], []
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            if ln.startswith('v '):
                V.append([float(x) for x in ln.split()[1:4]])
            elif ln.startswith('f '):
                idx = [int(t.split('/')[0]) - 1 for t in ln.split()[1:]]
                for k in range(1, len(idx) - 1):
                    F.append([idx[0], idx[k], idx[k + 1]])
    return np.array(V, float), np.array(F, int)


_MH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')


def voxelize(V, F, voxel):
    """닫힌 메시 → 복셀 격자. 반환 (occ[nx,ny,nz], 원점(x0,y0,z0)).
    Rust 판(rust/, `mh voxsil`)이 있으면 그것을 쓴다: 칸 단위로 같고(tests/selftest_rust.py) 80~170 배 빠르다.
    환경 변수 MH_RUST=0 이면 파이썬판."""
    if os.environ.get('MH_RUST', '1') != '0' and os.path.exists(_MH) and len(F):
        import json
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            vp, fp, dump = os.path.join(d, 'v.npy'), os.path.join(d, 'f.npy'), os.path.join(d, 'o')
            np.save(vp, np.ascontiguousarray(V, dtype=np.float64))
            np.save(fp, np.ascontiguousarray(F, dtype=np.int64))
            r = subprocess.run([_MH, 'voxsil', json.dumps({'verts_npy': vp, 'faces_npy': fp, 'voxel': float(voxel), 'dump': dump})],
                               capture_output=True, text=True, encoding='utf-8')
            if r.returncode == 0:
                lo = np.array(json.loads(r.stdout)['요약']['원점'], float)
                return np.load(dump + '_occ.npy'), lo
    return _voxelize_py(V, F, voxel)


def _voxelize_py(V, F, voxel):
    """파이썬판(기준). 닫힌 메시 → 복셀 격자. 반환 (occ[nx,ny,nz], 원점(x0,y0,z0))."""
    lo, hi = V.min(0) - 2 * voxel, V.max(0) + 2 * voxel
    # 광선을 격자에서 조금 비켜 쏜다: 복셀 메시(marching cubes)는 꼭짓점·모서리가 반 칸 격자에 놓여,
    # 광선이 모서리를 정확히 지나면 교차가 두 번 세어져 홀짝이 뒤집혔다(들소 둥근 뿔 정면 0.499, 두 뿔 사이가 채워짐)
    ys = np.arange(lo[1], hi[1], voxel) + voxel * 0.5 + voxel * 0.0137
    zs = np.arange(lo[2], hi[2], voxel) + voxel * 0.5 + voxel * 0.0291
    nx = int(np.ceil((hi[0] - lo[0]) / voxel))
    hits = {}
    T = V[F]
    for t in T:
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = t
        d = (y1 - y0) * (z2 - z0) - (y2 - y0) * (z1 - z0)
        if abs(d) < 1e-12:
            continue
        j0, j1 = np.searchsorted(ys, min(y0, y1, y2)), np.searchsorted(ys, max(y0, y1, y2))
        k0, k1 = np.searchsorted(zs, min(z0, z1, z2)), np.searchsorted(zs, max(z0, z1, z2))
        if j1 <= j0 or k1 <= k0:
            continue
        gy, gz = np.meshgrid(ys[j0:j1], zs[k0:k1], indexing='ij')
        a = ((gy - y0) * (z2 - z0) - (y2 - y0) * (gz - z0)) / d
        b = ((y1 - y0) * (gz - z0) - (gy - y0) * (z1 - z0)) / d
        ins = (a >= 0) & (b >= 0) & (a + b < 1)
        if not ins.any():
            continue
        xs = x0 + a * (x1 - x0) + b * (x2 - x0)
        for (jj, kk), x in zip(np.argwhere(ins), xs[ins]):
            hits.setdefault((j0 + jj, k0 + kk), []).append(x)
    occ = np.zeros((nx, len(ys), len(zs)), bool)
    for (j, k), xl in hits.items():
        xl = np.sort(np.array(xl))
        for a, b in zip(xl[0::2], xl[1::2]):
            i0, i1 = int(np.ceil((a - lo[0]) / voxel - 0.5)), int(np.floor((b - lo[0]) / voxel - 0.5))
            if i1 >= i0:
                occ[max(i0, 0):i1 + 1, j, k] = True
    return occ, lo


def project(occ, lo, voxel, pack, view, shape):
    """복셀 → 도면 픽셀 마스크(정사영, 투영 v2). 정면·뒤는 Y 로, 옆은 X 로 눌러 본다.
    칸 기둥의 실제 사각 발자국이 픽셀을 덮는 넓이를 더해 절반 이상이면 칠한다(정답 마스크의 '절반 이상' 규칙과 같게).
    v1(칸마다 3x3 점)은 칸 ≈ 1px 에서 가장자리를 1px 줄씩 부풀렸다(모델만 261·도면만 0, 수정_기록 47·48)."""
    sil = occ.any(1) if view in ('front', 'back') else occ.any(0)        # (가로칸, nz)
    li, zi = np.nonzero(sil)
    lat0 = lo[0] if view in ('front', 'back') else lo[1]
    xa, ya = pack.H_to_px(view, lat0 + li * voxel, lo[2] + zi * voxel)
    xb, yb = pack.H_to_px(view, lat0 + (li + 1) * voxel, lo[2] + (zi + 1) * voxel)
    x0, x1 = np.minimum(xa, xb), np.maximum(xa, xb)
    y0, y1 = np.minimum(ya, yb), np.maximum(ya, yb)
    cov = np.zeros(shape, float)
    k = int(np.ceil(float(np.max(x1 - x0)) if len(li) else 1.0)) + 1
    bx, by = np.floor(x0).astype(int), np.floor(y0).astype(int)
    for dx in range(k):
        for dy in range(k):
            c, r = bx + dx, by + dy
            ox = np.minimum(x1, c + 1) - np.maximum(x0, c)
            oy = np.minimum(y1, r + 1) - np.maximum(y0, r)
            ok = (ox > 0) & (oy > 0) & (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1])
            np.add.at(cov, (r[ok], c[ok]), (ox * oy)[ok])
    return cov >= 0.5 - 1e-9


def project_v1(occ, lo, voxel, pack, view, shape):
    """옛 투영(v1, 칸마다 3x3 점). 기록·비교용."""
    sil = occ.any(1) if view in ('front', 'back') else occ.any(0)
    li, zi = np.nonzero(sil)
    lat0 = lo[0] if view in ('front', 'back') else lo[1]
    m = np.zeros(shape, bool)
    for du in (0.17, 0.5, 0.83):
        for dv in (0.17, 0.5, 0.83):
            px, py = pack.H_to_px(view, lat0 + (li + du) * voxel, lo[2] + (zi + dv) * voxel)
            c, r = np.floor(px).astype(int), np.floor(py).astype(int)
            ok = (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1])
            m[r[ok], c[ok]] = True
    return m


def iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


def rows_of(m):
    r = np.flatnonzero(m.any(1))
    return (int(r.min()), int(r.max())) if len(r) else None


def section_fill(occ, voxel):
    """길쭉한 부위의 단면 채움비(중앙값). 가장 긴 축에 수직인 단면마다 넓이 ÷ (두 방향 폭의 곱)."""
    idx = np.argwhere(occ)
    if len(idx) < 20:
        return None, None
    ext = idx.max(0) - idx.min(0) + 1
    ax = int(np.argmax(ext))
    long_ratio = ext[ax] / max(np.mean([ext[i] for i in range(3) if i != ax]), 1)
    if long_ratio < LONG:
        return None, round(float(long_ratio), 2)
    vals = []
    for s in range(occ.shape[ax]):
        sl = np.take(occ, s, axis=ax)
        if sl.sum() < 6:
            continue
        r, c = np.nonzero(sl)
        box = (r.max() - r.min() + 1) * (c.max() - c.min() + 1)
        vals.append(sl.sum() / box)
    if not vals:
        return None, round(float(long_ratio), 2)
    return round(float(np.median(vals)), 3), round(float(long_ratio), 2)


def merged_check(V, F):
    """합친 메시 검사(trimesh, MIT): 몸 수, 닫힘, 오일러 수. 겹쳐 있기만 하고 합쳐지지 않은 조각을 찾는다.
    (들소 14차: 복셀 검사는 '떠 있는 조각 없음'이었지만 trimesh 로 보니 따로 닫힌 조각 5개였다. 겹쳐 닿아 보였을 뿐 불리언이 안 됐다)"""
    import trimesh
    m = trimesh.Trimesh(V, F, process=True)
    bodies = m.split(only_watertight=False)
    r = {'몸_수': len(bodies), '닫힘': bool(m.is_watertight), '오일러': int(m.euler_number), '진단': []}
    if len(bodies) > 1:
        r['진단'].append({'종류': '합쳐지지 않음', '설명': '따로 닫힌 조각 %d개(정점 %s). 불리언 합치기가 안 됐다' % (len(bodies), sorted(len(b.vertices) for b in bodies))})
    if not m.is_watertight:
        r['진단'].append({'종류': '열린 메시', '설명': '닫히지 않은 메시(구멍 또는 겹친 면)'})
    return r


def check(pack, parts, trace, views=('front', 'side'), voxel=0.008, shape=None):
    """parts {부위: (V, F)}, trace {(뷰, 부위): 마스크}. 반환 {'부위': {...}, '떠있는_조각': [...]}."""
    shape = shape or next(iter(trace.values())).shape
    out, occs = {}, {}
    for p, (V, F) in parts.items():
        occ, lo = voxelize(V, F, voxel)
        occs[p] = (occ, lo)
        r = {'뷰': {}, '진단': []}
        tr = {v: trace.get((v, p)) for v in views}
        for v in views:
            if tr[v] is None or not tr[v].any():
                continue
            pm = project(occ, lo, voxel, pack, v, shape)
            # 가림: 그 뷰에서 다른 부위로 트레이스된 자리는 이 부위가 뒤에 숨어 있을 수 있다(들소 옆 머리가 뿔·귀 밑으로 이어짐).
            # 모델이 그 자리에 있는 것은 오차로 세지 않는다. 트레이스에 있는데 모델에 없는 것은 언제나 오차.
            occl = np.zeros(shape, bool)
            for (vv, q), m in trace.items():
                if vv == v and q != p:
                    occl |= m
            pmv = pm & ~(occl & ~tr[v])
            r['뷰'][v] = {'IoU': round(iou(pmv, tr[v]), 3), '가림_제외_px': int((pm & occl & ~tr[v]).sum()),
                          '모델_행': rows_of(pm), '트레이스_행': rows_of(tr[v]), '_xor': pmv ^ tr[v]}
        # 그림 모순: 트레이스끼리 높이가 안 맞는 행(한 뷰에만 부위가 있는 행)
        have = [v for v in views if tr[v] is not None and tr[v].any()]
        only = np.zeros(shape[0], bool)
        if len(have) >= 2:
            rows = {v: tr[v].any(1) for v in have}
            for v in have:
                only |= rows[v] & ~np.logical_and.reduce([rows[u] for u in have if u != v])
            r['트레이스_높이차_px'] = int(only.sum())
        for v, d in r['뷰'].items():
            xor = d.pop('_xor')
            if d['IoU'] >= OK_IOU:
                continue
            share = float(xor[only].sum() / max(xor.sum(), 1))
            d['모순행_오차비'] = round(share, 2)
            if r.get('트레이스_높이차_px', 0) > TOL_PX and share >= 0.5:
                r['진단'].append({'종류': '그림 모순', '뷰': v, '설명': '뷰끼리 높이가 %dpx 다르고 오차의 %d%% 가 그 행에 있다' % (r['트레이스_높이차_px'], share * 100)})
            else:
                r['진단'].append({'종류': '모델링 오차', '뷰': v, '설명': 'IoU %.3f, 뷰가 서로 맞는 행에서 틀림' % d['IoU']})
        fill, lr = section_fill(occ, voxel)
        r['단면_채움비'], r['길쭉함'] = fill, lr
        if fill is not None and fill >= BOX_FILL:
            r['진단'].append({'종류': '상자 단면', '설명': '단면 채움비 %.2f(타원 0.79, 상자 1.0). 3/4 에서 판자처럼 보인다' % fill})
        out[p] = r
    # 떠 있는 조각: 모든 부위를 한 격자에 모아 연결 성분
    lo = np.min([o[1] for o in occs.values()], 0)
    hi = np.max([o[1] + np.array(o[0].shape) * voxel for o in occs.values()], 0)
    G = np.zeros(tuple(np.ceil((hi - lo) / voxel).astype(int) + 1), np.int16)
    for i, (p, (occ, l)) in enumerate(occs.items()):
        o = np.round((l - lo) / voxel).astype(int)
        sub = G[o[0]:o[0] + occ.shape[0], o[1]:o[1] + occ.shape[1], o[2]:o[2] + occ.shape[2]]
        sub[occ[:sub.shape[0], :sub.shape[1], :sub.shape[2]]] = i + 1
    # 넓히지 않고 맞닿은 칸(26 이웃)만 이어진 것으로 본다. 한 칸 넓혔을 때 2~5px 틈을 '닿음'으로 셌다(들소 14차)
    lab, n = ndi.label(G > 0, structure=np.ones((3, 3, 3)))
    floating = []
    if n > 1:
        sizes = ndi.sum(G > 0, lab, range(1, n + 1))
        main = int(np.argmax(sizes)) + 1
        names = list(occs)
        for c in range(1, n + 1):
            if c == main or sizes[c - 1] == 0:
                continue
            ids = np.unique(G[(lab == c) & (G > 0)])
            floating.append({'부위': [names[i - 1] for i in ids], '복셀': int(sizes[c - 1])})
            for i in ids:
                out[names[i - 1]]['진단'].append({'종류': '떠 있는 조각', '설명': '본체와 닿지 않음(%d 복셀)' % sizes[c - 1]})
    return {'부위': out, '떠있는_조각': floating}
