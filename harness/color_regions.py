# -*- coding: utf-8 -*-
"""도면 색 군집 → 재질 영역 → 재질 경계 지도.
셀 셰이딩 도면은 한 부위 안에도 음영 면마다 색이 달라 '아무 색 경계'에 붙이면 뿔이 조각난다(snap_trace 1차 시험에서 확인).
그래서 k-means 로 색을 군집하고, 같은 부위의 음영 군집들을 한 재질로 묶은 뒤(묶는 판단은 LLM·사람이 이름으로 준다),
재질이 바뀌는 곳만 경계로 쓴다. 군집 번호는 밝기 순으로 정렬해 실행마다 같게 한다.
"""
import numpy as np


def to_space(rgb, space='rgb'):
    """색 공간 바꾸기(군집·재질 판정용). rgb: (..., 3) 0~255.
    'rgb'    : 그대로. 밝기 차가 거리를 지배해, 밝기는 비슷하고 색조만 다른 재질(분홍 귀 안쪽과 얼굴)을 못 가른다.
    'lab'    : CIE Lab(사람 눈의 색차에 가까움). scikit-image rgb2lab.
    'lab_lw' : Lab 에서 밝기(L) 비중을 절반으로. 같은 재질의 음영 톤은 주로 밝기만 다르므로 색조 차이를 더 크게 본다."""
    a = np.asarray(rgb, float)
    if space == 'rgb':
        return a
    from . import vendor  # noqa: F401
    from skimage.color import rgb2lab
    shp = a.shape
    lab = rgb2lab(np.clip(a.reshape(-1, 1, 3) / 255.0, 0, 1)).reshape(shp)
    if space == 'lab_lw':
        lab[..., 0] *= 0.5
    return lab


def kmeans(X, k, it=30, seed=0):
    # 시작점: 가장 먼 색부터 고른다(무작위 시작은 배경을 두 군집으로 쪼개고 밝은 뿔을 배경에 합친 적이 있다)
    C = [X[np.argmin(((X - X.mean(0)) ** 2).sum(1))]]
    for _ in range(k - 1):
        d = np.min([((X - c) ** 2).sum(1) for c in C], axis=0)
        C.append(X[np.argmax(d)])
    C = np.array(C, float)
    for _ in range(it):
        lab = ((X[:, None] - C[None]) ** 2).sum(2).argmin(1)
        C = np.array([X[lab == j].mean(0) if (lab == j).any() else C[j] for j in range(k)])
    return C[np.argsort(-C.sum(1))]                    # 밝은 것부터


def background_mask(img, tol=18.0, gray_chroma=12.0, gray_min=150.0):
    """배경 먼저 지우기: 가장자리 픽셀의 중앙값을 배경색으로 보고, 그 색에 가까우면서(tol) 가장자리와 이어진 픽셀만 배경.
    색만으로 배경을 정하면 배경색과 비슷한 밝은 뿔 끝이 배경에 섞인다. 이어짐을 같이 보면 몸 안쪽의 밝은 곳은 남는다."""
    from .trace import components
    f = img[..., :3].astype(float)
    edge = np.concatenate([f[0], f[-1], f[:, 0], f[:, -1]])
    bg = np.median(edge, 0)
    near = np.linalg.norm(f - bg, axis=2) < tol
    # 여러 색 배경(사용자 지적: 체크무늬 '투명' 배경에서 흰 칸·칸 사이 중간색이 전경으로 남음).
    # 가장자리에 나오는 채도 낮은 색을 모두 배경 견본으로 모으고(채도 높은 색 = 옆 그림 조각 등은 뺌), 견본 중 하나에 tol 안이면 배경 후보.
    # 대표색 몇 개만 고르면 칸 사이 중간색·확대 번짐이 남았다(298→550 조각)
    ech = edge.max(1) - edge.min(1)
    # 견본은 주 배경색에서 45 안쪽 색만(돌리기 전에 정함): 체크무늬 회색·흰색과 그 중간색은 들고, 가장자리에 닿은 몸(어두운 털)은 뺀다.
    # 채도만 보면 합성 도면 아래 가장자리에 닿은 털이 견본에 들어가 옆 갈기가 −0.254 로 지워졌다
    fam = (ech < 25) & (np.linalg.norm(edge - bg, axis=1) < 45)
    pal = np.unique(np.round(edge[fam] / 4) * 4, axis=0)
    import os as _os
    if len(pal) > 1 and _os.environ.get('BG_PALETTE', '1') == '1':
        from .vendor import ndi as _ndi  # noqa: F401
        try:
            from scipy.spatial import cKDTree
            d, _ = cKDTree(pal).query(f.reshape(-1, 3))
            near |= d.reshape(f.shape[:2]) < tol * 0.6
        except ImportError:
            pass
    # 도면의 회색 안내선(점선, 192 정도의 무채색 1~2px)도 배경으로 본다. 채도 낮고 밝은 픽셀만이라 밝은 뿔(채도 ~40)은 남는다
    chroma = f.max(2) - f.min(2)
    gray = (chroma < gray_chroma) & (f.mean(2) > gray_min)
    # 단, 안내선이 지나는 행·열만(그 행·열의 20% 이상이 회색). 회색에 가까운 밝은 뿔 끝처럼 짧은 회색을 지우면 안 된다
    # (두께로 거르는 방식은 가는 뿔 끝도 얇아서 실패했다. 자체 시험에서 잡음)
    # 배경 자체도 무채색이라, 행·열 비율은 '배경색과는 다른 회색'만 센다
    line = gray & ~near
    rows = line.mean(1) > 0.2
    cols = line.mean(0) > 0.2
    near |= line & (rows[:, None] | cols[None, :])
    cc = components(near)
    ids = set(np.unique(np.concatenate([cc[0], cc[-1], cc[:, 0], cc[:, -1]])).tolist()) - {0}
    return np.isin(cc, list(ids)), bg


def label(img, C):
    f = img[..., :3].astype(float)
    return ((f.reshape(-1, 3)[:, None] - C[None]) ** 2).sum(2).argmin(1).reshape(f.shape[:2])


def majority(lab, n, r=1):
    """작은 얼룩 제거: (2r+1)^2 창에서 가장 많은 재질로."""
    h, w = lab.shape
    cnt = np.zeros((n, h, w), np.int32)
    P = np.pad(lab, r, mode='edge')
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            win = P[dy:dy + h, dx:dx + w]
            for m in range(n):
                cnt[m] += win == m
    return cnt.argmax(0)


def material_map(img, C, groups):
    """groups: {재질이름: [군집번호...]} → 재질 번호 지도와 이름 목록."""
    lab = label(img, C)
    names = list(groups)
    mat = np.zeros_like(lab)
    for i, nm in enumerate(names):
        for c in groups[nm]:
            mat[lab == c] = i
    return majority(mat, len(names)), names


def boundary(mat):
    """재질이 바뀌는 픽셀에 255 (snap_trace 의 기울기 지도 자리에 그대로 쓴다)."""
    e = np.zeros(mat.shape, float)
    e[:, 1:] = np.maximum(e[:, 1:], (mat[:, 1:] != mat[:, :-1]) * 255.0)
    e[1:] = np.maximum(e[1:], (mat[1:] != mat[:-1]) * 255.0)
    return e
