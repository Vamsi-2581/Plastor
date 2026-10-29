# -*- coding: utf-8 -*-
"""하네스 도구 층(추상화). 하네스가 LLM 에게 내주는 일을 도구 하나하나로 정한다: 이름, 받는 값, 돌려주는 값.
명령줄(mh_tool.py)·MCP·다른 창구는 모두 이 층만 부른다. 기존 모듈(trace.py·build.py·model_loop.py 등)은 그대로 두고 감싼다.

설계 규칙
- 받는 값은 경로·부위 이름·뷰 이름·단계 이름·결정 문장뿐이다. 좌표·정점 값을 받는 도구는 없다(LLM 이 눈대중 좌표를 쓰지 않게).
- 돌려주는 값은 늘 {'판정': PASS|FAIL|UNKNOWN|ERROR, '요약': ..., '파일': {...}} 이다. 통과는 실행한 검증기의 PASS 뿐.
- 긴 문서 대신 짧은 결과를 돌려준다. 다음 할 일은 card 도구가 정 → 동 순서 카드 한 장으로 준다.
"""
import contextlib
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

VERDICTS = ('PASS', 'FAIL', 'UNKNOWN', 'ERROR')
TOOLS = {}


def tool(name, desc, params):
    """params: {이름: (형, 설명, 필수?)}. 형은 'path'|'str'|'enum:a,b'|'list'."""
    def deco(fn):
        TOOLS[name] = {'fn': fn, '설명': desc, '받는값': params}
        return fn
    return deco


def _res(verdict, summary, files=None):
    assert verdict in VERDICTS
    return {'판정': verdict, '요약': summary, '파일': files or {}}


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def validate(name, args):
    """받는 값 검사. 틀리면 오류 문장 목록(빈 목록 = 통과)."""
    if name not in TOOLS:
        return ['모르는 도구 %s' % name]
    P, errs = TOOLS[name]['받는값'], []
    for k, (typ, _, req) in P.items():
        if req and k not in args:
            errs.append('빠진 값 %s' % k)
        if k in args and typ.startswith('enum:') and args[k] not in typ[5:].split(','):
            errs.append('%s 는 %s 중 하나' % (k, typ[5:]))
        if k in args and typ == 'path' and not isinstance(args[k], str):
            errs.append('%s 는 경로 문자열' % k)
    for k in args:
        if k not in P:
            errs.append('모르는 값 %s' % k)
    return errs


def call(name, **args):
    errs = validate(name, args)
    if errs:
        return _res('ERROR', {'받는값_오류': errs})
    try:
        return TOOLS[name]['fn'](**args)
    except Exception as e:   # 도구 실패는 ERROR 로 돌려준다(창구가 죽지 않게)
        import traceback
        return _res('ERROR', {'예외': repr(e), '자리': traceback.format_exc().splitlines()[-4:]})


def describe():
    """창구(MCP 등)가 도구 목록을 만들 때 쓰는 설명."""
    return {n: {'설명': t['설명'], '받는값': {k: {'형': v[0], '설명': v[1], '필수': v[2]} for k, v in t['받는값'].items()}} for n, t in TOOLS.items()}


# ---------------------------------------------------------------- 0단계: 트레이싱
@tool('trace', '도면 이미지 + 거친 다각형 사양으로 부위 마스크를 딴다. 겹침 그림을 사람·LLM 이 본다(판정 UNKNOWN).',
      {'spec': ('path', '트레이싱 사양 JSON(trace.py 형식)', True)})
def t_trace(spec):
    import trace as T
    S = T.jload(spec)
    T._CACHE.clear()
    res, _ = _quiet(T.build, S, spec, True, False)
    rep = res['rep']
    out = res['out']
    return _res('UNKNOWN', {'부위': sorted({k[1] for k in res['masks']}), '군집수': rep.get('군집수')},
                {'겹침그림': os.path.join(out, 'overlay.png'), '마스크': os.path.join(out, 'masks.npz'), '보고': os.path.join(out, 'report.json')})


