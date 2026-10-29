# -*- coding: utf-8 -*-
"""부위 비주얼 헐: 정면 실루엣을 앞뒤(Y)로, 옆 실루엣을 좌우(X)로 밀어내 겹친 부피 → marching cubes 메시.
높이별 단면 쌓기(tube.py)는 휜 뿔에서 같은 높이에 구간이 둘이면 가로 띠 흔적이 생겼다. 헐은 정의상 두 뷰 실루엣과 맞고
휜 모양도 그대로 담는다. 대신 단면이 상자에 가까워진다(가는 부위라 3/4 에서 차이가 작다고 보지만 확인 못 함).
기존 도구 사용: scipy.ndimage.gaussian_filter(부피 다듬기), skimage.measure.marching_cubes(면 뽑기).
"""
import numpy as np

from . import vendor  # noqa: F401
from .vendor import ndi


def _runs(a):
    """1차원 bool 배열의 참 구간들 [(시작, 끝 포함)]."""
    d = np.diff(np.concatenate([[0], a.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1))


def section_fill(inf, ins, n):
    """높이 칸마다 정면 구간(X) × 옆 구간(Y) 직사각형 대신 그 안에 꽉 차는 초타원 |u|^n + |v|^n ≤ 1 을 채운다.
    두 뷰 헐은 단면이 직사각형이라 깊이 방향이 부풀었다(M0 부피 0.39~0.63, 자유 작업 0.73~0.90).
    꽉 찬 초타원은 정면·옆으로 비추면 직사각형과 같은 폭이라 실루엣은 그대로다. n=2 타원, 클수록 직사각형에 가깝다.
    가장자리 칸이 한 칸도 안 남는 것을 막으려고 가운데 십자(가운데 줄·가운데 열)는 늘 채운다."""
    nx, nz = inf.shape
    ny = ins.shape[0]
    vol = np.zeros((nx, ny, nz), bool)
    for z in range(nz):
        for x0, x1 in _runs(inf[:, z]):
            for y0, y1 in _runs(ins[:, z]):
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                rx, ry = (x1 - x0 + 1) / 2, (y1 - y0 + 1) / 2
                u = np.abs((np.arange(x0, x1 + 1) - cx) / rx)[:, None]
                v = np.abs((np.arange(y0, y1 + 1) - cy) / ry)[None, :]
                blk = u ** n + v ** n <= 1
                blk[:, int(np.floor(cy - y0)):int(np.ceil(cy - y0)) + 1] = True
                blk[int(np.floor(cx - x0)):int(np.ceil(cx - x0)) + 1, :] = True
                vol[x0:x1 + 1, y0:y1 + 1, z] |= blk
    return vol


def build_hull(pack, mask_front, mask_side, voxel=0.008, smooth=1.0, occl_front=None, occl_side=None, master=None, section_n=None):
    """반환 V(H 단위, X 오른쪽·Y 앞·Z 위), F, 정보. 마스크는 도면 전체 크기(행, 열).
    occl_*: 그 뷰에서 이 부위를 가릴 수 있는 앞쪽 부위(머리 등). 가려진 자리도 '있을 수 있음'으로 본다(가림 인식 헐).
    (옆 뷰에서 옆으로 뻗은 뿔 아래쪽이 밑동·머리 자리에 겹쳐 헐이 가로로 잘렸다: 정면 IoU 0.625)"""
    from skimage.measure import marching_cubes
    rf, rs = np.nonzero(mask_front), np.nonzero(mask_side)   # 범위는 부위 자체로(가리개로 넓히지 않음)
    if not len(rf[0]) or not len(rs[0]):
        return None, None, {'이유': '한 뷰에 부위가 없음'}
    xf, zf = pack.px_to_H('front', rf[1] + 0.5, rf[0] + 0.5)
    ys, zs = pack.px_to_H('side', rs[1] + 0.5, rs[0] + 0.5)
    pad = 3 * voxel
    xs_ = np.arange(xf.min() - pad, xf.max() + pad, voxel)
    ys_ = np.arange(ys.min() - pad, ys.max() + pad, voxel)
    if master == 'front':                                     # 정면 기준: 높이 범위는 정면을 따른다(AI 도면은 뷰끼리 높이가 다름)
        zs_ = np.arange(zf.min() - pad, zf.max() + pad, voxel)
    else:
        zs_ = np.arange(max(zf.min(), zs.min()) - pad, min(zf.max(), zs.max()) + pad, voxel)
    if len(zs_) < 3:
        return None, None, {'이유': '두 뷰 높이가 겹치지 않음'}
    X, Z = np.meshgrid(xs_, zs_, indexing='ij')
    pxf, pyf = pack.H_to_px('front', X, Z)
    inf = _lookup(mask_front if occl_front is None else (mask_front | occl_front), pxf, pyf)     # (nx, nz)
    Y, Z2 = np.meshgrid(ys_, zs_, indexing='ij')
    pxs, pys = pack.H_to_px('side', Y, Z2)
    ins = _lookup(mask_side if occl_side is None else (mask_side | occl_side), pxs, pys)          # (ny, nz)
    borrowed = 0
    if master == 'front':
        # 옆 뷰에 없는 높이는 가장 가까운 옆 뷰 행의 앞뒤 폭을 빌린다(가정, 개수 보고).
        # 이유: 들소 귀는 정면이 옆보다 21px 높게 그려져, 겹치는 높이만 쓰면 정면 귀 윗부분이 잘렸다(결합 IoU 0.966→0.907)
        has = ins.any(0)
        if has.any():
            idx = np.flatnonzero(has)
            for zi in np.flatnonzero(~has & inf.any(0)):
                ins[:, zi] = ins[:, idx[np.argmin(np.abs(idx - zi))]]
                borrowed += 1
    vol = inf[:, None, :] & ins[None, :, :] if not section_n else section_fill(inf, ins, float(section_n))   # (nx, ny, nz)
    if vol.sum() < 8:
        return None, None, {'이유': '헐이 비었음'}
    f = ndi.gaussian_filter(vol.astype(float), smooth) if smooth else vol.astype(float)
    f = np.pad(f, 1)
    verts, faces, _, _ = marching_cubes(f, 0.5)
    verts = verts - 1
    V = np.stack([xs_[0] + verts[:, 0] * voxel, ys_[0] + verts[:, 1] * voxel, zs_[0] + verts[:, 2] * voxel], 1)
    F = faces[:, ::-1].copy()
    vol6 = np.einsum('ij,ij->i', V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])).sum()
    if vol6 < 0:
        F = F[:, ::-1].copy()
    return V, F, {'복셀': int(vol.sum()), '정점': len(V), '삼각형': len(F), '옆폭_빌린_높이칸': borrowed}


