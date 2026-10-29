# -*- coding: utf-8 -*-
"""M0 과제 묶음(docs/계획_숙련모델러.md 4장): 과제 만들기, 기준선 돌리기, 채점, 장부.

과제
  합성 6종(씨앗 600~605, 개발에 쓴 적 없는 씨앗): 기본·색조·두 재질 귀·체크무늬·배경 비슷한 뿔·외곽선.
    정답: 부위 마스크(실루엣)와 3D 도형(타원체 합집합, '목' 제외)을 안다.
  실제 도면: 들소 머리, 새 머리(케라투라 머리 128 시트). 3D 정답이 없어 실루엣은 트레이스와 비교하고 부피는 UNKNOWN.

채점(모델 하나 = 합친 메시 OBJ, H 단위)
  실루엣 IoU: 정면·옆 투영 대 정답 마스크 합집합(합성) 또는 트레이스 합집합(실제).
  부피 IoU: 0.01H 복셀에서 메시 안 대 정답 도형 안(합성만).
  몸 수: 합친 메시의 연결 조각 수(1 이 정상).
  지문: 꼭짓점 좌표(소수 4자리)와 면의 해시. 같은 입력으로 다시 돌렸을 때 같아야 한다.

명령
  python bench/m0.py make                       과제 폴더 bench/m0/<과제>/ 만들기
  python bench/m0.py harness [과제...]          기준선 ② 지금 하네스(build.py, 둥근 헐 + 제한 이완, 들소 16차 설정)
  python bench/m0.py score <과제> <OBJ> <기준선이름> [--note 글]   채점해 bench/m0/ledger.jsonl 에 한 줄
  python bench/m0.py table                      장부 요약표
"""
import hashlib
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'bench'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

M0 = os.path.join(ROOT, 'bench', 'm0')
LEDGER = os.path.join(M0, 'ledger.jsonl')
PARTS = ('머리', '뿔', '뿔 밑동', '귀', '갈기')
SYNTH = {   # 과제 이름: (씨앗, scene_case 옵션)
    'synth_basic': (600, {}),
    'synth_hue': (601, {'hue': True}),
    'synth_twotone': (602, {'twotone': True}),
    'synth_checker': (603, {'checker': True}),
    'synth_hardbg': (604, {'hard': True}),
    'synth_outline': (605, {'outline': True}),
}
DEV = {     # 개발용(루프가 후보를 고르는 데 씀). M0 과제(600~605)는 확인용으로만 쓴다
    'dev_basic': (700, {}), 'dev_hue': (701, {'hue': True}), 'dev_twotone': (702, {'twotone': True}),
    'dev_checker': (703, {'checker': True}), 'dev_hardbg': (704, {'hard': True}), 'dev_outline': (705, {'outline': True}),
}
SYNTH_ALL = dict(SYNTH, **DEV)
REAL = {    # 과제 이름: 기존 고정물(트레이스 결과 masks, 틀)
    'real_bison': {'masks': 'fixtures/bison_head/trace/out_v2/masks.npz', 'frame': {'pack': 'packs/head_traced/pack.json'},
                   'parts': ['뿔', '귀']},
    'real_bird': {'masks': 'fixtures/bird_head/out_sam/masks.npz', 'frame': {'meta': 'fixtures/bird_head/trace_meta.json'},
                  'parts': ['부리']},
}


