# -*- coding: utf-8 -*-
"""길쭉한 부위(뿔·꼬리·다리)를 중심선 + 타원 단면 쓸기로 만든다. 비주얼 헐은 두 뷰 실루엣은 맞지만 단면이 상자가 된다
(들소 뿔: 위에서 보면 직사각형 덩어리). 둥근 단면 사전(Kim 외 2013, Tai 외 2004)을 넣는 방법이다.
1) 헐 복셀을 만든다(두 뷰 실루엣의 교집합 = 단면 폭의 근거).
2) 뿌리(본체 쪽 끝)에서 헐 안쪽으로만 퍼지는 거리(측지 거리)를 잰다. 같은 거리 띠 = 관을 가로로 자른 조각.
3) 띠마다 중심(중심선 점)과, 중심선에 수직인 두 축 방향 반폭을 잰다. 그 반폭의 타원 = 단면.
4) 타원 고리들을 이어 닫힌 관 메시. 끝은 한 점으로 모은다.
헐 단면의 반폭을 그대로 쓰므로 축이 뷰 방향과 맞는 곳에서는 실루엣 폭이 보존된다(휜 곳은 근사).
"""
import numpy as np

from . import vendor  # noqa: F401
from .vendor import ndi


def hull_occ(pack, mask_front, mask_side, voxel=0.008, master='front'):
    """build_hull 과 같은 규칙의 복셀(다듬기·면 뽑기 전). 반환 (occ, (xs, ys, zs))."""
    rf, rs = np.nonzero(mask_front), np.nonzero(mask_side)
    xf, zf = pack.px_to_H('front', rf[1] + 0.5, rf[0] + 0.5)
    ys, zs = pack.px_to_H('side', rs[1] + 0.5, rs[0] + 0.5)
    pad = 2 * voxel
    X_ = np.arange(xf.min() - pad, xf.max() + pad, voxel)
    Y_ = np.arange(ys.min() - pad, ys.max() + pad, voxel)
    Z_ = np.arange(zf.min() - pad, zf.max() + pad, voxel) if master == 'front' else \
        np.arange(max(zf.min(), zs.min()) - pad, min(zf.max(), zs.max()) + pad, voxel)
    from .hull import _lookup
    X, Z = np.meshgrid(X_, Z_, indexing='ij')
    inf = _lookup(mask_front, *pack.H_to_px('front', X, Z))
    Y, Z2 = np.meshgrid(Y_, Z_, indexing='ij')
    ins = _lookup(mask_side, *pack.H_to_px('side', Y, Z2))
    if master == 'front':
        has = ins.any(0)
        if has.any():
            idx = np.flatnonzero(has)
            for zi in np.flatnonzero(~has & inf.any(0)):
                ins[:, zi] = ins[:, idx[np.argmin(np.abs(idx - zi))]]
    return inf[:, None, :] & ins[None, :, :], (X_, Y_, Z_)


def _geodesic(occ, seed):
    """seed 에서 occ 안으로만 퍼지는 걸음 수(26 이웃 파도). 닿지 않는 칸은 -1."""
    d = np.full(occ.shape, -1, int)
    front = seed & occ
    d[front] = 0
    seen = front.copy()
    st = np.ones((3, 3, 3), bool)
    k = 0
    while front.any():
        k += 1
        nxt = ndi.binary_dilation(front, st) & occ & ~seen
        d[nxt] = k
        seen |= nxt
        front = nxt
    return d


def _tube(rings, tip):
    """rings: [(중심, u, v, a, b)] 뿌리→끝. 각 고리 n 점, 마지막에 끝점."""
    n = 24
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    V, F = [], []
    for c, u, v, a, b in rings:
        V.extend(c + a * np.cos(t)[:, None] * u + b * np.sin(t)[:, None] * v)
    V = np.array(V)
    R = len(rings)
    for r in range(R - 1):
        for i in range(n):
            a0, a1 = r * n + i, r * n + (i + 1) % n
            b0, b1 = a0 + n, a1 + n
            F += [[a0, a1, b1], [a0, b1, b0]]
    base = len(V)
    V = np.vstack([V, rings[0][0], tip])
    for i in range(n):                                   # 뿌리 마개, 끝 모으기
        F.append([base, (i + 1) % n, i])
        j0, j1 = (R - 1) * n + i, (R - 1) * n + (i + 1) % n
        F.append([j0, j1, base + 1])
    return V, np.array(F)


