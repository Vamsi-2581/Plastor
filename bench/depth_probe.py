# -*- coding: utf-8 -*-
"""루프 항목 4d ①: 단안 깊이 추정(Depth Anything V2 Small)이 셀 셰이딩 크리처 도면의 깊이를 맞게 읽는지 잰다.
정답 깊이 = 정답 도형(prims.json)에서 정면 픽셀마다 가장 앞(Y 최대) 표면. 기준(돌리기 전): 전경 픽셀에서 추정값과 정답의
순위 상관(스피어만) ≥ 0.8(과제 평균). 실행: .venv_sam 파이썬(torch·transformers)으로
  .venv_sam/Scripts/python.exe bench/depth_probe.py dev_1000 dev_1001 ...
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
MODEL = 'depth-anything/Depth-Anything-V2-Small-hf'
W = 400


def gt_front_depth(d):
    """정면 패널(400x400)의 정답 앞면 Y(H), 전경 아니면 nan."""
    meta = json.load(open(os.path.join(d, 'meta.json'), encoding='utf-8'))
    P = json.load(open(os.path.join(d, 'prims.json'), encoding='utf-8'))
    ppH, g = meta['px_per_H'], meta['ground_row_grid']
    cx, sign = meta['panels']['front']['중심선_x'], meta['panels']['front']['x부호(화면x→캐릭터)']
    r, c = np.mgrid[:W, :W]
    X = sign * (c + 0.5 - cx) / ppH
    Z = (g - (r + 0.5)) / ppH
    depth = np.full((W, W), -np.inf)
    for p in P:
        (x0, y0, z0), (rx, ry, rz) = p['c'], p['r']
        q = ((X - x0) / rx) ** 2 + ((Z - z0) / rz) ** 2
        hit = q <= 1
        y = y0 + ry * np.sqrt(np.clip(1 - q, 0, 1))
        depth = np.where(hit & (y > depth), y, depth)
    depth[~np.isfinite(depth)] = np.nan
    return depth


def rank(a):
    o = np.argsort(a, kind='stable')
    r = np.empty(len(a))
    r[o] = np.arange(len(a))
    return r


def spearman(a, b):
    ra, rb = rank(a), rank(b)
    return float(np.corrcoef(ra, rb)[0, 1])


def main(names):
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    proc = AutoImageProcessor.from_pretrained(MODEL)
    model = AutoModelForDepthEstimation.from_pretrained(MODEL).eval()
    out = {}
    part_out = {}
    for n in names:
        d = os.path.join(ROOT, 'bench', 'v2', n)
        img = np.load(os.path.join(d, 'drawing.npy'))[:, :W, :3]
        with torch.no_grad():
            pred = model(**proc(images=img, return_tensors='pt')).predicted_depth   # 값이 클수록 가까움(상대 역깊이)
        pred = torch.nn.functional.interpolate(pred[None], size=(W, W), mode='bicubic', align_corners=False)[0, 0].numpy()
        gt = gt_front_depth(d)
        m = np.isfinite(gt)
        s = spearman(pred[m], gt[m])
        out[n] = round(s, 4)
        # 2차: 부위 안(머리·몸통) 순위 상관(정답 마스크의 그 부위 픽셀만)
        z = np.load(os.path.join(d, 'truth_all.npz'))
        for part in ('머리', '몸통'):
            k = 'front|' + part
            if k in z.files:
                pm = z[k][:, :W] & m
                if pm.sum() > 50:
                    part_out.setdefault(part, {})[n] = round(spearman(pred[pm], gt[pm]), 4)
        z.close()
        np.save(os.path.join(d, 'depth_pred_front.npy'), pred.astype(np.float32))
        print('DEPTH', n, '순위 상관 %.4f' % s, '전경 픽셀 %d' % m.sum(), flush=True)
    mean = float(np.mean(list(out.values())))
    print('평균 순위 상관 %.4f → %s (기준 ≥ 0.8)' % (mean, 'PASS' if mean >= 0.8 else 'FAIL'))
    for part, v in part_out.items():
        pmn = float(np.mean(list(v.values())))
        print('부위 %s 안 순위 상관 평균 %.4f (최소 %.4f) → %s (2차 기준 ≥ 0.8)' % (part, pmn, min(v.values()), 'PASS' if pmn >= 0.8 else 'FAIL'))
    json.dump({'모델': MODEL, '과제별': out, '평균': round(mean, 4), '부위_안': part_out}, open(os.path.join(ROOT, 'bench', 'v2', 'depth_probe.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main(sys.argv[1:] or ['dev_%d' % i for i in range(1000, 1012)])