@tool('review', '트레이스 교정 후보를 번호 그림으로 낸다(stage=candidates). LLM 은 사양 clicks 에 번호마다 넣기·빼기·그대로만 적고 stage=apply 로 실행한다.',
      {'spec': ('path', '트레이싱 사양 JSON', True), 'stage': ('enum:candidates,apply', '후보 내기 또는 적용', True)})
def t_review(spec, stage):
    import trace_review as R
    code, log = _quiet(R.main, [stage, '--spec', spec])
    import trace as T
    out = T._rel(spec, T.jload(spec)['out'])
    files = {'후보그림': os.path.join(out, 'review.png'), '후보': os.path.join(out, 'review.json')} if stage == 'candidates' else \
        {'기록': os.path.join(out, 'clicks_log.json'), '겹침그림': os.path.join(out, 'overlay_clicks.png')}
    lines = [ln for ln in log.splitlines() if ln.startswith(('REVIEW', 'APPLY'))]
    return _res('UNKNOWN' if stage == 'candidates' else ('PASS' if code == 0 else 'FAIL'), {'줄': lines[:40]}, files)


# ---------------------------------------------------------------- 만들기·검사
@tool('build', '한 명령 파이프라인(트레이스→본체→부위→합치기→3D 검사→각도 그림→리깅 준비→카드). 단계마다 판정을 돌려준다.',
      {'spec': ('path', 'build.json', True), 'start': ('enum:trace,body,parts,merge,check,views,rig,card', '이 단계부터', False),
       'only': ('enum:trace,body,parts,merge,check,views,rig,card', '이 단계만', False)})
def t_build(spec, start=None, only=None):
    import build as B
    b = B.Build(spec)
    code, _ = _quiet(b.run, start, only)
    steps = {s: b.log[s]['판정'] for s in B.STEPS if s in b.log}
    v = 'PASS' if code == 0 else 'ERROR' if code == 3 else 'FAIL' if code == 1 else 'UNKNOWN'
    return _res(v, {'단계': steps}, {'단계기록': b.logp, '카드': b.p('card.md'), '합친메시': b.p('merged.obj')})


@tool('card', '지금 막힌 단계 하나의 카드(고정 규칙 → 관련 교훈 → 실패 측정값). 다음에 무엇을 할지는 이것만 본다.',
      {'out': ('path', 'build 결과 폴더(model_check.json 이 있는 곳)', True)})
def t_card(out):
    import model_loop as ML
    R = json.load(open(os.path.join(out, 'model_check.json'), encoding='utf-8'))
    dp = os.path.join(out, 'model_decisions.json')
    v, text = ML.card(R, R.get('본체'), json.load(open(dp, encoding='utf-8')) if os.path.exists(dp) else [], history=ML.read_history(out), rig=ML.read_rig(out))
    return _res(v, {'카드': text}, {'검사': os.path.join(out, 'model_check.json')})


@tool('decide', '그림 모순처럼 LLM 이 정할 항목의 결정을 근거와 함께 기록한다. 기록된 항목은 카드에서 막지 않고 결정됨으로 보인다.',
      {'out': ('path', 'build 결과 폴더', True), 'part': ('str', '부위 이름', True),
       'kind': ('enum:그림 모순,모델링 오차,상자 단면,떠 있는 조각,합쳐지지 않음,열린 메시', '진단 종류', True),
       'decision': ('str', '결정(예: 정면 따름)', True), 'reason': ('str', '근거(빈 문자열 금지)', True)})
