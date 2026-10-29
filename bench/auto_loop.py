# -*- coding: utf-8 -*-
"""스스로 판단하는 조건부 분기 루프(사용자 "스스로 판단하는 조건부 기반 분기 루프를 짜서 돌리는 게").

판단은 미리 적은 기준과 측정한 숫자로만 한다. LLM 은 루프 안에 없다(크레딧을 쓰지 않음).
LLM 이 필요한 자리(모든 후보가 떨어짐, 원인 모름)에 오면 멈추고 bench/loop/판단_필요.md 를 남긴다.

계획 파일 bench/loop/plan.json:
  {"항목": [{"id", "가설", "반증", "후보": [{"이름", "설정"}], "기준": {"부피_차": 0.05, "실루엣_차": -0.01}, "개발": [과제], "확인": [과제]}]}
  설정 = bench/m0.py harness 의 덮어쓰기({'body': ..., 'parts': ..., 'merge': ...}).

분기(항목마다, 위에서부터):
  1. 기준선이 없으면 개발·확인 과제에서 기준선(덮어쓰기 없음)을 한 번 잰다.
  2. 후보를 개발 과제에서 잰다. ERROR 가 섞이면 한 번 다시, 또 ERROR 면 그 후보는 ERROR.
  3. 개발 PASS(평균 부피 ≥ 기준선 + 부피_차 그리고 정면·옆 평균 실루엣 ≥ 기준선 + 실루엣_차) → 확인 과제에서 같은 기준.
     확인 PASS → 항목 '채택 후보'(기본값 바꾸기는 LLM 이 회귀 시험과 함께), 다음 항목.
     확인 FAIL → '개발에만 맞음' 기록, 다음 후보.
  4. 개발 FAIL:
     - 부피가 기준선보다 줄었고 후보에 '계열'이 있으면 → 같은 계열 나머지 후보를 건너뛴다(방향이 틀림).
     - 부피는 올랐는데 실루엣만 떨어졌으면 → '실루엣 보호' 표시가 있는 후보를 앞으로 당긴다.
     - 그 밖 → 다음 후보.
  5. 후보가 다 떨어짐 → 항목 '보류', 판단_필요.md 에 숫자와 다음 단서 질문을 쓰고 루프를 멈춘다(조사는 LLM 몫).
멈춤: bench/loop/STOP 파일이 있거나, --hours 시간이 지남. 상태는 bench/loop/state.json(다시 켜면 이어서).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import m0  # noqa: E402

LOOP = os.path.join(HERE, 'loop')
STATE = os.path.join(LOOP, 'state.json')


def load(p, default):
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else default


def save(o, p):
    json.dump(o, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def log(st, msg):
    line = '%s %s' % (time.strftime('%H:%M:%S'), msg)
    print('LOOP', line, flush=True)
    st.setdefault('기록', []).append(line)
    save(st, STATE)


def summary(rows):
    """채점 줄 → 평균 부피·실루엣. ERROR 가 있으면 None."""
    if any(r.get('판정') == 'ERROR' for r in rows):
        return None
    vol = [r['부피'] for r in rows if isinstance(r.get('부피'), float)]
    sil = [x for r in rows for x in r['실루엣'].values()]
    return {'부피': round(sum(vol) / max(len(vol), 1), 4), '실루엣': round(sum(sil) / max(len(sil), 1), 4),
            '몸_수': round(sum(r.get('몸_수') or 0 for r in rows) / max(len(rows), 1), 2), '과제별': {r['과제']: [r.get('부피'), r['실루엣']] for r in rows}}


def measure(st, key, tasks, over, sub):
    """같은 (설정, 과제) 는 다시 재지 않는다(상태에 저장)."""
    cache = st.setdefault('측정', {})
    if key in cache:
        return cache[key]
    for attempt in (1, 2):
        rows = m0.harness(tasks, label='루프:' + key.split('|')[0], over=over, sub=sub)
        s = summary(rows)
        if s is not None:
            break
        log(st, '%s ERROR (%d번째), %s' % (key, attempt, '다시' if attempt == 1 else '포기'))
    cache[key] = s
    save(st, STATE)
    return s


def passes(c, b, crit):
    return c['부피'] >= b['부피'] + crit['부피_차'] and c['실루엣'] >= b['실루엣'] + crit['실루엣_차']


def run(hours):
    os.makedirs(LOOP, exist_ok=True)
    plan = load(os.path.join(LOOP, 'plan.json'), {'항목': []})
    st = load(STATE, {})
    t_end = time.time() + hours * 3600
    for it in plan['항목']:
        res = st.setdefault('항목', {}).setdefault(it['id'], {'상태': '대기', '후보': {}})
        if res['상태'] in ('채택 후보', '보류'):
            continue
        res['상태'] = '진행'
        crit = it['기준']
        base_dev = measure(st, '기준선|개발|' + it['id'], it['개발'], {}, 'loop_base')
        base_cf = None
        if base_dev is None:
            res['상태'] = '보류'
            log(st, '%s 기준선 ERROR → 보류' % it['id'])
            continue
        log(st, '%s 기준선 개발 부피 %.4f 실루엣 %.4f' % (it['id'], base_dev['부피'], base_dev['실루엣']))
        queue = list(it['후보'])
        skip_family = set()
        while queue:
            if os.path.exists(os.path.join(LOOP, 'STOP')) or time.time() > t_end:
                log(st, '멈춤(STOP 파일 또는 시간)')
                return 2
            cand = queue.pop(0)
            name = cand['이름']
            if name in res['후보'] and res['후보'][name].get('판정'):
                continue
            if cand.get('계열') in skip_family:
                res['후보'][name] = {'판정': '건너뜀', '이유': '같은 계열이 부피를 줄임'}
                log(st, '%s 건너뜀(계열 %s)' % (name, cand.get('계열')))
                continue
            c = measure(st, '%s|개발|%s' % (name, it['id']), it['개발'], cand['설정'], 'loop_' + name)
            if c is None:
                res['후보'][name] = {'판정': 'ERROR'}
                continue
            dv, ds = c['부피'] - base_dev['부피'], c['실루엣'] - base_dev['실루엣']
            log(st, '%s 개발 부피 %.4f(%+.4f) 실루엣 %.4f(%+.4f) 몸 %.1f' % (name, c['부피'], dv, c['실루엣'], ds, c['몸_수']))
            if passes(c, base_dev, crit):
                if base_cf is None:
                    base_cf = measure(st, '기준선|확인|' + it['id'], it['확인'], {}, 'loop_base')
                cc = measure(st, '%s|확인|%s' % (name, it['id']), it['확인'], cand['설정'], 'loop_' + name)
                ok = cc is not None and base_cf is not None and passes(cc, base_cf, crit)
                res['후보'][name] = {'판정': 'PASS' if ok else 'FAIL', '개발': c, '확인': cc, '확인_기준선': base_cf}
                if ok:
                    res['상태'] = '채택 후보'
                    res['채택'] = name
                    log(st, '%s 확인 PASS 부피 %.4f(기준 %.4f) 실루엣 %.4f(기준 %.4f) → 채택 후보' % (name, cc['부피'], base_cf['부피'], cc['실루엣'], base_cf['실루엣']))
                    break
                log(st, '%s 확인 FAIL(개발에만 맞음)' % name)
                continue
            res['후보'][name] = {'판정': 'FAIL', '개발': c}
            if dv < 0 and cand.get('계열'):
                skip_family.add(cand['계열'])
            elif dv >= crit['부피_차'] and ds < crit['실루엣_차']:
                prot = [q for q in queue if q.get('실루엣_보호')]
                queue = prot + [q for q in queue if not q.get('실루엣_보호')]
                if prot:
                    log(st, '부피는 올랐고 실루엣만 떨어짐 → 실루엣 보호 후보 %s 먼저' % [q['이름'] for q in prot])
        if res['상태'] == '진행':
            res['상태'] = '보류'
            q = ['# 판단 필요: %s' % it['id'], '', '가설: ' + it['가설'], '반증: ' + it['반증'], '',
                 '기준선(개발): 부피 %.4f 실루엣 %.4f' % (base_dev['부피'], base_dev['실루엣']), '']
            for n, r in res['후보'].items():
                d = r.get('개발') or {}
                q.append('- %s: %s, 개발 부피 %s 실루엣 %s' % (n, r.get('판정'), d.get('부피'), d.get('실루엣')))
            q += ['', '모든 후보가 기준을 못 넘었다. 다음 중 무엇을 할지 LLM 이 정한다: 원인 진단(과제별 숫자), 조사(웹 3번까지), 새 후보, 기준 재검토(사용자 승인 필요).']
            open(os.path.join(LOOP, '판단_필요.md'), 'w', encoding='utf-8').write('\n'.join(q) + '\n')
            log(st, '%s 보류 → 판단_필요.md, 루프 멈춤' % it['id'])
            save(st, STATE)
            return 1
        save(st, STATE)
    log(st, '계획 끝')
    return 0


if __name__ == '__main__':
    h = float(sys.argv[sys.argv.index('--hours') + 1]) if '--hours' in sys.argv else 4.0
    sys.exit(run(h))
