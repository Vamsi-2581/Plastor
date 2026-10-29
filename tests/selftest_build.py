# -*- coding: utf-8 -*-
"""한 명령 파이프라인(build.py) 처음부터 끝까지 시험. 정답 마스크를 아는 합성 장면(bench/scene.py)에서
본체·부위 헐 → 합치기 → 3D 검사 → 각도 그림 → 카드까지 돌린다(Blender 헤드리스 호출, 약 30초).
예측(돌리기 전에 정함): 부위 박기를 켜면 합친 메시가 한 덩어리, 끄면 떠 있는 부위가 생긴다. 부위 재투영 IoU ≥ 0.90.
실행: python tests/selftest_build.py (끝 코드 0 = PASS)"""
import json
import os
import shutil
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'bench'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import build as B  # noqa: E402
import run as bench  # noqa: E402

RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def make_case(d, embed, split=False):
    img, truth, pal, meta = bench.cached_render(68)
    os.makedirs(d, exist_ok=True)
    M = {}
    for (v, p), m in truth.items():
        q = '뿔' if p == '뿔 밑동' and not split else p
        M[(v, q)] = M.get((v, q), np.zeros_like(m)) | m
    np.savez_compressed(os.path.join(d, 'masks.npz'), **{'%s|%s' % k: m for k, m in M.items()})
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    S = {'out': 'out', 'frame': {'meta': 'meta.json'}, 'trace': {'masks': 'masks.npz'},
         'body': {'part': '머리', 'method': 'hull', 'smooth': 1.5},
         'parts': [{'name': '뿔', 'embed_px': embed}, {'name': '귀', 'embed_px': embed}] + ([{'name': '뿔 밑동', 'embed_px': embed}] if split else []),
         'merge': {'ratio': 0.2}}
    sp = os.path.join(d, 'build.json')
    json.dump(S, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return sp, M


def main():
    base = os.path.join(ROOT, 'bench', 'out', 'build_test')
    shutil.rmtree(base, ignore_errors=True)
    sp_on, M = make_case(os.path.join(base, 'embed'), 8)
    sp_off, _ = make_case(os.path.join(base, 'noembed'), 0)
    b_on, b_off = B.Build(sp_on), B.Build(sp_off)
    code_on = b_on.run()
    b_off.run(only='trace'); b_off.run(only='body'); b_off.run(only='parts'); b_off.run(only='merge')
    L_on, L_off = b_on.log, b_off.log
    ok('파이프라인: 모든 단계가 돌고 ERROR 없음', all(L_on[s]['판정'] != 'ERROR' for s in B.STEPS), str({s: L_on[s]['판정'] for s in B.STEPS}))
    m_on, m_off = L_on['merge']['정보']['검사']['몸_수'], L_off['merge']['정보']['검사']['몸_수']
    ok('부위 박기: 켜면 한 덩어리, 끄면 떠 있는 부위가 생긴다', m_on == 1 and m_off > 1, '켬 %d / 끔 %d' % (m_on, m_off))
    chk = L_on['check']['정보']
    ious = {p: r['IoU'] for p, r in chk.items() if r['IoU']}
    ok('재투영: 부위마다 정면·옆 IoU ≥ 0.90', all(x >= 0.90 for r in ious.values() for x in r.values()), str(ious))
    ok('각도 그림: 5장 생김', all(L_on['views']['정보']['그림'].values()), str(len(L_on['views']['정보']['그림'])))
    ok('카드: card.md 생김', os.path.exists(os.path.join(base, 'embed', 'out', 'card.md')))
    # 합치기 구멍 메우기: 줄이기 비율 0.5 는 이 장면에서 열린 변 8 이 남던 경우(수정_기록 37)
    import subprocess
    o = os.path.join(base, 'embed', 'out')
    r = subprocess.run([B.BLENDER, '-b', '-P', os.path.join(ROOT, 'harness', 'blender_merge.py'), '--', os.path.join(o, 'm05.obj'), '0.5',
                        os.path.join(o, 'body.obj'), os.path.join(o, 'part_뿔.obj'), os.path.join(o, 'part_귀.obj')], capture_output=True, text=True, encoding='utf-8', errors='replace')
    line = [ln for ln in r.stdout.splitlines() if ln.startswith('MERGE 합친')]
    ok('합치기: 줄이기 비율 0.5 에서도 열린 변 0', line and '열린변 0 ' in line[-1], line[-1] if line else r.stderr[-200:])
    again = B.Build(sp_on)
    again.run(only='parts')
    ok('입력 지문: 같은 입력으로 다시 돌리면 같은 지문', again.log['parts']['이전과_같은_입력'])
    # 하위 부위(뿔 밑동)를 따로 합쳐도 본체가 남는다: 불리언이 본체를 통째로 지운 적이 있다(M0 합성 6종, 수정_기록 44)
    sp_split, _ = make_case(os.path.join(base, 'split'), 8, split=True)
    bs = B.Build(sp_split)
    for st in ('trace', 'body', 'parts', 'merge'):
        bs.run(only=st)
    ml = bs.log['merge']['정보']['합치기']
    vols = [float(ln.split('→')[-1]) for ln in ml if ln.startswith('MERGE 부피')]
    ok('합치기: 하위 부위를 따로 합쳐도 부피를 잃지 않음', vols and not any(ln.startswith('MERGE 실패') for ln in ml) and vols == sorted(vols),
       ' '.join('%.4f' % x for x in vols))
    # 숨은 입력 없음: 둥근 본체를 앞 실행이 남긴 body.obj 와 상관없이 같게 만든다(M0 새 머리 재현성 FAIL, 수정_기록 45)
    import hashlib
    rd = os.path.join(base, 'round')
    sp_r, _ = make_case(rd, 8)
    S = json.load(open(sp_r, encoding='utf-8'))
    S['body'] = {'part': '머리', 'method': 'round', 'cesn': 5}
    json.dump(S, open(sp_r, 'w', encoding='utf-8'), ensure_ascii=False)
    hs = []
    for shift in (None, 0.3):
        if shift is not None:                       # 엉뚱한 자리의 body.obj 를 미리 둔다
            from harness.model_check import load_obj
            V, F = load_obj(os.path.join(rd, 'out', 'body.obj'))
            B.write_obj(os.path.join(rd, 'out', 'body.obj'), V + shift, F)
        br = B.Build(sp_r)
        br.run(only='trace')
        br.run(only='body')
        hs.append(hashlib.sha1(open(os.path.join(rd, 'out', 'body.obj'), 'rb').read()).hexdigest()[:10])
    ok('재현성: 미리 있던 body.obj 가 둥근 본체를 바꾸지 않음', hs[0] == hs[1], str(hs))
    bad = RESULTS.count(False)
    print('\n파이프라인 자체 시험 %s: %d개 중 %d개 통과 (build 끝 코드 %d)' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad, code_on))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
