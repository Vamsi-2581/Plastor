# -*- coding: utf-8 -*-
r"""실패 채굴: 장면 묶음을 돌려 '결과 IoU < 기준' 이거나 '도구가 거친 트레이스보다 나쁘게 만든' 항목을 모으고,
각각 오차 원인(재질 틀림·LLM 선 너무 멂·규칙이 뺌·다른 부위가 가져감·초과)을 자동으로 나눠 수리 목록을 만든다.
규칙을 고칠 곳은 사람(LLM)이 이 목록을 보고 정하고, 고친 뒤에는 고칠 때 안 본 새 씨앗으로 검증한다.
실행: python bench/mine_failures.py <씨앗 시작> <개수> [--thr 0.85] [--extra '{...}']
출력: bench/results/failures_<시작>_<개수>.json (항목별 원인, 원인별 합계 순위)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import run  # noqa: E402
from diagnose import diagnose  # noqa: E402

s0, n = int(sys.argv[1]), int(sys.argv[2])
thr = float(sys.argv[sys.argv.index('--thr') + 1]) if '--thr' in sys.argv else 0.85
extra = json.loads(sys.argv[sys.argv.index('--extra') + 1]) if '--extra' in sys.argv else {}
NAME = {'뿔+밑동': '뿔', '귀': '귀', '머리': '머리', '갈기': '갈기'}
fails, total = [], {}
for s in range(s0, s0 + n):
    sc = run.scene_case(s, extra=extra)
    for v, d in sc.items():
        for k, (a, b) in d.items():
            if b < thr or b < a - 0.01:
                rep = diagnose(s, v, NAME[k], extra=extra)
                causes = dict(rep['놓침'])
                causes['초과'] = sum(rep['초과'].values())
                fails.append({'씨앗': s, '뷰': v, '부위': k, '거친': round(a, 3), '결과': round(b, 3), '원인': causes})
                for c, x in causes.items():
                    total[c] = total.get(c, 0) + x
fails.sort(key=lambda f: f['결과'])
rank = sorted(total.items(), key=lambda kv: -kv[1])
out = {'기준': thr, '설정': extra, '실패': fails, '원인_합계_순위': rank}
json.dump(out, open(os.path.join(HERE, 'results', 'failures_%d_%d.json' % (s0, n)), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('MINE 실패 %d건 (기준 %.2f)' % (len(fails), thr))
for c, x in rank:
    print('MINE 원인 %-12s %d px' % (c, x))
for f in fails[:8]:
    print('MINE  s%d %s %s %.2f→%.2f 주원인 %s' % (f['씨앗'], f['뷰'], f['부위'], f['거친'], f['결과'], max(f['원인'], key=f['원인'].get)))
