# -*- coding: utf-8 -*-
"""비교용: VTracer(MIT, .vendor/ 에 설치)로 색 영역을 만들고, 그 영역을 재질 지도로 바꾼다.
직접 구현(색 군집 + 얼룩 흡수)과 '영역 만들기' 단계만 바꿔 끼워 비교하려는 것이다. 부위 선택(region_part)은 같다.
"""
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, '.vendor'))
import vtracer  # noqa: E402

from .trace import fill_poly  # noqa: E402

TOK = re.compile(r'[MLCZmlcz]|-?\d+(?:\.\d+)?')


def run(img_crop, **kw):
    h, w = img_crop.shape[:2]
    rgba = np.concatenate([img_crop[..., :3], np.full((h, w, 1), 255, np.uint8)], 2).astype(np.uint8)
    px = [tuple(int(v) for v in p) for p in rgba.reshape(-1, 4)]
    opt = dict(colormode='color', hierarchical='cutout', mode='polygon', filter_speckle=4, color_precision=6, layer_difference=16)
    opt.update(kw)
    return vtracer.convert_pixels_to_svg(px, (w, h), **opt)


def svg_shapes(svg):
    """[(채움색 rgb, [다각형 점 목록...])] — polygon 모드의 M/L/Z 만 다룬다."""
    out = []
    for m in re.finditer(r'<path\b([^>]*)/?>', svg):
        a = m.group(1)
        d = re.search(r'\bd="([^"]*)"', a)
        f = re.search(r'fill="#([0-9a-fA-F]{6})"', a)
        if not d or not f:
            continue
        tx = re.search(r'translate\(\s*(-?[\d.]+)[ ,]+(-?[\d.]+)\s*\)', a)
        ox, oy = (float(tx.group(1)), float(tx.group(2))) if tx else (0.0, 0.0)
        polys, cur, nums = [], [], []
        for t in TOK.findall(d.group(1)):
            if t in 'MLmlCcZz':
                if t in 'Mm' and cur:
                    polys.append(cur); cur = []
                if t in 'Zz' and cur:
                    polys.append(cur); cur = []
                continue
            nums.append(float(t))
            if len(nums) == 2:
                cur.append((nums[0] + ox, nums[1] + oy)); nums = []
        if cur:
            polys.append(cur)
        rgb = tuple(int(f.group(1)[i:i + 2], 16) for i in (0, 2, 4))
        out.append((rgb, polys))
    return out


def color_map(img_crop, **kw):
    """VTracer 결과를 픽셀마다 채움색으로 다시 칠한 그림(뒤에 그린 모양이 위). 빈 곳은 원래 색."""
    h, w = img_crop.shape[:2]
    out = img_crop[..., :3].copy()
    shapes = svg_shapes(run(img_crop, **kw))
    for rgb, polys in shapes:
        m = np.zeros((h, w), bool)
        for P in polys:
            if len(P) >= 3:
                m ^= fill_poly((h, w), P)                   # 짝-홀(구멍 다각형 처리)
        out[m] = rgb
    return out, len(shapes)