def _lookup(mask, px, py):
    c = np.floor(px).astype(int)
    r = np.floor(py).astype(int)
    ok = (r >= 0) & (r < mask.shape[0]) & (c >= 0) & (c < mask.shape[1])
    out = np.zeros(px.shape, bool)
    out[ok] = mask[r[ok], c[ok]]
    return out


def build_round(pack, mask_front, mask_side, voxel=0.008, smooth=1.0):
    """둥근 관 재구성(뿔처럼 가는 부위): 비주얼 헐 부피의 3D 뼈대(skimage skeletonize) 위 각 점에
    헐 안쪽 거리(scipy distance_transform_edt) 반지름의 공을 이어 붙인다(medial axis 재구성).
    이유: 헐 그대로는 정면·옆이 둘 다 넓은 곳에서 판자가 되어 3/4 뷰에서 뿔이 판 모양이었다(들소 10차 렌더).
    공은 헐 안에 있으므로 실루엣을 넘지 않는다(대신 조금 줄 수 있다)."""
    from skimage.measure import marching_cubes
    from skimage.morphology import skeletonize
    rf, rs = np.nonzero(mask_front), np.nonzero(mask_side)
    if not len(rf[0]) or not len(rs[0]):
        return None, None, {'이유': '한 뷰에 부위가 없음'}
    xf, zf = pack.px_to_H('front', rf[1] + 0.5, rf[0] + 0.5)
    ys, zs = pack.px_to_H('side', rs[1] + 0.5, rs[0] + 0.5)
    pad = 3 * voxel
    xs_ = np.arange(xf.min() - pad, xf.max() + pad, voxel)
    ys_ = np.arange(ys.min() - pad, ys.max() + pad, voxel)
    zs_ = np.arange(max(zf.min(), zs.min()) - pad, min(zf.max(), zs.max()) + pad, voxel)
    X, Z = np.meshgrid(xs_, zs_, indexing='ij')
    inf = _lookup(mask_front, *pack.H_to_px('front', X, Z))
    Y, Z2 = np.meshgrid(ys_, zs_, indexing='ij')
    ins = _lookup(mask_side, *pack.H_to_px('side', Y, Z2))
    vol = inf[:, None, :] & ins[None, :, :]
    dist = ndi.distance_transform_edt(vol)
    sk = skeletonize(vol)
    pts = np.argwhere(sk)
    if len(pts) < 3:
        return None, None, {'이유': '뼈대 없음'}
    rad = dist[sk]
    out = np.zeros(vol.shape, bool)
    gi = np.indices(vol.shape)
    for (a, b, c), r in zip(pts, rad):                    # 공 하나씩(뼈대 점 수백 개, 작은 상자 안만 칠한다)
        ri = int(np.ceil(r)) + 1
        sl = (slice(max(0, a - ri), a + ri + 1), slice(max(0, b - ri), b + ri + 1), slice(max(0, c - ri), c + ri + 1))
        d2 = (gi[0][sl] - a) ** 2 + (gi[1][sl] - b) ** 2 + (gi[2][sl] - c) ** 2
        out[sl] |= d2 <= r * r
    out &= vol
    f = ndi.gaussian_filter(out.astype(float), smooth) if smooth else out.astype(float)
    verts, faces, _, _ = marching_cubes(np.pad(f, 1), 0.5)
    verts = verts - 1
    V = np.stack([xs_[0] + verts[:, 0] * voxel, ys_[0] + verts[:, 1] * voxel, zs_[0] + verts[:, 2] * voxel], 1)
    F = faces[:, ::-1].copy()
    if np.einsum('ij,ij->i', V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])).sum() < 0:
        F = F[:, ::-1].copy()
    return V, F, {'헐_복셀': int(vol.sum()), '관_복셀': int(out.sum()), '뼈대_점': len(pts), '정점': len(V)}
