# -*- coding: utf-8 -*-
"""색 군집 → 재질 묶음 검토(Set-of-Mark 방식). 군집마다 번호를 찍은 작은 그림을 만들고, LLM 은 번호마다 재질 이름만 답한다.
기본 묶음은 기준색 최근접(trace.build_material)이라, 첫 판단에서 빠진 재질(들소 옆 귀 분홍)이나 밝기만 비슷한 색이 엉뚱한 재질로 간다.
같은 질문을 재질 보기 순서만 바꿔 두 번 묻고, 두 답이 다르면 그 번호는 UNKNOWN(기본 묶음 유지)으로 둔다.
근거: 여러 그림을 한꺼번에 준 VLM 판정이 순서만 보고 답한 사례(순서 바꾸면 100% 뒤집힘, arXiv 2606.20364). docs/자유조사_2026-10-29.md.
"""
import numpy as np

DIGITS = {'0': ['111', '101', '101', '101', '111'], '1': ['010', '110', '010', '010', '111'], '2': ['111', '001', '111', '100', '111'],
          '3': ['111', '001', '111', '001', '111'], '4': ['101', '101', '111', '001', '001'], '5': ['111', '100', '111', '001', '111'],
          '6': ['111', '100', '111', '101', '111'], '7': ['111', '001', '010', '010', '010'], '8': ['111', '101', '111', '101', '111'],
          '9': ['111', '101', '111', '001', '111']}


def stamp(img, x, y, text, col, s=3):
    for j, ch in enumerate(text):
        for r, row in enumerate(DIGITS[ch]):
            for c, b in enumerate(row):
                if b == '1':
                    yy, xx = y + r * s, x + j * 4 * s + c * s
                    if 0 <= yy < img.shape[0] - s and 0 <= xx < img.shape[1] - s:
                        img[yy:yy + s, xx:xx + s] = col


def cluster_stats(img, lab, boxes):
    """군집마다 평균 RGB 와 뷰별 픽셀 수. lab: 군집 번호 지도(전경만, 나머지 -1)."""
    k = int(lab.max()) + 1
    out = []
    for j in range(k):
        m = lab == j
        px = {v: int(m[r0:r1, c0:c1].sum()) for v, (r0, r1, c0, c1) in boxes.items()}
        col = img[m].mean(0) if m.any() else np.zeros(3)
        out.append({'id': j, '평균색': [int(round(x)) for x in col], '픽셀': px})
    return out


def tile(img, lab, boxes, j, views=None, width=420):
    """군집 j 한 칸: 그 군집 픽셀은 원래 색, 다른 전경은 옅게, 배경은 흰색(뷰를 옆으로 이어 붙임)."""
    views = views or [v for v in boxes if v != 'back']
    crops = [(img[r0:r1, c0:c1].astype(float), lab[r0:r1, c0:c1]) for v, (r0, r1, c0, c1) in boxes.items() if v in views]
    Hc = max(c[0].shape[0] for c in crops)
    parts = []
    for im, lb in crops:
        t = np.full(im.shape, 255.0)
        fg = lb >= 0
        t[fg] = 0.25 * im[fg] + 0.75 * 255
        t[lb == j] = im[lb == j]
        parts.append(np.pad(t, ((0, Hc - t.shape[0]), (0, 6), (0, 0)), constant_values=255))
    t = np.concatenate(parts, 1)
    f = width / t.shape[1]
    ys = (np.arange(int(t.shape[0] * f)) / f).astype(int)
    xs = (np.arange(width) / f).astype(int)
    return t[ys][:, xs]


def sheet(img, lab, boxes, views=None, width=420, cols=3):
    """번호 그림: 군집마다 한 칸. 그 군집 픽셀은 원래 색, 다른 전경은 옅게, 배경은 흰색. 칸 왼쪽 위에 번호와 평균색 견본."""
    k = int(lab.max()) + 1
    tiles = []
    for j in range(k):
        t = np.pad(tile(img, lab, boxes, j, views, width), ((26, 4), (2, 2), (0, 0)), constant_values=255)
        m = lab == j
        if m.any():
            t[2:22, 40:70] = img[m].mean(0)
        stamp(t, 4, 3, str(j), (200, 0, 0), s=3)
        tiles.append(t)
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 255))
    rows = [np.concatenate(tiles[i:i + cols], 1) for i in range(0, len(tiles), cols)]
    return np.clip(np.concatenate(rows, 0), 0, 255).astype(np.uint8)


