# -*- coding: utf-8 -*-
"""트레이싱 도구: LLM 이 그린 거친 부위 다각형을 도면 이미지의 재질 경계에 붙여 정밀한 부위 마스크와 윤곽 표를 만든다.

역할 분담
- LLM(또는 사람): 부위 이름과 대략의 다각형(분해선 형식), 색 군집 중 어느 것이 같은 재질인지(groups).
- 이 도구: 색 군집, 재질 지도, 작은 얼룩 흡수(코·눈 같은 구멍), 경계 스냅, 대칭 뷰 거울 붙이기, 마스크·윤곽 표.

순서 (trace.py 명령줄이 이 순서로 부른다)
1. clusters: 관심 상자 안 색을 k 개로 군집 → 중심값 저장 + 번호 붙은 미리보기(사람·LLM 이 보고 groups 를 정한다)
2. build: groups 로 재질 지도 → 작은 얼룩 흡수 → 재질 경계 지도 → 부위 다각형 스냅 → 대칭 뷰는 한쪽 절반 거울 → 부위 마스크
   → 높이별 윤곽 표(*_core, pack 이 읽는 형식) → 겹침 그림. 판정은 사람이 그림으로 한다(재질 경계 지지율은 같은 지도를 쓰므로 독립 검증이 아니다).
"""
import json
import os

import numpy as np

from .vendor import ndi
from .color_regions import boundary, kmeans, label
from .snap_trace import densify, mirror_half, snap, support


# ------------------------------------------------------------ 연결 성분 (scipy 없음: 두 번 훑기 + 합집합-찾기)
def components(mask):
    """4-이웃 연결 성분 번호(0 = 바깥). scipy 가 있으면 ndimage.label(같은 4-이웃), 없으면 손으로 짠 두 번 훑기."""
    if ndi is not None:
        return ndi.label(mask)[0]
    return _components_py(mask)


def _components_py(mask):
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    parent = [0]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    nxt = 1
    for y in range(h):
        row, up = mask[y], (mask[y - 1] if y else None)
        for x in range(w):
            if not row[x]:
                continue
            l = lab[y, x - 1] if x and row[x - 1] else 0
            u = lab[y - 1, x] if y and up[x] else 0
            if l and u:
                a, b = find(l), find(u)
                lab[y, x] = min(a, b)
                parent[max(a, b)] = min(a, b)
            elif l or u:
                lab[y, x] = l or u
            else:
                parent.append(nxt)
                lab[y, x] = nxt
                nxt += 1
    roots = np.array([find(i) for i in range(nxt)], np.int32)
    return roots[lab]


def absorb_small(mat, n, min_area):
    """재질 지도에서 min_area 픽셀보다 작은 덩어리(코·눈·얼룩)를 둘레에서 가장 많은 재질로 바꾼다."""
    out = mat.copy()
    for m in range(n):
        cc = components(out == m)
        ids, cnt = np.unique(cc[cc > 0], return_counts=True)
        for i, c in zip(ids, cnt):
            if c >= min_area:
                continue
            blob = cc == i
            ring = np.zeros_like(blob)
            ring[1:] |= blob[:-1]; ring[:-1] |= blob[1:]; ring[:, 1:] |= blob[:, :-1]; ring[:, :-1] |= blob[:, 1:]
            ring &= ~blob
            vals = out[ring]
            vals = vals[vals != m]
            if len(vals):
                out[blob] = np.bincount(vals, minlength=n).argmax()
    return out


# ------------------------------------------------------------ 1단계: 군집
def crop_pixels(img, boxes):
    return np.concatenate([img[r0:r1, c0:c1, :3].reshape(-1, 3) for r0, r1, c0, c1 in boxes.values()]).astype(float)


def clusters(img, boxes, k, sub=7):
    return kmeans(crop_pixels(img, boxes)[::sub], k)


def cluster_preview(img, C, boxes, sw=24):
    """상자마다 군집 번호 색으로 칠한 그림 + 아래에 번호 순서 견본 띠(왼쪽부터 0,1,2...)."""
    pal = np.array([[230, 230, 230], [250, 210, 120], [200, 120, 70], [120, 160, 220],
                    [200, 60, 60], [60, 160, 90], [150, 90, 200], [40, 40, 40], [240, 150, 200], [120, 120, 40]], np.uint8)
    tiles = []
    for r0, r1, c0, c1 in boxes.values():
        lab = label(img[r0:r1, c0:c1], C)
        tiles.append(pal[lab % len(pal)])
    H = max(t.shape[0] for t in tiles)
    row = np.concatenate([np.pad(t, ((0, H - t.shape[0]), (0, 6), (0, 0)), constant_values=255) for t in tiles], 1)
    strip = np.full((sw * 2, row.shape[1], 3), 255, np.uint8)
    for j, c in enumerate(C):
        strip[:sw, j * sw * 2:j * sw * 2 + sw] = pal[j % len(pal)]          # 번호 색
        strip[sw:, j * sw * 2:j * sw * 2 + sw] = np.clip(c, 0, 255)          # 실제 평균색
    return np.concatenate([row, strip], 0)


