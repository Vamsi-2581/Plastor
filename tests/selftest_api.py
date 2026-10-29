# -*- coding: utf-8 -*-
"""하네스 도구 층(harness/api.py) 자체 시험. 합성 장면 파이프라인을 도구로만 돌려 본다(Blender 헤드리스, 약 30초).
실행: python tests/selftest_api.py (끝 코드 0 = PASS)"""
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from harness import api  # noqa: E402
import selftest_build as SB  # noqa: E402

RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def main():
    need = {'trace', 'review', 'build', 'card', 'decide', 'views', 'status'}
    ok('도구 목록: 일곱 도구가 있다', need <= set(api.TOOLS), str(sorted(api.TOOLS)))
    bad = [(t, k) for t, d in api.TOOLS.items() for k in d['받는값'] if k.lower() in ('x', 'y', 'z', 'pts', 'points', 'coords', 'vertex', 'vertices', '좌표', '정점')]
    ok('좌표 금지: 좌표·정점을 받는 도구가 없다', not bad, str(bad))
    r = api.call('card', out='x', 좌표=[1, 2])
    ok('받는 값 검사: 모르는 값은 ERROR', r['판정'] == 'ERROR' and '모르는 값 좌표' in r['요약']['받는값_오류'], str(r['요약']))
    r = api.call('build', spec='x', start='아무거나')
    ok('받는 값 검사: 단계 이름이 틀리면 ERROR', r['판정'] == 'ERROR', str(r['요약']))
    base = os.path.join(ROOT, 'bench', 'out', 'api_test')
    shutil.rmtree(base, ignore_errors=True)
    sp, _ = SB.make_case(base, 8)
    r = api.call('build', spec=sp)
    ok('build 도구: 파이프라인이 ERROR 없이 돌고 단계 판정을 돌려준다', r['판정'] in ('PASS', 'FAIL', 'UNKNOWN') and len(r['요약']['단계']) == 8, str(r['요약']))
    out = os.path.join(base, 'out')
    c1 = api.call('card', out=out)
    ok('card 도구: 카드 한 장을 돌려준다', c1['판정'] in api.VERDICTS and c1['요약']['카드'].startswith('#'), c1['요약']['카드'].splitlines()[0] if c1['판정'] != 'ERROR' else str(c1['요약']))
    r = api.call('decide', out=out, part='귀', kind='그림 모순', decision='정면 따름', reason=' ')
    ok('decide 도구: 근거 없는 결정은 거절', r['판정'] == 'ERROR')
    r = api.call('decide', out=out, part='귀', kind='그림 모순', decision='정면 따름', reason='시험')
    D = json.load(open(os.path.join(out, 'model_decisions.json'), encoding='utf-8'))
    ok('decide 도구: 결정을 기록하고 같은 항목은 덮어쓴다', r['판정'] == 'PASS' and len(D) == 1 and api.call('decide', out=out, part='귀', kind='그림 모순', decision='옆 따름', reason='다시')['요약']['결정수'] == 1)
    st = api.call('status', out=out)
    ok('status 도구: 단계 기록을 돌려준다', set(st['요약']) == {'trace', 'body', 'parts', 'merge', 'check', 'views', 'rig', 'card'}, st['판정'])
    bad = RESULTS.count(False)
    print('\n도구 층 자체 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
