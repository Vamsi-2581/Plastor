# -*- coding: utf-8 -*-
"""LLM 이 그린 거친 트레이스(다각형)를 도면 이미지의 실제 색 경계에 붙인다.
역할 분담: LLM 은 "어디가 뿔인가"(부위 이름·대략의 모양)를 정하고, 이 도구는 픽셀 정밀도를 맡는다.
방법: 다각형 변을 2px 간격으로 촘촘히 한 뒤, 점마다 바깥 법선 방향 ±R px 안에서 색 기울기가 가장 큰 곳으로 옮긴다.
기울기가 GRAD 미만이면(원래 경계가 없는 컷 선) 옮기지 않고 '컷'으로 표시한다. 옮김량은 이웃과 중앙값으로 고른다(톱니 방지).
"""
import numpy as np

R = 8          # 탐색 반경 px (LLM 트레이스 오차가 이보다 크면 못 고친다)
GRAD = 20.0    # target_check 와 같은 기준
STEP = 2.0
SMOOTH = 5


def grad_mag(img):
    f = img[..., :3].astype(float)
    g = np.zeros(f.shape[:2])
    gx = np.linalg.norm(f[:, 2:] - f[:, :-2], axis=2) / 2.0
    gy = np.linalg.norm(f[2:] - f[:-2], axis=2) / 2.0
    g[:, 1:-1] = np.maximum(g[:, 1:-1], gx)
    g[1:-1] = np.maximum(g[1:-1], gy)
    return g


def densify(pts, step=STEP):
    P = np.asarray(pts, float)
    out = []
    for a, b in zip(P, np.roll(P, -1, 0)):
        n = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
        for t in np.arange(n) / n:
            out.append(a + (b - a) * t)
    return np.array(out)


def _normals(P):
    d = np.roll(P, -1, 0) - np.roll(P, 1, 0)
    n = np.stack([d[:, 1], -d[:, 0]], 1)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    area = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
    return n if area > 0 else -n                       # 바깥쪽으로(화면 좌표 y 아래 +)


def _sample(g, x, y):
    h, w = g.shape
    xi, yi = int(round(x)), int(round(y))
    return g[yi, xi] if 0 <= yi < h and 0 <= xi < w else 0.0


def support(g, P, win=3):
    """윤곽 점 중 ±win px 안에 기울기 ≥ GRAD 가 있는 비율(target_check 와 같은 뜻, 법선 방향 탐색)."""
    n = _normals(P)
    ok = 0
    for p, q in zip(P, n):
        if max(_sample(g, *(p + q * s)) for s in range(-win, win + 1)) >= GRAD:
            ok += 1
    return ok / len(P)


def snap(g, pts):
    P = densify(pts)
    n = _normals(P)
    off = np.zeros(len(P))
    cut = np.zeros(len(P), bool)
    for i, (p, q) in enumerate(zip(P, n)):
        vals = [(_sample(g, *(p + q * s)), -abs(s), s) for s in range(-R, R + 1)]
        best = max(vals)
        if best[0] >= GRAD:
            off[i] = best[2]
        else:
            cut[i] = True
    k = SMOOTH // 2
    sm = np.array([np.median(np.take(off, range(i - k, i + k + 1), mode='wrap')) for i in range(len(P))])
    return P + n * sm[:, None], cut


def mirror_half(mask, cx, keep='left'):
    """정면·뒤 컷은 좌우 대칭이므로 한쪽 절반만 쓰고 중심선(cx, 픽셀 경계 좌표)으로 접어 붙인다.
    픽셀 c 의 거울은 2*cx - 1 - c. keep 쪽 절반이 기준이 되고 반대쪽은 버린다.
    keep='union': 왼쪽 절반과 오른쪽 절반의 거울을 합친 뒤 붙인다(한쪽 트레이스만 놓친 곳을 다른 쪽이 메운다)."""
    h, w = mask.shape
    if keep == 'union':
        cols = np.arange(w)
        mc = np.round(2 * cx - 1 - cols).astype(int)
        ok = (mc >= 0) & (mc < w)
        mir = np.zeros_like(mask)
        mir[:, mc[ok]] = mask[:, cols[ok]]
        return mirror_half(mask | mir, cx, 'left')
    out = np.zeros_like(mask)
    cols = np.arange(w)
    src = cols < cx if keep == 'left' else cols >= cx
    out[:, src] = mask[:, src]
    mc = (2 * cx - 1 - cols[src]).round().astype(int)
    ok = (mc >= 0) & (mc < w)
    out[:, mc[ok]] |= mask[:, cols[src][ok]]
    return out
