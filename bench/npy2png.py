# -*- coding: utf-8 -*-
"""도면 npy(행, 열, RGB uint8) → PNG. Blender 로만 그림 파일을 쓸 수 있어 blender -b -P 로 돈다.
사용: blender -b -P bench/npy2png.py -- <in.npy> <out.png>"""
import sys
import bpy
import numpy as np
a = sys.argv[sys.argv.index('--') + 1:]
img = np.load(a[0]).astype(np.float32) / 255.0
h, w = img.shape[:2]
rgba = np.ones((h, w, 4), np.float32)
rgba[..., :3] = img[..., :3]
im = bpy.data.images.new('d', w, h, alpha=False)
im.pixels.foreach_set(rgba[::-1].ravel())          # Blender 그림은 아래 줄부터
im.filepath_raw = a[1]
im.file_format = 'PNG'
im.save()
print('PNG', a[1], w, h)