# ------------------------------------------------------------ 2단계: 재질 지도와 부위 마스크
def material(img, C, groups, boxes, min_area):
    """상자 안만 재질을 정한다(상자 밖은 -1). groups: {재질: [군집번호]}."""
    names = list(groups)
    lut = np.full(len(C), -1, int)
    for i, nm in enumerate(names):
        for c in groups[nm]:
            lut[c] = i
    if (lut < 0).any():
        raise ValueError('groups 에 빠진 군집 번호: %s' % np.flatnonzero(lut < 0).tolist())
    mat = np.full(img.shape[:2], -1, int)
    for r0, r1, c0, c1 in boxes.values():
        m = lut[label(img[r0:r1, c0:c1], C)]
        mat[r0:r1, c0:c1] = absorb_small(m, len(names), min_area)
    return mat, names


def fill_poly(shape, pts):
    """짝-홀 규칙 행 스캔(ref_trace_common.fill_poly 와 같은 규약: 픽셀 중심 y+0.5)."""
    m = np.zeros(shape, bool)
    P = np.asarray(pts, float)
    H, W = shape
    y0, y1 = max(0, int(np.floor(P[:, 1].min()))), min(H - 1, int(np.ceil(P[:, 1].max())))
    A, B = P, np.roll(P, -1, 0)
    for y in range(y0, y1 + 1):
        yc = y + 0.5
        s = ((A[:, 1] <= yc) & (yc < B[:, 1])) | ((B[:, 1] <= yc) & (yc < A[:, 1]))
        if not s.any():
            continue
        xs = np.sort(A[s, 0] + (yc - A[s, 1]) * (B[s, 0] - A[s, 0]) / (B[s, 1] - A[s, 1]))
        for xa, xb in zip(xs[0::2], xs[1::2]):
            c0, c1 = max(0, int(np.ceil(xa - 0.5))), min(W - 1, int(np.floor(xb - 0.5)))
            if c1 >= c0:
                m[y, c0:c1 + 1] = True
    return m


def trace_parts(img, mat, rough, parts, views, mirror_views, centers):
    """rough: 분해선 형식 {'panels': {view: {'parts': [{'name','polys':[{'pts'}]}]}}}.
    반환: masks[(view, part)] (bool), report[(view, part)] = 스냅 전후 재질 경계 지지율, 컷 비율."""
    E = boundary(np.where(mat < 0, 0, mat))
    E[mat < 0] = 0
    masks, rep = {}, {}
    for v in views:
        for it in rough['panels'][v]['parts']:
            if it['name'] not in parts:
                continue
            m = np.zeros(img.shape[:2], bool)
            r = []
            for poly in it['polys']:
                P0 = densify(poly['pts'])
                P1, cut = snap(E, poly['pts'])
                m |= fill_poly(m.shape, P1)
                r.append({'전': round(support(E, P0), 3), '후': round(support(E, P1), 3), '컷': round(float(cut.mean()), 3)})
            if v in mirror_views:
                m = mirror_half(m, centers[v], 'left')
            masks[(v, it['name'])] = m
            rep['%s|%s' % (v, it['name'])] = r
    return masks, rep


def _dilate(m, r):
    if ndi is not None and r > 0:
        return ndi.binary_dilation(m, iterations=r)          # 기본 구조 = 4-이웃 십자(손 구현과 같음)
    out = m.copy()
    for _ in range(r):
        g = out.copy()
        g[1:] |= out[:-1]; g[:-1] |= out[1:]; g[:, 1:] |= out[:, :-1]; g[:, :-1] |= out[:, 1:]
        out = g
    return out


def fill_holes(m):
    """바깥과 이어지지 않은 빈 곳을 채운다(코·눈 구멍)."""
    if ndi is not None:
        return ndi.binary_fill_holes(m)
    pad = np.pad(~m, 1, constant_values=True)
    cc = components(pad)
    outside = cc == cc[0, 0]
    return m | ~outside[1:-1, 1:-1]


def claim_closed(mat, polys, part_mats, names, frac=0.6, tone=None):
    """닫힌 재질 덩어리 배정. 재질마다 연결 덩어리를 보고, 그 재질을 쓰는 부위들의 다각형이 함께 덩어리의 frac 이상을 덮으면
    덩어리 전체를 가장 많이 덮은 부위 하나에 준다(같은 재질 하위 부위는 띠 규칙으로 자기 다각형 안을 갖고, 나누기는 resolve_overlaps).
    (처음엔 걸친 부위 모두에게 줬더니 머리 다각형이 귀 덩어리를 가져갔다)
    이유: LLM 선이 탐색 폭보다 크게 빗나가도 재질 경계로 닫힌 부위(뿔·귀·볏)는 통째로 되찾아야 한다(지적 5).
    목털·갈기처럼 다각형이 일부만 덮는 큰 덩어리는 걸리지 않고, 그런 곳은 region_part 의 띠 규칙(LLM 선이 컷)으로 간다."""
    claims = {k: np.zeros(mat.shape, bool) for k in polys}
    for mi, mname in enumerate(names):
        users = [k for k in polys if mname in part_mats.get(k[1], [])]
        if not users:
            continue
        union = np.zeros(mat.shape, bool)
        for k in users:
            union |= polys[k]
        cc = components(mat == mi)
        for i in np.unique(cc[(cc > 0) & union]):
            blob = cc == i
            if (blob & union).sum() >= frac * blob.sum():
                owner = max(users, key=lambda k: int((blob & polys[k]).sum()))
                claims[owner] |= blob
        if tone is not None:
            # 톤 단위로도: 같은 재질이라도 다른 톤으로 둘러싸여 닫힌 조각(분홍 귀 안쪽이 볼과 같은 '얼굴' 재질로 묶인 경우)을 배정한다
            taken = np.zeros(mat.shape, bool)
            for k in users:
                taken |= claims[k]
            tp = _tone_pieces((mat == mi) & (tone >= 0) & ~taken, tone)
            for i in np.unique(tp[(tp > 0) & union]):
                blob = tp == i
                if blob.sum() < 30:
                    continue
                if (blob & union).sum() >= frac * blob.sum():
                    owner = max(users, key=lambda k: int((blob & polys[k]).sum()))
                    claims[owner] |= blob
    return claims


