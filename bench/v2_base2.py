# -*- coding: utf-8 -*-
"""루프 항목 3: 기준선 ②(지금 하네스: build.py 헐 + Blender 합치기)를 v2 과제 묶음에 돌린다(docs/루프_작업목록.md).
입력은 생성기의 '그린 것' 마스크(drawn_all.npz = 오류가 든 도면의 이상적 트레이스). 채점은 Rust `mh score`(3D 정답 대비).
기준선 ② 자체가 파이썬 파이프라인이라 이 스크립트도 파이썬이다(Rust 이전 항목 7 에서 옮김).
  python bench/v2_base2.py [과제 이름...]      결과 bench/v2/<과제>/base2/, 장부 bench/v2/ledger.jsonl
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
V2 = os.path.join(ROOT, 'bench', 'v2')
MH = os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
LEDGER = os.path.join(V2, 'ledger.jsonl')
BODY = '몸통'
PARTS = ['머리', '목', '다리', '꼬리', '뿔', '귀']


def mh(tool, args):
    r = subprocess.run([MH, tool, json.dumps(args, ensure_ascii=False)], capture_output=True, text=True, encoding='utf-8')
    return json.loads(r.stdout)


def tasks():
    out = []
    for f in sorted(os.listdir(V2)):
        if f.endswith('_목록.json'):
            out += [t['과제'] for t in json.load(open(os.path.join(V2, f), encoding='utf-8'))['과제']]
    return out


def score(name, obj, label, extra=None):
    d = os.path.join(V2, name)
    z = mh('score', {'frame': os.path.join(d, 'meta.json'), 'obj': obj, 'truth': os.path.join(d, 'truth_all.npz'),
                     'prims': os.path.join(d, 'prims.json')})
    task = json.load(open(os.path.join(d, 'task.json'), encoding='utf-8'))
    row = dict({'시각': time.strftime('%Y-%m-%dT%H:%M:%S'), '과제': name, '기준선': label, '오류_주입': (task.get('오류_주입') or {}).get('종류', 'none'),
                'OBJ': os.path.relpath(obj, ROOT)}, **z.get('요약', {'판정': z.get('판정')}))
    row.update(extra or {})
    with open(LEDGER, 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    return row


def run(name):
    import build as B
    d = os.path.join(V2, name, 'base2')
    os.makedirs(d, exist_ok=True)
    for f in ('merged.obj', 'body.obj'):
        if os.path.exists(os.path.join(d, f)):
            os.remove(os.path.join(d, f))
    S = {'out': '.', 'frame': {'meta': '../meta.json'}, 'trace': {'masks': '../drawn_all.npz'},
         'body': {'part': BODY, 'method': 'hull', 'smooth': 1.5},
         'parts': [{'name': p, 'embed_px': 4} for p in PARTS], 'merge': {'ratio': 0.06}}
    sp = os.path.join(d, 'build.json')
    json.dump(S, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    b = B.Build(sp)
    code = 3
    try:
        for st in ('trace', 'body', 'parts', 'merge'):
            code = b.run(only=st)
    except Exception as e:  # noqa: BLE001  기준선은 실패도 기록한다
        print('BASE2 ERROR', name, repr(e)[:300])
    obj = os.path.join(d, 'merged.obj')
    st = {k: v.get('초') for k, v in b.log.items() if isinstance(v, dict) and '초' in v}
    extra = {'끝_코드': code, '비용': {'단계_초': st, 'LLM_호출': 0, '사람_개입': 0, '좌표_입력': 0}}
    if not os.path.exists(obj):
        row = {'시각': time.strftime('%Y-%m-%dT%H:%M:%S'), '과제': name, '기준선': '②하네스', '판정': 'ERROR', '메모': '합친 메시 없음'}
        with open(LEDGER, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return row
    return score(name, obj, '②하네스', extra)


if __name__ == '__main__':
    names = sys.argv[1:] or tasks()
    for n in names:
        r = run(n)
        print('V2', n, r.get('오류_주입'), '실루엣', r.get('실루엣'), '부피', r.get('부피'), '몸', r.get('몸_수'), r.get('판정', ''))
