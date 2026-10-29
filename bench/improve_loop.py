# -*- coding: utf-8 -*-
r"""트레이싱 하네스 개선 루프(벤치마크 단계): 설정 후보를 하나씩 바꿔 보고, 과적합을 막는 세 장면 묶음으로 채택한다.

  개발(dev)  : 후보마다 점수를 낸다. 가장 좋은 후보부터 검증으로 보낸다.
  검증(val)  : 채택 조건 = 평균 점수 +0.002 이상, 그리고 어느 항목의 최저 IoU 도 0.02 넘게 떨어지지 않는다(크게 무너지는 설정 금지).
  시험(test) : 루프가 한 번도 보지 않은 장면. 마지막에 처음 설정과 최종 설정만 잰다. 이 숫자만 보고에 쓴다.
점수 = 항목(뷰|부위)별 IoU 평균의 평균. 항목: 뿔+밑동, 귀, 머리, 갈기(있는 장면만).
후보(한 걸음에 하나만 바꿈): snap_px, min_area, claim_frac, tone_cut, mirror_mode, k(군집 수 +3), 부위별 알고리즘(ours|grabcut|watershed).
실행: python bench/improve_loop.py [--rounds 4] [--dev 40 8] [--val 48 8] [--test 56 12]
기록: bench/out/improve_loop.jsonl (걸음마다 후보·점수·채택 여부), bench/results/improve_loop_summary.json
"""
import copy
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import run  # noqa: E402

MIN_GAIN = 0.002
MAX_MIN_DROP = 0.02


def evaluate(cfg, seeds):
    items = {}
    for s in seeds:
        extra = {k: v for k, v in cfg.items() if k != 'k_add'}
        sc = run.scene_case(s, extra=extra)
        for v, d in sc.items():
            for k, (a, b) in d.items():
                items.setdefault('%s|%s' % (v, k), []).append(b)
    summ = {k: (float(np.mean(x)), float(np.min(x))) for k, x in items.items()}
    score = float(np.mean([m for m, _ in summ.values()]))
    return score, summ


def candidates(cfg):
    out = []
    def put(desc, **chg):
        c = copy.deepcopy(cfg)
        c.update(chg)
        if c != cfg:
            out.append((desc, c))
    for v in (5, 12):
        put('snap_px=%d' % v, snap_px=v)
    for v in (20, 80):
        put('min_area=%d' % v, min_area=v)
    for v in (0.5, 0.8):
        put('claim_frac=%.1f' % v, claim_frac=v)
    put('tone_cut=%s' % (not cfg.get('tone_cut', True)), tone_cut=not cfg.get('tone_cut', True))
    put('mirror_mode=%s' % ('left' if cfg.get('mirror_mode', 'union') == 'union' else 'union'),
        mirror_mode='left' if cfg.get('mirror_mode', 'union') == 'union' else 'union')
    for part in ('머리', '갈기', '귀', '뿔', '뿔 밑동'):
        cur = cfg.get('method_by_part', {}).get(part, 'ours')
        for alg in ('ours', 'grabcut', 'watershed'):
            if alg == cur:
                continue
            mbp = dict(cfg.get('method_by_part', {}))
            if alg == 'ours':
                mbp.pop(part, None)
            else:
                mbp[part] = alg
            put('%s=%s' % (part, alg), method_by_part=mbp)
    return out


def seeds_of(argv, name, s0, n):
    if name in argv:
        i = argv.index(name)
        s0, n = int(argv[i + 1]), int(argv[i + 2])
    return list(range(s0, s0 + n))


def main(argv):
    rounds = int(argv[argv.index('--rounds') + 1]) if '--rounds' in argv else 4
    dev, val, test = seeds_of(argv, '--dev', 40, 8), seeds_of(argv, '--val', 48, 8), seeds_of(argv, '--test', 56, 12)
    cfg0 = {'mirror_mode': 'union', 'tone_cut': True, 'snap_px': 8, 'min_area': 40, 'claim_frac': 0.6}
    cfg = copy.deepcopy(cfg0)
    log = open(os.path.join(run.OUT, 'improve_loop.jsonl'), 'w', encoding='utf-8')
    t0 = time.time()
    dev_s, _ = evaluate(cfg, dev)
    val_s, val_summ = evaluate(cfg, val)
    print('LOOP 시작 dev %.4f val %.4f (%.0fs)' % (dev_s, val_s, time.time() - t0))
    log.write(json.dumps({'걸음': 0, '설정': cfg, 'dev': dev_s, 'val': val_s}, ensure_ascii=False) + '\n'); log.flush()
    history = []
    for r in range(1, rounds + 1):
        scored = []
        for desc, c in candidates(cfg):
            s, _ = evaluate(c, dev)
            scored.append((s, desc, c))
            log.write(json.dumps({'걸음': r, '후보': desc, 'dev': s}, ensure_ascii=False) + '\n'); log.flush()
        scored.sort(key=lambda x: -x[0])
        print('LOOP 걸음 %d 후보 %d개, dev 상위: %s' % (r, len(scored), ', '.join('%s %.4f' % (d, s) for s, d, _ in scored[:4])))
        accepted = None
        for s, desc, c in scored[:3]:
            if s < dev_s + MIN_GAIN:
                break
            vs, vsumm = evaluate(c, val)
            drops = {k: round(val_summ[k][1] - vsumm.get(k, (0, 0))[1], 3) for k in val_summ}
            worst = max(drops.values())
            ok = vs >= val_s + MIN_GAIN and worst <= MAX_MIN_DROP
            log.write(json.dumps({'걸음': r, '검증': desc, 'dev': s, 'val': vs, '최저_하락_최대': worst, '채택': ok}, ensure_ascii=False) + '\n'); log.flush()
            print('LOOP   검증 %s: val %.4f → %.4f, 최저 하락 최대 %.3f → %s' % (desc, val_s, vs, worst, '채택' if ok else '기각'))
            if ok:
                accepted = (desc, c, s, vs, vsumm)
                break
        if accepted is None:
            print('LOOP 걸음 %d: 채택할 후보 없음 → 멈춤' % r)
            break
        desc, cfg, dev_s, val_s, val_summ = accepted
        history.append(desc)
    t_base, tb = evaluate(cfg0, test)
    t_fin, tf = evaluate(cfg, test)
    print('LOOP 시험(처음 보는 장면 %d장): 처음 %.4f → 최종 %.4f' % (len(test), t_base, t_fin))
    for k in sorted(tf):
        print('LOOP   %-12s 평균 %.3f → %.3f, 최저 %.3f → %.3f' % (k, tb[k][0], tf[k][0], tb[k][1], tf[k][1]))
    summary = {'처음_설정': cfg0, '최종_설정': cfg, '채택_순서': history, '시험': {'처음': t_base, '최종': t_fin,
               '항목': {k: {'처음': tb[k], '최종': tf[k]} for k in tf}}, '씨앗': {'dev': dev, 'val': val, 'test': test},
               '초': round(time.time() - t0)}
    json.dump(summary, open(os.path.join(os.path.dirname(run.OUT), 'results', 'improve_loop_summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log.close()


if __name__ == '__main__':
    main(sys.argv[1:])