def _tone_pieces(sel, tone):
    """sel 안을 톤(군집 번호)이 같은 픽셀끼리만 이은 연결 덩어리 번호."""
    out = np.zeros(sel.shape, np.int64)
    base = 0
    for t in np.unique(tone[sel]):
        cc = components(sel & (tone == t))
        nz = cc > 0
        out[nz] = cc[nz] + base
        base = out.max()
    return out


def region_part(mat, mats, poly_mask, d, claimed=None, tone=None):
    """영역 선택(Potrace·VTracer 처럼 경계를 점이 아닌 영역에서 얻는다).
    claimed(claim_closed 결과)는 통째로 넣는다. 나머지 후보 = 부위 재질 ∩ (LLM 다각형을 d px 넓힌 곳):
    - 다각형 안의 후보는 모두 넣는다.
    - 다각형 밖 띠의 후보 중 띠 바깥 가장자리까지 이어지는 것은 뺀다(같은 재질이 계속 밖으로 감 → LLM 선이 컷).
      이어지지 않는 주머니는 넣는다(재질 경계로 닫힘)."""
    D = _dilate(poly_mask, d)
    rim = D & _dilate(~D, 1)
    out = np.zeros_like(poly_mask) if claimed is None else claimed.copy()
    for mt in mats:
        cand = (mat == mt) & D & ~out
        band = cand & ~poly_mask
        cc = components(band)
        leak = set(np.unique(cc[rim & band]).tolist()) - {0}
        keep = band & ~np.isin(cc, list(leak)) if leak else band
        inside = cand & poly_mask
        if tone is not None and leak:
            # 같은 재질이 밖으로 이어지는 컷은 LLM 선 대신 근처(±d)의 톤 경계로 옮긴다.
            # 셀 셰이딩에서 앞 물체가 뒤 물체를 가리는 곳은 톤이 바뀐다(가림 윤곽). 재질로 합치면 이 선을 잃는다.
            leaky = band & np.isin(cc, list(leak))
            tp = _tone_pieces(leaky, tone)
            back_in = leaky & ~np.isin(tp, np.unique(tp[rim & leaky]))      # 톤으로 보면 밖까지 안 이어지는 조각 → 넣는다
            keep |= back_in
            deep = poly_mask & ~_dilate(~poly_mask, d)                       # 다각형 깊은 안쪽
            edge_in = inside & ~deep
            ti = _tone_pieces(edge_in | (leaky & ~back_in), tone)
            out_ids = set(np.unique(ti[leaky & ~back_in]).tolist()) - {0}
            in_ids = set(np.unique(ti[edge_in & _dilate(deep, 1)]).tolist()) - {0}
            drop = edge_in & np.isin(ti, list(out_ids - in_ids))             # 안쪽 가장자리인데 톤이 밖과만 이어짐 → 뺀다
            # 가는 부위(폭이 2d 보다 좁아 깊은 안쪽이 거의 없음)는 빼지 않는다: 부위 전체가 '가장자리'라 통째로 지워졌다(옆 귀 0.50→0.12)
            if deep.sum() >= 0.3 * poly_mask.sum():
                inside = inside & ~drop
        out |= inside | keep
    return fill_holes(out)


