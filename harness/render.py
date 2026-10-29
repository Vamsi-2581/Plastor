"""소프트웨어 겹침 그림 (numpy 만, PIL 없이 zlib 로 PNG 직접 기록).
도면 위에 모델 외곽(빨강)과 도면 윤곽(초록), 높이 띠 오차 색을 얹는다. 3/4 은 도면이 없어 음영 그림만.
"""
import struct
import zlib

import numpy as np

from .measure import slice_points, unique_edges

SCALE = 260                        # 그림 해상도: 1H = 260px
Z_TOP, Z_BOT = 5.62, 4.15
RANGE = {'front': (-1.05, 1.05), 'back': (-1.05, 1.05), 'side': (-0.95, 1.25)}
RED, GREEN, BLUE = (230, 40, 40), (30, 170, 60), (40, 90, 220)


def write_png(path, rgb):
    rgb = np.ascontiguousarray(rgb, np.uint8)
    h, w, _ = rgb.shape
    raw = b''.join(b'\x00' + rgb[y].tobytes() for y in range(h))

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)

    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
                chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def _line(img, p0, p1, color, width=2):
    n = int(max(abs(p1[0] - p0[0]), abs(p1[1] - p0[1]))) + 1
    xs = np.linspace(p0[0], p1[0], n)
    ys = np.linspace(p0[1], p1[1], n)
    for dx in range(-(width // 2), width - width // 2):
        for dy in range(-(width // 2), width - width // 2):
            x = np.round(xs + dx).astype(int)
            y = np.round(ys + dy).astype(int)
            ok = (x >= 0) & (x < img.shape[1]) & (y >= 0) & (y < img.shape[0])
            img[y[ok], x[ok]] = color


def _poly(img, pts, color, width=2):
    for a, b in zip(pts[:-1], pts[1:]):
        _line(img, a, b, color, width)


def _dot(img, p, color, r=4, cross=False):
    x, y = int(round(p[0])), int(round(p[1]))
    for d in range(-r, r + 1):
        for (xx, yy) in ((x + d, y), (x, y + d)):
            if 0 <= xx < img.shape[1] and 0 <= yy < img.shape[0]:
                img[yy, xx] = color
    if not cross:
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                if 0 <= x + dx < img.shape[1] and 0 <= y + dy < img.shape[0]:
                    img[y + dy, x + dx] = color


def _err_color(e):
    e = abs(e)
    return (40, 180, 60) if e < 0.03 else (235, 200, 30) if e < 0.05 else (240, 140, 30) if e < 0.10 else (220, 40, 40)


def _panel(pack, view, V, E, rep):
    lat0, lat1 = RANGE[view]
    W, H = int((lat1 - lat0) * SCALE), int((Z_TOP - Z_BOT) * SCALE)
    img = np.full((H, W, 3), 225, np.uint8)
    draw = pack.drawing()
    uu = lat0 + (np.arange(W) + 0.5) / SCALE
    zz = Z_TOP - (np.arange(H) + 0.5) / SCALE
    if draw is not None:
        px, _ = pack.H_to_px(view, uu, np.zeros_like(uu))
        _, py = pack.H_to_px(view, np.zeros_like(zz), zz)
        xi = np.clip(np.round(px - 0.5).astype(int), 0, draw.shape[1] - 1)
        yi = np.clip(np.round(py - 0.5).astype(int), 0, draw.shape[0] - 1)
        img = draw[yi][:, xi].copy()
        img = (img * 0.8 + 255 * 0.2).astype(np.uint8)                  # 윤곽이 잘 보이게 살짝 밝게

    def to_img(lat, z):
        return ((np.asarray(lat) - lat0) * SCALE, (Z_TOP - np.asarray(z)) * SCALE)

    P = pack.prof[view]
    sel = {'front': ('lo', 'hi'), 'back': ('lo', 'hi'), 'side': ('lo', 'hi')}[view]
    for key in sel:                                          # 도면 윤곽(초록)
        x, y = to_img(P[key], pack.z)
        _poly(img, list(zip(x, y)), GREEN, 2)
    # 모델 외곽(빨강): 0.0125H 간격 단면의 최소·최대
    zs = np.arange(pack.z[0], pack.z[-1] + 1e-9, 0.0125)
    lo, hi = [], []
    for h in zs:
        p = slice_points(V, E, h)
        col = 1 if view == 'side' else 0
        lo.append(p[:, col].min())
        hi.append(p[:, col].max())
    for arr in (lo, hi):
        x, y = to_img(arr, zs)
        _poly(img, list(zip(x, y)), RED, 2)
    # 높이 띠 오차 색 막대(모델 바깥쪽 끝에 짧게)
    fams = {'front': ('front',), 'back': ('back',), 'side': ('side_f', 'side_b')}[view]
    for b in rep['bands']:
        if b.get('missing'):
            continue
        for fam in fams:
            e = b[fam]['e']
            m = b[fam]['m']
            # 앞끝/반폭은 +쪽, 옆 뒤끝은 -쪽 가장자리
            lat = -m if fam == 'side_b' else m
            if view != 'side':
                lat = m
            x, y = to_img(lat, b['z'])
            sx = 1 if fam != 'side_b' else -1
            if view in ('front', 'back'):
                for sgn in (1, -1):
                    xx, yy = to_img(sgn * m, b['z'])
                    _line(img, (xx, yy), (xx + sgn * 9, yy), _err_color(e), 4)
            else:
                _line(img, (x, y), (x + sx * 9, y), _err_color(e), 4)
    # 랜드마크: 도면 목표(초록 점)와 모델(빨강 십자)
    for lm in rep['landmarks']:
        if 'model' not in lm:
            continue
        t, m = lm['target'], lm['model']
        if view == 'side' and t['y'] is not None:
            _dot(img, to_img(t['y'], t['z']), GREEN, 5)
            _dot(img, to_img(m[1], m[2]), RED, 5, cross=True)
        elif view in ('front', 'back') and t['x'] is not None:
            for sgn in ((1, -1) if lm['rule'] != 'manual' else (1,)):
                _dot(img, to_img(sgn * t['x'], t['z']), GREEN, 5)
                _dot(img, to_img(sgn * m[0], m[2]), RED, 5, cross=True)
    # 화면 좌우 방향: 도면 패널 부호에 맞춰(정면은 캐릭터 오른쪽이 화면 왼쪽) 뒤집기
    if pack.panels[view]['sign'] == -1:
        img = img[:, ::-1].copy()
    return img


def _shade(V, F, az_deg=35.0, el_deg=12.0, size=(560, 380)):
    a, e = np.radians(az_deg), np.radians(el_deg)
    d = -np.array([np.sin(a) * np.cos(e), np.cos(a) * np.cos(e), np.sin(e)])
    z = np.array([0, 0, 1.0])
    r = np.cross(d, z)
    r /= np.linalg.norm(r)
    up = np.cross(r, d)
    u, v, dep = V @ r, V @ up, V @ (-d)
    W, H = size
    s = 0.86 * H / (v.max() - v.min())
    cu, cv = 0.5 * (u.max() + u.min()), 0.5 * (v.max() + v.min())
    X = (u - cu) * s + W / 2
    Y = H / 2 - (v - cv) * s
    img = np.full((H, W, 3), 225, np.uint8)
    zbuf = np.full((H, W), -1e9)
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    light = -d + 0.5 * up - 0.4 * r
    light /= np.linalg.norm(light)
    shade = np.clip(n @ light, 0, 1) * 0.75 + 0.25
    for k in range(len(F)):
        if n[k] @ (-d) <= 0:
            continue                                         # 뒷면
        xs, ys, ds = X[F[k]], Y[F[k]], dep[F[k]]
        x0, x1 = int(max(0, np.floor(xs.min()))), int(min(W - 1, np.ceil(xs.max())))
        y0, y1 = int(max(0, np.floor(ys.min()))), int(min(H - 1, np.ceil(ys.max())))
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-12:
            continue
        l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
        l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
        l2 = 1 - l0 - l1
        inside = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
        dz = l0 * ds[0] + l1 * ds[1] + l2 * ds[2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        upd = inside & (dz > sub)
        sub[upd] = dz[upd]
        col = (np.array([150, 105, 70]) * shade[k]).astype(np.uint8)
        img[y0:y1 + 1, x0:x1 + 1][upd] = col
    return img


def show(pack, V, F, rep, out, views):
    E = unique_edges(F)
    tiles = []
    for v in views:
        if v == 'q34':
            tiles.append(_shade(V, F))
        elif v in ('front', 'side', 'back'):
            tiles.append(_panel(pack, v, V, E, rep))
    h = max(t.shape[0] for t in tiles)
    row = []
    for t in tiles:
        pad = np.full((h, t.shape[1] + 6, 3), 255, np.uint8)
        pad[:t.shape[0], :t.shape[1]] = t
        row.append(pad)
    write_png(out, np.concatenate(row, 1))