def build_sweep(pack, mask_front, mask_side, root_point, voxel=0.008, master='front', step=2, min_ring=3):
    """root_point: 뿌리 쪽을 가리키는 3D 점(H, 보통 본체 중심). 연결된 덩어리(좌우 뿔)마다 따로 쓸어 합친다.
    반환 V, F, 정보."""
    occ, (X_, Y_, Z_) = hull_occ(pack, mask_front, mask_side, voxel, master)
    lab, n = ndi.label(occ, np.ones((3, 3, 3)))
    VV, FF, info = [], [], {'덩어리': 0, '고리': []}
    for li in range(1, n + 1):
        blob = lab == li
        if blob.sum() < 50:
            continue
        idx = np.argwhere(blob)
        P = np.stack([X_[idx[:, 0]], Y_[idx[:, 1]], Z_[idx[:, 2]]], 1)
        dist = np.linalg.norm(P - np.asarray(root_point, float), axis=1)
        seed = np.zeros(occ.shape, bool)
        near = dist <= dist.min() + 2 * voxel
        seed[tuple(idx[near].T)] = True
        g = _geodesic(blob, seed)[tuple(idx.T)]
        ok = g >= 0
        P, g = P[ok], g[ok]
        bins = g // step
        cents, groups = [], []
        for b in range(bins.max() + 1):
            q = P[bins == b]
            if len(q) >= min_ring:
                cents.append(q.mean(0))
                groups.append(q)
        if len(cents) < 3:
            continue
        C = np.array(cents)
        # 중심선 다듬기(이웃 평균) 후 접선
        Cs = C.copy()
        for _ in range(2):
            Cs[1:-1] = (Cs[:-2] + Cs[1:-1] + Cs[2:]) / 3
        rings = []
        for i, q in enumerate(groups):
            tng = Cs[min(i + 1, len(Cs) - 1)] - Cs[max(i - 1, 0)]
            tng /= max(np.linalg.norm(tng), 1e-9)
            # 단면 축은 뷰 방향에 맞춘다: v = 앞뒤(Y, 옆 뷰가 재는 폭)에서 접선 성분을 뺀 것, u = 접선 × v(정면 뷰가 재는 폭).
            # 주성분 축은 쓰지 않는다: 헐 단면은 정사각형에 가까워 주축이 대각선으로 잡히고, 대각선 폭은 최대 1.4배라 관이 뚱뚱해졌다
            # (합성 휜 뿔 실루엣 IoU 0.69). 접선이 앞뒤를 향하면 대신 위(Z)를 기준으로 한다.
            d = q - Cs[i]
            d = d - np.outer(d @ tng, tng)
            ref = np.array([0.0, 1.0, 0.0]) if abs(tng[1]) < 0.9 else np.array([0.0, 0.0, 1.0])
            v = ref - (ref @ tng) * tng
            v /= np.linalg.norm(v)
            u = np.cross(v, tng)
            pu, pv = d @ u, d @ v
            a = max(0.5 * (np.percentile(pu, 99) - np.percentile(pu, 1)), voxel)
            b = max(0.5 * (np.percentile(pv, 99) - np.percentile(pv, 1)), voxel)
            # 중심도 두 축 범위의 가운데로(띠 무게중심은 휜 쪽으로 치우침)
            c = Cs[i] + u * 0.5 * (np.percentile(pu, 99) + np.percentile(pu, 1)) + v * 0.5 * (np.percentile(pv, 99) + np.percentile(pv, 1))
            Cs[i] = c
            rings.append((Cs[i], u, v, a, b))
        tip = Cs[-1] + (Cs[-1] - Cs[-2]) * 0.5
        V, F = _tube(rings, tip)
        FF.append(F + sum(len(x) for x in VV))
        VV.append(V)
        info['덩어리'] += 1
        info['고리'].append(len(rings))
    if not VV:
        return None, None, {'이유': '쓸 덩어리 없음'}
    return np.vstack(VV), np.vstack(FF), info


