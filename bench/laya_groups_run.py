# -*- coding: utf-8 -*-
r"""Laya Vision(thaitea/laya-vision, CPU) 로 재질 묶음 답 쓰기. 별도 환경에서만: .venv_laya/Scripts/python.exe bench/laya_groups_run.py <A|B>
A = 보기 순서 그대로, B = 거꾸로. 확률 0.5 미만이면 그 번호는 기본 묶음 그대로(답에서 뺌 → 합칠 때 UNKNOWN).
모델은 영어로 배웠으므로 재질 이름을 영어 보기로 바꿔 묻고 답을 한국어 이름으로 되돌린다."""
import json
import os
import sys

from PIL import Image

import laya

HERE = os.path.dirname(os.path.abspath(__file__))
D0 = os.path.join(HERE, 'out', 'groups_laya')
EN = {'털': 'dark fur', '얼굴': 'face skin', '뿔': 'horn', '귀안': 'inner ear', '선': 'outline', '배경': 'background or edge noise'}
PART_EN = {'머리': 'head', '뿔': 'horn', '뿔 밑동': 'horn base', '귀': 'ear', '갈기': 'mane', '목': 'neck'}
OTHER = 'a different paint not in this list'
order = sys.argv[1]
agent = laya.load_vlm('thaitea/laya-vision', device='cpu')
for case in sorted(os.listdir(D0)):
    d = os.path.join(D0, case)
    Q = json.load(open(os.path.join(d, 'q.json'), encoding='utf-8'))
    mats = Q['mats'] + ['배경']
    opts = [EN.get(m, m) for m in mats] + [OTHER]
    popts = [PART_EN.get(p, p) for p in Q['parts']]
    if order == 'B':
        opts, popts = opts[::-1], popts[::-1]
    back = {EN.get(m, m): m for m in mats}
    pback = {PART_EN.get(p, p): p for p in Q['parts']}
    ans, add, log = [], {}, []
    for it in Q['items']:
        img = Image.open(os.path.join(d, it['png'])).convert('RGB')
        r = agent.predict({'image': img, 'note': 'Cel-shaded drawing of a creature head, front view and side view. '
                                                  'Strongly colored pixels are one color cluster; faded pixels are other clusters.'},
                          {'mat': {'type': 'choice', 'instructions': 'Which painted material are the strongly colored pixels? Shadow tones of one paint count as the same material.', 'criteria': opts},
                           'part': {'type': 'choice', 'instructions': 'On which body part are most of the strongly colored pixels?', 'criteria': popts}},
                          n_permutations=1)
        a = r['answers']
        top = a['mat']['choice']
        p = a['mat']['probabilities'][top]
        log.append({'id': it['id'], 'mat': a['mat'], 'part': a['part']})
        if p < 0.5:
            continue
        if top == OTHER:
            name = '새재질'
            ans.append({'id': it['id'], '재질': name})
            add.setdefault(pback.get(a['part']['choice'], a['part']['choice']), [])
            if name not in add[pback.get(a['part']['choice'], a['part']['choice'])]:
                add[pback.get(a['part']['choice'], a['part']['choice'])].append(name)
        else:
            ans.append({'id': it['id'], '재질': back.get(top, top)})
    out = os.path.join(D0 + '_' + order, case)
    os.makedirs(out, exist_ok=True)
    json.dump({'answers': ans, 'part_mats_add': add}, open(os.path.join(out, 'groups_%s.json' % order), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(log, open(os.path.join(out, 'raw_%s.json' % order), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print('LAYA', order, case, [(x['id'], x['재질']) for x in ans], add, flush=True)
