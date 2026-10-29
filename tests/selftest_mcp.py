# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-011 R-012 R-013 R-015 R-018 R-019
"""하네스 MCP 서버(`mh mcp`, 루프 항목 4e) 시험. stdio JSON-RPC 로 직접 말을 건다.
  (가) initialize·tools/list·tools/call 이 stdio 로 동작
  (나) 역할(상태·관찰·행동·검증 관문·판단·기억·예산·호출 기록)이 다 있고, 좌표 인자를 거부하며, 관문 FAIL 3번이면 행동이 막힌다
  (다) dev_1000 에서 MCP 에피소드(기본 연산자 설계도)의 메시 지문이 CLI `mh fit` 과 같다
실행: python tests/selftest_mcp.py (끝 코드 0 = PASS). 바이너리는 환경 변수 MH 로 바꿀 수 있다."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
MH = os.environ.get('MH') or os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail), flush=True)


class Client:
    def __init__(self):
        self.p = subprocess.Popen([MH, 'mcp'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding='utf-8')
        self.n = 0

    def req(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.n, 'method': method, 'params': params or {}}, ensure_ascii=False) + '\n')
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def note(self, method):
        self.p.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': method}) + '\n')
        self.p.stdin.flush()

    def tool(self, name, args):
        r = self.req('tools/call', {'name': name, 'arguments': args})['result']
        return json.loads(r['content'][0]['text']), r['isError']

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=30)


def sha(p):
    return hashlib.sha1(open(p, 'rb').read()).hexdigest()[:12]


def main():
    d = os.path.join(ROOT, 'bench', 'v2', 'dev_1000')
    c = Client()
    r = c.req('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'selftest', 'version': '0'}})
    c.note('notifications/initialized')
    init_ok = r['result']['serverInfo']['name'] == 'modeler-harness' and 'tools' in r['result']['capabilities']
    names = [t['name'] for t in c.req('tools/list')['result']['tools']]
    body, err = c.tool('harness_rules', {})
    ok('(가) initialize·tools/list·tools/call', init_ok and len(names) >= 13 and not err and 'PASS' in body['요약']['규칙'], '도구 %d개' % len(names))

    roles = {'상태': 'episode_start', '관찰': 'observe_look', '행동': 'act_fit', '검증 관문': 'verify_gate', '판단': 'judge', '기억': 'memory_lessons', '예산': 'episode_reset_budget'}
    missing = [k for k, v in roles.items() if v not in names]
    ok('(나-1) 역할 도구가 다 있다', not missing, '빠짐 %s' % missing)
    prompts = c.req('prompts/list')['result']['prompts']
    res = c.req('resources/read', {'uri': 'harness://anatomy'})['result']['contents'][0]['text']
    ok('(나-2) 규칙이 prompts·resources 로 나온다', prompts and '두개골' in res)

    ep = 'selftest_mcp'
    shutil.rmtree(os.path.join(ROOT, 'episodes', ep), ignore_errors=True)
    body, err = c.tool('episode_start', {'task_dir': d, 'id': ep})
    ok('(나-3) episode_start', not err and body['판정'] == 'PASS', str(body['요약'].get('부위')))
    parts = body['요약']['부위']
    dg, _ = c.tool('observe_digest', {'id': ep})
    zm, zerr = c.tool('observe_zoom', {'id': ep, 'part': '머리', 'view': 'front'})
    ok('(나-4) 관찰(숫자 표·확대 그림)', len(dg['요약']['표']) > 0 and not zerr and os.path.exists(os.path.join(ROOT, zm['요약']['그림'])))
    bad, berr = c.tool('act_blueprint', {'id': ep, 'parts': {'머리': {'연산자': '덩어리', '중심': [0.1, 0.2, 1.3]}}})
    ok('(나-5) 좌표 인자를 거부', berr and bad['판정'] == 'ERROR', bad['요약'].get('이유', ''))

    # (다) 기본 연산자 설계도 → CLI 와 같은 지문
    kind = lambda p: '관' if p in ('목', '다리', '꼬리', '뿔', '뿔 밑동') else ('판' if p == '귀' else '덩어리')
    bp = {p: {'연산자': kind(p), '분류': '정체성', '근거': '기본'} for p in parts}
    _, e1 = c.tool('act_blueprint', {'id': ep, 'parts': bp})
    fit, e2 = c.tool('act_fit', {'id': ep})
    tmp = tempfile.mkdtemp()
    subprocess.run([MH, 'fit', json.dumps({'frame': os.path.join(d, 'meta.json'), 'masks': os.path.join(d, 'drawn_all.npz'), 'out': tmp}, ensure_ascii=False)], capture_output=True, cwd=ROOT)
    h_mcp, h_cli = sha(os.path.join(ROOT, 'episodes', ep, 'merged.obj')), sha(os.path.join(tmp, 'merged.obj'))
    ok('(다) MCP 에피소드 지문 = CLI 지문', not e1 and not e2 and h_mcp == h_cli, '%s / %s' % (h_mcp, h_cli))
    lk, lerr = c.tool('observe_look', {'id': ep})
    ok('(나-4b) 관찰(헤드리스 3/4·위·아래 그림)', not lerr and len(lk['요약'].get('그림', [])) >= 3, '%d장' % len(lk['요약'].get('그림', [])))
    g, _ = c.tool('verify_gate', {'id': ep, '단계': '형상'})
    print('   기본 설계도 관문:', g['판정'], json.dumps(g['요약']['검사'], ensure_ascii=False))

    # 예산: 판(얇은 판)만 쓴 설계도로 관문을 거듭 떨어뜨린다 → 3번째 FAIL 뒤 act_fit 거부
    ep2 = 'selftest_mcp_budget'
    shutil.rmtree(os.path.join(ROOT, 'episodes', ep2), ignore_errors=True)
    c.tool('episode_start', {'task_dir': d, 'id': ep2})
    c.tool('act_blueprint', {'id': ep2, 'parts': {p: {'연산자': '판', '근거': '시험: 일부러 틀림'} for p in parts}})
    c.tool('act_fit', {'id': ep2})
    verdicts = [c.tool('verify_gate', {'id': ep2, '단계': '형상'})[0]['판정'] for _ in range(3)]
    blocked, _ = c.tool('act_fit', {'id': ep2})
    st, _ = c.tool('episode_status', {'id': ep2})
    ok('(나-6) 관문 FAIL 3번 → 행동 막힘', verdicts == ['FAIL'] * 3 and blocked['판정'] == 'FAIL' and st['요약']['막힘'] is True, str(verdicts))
    rs, _ = c.tool('episode_reset_budget', {'id': ep2, '이유': '시험'})
    ok('(나-7) 예산 되돌림', rs['요약']['막힘'] is False)
    lines = open(os.path.join(ROOT, 'episodes', ep2, 'trace.jsonl'), encoding='utf-8').read().splitlines()
    ok('(나-8) 모든 호출 기록(trace.jsonl)', len(lines) >= 8 and all('판정' in json.loads(x) for x in lines), '%d줄' % len(lines))
    jr, _ = c.tool('judge', {'runs': [{'가족': 'a', '순서': 'A', '답': {'q1': 'x'}}, {'가족': 'a', '순서': 'B', '답': {'q1': 'x'}},
                                      {'가족': 'b', '순서': 'A', '답': {'q1': 'x'}}, {'가족': 'b', '순서': 'B', '답': {'q1': 'x'}}]})
    ml, _ = c.tool('memory_lessons', {'단어': '그림 모순'})
    ok('(나-9) 판단 모음·기억 검색', jr['판정'] == 'PASS' and len(ml['요약']['교훈']) >= 1, '교훈 %d건' % len(ml['요약']['교훈']))
    c.close()
    n = sum(RESULTS)
    print('MCP 시험 %d/%d PASS' % (n, len(RESULTS)))
    sys.exit(0 if n == len(RESULTS) else 1)


if __name__ == '__main__':
    main()
