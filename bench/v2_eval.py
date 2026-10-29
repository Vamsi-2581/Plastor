# -*- coding: utf-8 -*-
"""루프 항목 4: ③ 원형 연산자 맞추기(`mh fit`)를 v2 과제에 돌리고, 기준(docs/루프_작업목록.md 4)으로 ② 와 비교한다.
  python bench/v2_eval.py fit <접두사 dev|cf> [라벨 ③맞추기] [하위폴더 fit]   맞추기 + 채점 → bench/v2/ledger.jsonl
  python bench/v2_eval.py judge <접두사> [라벨]                               기준 판정(② 대비)
"""
import json
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'bench'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import v2_base2 as B  # noqa: E402

DEV_MH = os.path.join(ROOT, 'rust', 'target_dev', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
if os.path.exists(DEV_MH):
    B.MH = DEV_MH


def names(prefix):
    return [n for n in B.tasks() if n.startswith(prefix + '_')]


def fit(prefix, label='③맞추기', sub='fit', blend='0'):
    for n in names(prefix):
        d = os.path.join(B.V2, n)
        r = B.mh('fit', {'frame': os.path.join(d, 'meta.json'), 'masks': os.path.join(d, 'drawn_all.npz'), 'out': os.path.join(d, sub), 'blend': float(blend)})
        row = B.score(n, os.path.join(d, sub, 'merged.obj'), label, {'맞추기': {'걸린초': r['요약'].get('_걸린초')}, 'LLM_호출': 0, '좌표_입력': 0})
        print('FIT', n, row.get('오류_주입'), row.get('실루엣'), row.get('부피'), row.get('몸_수'))


def gt_quarter(n):
    """정답 메시의 3/4 폭 비(같은 채점기)."""
    d = os.path.join(B.V2, n)
    p = os.path.join(d, 'gt_score.json')
    if not os.path.exists(p):
        z = B.mh('score', {'frame': os.path.join(d, 'meta.json'), 'obj': os.path.join(d, 'gt.obj'), 'truth': os.path.join(d, 'truth_all.npz'),
                           'prims': os.path.join(d, 'prims.json')})
        json.dump(z['요약'], open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return json.load(open(p, encoding='utf-8'))['3/4폭비']


def judge(prefix, label='③맞추기'):
    rows = [json.loads(x) for x in open(B.LEDGER, encoding='utf-8')]
    last = {}
    for r in rows:
        last[(r['과제'], r['기준선'])] = r
    ns = names(prefix)
    A = [last[(n, '②하네스')] for n in ns]
    C = [last[(n, label)] for n in ns]
    sil = lambda r: (r['실루엣']['front'] + r['실루엣']['side']) / 2
    q = {n: gt_quarter(n) for n in ns}
    m = lambda xs: float(np.mean(xs))
    a_vol, c_vol = m([r['부피'] for r in A]), m([r['부피'] for r in C])
    a_sil, c_sil = m([sil(r) for r in A]), m([sil(r) for r in C])
    a_q, c_q = m([abs(r['3/4폭비'] - q[r['과제']]) for r in A]), m([abs(r['3/4폭비'] - q[r['과제']]) for r in C])
    a_r, c_r = m([r['거칠기'] for r in A]), m([r['거칠기'] for r in C])
    one = sum(r['몸_수'] == 1 for r in C)
    crit = {
        '부피 ≥ ② + 0.15': (c_vol >= a_vol + 0.15, '%.4f vs %.4f' % (c_vol, a_vol)),
        '실루엣 ≥ ② − 0.01': (c_sil >= a_sil - 0.01, '%.4f vs %.4f' % (c_sil, a_sil)),
        '3/4 폭 비 오차 ≤ ② 의 절반': (c_q <= a_q / 2, '%.4f vs %.4f' % (c_q, a_q)),
        '거칠기 ≤ ②': (c_r <= a_r, '%.2f vs %.2f' % (c_r, a_r)),
        '몸 수 1 ≥ 11/12': (one >= 11, '%d/%d' % (one, len(C))),
    }
    for k, (ok, d) in crit.items():
        print('%s %s %s' % ('PASS' if ok else 'FAIL', k, d))
    # 오류 주입 과제와 없는 과제 따로(참고)
    for inj in ('none', 'side_height', 'twin'):
        cc = [r for r in C if r['오류_주입'] == inj]
        aa = [r for r in A if r['오류_주입'] == inj]
        if cc:
            print('  [%s] 부피 ③ %.4f ② %.4f, 실루엣 ③ %.4f ② %.4f' % (inj, m([r['부피'] for r in cc]), m([r['부피'] for r in aa]), m([sil(r) for r in cc]), m([sil(r) for r in aa])))
    verdict = 'PASS' if all(ok for ok, _ in crit.values()) else 'FAIL'
    print('항목 4 판정(%s, %s): %s' % (prefix, label, verdict))
    return verdict


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'fit':
        fit(a[1], *(a[2:5]))
    else:
        judge(a[1], *(a[2:3]))