def jdump(o, p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def _prims(seed, opt):
    from scene import creature
    rng = np.random.default_rng(seed)
    hue = opt.get('hue') or opt.get('twotone')
    prims, _ = creature(rng, opt.get('hard', False), hue, opt.get('twotone', False))
    return [p for p in prims if p['part'] != '목']


def make(only=None):
    import shutil
    import run
    for name, (seed, opt) in SYNTH_ALL.items():
        if only and name not in only:
            continue
        d = os.path.join(M0, name)
        os.makedirs(d, exist_ok=True)
        cases = run.scene_case(seed, hard=opt.get('hard', False), outline=opt.get('outline', False), hue=opt.get('hue', False),
                               twotone=opt.get('twotone', False), checker=opt.get('checker', False))
        src = os.path.join(run.OUT, 's%02d' % seed)
        for f in ('drawing.npy', 'meta.json', 'rough.json', 'spec.json'):
            shutil.copy(os.path.join(src, f), os.path.join(d, f))
        S = json.load(open(os.path.join(d, 'spec.json'), encoding='utf-8'))
        S['out'] = 'trace_out'
        jdump(S, os.path.join(d, 'spec.json'))
        img, truth, pal, meta = run.cached_render(seed, opt.get('hard', False), opt.get('outline', False), False,
                                                  bool(opt.get('hue') or opt.get('twotone')), opt.get('twotone', False), opt.get('checker', False))
        np.savez_compressed(os.path.join(d, 'truth.npz'), **{'%s|%s' % k: m for k, m in truth.items() if k[1] in PARTS})
        jdump({'이름': name, '종류': '합성', '씨앗': seed, '옵션': opt, '부위': sorted({k[1] for k in truth if k[1] in PARTS}),
               '정답': {'실루엣': 'truth.npz', '부피': 'scene.creature(씨앗) 타원체 합집합(목 제외)'}}, os.path.join(d, 'task.json'))
        print('MAKE', name, '씨앗', seed, sorted({k[1] for k in truth}))
    for name, r in REAL.items():
        if only and name not in only:
            continue
        d = os.path.join(M0, name)
        jdump({'이름': name, '종류': '실제', '트레이스': r['masks'], '틀': r['frame'], '부위': r['parts'],
               '정답': {'실루엣': '트레이스(정답 아님, 하네스 자체 결과)', '부피': 'UNKNOWN'}}, os.path.join(d, 'task.json'))
        print('MAKE', name)


def _frame(task):
    from build import Frame
    if task['종류'] == '합성':
        return Frame.load({'meta': os.path.join(M0, task['이름'], 'meta.json')}, ROOT)
    return Frame.load({k: os.path.join(ROOT, v) for k, v in task['틀'].items()}, ROOT)


def _ref_masks(task):
    if task['종류'] == '합성':
        z = np.load(os.path.join(M0, task['이름'], 'truth.npz'))
    else:
        z = np.load(os.path.join(ROOT, task['트레이스']))
    with z:
        M = {tuple(k.split('|')): z[k] for k in z.files}
    return M


def _gt_occ(task, lo, shape, voxel):
    seed, opt = SYNTH_ALL[task['이름']]
    pts = [lo + (np.indices(shape).reshape(3, -1).T + 0.5) * voxel][0]
    ins = np.zeros(len(pts), bool)
    for p in _prims(seed, opt):
        ins |= (((pts - p['c']) / p['r']) ** 2).sum(1) <= 1
    return ins.reshape(shape)


def _voxelize_parts(V, F, voxel, voxelize):
    """연결 조각마다 따로 복셀화해 합친다. 겹친 닫힌 조각들을 한 번에 광선 홀짝으로 재면 겹친 곳이 '밖'이 된다
    (기준선 ① 은 부위를 합치지 않고 한 OBJ 에 넣었다). 한 덩어리 메시는 결과가 같다."""
    par = np.arange(len(V))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    for f in F:
        r = [find(x) for x in f]
        for x in r[1:]:
            par[x] = r[0]
    lab = np.array([find(f[0]) for f in F])
    lo = V.min(0) - 2 * voxel
    shape = np.ceil((V.max(0) + 2 * voxel - lo) / voxel).astype(int) + 1
    occ = np.zeros(shape, bool)
    for c in np.unique(lab):
        o, l = voxelize(V, F[lab == c], voxel)
        s = np.round((l - lo) / voxel).astype(int)
        e = np.minimum(s + np.array(o.shape), shape)
        occ[s[0]:e[0], s[1]:e[1], s[2]:e[2]] |= o[:e[0] - s[0], :e[1] - s[1], :e[2] - s[2]]
    return occ, lo


def score(tname, obj, base, note='', extra=None):
    from harness.model_check import load_obj, voxelize, project, iou, merged_check
    task = json.load(open(os.path.join(M0, tname, 'task.json'), encoding='utf-8'))
    V, F = load_obj(obj)
    fp = hashlib.sha1(np.round(V, 4).tobytes() + F.tobytes()).hexdigest()[:12]
    frame = _frame(task)
    M = _ref_masks(task)
    shape = next(iter(M.values())).shape
    # 복셀 한 칸이 도면 1.5px 이하가 되게(투영은 칸마다 3x3 점이라, 새 머리 1H=376px 에서 0.01H 는 칸 사이에 구멍이 났다)
    # 채점 칸 0.5px(0.003~0.005H): 1px 칸은 칸이 통째로 차거나 비어 가장자리 ±0.5px(수정_기록 48·49). 옛 규칙 min(0.01, 1.5/ppH)
    voxel = min(0.005, max(0.003, 0.5 / frame.ppH))
    occ, lo = _voxelize_parts(V, F, voxel, voxelize)
    row = {'시각': time.strftime('%Y-%m-%dT%H:%M:%S'), '과제': tname, '기준선': base, 'OBJ': os.path.relpath(obj, ROOT) if os.path.splitdrive(os.path.abspath(obj))[0].lower() == os.path.splitdrive(ROOT)[0].lower() else obj, '지문': fp,
           '실루엣': {}, '메모': note}
    for v in ('front', 'side'):
        ref = np.zeros(shape, bool)
        for (vv, p), m in M.items():
            if vv == v and (task['종류'] == '실제' or p in PARTS):
                ref |= m
        if ref.any():
            row['실루엣'][v] = round(iou(project(occ, lo, voxel, frame, v, shape), ref), 4)
    if task['종류'] == '합성':
        # 정답과 같은 격자에서 비교: 둘을 모두 담는 상자
        seed, opt = SYNTH_ALL[tname]
        P = _prims(seed, opt)
        glo = np.minimum(lo, np.min([p['c'] - p['r'] for p in P], 0)) - 2 * voxel
        ghi = np.maximum(lo + np.array(occ.shape) * voxel, np.max([p['c'] + p['r'] for p in P], 0)) + 2 * voxel
        gs = np.ceil((ghi - glo) / voxel).astype(int)
        mine = np.zeros(gs, bool)
        o = np.round((lo - glo) / voxel).astype(int)
        mine[o[0]:o[0] + occ.shape[0], o[1]:o[1] + occ.shape[1], o[2]:o[2] + occ.shape[2]] = occ
        gt = _gt_occ(task, glo, tuple(gs), voxel)
        row['부피'] = round(float((mine & gt).sum() / max((mine | gt).sum(), 1)), 4)
    else:
        row['부피'] = 'UNKNOWN'
    row['복셀'] = round(voxel, 5)
    mc = merged_check(V, F)
    row['몸_수'] = mc.get('몸_수')
    row.update(_k1(task, obj, V, F, occ, voxel, frame, M, shape))
    row.update(extra or {})
    os.makedirs(M0, exist_ok=True)
    with open(LEDGER, 'a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print('SCORE', json.dumps(row, ensure_ascii=False))
    return row


GROUPS = {'머리': ('머리',), '뿔': ('뿔', '뿔 밑동'), '귀': ('귀',), '갈기': ('갈기',)}   # 채점 부위 묶음(뿔 밑동은 뿔로)


def _part_meshes(d):
    """결과 폴더의 부위 메시: 머리 = body.obj, 나머지 = part_<이름>.obj(뿔 밑동은 뿔 묶음에 합침)."""
    from harness.model_check import load_obj
    out = {}
    for g, names in GROUPS.items():
        files = ['body.obj'] if g == '머리' else ['part_%s.obj' % n for n in names]
        mm = [load_obj(os.path.join(d, f)) for f in files if os.path.exists(os.path.join(d, f))]
        if mm:
            out[g] = mm
    return out


def _k1(task, obj, V, F, occ, voxel, frame, M, shape):
    """K1 채점 항목(docs/구현계획_통합.md K1): 거칠기·3/4 폭 비·부위별 실루엣(가려진 픽셀 제외)·부위 부피·랜드마크."""
    from harness import metrics as K
    from harness.model_check import project
    r = {'거칠기': K.roughness_v2(V, F), '3/4폭비': K.quarter_ratio(occ, voxel)}   # 거칠기 v2(K1, v1 은 FAIL 로 버림)
    r['거칠기'] = round(r['거칠기'], 2) if r['거칠기'] is not None else None
    r['3/4폭비'] = round(r['3/4폭비'], 4) if r['3/4폭비'] is not None else None
    pm = _part_meshes(os.path.dirname(obj))
    if not pm:
        r['부위'] = 'UNKNOWN(부위 메시 없음)'
        return r
    if task['종류'] == '합성':
        import run
        seed, opt = SYNTH_ALL[task['이름']]
        _, truth, _, _ = run.cached_render(seed, opt.get('hard', False), opt.get('outline', False), False,
                                           bool(opt.get('hue') or opt.get('twotone')), opt.get('twotone', False), opt.get('checker', False))
        P = _prims(seed, opt)
    else:
        truth, P = M, None
    parts, occs = {}, {}
    for g, meshes in pm.items():
        names = GROUPS[g]
        o, lo = _voxelize_parts(np.vstack([m[0] for m in meshes]),
                                np.vstack([m[1] + sum(len(q[0]) for q in meshes[:i]) for i, m in enumerate(meshes)]), voxel, _vox())
        occs[g] = (o, lo)
        e = {'실루엣': {}}
        for v in ('front', 'side'):
            ref = np.zeros(shape, bool)
            dc = np.zeros(shape, bool)
            for (vv, p), m in truth.items():
                if vv != v:
                    continue
                if p in names:
                    ref |= m
                else:
                    dc |= m
            if ref.any():
                e['실루엣'][v] = round(K.part_silhouette(project(o, lo, voxel, frame, v, shape), ref, dc), 4)
        if P is not None and any(p['part'] in names for p in P):
            mine, gt, _ = K.common_grid(o, lo, P, names, voxel)
            e['부피'] = round(float((mine & gt).sum() / max((mine | gt).sum(), 1)), 4)
        e['3/4폭비'] = K.quarter_ratio(o, voxel)
        e['3/4폭비'] = round(e['3/4폭비'], 4) if e['3/4폭비'] is not None else None
        parts[g] = e
    r['부위'] = parts
    # 랜드마크: 합성은 정답 칸과 같은 규칙(3D), 실제는 옆 뷰 트레이스의 코끝(2D)
    if '머리' in occs:
        hm = K.cell_points(*occs['머리'], voxel)
        horn = K.cell_points(*occs['뿔'], voxel) if '뿔' in occs else None
        mod = K.landmarks(hm, horn)
        if P is not None:
            gh = K.common_grid(*occs['머리'], P, GROUPS['머리'], voxel)
            th = K.cell_points(gh[1], gh[2], voxel)
            tn = None
            if '뿔' in occs and any(p['part'] in GROUPS['뿔'] for p in P):
                gn = K.common_grid(*occs['뿔'], P, GROUPS['뿔'], voxel)
                tn = K.cell_points(gn[1], gn[2], voxel)
            r['랜드마크_잔차'] = K.landmark_residuals(mod, K.landmarks(th, tn))
        else:
            m = truth.get(('side', '머리'))
            if m is not None and m.any():
                pj = project(*occs['머리'], voxel, frame, 'side', shape)
                def tip(mask):
                    c = np.flatnonzero(mask.any(0))
                    c0 = c.min() if frame.panels['side']['sign'] < 0 else c.max()   # 화면에서 앞쪽 끝
                    rows = np.flatnonzero(mask[:, c0])
                    return np.array(frame.px_to_H('side', c0 + 0.5, rows.mean() + 0.5))
                r['랜드마크_잔차'] = {'코끝(옆 2D)': round(float(np.linalg.norm(tip(pj) - tip(m))), 4)}
    return r


def _vox():
    from harness.model_check import voxelize
    return voxelize


def _merge(a, b):
    out = dict(a)
    for k, v in b.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def harness(names, label='②하네스', over=None, sub='base2'):
    """기준선 ②: 들소 16차와 같은 설정(본체 둥근 헐 + 제한 이완 20, 뿔 둥근 헐, 나머지 기본 헐, 박기).
    over: 설정 덮어쓰기 {'body': {...}, 'parts': {부위 또는 '*': {...}}, 'merge': {...}}. sub: 결과 폴더 이름. 반환 채점 줄 목록."""
    import build as B
    over = over or {}
    names = names or list(SYNTH) + list(REAL)
    rows = []
    for name in names:
        task = json.load(open(os.path.join(M0, name, 'task.json'), encoding='utf-8'))
        d = os.path.join(M0, name, sub)
        os.makedirs(d, exist_ok=True)
        if task['종류'] == '합성':
            parts = [p for p in task['부위'] if p != '머리']
            S = {'out': '.', 'frame': {'meta': '../meta.json'}, 'trace': {'spec': '../spec.json'}}
        else:
            parts = task['부위']
            S = {'out': '.', 'frame': {k: os.path.relpath(os.path.join(ROOT, v), d) for k, v in task['틀'].items()},
                 'trace': {'masks': os.path.relpath(os.path.join(ROOT, task['트레이스']), d)}}
        S['body'] = _merge({'part': '머리', 'method': 'round', 'smooth': 1.5, 'cesn': 20}, over.get('body', {}))
        po = over.get('parts', {})
        S['parts'] = [_merge(_merge(({'name': p, 'method': 'round', 'embed_px': 8, 'cesn': 20} if p in ('뿔', '뿔 밑동', '부리') else {'name': p, 'embed_px': 4}),
                                    po.get('*', {})), po.get(p, {})) for p in parts]
        S['merge'] = _merge({'ratio': 0.06}, over.get('merge', {}))
        sp = os.path.join(d, 'build.json')
        jdump(S, sp)
        for f in ('merged.obj', 'body.obj'):          # 실패했을 때 지난 결과를 채점하지 않게
            if os.path.exists(os.path.join(d, f)):
                os.remove(os.path.join(d, f))
        b = B.Build(sp)
        code = 3
        try:
            for st in ('trace', 'body', 'parts', 'merge', 'check'):
                code = b.run(only=st)
        except Exception as e:  # noqa: BLE001  기준선은 실패도 기록한다
            print('HARNESS ERROR', name, repr(e)[:300])
        obj = os.path.join(d, 'merged.obj')
        if os.path.exists(obj):
            # 비용 지표(K1, I08): 단계별 걸린 시간. 하네스 자동 실행이라 LLM 호출·사람 개입·LLM 이 쓴 좌표는 0(도구가 좌표를 받지 않음)
            st = {k: v.get('초') for k, v in b.log.items() if isinstance(v, dict) and '초' in v}
            cost = {'비용': {'단계_초': st, '전체_초': round(sum(x or 0 for x in st.values()), 1), 'LLM_호출': 0, '사람_개입': 0, '좌표_입력': 0}}
            rows.append(score(name, obj, label, '끝 코드 %s' % code, cost))
        else:
            r = {'시각': time.strftime('%Y-%m-%dT%H:%M:%S'), '과제': name, '기준선': label, '판정': 'ERROR', '메모': '합친 메시 없음'}
            with open(LEDGER, 'a', encoding='utf-8') as f:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
            rows.append(r)
            print('HARNESS 메시 없음', name)
    return rows


def table():
    rows = [json.loads(l) for l in open(LEDGER, encoding='utf-8')] if os.path.exists(LEDGER) else []
    last = {}
    for r in rows:
        last[(r['과제'], r['기준선'])] = r
    print('과제 | 기준선 | 정면 | 옆 | 부피 | 몸 | 지문')
    for (t, b), r in sorted(last.items()):
        s = r.get('실루엣', {})
        print('%s | %s | %s | %s | %s | %s | %s' % (t, b, s.get('front', '-'), s.get('side', '-'), r.get('부피', r.get('판정')), r.get('몸_수', '-'), r.get('지문', '-')))


if __name__ == '__main__':
    a = sys.argv[1:]
    if not a or a[0] == 'make':
        make(a[1:])
    elif a[0] == 'harness':
        harness(a[1:])
    elif a[0] == 'score':
        note = a[a.index('--note') + 1] if '--note' in a else ''
        score(a[1], a[2], a[3], note)
    elif a[0] == 'table':
        table()
