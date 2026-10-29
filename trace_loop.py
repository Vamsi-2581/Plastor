# -*- coding: utf-8 -*-
r"""트레이싱 루프: 측정 → 진단 → 설정 한 가지 바꾸기 → 재측정. 좋아질 때만 받아들이고, 안 좋아지면 멈춘다.

왜 '그림을 보고 고치기'가 아닌가: VLM 에게 겹침 그림을 보여 주고 고치게 하면 오히려 나빠진다는 보고가 있다
(Iterative Visual Thinking, 2026: 79.6% → 48.7%). 그래서 루프는 도면 기하에서 나오는 독립 검사 숫자로 돈다.
이 숫자들은 경계 지도(스냅·G0 가 쓰는 것)와 무관해서, 트레이스가 자기 자신을 채점하는 순환이 없다.

독립 검사(부위마다)
  H  높이 일치: 정사영이면 한 부위의 위 끝·아래 끝 높이는 정면과 옆에서 같다. |차| ≤ 0.02H(3px) 이면 통과.
  LR 좌우 일치: 거울로 붙이기 전 정면 마스크의 왼쪽 절반과 오른쪽 절반(거울)이 같다. IoU ≥ 0.95 이면 통과.
  (정면·뒤 일치는 도면이 뒤를 다르게 그려 0.75~0.82 라 판정에 넣지 않고 보고만 한다)
바꿀 수 있는 것(행동)
  claim_off 켜기/끄기(노랑으로 자동 덧붙인 곳마다), snap_px(탐색 폭) 5·8·12,
  높이 맞추기: H 가 실패한 부위에서 범위가 짧은 뷰의 거친 다각형을 모자란 행만큼 부위 재질 쪽으로 넓힌다(rough_grow).
손실 = Σ 부위 [max(0, H차−3px)/3px + max(0, 0.95−LR)/0.02]. 한 걸음에 행동 하나, 손실이 가장 많이 줄어드는 것.
판정: 모든 부위 H·LR 통과면 PASS, 아니면 FAIL(남은 항목 보고). 루프가 못 고친 것은 사람 몫으로 남긴다.

실행: python trace_loop.py --spec fixtures/bison_head/trace/head_spec.json [--max-steps 8]
출력: <out>/loop.jsonl(걸음마다 전·후 검사), <out>/spec_loop.json(최종 설정), 최종 build 결과(마스크·윤곽표·그림)
"""
import copy
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import trace as T  # noqa: E402

H_TOL_PX = 3
LR_MIN = 0.95


def rows_of(m):
    r = np.flatnonzero(m.any(1))
    return (int(r.min()), int(r.max())) if len(r) else None


def checks(res):
    masks, raw, centers = res['masks'], res['raw'], res['centers']
    out = {}
    parts = sorted({k[1] for k in masks})
    for p in parts:
        c = {}
        f, s = masks.get(('front', p)), masks.get(('side', p))
        if f is not None and s is not None and f.any() and s.any():
            (ft, fb), (st, sb) = rows_of(f), rows_of(s)
            c['H_위끝차_px'] = abs(ft - st)
            c['H_아래끝차_px'] = abs(fb - sb)
            c['H_통과'] = max(c['H_위끝차_px'], c['H_아래끝차_px']) <= H_TOL_PX
        r = raw.get(('front', p))
        if r is not None and r.any():
            cx = centers['front']
            cols = np.arange(r.shape[1])
            mc = np.round(2 * cx - 1 - cols).astype(int)
            ok = (mc >= 0) & (mc < r.shape[1])
            mir = np.zeros_like(r)
            mir[:, mc[ok]] = r[:, cols[ok]]
            left = cols < cx
            a, b = r[:, left], mir[:, left]
            c['LR_IoU'] = round(float((a & b).sum() / max((a | b).sum(), 1)), 3)
            c['LR_통과'] = c['LR_IoU'] >= LR_MIN
        out[p] = c
    return out


def loss(ch, res=None):
    """독립 검사 벌점 + 번짐 벌점(LLM 선으로 자른 픽셀 수 / 200). 번짐 벌점이 없으면 높이를 맞추려고 같은 털로 이어진 갈기까지
    가져가는 변경을 받아들였다(들소 옆 뷰 가로 직사각형)."""
    L = 0.0
    if res is not None:
        oc = res['rep'].get('LLM선_컷(바깥도 같은 재질)', {})
        L += sum(v['LLM컷_픽셀'] for v in oc.values()) / 200.0
        L += sum(res['rep'].get('지어낸_경계_픽셀(주황, 사람 확인)', {}).values()) / 400.0    # 지어낸 경계도 조금 벌점
    for c in ch.values():
        if 'H_통과' in c:
            L += max(0, max(c['H_위끝차_px'], c['H_아래끝차_px']) - H_TOL_PX) / H_TOL_PX
        if 'LR_IoU' in c:
            L += max(0.0, LR_MIN - c['LR_IoU']) / 0.02
    return round(L, 3)


