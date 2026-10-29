# -*- coding: utf-8 -*-
r"""재질 묶음 검토(Set-of-Mark) 벤치마크. 채택 기준은 돌리기 전에 정함(docs/수정_기록.md 27):
  A 재질 누락: 색조 변형 씨앗 200~211, 첫 판단에서 '귀안' 을 빠뜨림(k=12). 귀 IoU 평균 +0.05 이상이어야 채택.
  B 정상: 씨앗 68~71(k=9). A·B 모두 다른 항목이 0.01 넘게 떨어지면 기각.
  python bench/groups_bench.py make    → bench/out/groups/<사례>/groups.png, groups_prompt_A.txt, _B.txt
  (LLM 이 정답을 보지 않고 groups_A.json, groups_B.json 을 쓴다)
  python bench/groups_bench.py score   → 기본 / 검토 / 정답 묶음(상한) 비교
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import run  # noqa: E402
import trace as T  # noqa: E402
from harness.groups_review import cluster_stats, merge, prompt, sheet  # noqa: E402
from harness.render import write_png  # noqa: E402

CASES = [('A%03d' % s, s, True, {'_drop_mats': ['귀안'], 'k': 12}) for s in range(200, 212)] + \
        [('B%03d' % s, s, False, {}) for s in range(68, 72)]
GD = os.path.join(run.OUT, 'groups')


def base(case):
    name, seed, hue, extra = case
    sc = run.scene_case(seed, extra=extra, hue=hue)
    img, boxes, C, mat, names, cmap, lab = T._CACHE[list(T._CACHE)[0]]
    S = T.jload(os.path.join(run.OUT, 's%02d' % seed, 'spec.json'))
    return sc, img, boxes, names, cmap, lab, S


def oracle(case, img, lab, names):
    """정답 묶음: 픽셀 재질 = 팔레트×톤 중 가장 가까운 색, 군집마다 다수 재질."""
    name, seed, hue, extra = case
    _, _, pal, _ = run.cached_render(seed, hue=hue)
    refs = [(m, pal[m] * t) for m in pal if m != '배경' for t in (0.72, 0.88, 1.06)]
    R = np.array([r for _, r in refs])
    cm = {}
    for j in range(int(lab.max()) + 1):
        px = img[lab == j].astype(float)
        if not len(px):
            continue
        near = np.linalg.norm(px[:, None] - R[None], axis=-1).argmin(1)
        ms = [refs[i][0] for i in near]
        cm[str(j)] = max(set(ms), key=ms.count)
    add = {'귀': ['귀안']} if hue and '귀안' in cm.values() else {}
    return cm, add


def flat(sc):
    return {'%s|%s' % (v, k): b for v, d in sc.items() for k, (a, b) in d.items()}


def main(cmd):
    rows = []
    for case in CASES:
        d = os.path.join(GD, case[0])
        os.makedirs(d, exist_ok=True)
        sc, img, boxes, names, cmap, lab, S = base(case)
        if cmd == 'make':
            write_png(os.path.join(d, 'groups.png'), sheet(img, lab, boxes))
            st = cluster_stats(img, lab, boxes)
            mats = [n for n in names if n != '배경']
            for tag, order in (('A', mats), ('B', mats[::-1])):
                open(os.path.join(d, 'groups_prompt_%s.txt' % tag), 'w', encoding='utf-8').write(prompt(st, names, cmap, order, S['part_mats']))
            print('MAKE', case[0], len(st), '군집')
            continue
        res = {'기본': flat(sc)}
        ocm, oadd = oracle(case, img, lab, names)
        res['정답묶음'] = flat(run.scene_case(case[1], extra=dict(case[3], cluster_mats=ocm, _part_mats_add=oadd), hue=case[2]))
        ad = os.environ.get('GROUPS_ANS')                 # 다른 모델 답 폴더(<폴더>_A/<사례>/groups_A.json 형식), 없으면 기본 자리
        fa = os.path.join(ad + '_A', case[0], 'groups_A.json') if ad else os.path.join(d, 'groups_A.json')
        fb = os.path.join(ad + '_B', case[0], 'groups_B.json') if ad else os.path.join(d, 'groups_B.json')
        if os.path.exists(fa) and os.path.exists(fb):
            cm, add, log = merge(cmap, T.jload(fa), T.jload(fb))
            res['검토'] = flat(run.scene_case(case[1], extra=dict(case[3], cluster_mats=cm, _part_mats_add=add), hue=case[2]))
            res['기록'] = {'바꿈': sum(x['판정'] == '바꿈' for x in log), 'UNKNOWN': sum(x['판정'] == 'UNKNOWN' for x in log), 'cm': cm, 'add': add}
        rows.append((case[0], res))
        print('SCORE', case[0], {k: (round(v.get('front|귀', 0), 3), round(v.get('side|귀', 0), 3)) for k, v in res.items() if k != '기록'}, res.get('기록', {}).get('UNKNOWN'))
    if cmd != 'score':
        return
    for grp in 'AB':
        R = [r for n, r in rows if n[0] == grp]
        for arm in ('기본', '검토', '정답묶음'):
            if not all(arm in r for r in R):
                continue
            keys = sorted(set().union(*[r['기본'] for r in R]))
            print('SUM %s %-6s' % (grp, arm), ' '.join('%s %.3f' % (k, np.mean([r[arm][k] for r in R if k in r[arm]])) for k in keys))
    tag = os.environ.get('GROUPS_TAG', '')
    json.dump(rows, open(os.path.join(GD, 'score%s.json' % (('_' + tag) if tag else '')), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main(sys.argv[1])
