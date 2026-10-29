# -*- coding: utf-8 -*-
"""K1 채점 항목(docs/구현계획_통합.md K1): 거칠기, 3/4 폭 비, 랜드마크, 부위별 실루엣(가려진 픽셀 제외)·부피.
모두 칸(복셀) 또는 면 법선에서 재고, 정답과 모델에 **같은 규칙**을 쓴다(규칙이 다르면 잔차가 규칙 차이를 잰다).
"""
import numpy as np


def roughness(V, F):
    """이웃 면 법선 각(도)의 평균. 매끈한 곡면은 작고, 복셀 계단은 크다(수정_기록 보류: 둥근 헐 13.7°).
    중앙값은 쓰지 않는다: 계단 메시는 평평한 면이 대부분이라 중앙값이 0 에 가깝게 나왔다(합성 기본 0.19°)."""
    T = V[F]
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    fid = np.tile(np.arange(len(F)), 3)
    e = np.sort(e, 1)
    key = e[:, 0].astype(np.int64) * (len(V) + 1) + e[:, 1]
    order = np.argsort(key, kind='stable')
    k, f = key[order], fid[order]
    same = np.flatnonzero(k[1:] == k[:-1])          # 같은 변을 공유하는 면 둘
    if not len(same):
        return None
    c = np.clip((n[f[same]] * n[f[same + 1]]).sum(1), -1, 1)
    return float(np.degrees(np.mean(np.arccos(c))))


def roughness_v2(V, F, radius=0.03):
    """거칠기 v2: 면마다 '반경 radius(H) 안 면들의 넓이 가중 평균 법선'과의 각(도), 그 넓이 가중 평균.
    계단은 국소 평균 법선에서 크게 벗어나고 매끈한 면은 안 벗어난다(v1 이웃 면 각 평균은 계단 9.45° 로 약했음, K1 1차)."""
    from scipy.spatial import cKDTree
    T = V[F]
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    a = np.linalg.norm(n, axis=1)
    n = n / np.maximum(a[:, None], 1e-12)
    c = T.mean(1)
    tree = cKDTree(c)
    out = np.zeros(len(F))
    for i, nb in enumerate(tree.query_ball_point(c, radius)):
        m = (n[nb] * a[nb, None]).sum(0)
        m /= max(np.linalg.norm(m), 1e-12)
        out[i] = np.degrees(np.arccos(np.clip(n[i] @ m, -1, 1)))
    return float((out * a).sum() / max(a.sum(), 1e-12))


def quarter_ratio(occ, voxel, min_cells=12):
    """3/4(45°) 폭 비: 높이 칸마다 45° 방향 폭 / 상자 상한((X 폭 + Y 폭)/√2) 의 중앙값.
    타원 단면은 √(a²+b²)/(a+b)(정원 0.707), 직사각형 단면은 1.0. 두 뷰 헐(상자 단면)을 숫자로 잡는다(B09)."""
    r = []
    for z in range(occ.shape[2]):
        xi, yi = np.nonzero(occ[:, :, z])
        if len(xi) < min_cells:
            continue
        wx, wy = xi.max() - xi.min() + 1, yi.max() - yi.min() + 1
        u = (xi + yi) / np.sqrt(2)
        w45 = u.max() - u.min() + np.sqrt(2)            # 칸 하나의 45° 폭(대각선)
        r.append(w45 / ((wx + wy) / np.sqrt(2)))
    return float(np.median(r)) if r else None


def cell_points(occ, lo, voxel):
    return lo + (np.argwhere(occ) + 0.5) * voxel


def landmarks(head_pts, horn_pts=None):
    """부위 이름이 붙은 점(H 단위). 같은 규칙을 정답 칸과 모델 칸에 쓴다.
    코끝 = 머리에서 가장 앞(Y 최대) 칸들의 평균, 정수리 = 가장 위(Z 최대) 칸들의 평균,
    뿔끝_오른·왼 = 뿔 칸 중 X>0·X<0 각각 머리 중심에서 가장 먼 칸들의 평균."""
    out = {}
    if head_pts is not None and len(head_pts):
        for name, k in (('코끝', 1), ('정수리', 2)):
            m = head_pts[:, k] >= head_pts[:, k].max() - 0.015
            out[name] = head_pts[m].mean(0)
        hc = head_pts.mean(0)
        if horn_pts is not None and len(horn_pts):
            for name, side in (('뿔끝_오른', 1), ('뿔끝_왼', -1)):
                q = horn_pts[side * horn_pts[:, 0] > 0]
                if len(q):
                    d = np.linalg.norm(q - hc, axis=1)
                    out[name] = q[d >= d.max() - 0.015].mean(0)
    return out


def landmark_residuals(model, truth):
    return {k: round(float(np.linalg.norm(model[k] - truth[k])), 4) for k in model if k in truth}


def part_silhouette(pm, ref, dont_care):
    """부위 실루엣 IoU(가려진 픽셀 제외): 정답에서 다른 부위로 보이는 픽셀은 옳고 그름을 모르니 뺀다."""
    keep = ~dont_care | ref
    a, b = pm & keep, ref & keep
    return float((a & b).sum() / max((a | b).sum(), 1))


def gt_occ(prims, names, lo, shape, voxel):
    pts = (lo + (np.indices(shape).reshape(3, -1).T + 0.5) * voxel)
    ins = np.zeros(len(pts), bool)
    for p in prims:
        if p['part'] in names:
            ins |= (((pts - p['c']) / p['r']) ** 2).sum(1) <= 1
    return ins.reshape(shape)


def common_grid(occ, lo, prims, names, voxel):
    """모델 칸과 정답 도형을 함께 담는 격자로 옮긴다. 반환 (모델 칸, 정답 칸, 원점)."""
    Q = [p for p in prims if p['part'] in names]
    glo = np.minimum(lo, np.min([p['c'] - p['r'] for p in Q], 0)) - 2 * voxel
    ghi = np.maximum(lo + np.array(occ.shape) * voxel, np.max([p['c'] + p['r'] for p in Q], 0)) + 2 * voxel
    gs = tuple(np.ceil((ghi - glo) / voxel).astype(int))
    mine = np.zeros(gs, bool)
    o = np.round((lo - glo) / voxel).astype(int)
    mine[o[0]:o[0] + occ.shape[0], o[1]:o[1] + occ.shape[1], o[2]:o[2] + occ.shape[2]] = occ
    return mine, gt_occ(prims, names, glo, gs, voxel), glo
