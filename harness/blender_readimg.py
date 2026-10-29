# blender -b -P 로 실행: 이미지(webp 등)를 읽어 uint8 RGB .npy 로 저장한다 (Blender 번들 Python 에는 PIL 이 없어서).
# 사용: blender -b -P blender_readimg.py -- <입력 이미지> <출력 .npy>
import sys
import bpy
import numpy as np

argv = sys.argv[sys.argv.index('--') + 1:]
src, dst = argv[0], argv[1]
img = bpy.data.images.load(src)
w, h = img.size
px = np.empty(w * h * 4, np.float32)
img.pixels.foreach_get(px)
px = px.reshape(h, w, 4)[::-1]          # Blender 는 아래 행이 먼저 → 위 행이 먼저로 뒤집는다
rgb = (np.clip(px[:, :, :3], 0, 1) * 255 + 0.5).astype(np.uint8)
np.save(dst, rgb)
print('이미지 저장', dst, rgb.shape)
