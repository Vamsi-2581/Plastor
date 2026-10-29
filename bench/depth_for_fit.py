# -*- coding: utf-8 -*-
"""맞추기용 정면 깊이(항목 4d): 도면의 정면 칸(열 범위)을 Depth Anything V2 Small 로 추정해 그림 전체 크기 float64 npy 로 저장(칸 밖 0).
  .venv_sam/Scripts/python.exe bench/depth_for_fit.py <drawing.npy> <열 시작> <열 끝> <출력.npy>"""
import sys

import numpy as np


def main(src, c0, c1, out):
    import torch
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    name = 'depth-anything/Depth-Anything-V2-Small-hf'
    proc = AutoImageProcessor.from_pretrained(name)
    model = AutoModelForDepthEstimation.from_pretrained(name).eval()
    img = np.load(src)[:, :, :3]
    crop = img[:, c0:c1]
    with torch.no_grad():
        pred = model(**proc(images=crop, return_tensors='pt')).predicted_depth
    pred = torch.nn.functional.interpolate(pred[None], size=crop.shape[:2], mode='bicubic', align_corners=False)[0, 0].numpy()
    full = np.zeros(img.shape[:2], np.float64)
    full[:, c0:c1] = pred - pred.min() + 1e-3     # 0 은 '없음' 표시라 양수로
    np.save(out, full)
    print('깊이 저장', out, full.shape)


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4])
