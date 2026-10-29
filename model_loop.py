# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-017
r"""3D 모델링 루프: 만든 모델을 도면 뷰에 다시 비춰 재고(check), 지금 막힌 단계 하나의 카드만 낸다(next).
카드는 정 → 동 순서다: 그 단계의 고정 규칙(cards/*.md) → 관련 교훈(docs/교훈.jsonl 에서 진단·부위로 골라 최대 4개) → 지금 측정값(실패 항목만).
LLM 은 긴 맥락에서 중간 정보를 놓치고 비슷한 오답 정보에 흔들린다(맥락 부패 연구). 그래서 전체 문서 대신 막힌 단계에 필요한 것만 준다.
단계: 1 뷰 맞추기(그림 모순) → 2 큰 형태(본체) → 3 부위 형태(재투영·단면) → 4 합치기(떠 있는 조각) → 5 리깅 준비(검사기 없음, UNKNOWN).
앞 단계가 남아 있으면 뒤 단계 카드는 내지 않는다(큰 것부터, 모순부터).

실행(Blender 번들 python):
  python model_loop.py check --pack packs/head_traced/pack.json --masks fixtures/bison_head/trace/out/masks.npz \
         --part 머리=results/x/head_core_h.obj --part 뿔=results/x/hull_뿔_h.obj --body 머리 --merged results/x/최종.obj --out results/x
  python model_loop.py next --check results/x/model_check.json
  (그림 모순처럼 LLM 이 정할 항목은 같은 폴더 model_decisions.json 에 [{"부위","종류","결정","근거"}] 로 적는다)
판정: 단계 1~4 진단이 모두 없으면 PASS(단계 5 는 UNKNOWN 이라 전체는 UNKNOWN). 진단이 있으면 FAIL 과 그 단계 카드.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from harness.model_check import check, load_obj, merged_check  # noqa: E402
from harness.pack import Pack  # noqa: E402

CARDS = os.path.join(ROOT, 'cards')
LESSONS = os.path.join(ROOT, 'docs', '교훈.jsonl')
STAGE_FILES = {1: '1_뷰맞추기.md', 2: '2_큰형태.md', 3: '3_부위형태.md', 4: '4_합치기.md', 5: '5_리깅준비.md'}


def arg(argv, k, many=False):
    if many:
        return [argv[i + 1] for i, a in enumerate(argv) if a == k]
    return argv[argv.index(k) + 1] if k in argv else None


def stage_items(R, body):
    """진단을 단계로 나눈다. 반환 {단계: [(부위, 진단)]}."""
    st = {1: [], 2: [], 3: [], 4: []}
    for p, r in R['부위'].items():
        for d in r['진단']:
            if d['종류'] == '그림 모순':
                st[1].append((p, d))
            elif d['종류'] in ('떠 있는 조각', '합쳐지지 않음', '열린 메시'):
                st[4].append((p, d))
            elif p == body:
                st[2].append((p, d))
            else:
                st[3].append((p, d))
    return st


def lessons(stage, items, k=4):
    kinds = {d['종류'] for _, d in items}
    parts = {p for p, _ in items}
    L = [json.loads(x) for x in open(LESSONS, encoding='utf-8') if x.strip()]
    scored = []
    for e in L:
        if stage not in e['단계']:
            continue
        s = 2 * len(kinds & set(e['진단'])) + len(parts & set(e['부위'])) + (0.5 if not e['진단'] else 0)
        if s > 0:
            scored.append((s, e))
    scored.sort(key=lambda t: -t[0])
    return [e for _, e in scored[:k]]


QUERY_TERMS = {
    '상자 단면': 'visual hull cross-section prior round tube',
    '그림 모순': 'inconsistent multi-view drawings 3D reconstruction',
    '모델링 오차': 'silhouette fitting mesh optimization orthographic views',
    '떠 있는 조각': 'mesh boolean union disconnected components repair',
    '합쳐지지 않음': 'mesh boolean union disconnected components repair',
    '열린 메시': 'mesh hole filling watertight repair',
}


def read_history(folder):
    """결과 폴더의 check_history.jsonl 을 읽는다. 없으면 빈 목록."""
    p = os.path.join(folder, 'check_history.jsonl')
    if not os.path.exists(p):
        return []
    out = []
    for ln in open(p, encoding='utf-8'):
        if ln.strip():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def stuck(history, k=2):
    """최근 k 번의 기록 모두에 들어 있는 (부위, 종류) 목록(기록 순서 유지)."""
    if not history or len(history) < k:
        return []
    sets = [{tuple(x) for x in h['진단']} for h in history[-k:]]
    common = set.intersection(*sets)
    return [t for t in dict.fromkeys(tuple(x) for x in history[-1]['진단']) if t in common]


def _run_length(history, key):
    n = 0
    for h in reversed(history):
        if key in {tuple(x) for x in h['진단']}:
            n += 1
        else:
            break
    return n


def research_section(stage, items, history, k=2):
    """막힌 항목이 있으면 '## 막힘: 조사 단계' 절 줄 목록, 없으면 빈 목록."""
    st = set(stuck(history, k))
    hit = [(p, d['종류']) for p, d in items if (p, d['종류']) in st]
    hit = list(dict.fromkeys(hit))
    if not hit:
        return []
    out = ['', '## 막힘: 조사 단계', '같은 진단이 계속 반복된다. 같은 방법을 되풀이하지 말고 조사부터 한다.']
    for p, kind in hit:
        out.append('- 막힌 항목: %s / %s / %d번 연속' % (p, kind, _run_length(history, (p, kind))))
        if not lessons(stage, [(p, {'종류': kind})]):
            out.append('  - 관련 교훈 없음')
    out += ['', '할 일 순서: 웹 검색 최대 3번(논문·기존 도구 먼저) → 반증 조건이 있는 가설 하나 → 사양 바꾸기 또는 decide 로 기록 → 다시 build', '',
            '검색어 제안:']
    qs = []
    for p, kind in hit:
        base = QUERY_TERMS.get(kind, 'mesh reconstruction from orthographic drawings')
        qs.append('%s %s' % (base, p))
        qs.append('%s (%s) 3D modeling' % (base, p))
    for q in list(dict.fromkeys(qs))[:2]:
        out.append('- ' + q)
    return out


def read_rig(out):
    """결과 폴더의 rig_check.json(단계 5 검사 결과). 없으면 None."""
    p = os.path.join(out, 'rig_check.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None


def card(R, body, decided=(), history=None, rig=None):
    """decided: [{'부위','종류','결정','근거'}] LLM 이 결정한 그림 모순 등. 결정된 항목은 막지 않고 '결정됨'으로만 보인다.
    history: check_history.jsonl 기록. 지금 단계 실패 항목이 최근 2번 연속이면 '## 막힘: 조사 단계' 절을 붙인다(판정은 그대로)."""
    st = stage_items(R, body)
    done = {(d['부위'], d['종류']): d for d in decided}
    kept = []
    for s_ in st:
        keep = [(p, d) for p, d in st[s_] if (p, d['종류']) not in done]
        kept += [(p, d) for p, d in st[s_] if (p, d['종류']) in done]
        st[s_] = keep
    stage = next((s for s in (1, 2, 3, 4) if st[s]), None)
    if stage is None and rig and rig.get('판정') in ('PASS', 'FAIL'):
        head = '결정됨 %d건. 단계 1~4 진단 없음. ' % len(kept)
        meas = '덩어리 %s, 열린 변 %s, 비대칭도 %s(보고만), 가중치 0 정점 비율 %s' % (
            rig.get('덩어리'), rig.get('열린변'), rig.get('비대칭도'), rig.get('가중치0_비율'))
        if rig['판정'] == 'PASS':
            return 'PASS', head + '# 단계 5 통과. 리깅 준비 검사 PASS.\n' + meas
        return 'FAIL', head + open(os.path.join(CARDS, STAGE_FILES[5]), encoding='utf-8').read().strip() + '\n\n## 실패 이유\n' + \
            '\n'.join('- ' + x for x in rig.get('이유', [])) + '\n\n측정: ' + meas
    if stage is None:
        return 'UNKNOWN', '결정됨 %d건. ' % len(kept) + '단계 1~4 진단 없음. ' + open(os.path.join(CARDS, STAGE_FILES[5]), encoding='utf-8').read()
    items = st[stage]
    out = [open(os.path.join(CARDS, STAGE_FILES[stage]), encoding='utf-8').read().strip(), '', '## 관련 교훈']
    for e in lessons(stage, items):
        out.append('- [%s] %s (%s)' % (e['id'], e['교훈'], e['출처']))
    out += ['', '## 지금 측정값(실패 항목만)']
    for p, d in items:
        r = R['부위'][p]
        views = ', '.join('%s IoU %.3f' % (v, x['IoU']) for v, x in r['뷰'].items())
        out.append('- %s: %s. %s%s' % (p, d['종류'], d['설명'], (' (' + views + ')') if views else ''))
    for p, d in {(p, d['종류']): (p, d) for p, d in kept}.values():
        x = done[(p, d['종류'])]
        out.append('- (결정됨) %s %s: %s. 근거: %s' % (p, d['종류'], x['결정'], x['근거']))
    later = [s for s in (2, 3, 4) if s > stage and st[s]]
    if later:
        out.append('(뒤 단계 %s 에도 진단이 있지만 이 단계를 끝낸 뒤 본다)' % later)
    out += research_section(stage, items, history or [])
    return 'FAIL', '\n'.join(out)


def main(argv):
    cmd = argv[0]
    if cmd == 'check':
        pk = Pack(arg(argv, '--pack'))
        z = np.load(arg(argv, '--masks'))
        trace = {tuple(k.split('|')): z[k] for k in z.files}
        parts = {}
        for s in arg(argv, '--part', many=True):
            name, path = s.split('=', 1)
            parts[name] = load_obj(path)
        R = check(pk, parts, trace, voxel=float(arg(argv, '--voxel') or 0.008))
        R['본체'] = arg(argv, '--body') or max(parts, key=lambda p: len(parts[p][0]))
        if arg(argv, '--merged'):                      # 합친 최종 메시(합쳐졌는지·닫혔는지)
            mc = merged_check(*load_obj(arg(argv, '--merged')))
            R['합친_메시'] = mc
            R['부위']['(합친 메시)'] = {'뷰': {}, '진단': mc['진단']}
            print('MODEL 합친 메시', {k: v for k, v in mc.items() if k != '진단'}, [d['종류'] for d in mc['진단']])
        out = arg(argv, '--out')
        os.makedirs(out, exist_ok=True)
        json.dump(R, open(os.path.join(out, 'model_check.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        for p, r in R['부위'].items():
            print('MODEL %s %s 채움비 %s 길쭉함 %s 높이차 %spx 진단 %s' % (p, {v: d['IoU'] for v, d in r['뷰'].items()}, r['단면_채움비'], r['길쭉함'],
                  r.get('트레이스_높이차_px'), [d['종류'] + ('/' + d['뷰'] if 'v' in d.get('뷰', 'v') and d.get('뷰') else '') for d in r['진단']]))
        print('MODEL 떠 있는 조각', R['떠있는_조각'])
        return 0
    cp = arg(argv, '--check')
    R = json.load(open(cp, encoding='utf-8'))
    dp = os.path.join(os.path.dirname(cp), 'model_decisions.json')         # LLM 결정 기록(같은 폴더)
    verdict, text = card(R, R.get('본체'), json.load(open(dp, encoding='utf-8')) if os.path.exists(dp) else [],
                         history=read_history(os.path.dirname(cp)), rig=read_rig(os.path.dirname(cp)))
    print(text)
    print('\n판정:', verdict)
    return 0 if verdict == 'PASS' else (2 if verdict == 'UNKNOWN' else 1)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
