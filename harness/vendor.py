# -*- coding: utf-8 -*-
"""프로젝트 안 .vendor/ (사용자 승인 설치: vtracer, scipy, scikit-image, opencv-python-headless, trimesh)를 가져오기 경로에 넣는다.
numpy 는 Blender 번들 것을 쓴다(.vendor 의 numpy 는 지웠다). 없으면 None 을 돌려 손으로 짠 대체 코드로 간다."""
import os
import sys

_V = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.vendor')
if os.path.isdir(_V) and _V not in sys.path:
    sys.path.append(_V)          # 뒤에 붙인다: 번들 numpy 가 먼저

try:
    import scipy.ndimage as ndi  # noqa: E402
except Exception:                # 설치 안 된 환경
    ndi = None