def constrained_relax(V, F, voxel, iters=20, lam=0.5):
    """제한 이완(Gibson 1998 '제한 탄성 표면망', MERL TR99-24): 정점을 이웃 평균 쪽으로 조금씩 옮기되,
    매 걸음 원래 자리에서 축마다 반 칸(voxel/2) 안으로 묶는다. 복셀 계단은 반 칸 높이라 계단만 없어지고 가는 부분·실루엣은 반 칸 안에서 지켜진다.
    (가우스·Taubin·거리장 다듬기는 가는 뿔 가장자리를 깎아 실루엣이 0.94~0.96 으로 떨어졌다)"""
    V0 = V.copy()
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    deg = np.bincount(e[:, 0], minlength=len(V)).astype(float)
    h = voxel / 2
    for _ in range(iters):
        acc = np.zeros_like(V)
        np.add.at(acc, e[:, 0], V[e[:, 1]])
        avg = acc / np.maximum(deg, 1)[:, None]
        V = V + lam * (avg - V)
        V = np.clip(V, V0 - h, V0 + h)
    return V


def build_round_hull(pack, mask_front, mask_side, root_point, voxel=0.008, master='front', smooth=0.0, taubin=0, sdf_smooth=0.0, cesn=0):
    """둥근 헐: 쓸기(둥근 단면) ∩ 헐, 그리고 실루엣이 빈 시선마다 헐 칸을 쓸기 중심 쪽에서 채운다.
    쓸기만 쓰면 가는 뿔에서 가장자리 1px 씩 틀려 실루엣이 0.9 로 떨어졌다(합성 8개). 헐과 섞어 실루엣은 헐과 같게, 단면은 둥글게.
    smooth 기본 0: 다듬으면 한 칸짜리 채움이 1px 아래로 줄어 실루엣 0.94. 끄면 1.000(bench/sweep_bench.py, 새 씨앗 8~15 에서도 PASS).
    대신 표면이 복셀 계단이다(합치기 뒤 Decimate 로 줄어듦, 매끈하게 하는 것은 남은 과제)."""
    from skimage.measure import marching_cubes
    occ, (X_, Y_, Z_) = hull_occ(pack, mask_front, mask_side, voxel, master)
    Vs, Fs, info = build_sweep(pack, mask_front, mask_side, root_point, voxel, master)
    if Vs is None:
        return None, None, info
    from .model_check import voxelize
    o, l = voxelize(Vs, Fs, voxel)
    S = np.zeros(occ.shape, bool)
    s = np.round((l - np.array([X_[0], Y_[0], Z_[0]])) / voxel).astype(int)
    a0 = np.maximum(s, 0)
    b0 = np.minimum(s + np.array(o.shape), occ.shape)
    if (b0 > a0).all():
        S[a0[0]:b0[0], a0[1]:b0[1], a0[2]:b0[2]] = o[a0[0] - s[0]:b0[0] - s[0], a0[1] - s[1]:b0[1] - s[1], a0[2] - s[2]:b0[2] - s[2]]
    S &= occ                                                  # 실루엣 밖으로 나간 것 잘라냄
    # 급히 휜 곳에서 관 고리가 서로 겹치면 홀짝 채우기가 안을 비운다(들소 뿔: 속이 빈 조각 121개). 속 빈 곳을 메운다
    S = ndi.binary_fill_holes(S)
    # 실루엣 채우기: S 에서 헐 안으로 자라되, 아직 실루엣이 빈 시선(정면 X·Z 칸, 옆 Y·Z 칸)에 든 칸만 받는다.
    # 시선마다 한 칸씩 따로 찍으면 떨어진 낱칸 222 개가 생겼다(들소 뿔). 자라서 채우면 늘 S 에 붙는다.
    st6 = ndi.generate_binary_structure(3, 1)
    added = 0
    for _ in range(60):
        need_f = occ.any(1) & ~S.any(1)                   # (x, z)
        need_s = occ.any(0) & ~S.any(0)                   # (y, z)
        if not need_f.any() and not need_s.any():
            break
        grow = ndi.binary_dilation(S, st6) & occ & ~S
        want = grow & (need_f[:, None, :] | need_s[None, :, :])
        if not want.any():
            # 빈 시선이 아직 멀다: 한 겹 전체로 자란 뒤 다시 본다(헐 쪽으로 조금 뚱뚱해짐)
            if not grow.any():
                break
            want = grow
        S |= want
        added += int(want.sum())
    # 남은 낱조각 정리: 덩어리(좌우 뿔)마다 큰 것만 남긴다
    lab, n = ndi.label(S, st6)
    if n > 1:
        sz = ndi.sum(S, lab, range(1, n + 1))
        keep = np.isin(lab, 1 + np.flatnonzero(sz >= 0.02 * sz.max()))
        S &= keep
    S = ndi.binary_fill_holes(S)
    if sdf_smooth:
        # 부호 거리장 다듬기: 칸(0/1)을 다듬으면 가는 끝이 0.5 아래로 사라졌다(실루엣 0.94). 표면까지의 거리(안 +, 밖 −)를
        # 조금만 다듬고 0 에서 면을 뽑으면 표면이 덜 움직여 계단만 줄어든다는 가설(루프 작업 5번)
        sd0 = ndi.distance_transform_edt(S) - ndi.distance_transform_edt(~S)
        sd = ndi.gaussian_filter(sd0, sdf_smooth)
        # 제한 띠: 다듬은 면이 원래 면에서 반 칸 넘게 움직이지 못하게(Gibson 1998 '제한 탄성 표면망' 과 같은 생각).
        # 그냥 다듬으면 가는 가장자리가 깎여 실루엣 0.962(새 뿔 16~23). 계단 높이가 반 칸이라 이 띠 안에서 다듬으면 계단만 없어진다
        sd = np.clip(sd, sd0 - 0.5, sd0 + 0.5)
        sd = np.pad(sd, 1, constant_values=-1.0)
        verts, faces, _, _ = marching_cubes(sd, 0.0)
        verts = verts - 1
        V = np.stack([X_[0] + verts[:, 0] * voxel, Y_[0] + verts[:, 1] * voxel, Z_[0] + verts[:, 2] * voxel], 1)
        F = faces[:, ::-1].copy()
        if np.einsum('ij,ij->i', V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])).sum() < 0:
            F = F[:, ::-1].copy()
        info.update({'헐_칸': int(occ.sum()), '둥근_칸': int(S.sum()), '실루엣_채운_칸': added, 'sdf_smooth': sdf_smooth})
        return V, F, info
    f = ndi.gaussian_filter(S.astype(float), smooth) if smooth else S.astype(float)
    # 다듬기로 가는 끝이 0.5 아래로 사라지지 않게, 원래 칸은 최소 0.5 를 지킨다
    f = np.maximum(f, 0.5 * S + 1e-3 * S)
    f = np.pad(f, 1)
    verts, faces, _, _ = marching_cubes(f, 0.5)
    verts = verts - 1
    V = np.stack([X_[0] + verts[:, 0] * voxel, Y_[0] + verts[:, 1] * voxel, Z_[0] + verts[:, 2] * voxel], 1)
    F = faces[:, ::-1].copy()
    vol6 = np.einsum('ij,ij->i', V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])).sum()
    if vol6 < 0:
        F = F[:, ::-1].copy()
    if cesn:
        V = constrained_relax(V, F, voxel, int(cesn))
    if taubin:
        # 복셀 계단을 줄이는 Taubin 다듬기(부피가 거의 줄지 않음, trimesh). 들소 뿔이 위·3/4 에서 울퉁불퉁했다
        import trimesh
        m = trimesh.Trimesh(V, F, process=False)
        trimesh.smoothing.filter_taubin(m, lamb=0.5, nu=-0.53, iterations=int(taubin))
        V = np.asarray(m.vertices)
    info.update({'헐_칸': int(occ.sum()), '둥근_칸': int(S.sum()), '실루엣_채운_칸': added, 'taubin': int(taubin)})
    return V, F, info