def trace_parts_region(img, mat, names, rough, part_mats, views, mirror_views, centers, d=8, box=None, claim_off=(), rough_grow=None, tone=None, mirror_mode='left', claim_frac=0.6, learn_share=None, tone_claim=False):
    """part_mats: {부위: [재질이름...]}. 반환 masks[(view, part)] (겹침 해소 전). 다각형은 trace_parts_region.polys,
    닫힌 덩어리 규칙이 다각형 밖에 덧붙인 영역은 trace_parts_region.added 에 남긴다(사람 확인용, 겹침 그림에 노랑).
    claim_off: ['뷰|부위', ...] 덩어리 규칙을 끈다. 덧붙인 영역이 이름 없는 다른 것(옆 뷰의 반대편 뿔 등)일 때 사람이 정한다.
    (덮는 비율로는 '선이 가장자리를 놓침'(정면 뿔 0.884)과 '다른 것이 붙음'(옆 뿔 0.902)을 가를 수 없었다)"""
    polys = {}
    trace_parts_region.invented = {}
    for v in views:
        for it in rough['panels'][v]['parts']:
            if it['name'] not in part_mats:
                continue
            pm = np.zeros(img.shape[:2], bool)
            for poly in it['polys']:
                pm |= fill_poly(pm.shape, poly['pts'])
            key = '%s|%s' % (v, it['name'])
            if rough_grow and key in rough_grow:
                rg = rough_grow[key]
                for r in (rg if rg and isinstance(rg[0], list) else [rg]):
                    strict = not (len(r) > 2 and r[2] == '제안')
                    pm = grow_rows(pm, mat, [names.index(n) for n in part_mats[it['name']]], tuple(r[:2]), tone=tone, strict=strict)
                    if grow_rows.invented.any():
                        trace_parts_region.invented[key] = trace_parts_region.invented.get(key, np.zeros_like(pm)) | grow_rows.invented
            polys[(v, it['name'])] = pm
    trace_parts_region.polys = polys
    trace_parts_region.added = {}
    trace_parts_region.raw = {}                               # 거울 붙이기 전(좌우 일관성 검사용)
    trace_parts_region.learned = {}                           # 부위 색 배우기로 재질을 바꾼 픽셀 수
    masks = {}
    for v in views:
        r0, r1, c0, c1 = box[v] if box is not None else (0, img.shape[0], 0, img.shape[1])
        sub_polys = {k: p[r0:r1, c0:c1] for k, p in polys.items() if k[0] == v}
        claims = claim_closed(mat[r0:r1, c0:c1], sub_polys, part_mats, names, frac=claim_frac,
                              tone=None if (tone is None or not tone_claim) else tone[r0:r1, c0:c1])
        for k, pm in sub_polys.items():
            mats = [names.index(n) for n in part_mats[k[1]]]
            cl = None if '%s|%s' % k in claim_off else claims[k]
            mloc = mat[r0:r1, c0:c1]
            tloc = None if tone is None else tone[r0:r1, c0:c1]
            if learn_share and tloc is not None:
                # 부위 색 배우기: 다각형 깊은 안쪽(d 깎음, 다른 부위 다각형 제외)에서 learn_share 이상을 차지하는 색 군집은
                # 전역 재질 묶음과 상관없이 이 부위 근처(2d)에서는 부위 재질로 본다.
                # 이유: 털 밝은 톤과 얼굴 어두운 톤이 겹친 장면에서 갈기가 '얼굴'로 분류돼 통째로 빠졌다(씨앗 66, 0.78→0.17).
                others = np.zeros_like(pm)
                for k2, p2 in sub_polys.items():
                    if k2 != k:
                        others |= p2
                core = pm & ~_dilate(~pm, d) & ~others
                if core.sum() < 30:                              # 작은 부위(옆 귀 등)는 2px 만 깎는다(씨앗 94: 깊은 안쪽이 비어 규칙이 꺼짐)
                    core = pm & ~_dilate(~pm, 2) & ~others
                if core.sum() >= 30:
                    ids, cnt = np.unique(tloc[core & (tloc >= 0)], return_counts=True)
                    learned = [int(i) for i, c in zip(ids, cnt) if c >= learn_share * core.sum()]
                    zone = _dilate(pm, 2 * d) & np.isin(tloc, learned) & ~np.isin(mloc, mats) & (mloc > 0)
                    if zone.any():
                        mloc = mloc.copy()
                        mloc[zone] = mats[0]
                        trace_parts_region.learned['%s|%s' % k] = int(zone.sum())
            m = np.zeros(img.shape[:2], bool)
            m[r0:r1, c0:c1] = region_part(mloc, mats, pm, d, cl, tloc)
            if cl is not None:
                add = np.zeros(img.shape[:2], bool)
                add[r0:r1, c0:c1] = cl & ~_dilate(pm, d)          # 다각형+탐색 폭 밖에서 덩어리 규칙으로만 들어온 곳
                if add.any():
                    trace_parts_region.added[k] = add
            trace_parts_region.raw[k] = m
            if v in mirror_views:
                m = mirror_half(m, centers[v], mirror_mode)
            masks[k] = m
    return masks


def symmetry_axis(fg, c0, cx_meta, search=4.0, step=0.5):
    """전경 실루엣이 가장 잘 겹치는 좌우 대칭축(열 좌표, 픽셀 경계 기준)을 등록 값 ±search 안에서 0.5px 단위로 찾는다.
    등록 파일(trace_meta)의 중심선이 실제 대칭축과 1px 어긋나 거울 붙이기에 틈이 생긴 것을 측정으로 찾았다."""
    cols = np.arange(fg.shape[1]) + c0
    best = None
    for cx in np.arange(cx_meta - search, cx_meta + search + 1e-9, step):
        mc = np.round(2 * cx - 1 - cols).astype(int) - c0
        ok = (mc >= 0) & (mc < fg.shape[1])
        mir = np.zeros_like(fg)
        mir[:, mc[ok]] = fg[:, (cols[ok] - c0)]
        left = cols < cx
        a, b = fg[:, left], mir[:, left]
        v = (a & b).sum() / max((a | b).sum(), 1)
        if best is None or v > best[0]:
            best = (float(v), float(cx))
    return best[1], best[0]


