# -*- coding: utf-8 -*-
"""K0 LLM 능력 재기(docs/구현계획_통합.md K0). 합성 장면에서 정답을 알고 묻는다.
  python bench/k0.py make            문항 그림·질문(순서 A·B)·정답 만들기 → bench/k0/q/ (모델에게 줄 폴더), bench/k0/gt.json (주지 않음)
  python bench/k0.py score           bench/k0/answers/*.json 을 모아 세트별 정확도·judge 통계·기준 판정
답 파일: {"가족": "claude"|"codex", "순서": "A"|"B", "답": {"q01": "있다", ...}}
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
K0 = os.path.join(HERE, 'k0')
Q = os.path.join(K0, 'q')


def png(arr, path):
    from harness.llm_aids import save_png
    save_png(np.ascontiguousarray(arr, np.uint8), path)


def prims_of(seed, ear_scale=1.0):
    from scene import creature
    return creature(np.random.default_rng(seed), ear_scale=ear_scale)[0]


def has_crest(P):
    base = next(p for p in P if p['part'] == '머리')
    return any(p['part'] == '머리' and p['mat'] == '털' and p is not base and p['r'][0] < 0.5 * base['r'][0] for p in P)


def truth_npz(truth, path):
    np.savez(path, **{'%s|%s' % k: m for k, m in truth.items()})


def gt_mesh(task, path):
    """M0 합성 과제의 정답 도형(목 제외 타원체 합집합) → OBJ."""
    import m0
    from harness import metrics as K
    from harness.export import write_obj
    from skimage.measure import marching_cubes
    seed, opt = m0.SYNTH_ALL[task]
    P = m0._prims(seed, opt)
    vx = 0.006
    lo = np.min([p['c'] - p['r'] for p in P], 0) - 3 * vx
    hi = np.max([p['c'] + p['r'] for p in P], 0) + 3 * vx
    shape = tuple(np.ceil((hi - lo) / vx).astype(int))
    occ = K.gt_occ(P, {p['part'] for p in P}, lo, shape, vx).astype(float)
    v, f, _, _ = marching_cubes(np.pad(occ, 1), 0.5)
    write_obj(path, lo + (v - 1) * vx, f[:, ::-1].copy())


PAIR_PY = r'''
import sys, bpy, math, mathutils
a = sys.argv[sys.argv.index('--') + 1:]
left, right, out = a[0], a[1], a[2]
bpy.ops.wm.read_factory_settings(use_empty=True)
obs = []
for p in (left, right):
    bpy.ops.wm.obj_import(filepath=p, forward_axis='Y', up_axis='Z')
    obs.append(bpy.context.selected_objects[0])
def bounds(o):
    ps = [o.matrix_world @ v.co for v in o.data.vertices]
    c = sum(ps, mathutils.Vector()) / len(ps)
    return c, max((q - c).length for q in ps)
(c0, r0), (c1, r1) = bounds(obs[0]), bounds(obs[1])
R = max(r0, r1)
obs[0].location -= c0 - mathutils.Vector((-1.15 * R, 0, 0))
obs[1].location -= c1 - mathutils.Vector((1.15 * R, 0, 0))
sc = bpy.context.scene
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'
sc.display.shading.color_type = 'SINGLE'
sc.render.resolution_x, sc.render.resolution_y = 1200, 600
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'; cam.data.ortho_scale = 4.8 * R; cam.data.clip_end = 100 * R
rot = mathutils.Euler((math.radians(75), 0, math.radians(150)), 'XYZ')
for o in obs:   # 둘 다 같은 3/4 방향으로 보이게 모델을 돌린다(카메라는 정면)
    o.rotation_euler = (0, 0, math.radians(-30))
cam.rotation_euler = mathutils.Euler((math.radians(75), 0, 0), 'XYZ')
cam.location = mathutils.Vector((0, -10 * R, 2.7 * R))
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
'''


def make():
    import run
    from harness.llm_aids import zoom_image
    import m0
    os.makedirs(Q, exist_ok=True)
    items, gt = [], {}
    n = [0]

    def add(set_id, img, question, options, answer, extra=None):
        n[0] += 1
        q = 'q%02d' % n[0]
        png(img, os.path.join(Q, q + '.png')) if img is not None else None
        items.append({'id': q, '세트': set_id, '질문': question, '보기': options})
        gt[q] = dict({'세트': set_id, '정답': answer}, **(extra or {}))
        return q
    tmp = os.path.join(K0, 'tmp')
    os.makedirs(tmp, exist_ok=True)
    # 세트 1: 부위 알아보기(전체 그림)
    for s in range(800, 810):
        img, truth, _, _ = run.cached_render(s)
        P = prims_of(s)
        mane = any(p['part'] == '갈기' for p in P)
        add(1, img, '이 크리처 머리 도면(왼쪽 정면, 오른쪽 옆면)에 **갈기**(머리 뒤쪽에서 위로 크게 덮은 털 덩어리)가 있나?', ['있다', '없다'], '있다' if mane else '없다')
        n[0] += 0
        items.append(dict(items[-1], id='q%02d' % (n[0] + 1), 질문='같은 그림(앞 문항 그림을 본다)에서 정수리 위에 작은 **볏**(혹)이 있나?', 보기=['있다', '없다'], 그림=items[-1]['id']))
        n[0] += 1
        gt['q%02d' % n[0]] = {'세트': 1, '정답': '있다' if has_crest(P) else '없다'}
    # 세트 2: 연산자 고르기(이름 숨긴 부위 확대)
    OPS = ['덩어리(둥근 덩어리)', '관(굵기가 변하는 휜 관)', '판(얇은 판)']
    ans = {'뿔': OPS[1], '귀': OPS[2], '갈기': OPS[0], '머리': OPS[0]}
    for s in range(800, 804):
        img, truth, _, _ = run.cached_render(s)
        P = prims_of(s)
        tn = os.path.join(tmp, 't%d.npz' % s)
        T = {}
        for (v, p), m in truth.items():
            q = '뿔' if p == '뿔 밑동' else p
            T[(v, q)] = T.get((v, q), np.zeros_like(m)) | m
        truth_npz(T, tn)
        for part in ['뿔', '귀', '갈기' if any(p['part'] == '갈기' for p in P) else '머리']:
            z, _ = zoom_image(img, tn, part, 'front')
            add(2, z, '색 테두리로 표시한 부위를 3D 로 만들 때 가장 맞는 기본 도형은?', OPS, ans[part], {'부위': part})
    # 세트 3: 작은 부위 보이기(귀 크기 0·0.5·1, 전체 그림 대 zoom)
    from scene import render
    for s in range(820, 824):
        for es in (0.0, 0.5, 1.0):
            img, truth, _, _ = render(s, ear_scale=es)
            tn = os.path.join(tmp, 'e%d_%g.npz' % (s, es))
            truth_npz(truth, tn)
            z, _ = zoom_image(img, tn, '머리', 'front', margin=0.6)
            a = '있다' if es > 0 else '없다'
            add(3, img, '이 도면(왼쪽 정면, 오른쪽 옆면)에서 머리 옆에 **귀**가 보이나?', ['있다', '없다'], a, {'귀_크기': es, '그림': '전체'})
            add(3, z, '이 확대 그림에서 머리 옆에 **귀**가 보이나?', ['있다', '없다'], a, {'귀_크기': es, '그림': 'zoom'})
    # 세트 4: 아트(정답 도형 렌더 대 하네스 결과 렌더). 순서 A 는 왼쪽 = 짝수 문항에 따라 섞음, B 는 좌우를 바꾼 그림을 따로 만든다
    from build import BLENDER
    pair_py = os.path.join(tmp, 'pair.py')
    open(pair_py, 'w', encoding='utf-8').write(PAIR_PY)
    for i, t in enumerate(['synth_basic', 'synth_hue', 'synth_twotone', 'synth_checker', 'synth_hardbg', 'synth_outline']):
        g = os.path.join(tmp, 'gt_%s.obj' % t)
        gt_mesh(t, g)
        h = os.path.join(ROOT, 'bench', 'm0', t, 'base2', 'merged.obj')
        good_left = i % 2 == 0
        n[0] += 1
        q = 'q%02d' % n[0]
        for order, gl in (('A', good_left), ('B', not good_left)):
            l, r = (g, h) if gl else (h, g)
            subprocess.run([BLENDER, '-b', '-P', pair_py, '--', l, r, os.path.join(Q, '%s_%s.png' % (q, order))], capture_output=True)
        items.append({'id': q, '세트': 4, '질문': '두 3D 모델(같은 크리처 머리) 중 **형태가 더 잘 만들어진 쪽**은? (덩어리의 둥근 입체감, 매끈한 표면, 자연스러운 단면으로 판단. 색·질감은 없음)',
                      '보기': ['왼쪽', '오른쪽'], '그림_순서별': True})
        gt[q] = {'세트': 4, '정답_A': '왼쪽' if good_left else '오른쪽', '정답_B': '오른쪽' if good_left else '왼쪽', '과제': t}
    json.dump(gt, open(os.path.join(K0, 'gt.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for order in ('A', 'B'):
        L = ['# K0 문항(순서 %s)' % order, '', '규칙: 문항마다 그림 파일을 보고, 보기 중 하나를 **글자 그대로** 고른다. 다른 파일(정답·코드)은 보지 않는다.',
             '답은 JSON 한 개: {"q01": "보기 글자", ...}', '']
        for it in items:
            opts = it['보기'] if order == 'A' else list(reversed(it['보기']))
            if it.get('그림_순서별'):
                pic = '%s_%s.png' % (it['id'], order)
            else:
                pic = '%s.png' % it.get('그림', it['id'])
            L.append('- %s | 그림 %s | %s | 보기: %s' % (it['id'], pic, it['질문'], ' / '.join(opts)))
        open(os.path.join(Q, '문항_%s.md' % order), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print('K0 문항', len(items), '그림', len([f for f in os.listdir(Q) if f.endswith('.png')]))


def score():
    from harness.llm_aids import judge
    gt = json.load(open(os.path.join(K0, 'gt.json'), encoding='utf-8'))
    runs = [json.load(open(os.path.join(K0, 'answers', f), encoding='utf-8')) for f in sorted(os.listdir(os.path.join(K0, 'answers'))) if f.endswith('.json')]
    norm = []
    for r in runs:      # 세트 4 는 순서마다 정답 칸이 달라 '정답이냐'로 바꿔 모은다(좌우가 아니라 맞음/틀림으로)
        a = {}
        for q, v in r['답'].items():
            g = gt.get(q)
            if g is None:
                continue
            if g['세트'] == 4:
                a[q] = '정답' if v.strip() == g['정답_' + r['순서']] else '오답'
            else:
                a[q] = v.strip()
        norm.append(dict(r, 답=a))
    J = judge(norm)
    out = {'가족_카파': J['가족_카파'], '세트': {}}
    for sid in (1, 2, 3, 4):
        qs = [q for q, g in gt.items() if g['세트'] == sid]
        cor, tot = 0, 0
        for r in norm:
            for q in qs:
                if q in r['답']:
                    ok = r['답'][q] == '정답' if sid == 4 else r['답'][q] == gt[q]['정답']
                    cor += ok
                    tot += 1
        st = [J['문항'][q] for q in qs if q in J['문항']]
        out['세트'][sid] = {'정확도': round(cor / max(tot, 1), 3), '답_수': tot,
                           '확정_비율': round(np.mean([x['판정'] == '확정' for x in st]), 3) if st else None,
                           '재현율_평균': round(np.mean([x['재현율'] for x in st]), 3) if st else None,
                           '순서_뒤집힘_평균': round(np.mean([x['순서_뒤집힘'] for x in st]), 3) if st else None}
        fams = sorted({r['가족'] for r in norm})
        out['세트'][sid]['가족별_정확도'] = {}
        for f in fams:
            c = t2 = 0
            for r in norm:
                if r['가족'] != f:
                    continue
                for q in qs:
                    if q in r['답']:
                        c += (r['답'][q] == '정답') if sid == 4 else (r['답'][q] == gt[q]['정답'])
                        t2 += 1
            out['세트'][sid]['가족별_정확도'][f] = round(c / max(t2, 1), 3)
    # 세트 3: 귀 크기별 전체 대 zoom
    s3 = {}
    for q, g in gt.items():
        if g['세트'] != 3:
            continue
        key = '%s_%g' % (g['그림'], g['귀_크기'])
        for r in norm:
            if q in r['답']:
                s3.setdefault(key, []).append(r['답'][q] == g['정답'])
    out['세트3_크기별'] = {k: round(float(np.mean(v)), 3) for k, v in sorted(s3.items())}
    S = out['세트']
    d05 = out['세트3_크기별'].get('zoom_0.5', 0) - out['세트3_크기별'].get('전체_0.5', 0)
    out['판정'] = {
        '1 부위 알아보기(정확도 ≥ 0.9, 확정 ≥ 0.8)': 'PASS' if S[1]['정확도'] >= 0.9 and (S[1]['확정_비율'] or 0) >= 0.8 else 'FAIL',
        '2 연산자 고르기(정확도 ≥ 0.9)': 'PASS' if S[2]['정확도'] >= 0.9 else 'FAIL',
        '3 작은 부위(0.5배 zoom − 전체 ≥ +0.2)': 'PASS' if d05 >= 0.2 else 'FAIL',
        '4 아트 판정(정확도 ≥ 0.8, 카파 ≥ 0.6)': 'PASS' if S[4]['정확도'] >= 0.8 and (J['가족_카파'] or 0) >= 0.6 else 'FAIL',
        '5 재현(재현율 ≥ 0.9, 뒤집힘 ≤ 0.1)': 'PASS' if np.mean([S[k]['재현율_평균'] for k in S]) >= 0.9 and np.mean([S[k]['순서_뒤집힘_평균'] for k in S]) <= 0.1 else 'FAIL',
    }
    out['세트3_0.5배_차'] = round(d05, 3)
    json.dump(out, open(os.path.join(K0, 'result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    {'make': make, 'score': score}[sys.argv[1]]()
