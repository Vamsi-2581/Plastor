# -*- coding: utf-8 -*-
"""트레이싱 연습용 합성 도면: 3D 도형(타원체·구 사슬)을 셀 셰이딩으로 정사영 렌더링해 정면·옆 패널을 만든다.
부위마다 정확한 정답 마스크(그 뷰에서 보이는 픽셀)를 함께 낸다. 무작위 씨앗마다 모양·색·뿔 휨·귀·볏·갈기가 달라진다.
들어가는 어려움: 가림, 음영 면(재질 하나에 3톤), 휜 뿔(같은 높이를 두 번 지남), 같은 재질 하위 부위(뿔 밑동),
같은 재질로 이어진 부위(머리 털과 갈기·목), 배경과 비슷한 밝은 색(선택), 회색 점선 안내선, 앤티에일리어싱, 잡음.
좌표: 캐릭터 X 오른쪽 +, Y 앞 +, Z 위. 정면 패널은 캐릭터 오른쪽이 화면 왼쪽(x부호 −1), 옆 패널은 앞이 화면 왼쪽(x부호 −1).
"""
import numpy as np

W = H = 300          # 패널 크기(px)
PPH = 160.0          # 1H = 160px
GROUND = 290.0       # 발바닥 행(패널 안에서는 머리만 보이므로 높이 값은 임의)
ZOFF = 4.0           # 패널 맨 아래 근처가 이 높이


def _ellipsoid(c, r, part, mat):
    return {'kind': 'ell', 'c': np.array(c, float), 'r': np.array(r, float), 'part': part, 'mat': mat}


def _chain(path, radii, parts, mat):
    return [{'kind': 'ell', 'c': np.array(p, float), 'r': np.array([q, q, q], float), 'part': pt, 'mat': mat}
            for p, q, pt in zip(path, radii, parts)]


def creature(rng, hard_bg=False, hue=False, twotone=False, ear_scale=1.0):
    """hue=True: 귀를 '귀안'(분홍) 재질로, 밝기는 얼굴과 같고 붉은 기만 다르게. 얼굴 앞면을 넓혀 귀와 맞닿게 한다(들소 옆 귀 같은 경우)."""
    """무작위 머리 하나(H 단위). 반환 도형 목록, 재질 기본색."""
    hz = 4.8
    prims = []
    hw, hd, hh = rng.uniform(0.28, 0.4), rng.uniform(0.3, 0.42), rng.uniform(0.3, 0.42)
    prims.append(_ellipsoid([0, 0.1, hz], [hw, hd, hh], '머리', '털'))
    prims.append(_ellipsoid([0, 0.1 + hd * 0.85, hz - hh * 0.35], [hw * 0.55, hd * 0.55, hh * 0.45], '머리', '얼굴'))   # 주둥이
    prims.append(_ellipsoid([0, 0.1 + hd * 0.2, hz + hh * 0.1], [hw * (1.08 if hue else 0.8), hd * 0.75, hh * 0.8], '머리', '얼굴'))     # 얼굴 앞면
    if rng.random() < 0.7:                                                                                        # 볏(털)
        prims.append(_ellipsoid([0, 0.1, hz + hh * 0.9], [hw * 0.35, hd * 0.35, hh * 0.45], '머리', '털'))
    prims.append(_ellipsoid([0, -0.25, hz - hh * 1.2], [hw * 1.1, hd * 1.2, 0.5], '목', '털'))                    # 목(같은 털, 머리와 이어짐)
    if rng.random() < 0.6:                                                                                        # 갈기
        prims.append(_ellipsoid([0, -hd * 0.9, hz + 0.05], [hw * 1.3, hd * 0.7, hh * 1.3], '갈기', '털'))
    # 뿔: 옆으로 뻗었다가 위로 휘고, 씨앗에 따라 끝이 안쪽으로 감긴다(같은 높이를 두 번 지남)
    curl = rng.uniform(0.0, 1.2)
    n = 90
    t = np.linspace(0, 1, n)
    for sx in (1, -1):
        ang = t * (np.pi * 0.55 + curl)
        R = rng.uniform(0.32, 0.45) if sx == 1 else None
        if sx == 1:
            horn_R = R
            base_x = hw * 0.75
            yoff = rng.uniform(-0.1, 0.15)
        x = sx * (base_x + horn_R * np.sin(ang))
        z = hz + hh * 0.45 + horn_R * (1 - np.cos(ang))
        y = np.full(n, 0.05 + yoff) + 0.1 * t
        rad = 0.085 * (1 - t) + 0.012
        parts = ['뿔 밑동' if ti < 0.22 else '뿔' for ti in t]
        prims += _chain(np.stack([x, y, z], 1), rad, parts, '뿔')
    # 귀: 납작한 타원체, 뿔 아래 옆
    ez = hz + rng.uniform(-0.05, 0.12)
    for sx in ((1, -1) if ear_scale > 0 else ()):     # ear_scale(K0 작은 부위 시험): 0 이면 귀 없음, 난수는 그대로 뽑음
        if twotone:   # 두 재질 귀(들소처럼): 털 테두리 + 앞쪽에 작은 분홍 안쪽. 난수는 더 뽑지 않는다(다른 장면과 같은 씨앗 결과 유지)
            prims.append(_ellipsoid([sx * (hw + 0.12), 0.12, ez], [0.16, 0.05, 0.07], '귀', '털'))
            prims.append(_ellipsoid([sx * (hw + 0.14), 0.155, ez - 0.012], [0.11, 0.03, 0.045], '귀', '귀안'))
        else:
            prims.append(_ellipsoid([sx * (hw + 0.12 * ear_scale), 0.0 if not hue else 0.12, ez], [0.16 * ear_scale, 0.05 * ear_scale, 0.07 * ear_scale], '귀', '귀안' if hue else '털'))
    pal = {'배경': np.array([218, 218, 220], float),
           '털': np.array(rng.uniform([70, 50, 45], [110, 85, 75]), float),
           '얼굴': np.array(rng.uniform([135, 95, 80], [165, 125, 105]), float),
           '뿔': np.array(rng.uniform([200, 180, 160], [225, 200, 180]), float)}
    if hard_bg:
        pal['뿔'] = np.array([205, 200, 192], float)          # 배경과 색 거리 ~30
    if hue:
        f = pal['얼굴']
        pink = f + np.array([24.0, -14.0, -8.0])               # 밝기(합)는 거의 같고 붉은 기만 다름
        pal['귀안'] = np.clip(pink, 0, 255)
    return prims, pal