def actions(S, res):
    acts = []
    for k in res['added']:
        key = '%s|%s' % k
        if key not in S.get('claim_off', []):
            acts.append(('claim_off 켜기', key))
    for key in S.get('claim_off', []):
        acts.append(('claim_off 끄기', key))
    ch = checks(res)
    for p, c in ch.items():
        if c.get('H_통과') is False:
            f, s = rows_of(res['masks'][('front', p)]), rows_of(res['masks'][('side', p)])
            for (tv, own), other in ((('front', f), s), (('side', s), f)):
                for mode in ('엄격', '제안'):                           # 제안 = 도면 경계 없는 곳도 붙이되 주황으로 표시(사람 확인)
                    if other[0] < own[0] - H_TOL_PX:                   # 위 끝이 짧다
                        acts.append(('높이 맞추기', '%s|%s' % (tv, p), [other[0], own[0], mode]))
                    if other[1] > own[1] + H_TOL_PX:                   # 아래 끝이 짧다
                        acts.append(('높이 맞추기', '%s|%s' % (tv, p), [own[1], other[1], mode]))
    for d in (5, 8, 12):
        if d != S.get('snap_px', 8):
            acts.append(('snap_px', d))
    return acts


def apply(S, act):
    S2 = copy.deepcopy(S)
    kind, val = act[0], act[1]
    if kind == 'claim_off 켜기':
        S2['claim_off'] = sorted(set(S2.get('claim_off', [])) | {val})
    elif kind == 'claim_off 끄기':
        S2['claim_off'] = sorted(set(S2.get('claim_off', [])) - {val})
    elif kind == 'snap_px':
        S2['snap_px'] = val
    elif kind == '높이 맞추기':
        g = S2.setdefault('rough_grow', {})
        rngs = g.get(val, [])
        if rngs and not isinstance(rngs[0], list):
            rngs = [rngs]
        g[val] = rngs + [[int(act[2][0]), int(act[2][1])] + ([act[2][2]] if act[2][2] == '제안' else [])]   # 범위는 따로(위·아래를 합치면 높이 전체가 넓어졌다)
    return S2


def verdict(ch):
    bad = {p: c for p, c in ch.items() if c.get('H_통과') is False or c.get('LR_통과') is False}
    return ('PASS' if not bad else 'FAIL'), bad


def main(argv):
    spec_path = argv[argv.index('--spec') + 1]
    max_steps = int(argv[argv.index('--max-steps') + 1]) if '--max-steps' in argv else 8
    S = T.jload(spec_path)
    res = T.build(S, spec_path, write=False)
    ch = checks(res)
    L = loss(ch, res)
    out = res['out']
    log = open(os.path.join(out, 'loop.jsonl'), 'w', encoding='utf-8')
    log.write(json.dumps({'걸음': 0, '설정': {k: S.get(k) for k in ('claim_off', 'snap_px', 'rough_grow')}, '손실': L, '검사': ch}, ensure_ascii=False) + '\n')
    print('LOOP 시작 손실 %.3f' % L, verdict(ch)[0])
    for step in range(1, max_steps + 1):
        best = None
        for act in actions(S, res):
            S2 = apply(S, act)
            r2 = T.build(S2, spec_path, write=False)
            ch2 = checks(r2)
            L2 = loss(ch2, r2)
            if best is None or L2 < best[0]:
                best = (L2, act, S2, r2, ch2)
        if best is None or best[0] >= L:
            print('LOOP 걸음 %d: 손실을 줄이는 행동 없음 → 멈춤' % step)
            log.write(json.dumps({'걸음': step, '멈춤': '손실을 줄이는 행동 없음', '최선_후보': None if best is None else {'행동': list(best[1]), '손실': best[0]}}, ensure_ascii=False) + '\n')
            break
        L_prev, ch_prev = L, ch
        L, act, S, res, ch = best
        print('LOOP 걸음 %d: %s → 손실 %.3f → %.3f' % (step, ' '.join(map(str, act)), L_prev, L))
        log.write(json.dumps({'걸음': step, '행동': list(act), '전_손실': L_prev, '후_손실': L, '전_검사': ch_prev, '후_검사': ch}, ensure_ascii=False) + '\n')
    log.close()
    with open(os.path.join(out, 'spec_loop.json'), 'w', encoding='utf-8') as f:
        json.dump(S, f, ensure_ascii=False, indent=1)
    T.build(S, spec_path, write=True)
    v, bad = verdict(ch)
    print('LOOP 판정 %s 손실 %.3f 설정 claim_off=%s snap_px=%s rough_grow=%s' % (v, L, S.get('claim_off', []), S.get('snap_px', 8), S.get('rough_grow', {})))
    for p, c in ch.items():
        print('LOOP   %s %s' % (p, c))
    if bad:
        print('LOOP 남은 실패(사람 확인):', sorted(bad))
    return 0 if v == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
