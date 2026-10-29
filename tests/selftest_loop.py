# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-035
"""분기 루프 엔진(`mh loop_next`·`mh loop_report`, 루프 항목 4g) 시험. 임시 폴더에서 가짜 기준 명령(끝 코드를 파일로 바꿈)으로 모든 분기를 밟는다.
  (가) 기준 먼저 → 구현 → 엔진 판정 PASS + 추적 PASS → 완료       (나) 보고에 적은 판정은 무시
  (다) PASS + 추적 FAIL → 추적_채우기 → 채우고 추적_끝 → 완료        (라) 선행 미완 항목은 건너뛰고 뒤에 고름(비선형)
  (마) FAIL → 진단·다시 2번 → 조사 → 가설(반증 없으면 거부) → 한 번 더 → 보류
  (바) ERROR → 고치기 → 또 ERROR → 보류    (사) UNKNOWN → 판정 수단 → 보류_요청
  (아) 첫 판정 뒤 기준 파일이 바뀌면 이유 없이는 거부    (자) 보류 항목이 깨우는 항목 완료로 다시 열림
  (차) 전제_바뀜: 이유 없으면 거부, 있으면 순서 바꿈      (카) 사용량 문턱에서 잠·멈춤
  (타) MCP 로 같은 흐름(loop_next·loop_report)
실행: python tests/selftest_loop.py (끝 코드 0 = PASS). 바이너리는 환경 변수 MH 로 바꿀 수 있다."""
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
X = lambda n: 'R' + '-' + '%03d' % n     # 임시 저장소 전용 ID(진짜 장부의 '없는 ID' 검사에 안 걸리게 나눠 씀)
B = tempfile.mkdtemp()
ENV = dict(os.environ, MH_PY=sys.executable)


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail), flush=True)


def w(path, text):
    p = os.path.join(B, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'w', encoding='utf-8').write(text)


def mh(tool, args):
    r = subprocess.run([MH, tool, json.dumps(args, ensure_ascii=False)], cwd=B, capture_output=True, text=True, encoding='utf-8', env=ENV)
    return json.loads(r.stdout)


def nxt(**kw):
    return mh('loop_next', kw)['요약']


def rep(item, kind, **kw):
    r = mh('loop_report', dict(kw, 항목=item, 종류=kind))
    return r['판정'], r['요약']


def code_cmd(name, code):
    """끝 코드를 flag 파일에서 읽는 가짜 기준 명령."""
    w('flags/%s' % name, str(code))
    w('tests/c_%s.py' % name, 'import sys\nsys.exit(int(open("flags/%s").read()))\n' % name)
    return 'tests/c_%s.py' % name