def prompt(stats, names, cmap, order, part_mats):
    """LLM 에게 줄 질문. order: 재질 보기 순서(두 번 묻기에서 서로 다르게). 현재 묶음은 보여 주지 않는다(답을 끌고 가지 않게)."""
    lines = ['그림 groups.png 의 칸마다 빨간 번호가 색 군집 번호다. 칸에서 진하게 보이는 픽셀이 그 군집이다(옅은 것은 다른 군집).',
             '각 번호가 그림에서 어떤 재질(같은 물감으로 칠한 면, 그림자 톤은 같은 재질)인지 답하라.',
             '재질 보기: ' + ', '.join(order) + '. 보기에 맞는 것이 없으면 새 재질 이름을 지어도 된다.',
             '새 재질을 지었으면 그 재질이 속한 부위를 part_mats_add 에 적는다. 지금 부위별 재질: %s' % part_mats,
             '답 형식(JSON): {"answers": [{"id": 0, "재질": "..."}, ...], "part_mats_add": {"부위": ["새 재질"]}} 모든 번호에 답한다.']
    for s in stats:
        lines.append('번호 %d: 평균색 %s, 픽셀 %s' % (s['id'], s['평균색'], s['픽셀']))
    return '\n'.join(lines)


def merge(cmap, ans_a, ans_b):
    """두 답을 합친다. 같으면 채택(기본과 다를 때만 cluster_mats 에 적음), 다르면 UNKNOWN(기본 유지).
    part_mats_add 는 두 답에 모두 있는 (부위, 재질)만, 그리고 채택된 재질만 남긴다.
    반환 (cluster_mats, part_mats_add, 기록 목록)."""
    a = {int(x['id']): x['재질'] for x in ans_a['answers']}
    b = {int(x['id']): x['재질'] for x in ans_b['answers']}
    out, log = {}, []
    for j in sorted(set(a) | set(b) | {int(k) for k in cmap}):
        cur = cmap.get(str(j))
        if j not in a or j not in b:
            log.append({'id': j, '판정': 'UNKNOWN', '이유': '한쪽 답 없음', '기본': cur})
        elif a[j] != b[j]:
            log.append({'id': j, '판정': 'UNKNOWN', '이유': '순서 바꾸자 답이 다름 %s/%s' % (a[j], b[j]), '기본': cur})
        elif a[j] == cur:
            log.append({'id': j, '판정': '그대로', '기본': cur})
        else:
            out[str(j)] = a[j]
            log.append({'id': j, '판정': '바꿈', '기본': cur, '새': a[j]})
    used = set(out.values())
    pa, pb = ans_a.get('part_mats_add', {}), ans_b.get('part_mats_add', {})
    add = {}
    for part in set(pa) & set(pb):
        ms = [m for m in pa[part] if m in pb[part] and m in used]
        if ms:
            add[part] = ms
    return out, add, log


# ---------------------------------------------------------------- v2: 빠진 재질 찾기(채택, docs/수정_기록.md 34)
Q_NEW = '''그림 groups.png 의 칸마다 빨간 번호가 색 군집 번호다. 칸에서 진하게 보이는 픽셀이 그 군집이다(옅은 것은 다른 군집).
칠한 물감(재질) 목록: {mats}. 같은 물감의 그림자·밝은 톤은 같은 재질로 본다.
질문 하나: 목록의 어느 물감과도 다른 물감으로 칠한 면이 있는가? 있으면 그 군집 번호들과, 그 면이 있는 부위({parts} 중 하나)를 답하라.
없으면 빈 목록. 배경·가장자리 잡티는 세지 않는다.
답 형식(JSON): {{"new": [번호, ...], "part": "부위 또는 빈 문자열"}}'''


def prompt_new(mats, parts, order):
    """빠진 재질 찾기 질문. 현재 묶음·부위별 재질은 보여 주지 않는다(L13: 보여 주면 그대로 따라 답함).
    order 'A' 는 목록 그대로, 'B' 는 거꾸로(두 답이 같아야 채택)."""
    mm = list(mats) if order == 'A' else list(mats)[::-1]
    return Q_NEW.format(mats=', '.join(mm), parts=', '.join(parts))


def merge_new(ans_a, ans_b, name='새재질'):
    """두 답(서로 다른 모델 가족·보기 순서)에서 같은 번호·같은 부위만. 반환 (cluster_mats, part_mats_add, 판정 정보).
    묶기 전체를 LLM 에게 맡기면 기준색 최근접(정답률 0.85)보다 낫지 않았다(L18). 빠진 재질 하나만 묻는다."""
    new = sorted(set(map(int, ans_a.get('new', []))) & set(map(int, ans_b.get('new', []))))
    part = ans_a.get('part') if ans_a.get('part') == ans_b.get('part') else ''
    only = sorted(set(map(int, ans_a.get('new', []))) ^ set(map(int, ans_b.get('new', []))))
    info = {'일치': new, '부위': part, '엇갈림_UNKNOWN': only}
    if not new or not part:
        return {}, {}, info
    return {str(j): name for j in new}, {part: [name]}, info