def _view(prims, view, cx):
    """정사영 깊이 버퍼. 반환 (부위 이름 배열, 재질 이름 배열, 음영 0~2)."""
    S = 2                                                      # 2배로 그린 뒤 줄여 앤티에일리어싱
    h, w = H * S, W * S
    yy, xx = np.mgrid[:h, :w]
    px, py = (xx + 0.5) / S, (yy + 0.5) / S
    lat = -(px - cx) / PPH                                     # 화면 → 캐릭터 가로(정면: X, 옆: Y)
    zz = (GROUND - py) / PPH + ZOFF                             # 패널 안 높이(머리가 보이도록 올림)
    depth = np.full((h, w), -1e9)
    part = np.full((h, w), '', object)
    mat = np.full((h, w), '', object)
    shade = np.zeros((h, w), int)
    L = np.array([0.45, 0.55, 0.7]); L /= np.linalg.norm(L)
    for p in prims:
        c, r = p['c'], p['r']
        if view == 'front':     # 보는 방향 −Y(앞에서 봄), 화면 가로 = X, 깊이 = Y
            a, b, d, ra, rb, rd = c[0], c[2], c[1], r[0], r[2], r[1]
        else:                   # 옆(캐릭터 오른쪽에서 봄), 화면 가로 = Y, 깊이 = X
            a, b, d, ra, rb, rd = c[1], c[2], c[0], r[1], r[2], r[0]
        q = ((lat - a) / ra) ** 2 + ((zz - b) / rb) ** 2
        hit = q <= 1
        if not hit.any():
            continue
        dz = d + rd * np.sqrt(np.clip(1 - q, 0, 1))
        win = hit & (dz > depth)
        nl = (lat - a) / ra ** 2; nv = (zz - b) / rb ** 2; nd = (dz - d) / rd ** 2
        if view == 'front':
            N = np.stack([nl, nd, nv], -1)
        else:
            N = np.stack([nd, nl, nv], -1)
        N /= np.maximum(np.linalg.norm(N, axis=-1, keepdims=True), 1e-9)
        lam = N @ L
        sh = np.where(lam > 0.55, 2, np.where(lam > 0.15, 1, 0))
        depth[win] = dz[win]; part[win] = p['part']; mat[win] = p['mat']; shade[win] = sh[win]
    _view.depth = depth
    return part, mat, shade, S