def main():
    ra, rb = X(911), X(912)
    w('docs/조사.md', '조사\n')
    w('docs/d.md', '설계 %s %s\n' % (ra, rb))
    w('src/a.py', '# 추적: %s\n' % ra)
    w('src/b.py', '# 추적: %s\n' % rb)
    w('tests/t_a.py', '# 추적: %s\nimport sys\nsys.exit(0)\n' % ra)
    w('tests/t_b.py', '# 추적: %s\nimport sys\nsys.exit(0)\n' % rb)
    reg = [{'id': ra, '조사': '가', '출처': ['docs/조사.md'], '상태': '채택', '근거': '시험', '자리': 'A', '설계': ['docs/d.md'], '구현': ['src/a.py'], '시험': ['tests/t_a.py']},
           {'id': rb, '조사': '나', '출처': ['docs/조사.md'], '상태': '채택', '근거': '시험', '자리': 'B', '설계': ['docs/d.md']}]
    w('trace/registry.json', json.dumps(reg, ensure_ascii=False))
    mh('trace_verify', {})
    cA, cB, cE, cF, cG, cH = (code_cmd(n, c) for n, c in (('A', 0), ('B', 0), ('E', 1), ('F', 3), ('G', 2), ('H', 1)))
    plan = {'항목': [
        {'id': 'C', '제목': '선행 B', '상태': '대기', '선행': ['B'], '기준': [cA], '추적_자리': 'A'},
        {'id': 'A', '제목': '기준 없음', '상태': '대기'},
        {'id': 'B', '제목': '추적 빠짐', '상태': '대기', '기준': [cB]},
        {'id': 'E', '제목': 'FAIL 길', '상태': '대기', '기준': [cE]},
        {'id': 'F', '제목': 'ERROR 길', '상태': '대기', '기준': [cF]},
        {'id': 'G', '제목': 'UNKNOWN 길', '상태': '대기', '기준': [cG]},
        {'id': 'H', '제목': '기준 바뀜', '상태': '대기', '기준': [cH], '추적_자리': 'A'},
        {'id': 'D', '제목': '보류였다 깨움', '상태': '보류', '깨우는_항목': ['A'], '기준': [cA], '추적_자리': 'A'},
    ]}
    w('loop/plan.json', json.dumps(plan, ensure_ascii=False))

    ok('(카) 사용량 98% → 멈춤, 95% → 잠', nxt(사용량={'주간': 98})['행동'] == '멈춤' and nxt(사용량={'주간': 96})['행동'] == '잠')
    n = nxt()
    ok('(라) 선행 미완(C) 건너뛰고 A, 기준 먼저', n['항목'] == 'A' and n['행동'] == '기준_필요', str(n['항목']))
    v, s = rep('A', '구현_끝')
    ok('    기준 없이 구현_끝은 거부', v == 'FAIL' and '거부' in s)
    rep('A', '기준', 명령=[cA])
    v, s = rep('A', '구현_끝', 판정='FAIL')
    ok('(가) 엔진 판정 PASS + 추적 PASS → 완료', s.get('판정') == 'PASS' and s.get('다음') == '완료', json.dumps(s.get('추적_관문', {}).get('판정'), ensure_ascii=False))
    ok('(나) 보고에 적은 판정은 무시', '무시함' in s)
    ok('(자) A 완료로 보류 D 가 깨어남', s.get('깨움') == ['D'])

    n = nxt()
    v, s = rep(n['항목'], '구현_끝')
    ok('(다) B: PASS + 추적 FAIL → 추적_채우기', n['항목'] == 'B' and s.get('다음') == '추적_채우기')
    reg[1].update({'구현': ['src/b.py'], '시험': ['tests/t_b.py']})
    w('trace/registry.json', json.dumps(reg, ensure_ascii=False))
    mh('trace_verify', {})
    v, s = rep('B', '추적_끝')
    ok('    추적 채우고 추적_끝 → 완료', s.get('다음') == '완료')
    n = nxt()
    v, s = rep(n['항목'], '구현_끝')
    ok('(라) 선행 B 가 끝나자 C 를 고름(비선형)', n['항목'] == 'C' and s.get('다음') == '완료')

    n = nxt()
    path = []
    _, s = rep('E', '구현_끝'); path.append(s.get('다음'))
    _, s = rep('E', '진단', 진단='원인 가', 원인_앎=True); path.append(s.get('다음'))
    _, s = rep('E', '구현_끝'); path.append(s.get('다음'))
    _, s = rep('E', '진단', 진단='원인 나', 원인_앎=True); path.append(s.get('다음'))
    _, s = rep('E', '구현_끝'); path.append(s.get('다음'))
    _, s = rep('E', '진단', 진단='원인 다', 원인_앎=True); path.append(s.get('다음'))
    _, s = rep('E', '조사', 내용='논문 둘'); path.append(s.get('다음'))
    v1, _ = rep('E', '가설', 가설='가설만')
    _, s = rep('E', '가설', 가설='가설', 반증='이러면 거짓'); path.append(s.get('다음'))
    _, s = rep('E', '구현_끝'); path.append(s.get('상태'))
    want = ['진단', '구현', '진단', '구현', '진단', '조사', '가설', '마지막_시도', '보류']
    ok('(마) FAIL → 진단·다시 2번 → 조사 → 가설 → 한 번 더 → 보류', n['항목'] == 'E' and path == want and v1 == 'FAIL', str(path))

    n = nxt()
    p2 = [rep('F', '구현_끝')[1].get('다음')]
    p2.append(rep('F', '구현_끝')[1].get('상태'))
    ok('(바) ERROR → 고치기 → 또 ERROR → 보류', n['항목'] == 'F' and p2 == ['환경_고치기', '보류'], str(p2))
    n = nxt()
    p3 = [rep('G', '구현_끝')[1].get('다음'), rep('G', '보류_요청', 이유='검사기 없음', 단서='합성 정답')[1].get('다음')]
    ok('(사) UNKNOWN → 판정 수단 → 보류_요청', n['항목'] == 'G' and p3 == ['판정_수단', '보류'], str(p3))

    n = nxt()
    rep('H', '구현_끝')
    rep('H', '진단', 진단='시험이 틀림', 원인_앎=True)
    w(cH, 'import sys\nsys.exit(0)  # 기준을 바꿈\n')
    v, s = rep('H', '구현_끝')
    v2, _ = rep('H', '기준_고침')
    v3, _ = rep('H', '기준_고침', 이유='시험 스크립트가 잘못된 파일을 읽었다(결함), 기준 숫자는 그대로')
    _, s4 = rep('H', '구현_끝')
    ok('(아) 기준 파일 바뀜 → 이유 없으면 거부, 이유 있으면 다시 돌림', n['항목'] == 'H' and v == 'FAIL' and '거부' in s and v2 == 'FAIL' and v3 == 'PASS' and s4.get('판정') == 'PASS')

    n = nxt()
    _, s = rep('D', '구현_끝')
    ok('(자) 깨어난 D 를 고르고 완료', n['항목'] == 'D' and s.get('다음') == '완료')
    ok('    남은 항목 없음 → 끝', nxt()['행동'] == '끝')

    plan2 = {'항목': [{'id': 'P', '상태': '대기', '기준': [cA]}, {'id': 'Q', '상태': '대기', '기준': [cA]}]}
    w('loop/plan2.json', json.dumps(plan2))
    mh('loop_next', {'plan': 'loop/plan2.json'})
    r1 = mh('loop_report', {'plan': 'loop/plan2.json', '항목': 'P', '종류': '전제_바뀜', '순서': ['Q']})
    r2 = mh('loop_report', {'plan': 'loop/plan2.json', '항목': 'P', '종류': '전제_바뀜', '순서': ['Q'], '이유': 'P 결과가 Q 의 전제를 바꿈'})
    n2 = mh('loop_next', {'plan': 'loop/plan2.json'})['요약']
    ok('(차) 전제_바뀜: 이유 없으면 거부, 있으면 Q 먼저', r1['판정'] == 'FAIL' and r2['판정'] == 'PASS' and n2['항목'] == 'Q')

    # (타) MCP 로 같은 흐름
    w('loop/plan.json', json.dumps({'항목': [{'id': 'M', '상태': '대기', '기준': [cA], '추적_자리': 'A'}]}))
    p = subprocess.Popen([MH, 'mcp'], cwd=B, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8', env=dict(ENV, MH_ROOT=B))

    def call(i, name, args):
        p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}, ensure_ascii=False) + '\n')
        p.stdin.flush()
        return json.loads(json.loads(p.stdout.readline())['result']['content'][0]['text'])
    a = call(1, 'loop_next', {})
    b = call(2, 'loop_report', {'항목': 'M', '종류': '구현_끝'})
    p.stdin.close()
    p.wait(timeout=30)
    ok('(타) MCP loop_next·loop_report', a['요약']['항목'] == 'M' and b['요약'].get('다음') == '완료')
    n = sum(RESULTS)
    print('루프 엔진 시험 %d/%d PASS' % (n, len(RESULTS)))
    sys.exit(0 if n == len(RESULTS) else 1)


if __name__ == '__main__':
    main()
