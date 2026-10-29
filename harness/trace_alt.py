# -*- coding: utf-8 -*-
"""영역 선택의 대안: 기존 검증된 알고리즘(scikit-image watershed·random_walker, OpenCV GrabCut)으로 부위 마스크를 만든다.
지금 방식(재질 지도 + 덩어리 배정 + 띠 규칙 + 톤 컷, harness/trace.py)과 같은 입력(도면, LLM 거친 다각형)을 받아 벤치마크로 비교한다.
씨앗(markers): 부위마다 거친 다각형을 d px 깎은 곳, 배경 = 배경 마스크, '그 밖의 몸' = 전경 중 모든 다각형을 d px 넓힌 곳 밖.
여러 부위 다각형이 겹치는 곳은 씨앗에서 뺀다(모름).
"""
import numpy as np

from . import vendor  # noqa: F401  (.vendor 경로)
from .color_regions import background_mask
from .vendor import ndi


def _markers(crop, polys, d):
    bg, _ = background_mask(crop)
    keys = list(polys)
    L = np.zeros(crop.shape[:2], np.int32)
    union = np.zeros(crop.shape[:2], bool)
    cnt = np.zeros(crop.shape[:2], np.int32)
    for k in keys:
        union |= polys[k]
        cnt += ndi.binary_erosion(polys[k], iterations=d).astype(np.int32)
    for i, k in enumerate(keys):
        core = ndi.binary_erosion(polys[k], iterations=d) & (cnt == 1)
        if not core.any():                                    # 가는 부위: 덜 깎는다
            core = ndi.binary_erosion(polys[k], iterations=max(1, d // 3)) & (cnt <= 1)
        L[core] = i + 3
    far = ~ndi.binary_dilation(union, iterations=d)
    L[bg & far] = 1
    L[~bg & far] = 2                                          # 이름 없는 몸(목·몸통 …)
    return L, keys, bg


def _elevation(crop):
    f = crop.astype(float)
    g = np.zeros(f.shape[:2])
    for c in range(3):
        gx = ndi.sobel(f[..., c], 1)
        gy = ndi.sobel(f[..., c], 0)
        g = np.maximum(g, np.hypot(gx, gy))
    return g


def segment(method, crop, polys, d=8):
    """반환 {키: 마스크}(crop 크기)."""
    from skimage.segmentation import random_walker, watershed
    L, keys, bg = _markers(crop, polys, d)
    if method == 'watershed':
        lab = watershed(_elevation(crop), markers=L)
    elif method == 'random_walker':
        f = crop.astype(float) / 255.0
        lab = random_walker(f, L, beta=2000, mode='cg', channel_axis=-1, tol=1e-3)
    elif method == 'grabcut':
        import cv2
        out = {}
        for i, k in enumerate(keys):
            gm = np.full(crop.shape[:2], cv2.GC_BGD, np.uint8)
            D = ndi.binary_dilation(polys[k], iterations=d)
            gm[D] = cv2.GC_PR_BGD
            gm[polys[k]] = cv2.GC_PR_FGD
            gm[L == i + 3] = cv2.GC_FGD
            gm[bg] = cv2.GC_BGD
            if not (gm == cv2.GC_FGD).any():
                out[k] = polys[k] & ~bg
                continue
            bgm, fgm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
            cv2.grabCut(np.ascontiguousarray(crop[..., ::-1]), gm, None, bgm, fgm, 5, cv2.GC_INIT_WITH_MASK)
            out[k] = ndi.binary_fill_holes((gm == cv2.GC_FGD) | (gm == cv2.GC_PR_FGD))
        return out
    else:
        raise ValueError(method)
    return {k: ndi.binary_fill_holes(lab == i + 3) for i, k in enumerate(keys)}