def grow_rows(poly, mat, mats, rows, reach=40, tone=None, strict=True):
    """거친 다각형을 행 범위 rows=(위, 아래) 안에서 부위 재질 쪽으로 넓힌다(다른 뷰와 높이를 맞추는 루프 행동).
    다각형과 이어진 부위 재질 덩어리 중 다각형에서 reach px 안, 그 행 범위 안의 것만 더한다."""
    band = np.zeros_like(poly)
    pr = np.flatnonzero(poly.any(1))
    lo, hi = rows
    if len(pr):                                   # 범위가 다각형과 떨어져 있으면 다각형까지 잇는다
        if hi < pr.min():                         # (마스크가 덩어리 규칙으로 다각형보다 위까지 올라가 있으면 틈이 생겨 아무것도 안 붙었다)
            hi = int(pr.min())
        if lo > pr.max():
            lo = int(pr.max())
    band[max(0, lo):hi + 1] = True
    # 열 제한: 넓히는 쪽 다각형 끝 10행이 차지하던 열 ±8px 안에서만 위·아래로 늘린다.
    # (행 전체에서 옆으로 40px 까지 가져가 갈기 쪽에 가로 직사각형이 생겼다. 들소 옆 뷰에서 그림으로 확인)
    if len(pr):
        edge_rows = pr[:10] if hi <= pr.min() + 1 else pr[-10:]
        cs = np.flatnonzero(poly[edge_rows].any(0))
        colmask = np.zeros(poly.shape[1], bool)
        colmask[max(0, cs.min() - 8):cs.max() + 9] = True
        band &= colmask[None, :]
    cand = np.isin(mat, mats) & band & _dilate(poly, reach) & ~poly
    # 닫힌 조각만 붙인다: 조각이 띠 밖의 같은 재질과 맞닿으면(같은 털이 계속 이어짐) 버린다.
    # (턱 아래·귀 위에서 행·열 범위로 잘린 직선 모서리 상자가 생겼다. 볏처럼 위가 배경으로 닫힌 조각만 붙어야 한다)
    same_out = np.isin(mat, mats) & ~band & ~poly
    if tone is not None:                          # 톤 조각 단위: 같은 털이라도 가림 윤곽에서 톤이 바뀌면 떼어 낸다
        cc = _tone_pieces(cand, tone)
        leak = set()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb_same = np.roll(np.roll(same_out, -dy, 0), -dx, 1) & (np.roll(np.roll(tone, -dy, 0), -dx, 1) == tone)
            leak |= set(np.unique(cc[cand & nb_same]).tolist())
        leak -= {0}
    else:
        cc = components(cand)
        leak = set(np.unique(cc[_dilate(same_out, 1) & cand]).tolist()) - {0}
    touch = set(np.unique(cc[_dilate(poly, 1) & cand]).tolist()) - {0}
    keep = np.isin(cc, list(touch - leak))
    grow_rows.invented = np.zeros_like(poly)
    if not strict:                                # 제안 모드: 이어지는 조각도 붙이되 '지어낸 경계'로 따로 남긴다(사람 확인)
        inv = np.isin(cc, list(touch & leak)) & cand
        grow_rows.invented = inv
        keep = keep | inv
    return poly | (keep & cand)


def resolve_overlaps(masks, polys, views, priority=()):
    """픽셀마다 한 부위만. 겹친 픽셀은 그 픽셀을 다각형으로 감싼 부위 중 다각형이 가장 작은(더 구체적인) 부위가 갖는다.
    아무 다각형에도 없으면 원래 가진 부위 중 마스크가 큰 쪽이 갖는다(재질 덩어리로 들어온 경우).
    이유: 같은 재질의 하위 부위(뿔과 뿔 밑동)가 덩어리 규칙으로 서로를 먹어 같은 자리에 관이 이중으로 생겼다.
    priority: 그림 근거로 딴 부위(학습 분할 SAM 등). 그 마스크 안의 겹친 픽셀은 이 부위가 갖는다. 다각형은 LLM 의 거친 짐작일 뿐이라
    그림 근거가 앞선다(SAM 옆 귀 0.777 이 머리 다각형에 559px 를 빼앗겨 0.619 로 떨어졌다)."""
    out = {k: m.copy() for k, m in masks.items()}
    stats = {}
    for v in views:
        keys = [k for k in masks if k[0] == v]
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                ov = out[a] & out[b]
                n = int(ov.sum())
                if not n:
                    continue
                pa, pb = polys.get(a, np.zeros_like(ov)), polys.get(b, np.zeros_like(ov))
                a_small = int(pa.sum()) <= int(pb.sum())
                a_big_mask = out[a].sum() >= out[b].sum()
                both, only_a, only_b = pa & pb, pa & ~pb, pb & ~pa
                none = ~pa & ~pb
                own_a = ov & ((both & a_small) | only_a | (none & a_big_mask))
                if (a in priority) != (b in priority):          # 한쪽만 그림 근거 → 겹친 곳 전부 그쪽
                    own_a = ov if a in priority else np.zeros_like(ov)
                own_b = ov & ~own_a
                out[a] &= ~own_b
                out[b] &= ~own_a
                stats['%s|%s↔%s' % (v, a[1], b[1])] = n
    return out, stats


