# -*- coding: utf-8 -*-
r"""트레이싱 벤치마크: 합성 도면 N 장에 LLM 거친 트레이스를 흉내 낸 다각형을 주고 trace.build 결과를 정답과 비교한다.
거친 트레이스 = 정답 윤곽을 따라 점 8px 마다 하나, 각 점을 ±jitter px 흔들고, 일부 구간은 안쪽으로 크게(지적 5 같은 실수) 뺀다.
점수: 부위·뷰마다 IoU(정답 대비). '경계로 정해지는 부위'(뿔+뿔 밑동 합침, 귀)와 '컷이 있는 부위'(머리: 목·갈기와 같은 털)를 나눠 본다.
실행: python bench/run.py [--n 12] [--seed0 0] [--hard]
출력: bench/out/result.json, 장면별 겹침 그림 bench/out/sNN_overlay.png
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import trace as T  # noqa: E402
from harness.render import write_png  # noqa: E402
from harness.trace import components, fill_poly, overlay  # noqa: E402
from scene import GROUND, H, PPH, W, ZOFF, render  # noqa: E402

BLENDER = os.path.join('C:' + os.sep, 'Program Files', 'Blender Foundation', 'Blender 5.2', 'blender.exe')


def render_blender(seed, outline=False, guide=True, noise=2.0):
    """Blender(Eevee 툰 셰이딩)로 렌더한 합성 도면. 정답은 부위 고유 발광색 렌더에서 가장 가까운 색으로."""
    import subprocess
    sys.path.append(os.path.join(ROOT, '.vendor'))
    from PIL import Image
    d = os.path.join(OUT, 'bl%02d%s' % (seed, '_o' if outline else ''))
    if not os.path.exists(os.path.join(d, 'id_side.png')):
        subprocess.run([BLENDER, '-b', '-P', os.path.join(HERE, 'blender_scene.py'), '--', str(seed), d] + (['outline'] if outline else []),
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    pal = {k: np.array(v) for k, v in json.load(open(os.path.join(d, 'pal.json'), encoding='utf-8')).items()}
    pid = json.load(open(os.path.join(d, 'parts.json'), encoding='utf-8'))
    names = list(pid)
    cols = np.array([pid[n] for n in names], float)
    panels, truth = [], {}
    for v in ('front', 'side'):
        a = np.array(Image.open(os.path.join(d, 'color_%s.png' % v)).convert('RGBA')).astype(float)
        al = a[..., 3:] / 255.0
        panels.append(a[..., :3] * al + pal['배경'] * (1 - al))
        idm = np.array(Image.open(os.path.join(d, 'id_%s.png' % v)).convert('RGBA')).astype(float)
        dist = np.linalg.norm(idm[..., None, :3] - cols[None, None], axis=-1)
        lab = dist.argmin(-1)
        ok = (dist.min(-1) < 40) & (idm[..., 3] > 127)
        for i, n in enumerate(names):
            m = ok & (lab == i)
            if m.any():
                z = np.zeros((H, 2 * W), bool)
                off = 0 if v == 'front' else W
                z[:, off:off + W] = m
                truth[(v, n)] = z
    img = np.concatenate(panels, 1)
    rng = np.random.default_rng(seed)
    if guide:
        img[int(GROUND - (4.8 + 0.7 - ZOFF) * PPH), ::2] = (192, 194, 196)
    img = np.clip(img + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    meta = {'px_per_H': PPH, 'ground_row_grid': GROUND + ZOFF * PPH,
            'panels': {'front': {'중심선_x': W / 2, 'x부호(화면x→캐릭터)': -1}, 'side': {'중심선_x': W + W / 2, 'x부호(화면x→캐릭터)': -1}}}
    return img, truth, pal, meta

OUT = os.path.join(HERE, 'out')
NB8 = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


def contour(blob):
    """무어 이웃 경계 추적(바깥 윤곽 한 줄, 시계 방향). 반환 [(x, y)]."""
    ys, xs = np.nonzero(blob)
    i = np.lexsort((xs, ys))[0]
    start = (int(ys[i]), int(xs[i]))
    pts, cur, back = [start], start, 6
    h, w = blob.shape
    for _ in range(blob.sum() * 4 + 10):
        found = False
        for k in range(8):
            d = (back + 1 + k) % 8
            ny, nx = cur[0] + NB8[d][0], cur[1] + NB8[d][1]
            if 0 <= ny < h and 0 <= nx < w and blob[ny, nx]:
                back = (d + 4) % 8
                cur = (ny, nx)
                found = True
                break
        if not found or cur == start:
            break
        pts.append(cur)
    return [(x + 0.5, y + 0.5) for y, x in pts]


def rough_polys(mask, rng, step=8, jitter=4.0, miss_p=0.15, miss_px=12):
    polys = []
    cc = components(mask)
    for i in np.unique(cc[cc > 0]):
        blob = cc == i
        if blob.sum() < 25:
            continue
        P = np.array(contour(blob))
        if len(P) < 6:
            continue
        P = P[::max(1, len(P) // max(6, len(P) // step))]
        c = P.mean(0)
        out = []
        miss = rng.random() < miss_p
        lo = rng.integers(0, len(P))
        for j, p in enumerate(P):
            q = p + rng.uniform(-jitter, jitter, 2)
            if miss and (j - lo) % len(P) < len(P) // 5:            # 한 구간을 안쪽으로 크게 뺀다
                v = c - q
                q = q + v / max(np.linalg.norm(v), 1e-9) * miss_px
            out.append([float(q[0]), float(q[1])])
        polys.append({'pts': out})
    return polys


def iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


def cached_render(seed, hard=False, outline=False, blender=False, hue=False, twotone=False, checker=False):
    """렌더 결과를 bench/out/cache 에 저장해 두고 다시 쓴다(개선 루프가 같은 장면을 여러 번 평가)."""
    cdir = os.path.join(OUT, 'cache')
    os.makedirs(cdir, exist_ok=True)
    f = os.path.join(cdir, '%s%s%s%s%s%s_%03d.npz' % ('bl' if blender else 'np', '_hard' if hard else '', '_o' if outline else '', '_hue' if hue else '', '_2t' if twotone else '', '_ck' if checker else '', seed))
    if os.path.exists(f):
        z = np.load(f, allow_pickle=True)
        truth = {tuple(k.split('|')): z['t_' + k] for k in z['keys']}
        return z['img'], truth, {k: np.array(v) for k, v in json.loads(str(z['pal'])).items()}, json.loads(str(z['meta']))
    if blender:
        img, truth, pal, meta = render_blender(seed, outline)
    else:
        img, truth, pal, meta = render(seed, hard_bg=hard, outline=outline, hue=hue, twotone=twotone, checker=checker)
    keys = ['%s|%s' % k for k in truth]
    np.savez_compressed(f, img=img, keys=np.array(keys), pal=json.dumps({k: list(map(float, v)) for k, v in pal.items()}),
                        meta=json.dumps(meta, ensure_ascii=False), **{'t_' + k: truth[tuple(k.split('|'))] for k in keys})
    return img, truth, pal, meta


def scene_case(seed, hard=False, tone_cut=True, extra=None, outline=False, blender=False, hue=False, twotone=False, checker=False):
    img, truth, pal, meta = cached_render(seed, hard, outline, blender, hue or twotone, twotone, checker)
    hue = hue or twotone
    rng = np.random.default_rng(1000 + seed)
    d = os.path.join(OUT, 's%02d' % seed)
    os.makedirs(d, exist_ok=True)
    np.save(os.path.join(d, 'drawing.npy'), img)
    json.dump(meta, open(os.path.join(d, 'meta.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    parts = ['머리', '뿔', '뿔 밑동', '귀', '갈기']
    rough = {'panels': {}}
    for v in ('front', 'side'):
        rough['panels'][v] = {'parts': [{'name': p, 'polys': rough_polys(truth[(v, p)], rng)} for p in parts if (v, p) in truth]}
    json.dump(rough, open(os.path.join(d, 'rough.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    tones = [0.72, 0.88, 1.06]
    S = {'drawing': 'drawing.npy', 'meta': 'meta.json', 'rough': 'rough.json',
         'boxes': {'front': [0, 300, 0, W], 'side': [0, 300, W, 2 * W]}, 'k': 12 if hue else 9,
         'groups_ref': {m: [list(np.clip(pal[m] * t, 0, 255)) for t in tones] for m in (('털', '얼굴', '뿔', '귀안') if hue else ('털', '얼굴', '뿔'))},
         'part_mats': {'머리': ['털', '얼굴'], '뿔': ['뿔'], '뿔 밑동': ['뿔'], '귀': (['털', '귀안'] if twotone else ['귀안']) if hue else ['털'], '갈기': ['털']},
         'mirror_views': ['front'], 'profile_parts': ['머리'], 'min_area': 40, 'snap_px': 8, 'out': '.', 'tone_cut': tone_cut}
    if outline:                                   # 외곽선 그림: 선 색을 '선' 재질로(LLM 이 미리보기를 보고 정하는 묶음)
        S['groups_ref']['선'] = [[38, 30, 28]]
        S['k'] += 1
    extra = dict(extra or {})
    for m in extra.pop('_drop_mats', []):          # 첫 판단에서 재질 하나를 빠뜨린 경우(들소 옆 귀 분홍): 부위 재질은 가장 가까운 남은 재질로
        if m in S['groups_ref']:
            del S['groups_ref'][m]
            near = min(S['groups_ref'], key=lambda n: np.linalg.norm(pal[n] - pal[m]))
            S['part_mats'] = {p: list(dict.fromkeys(near if x == m else x for x in ms)) for p, ms in S['part_mats'].items()}
    for p, ms in extra.pop('_part_mats_add', {}).items():
        S['part_mats'][p] = list(dict.fromkeys(S['part_mats'].get(p, []) + ms))
    S.update(extra)
    sp = os.path.join(d, 'spec.json')
    json.dump(S, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    T._CACHE.clear()
    res = T.build(S, sp, write=False)
    M = res['masks']
    score = {}
    for v in ('front', 'side'):
        def g(dct, p):
            return dct.get((v, p), np.zeros(img.shape[:2], bool))
        rp = {p: np.zeros(img.shape[:2], bool) for p in parts}
        for it in rough['panels'][v]['parts']:
            for poly in it['polys']:
                rp[it["name"]] |= fill_poly(img.shape[:2], poly["pts"])
        horn_t = g(truth, '뿔') | g(truth, '뿔 밑동')
        horn_m = g(M, '뿔') | g(M, '뿔 밑동')
        horn_r = rp['뿔'] | rp['뿔 밑동']
        score[v] = {'뿔+밑동': (iou(horn_r, horn_t), iou(horn_m, horn_t)),
                    '귀': (iou(rp['귀'], g(truth, '귀')), iou(g(M, '귀'), g(truth, '귀'))),
                    '머리': (iou(rp['머리'], g(truth, '머리')), iou(g(M, '머리'), g(truth, '머리')))}
        if (v, '갈기') in truth:
            score[v]['갈기'] = (iou(rp['갈기'], g(truth, '갈기')), iou(g(M, '갈기'), g(truth, '갈기')))
    write_png(os.path.join(OUT, 's%02d_overlay.png' % seed), overlay(img, M, {'f': (0, 300, 0, W), 's': (0, 300, W, 2 * W)}, scale=2, added=res['added']))
    return score


def main(argv):
    n = int(argv[argv.index('--n') + 1]) if '--n' in argv else 12
    s0 = int(argv[argv.index('--seed0') + 1]) if '--seed0' in argv else 0
    hard = '--hard' in argv
    tone_cut = '--no-tone' not in argv
    outline = '--outline' in argv
    blender = '--blender' in argv
    extra = json.loads(argv[argv.index('--extra') + 1]) if '--extra' in argv else {}
    tag = argv[argv.index('--tag') + 1] if '--tag' in argv else ''
    t0 = time.time()
    allres = {}
    for s in range(s0, s0 + n):
        sc = scene_case(s, hard, tone_cut, extra, outline, blender)
        allres[s] = sc
        print('BENCH s%02d' % s, ' | '.join('%s %s' % (v, ' '.join('%s %.2f→%.2f' % (k, a, b) for k, (a, b) in d.items())) for v, d in sc.items()))
    agg = {}
    for sc in allres.values():
        for v, d in sc.items():
            for k, (a, b) in d.items():
                agg.setdefault('%s|%s' % (v, k), []).append((a, b))
    summ = {k: {'거친_평균': round(float(np.mean([a for a, _ in x])), 3), '결과_평균': round(float(np.mean([b for _, b in x])), 3),
                '결과_최저': round(float(np.min([b for _, b in x])), 3), 'n': len(x)} for k, x in sorted(agg.items())}
    for k, s in summ.items():
        print('BENCH 요약 %-12s 거친 %.3f → 결과 %.3f (최저 %.3f, n=%d)' % (k, s['거친_평균'], s['결과_평균'], s['결과_최저'], s['n']))
    json.dump({'장면': {str(k): v for k, v in allres.items()}, '요약': summ, '초': round(time.time() - t0, 1)},
              open(os.path.join(OUT, 'result%s%s%s%s%s_%d_%d.json' % ('_blender' if blender else '', '_hard' if hard else '', '_outline' if outline else '', '' if tone_cut else '_notone', ('_' + tag) if tag else '', s0, n)), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main(sys.argv[1:])
