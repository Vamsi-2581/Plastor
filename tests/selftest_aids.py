# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-011 R-012 R-015
"""LLM 보완 도구 시험(docs/조사_LLM한계.md 2장). 기준(돌리기 전에 정함):
  digest: 합성 장면 정답 마스크에서 정면 뿔 조각 수 = 2(좌우), 귀 = 2, 머리 좌우 대칭 ≥ 0.9.
  zoom: 정면 귀 그림의 긴 변 ≤ 1568 이고 원래 자른 크기의 2배 이상, 조각 색 수 = 정면 귀 조각 수, PNG 생김.
  judge: (가) 두 가족·순서 바꿈 모두 같은 답 → PASS·전부 확정, (나) 한 문항만 순서에 따라 답이 바뀜 → 그 문항 UNKNOWN,
         (다) 두 가족이 체계적으로 다름 → 카파 < 0.6 → 전체 UNKNOWN. 카파 계산: 알려진 예 0.5.
실행: python tests/selftest_aids.py (끝 코드 0 = PASS)"""
import json
import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from build import Frame  # noqa: E402
from harness import api  # noqa: E402
from harness.llm_aids import digest, judge, kappa, zoom_image  # noqa: E402

RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def main():
    d = os.path.join(ROOT, 'bench', 'm0', 'synth_basic')
    fr = Frame.load({'meta': os.path.join(d, 'meta.json')}, ROOT)
    tmp = tempfile.mkdtemp()
    z = np.load(os.path.join(d, 'truth.npz'))
    masks = os.path.join(tmp, 't.npz')
    np.savez(masks, **{k: z[k] for k in z.files})
    g = digest(masks, fr)
    P = g['부위']
    ok('digest: 정면 뿔 2조각·귀 2조각·머리 대칭 ≥ 0.9', P['뿔']['front']['조각_수'] == 2 and P['귀']['front']['조각_수'] == 2 and P['머리']['front']['좌우_대칭'] >= 0.9,
       '뿔 %d 귀 %d 머리 대칭 %.3f' % (P['뿔']['front']['조각_수'], P['귀']['front']['조각_수'], P['머리']['front']['좌우_대칭']))
    img, info = zoom_image(np.load(os.path.join(d, 'drawing.npy')), masks, '귀', 'front')
    r0, r1, c0, c1 = info['자른_범위_px']
    out = os.path.join(tmp, 'z.png')
    rr = api.call('zoom', drawing=os.path.join(d, 'drawing.npy'), masks=masks, part='귀', view='front', out=out)
    ok('zoom: 긴 변 ≤ 1568, 2배 이상 키움, 조각 색 = 조각 수, PNG 생김',
       max(img.shape[:2]) <= 1568 and img.shape[0] >= 2 * (r1 - r0) and len(info['조각_색']) == P['귀']['front']['조각_수'] and os.path.exists(out),
       '크기 %s 배율 %d 색 %d PNG %s(%s)' % (img.shape[:2], info['배율'], len(info['조각_색']), os.path.exists(out), rr['판정']))
    same = [{'가족': f, '순서': o, '답': {'1': '관', '2': '판', '3': '덩어리'}} for f in ('claude', 'codex') for o in ('A', 'B')]
    a = judge(same)
    ok('judge (가) 모두 같음 → PASS·전부 확정', a['판정'] == 'PASS' and all(x['판정'] == '확정' for x in a['문항'].values()), str(a['판정']))
    flip = [dict(r, 답=dict(r['답'], **({'2': '덩어리'} if r['순서'] == 'B' else {}))) for r in same]
    b = judge(flip)
    ok('judge (나) 순서에 따라 바뀐 문항만 UNKNOWN', b['문항']['2']['판정'] == 'UNKNOWN' and b['문항']['1']['판정'] == '확정', json.dumps({k: v['판정'] for k, v in b['문항'].items()}, ensure_ascii=False))
    many = {str(i): ('관' if i % 2 else '판') for i in range(10)}
    other = {str(i): ('판' if i % 3 else '관') for i in range(10)}
    sysdiff = [{'가족': 'claude', '순서': o, '답': many} for o in ('A', 'B')] + [{'가족': 'codex', '순서': o, '답': other} for o in ('A', 'B')]
    c = judge(sysdiff)
    k = kappa(['a', 'a', 'b', 'b'], ['a', 'b', 'b', 'b'])
    ok('judge (다) 가족이 체계적으로 다름 → 카파 < 0.6 → UNKNOWN, 카파 예 0.5', c['판정'] == 'UNKNOWN' and c['가족_카파'] < 0.6 and abs(k - 0.5) < 1e-9,
       '카파 %.3f 예 %.3f' % (c['가족_카파'], k))
    bad = RESULTS.count(False)
    print('\nLLM 보완 도구 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