def tone_vote(masks, polys, mat, tone, part_mats, names, views, share=0.6, min_cover=0.3):
    """같은 재질 부위끼리 톤 조각(같은 톤으로 이어진 픽셀 = 슈퍼픽셀) 투표.
    조각마다 그 재질을 쓰는 부위들의 다각형이 덮는 픽셀을 세어, 한 부위가 덮인 픽셀의 share 이상이고 조각의 min_cover 이상이 덮였으면
    조각을 그 부위에 준다. 단 다른 부위 다각형 안의 픽셀은 그대로 둔다(LLM 이 그 부위라고 그린 곳은 빼앗지 않는다).
    이유: 옆 뷰 귀처럼 같은 털로 머리와 붙은 작은 부위를 머리가 통째로 가져갔다(벤치마크 옆 귀 0.33~0.41).
    귀는 머리 앞에 튀어나와 톤 조각이 따로 생기므로, 그 조각을 대부분 덮은 귀 다각형이 조각 전체를 갖는다."""
    out = {k: m.copy() for k, m in masks.items()}
    moved = {}
    for v in views:
        keys = [k for k in masks if k[0] == v and k in polys]
        if len(keys) < 2:
            continue
        union = np.zeros(mat.shape, bool)
        for k in keys:
            union |= out[k]
        tp = _tone_pieces(union & (tone >= 0), tone)
        for i in np.unique(tp[tp > 0]):
            piece = tp == i
            mt = int(np.bincount(mat[piece][mat[piece] >= 0]).argmax()) if (mat[piece] >= 0).any() else -1
            if mt < 0:
                continue
            users = [k for k in keys if names[mt] in part_mats.get(k[1], [])]
            if len(users) < 2:
                continue
            cov = {k: int((piece & polys[k]).sum()) for k in users}
            tot = sum(cov.values())
            if tot < min_cover * piece.sum():
                continue
            owner = max(cov, key=cov.get)
            if cov[owner] < share * tot:
                continue
            others_poly = np.zeros(mat.shape, bool)
            for k in users:
                if k != owner:
                    others_poly |= polys[k]
            give = piece & ~others_poly & ~out[owner]
            n = int(give.sum())
            if not n:
                continue
            for k in users:
                if k != owner:
                    out[k] &= ~give
            out[owner] |= give
            moved['%s|→%s' % (v, owner[1])] = moved.get('%s|→%s' % (v, owner[1]), 0) + n
    return out, moved


def absorb_lines(masks, mat, names, views, width=3):
    """외곽선 재질('선')은 영역 선택에서는 칸막이(어느 부위 재질도 아님)로 쓰고, 끝난 뒤 맞닿은 부위가 나눠 갖는다.
    선 픽셀마다 가장 가까운(width px 안) 부위에 준다. 거리가 같으면 먼저 닿은 부위(번호 순).
    이유: 외곽선이 있는 그림에서 선을 털 같은 어두운 재질로 섞으면 경계 단서를 잃고, 그냥 빼면 부위 사이에 틈이 생긴다."""
    if '선' not in names:
        return masks
    line = mat == names.index('선')
    out = {k: m.copy() for k, m in masks.items()}
    for v in views:
        keys = [k for k in masks if k[0] == v]
        taken = np.zeros(line.shape, bool)
        grown = {k: out[k].copy() for k in keys}
        for _ in range(width):
            for k in keys:
                g = grown[k]
                nb = g.copy()
                nb[1:] |= g[:-1]; nb[:-1] |= g[1:]; nb[:, 1:] |= g[:, :-1]; nb[:, :-1] |= g[:, 1:]
                add = nb & line & ~taken
                grown[k] = g | add
                taken |= add
        for k in keys:
            out[k] = grown[k]
    return out


def prune_masks(masks, expected, views, spur_px=2, island_frac=0.05, min_px=30):
    """불필요한 트레이스 걷어내기(자동 두 가지). 반환 (마스크, 걷어낸 마스크 {키: bool 배열}).
    1) 가는 가시: spur_px 반지름 열기(opening)로 사라지는 곳 중, 본체에서 튀어나온 실 같은 돌기(선·앤티에일리어싱 흔적).
       열기로 사라지는 픽셀 전체가 아니라, 열기 뒤 본체와 이어지지 않는 조각만 뺀다(모서리 둥글리기 방지).
    2) 떨어진 조각: 연결 덩어리를 크기순으로 기대 개수(expected[키], 기본 1; 좌우 한 쌍은 2)만 남기고,
       나머지 중 가장 큰 덩어리의 island_frac 미만이거나 min_px 미만인 것은 뺀다(큰 덩어리가 더 있으면 남기고 보고만).
    이유: 더하는 규칙(덧붙임·넓히기·추론)만 있고 잘못 들어간 것을 걷어내는 장치가 없었다(사용자 지적)."""
    out, removed = {}, {}
    for k, m in masks.items():
        if k[0] not in views or not m.any():
            out[k] = m
            continue
        rm = np.zeros_like(m)
        if spur_px > 0 and ndi is not None:
            # 가시: 폭 2*spur_px 이하로 열기에 사라지면서 길이가 8px 이상인 실 조각만. (뿔 끝·볏 털처럼 원래 가는 끝도
            # 열기에 사라지므로 기본은 끔. 켜면 1px 안내선·앤티에일리어싱 실만 겨냥하도록 spur_px=1 권장)
            op = ndi.binary_opening(m, iterations=spur_px)
            thin = m & ~op
            cc = components(thin)
            for i in np.unique(cc[cc > 0]):
                piece = cc == i
                ys, xs = np.nonzero(piece)
                if max(ys.max() - ys.min(), xs.max() - xs.min()) + 1 >= 8 and piece.sum() <= 2 * spur_px * (max(ys.max() - ys.min(), xs.max() - xs.min()) + 1):
                    rm |= piece
            m = m & ~rm
        others = np.zeros_like(m)
        for k2, m2 in masks.items():
            if k2[0] == k[0] and k2 != k:
                others |= m2
        near_other = _dilate(others, 2)
        cc = components(m)
        ids, cnt = np.unique(cc[cc > 0], return_counts=True)
        if len(ids):
            order = np.argsort(-cnt)
            keep_n = expected.get(k, 1)
            big = cnt[order[0]]
            for j in order[keep_n:]:
                piece = cc == ids[j]
                if (piece & near_other).any():           # 다른 부위와 맞닿은 조각은 떨어진 게 아니다(뿔이 밑동 컷으로 나뉜 조각 등)
                    continue
                if cnt[j] < island_frac * big or cnt[j] < min_px:
                    rm |= piece
        out[k] = m & ~rm
        if rm.any():
            removed[k] = rm
    return out, removed


