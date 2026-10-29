# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-014
"""추적 검사기(`mh trace_check`·`mh trace_verify`) 시험. 임시 폴더에 작은 저장소를 만들고, 검사기가 잡아야 할 경우를 하나씩 넣는다.
  (가) 채택 + 표지 + 시험 PASS 증거 → 반영됨   (나) 표지만 있고 시험이 FAIL(편법) → 시험 FAIL
  (다) 채택인데 구현 없음 → 미구현            (라) 시험 뒤 구현 파일이 바뀜 → 증거 낡음
  (마) 대기인데 자리 없음 → 잊힘              (바) 채택끼리 충돌 → 충돌
  (사) 장부에 없는 ID 표지 → 없는 ID          (아) 출처에 없는 조사 문서 → 등록 안 된 조사 문서
  (자) 관문: 자리 G1(반영됨만) PASS, 자리 G2(편법) FAIL
실행: python tests/selftest_traceability.py (끝 코드 0 = PASS). 바이너리는 환경 변수 MH 로 바꿀 수 있다."""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
MH = os.environ.get('MH') or os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
RESULTS = []
# 아래 ID 들은 임시 저장소 안에서만 쓴다. 이 파일이 진짜 장부 검사에서 '없는 ID' 로 잡히지 않게 글자를 나눠 만든다
X = lambda n: 'R' + '-' + '%03d' % n


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail), flush=True)


def w(base, path, text):
    p = os.path.join(base, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w', encoding='utf-8').write(text)


def mh(base, tool, args):
    env = dict(os.environ, MH_PY=sys.executable)
    r = subprocess.run([MH, tool, json.dumps(args, ensure_ascii=False)], cwd=base, capture_output=True, text=True, encoding='utf-8', env=env)
    return json.loads(r.stdout), r.returncode


def main():
    b = tempfile.mkdtemp()
    a1, a2, a3, a5, a6, a7 = X(901), X(902), X(903), X(905), X(906), X(907)
    w(b, 'docs/조사_가.md', '조사 문서\n')
    w(b, 'docs/조사_빠짐.md', '아무 항목의 출처에도 없음\n')
    w(b, 'docs/설계.md', '설계 %s %s %s\n' % (a1, a2, a3))
    w(b, 'src/좋음.py', '# 추적: %s\n' % a1)
    w(b, 'src/편법.py', '# 추적: %s (표지만, 기능 없음)\n' % a2)
    w(b, 'tests/t_좋음.py', '# 추적: %s\nimport sys\nsys.exit(0)\n' % a1)
    w(b, 'tests/t_편법.py', '# 추적: %s\nimport sys\nsys.exit(1)\n' % a2)
    w(b, 'tests/t_떠돌이.py', '# %s 는 장부에 없다\n' % X(999))
    src = ['docs/조사_가.md']
    reg = [
        {'id': a1, '조사': '좋은 것', '출처': src, '상태': '채택', '근거': '시험', '자리': 'G1', '설계': ['docs/설계.md'], '구현': ['src/좋음.py'], '시험': ['tests/t_좋음.py']},
        {'id': a2, '조사': '편법', '출처': src, '상태': '채택', '근거': '시험', '자리': 'G2', '설계': ['docs/설계.md'], '구현': ['src/편법.py'], '시험': ['tests/t_편법.py']},
        {'id': a3, '조사': '안 만든 것', '출처': src, '상태': '채택', '근거': '시험', '설계': ['docs/설계.md']},
        {'id': a5, '조사': '정하지 않음', '출처': src, '상태': '대기', '근거': '시험'},
        {'id': a6, '조사': '충돌 가', '출처': src, '상태': '보류', '근거': '시험', '다시_볼_조건': '시험'},
        {'id': a7, '조사': '충돌 나', '출처': src, '상태': '기각', '근거': '시험', '다시_볼_조건': '시험'},
    ]
    w(b, 'trace/registry.json', json.dumps(reg, ensure_ascii=False))
    v, code = mh(b, 'trace_verify', {})
    ok('증거 실행기가 시험을 돌림', len(v['요약']['시험']) == 2 and code == 1, str(v['요약']['시험']))
    r, _ = mh(b, 'trace_check', {})
    row = {x['id']: x for x in r['요약']['문제_항목']}
    ok('(가) 채택 + 시험 PASS 증거 → 반영됨', a1 in r['요약']['반영됨'])
    ok('(나) 표지만 있고 시험 FAIL → 시험 FAIL', any('시험 FAIL' in p for p in row.get(a2, {}).get('문제', [])))
    ok('(다) 구현 없음 → 미구현', any('미구현' in p for p in row.get(a3, {}).get('문제', [])))
    ok('(마) 대기인데 자리 없음 → 잊힘', any('잊힘' in p for p in row.get(a5, {}).get('문제', [])))
    g = r['요약']['전체_문제']
    ok('(사) 장부에 없는 ID → 없는 ID', any('없는 ID' in p and X(999) in p for p in g))
    ok('(아) 출처에 없는 조사 문서', any('조사_빠짐.md' in p for p in g) and not any('조사_가.md' in p for p in g))
    ok('전체 판정 FAIL', r['판정'] == 'FAIL')
    g1, c1 = mh(b, 'trace_check', {'항목': 'G1'})
    g2, c2 = mh(b, 'trace_check', {'항목': 'G2'})
    ok('(자) 관문 G1 PASS·G2 FAIL', g1['판정'] == 'PASS' and c1 == 0 and g2['판정'] == 'FAIL' and c2 == 1)
    w(b, 'src/좋음.py', '# 추적: %s\n# 바뀜\n' % a1)
    r, _ = mh(b, 'trace_check', {'항목': 'G1'})
    ok('(라) 시험 뒤 구현이 바뀜 → 증거 낡음', r['판정'] == 'FAIL' and any('증거 낡음' in p for p in r['요약']['문제_항목'][0]['문제']))
    reg[4].update({'상태': '채택', '충돌': [a7]})
    reg[5].update({'상태': '채택'})
    for e in reg[4:]:
        e.update({'설계': ['docs/설계.md']})
    w(b, 'trace/registry.json', json.dumps(reg, ensure_ascii=False))
    r, _ = mh(b, 'trace_check', {})
    row = {x['id']: x for x in r['요약']['문제_항목']}
    ok('(바) 채택끼리 충돌', any('충돌' in p for p in row.get(a6, {}).get('문제', [])))
    n = sum(RESULTS)
    print('추적 검사기 시험 %d/%d PASS' % (n, len(RESULTS)))
    sys.exit(0 if n == len(RESULTS) else 1)


if __name__ == '__main__':
    main()
