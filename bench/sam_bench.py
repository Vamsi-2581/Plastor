# -*- coding: utf-8 -*-
r"""SAM 2.1(tiny, CPU) 대 우리 트레이싱 도구. 같은 합성 장면·같은 LLM 거친 다각형(bench/run.py)을 힌트로 쓴다.
채택 기준(돌리기 전에 정함, docs/수정_기록.md 31): 부위·뷰 항목마다 SAM 평균 ≥ 우리 + 0.02 이고 SAM 최저 ≥ 우리 최저 − 0.05.
통과 항목만 새 씨앗(80~91)에서 다시 확인. 힌트 A: 다각형 상자 + 안쪽 점. B: A + 상자 안 다른 부위의 안쪽 점(음성).
실행: python bench/sam_bench.py <씨앗 시작> <개수>
"""
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import run  # noqa: E402
from harness.trace import fill_poly  # noqa: E402
from harness.vendor import ndi  # noqa: E402

SAMPY = os.path.join(ROOT, '.venv_sam', 'Scripts', 'python.exe')
W = run.W


def inner_point(m):
    d = ndi.distance_transform_edt(m)
    y, x = np.unravel_index(np.argmax(d), d.shape)
    return [float(x) + 0.5, float(y) + 0.5]


def main(s0, n):
    out = os.path.join(run.OUT, 'sam')
    os.makedirs(out, exist_ok=True)
    rows = []
    for seed in range(s0, s0 + n):
        ours = run.scene_case(seed)
        img, truth, pal, meta = run.cached_render(seed)
        rough = json.load(open(os.path.join(run.OUT, 's%02d' % seed, 'rough.json'), encoding='utf-8'))
        prompts, owner = [], {}
        for v, off in (('front', 0), ('side', W)):
            polys = [(it['name'], fill_poly(img.shape[:2], q['pts'])) for it in rough['panels'][v]['parts'] for q in it['polys']]
            for i, (name, m) in enumerate(polys):
                if m.sum() < 10:
                    continue
                ys, xs = np.nonzero(m)
                box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
                pos = inner_point(m)
                neg = []
                for j, (n2, m2) in enumerate(polys):
                    if j != i and n2 != name and m2.sum() >= 10:
                        q = inner_point(m2 & ~m) if (m2 & ~m).any() else None
                        if q and box[0] <= q[0] <= box[2] and box[1] <= q[1] <= box[3]:
                            neg.append(q)
                for arm, p in (('A', {'box': box, 'pos': [pos]}), ('B', {'box': box, 'pos': [pos], 'neg': neg})):
                    pid = '%s|%s|%d|%s' % (v, name, i, arm)
                    prompts.append(dict(p, id=pid))
                    owner[pid] = (v, name, arm, off)
        d = os.path.join(out, 's%02d' % seed)
        os.makedirs(d, exist_ok=True)
        np.savez(os.path.join(d, 'in.npz'), image=img)
        json.dump(prompts, open(os.path.join(d, 'prompts.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        r = subprocess.run([SAMPY, os.path.join(ROOT, 'tools', 'sam_worker.py'), os.path.join(d, 'in.npz'), os.path.join(d, 'prompts.json'),
                            os.path.join(d, 'out.npz')], capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode:
            print('SAM 오류', r.stderr[-600:])
            return 3
        Z = np.load(os.path.join(d, 'out.npz'))
        M = {}
        for pid, (v, name, arm, off) in owner.items():
            m = Z[pid].copy()
            pan = np.zeros_like(m)
            pan[:, off:off + W] = True                       # 그 뷰 패널 안으로만
            key = (arm, v, '뿔+밑동' if name in ('뿔', '뿔 밑동') else name)
            M[key] = M.get(key, np.zeros_like(m)) | (m & pan)
        row = {}
        for v in ('front', 'side'):
            g = lambda p: truth.get((v, p), np.zeros(img.shape[:2], bool))  # noqa: E731
            T = {'뿔+밑동': g('뿔') | g('뿔 밑동'), '귀': g('귀'), '머리': g('머리'), '갈기': g('갈기')}
            for k, t in T.items():
                if not t.any() or k not in ours[v]:
                    continue
                rec = {'우리': ours[v][k][1]}
                for arm in 'AB':
                    m = M.get((arm, v, k), np.zeros_like(t))
                    rec['SAM' + arm] = float((m & t).sum() / max((m | t).sum(), 1))
                row['%s|%s' % (v, k)] = rec
        rows.append(row)
        print('SAMB s%02d' % seed, ' '.join('%s 우리 %.2f A %.2f B %.2f' % (k, x['우리'], x['SAMA'], x['SAMB']) for k, x in row.items()), flush=True)
    keys = sorted({k for r in rows for k in r})
    summ = {}
    for k in keys:
        xs = [r[k] for r in rows if k in r]
        summ[k] = {a: (round(float(np.mean([x[a] for x in xs])), 3), round(float(np.min([x[a] for x in xs])), 3)) for a in ('우리', 'SAMA', 'SAMB')}
        u = summ[k]['우리']
        verdict = {a: (summ[k][a][0] >= u[0] + 0.02 and summ[k][a][1] >= u[1] - 0.05) for a in ('SAMA', 'SAMB')}
        print('SAMB 요약 %-12s 우리 %.3f(%.2f) A %.3f(%.2f) B %.3f(%.2f) 채택후보 %s' % (k, u[0], u[1], *summ[k]['SAMA'], *summ[k]['SAMB'], [a for a, ok in verdict.items() if ok] or '없음'))
    json.dump({'장면': rows, '요약': summ}, open(os.path.join(ROOT, 'bench', 'results', 'sam_%d_%d.json' % (s0, n)), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main(int(sys.argv[1]), int(sys.argv[2])))