def height_unsupported(masks, views=('front', 'side'), tol=3):
    """부위의 행 중 다른 뷰에서는 그 부위가 없는 행(정사영이면 같은 높이에 있어야 함). 자동으로 지우지 않고 보고만(LLM 이 판단)."""
    rep = {}
    parts = {k[1] for k in masks if k[0] in views}
    for p in parts:
        a, b = masks.get((views[0], p)), masks.get((views[1], p))
        if a is None or b is None or not a.any() or not b.any():
            continue
        ra, rb = np.flatnonzero(a.any(1)), np.flatnonzero(b.any(1))
        for (v, r_own), r_other in (((views[0], ra), rb), ((views[1], rb), ra)):
            lo, hi = r_other.min() - tol, r_other.max() + tol
            bad = r_own[(r_own < lo) | (r_own > hi)]
            if len(bad):
                rep['%s|%s' % (v, p)] = {'행': [int(bad.min()), int(bad.max())], '행수': int(len(bad))}
    return rep


def click_candidates(masks, mat, tone, polys, part_mats, names, views, d=8, min_px=40, top=12):
    """교정 후보(SAM-Veteran·MedSAM-Agent 방식 참고): LLM 이 좌표를 그리지 않고 번호에 '넣기/빼기/그대로'만 답하게 한다.
    후보 = 부위 윤곽에 맞닿은 톤 조각(같은 톤으로 이어진 픽셀 덩어리, 슈퍼픽셀)으로, 부위 재질이면서
      바깥 조각(+ 후보: 빠졌을 수 있음) 또는 안쪽 가장자리 조각(- 후보: 넘쳤을 수 있음).
    점 = 조각 안 거리 변환 최댓값(조각 중심, MedSAM-Agent 의 오차 군집 중심 클릭과 같은 생각). 크기순 top 개."""
    from .vendor import ndi as _ndi
    out = []
    for k, m in masks.items():
        if k[0] not in views or k not in polys or not m.any():
            continue
        mats = [names.index(n) for n in part_mats.get(k[1], []) if n in names]
        zone = _dilate(polys[k], 2 * d)
        band = _dilate(m, d) & _dilate(~m, d)                  # 경계 ±d 띠: 후보는 이 안의 조각만(안쪽 전체를 잡지 않게)
        ring_out = _dilate(m, 2) & ~m & zone & np.isin(mat, mats) & (tone >= 0)
        ring_in = m & _dilate(~m, 3) & (tone >= 0)
        for sign, sel in (('+', ring_out), ('-', ring_in)):
            tp = _tone_pieces(sel, tone)
            for i in np.unique(tp[tp > 0]):
                seed = tp == i
                t = int(np.bincount(tone[seed]).argmax())
                region = ((~m) if sign == '+' else m) & (tone == t) & zone & band
                cc = components(region)
                ids = np.unique(cc[seed & region])
                ids = ids[ids > 0]
                if not len(ids):
                    continue
                piece = np.isin(cc, ids)
                n = int(piece.sum())
                if n < min_px:
                    continue
                dt = _ndi.distance_transform_edt(piece) if _ndi is not None else piece.astype(float)
                yy, xx = np.unravel_index(int(np.argmax(dt)), dt.shape)
                out.append({'view': k[0], 'part': k[1], 'sign': sign, 'x': int(xx), 'y': int(yy), 'px': n})
    out.sort(key=lambda c: -c['px'])
    seen, uniq = set(), []
    for c in out:
        key = (c['view'], c['part'], c['sign'], c['x'] // 6, c['y'] // 6)
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    uniq = uniq[:top]
    for i, c in enumerate(uniq):
        c['id'] = i + 1
    return uniq


def apply_click(masks, mat, tone, polys, click, d=8):
    """점 하나 실행: (x, y) 의 톤 조각을 부위 구역(다각형 2d 넓힘) 안에서 통째로 더하거나(+) 뺀다(-). 바뀐 픽셀 수."""
    k = (click['view'], click['part'])
    m = masks[k]
    zone = _dilate(polys[k], 2 * d) if k in polys else np.ones_like(m)
    t = tone[click['y'], click['x']]
    if t < 0:
        return 0
    band = _dilate(m, d) & _dilate(~m, d)
    region = ((~m) if click['sign'] == '+' else m) & (tone == t) & zone & band
    cc = components(region)
    i = cc[click['y'], click['x']]
    if i == 0:
        return 0
    piece = cc == i
    masks[k] = (m | piece) if click['sign'] == '+' else (m & ~piece)
    return int(piece.sum())


def unsupported_cuts(masks, mat, views, min_len=10):
    """두 부위가 맞닿은 선 중 재질 경계가 아닌 곳(같은 재질 안을 LLM 선으로 자른 곳)의 길이와 비율.
    도면으로 확인할 수 없는 구분이라 보고 대상이다(합칠지 둘지는 사람이 정한다)."""
    rep = {}
    E = boundary(np.where(mat < 0, 0, mat)) > 0
    for v in views:
        keys = [k for k in masks if k[0] == v]
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                A, B = masks[a], masks[b]
                touch = (A & (np.roll(B, 1, 0) | np.roll(B, -1, 0) | np.roll(B, 1, 1) | np.roll(B, -1, 1)))
                n = int(touch.sum())
                if n < min_len:
                    continue
                sup = int((touch & (E | np.roll(E, 1, 0) | np.roll(E, 1, 1))).sum())
                rep['%s|%s↔%s' % (v, a[1], b[1])] = {'맞닿은_픽셀': n, '재질경계_비율': round(sup / n, 3),
                                                      '판정': '도면 근거 있음' if sup / n >= 0.5 else '도면 근거 없는 컷(LLM 선)'}
    return rep


def open_cuts(masks, mat, views, keep_cols=None):
    """부위 윤곽 중 바깥이 '어느 부위도 아닌 같은 재질'인 곳 = LLM 선으로 자른 곳(도면이 정해 주지 않는 끝, 예: 머리↔목).
    부위끼리 맞닿은 같은 재질 경계는 unsupported_cuts 가 따로 본다. 부위마다 픽셀 수와 비율.
    keep_cols={뷰: 열 마스크}: 거울로 붙인 뷰는 기준 절반에서만 잰다(반대쪽은 도면의 1~2px 비대칭이 컷처럼 잡힌다)."""
    rep = {}
    for v in views:
        union = np.zeros(mat.shape, bool)
        for k, m in masks.items():
            if k[0] == v:
                union |= m
        for k, m in masks.items():
            if k[0] != v:
                continue
            e = m & ~(np.roll(m, 1, 0) & np.roll(m, -1, 0) & np.roll(m, 1, 1) & np.roll(m, -1, 1))
            cut = np.zeros_like(e)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nb_free = np.roll(np.roll(~union, -dy, 0), -dx, 1)           # 이웃이 어느 부위도 아님
                nb_same = np.roll(np.roll(mat, -dy, 0), -dx, 1) == mat       # 이웃이 같은 재질
                cut |= e & nb_free & nb_same
            if keep_cols is not None and v in keep_cols:
                e &= keep_cols[v][None, :]
                cut &= keep_cols[v][None, :]
            n = int(e.sum())
            rep['%s|%s' % k] = {'윤곽_픽셀': n, 'LLM컷_픽셀': int(cut.sum()), 'LLM컷_비율': round(float(cut.sum()) / max(n, 1), 3)}
    return rep


def profile_rows(masks, part_names, meta, views=('front', 'side', 'back'), h0=0.0, h1=6.0, step=0.05):
    """부위 마스크 합집합 → 높이별 *_core 윤곽 표(harness.pack 이 읽는 profile 형식)."""
    ppH, ground = meta['px_per_H'], meta['ground_row_grid']
    U = {}
    for v in views:
        u = None
        for p in part_names:
            if (v, p) in masks:
                u = masks[(v, p)] if u is None else (u | masks[(v, p)])
        U[v] = u
    rows = []
    for h in np.round(np.arange(h0, h1 + 1e-9, step), 4):
        row = int(round(ground - h * ppH))
        out = {'h': float(h), 'row': row}
        for v in views:
            pm = meta['panels'][v]
            u = U[v]
            cs = np.flatnonzero(u[row]) if u is not None and 0 <= row < u.shape[0] else []
            if len(cs) == 0:
                out[v + '_core'] = None
                continue
            sg, cx = pm['x부호(화면x→캐릭터)'], pm['중심선_x']
            a, b = sg * (cs[0] - cx) / ppH, sg * (cs[-1] + 1 - cx) / ppH
            lo, hi = min(a, b), max(a, b)
            out[v + '_core'] = {'min': round(lo, 4), 'max': round(hi, 4), 'half_width': round((hi - lo) / 2, 4), 'center_offset': round((hi + lo) / 2, 4)}
        rows.append(out)
    return rows


def overlay(img, masks, boxes, scale=3, added=None, invented=None, inferred=None, pruned=None):
    """상자마다 도면 위에 부위 마스크 윤곽(빨강)을 그린 그림(사람 확인용). added 는 노랑(자동으로 덧붙인 곳),
    invented 는 주황(도면 경계 없이 높이 맞추기로 지어낸 곳)."""
    A = img[..., :3].copy()
    for m in (invented or {}).values():
        A[m] = (0.4 * A[m] + 0.6 * np.array([255, 120, 0])).astype(np.uint8)
    for m in (pruned or {}).values():                         # 청록 줄무늬 = 걷어낸 곳
        yy, xx = np.nonzero(m)
        sel = ((yy + xx) % 3) == 0
        A[yy[sel], xx[sel]] = (0, 200, 200)
    for m in (inferred or {}).values():                       # 보라 = LLM 추론(도면 근거 없음, 결정 파일에 근거 문장)
        A[m] = (0.4 * A[m] + 0.6 * np.array([170, 60, 220])).astype(np.uint8)
    for m in (added or {}).values():
        A[m] = (0.5 * A[m] + 0.5 * np.array([255, 220, 0])).astype(np.uint8)
    for m in masks.values():
        e = m.copy()
        e[1:-1, 1:-1] = m[1:-1, 1:-1] & ~(m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:])
        A[e] = (255, 0, 0)
    tiles = [np.repeat(np.repeat(A[r0:r1, c0:c1], scale, 0), scale, 1) for r0, r1, c0, c1 in boxes.values()]
    H = max(t.shape[0] for t in tiles)
    return np.concatenate([np.pad(t, ((0, H - t.shape[0]), (0, 12), (0, 0)), constant_values=255) for t in tiles], 1)
