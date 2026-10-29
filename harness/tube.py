# -*- coding: utf-8 -*-
"""뿔·귀처럼 고리 케이지(높이별 대칭 단면 하나)로 못 만드는 부위를 위한 관(tube) 생성.
도면 분해선의 부위 다각형에서: 정면 다각형 → 높이별 좌우 섬(섬마다 중심 x·반폭), 옆 다각형 → 높이별 앞뒤 중심 y·반두께.
섬마다 높이 방향으로 타원 고리를 쌓고 양 끝을 닫는다(윤곽이 도면과 같은 규칙에서 나온다. 좌표를 손으로 쓰지 않는다).
높이에 대해 한 값씩인 부위만 다룬다(안쪽으로 되접히는 모양은 못 만든다).
"""
import json
import os
import sys

import numpy as np


def _mask(T, bun, view, part, shape=(1024, 1536)):
    m = np.zeros(shape, bool)
    for it in bun['panels'][view]['parts']:
        if it['name'] == part:
            for poly in it['polys']:
                T.fill_poly(m, [tuple(p) for p in poly['pts']])
    return m


def _runs(row):
    idx = np.flatnonzero(row)
    if len(idx) == 0:
        return []
    cuts = np.flatnonzero(np.diff(idx) > 1)
    st = np.r_[idx[0], idx[cuts + 1]]
    en = np.r_[idx[cuts], idx[-1]]
    return [(int(a), int(b) + 1) for a, b in zip(st, en)]


def build_tube(pack, bun, part, T, step=0.02, nseg=16, min_hw=0.004, masks=None):
    """pack: harness.pack.Pack, bun: 분해선 json, T: ref_trace_common(fill_poly). 반환 V, F (H 단위, 좌우 섬 모두)."""
    if masks is not None:                          # trace.py 결과(뷰|부위 → 마스크)를 쓴다
        mf, ms = masks['front|' + part], masks['side|' + part]
    else:
        mf, ms = _mask(T, bun, 'front', part), _mask(T, bun, 'side', part)
    fr = np.flatnonzero(mf.any(1))
    sr = np.flatnonzero(ms.any(1))
    zlo = max((pack.ground - fr.max()) / pack.ppH, (pack.ground - sr.max()) / pack.ppH)
    zhi = min((pack.ground - fr.min()) / pack.ppH, (pack.ground - sr.min()) / pack.ppH)
    zs = np.arange(zlo + 0.005, zhi - 0.005, step)
    islands = {}                                   # 부호(+1 오른쪽/-1 왼쪽) → [(z, xc, a, yc, b)]
    for z in zs:
        row = int(round(pack.ground - z * pack.ppH))
        sx = _runs(ms[row])
        if not sx:
            continue
        ylo, yhi = pack.px_to_H('side', sx[0][0], 0)[0], pack.px_to_H('side', sx[-1][1], 0)[0]
        ylo, yhi = min(ylo, yhi), max(ylo, yhi)
        for a0, a1 in _runs(mf[row]):
            x0, x1 = pack.px_to_H('front', a0, 0)[0], pack.px_to_H('front', a1, 0)[0]
            x0, x1 = min(x0, x1), max(x0, x1)
            xc = 0.5 * (x0 + x1)
            sg = 1 if xc > 0 else -1
            islands.setdefault(sg, []).append((float(z), float(xc), max(0.5 * (x1 - x0), min_hw), 0.5 * (ylo + yhi), max(0.5 * (yhi - ylo), min_hw)))
    # 좌우 대칭: 오른쪽(+x) 섬 하나를 만들고 거울로 붙인다. 같은 높이에 왼쪽 섬도 있으면 두 섬의 평균을 쓰고, 좌우 도면 차이를 보고한다.
    R_, L_ = {r[0]: r for r in islands.get(1, [])}, {r[0]: r for r in islands.get(-1, [])}
    rows, gap = [], 0.0
    for z in sorted(set(R_) | set(L_)):
        if z in R_ and z in L_:
            (_, xr, ar, yr, br), (_, xl, al, yl, bl) = R_[z], L_[z]
            gap = max(gap, abs(xr + xl), abs(ar - al))
            rows.append((z, 0.5 * (xr - xl), 0.5 * (ar + al), yr, br))
        else:
            r = R_.get(z) or L_[z]
            rows.append((z, abs(r[1]), r[2], r[3], r[4]))
    if len(rows) < 3:
        return np.zeros((0, 3)), np.zeros((0, 3), int), {'rows': len(rows)}
    th = np.linspace(0, 2 * np.pi, nseg, endpoint=False)
    V, F = [], []
    n = len(rows)
    for z, xc, a, yc, b in rows:
        for t in th:
            V.append([xc + a * np.cos(t), yc + b * np.sin(t), z])
    for i in range(n - 1):
        for j in range(nseg):
            p, q = i * nseg + j, i * nseg + (j + 1) % nseg
            r, s2 = (i + 1) * nseg + j, (i + 1) * nseg + (j + 1) % nseg
            F += [(p, r, s2), (p, s2, q)]
    for end, flip in ((0, True), (n - 1, False)):
        z, xc, a, yc, b = rows[end]
        c = len(V)
        V.append([xc, yc, z + (-0.005 if end == 0 else 0.005)])
        for j in range(nseg):
            p, q = end * nseg + j, end * nseg + (j + 1) % nseg
            F.append((c, q, p) if flip else (c, p, q))
    V = np.array(V, float)
    F = np.array(F, int)
    vol = np.einsum('ij,ij->i', V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])).sum()
    if vol < 0:
        F = F[:, ::-1]
    Vm = V * np.array([-1.0, 1.0, 1.0])
    Fm = F[:, ::-1] + len(V)                       # 거울이면 면 방향이 뒤집히므로 다시 뒤집는다
    return np.concatenate([V, Vm]), np.concatenate([F, Fm]), {'행': n, '좌우_도면_최대차': round(float(gap), 4)}
