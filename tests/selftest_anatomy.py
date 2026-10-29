# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-024
"""해부 규칙 검사기 시험(루프 항목 4b 기준 가, 돌리기 전에 적음).
  정상 맞추기 결과(dev_1000)는 '위반' 0, 일부러 망친 셋은 각각 해당 규칙 '위반':
  (1) 머리 앞뒤 반지름 ×0.2(납작 원판) → 덩어리_납작함, (2) 뿔 조절점을 머리 높이 반지름 2배만큼 아래로 → 뿔_뿌리_높이,
  (3) 귀를 뿔 뿌리보다 머리 높이 반지름 1배 위로 → 귀_아래.
실행: python tests/selftest_anatomy.py (끝 코드 0 = PASS)"""
import copy
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
MH = os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
DEV = os.path.join(ROOT, 'rust', 'target_dev', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
if os.path.exists(DEV) and os.path.getmtime(DEV) > os.path.getmtime(MH):
    MH = DEV
RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def mh(tool, args):
    r = subprocess.run([MH, tool, json.dumps(args, ensure_ascii=False)], capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
    return json.loads(r.stdout)


def check(insts, tmp, name):
    p = os.path.join(tmp, name + '.json')
    json.dump(insts, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    r = mh('anatomy', {'insts': p})['요약']
    return r, {x['규칙'] for x in r['항목'] if x['판정'] == '위반'}


def main():
    d = os.path.join(ROOT, 'bench', 'v2', 'dev_1000')
    tmp = tempfile.mkdtemp()
    mh('fit', {'frame': os.path.join(d, 'meta.json'), 'masks': os.path.join(d, 'drawn_all.npz'), 'out': tmp, 'rules': 'rules/anatomy_rules.json'})
    base = json.load(open(os.path.join(tmp, 'fit_insts.json'), encoding='utf-8'))
    r, v = check(base, tmp, 'ok')
    ok('정상 모델 위반 0', r['위반'] == 0, '위반 %d 주의 %d %s' % (r['위반'], r['주의'], sorted(v)))
    head = max((e for it in base if it['부위'] == '머리' for e in it['타원체']), key=lambda e: e['r'][0] * e['r'][1] * e['r'][2])
    rz = head['r'][2]
    b1 = copy.deepcopy(base)
    for it in b1:
        if it['부위'] == '머리':
            for e in it['타원체']:
                e['r'][1] *= 0.2
    b2 = copy.deepcopy(base)
    for it in b2:
        if it['부위'] == '뿔':
            it['조절점'] = [[c[0], c[1], c[2] - 2 * rz] for c in it['조절점']]
    root_z = max(it['조절점'][0][2] for it in base if it['부위'] == '뿔')
    b3 = copy.deepcopy(base)
    for it in b3:
        if it['부위'] == '귀':
            for e in it['타원체']:
                e['c'][2] = root_z + rz
    for name, b, rule in (('납작 머리', b1, '덩어리_납작함'), ('뿔 뿌리 아래', b2, '뿔_뿌리_높이'), ('귀가 뿔 위', b3, '귀_아래')):
        _, v = check(b, tmp, name)
        ok('망친 모델 %s → %s 위반' % (name, rule), rule in v, str(sorted(v)))
    bad = RESULTS.count(False)
    print('\n해부 검사기 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