def render(seed, hard_bg=False, guide=True, noise=2.0, outline=False, hue=False, twotone=False, checker=False, ear_scale=1.0):
    """outline=True: 도형 경계(부위가 바뀌거나 깊이가 크게 뛰는 곳)에 어두운 외곽선(2배 해상도에서 2px = 원래 1px)을 그린다."""
    rng = np.random.default_rng(seed)
    prims, pal = creature(rng, hard_bg, hue or twotone, twotone, ear_scale)
    tone = np.array([0.72, 0.88, 1.06])
    panels, truth = [], {}
    for vi, view in enumerate(('front', 'side')):
        part, mat, shade, S = _view(prims, view, W / 2)
        img = np.zeros(part.shape + (3,), float)
        img[:] = pal['배경']
        for m, base in pal.items():
            if m == '배경':
                continue
            for k in range(3):
                sel = (mat == m) & (shade == k)
                img[sel] = np.clip(base * tone[k], 0, 255)
        if outline:
            dep = _view.depth
            fg = mat != ''
            pid = np.where(fg, np.vectorize(hash)(part.astype(str)) % 997, -1)
            e = np.zeros(fg.shape, bool)
            for dy, dx in ((1, 0), (0, 1)):
                a, b = pid, np.roll(np.roll(pid, -dy, 0), -dx, 1)
                da, db = dep, np.roll(np.roll(dep, -dy, 0), -dx, 1)
                jump = (a != b) | (fg & np.abs(da - db).__gt__(0.06))
                e |= jump
            e = e | np.roll(e, 1, 0) | np.roll(e, 1, 1)
            img[e & (fg | np.roll(fg, 1, 0) | np.roll(fg, 1, 1))] = (38, 30, 28)
        if checker:   # 가짜 투명 체크무늬 배경(새 머리 도면처럼): 회색·흰 칸 12px. 칸 경계는 아래 줄이기·흐림에서 중간색이 된다
            yy, xx = np.mgrid[:img.shape[0], :img.shape[1]]
            sq = ((yy // (12 * S)) + (xx // (12 * S))) % 2 == 0
            bgm = mat == ''
            img[bgm & sq] = (238, 238, 240)
            img[bgm & ~sq] = (204, 204, 208)
        img = img.reshape(H, S, W, S, 3).mean((1, 3))              # 앤티에일리어싱
        if checker:   # 확대 번짐 흉내: 약한 흐림(σ 0.7)
            from scipy.ndimage import gaussian_filter
            img = np.stack([gaussian_filter(img[..., c], 0.7) for c in range(3)], -1)
        for pname in ('머리', '목', '갈기', '뿔', '뿔 밑동', '귀'):
            m = (part == pname).reshape(H, S, W, S).mean((1, 3)) >= 0.5
            if m.any():
                truth[(view, pname)] = m
        panels.append(img)
    img = np.concatenate(panels, 1)
    if guide:
        img[int(GROUND - (4.8 + 0.7 - ZOFF) * PPH), ::2] = (192, 194, 196)   # 점선 안내선 한 줄
    img = np.clip(img + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    # truth 는 패널 좌표 → 합친 그림 좌표로
    full = {}
    for (v, p), m in truth.items():
        z = np.zeros((H, 2 * W), bool)
        off = 0 if v == 'front' else W
        z[:, off:off + W] = m
        full[(v, p)] = z
    meta = {'px_per_H': PPH, 'ground_row_grid': GROUND + ZOFF * PPH,
            'panels': {'front': {'중심선_x': W / 2, 'x부호(화면x→캐릭터)': -1}, 'side': {'중심선_x': W + W / 2, 'x부호(화면x→캐릭터)': -1}}}
    return img, full, pal, meta
