# -*- coding: utf-8 -*-
r"""SAM 옆 귀 진단: 파이프라인에서 SAM 이 딴 귀(raw)가 최종 마스크까지 오며 어디로 사라지는지. 씨앗 80~91."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import run  # noqa: E402
import trace as T  # noqa: E402

tot = {'raw': [], 'final': [], 'lost_to': {}}
for seed in range(80, 92):
    run.scene_case(seed, extra={'method_by_part': {'귀': 'sam'}})
    img, truth, pal, meta = run.cached_render(seed)
    sp = os.path.join(run.OUT, 's%02d' % seed, 'spec.json')
    T._CACHE.clear()
    res = T.build(T.jload(sp), sp, write=False)
    t = truth[('side', '귀')]
    raw, fin = res['raw'].get(('side', '귀')), res['masks'].get(('side', '귀'))
    iou = lambda a, b: float((a & b).sum() / max((a | b).sum(), 1))  # noqa: E731
    tot['raw'].append(iou(raw, t)); tot['final'].append(iou(fin, t))
    lost = raw & ~fin
    for (v, p), m in res['masks'].items():
        if v == 'side' and p != '귀':
            tot['lost_to'][p] = tot['lost_to'].get(p, 0) + int((lost & m).sum())
    tot['lost_to']['(아무 데도)'] = tot['lost_to'].get('(아무 데도)', 0) + int((lost & ~np.any([m for (v, p), m in res['masks'].items() if v == 'side'], 0)).sum())
    print('DIAG s%d 옆귀 raw %.3f final %.3f 잃은 %d px (정답 안 %d)' % (seed, tot['raw'][-1], tot['final'][-1], lost.sum(), (lost & t).sum()), flush=True)
print('DIAG 평균 raw %.3f final %.3f 잃은 곳 %s' % (np.mean(tot['raw']), np.mean(tot['final']), tot['lost_to']))