def t_decide(out, part, kind, decision, reason):
    if not reason.strip():
        return _res('ERROR', {'이유': '근거 없는 결정은 받지 않는다'})
    dp = os.path.join(out, 'model_decisions.json')
    D = json.load(open(dp, encoding='utf-8')) if os.path.exists(dp) else []
    D = [d for d in D if not (d['부위'] == part and d['종류'] == kind)]
    D.append({'부위': part, '종류': kind, '결정': decision, '근거': reason})
    json.dump(D, open(dp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return _res('PASS', {'결정수': len(D)}, {'결정': dp})


@tool('views', '모델을 도면에 없는 각도(3/4·위·아래)에서 창 없이 찍는다. 그림은 판정이 아니다(UNKNOWN).',
      {'obj': ('path', 'OBJ 경로', True), 'out': ('path', '그림 폴더', True)})
def t_views(obj, out):
    from harness.blender_view import views_bg
    files = views_bg(obj, out)
    return _res('UNKNOWN' if all(files.values()) else 'ERROR', {'장수': sum(bool(f) for f in files.values())}, files)


def _frame(path):
    from build import Frame
    return Frame.load({('pack' if 'pack' in os.path.basename(path) else 'meta'): os.path.abspath(path)}, ROOT)


@tool('digest', '트레이스를 숫자로 요약한다(부위·뷰마다 조각 수·넓이·H 범위·좌우 대칭). 그림에서 세거나 재지 말고 이 숫자를 읽는다(LLM 은 세기·시점 합치기에 약함).',
      {'masks': ('path', 'masks.npz', True), 'frame': ('path', '팩(pack.json) 또는 trace meta(meta.json)', True)})
def t_digest(masks, frame):
    from harness.llm_aids import digest
    d = digest(masks, _frame(frame))
    return _res('UNKNOWN', {'표': d['글']}, {})


@tool('zoom', '부위 이름으로 그 부위 둘레를 원래 해상도로 잘라 키운 그림을 만든다. 조각마다 다른 색 테두리(digest 조각 순서). 작은 부위는 전체 그림 대신 이것을 본다.',
      {'drawing': ('path', '도면 npy', True), 'masks': ('path', 'masks.npz', True), 'part': ('str', '부위 이름', True),
       'view': ('enum:front,side,back', '뷰', True), 'out': ('path', 'PNG 경로', True)})
def t_zoom(drawing, masks, part, view, out):
    import numpy as np
    from harness.llm_aids import save_png, zoom_image
    img, info = zoom_image(np.load(drawing), masks, part, view)
    if img is None:
        return _res('FAIL', info)
    ok = save_png(img, out)
    return _res('UNKNOWN' if ok else 'ERROR', info, {'그림': out} if ok else {})


@tool('judge', '같은 질문을 순서 바꿔 여러 번·두 모델 가족으로 물은 답을 모아 확정/UNKNOWN 을 낸다(재현율 ≥ 0.8, 순서 뒤집힘 ≤ 0.2, 가족 일치, 가족 카파 ≥ 0.6).',
      {'runs': ('path', '답 모음 JSON: [{가족, 순서, 답: {문항: 답}}]', True)})
def t_judge(runs):
    from harness.llm_aids import judge
    r = judge(json.load(open(runs, encoding='utf-8')))
    return _res(r['판정'], {'가족_카파': r['가족_카파'], '확정': sum(x['판정'] == '확정' for x in r['문항'].values()), '문항_수': len(r['문항'])},
                {'자세히': r['문항']})


@tool('status', 'build 결과 폴더의 단계별 판정과 입력 지문을 돌려준다.',
      {'out': ('path', 'build 결과 폴더', True)})
def t_status(out):
    p = os.path.join(out, 'build_steps.json')
    if not os.path.exists(p):
        return _res('UNKNOWN', {'이유': '아직 build 를 돌리지 않음'})
    L = json.load(open(p, encoding='utf-8'))
    vs = {s: x['판정'] for s, x in L.items()}
    v = 'PASS' if all(x == 'PASS' for x in vs.values()) else 'ERROR' if 'ERROR' in vs.values() else 'FAIL' if 'FAIL' in vs.values() else 'UNKNOWN'
    return _res(v, {s: {'판정': x['판정'], '같은입력': x.get('이전과_같은_입력')} for s, x in L.items()}, {'단계기록': p})
