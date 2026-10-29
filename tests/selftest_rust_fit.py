# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-001 R-003 R-033
"""원형 연산자 맞추기(`mh fit`, 루프 항목 4) 회귀 시험.
  (가) 같은 입력 → 같은 메시 지문, (나) dev_1000 부피 IoU ≥ 0.90·몸 수 1, (다) 꼬리처럼 한 뷰에만 보이는 부위도 만든다.
v2 과제가 없으면 `mh bundle` 로 dev 묶음을 먼저 만든다. 실행: python tests/selftest_rust_fit.py (끝 코드 0 = PASS)"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
MH = os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def mh(tool, args):
    r = subprocess.run([MH, tool, json.dumps(args, ensure_ascii=False)], capture_output=True, text=True, encoding='utf-8')
    return json.loads(r.stdout)


def main():
    d = os.path.join(ROOT, 'bench', 'v2', 'dev_1000')
    if not os.path.exists(os.path.join(d, 'drawn_all.npz')):
        mh('bundle', {'out': os.path.join(ROOT, 'bench', 'v2'), 'prefix': 'dev', 'start': 1000, 'count': 12})
    tmp = tempfile.mkdtemp()
    a, b = os.path.join(tmp, 'a'), os.path.join(tmp, 'b')
    for o in (a, b):
        r = mh('fit', {'frame': os.path.join(d, 'meta.json'), 'masks': os.path.join(d, 'drawn_all.npz'), 'out': o})
    h = [hashlib.sha1(open(os.path.join(o, 'merged.obj'), 'rb').read()).hexdigest()[:12] for o in (a, b)]
    ok('(가) 같은 입력 → 같은 지문', h[0] == h[1], str(h))
    z = mh('score', {'frame': os.path.join(d, 'meta.json'), 'obj': os.path.join(a, 'merged.obj'), 'truth': os.path.join(d, 'truth_all.npz'),
                     'prims': os.path.join(d, 'prims.json')})['요약']
    ok('(나) 부피 ≥ 0.90, 몸 수 1', z['부피'] >= 0.90 and z['몸_수'] == 1, '부피 %s 몸 %s' % (z['부피'], z['몸_수']))
    ok('(다) 한 뷰에만 보이는 꼬리도 만든다', '꼬리' in r['요약'], sorted(k for k in r['요약'] if not k.startswith('_')))
    bad = RESULTS.count(False)
    print('\n맞추기 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
