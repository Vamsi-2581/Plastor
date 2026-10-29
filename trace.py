# -*- coding: utf-8 -*-
r"""트레이싱 도구 명령줄. 도면 이미지 + LLM 거친 부위 다각형 → 정밀 부위 마스크·윤곽 표·겹침 그림.
실행(Blender 번들 python):
  python trace.py clusters --spec S.json     # 전경 색 군집 중심과 미리보기(그림을 보고 groups_ref 를 정한다)
  python trace.py build    --spec S.json     # 배경 지우기 → 군집 → 재질 → 얼룩 흡수 → 영역 선택 → 거울 → 마스크·윤곽표·그림

spec.json:
  drawing     도면 .npy (행,열,RGB)           meta   trace_meta.json (패널 중심선·x부호·px_per_H·발바닥 행)
  rough       거친 부위 다각형(분해선 형식)    boxes  {뷰: [r0, r1, c0, c1]} 관심 상자
  k           전경 군집 수                     groups_ref {재질: [[r,g,b], ...]} 군집 중심을 가장 가까운 기준색의 재질로(LLM 판단)
  cluster_mats {군집 번호: 재질} 번호 그림을 보고 LLM 이 고친 묶음(trace_review.py groups → groups_merge 가 적는다)
  part_mats   {부위: [재질...]}                mirror_views [정면·뒤처럼 좌우 대칭인 뷰]
  claim_off   ['뷰|부위'] 닫힌 덩어리 규칙 끄기(노랑이 다른 것일 때)  merge {남길 부위: [합칠 부위]}
  profile_parts [윤곽 표에 합칠 부위]          min_area 얼룩 흡수 크기(px), snap_px 영역 선택 띠 폭(px)
  out         출력 폴더
판정은 사람이 겹침 그림으로 한다. 재질 경계 지지율은 같은 지도를 쓰므로 독립 검증이 아니다.
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from harness.color_regions import background_mask, kmeans, label, to_space  # noqa: E402
from harness.render import write_png  # noqa: E402
from harness.trace import _dilate as _dilate_np, fill_poly, prune_masks, height_unsupported, absorb_lines, absorb_small, cluster_preview, open_cuts, tone_vote, symmetry_axis, overlay, profile_rows, resolve_overlaps, trace_parts_region, unsupported_cuts  # noqa: E402


def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def _rel(spec_path, p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(spec_path)), p))


AUTO_DE = 8.0      # 색차 기준(Lab 공간이면 ΔE*ab). 결과를 보기 전에 정한 값
AUTO_KMAX = 16


def fg_centers(img, boxes, k, space='rgb'):
    """전경 색 군집 중심(space 공간 값). 배경은 RGB 로 먼저 지운다."""
    X = []
    for v, (r0, r1, c0, c1) in boxes.items():
        crop = img[r0:r1, c0:c1]
        bg, _ = background_mask(crop)
        X.append(to_space(crop[~bg], space))
    X = np.concatenate(X)
    X = X[::max(1, len(X) // 40000)]
    if k != 'auto':
        return kmeans(X, k)
    # 군집 수 자동: 4개부터 늘려, 전경 픽셀 95% 가 자기 중심에서 색차 AUTO_DE 이내가 되는 가장 작은 수(최대 AUTO_KMAX).
    # 군집이 많으면 재질 묶음에서 합쳐져 해가 적고, 모자라면 다른 재질이 한 군집에 섞인다(들소 k=5: 분홍 귀가 얼굴과 섞임).
    for kk in range(4, AUTO_KMAX + 1):
        C = kmeans(X, kk)
        d = np.sqrt(((X[:, None, :] - C[None]) ** 2).sum(-1)).min(1)
        if np.percentile(d, 95) <= AUTO_DE:
            break
    fg_centers.chosen = (kk, round(float(np.percentile(d, 95)), 2))
    return C


def build_material_lut(C, groups_ref, names, space='rgb'):
    refs = [(names.index(n), to_space(np.array(c, float), space)) for n in groups_ref for c in groups_ref[n]]
    return np.array([min(refs, key=lambda r: np.linalg.norm(c - r[1]))[0] for c in C])


def _merge_regions(crop, lab, bg, refs, thresh, m_default):
    """군집 번호 지도 lab(배경 -1)의 연결 성분 → Lab 평균색 인접 그래프 → thresh 이하 이웃 계층 합치기 → 영역 평균색 최근접 기준색 재질."""
    from harness import vendor  # noqa: F401
    from skimage import graph as skg
    from skimage.measure import label as cc_label
    lab_img = to_space(crop, 'lab')
    comp = np.zeros(lab.shape, int)
    n = 0
    for j in np.unique(lab[lab >= 0]):
        cl, k = cc_label(lab == j, connectivity=1, return_num=True)
        comp[cl > 0] = cl[cl > 0] + n
        n += k
    if n == 0:
        return m_default
    rag = skg.rag_mean_color(lab_img, comp, mode='distance')
    if 0 in rag:
        rag.remove_node(0)                      # 배경(0)은 합치기에서 뺀다

    def weight(g, src, dst, n_):
        d = g.nodes[dst]['mean color'] - g.nodes[n_]['mean color']
        return {'weight': float(np.linalg.norm(d))}

    def merge(g, src, dst):
        g.nodes[dst]['total color'] += g.nodes[src]['total color']
        g.nodes[dst]['pixel count'] += g.nodes[src]['pixel count']
        g.nodes[dst]['mean color'] = g.nodes[dst]['total color'] / g.nodes[dst]['pixel count']

    out = skg.merge_hierarchical(comp, rag, thresh=thresh, rag_copy=False, in_place_merge=True, merge_func=merge, weight_func=weight)
    m = m_default.copy()
    for r in np.unique(out[~bg]):
        sel = (out == r) & ~bg
        c = lab_img[sel].mean(0)
        m[sel] = min(refs, key=lambda q: np.linalg.norm(c - q[1]))[0]
    return m


def build_material(img, boxes, C, groups_ref, min_area, space='rgb', cluster_mats=None, region_merge=None):
    """상자마다: 배경(0) + 전경 군집을 기준색(RGB 로 적고 space 로 바꿔 비교)에 가장 가까운 재질로. 상자 밖은 -1.
    cluster_mats {군집 번호: 재질}: LLM 이 번호 그림(trace_review.py groups)을 보고 고친 묶음. 기준색 최근접보다 앞선다.
    groups_ref 에 없는 재질 이름이면 새 재질로 더한다(들소 옆 귀 분홍처럼 첫 판단에서 빠진 재질).
    region_merge {'thresh': ΔE}: 군집 번호 지도의 연결 성분을 조각으로 삼아, 맞붙고 Lab 평균색 차가 thresh 이하인 이웃끼리만 합친 뒤
    합친 영역의 평균색으로 재질을 정한다(색조만 다른 이웃 면을 군집 번호 대신 위치까지 보고 가른다). 없으면 기존 동작."""
    names = ['배경'] + list(groups_ref)
    refs = [(i + 1, to_space(np.array(c, float), space)) for i, n in enumerate(groups_ref) for c in groups_ref[n]]
    lut = np.array([min(refs, key=lambda r: np.linalg.norm(c - r[1]))[0] for c in C])
    for j, mname in (cluster_mats or {}).items():
        j = int(j)
        if not 0 <= j < len(C):
            continue
        if mname not in names:
            names.append(mname)
        lut[j] = names.index(mname)
    refs_lab = [(i + 1, to_space(np.array(c, float), 'lab')) for i, n in enumerate(groups_ref) for c in groups_ref[n]] if region_merge else None
    mat = np.full(img.shape[:2], -1, int)
    tone = np.full(img.shape[:2], -1, int)
    for v, (r0, r1, c0, c1) in boxes.items():
        crop = img[r0:r1, c0:c1]
        bg, _ = background_mask(crop)
        lab = label(to_space(crop, space), C)
        tone[r0:r1, c0:c1] = np.where(bg, -1, lab)
        m = lut[lab]
        if region_merge:
            m = _merge_regions(crop, np.where(bg, -1, lab), bg, refs_lab, float(region_merge['thresh']), m)
        m[bg] = 0
        mat[r0:r1, c0:c1] = absorb_small(m, len(names), min_area)
    build_material.tone = tone
    return mat, names, {('%d' % j): names[lut[j]] for j in range(len(C))}


def main(argv):
    cmd, spec_path = argv[0], argv[argv.index('--spec') + 1]
    S = jload(spec_path)
    if cmd == 'clusters':
        img = np.load(_rel(spec_path, S['drawing']))[..., :3]
        boxes = {v: tuple(b) for v, b in S['boxes'].items()}
        out = _rel(spec_path, S['out'])
        os.makedirs(out, exist_ok=True)
        C = fg_centers(img, boxes, S['k'])
        write_png(os.path.join(out, 'clusters.png'), np.repeat(np.repeat(cluster_preview(img, C, boxes), 2, 0), 2, 1))
        print('TRACE 전경 군집(밝기순)', [list(map(int, np.round(c))) for c in C])
        return 0
    build(S, spec_path, write=True, verbose=True)
    return 0


_CACHE = {}


def build(S, spec_path, write=True, verbose=False):
    """트레이스 한 번. 반환 dict(masks, raw, added, rep, mat, names, meta, boxes, centers, img).
    trace_loop.py 가 설정을 바꿔 가며 여러 번 부른다(도면·군집은 캐시)."""
    key = (_rel(spec_path, S['drawing']), json.dumps(S['boxes']), S['k'], json.dumps(S['groups_ref'], ensure_ascii=False), S.get('min_area', 150),
           json.dumps(S.get('extra_centers', [])), S.get('color_space', 'lab'), json.dumps(S.get('cluster_mats', {}), ensure_ascii=False, sort_keys=True), json.dumps(S.get('region_merge')))
    if key not in _CACHE:
        img = np.load(_rel(spec_path, S['drawing']))[..., :3]
        boxes = {v: tuple(b) for v, b in S['boxes'].items()}
        space = S.get('color_space', 'lab')            # 기본 lab: 색조만 다른 재질 변형에서 귀 0.54→0.76, 기존 도면 영향 ≤0.002
        C = fg_centers(img, boxes, S['k'], space)
        if S.get('extra_centers'):
            # LLM 이 도면에서 짚은 색을 군집 중심으로 더한다(k-means 가 밝기 위주라 붉은 기만 다른 분홍 귀 안쪽이 얼굴과 합쳐졌다)
            C = np.vstack([C, to_space(np.array(S['extra_centers'], float), space)])
        mat, names, cmap = build_material(img, boxes, C, S['groups_ref'], S.get('min_area', 150), space, S.get('cluster_mats'), S.get('region_merge'))
        _CACHE.clear()
        _CACHE[key] = (img, boxes, C, mat, names, cmap, build_material.tone)
    img, boxes, C, mat, names, cmap, tone = _CACHE[key]
    meta = jload(_rel(spec_path, S['meta']))
    out = _rel(spec_path, S['out'])
    os.makedirs(out, exist_ok=True)
    rough0 = jload(_rel(spec_path, S['rough']))
    if S.get('local_materials'):
        # 지역 재질: {재질: 부위}. 그 재질은 부위 거친 다각형 근처(2×탐색 폭)에서만 유효하고, 밖에서는 가장 가까운 다른 재질로 돌린다.
        # 이유: 옆 귀 분홍을 따로 두자 밝은 얼굴 면까지 '귀안' 이 되어 귀 밖 1420px 중 1315px 가 엉뚱한 곳이었다
        from harness.trace import _dilate as _dl
        mat = mat.copy()
        for mname, part in S['local_materials'].items():
            if mname not in names:
                continue
            zone = np.zeros(mat.shape, bool)
            for v, pd in rough0['panels'].items():
                for it in pd['parts']:
                    if it['name'] == part:
                        for poly in it['polys']:
                            zone |= fill_poly(mat.shape, poly['pts'])
            zone = _dl(zone, 2 * S.get('snap_px', 8))
            mi = names.index(mname)
            far = (mat == mi) & ~zone
            if far.any():
                others = [j for j in range(len(C)) if build_material_lut(C, S['groups_ref'], names, S.get('color_space', 'lab'))[j] != mi]
                cl = tone[far]
                d2 = ((C[cl][:, None, :] - C[others][None, :, :]) ** 2).sum(-1)
                lut = build_material_lut(C, S['groups_ref'], names, S.get('color_space', 'lab'))
                mat[far] = lut[np.array(others)[d2.argmin(1)]]
    rough = jload(_rel(spec_path, S['rough']))
    centers = {v: float(meta['panels'][v]['중심선_x']) for v in boxes}
    axis = {}
    for v in S.get('mirror_views', []):                         # 거울 축은 실루엣에서 추정(등록 값과 차이는 보고)
        if v in boxes and S.get('axis_from_silhouette', True):
            r0, r1, c0, c1 = boxes[v]
            cx, q = symmetry_axis(mat[r0:r1, c0:c1] > 0, c0, centers[v])
            axis[v] = {'등록': centers[v], '추정': cx, '실루엣_좌우IoU': round(q, 3)}
            centers[v] = cx
    claim_off = set(S.get('claim_off', []))
    if S.get('pair_side_no_claim', False) and 'side' in boxes:      # 기본 끔: 정사영 도면에서는 정당한 덧붙임까지 막았다(옆 뿔 0.972→0.920). AI 도면의 반대편 짝은 LLM 이 결정 파일로 끈다
        # 좌우 한 쌍 부위(정면 거친 다각형이 2개 이상: 뿔·귀)는 옆 뷰에서 닫힌 덩어리 덧붙임을 끈다.
        # 옆 뷰에 붙어 보이는 같은 재질 덩어리는 흔히 반대편 짝이다(들소: 비켜 그린 반대편 뿔을 먹어 헐이 판자가 됨)
        for it in rough['panels'].get('front', {}).get('parts', []):
            if len(it['polys']) >= 2 and it['name'] in S['part_mats']:
                claim_off.add('side|%s' % it['name'])
    masks = trace_parts_region(img, mat, names, rough, S['part_mats'], list(boxes), S.get('mirror_views', []), centers,
                               d=S.get('snap_px', 8), box=boxes, claim_off=claim_off, rough_grow=S.get('rough_grow'),
                               tone=tone if S.get('tone_cut', True) else None, mirror_mode=S.get('mirror_mode', 'union'), claim_frac=S.get('claim_frac', 0.6), learn_share=S.get('learn_share', 0.2), tone_claim=S.get('tone_claim', False))
    added = {k: m for k, m in trace_parts_region.added.items()}
    raw = dict(trace_parts_region.raw)
    method = S.get('region_method', 'ours')
    # 기본: 귀는 SAM(학습 분할) + 그림 근거 우선(검증된 범위는 한 재질 귀뿐: 새 씨앗 92~103 옆 귀 0.654→0.695·정면 0.927→0.952).
    # SAM 환경(.venv_sam)이 없으면 sam_bridge 가 건너뛰고 우리 방식 그대로. 끄려면 사양에 "method_by_part": {}.
    from harness import sam_bridge as _sb
    # 한 재질만으로 좁혔다가 되돌림: 합성 두 재질 귀(씨앗 300~311)에서 SAM 옆 귀 0.695→0.821 로 예측(SAM 이 더 나쁨)이 틀렸다.
    # 들소에서 분홍만 딴 것은 아래 안전 검사(우리 방식 넓이의 sam_min_ratio 미만이면 우리 방식)로 막는다.
    # 작은 부위 규칙(사용자 "넓혀 검증"): 이름이 아니라 크기로. 모든 뷰에서 거친 다각형 넓이가 그 뷰 가장 큰 부위의 sam_small 이하면 SAM.
    # 근거: SAM 은 작은 부위(귀, 새 머리 부리 좌우 0.862→0.928)에서 낫고 큰 부위에서 졌다. 안전 검사(sam_min_ratio)는 그대로
    # 기본으로는 끔(수정_기록 43): 세 벤치마크 모두 '귀만 SAM'보다 낮았다(옆 귀 -0.035·-0.054·-0.062). 정면 귀 한 쌍을 합쳐 재면
    # 0.15 를 넘어 귀가 빠졌고, 조각 하나씩 재도 귀(최대 0.111)와 뿔(최소 0.113)이 맞닿아 크기 문턱 하나로 가를 수 없다.
    # 그래서 SAM 은 사양의 method_by_part 로 부위마다 정하고, sam_small 을 적었을 때만 이 규칙을 쓴다.
    def _small_parts(frac):
        area = {}
        for v, pd in rough0['panels'].items():
            if v not in boxes or (S.get('back_from_front') and v == 'back'):
                continue
            for it in pd['parts']:
                a_ = sum(float(fill_poly(img.shape[:2], q['pts']).sum()) for q in it['polys'])
                area.setdefault(it['name'], {})[v] = a_
        top = {v: max([d.get(v, 0) for d in area.values()] or [1]) for v in boxes}
        return [p_ for p_, d in area.items() if d and all(d[v] <= frac * top[v] for v in d)]
    _auto = {p_: 'sam' for p_ in _small_parts(S['sam_small'])} if 'sam_small' in S and os.path.exists(_sb.SAMPY) else {}
    by_part = S.get('method_by_part', _auto)
    if 'method_by_part' not in S and verbose:
        print('TRACE 작은 부위 SAM:', sorted(_auto))
    _ours_before_sam = {}               # {부위: 'grabcut'|'watershed'|'sam'} 그 부위만 기존 알고리즘(나머지는 우리 방식). 'sam' 은 귀에서만 채택
    if by_part and method == 'ours':
        from harness.trace_alt import segment
        from harness.snap_trace import mirror_half
        for alg in sorted(set(by_part.values())):
            for v, (r0, r1, c0, c1) in boxes.items():
                sub = {k: p[r0:r1, c0:c1] for k, p in trace_parts_region.polys.items() if k[0] == v}
                if v == 'back' and S.get('back_from_front'):
                    continue
                if alg == 'sam':                        # 학습 분할 모델(귀만 채택, harness/sam_bridge.py)
                    from harness import sam_bridge
                    seg = sam_bridge.segment(img[r0:r1, c0:c1], sub, [k for k in sub if by_part.get(k[1]) == 'sam'], tile=S.get('sam_tile'))
                    if sam_bridge.segment.skipped:
                        print('TRACE SAM 건너뜀:', sam_bridge.segment.skipped)
                else:
                    seg = segment(alg, img[r0:r1, c0:c1], sub, S.get('snap_px', 8))
                for k, m in seg.items():
                    if by_part.get(k[1]) != alg:
                        continue
                    full = np.zeros(img.shape[:2], bool)
                    full[r0:r1, c0:c1] = m
                    if alg == 'sam' and k in raw and full.sum() < S.get('sam_min_ratio', 0.7) * raw[k].sum():
                        # SAM 이 부위의 일부(고르게 칠한 한 영역)만 땄다고 본다(들소 두 재질 귀: 690/1066px). 우리 방식 그대로
                        print('TRACE SAM 일부만 땀 → 우리 방식 유지', k, int(full.sum()), int(raw[k].sum()))
                        _ours_before_sam[k] = True
                        continue
                    raw[k] = full
                    added.pop(k, None)
                    masks[k] = mirror_half(full, centers[v], S.get('mirror_mode', 'union')) if v in S.get('mirror_views', []) else full
    if method != 'ours':                      # 비교용: 기존 알고리즘(watershed·random_walker·grabcut)으로 바꿔 끼운다
        from harness.trace_alt import segment
        from harness.snap_trace import mirror_half
        added, raw = {}, {}
        for v, (r0, r1, c0, c1) in boxes.items():
            sub = {k: p[r0:r1, c0:c1] for k, p in trace_parts_region.polys.items() if k[0] == v}
            seg = segment(method, img[r0:r1, c0:c1], sub, S.get('snap_px', 8))
            for k, m in seg.items():
                full = np.zeros(img.shape[:2], bool)
                full[r0:r1, c0:c1] = m
                raw[k] = full
                masks[k] = mirror_half(full, centers[v], S.get('mirror_mode', 'union')) if v in S.get('mirror_views', []) else full
    # 픽셀마다 한 부위(겹침 해소) → 도면 근거 없는 컷 보고 → 사람이 정한 합치기(merge: {남길 부위: [합칠 부위...]})
    main_views = [v for v in boxes if not (S.get('back_from_front') and v == 'back')]   # 뒤는 아래에서 정면 거울로 바뀐다
    fb_raw = {k: m for k, m in masks.items() if k[0] == 'back'}
    prio = {k for k in masks if by_part.get(k[1]) == 'sam' and k not in _ours_before_sam} if S.get('sam_priority', True) else set()   # 그림 근거(SAM) 부위 우선
    masks, overlaps = resolve_overlaps({k: m for k, m in masks.items() if k[0] in main_views}, trace_parts_region.polys, main_views, priority=prio)
    # 걷어내기(자동): 가는 가시·떨어진 조각. 좌우 한 쌍 부위는 정면·뒤에서 덩어리 2개를 기대한다
    expected = {}
    for it in rough['panels'].get('front', {}).get('parts', []):
        if len(it['polys']) >= 2:
            for v in ('front', 'back'):
                expected[(v, it['name'])] = len(it['polys'])
    pruned = {}
    if S.get('prune', True):
        mv = {k: m for k, m in masks.items() if k[0] in main_views}
        mv, pruned = prune_masks(mv, expected, main_views, spur_px=S.get('prune_spur_px', 0))
        masks.update(mv)
    # LLM 추론(사람이 아니라 LLM 이 도면의 의도를 추론해 적은 결정). 도면에 근거가 없거나 뷰끼리 모순되는 곳만.
    # 형식: {'view','part','mode': 'add'|'remove','polygon': [[열,행],...],'근거': 문장}. 결과는 보라색으로 따로 표시하고 보고한다.
    inferred = {}
    for inf in S.get('inferences', []):
        k = (inf['view'], inf['part'])
        if 'copy_from' in inf:
            # 다른 뷰 윤곽 옮기기: 행 범위에서 원본 뷰 부위 폭 × ratio 를 center_col 중심으로 채운다(모양은 도면에서, 위치·비율만 LLM)
            src = masks[(inf['copy_from'], inf['part'])]
            pm = np.zeros(img.shape[:2], bool)
            for rr in range(inf['rows'][0], inf['rows'][1] + 1):
                cs = np.flatnonzero(src[rr])
                if len(cs):
                    w = (cs.max() - cs.min() + 1) * inf['ratio']
                    a, b = int(round(inf['center_col'] - w / 2)), int(round(inf['center_col'] + w / 2))
                    pm[rr, max(0, a):b + 1] = True
        else:
            pm = fill_poly(img.shape[:2], inf['polygon'])
        if inf.get('mats'):                                   # 재질 제한: 그 재질 픽셀만(경계가 도면을 따른다)
            pm &= np.isin(mat, [names.index(n) for n in inf['mats'] if n in names])
        if k not in masks:
            masks[k] = np.zeros(img.shape[:2], bool)
        if inf.get('mode', 'add') == 'add':
            new = pm & ~masks[k]
            masks[k] = masks[k] | pm
        else:
            new = pm & masks[k]
            masks[k] = masks[k] & ~pm
        inferred['%s|%s|%s' % (inf['view'], inf['part'], inf.get('mode', 'add'))] = {'픽셀': int(new.sum()), '근거': inf.get('근거', '')}
        trace_parts_region.invented.setdefault(('LLM', k), np.zeros(img.shape[:2], bool))
        trace_parts_region.invented[('LLM', k)] |= new
    # 해부 보완: LLM 이 정한 덮개 재질(수염·털 등) 밑으로 들어간 부위 윤곽을 곡선으로 잇는다(덮개 안으로만, 가정으로 보고)
    amodal_rep = {}
    for am in S.get('amodal', []):
        from harness.amodal import complete
        k = (am['view'], am['part'])
        if k not in masks:
            continue
        cov_m = np.isin(mat, [names.index(n) for n in am['cover_mats'] if n in names])
        others = np.zeros(mat.shape, bool)
        for k2, m2 in masks.items():
            if k2[0] == k[0] and k2 != k:
                others |= m2
        band = _dilate_np(masks[k], am.get('band', 25))
        cover = cov_m & band & ~masks[k] & ~others
        if am.get('rows'):                                    # 보완할 구간(행 범위)을 LLM 이 정한다(예: 턱 아래만, 볼 옆 털은 제외)
            rr = np.zeros(mat.shape[0], bool)
            rr[am['rows'][0]:am['rows'][1] + 1] = True
            cover &= rr[:, None]
        masks[k], add, info = complete(masks[k], cover)
        amodal_rep['%s|%s' % k] = dict(info, 근거=am.get('근거', ''))
        trace_parts_region.invented.setdefault(('LLM', ('해부',) + k), np.zeros(mat.shape, bool))
        trace_parts_region.invented[('LLM', ('해부',) + k)] |= add
    voted = {}
    if S.get('tone_vote', False):                  # 새 장면 12개에서 효과 0.001 이하라 기본 끔
        mv = {k: m for k, m in masks.items() if k[0] in main_views and k[0] not in S.get('mirror_views', [])}
        mv, voted = tone_vote(mv, trace_parts_region.polys, mat, tone, S['part_mats'], names, [v for v in main_views if v not in S.get('mirror_views', [])])
        masks.update(mv)
    masks.update(absorb_lines({k: m for k, m in masks.items() if k[0] in main_views}, mat, names, main_views))
    masks.update({k: m for k, m in fb_raw.items() if k[0] not in main_views})
    cuts = unsupported_cuts(masks, mat, main_views)
    half = {v: np.arange(img.shape[1]) < centers[v] for v in S.get('mirror_views', []) if v in centers}
    llm_cuts = open_cuts(masks, mat, main_views, half)
    for keep, subs in S.get('merge', {}).items():
        for v in boxes:
            for sub in subs:
                if (v, sub) in masks and (v, keep) in masks:
                    masks[(v, keep)] = masks[(v, keep)] | masks.pop((v, sub))
    # 뒤 뷰는 새로 그리지 않는다: 한 부위의 정사영은 앞에서 본 것과 뒤에서 본 것이 좌우 거울로 같다(가림만 다름).
    # 뒤 트레이스는 정면을 거울로 옮긴 것과 비교해 도면의 정면·뒤 불일치를 보고하는 데만 쓴다.
    fb = {}
    if S.get('back_from_front') and 'front' in boxes and 'back' in centers:
        cf, cb = centers['front'], centers['back']
        cols = np.arange(img.shape[1])
        src = np.round(cf - (cols + 0.5 - cb) - 0.5).astype(int)          # 뒤 열 → 같은 캐릭터 가로 위치의 정면 열
        ok = (src >= 0) & (src < img.shape[1])
        for p in list({k[1] for k in masks}):
            if ('front', p) not in masks:
                continue
            mb = np.zeros_like(masks[('front', p)])
            mb[:, cols[ok]] = masks[('front', p)][:, src[ok]]
            if ('back', p) in masks:
                t = masks[('back', p)]
                fb[p] = round(float((mb & t).sum() / max((mb | t).sum(), 1)), 3)
            masks[('back', p)] = mb
    rows = profile_rows(masks, S['profile_parts'], meta, views=tuple(boxes))
    prof = {'설명': 'trace.py 로 도면 이미지에서 만든 부위 %s 의 높이별 윤곽' % '+'.join(S['profile_parts']),
            '표본': {'h_step': 0.05}, 'rows': rows}
    rep = {'군집수': getattr(fg_centers, 'chosen', S['k']), '대칭축': axis, '거친다각형_넓힘': S.get('rough_grow', {}), '군집': [list(map(int, np.round(c))) for c in C], '군집→재질': cmap,
           '부위_픽셀': {'%s|%s' % k: int(v.sum()) for k, v in masks.items()},
           '정면_vs_뒤트레이스_IoU(도면 불일치 보고)': fb,
           '자동_덧붙임_픽셀(노랑, 사람 확인)': {'%s|%s' % k: int(m.sum()) for k, m in added.items()}, '덩어리규칙_끔': sorted(claim_off),
           '지어낸_경계_픽셀(주황, 사람 확인)': {(k if isinstance(k, str) else '%s|%s' % k): int(m.sum()) for k, m in getattr(trace_parts_region, 'invented', {}).items() if not (isinstance(k, tuple) and k[0] == 'LLM')}, 'LLM_추론': inferred, '해부_보완': amodal_rep, '걷어낸_픽셀(청록)': {'%s|%s' % k: int(m.sum()) for k, m in pruned.items()}, '높이_근거_없는_행(LLM 판단)': height_unsupported({k: m for k, m in masks.items() if k[0] in ('front', 'side')}), '부위색_배움_픽셀': dict(trace_parts_region.learned), '겹침_해소_픽셀': overlaps, '톤_투표_이동': voted, '부위_경계': cuts, 'LLM선_컷(바깥도 같은 재질)': llm_cuts, '합치기': S.get('merge', {}),
           '윤곽표_행(세 뷰 모두)': [r['h'] for r in rows if all(r.get(v + '_core') for v in boxes)]}
    res = {'masks': masks, 'raw': raw, 'added': added, 'rep': rep, 'mat': mat, 'names': names, 'meta': meta,
           'boxes': boxes, 'centers': centers, 'img': img, 'out': out}
    if write:
        np.savez_compressed(os.path.join(out, 'masks.npz'), **{'%s|%s' % k: v for k, v in masks.items()})
        with open(os.path.join(out, 'profile.json'), 'w', encoding='utf-8') as f:
            json.dump(prof, f, ensure_ascii=False, indent=1)
        inv = getattr(trace_parts_region, 'invented', {})
        write_png(os.path.join(out, 'overlay.png'), overlay(img, masks, boxes, added=added, invented={k: v for k, v in inv.items() if not (isinstance(k, tuple) and k[0] == 'LLM')}, inferred={k: v for k, v in inv.items() if isinstance(k, tuple) and k[0] == 'LLM'}, pruned=pruned))
        with open(os.path.join(out, 'report.json'), 'w', encoding='utf-8') as f:
            json.dump(rep, f, ensure_ascii=False, indent=1)
    if not verbose:
        return res
    hs = rep['윤곽표_행(세 뷰 모두)']
    print('TRACE 대칭축', axis)
    print('TRACE 정면·뒤 도면 일치(IoU)', fb)
    print('TRACE 겹침 해소', overlaps)
    print('TRACE 자동 덧붙임(노랑, 확인 필요)', {'%s|%s' % k: int(m.sum()) for k, m in added.items()})
    for k, c in cuts.items():
        if c['판정'] != '도면 근거 있음':
            print('TRACE 도면 근거 없는 컷', k, c)
    print('TRACE 완료', out, '군집→재질', cmap, '윤곽 행 %d개 h %s~%s' % (len(hs), hs[0] if hs else '-', hs[-1] if hs else '-'))
    return res


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
