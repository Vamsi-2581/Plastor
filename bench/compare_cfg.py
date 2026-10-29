# -*- coding: utf-8 -*-
r"""설정 두 개를 같은 장면 묶음에서 비교(평균·최저). python bench/compare_cfg.py <씨앗 시작> <개수> '<설정A json>' '<설정B json>'"""
import json
import sys

import numpy as np

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run  # noqa: E402

s0, n = int(sys.argv[1]), int(sys.argv[2])
cfgs = [json.loads(a) for a in sys.argv[3:5]]
hue = '--hue' in sys.argv
twotone = '--twotone' in sys.argv
checker = '--checker' in sys.argv
res = []
for cfg in cfgs:
    items = {}
    for s in range(s0, s0 + n):
        for v, d in run.scene_case(s, extra=cfg, hue=hue, twotone=twotone, checker=checker).items():
            for k, (a, b) in d.items():
                items.setdefault('%s|%s' % (v, k), []).append(b)
    res.append({k: (float(np.mean(x)), float(np.min(x))) for k, x in items.items()})
print('CMP 씨앗 %d~%d  A=%s  B=%s' % (s0, s0 + n - 1, sys.argv[3], sys.argv[4]))
for k in sorted(res[0]):
    a, b = res[0][k], res[1].get(k, (0, 0))
    print('CMP %-12s A %.3f(%.2f)  B %.3f(%.2f)  차 %+.3f' % (k, a[0], a[1], b[0], b[1], b[0] - a[0]))
print('CMP 전체 평균 A %.4f B %.4f' % (np.mean([v[0] for v in res[0].values()]), np.mean([v[0] for v in res[1].values()])))
