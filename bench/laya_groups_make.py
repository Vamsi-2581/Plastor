# -*- coding: utf-8 -*-
r"""Laya Vision 재질 묶음 시험 준비(Blender python): 사례마다 군집 칸 그림(군집 하나씩)과 질문 JSON 을 쓴다.
판단을 잘게 쪼갠다: 군집마다 (1) 재질 객관식, (2) '목록에 없는 재질'이면 부위 객관식. 답은 bench/laya_groups_run.py(.venv_laya)가 쓴다."""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import groups_bench as G  # noqa: E402
from harness.groups_review import tile  # noqa: E402
from harness.render import write_png  # noqa: E402

OUT = os.path.join(G.run.OUT, 'groups_laya')
for case in G.CASES:
    sc, img, boxes, names, cmap, lab, S = G.base(case)
    d = os.path.join(OUT, case[0])
    os.makedirs(d, exist_ok=True)
    mats = [n for n in names if n != '배경']
    items = []
    for j in range(int(lab.max()) + 1):
        if not (lab == j).any():
            continue
        write_png(os.path.join(d, 'c%02d.png' % j), np.clip(tile(img, lab, boxes, j), 0, 255).astype(np.uint8))
        items.append({'id': j, 'png': 'c%02d.png' % j})
    json.dump({'mats': mats, 'parts': sorted(S['part_mats']), 'items': items}, open(os.path.join(d, 'q.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('MAKE', case[0], len(items))
