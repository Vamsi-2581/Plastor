# -*- coding: utf-8 -*-
r"""재질 묶음 질문 v2(L13·L18): 묶기 전체가 아니라 "목록에 없는 물감으로 칠한 군집 번호는?" 한 질문. 현재 묶음은 보여 주지 않는다.
채택 기준(돌리기 전에 정함, docs/루프_작업목록.md 3번): 재질 누락 장면(새 씨앗 212~223) 귀 평균(정면·옆) +0.05, 다른 항목 −0.01 이내(정상 72~75 포함).
  python bench/groups_v2.py make   → bench/out/groups_v2/<사례>/groups.png, q_A.txt, q_B.txt(재질 목록 순서만 다름)
  (답: groups_v2/<사례>/ans_A.json, ans_B.json = {"new": [번호...], "part": "부위"})
  python bench/groups_v2.py score
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import groups_bench as G  # noqa: E402
from harness.groups_review import cluster_stats, sheet  # noqa: E402
from harness.render import write_png  # noqa: E402

G.CASES = [('A%03d' % s, s, True, {'_drop_mats': ['귀안'], 'k': 12}) for s in range(212, 224)] + [('B%03d' % s, s, False, {}) for s in range(72, 76)]
OUT = os.path.join(G.run.OUT, 'groups_v2')

Q = '''그림 groups.png 의 칸마다 빨간 번호가 색 군집 번호다. 칸에서 진하게 보이는 픽셀이 그 군집이다(옅은 것은 다른 군집).
이 그림은 크리처 머리의 정면·옆 그림이다. 칠한 물감(재질) 목록: {mats}. 같은 물감의 그림자·밝은 톤은 같은 재질로 본다.
질문 하나: 목록의 어느 물감과도 다른 물감으로 칠한 면이 있는가? 있으면 그 군집 번호들과, 그 면이 있는 부위({parts} 중 하나)를 답하라.
없으면 빈 목록. 배경·가장자리 잡티는 세지 않는다.
답 형식(JSON): {{"new": [번호, ...], "part": "부위 또는 빈 문자열"}}'''


def main(cmd):
    rows = []
    for case in G.CASES:
        d = os.path.join(OUT, case[0])
        os.makedirs(d, exist_ok=True)
        sc, img, boxes, names, cmap, lab, S = G.base(case)
        mats = [n for n in names if n != '배경']
        parts = sorted(S['part_mats'])
        if cmd == 'make':
            write_png(os.path.join(d, 'groups.png'), sheet(img, lab, boxes))
            for tag, mm in (('A', mats), ('B', mats[::-1])):
                open(os.path.join(d, 'q_%s.txt' % tag), 'w', encoding='utf-8').write(Q.format(mats=', '.join(mm), parts=', '.join(parts)))
            print('MAKE', case[0])
            continue
        res = {'기본': G.flat(sc)}
        fa, fb = os.path.join(d, 'ans_A.json'), os.path.join(d, 'ans_B.json')
        a, b = json.load(open(fa, encoding='utf-8')), json.load(open(fb, encoding='utf-8'))
        new = sorted(set(map(int, a.get('new', []))) & set(map(int, b.get('new', []))))      # 두 답이 같은 번호만
        part = a.get('part') if a.get('part') == b.get('part') else ''
        if new and part:
            cm = {str(j): '새재질' for j in new}
            res['v2'] = G.flat(G.run.scene_case(case[1], extra=dict(case[3], cluster_mats=cm, _part_mats_add={part: ['새재질']}), hue=case[2]))
        else:
            res['v2'] = res['기본']
        res['답'] = {'new': new, 'part': part}
        rows.append((case[0], res))
        print('V2', case[0], res['답'], {k: (round(res['기본'].get(k, 0), 3), round(res['v2'].get(k, 0), 3)) for k in ('front|귀', 'side|귀')})
    if cmd == 'score':
        for grp in 'AB':
            R = [r for n, r in rows if n[0] == grp]
            keys = sorted(set().union(*[r['기본'] for r in R]))
            for arm in ('기본', 'v2'):
                print('SUM %s %-4s' % (grp, arm), ' '.join('%s %.3f' % (k, np.mean([r[arm][k] for r in R if k in r[arm]])) for k in keys))
        json.dump(rows, open(os.path.join(OUT, 'score.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main(sys.argv[1])
