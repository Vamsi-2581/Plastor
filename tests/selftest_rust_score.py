# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-032
"""Rust 첫 걸음 대조(docs/설계_러스트.md 7.1, 기준은 돌리기 전에 적음).
  PNG: Rust 가 쓴 PNG 를 Blender 가 읽은 화소가 원래 배열과 칸 단위로 같음(그림 3장).
  채점기: M0 장부의 'K1 재채점' 10줄과 실루엣 ≤ 0.002, 부피 ≤ 0.005, 부위 실루엣·부피 ≤ 0.005, 3/4 폭 비 ≤ 0.01,
          거칠기 ≤ 0.5°, 랜드마크 ≤ 0.005H, 몸 수 같음. 합성 정답은 파이썬이 만든 도형을 prims.json 으로 한 번 내보내 쓴다.
실행: python tests/selftest_rust_score.py (끝 코드 0 = PASS). 먼저 cd rust && cargo build --release"""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'bench'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
MH = os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
BLENDER = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def mh(tool, args):
    r = subprocess.run([MH, tool, json.dumps(args, ensure_ascii=False)], capture_output=True, text=True, encoding='utf-8')
    return json.loads(r.stdout)


def export_task(t, d):
    """합성 과제의 정답 도형(prims.json)과 목 포함 전체 정답 마스크(truth_all.npz)를 한 번 내보낸다(파이썬 정답 그대로)."""
    import m0
    import run
    seed, opt = m0.SYNTH_ALL[t]
    P = m0._prims(seed, opt)
    json.dump([{'c': list(map(float, p['c'])), 'r': list(map(float, p['r'])), 'part': p['part']} for p in P],
              open(os.path.join(d, 'prims.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    _, truth, _, _ = run.cached_render(seed, opt.get('hard', False), opt.get('outline', False), False,
                                       bool(opt.get('hue') or opt.get('twotone')), opt.get('twotone', False), opt.get('checker', False))
    np.savez(os.path.join(d, 'truth_all.npz'), **{'%s|%s' % k: m for k, m in truth.items()})


def close(a, b, tol):
    if isinstance(a, str) or isinstance(b, str) or a is None or b is None:
        return a == b
    return abs(a - b) <= tol


def main():
    tmp = tempfile.mkdtemp()
    # 1. PNG
    imgs = [np.load(os.path.join(ROOT, 'bench/m0/synth_basic/drawing.npy')),
            np.load(os.path.join(ROOT, 'bench/m0/synth_checker/drawing.npy')),
            (np.random.default_rng(0).integers(0, 256, (97, 131, 3))).astype(np.uint8)]
    same = []
    for i, a in enumerate(imgs):
        n, p, back = [os.path.join(tmp, 'p%d%s' % (i, e)) for e in ('.npy', '.png', '_back.npy')]
        np.save(n, np.ascontiguousarray(a[:, :, :3], np.uint8))
        mh('png', {'npy': n, 'out': p})
        subprocess.run([BLENDER, '-b', '-P', os.path.join(ROOT, 'harness', 'blender_readimg.py'), '--', p, back], capture_output=True)
        b = np.load(back) if os.path.exists(back) else None
        same.append(b is not None and b.shape == a[:, :, :3].shape and bool((b == a[:, :, :3]).all()))
    ok('PNG: Blender 가 읽은 화소가 원래와 같음(3장)', all(same), str(same))
    # 2. 채점기 대조
    rows = [json.loads(x) for x in open(os.path.join(ROOT, 'bench/m0/ledger.jsonl'), encoding='utf-8')]
    ref = {}
    for r in rows:
        if r.get('메모') == '칸 0.5px 재채점':   # 칸 0.5px(수정_기록 49) 뒤 기준값
            ref[(r['과제'], r['기준선'])] = r
    PARTS = ['머리', '뿔', '뿔 밑동', '귀', '갈기']
    bad_detail = []
    for (t, b), r in sorted(ref.items()):
        d = os.path.join(ROOT, 'bench/m0', t)
        task = json.load(open(os.path.join(d, 'task.json'), encoding='utf-8'))
        if task['종류'] == '합성':
            if not os.path.exists(os.path.join(d, 'prims.json')):
                export_task(t, d)
            args = {'frame': os.path.join(d, 'meta.json'), 'obj': os.path.join(ROOT, r['OBJ']), 'truth': os.path.join(d, 'truth_all.npz'),
                    'prims': os.path.join(d, 'prims.json'), 'ref_parts': PARTS}
        else:
            fr = task['틀']
            args = {'frame': os.path.join(ROOT, fr.get('pack') or fr.get('meta')), 'obj': os.path.join(ROOT, r['OBJ']),
                    'truth': os.path.join(ROOT, task['트레이스'])}
        z = mh('score', args)['요약']
        diffs = []
        for v in ('front', 'side'):
            if not close(z['실루엣'].get(v), r['실루엣'].get(v), 0.002):
                diffs.append('실루엣 %s %s/%s' % (v, z['실루엣'].get(v), r['실루엣'].get(v)))
        if not close(z['부피'], r['부피'], 0.005):
            diffs.append('부피 %s/%s' % (z['부피'], r['부피']))
        if z['몸_수'] != r['몸_수']:
            diffs.append('몸 수 %s/%s' % (z['몸_수'], r['몸_수']))
        if not close(z['거칠기'], r['거칠기'], 0.5):
            diffs.append('거칠기 %s/%s' % (z['거칠기'], r['거칠기']))
        if not close(z['3/4폭비'], r['3/4폭비'], 0.01):
            diffs.append('3/4 %s/%s' % (z['3/4폭비'], r['3/4폭비']))
        if isinstance(r.get('부위'), dict):
            for g, e in r['부위'].items():
                ze = z['부위'].get(g, {}) if isinstance(z.get('부위'), dict) else {}
                for v, x in e['실루엣'].items():
                    if not close(ze.get('실루엣', {}).get(v), x, 0.005):
                        diffs.append('%s 실루엣 %s %s/%s' % (g, v, ze.get('실루엣', {}).get(v), x))
                if '부피' in e and not close(ze.get('부피'), e['부피'], 0.005):
                    diffs.append('%s 부피 %s/%s' % (g, ze.get('부피'), e['부피']))
                if not close(ze.get('3/4폭비'), e.get('3/4폭비'), 0.01):
                    diffs.append('%s 3/4 %s/%s' % (g, ze.get('3/4폭비'), e.get('3/4폭비')))
            for k, x in r.get('랜드마크_잔차', {}).items():
                if not close(z.get('랜드마크_잔차', {}).get(k), x, 0.005):
                    diffs.append('랜드마크 %s %s/%s' % (k, z.get('랜드마크_잔차', {}).get(k), x))
        elif r.get('부위') != z.get('부위'):
            diffs.append('부위 %s/%s' % (z.get('부위'), r.get('부위')))
        if diffs:
            bad_detail.append('%s %s: %s' % (t, b, '; '.join(diffs)))
    ok('채점기: M0 칸 0.5px 재채점 %d줄과 허용 차 안' % len(ref), not bad_detail, ' | '.join(bad_detail)[:1500])
    bad = RESULTS.count(False)
    print('\nRust 첫 걸음 대조 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
