r"""트레이싱 도구 자체 시험. 끝 코드 0 = PASS.
정답을 아는 합성 도면(배경·얼굴·털·뿔 두 색·귀, 뿔과 같은 색의 '뿔 밑동' 하위 부위)에 ±5px 흔든 거친 다각형을 주고 확인한다:
1. 영역 선택 결과가 정답과 IoU ≥ 0.97, 거친 다각형보다 낫다. 같은 재질 하위 부위(뿔·뿔 밑동)는 둘 사이 경계가 LLM 선이라
   그 정확도를 넘을 수 없으므로 합친 영역으로 채점하고, 하위 부위 각각은 '거친 다각형보다 낫다'만 본다
2. 겹침 해소 뒤 부위끼리 겹치는 픽셀 0
3. 같은 재질 안의 컷(뿔↔뿔 밑동)은 '도면 근거 없는 컷', 재질이 다른 경계(머리↔귀)는 '도면 근거 있음'
4. 배경 먼저 지우기: 배경색과 비슷한 밝은 뿔 끝(몸에 이어짐)은 배경이 아니다
5. 거울 붙이기 결과가 좌우 대칭
6. 사람 지적별 회귀(docs/수정_기록.md): 안내선(4), 탐색 폭보다 크게 모자란 트레이스(5), 뒤=정면 거울(6)
실행: "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" tests/selftest_trace.py
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from harness.color_regions import background_mask, kmeans, label  # noqa: E402
from harness.snap_trace import mirror_half  # noqa: E402
from harness.trace import absorb_small, claim_closed, components, fill_poly, open_cuts, region_part, resolve_overlaps, unsupported_cuts  # noqa: E402

RESULTS = []
BG, FACE, FUR, HORN_L, HORN_D, TIP = (220, 220, 222), (144, 107, 92), (89, 69, 65), (215, 191, 173), (180, 151, 136), (212, 200, 190)


def check(name, ok, detail=''):
    RESULTS.append(bool(ok))
    print('%s %s %s' % ('PASS' if ok else 'FAIL', name, detail))


def iou(a, b):
    return float((a & b).sum() / max((a | b).sum(), 1))


def scene(seed=0):
    H, W = 300, 300
    yy, xx = np.mgrid[:H, :W]
    img = np.zeros((H, W, 3), float); img[:] = BG
    body = yy > 240
    neck = (yy > 200) & (np.abs(xx - 150) < 34)
    face = ((xx - 150) / 55.0) ** 2 + ((yy - 150) / 72.0) ** 2 <= 1
    tuft = fill_poly((H, W), [(118, 100), (150, 62), (182, 100), (150, 112)])
    horn = fill_poly((H, W), [(108, 112), (70, 104), (42, 72), (36, 40), (52, 66), (80, 86), (112, 92)])
    horn |= fill_poly((H, W), [(192, 112), (230, 104), (258, 72), (264, 40), (248, 66), (220, 86), (188, 92)])
    base = horn & (np.abs(xx - 150) > 38) & (np.abs(xx - 150) < 62) & (yy > 85)             # 뿔과 같은 색의 하위 부위
    tip = horn & (yy < 52)                                                                  # 배경색에 가까운 밝은 끝
    ear = ((xx - 84) / 24.0) ** 2 + ((yy - 158) / 12.0) ** 2 <= 1
    ear |= ((xx - 216) / 24.0) ** 2 + ((yy - 158) / 12.0) ** 2 <= 1
    for m, c in ((body, FUR), (neck, FUR), (face, FACE), (tuft, FUR), (ear, FUR), (horn, HORN_L), (horn & (yy > 0.55 * np.minimum(xx, 300 - xx) + 40), HORN_D), (tip, TIP)):
        img[m] = c
    rng = np.random.default_rng(seed)
    img = np.clip(img + rng.normal(0, 2, img.shape), 0, 255).astype(np.uint8)
    truth = {'머리': (face | tuft) & ~horn & ~ear, '뿔': horn & ~base, '뿔 밑동': base, '귀': ear}
    truth['_끝'] = tip
    return img, truth, rng


def _grow(m, r):
    out = m.copy()
    for _ in range(abs(r)):
        g = out.copy() if r > 0 else out.copy()
        if r > 0:
            g[1:] |= out[:-1]; g[:-1] |= out[1:]; g[:, 1:] |= out[:, :-1]; g[:, :-1] |= out[:, 1:]
        else:
            g[1:] &= out[:-1]; g[:-1] &= out[1:]; g[:, 1:] &= out[:, :-1]; g[:, :-1] &= out[:, 1:]
        out = g
    return out


def rough_of(m, rng, cut=None):
    """LLM 거친 트레이스 흉내: 정답을 ±3px 옮기고, 경계를 구역마다 ±4px 넓히거나 줄인다.
    cut=(행 범위) 를 주면 그 행들에서 정답의 왼쪽 가장자리 12px 를 뺀다(지적 5: 한쪽 가장자리가 탐색 폭보다 크게 모자란 트레이스)."""
    dy, dx = rng.integers(-3, 4, 2)
    r = np.roll(np.roll(m, dy, 0), dx, 1)
    grown, shrunk = _grow(r, 4), _grow(r, -4)
    pick = rng.random((m.shape[0] // 20 + 1, m.shape[1] // 20 + 1))
    pick = np.repeat(np.repeat(pick, 20, 0), 20, 1)[:m.shape[0], :m.shape[1]]
    out = np.where(pick < 0.33, shrunk, np.where(pick > 0.66, grown, r))
    if cut is not None:
        for r in range(cut[0], cut[1]):
            left = m[r] & ~np.roll(m[r], 12)                    # 각 구간의 왼쪽 12px
            out[r] &= ~left
    return out


def main():
    img, truth, rng = scene()
    tip_truth = truth.pop('_끝')                      # 그린 모양 그대로(색으로 고르면 배경이 섞인다)
    bg, _ = background_mask(img)
    check('배경 먼저: 배경색에 가까운 뿔 끝은 배경이 아니다', tip_truth.sum() > 20 and not (bg & tip_truth).any(), '끝 %d px 중 배경 %d' % (tip_truth.sum(), (bg & tip_truth).sum()))

    fg = img[~bg].astype(float)
    C = kmeans(fg[::3], 5)
    ref = {'뿔': [HORN_L, HORN_D, TIP], '얼굴': [FACE], '털': [FUR]}
    names = ['배경'] + list(ref)
    refs = [(i + 1, np.array(c, float)) for i, n in enumerate(ref) for c in ref[n]]
    lut = np.array([min(refs, key=lambda r: np.linalg.norm(c - r[1]))[0] for c in C])
    mat = lut[label(img, C)]
    mat[bg] = 0
    mat = absorb_small(mat, len(names), 60)
    part_mats = {'머리': ['얼굴', '털'], '뿔': ['뿔'], '뿔 밑동': ['뿔'], '귀': ['털']}
    masks, polys, rough_iou = {}, {}, {}
    for p, t in truth.items():
        pm = rough_of(t, rng)
        polys[('front', p)] = pm
        rough_iou[p] = iou(pm, t)
    claims = claim_closed(mat, polys, part_mats, names)
    for p in truth:
        masks[('front', p)] = region_part(mat, [names.index(n) for n in part_mats[p]], polys[('front', p)], 8, claims[('front', p)])
    masks, ov = resolve_overlaps(masks, polys, ['front'])
    res = {p: iou(masks[('front', p)], truth[p]) for p in truth}
    # 머리↔목은 같은 털이 이어져 도면이 끝을 정해 주지 않는다(LLM 선이 컷). 그 구역(몸통과 이어진 털 덩어리)은 빼고 채점한다
    fur = mat == names.index('털')
    cc = components(fur)
    neck = np.isin(cc, np.unique(cc[fur & (np.mgrid[:300, :300][0] > 250)]))
    head_iou = iou(masks[('front', '머리')] & ~neck, truth['머리'] & ~neck)
    scored = {'머리(목 컷 제외)': head_iou, '귀': res['귀'],
              '뿔+뿔 밑동': iou(masks[('front', '뿔')] | masks[('front', '뿔 밑동')], truth['뿔'] | truth['뿔 밑동'])}
    check('영역 선택 IoU ≥ 0.97 (도면 경계로 정해지는 영역)', min(scored.values()) >= 0.97, ' '.join('%s %.3f' % kv for kv in scored.items()))
    check('거친 다각형보다 낫다', all(res[p] > rough_iou[p] for p in truth), ' '.join('%s %.3f→%.3f' % (p, rough_iou[p], res[p]) for p in truth))
    keys = list(masks)
    over = sum(int((masks[a] & masks[b]).sum()) for i, a in enumerate(keys) for b in keys[i + 1:])
    check('겹침 해소 뒤 부위끼리 겹침 0', over == 0, '해소 전 겹침 %s' % ov)
    cuts = unsupported_cuts(masks, mat, ['front'])
    hb = cuts.get('front|뿔↔뿔 밑동', {}).get('판정')
    he = cuts.get('front|머리↔귀', {}).get('판정')
    oc = open_cuts(masks, mat, ['front'])
    check('LLM 선 컷 보고: 머리(목과 이어짐)에는 있고, 닫힌 귀에는 거의 없다', oc['front|머리']['LLM컷_픽셀'] > 10 and oc['front|귀']['LLM컷_비율'] < 0.05,
          '머리 %s / 귀 %s' % (oc['front|머리'], oc['front|귀']))
    check('같은 재질 컷(뿔↔뿔 밑동)은 도면 근거 없음, 재질 경계(머리↔귀)는 근거 있음', hb == '도면 근거 없는 컷(LLM 선)' and he == '도면 근거 있음', '뿔↔밑동 %s / 머리↔귀 %s' % (hb, he))
    # 지적 5: 한쪽이 탐색 폭(8px)보다 크게(12px) 모자란 트레이스도 재질 덩어리가 닫혀 있으면 되찾는다
    horn_all = truth['뿔'] | truth['뿔 밑동']
    short = rough_of(horn_all, rng, cut=(85, 115))
    cl = claim_closed(mat, {('front', '뿔'): short}, {'뿔': ['뿔']}, names)
    got = region_part(mat, [names.index('뿔')], short, 8, cl[('front', '뿔')])
    check('지적5: 탐색 폭보다 크게 모자란 트레이스도 닫힌 재질 덩어리는 되찾는다', iou(got, horn_all) >= 0.97 and iou(short, horn_all) < 0.9,
          '거친 %.3f → 결과 %.3f' % (iou(short, horn_all), iou(got, horn_all)))
    # 지적 4: 배경과 다른 회색 점선 안내선(행 전체)은 배경, 그 행을 지나는 뿔은 전경
    img2 = img.copy()
    img2[60:62, ::2] = (192, 194, 196)
    bg2, _ = background_mask(img2)
    line = np.zeros(bg2.shape, bool); line[60:62, ::2] = True
    on_horn = line & horn_all
    check('지적4: 회색 안내선은 배경, 안내선이 지나는 뿔은 배경 아님', (bg2 & line & ~horn_all).mean() > 0 and (bg2[line & ~horn_all]).mean() > 0.95 and not (bg2 & horn_all & ~line).any(),
          '안내선 배경 비율 %.2f, 뿔(안내선 밖) 배경 %d px' % ((bg2[line & ~horn_all]).mean(), (bg2 & horn_all & ~line).sum()))
    # 지적 6: 뒤 뷰는 정면 거울(trace.py back_from_front 와 같은 식)
    cf, cb = 150.0, 450.0
    front = np.zeros((300, 600), bool); front[:, :300] = masks[('front', '뿔')]
    cols = np.arange(600); src = np.round(cf - (cols + 0.5 - cb) - 0.5).astype(int); ok = (src >= 0) & (src < 600)
    back = np.zeros_like(front); back[:, cols[ok]] = front[:, src[ok]]
    check('지적6: 뒤 = 정면을 중심선 기준 좌우 거울로 옮긴 것', np.array_equal(back[:, 300:][:, ::-1], front[:, :300][:, ::-1][:, ::-1][:, ::-1]) or np.array_equal(back[:, 300:], front[:, :300][:, ::-1]))
    # 지적 16(벤치마크 씨앗 66): 재질 묶음이 틀려도(뿔 그림자 색을 '얼굴'로) 부위 색 배우기로 되찾는다
    from harness.trace import trace_parts_region
    sys.path.insert(0, os.path.join(ROOT, 'bench'))
    from run import contour
    bad_lut = lut.copy()
    j_dark = int(np.argmin([np.linalg.norm(c - np.array(HORN_D)) for c in C]))
    bad_lut[j_dark] = names.index('얼굴')
    tone = label(img, C); tone[bg] = -1
    mat_bad = bad_lut[tone.clip(0)]; mat_bad[bg] = 0
    rough = {'panels': {'front': {'parts': [{'name': '뿔', 'polys': [{'pts': contour(c)} for c in [components(horn_all) == i for i in (1, 2)]]}]}}}
    res = {}
    for ls in (None, 0.2):
        mm = trace_parts_region(img, mat_bad, names, rough, {'뿔': ['뿔']}, ['front'], [], {'front': 150.0}, d=8, tone=tone, learn_share=ls)
        res[ls] = iou(mm[('front', '뿔')], horn_all)
    check('지적16: 재질 묶음이 틀려도 부위 색 배우기로 되찾는다', res[0.2] >= 0.97 and res[None] < 0.9, '끔 %.3f → 켬 %.3f' % (res[None], res[0.2]))
    # 모델링 회귀(들소 10차): 같은 재질 하위 부위를 합친 비주얼 헐은 두 뷰 실루엣과 맞는다, 한 뷰 높이 확장은 가정으로 보고된다
    sys.path.insert(0, os.path.join(ROOT, 'fixtures', 'bison_head'))
    import fitloop
    from harness.hull import build_hull
    from harness.pack import Pack
    pk = Pack(os.path.join(ROOT, 'packs', 'head_traced', 'pack.json'))
    MB = dict(np.load(os.path.join(ROOT, 'fixtures', 'bison_head', 'trace', 'out', 'masks.npz')))
    z0 = np.zeros_like(MB['front|뿔'])
    hf, hs = MB['front|뿔'] | MB.get('front|뿔 밑동', z0), MB['side|뿔'] | MB.get('side|뿔 밑동', z0)
    Vh, Fh, _ = build_hull(pk, hf, hs)
    fr = {'H_bu': 0.598, 'px_per_H': pk.ppH, 'ground_row': pk.ground, 'shape': [1024, 1536], 'xc': {v: float(pk.panels[v]['center_x']) for v in ('front', 'side')}}
    fitloop.set_frame(fr)
    MM = fitloop.masks_of(Vh * 0.598, Fh, fr, ['front', 'side'])
    hi = {'front': iou(MM['front'], hf), 'side': iou(MM['side'], hs)}
    check('모델링: 뿔+밑동 헐이 정면·옆 실루엣과 IoU ≥ 0.95', min(hi.values()) >= 0.95, '정면 %.3f 옆 %.3f' % (hi['front'], hi['side']))
    check('모델링: 한 뷰에만 있는 높이는 가정으로 보고된다', len(pk.assumed) > 0 and all(v in ('front', 'side', 'back') for _, v in pk.assumed), '%d개' % len(pk.assumed))
    # 걷어내기(사용자 지적: 불필요한 트레이스를 걷어내는 능력): 떨어진 작은 조각은 빼고, 좌우 한 쌍은 두 덩어리를 남기고,
    # 가시 옵션은 1px 실을 빼되 뿔 끝처럼 가는 끝은 남긴다
    from harness.trace import prune_masks
    base = masks[('front', '뿔')].copy()
    junk = base.copy(); junk[20:24, 20:24] = True                       # 떨어진 작은 조각(16px)
    junk[150:151, 5:40] = True                                          # 1px 실(본체와 떨어진 곳에 둔 가시)
    pm2, rm2 = prune_masks({('front', '뿔'): junk, ('front', '뿔 밑동'): masks[('front', '뿔 밑동')]}, {('front', '뿔'): 2}, ['front'], spur_px=0)   # 기본 설정, 이웃 부위 함께
    kept = pm2[('front', '뿔')]
    check('걷어내기: 작은 조각·1px 실은 빼고 좌우 두 뿔은 남긴다', not kept[20:24, 20:24].any() and not kept[150, 5:40].any() and iou(kept, base) > 0.98,
          '본체 IoU %.3f, 걷어낸 %d px' % (iou(kept, base), int(rm2.get(('front', '뿔'), np.zeros(1)).sum())))
    tip_rows = np.flatnonzero(base.any(1))[:6]
    check('걷어내기: 뿔 끝(가는 끝 6행)은 남는다', kept[tip_rows].sum() >= 0.8 * base[tip_rows].sum(), '%d/%d' % (kept[tip_rows].sum(), base[tip_rows].sum()))
    # 해부 보완(사용자 지적: 수염을 피하지 말고 그 밑 턱을 메워야): 덮개 밑으로 들어간 윤곽을 곡선으로 이어 정답에 가까워진다
    from harness.amodal import complete
    yy2, xx2 = np.mgrid[:200, :200]
    jaw = (((xx2 - 100) / 70.) ** 2 + ((yy2 - 90) / 50.) ** 2 <= 1) & (yy2 < 130) | (((xx2 - 70) / 40.) ** 2 + ((yy2 - 125) / 20.) ** 2 <= 1)
    beard = ((xx2 - 80) / 35.) ** 2 + ((yy2 - 150) / 30.) ** 2 <= 1
    vis = jaw & ~beard
    done, add, info = complete(vis, beard & ~vis)
    check('해부 보완: 수염 밑 턱을 곡선으로 메워 정답에 가까워진다', iou(done, jaw) > iou(vis, jaw) + 0.04 and not (add & ~beard).any(),
          '보이는 것 %.3f → 보완 %.3f, 덮개 밖 추가 %d px' % (iou(vis, jaw), iou(done, jaw), int((add & ~beard).sum())))
    m = mirror_half(masks[('front', '뿔')], 150.0, 'left')
    check('거울 붙이기는 좌우 대칭', np.array_equal(m, m[:, ::-1]))
    # 재질 묶음 검토(Set-of-Mark): 두 답이 같으면 바꾸고, 보기 순서를 바꾸자 답이 달라진 번호는 UNKNOWN 으로 기본 유지
    from harness.groups_review import merge_new
    cm, add, info = merge_new({'new': [3, 5], 'part': '귀'}, {'new': [3], 'part': '귀'})
    cm2, add2, _ = merge_new({'new': [3], 'part': '귀'}, {'new': [3], 'part': '머리'})
    check('빠진 재질 찾기: 두 답이 같은 번호·부위만 새 재질, 엇갈린 번호는 UNKNOWN', cm == {'3': '새재질'} and add == {'귀': ['새재질']} and info['엇갈림_UNKNOWN'] == [5] and cm2 == {} and add2 == {},
          '%s %s %s' % (cm, add, info))
    import trace as TR
    im = np.zeros((20, 40, 3), np.uint8); im[:] = (218, 218, 220); im[5:15, 5:15] = (150, 110, 95); im[5:15, 20:30] = (175, 96, 87)
    Cc = np.array([[175., 96, 87], [150, 110, 95]])
    mt, nm, cmp_ = TR.build_material(im, {'f': (0, 20, 0, 40)}, Cc, {'얼굴': [[150, 110, 95]], '털': [[90, 70, 65]]}, 1, 'rgb', {'0': '귀안'})
    check('묶음 검토: cluster_mats 로 새 재질이 생기고 그 군집 픽셀이 새 재질', '귀안' in nm and (mt[5:15, 20:30] == nm.index('귀안')).all() and (mt[5:15, 5:15] == nm.index('얼굴')).all(), str(cmp_))

    bad = RESULTS.count(False)
    print('\n자체 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
