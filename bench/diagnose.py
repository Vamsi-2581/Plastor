# -*- coding: utf-8 -*-
r"""벤치마크 오차 진단: 정답과 다른 픽셀을 원인별로 나눈다(규칙을 어디부터 고칠지 정하려고).
놓침(정답인데 결과에 없음)
  재질 틀림   : 그 픽셀의 재질이 부위 재질 목록에 없다(군집·재질 묶음 문제)
  LLM 선 너무 멂: 거친 다각형에서 탐색 폭(d)보다 멀다(트레이스 오차가 도구 범위 밖)
  규칙이 뺌   : 범위 안·재질 맞음인데 선택되지 않음(영역 선택 규칙 문제)
  다른 부위가 가져감: 결과에서 다른 부위 마스크에 들어감(겹침 해소·덩어리 배정 문제)
초과(결과인데 정답 아님)
  정답의 다른 부위: 그 픽셀이 정답에서는 어느 부위인지(목·갈기·귀 …)
  정답 배경/이름 없음
실행: python bench/diagnose.py --seed 7 --view front --part 머리
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import trace as T  # noqa: E402
from harness.trace import _dilate, fill_poly  # noqa: E402
from harness.render import write_png  # noqa: E402
from scene import render  # noqa: E402


def main(argv):
    seed = int(argv[argv.index('--seed') + 1])
    view = argv[argv.index('--view') + 1]
    part = argv[argv.index('--part') + 1]
    diagnose(seed, view, part, picture=True)


def diagnose(seed, view, part, picture=False, extra=None):
    """오차 원인별 픽셀 수(dict). extra 는 spec 덮어쓰기. 장면 폴더(spec·rough)는 run.scene_case 가 먼저 만들어 둔다."""
    d = os.path.join(HERE, 'out', 's%02d' % seed)
    import run as R; img, truth, pal, meta = R.cached_render(seed)
    sp = os.path.join(d, 'spec.json')
    S = T.jload(sp)
    S.update(extra or {})
    T._CACHE.clear()
    res = T.build(S, sp, write=False)
    M, mat, names = res['masks'], res['mat'], res['names']
    rough = T.jload(os.path.join(d, 'rough.json'))
    pm = np.zeros(img.shape[:2], bool)
    for it in rough['panels'][view]['parts']:
        if it['name'] == part:
            for p in it['polys']:
                pm |= fill_poly(pm.shape, p['pts'])
    t = truth.get((view, part), np.zeros(pm.shape, bool))
    m = M.get((view, part), np.zeros(pm.shape, bool))
    mats = [names.index(n) for n in S['part_mats'][part]]
    D = _dilate(pm, S.get('snap_px', 8))
    miss, ex = t & ~m, m & ~t
    other = np.zeros(pm.shape, bool)
    for k, mm in M.items():
        if k[0] == view and k[1] != part:
            other |= mm
    rep = {'정답': int(t.sum()), '결과': int(m.sum()), 'IoU': round(float((t & m).sum() / max((t | m).sum(), 1)), 3)}
    rep['놓침'] = {'재질 틀림': int((miss & ~np.isin(mat, mats)).sum()),
                 'LLM 선 너무 멂': int((miss & np.isin(mat, mats) & ~D).sum()),
                 '다른 부위가 가져감': int((miss & np.isin(mat, mats) & D & other).sum()),
                 '규칙이 뺌': int((miss & np.isin(mat, mats) & D & ~other).sum())}
    exo = {}
    for k, tt in truth.items():
        if k[0] == view and k[1] != part:
            n = int((ex & tt).sum())
            if n:
                exo['정답 ' + k[1]] = n
    named = np.zeros(pm.shape, bool)
    for k, tt in truth.items():
        if k[0] == view:
            named |= tt
    exo['정답 배경/이름 없음'] = int((ex & ~named).sum())
    rep['초과'] = exo
    rep['초과_다각형_안'] = int((ex & pm).sum())
    if not picture:
        return rep
    print('DIAG', json.dumps(rep, ensure_ascii=False))
    # 그림: 초록=맞음, 빨강=놓침, 파랑=초과, 노랑 선=거친 다각형
    vis = img.copy()
    vis[t & m] = (0.5 * vis[t & m] + [0, 110, 0]).astype(np.uint8)
    vis[miss] = (255, 40, 40)
    vis[ex] = (40, 120, 255)
    e = pm & ~(np.roll(pm, 1, 0) & np.roll(pm, -1, 0) & np.roll(pm, 1, 1) & np.roll(pm, -1, 1))
    vis[e] = (255, 230, 0)
    c0 = 0 if view == 'front' else 300
    write_png(os.path.join(HERE, 'out', 'diag_s%02d_%s_%s.png' % (seed, view, part)), np.repeat(np.repeat(vis[:, c0:c0 + 300], 3, 0), 3, 1))
    return rep


if __name__ == '__main__':
    main(sys.argv[1:])
