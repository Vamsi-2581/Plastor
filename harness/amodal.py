# -*- coding: utf-8 -*-
"""가려진 모양 보완(amodal completion): 트레이스는 보이는 것만 따지만, 모델은 덮개(수염·갈기·털 뭉치) 밑의 몸 모양이 필요하다.
부위 윤곽 중 덮개에 맞닿은 구간을, 그 구간 양 끝의 보이는 윤곽 방향(접선)을 이어받는 3차 에르미트 곡선으로 바꾼다.
메우는 영역은 덮개 안으로만 자른다(덮개 밑이 아닌 배경은 지어내지 않는다). 결과는 가정이므로 따로 표시·보고한다.
사용자 지적: "수염을 피해서 그렸지만 해부학을 따졌다면 수염을 제거한 턱을 메웠을 것"(2026-10-28).
기존 도구: skimage.measure.find_contours(윤곽 순서), 다각형 채우기는 harness.trace.fill_poly.
"""
import numpy as np

from . import vendor  # noqa: F401
from .vendor import ndi


def _hermite(p0, p1, t0, t1, n):
    s = np.linspace(0, 1, n)[:, None]
    h00, h10, h01, h11 = 2 * s ** 3 - 3 * s ** 2 + 1, s ** 3 - 2 * s ** 2 + s, -2 * s ** 3 + 3 * s ** 2, s ** 3 - s ** 2
    return h00 * p0 + h10 * t0 + h01 * p1 + h11 * t1


def complete(mask, cover, near=2, tan_k=6, min_run=4):
    """mask: 부위(보이는 것), cover: 덮개 재질 픽셀(부위 밖). 반환 (보완된 마스크, 더한 픽셀, 정보)."""
    from skimage.measure import find_contours
    from .trace import fill_poly
    if not mask.any() or not cover.any():
        return mask, np.zeros_like(mask), {'구간': 0}
    pad = np.pad(mask, 1).astype(float)
    cs = find_contours(pad, 0.5)
    C = max(cs, key=len)[:, ::-1] - 1                        # (x, y), 가장 긴 바깥 윤곽
    if np.allclose(C[0], C[-1]):
        C = C[:-1]
    n = len(C)
    near_cover = ndi.binary_dilation(cover, iterations=near)
    xi = np.clip(np.round(C[:, 0]).astype(int), 0, mask.shape[1] - 1)
    yi = np.clip(np.round(C[:, 1]).astype(int), 0, mask.shape[0] - 1)
    hid = near_cover[yi, xi]
    if hid.all() or not hid.any():
        return mask, np.zeros_like(mask), {'구간': 0}
    # 원형 배열에서 연속 구간 찾기(보이는 점에서 시작하도록 회전)
    start = int(np.flatnonzero(~hid)[0])
    order = np.r_[start:n, 0:start]
    Cr, hr = C[order], hid[order]
    out_pts, runs, i = [], 0, 0
    while i < n:
        if not hr[i]:
            out_pts.append(Cr[i])
            i += 1
            continue
        j = i
        while j < n and hr[j]:
            j += 1
        if j - i < min_run:
            out_pts.extend(Cr[i:j])
            i = j
            continue
        a, b = i - 1, j % n                                  # 구간 양 끝의 보이는 점
        A, B = Cr[a], Cr[b]
        tA = Cr[a] - Cr[max(0, a - tan_k)]
        tB = Cr[min(n - 1, b + tan_k)] - Cr[b] if b + tan_k < n else Cr[(b + tan_k) % n] - Cr[b]
        L = np.linalg.norm(B - A)
        tA = tA / max(np.linalg.norm(tA), 1e-9) * L
        tB = tB / max(np.linalg.norm(tB), 1e-9) * L
        out_pts.extend(_hermite(A, B, tA, tB, max(8, j - i)))
        runs += 1
        i = j
    filled = fill_poly(mask.shape, [tuple(p) for p in out_pts])
    added = filled & ~mask & cover                           # 덮개 안으로만
    return mask | added, added, {'구간': runs, '더한_픽셀': int(added.sum())}
