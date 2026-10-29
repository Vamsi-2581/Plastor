# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-011 R-012 R-015
"""LLM 이 약한 곳을 메우는 도구(docs/조사_LLM한계.md 2장). 모두 좌표를 받지 않는다(부위·뷰 이름만).

digest: 도구가 잰 숫자 요약(인지 지도). LLM 이 그림에서 세거나 재지 않게 — 부위·뷰마다 조각 수·넓이·H 범위·대칭.
        시점을 머릿속에서 합치는 일(W1)과 세기(W2)를 도구가 한다.
zoom:   부위 둘레를 원래 해상도로 잘라 키운 그림. 조각마다 다른 색 테두리(Set-of-Mark), digest 의 조각 번호와 같은 순서.
        그림이 줄어들어 작은 부위가 몇 칸만 남는 문제(W3)와 세밀한 지각(W2)을 메운다. 긴 변은 1568px 이하.
judge:  같은 질문을 순서 바꿔 여러 번·두 모델 가족으로 물은 답을 모아 다수결·재현율·순서 뒤집힘·가족 간 카파.
        문턱 미달이면 UNKNOWN(W6: 안정 ≠ 옳음, 재현·순서·우연 보정 일치를 따로 잰다).
"""
import json
import os
import subprocess

import numpy as np

from .vendor import ndi  # noqa: F401  (scipy.ndimage)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 조각 색(Set-of-Mark): 번호 1, 2, 3 ... 순서. 서로 잘 구별되고 셀 셰이딩 갈색·분홍과 겹치지 않게
PALETTE = [(0, 200, 255), (255, 0, 200), (255, 220, 0), (0, 255, 90), (255, 90, 0), (150, 80, 255), (0, 120, 255), (255, 255, 255)]
MAX_EDGE = 1568


def _load_masks(path):
    z = np.load(path)
    with z:
        return {tuple(k.split('|')): z[k].astype(bool) for k in z.files}


def pieces(mask, min_px=30):
    """연결 성분(8 이웃) 중 min_px 이상, 큰 순서. 반환 [(조각 마스크, 넓이)]."""
    lab, n = ndi.label(mask, np.ones((3, 3)))
    if not n:
        return []
    sz = ndi.sum(mask, lab, range(1, n + 1))
    order = [i for i in np.argsort(-sz) if sz[i] >= min_px]
    return [(lab == i + 1, int(sz[i])) for i in order]


def digest(masks_path, frame, views=('front', 'side'), min_px=30):
    """부위·뷰마다 숫자 요약. frame 은 build.Frame/Pack(px_to_H 가 있음). 반환 {'부위': {...}, '글': 표 문자열}."""
    M = _load_masks(masks_path)
    out = {}
    for (v, p), m in sorted(M.items()):
        if v not in views or not m.any():
            continue
        ps = pieces(m, min_px)
        rows = []
        for pm, area in ps:
            r, c = np.nonzero(pm)
            lat, z = frame.px_to_H(v, c + 0.5, r + 0.5)
            rows.append({'넓이_px': area, '가로_H': [round(float(lat.min()), 3), round(float(lat.max()), 3)],
                         '높이_H': [round(float(z.min()), 3), round(float(z.max()), 3)],
                         '중심_H': [round(float(lat.mean()), 3), round(float(z.mean()), 3)]})
        e = {'조각_수': len(ps), '조각': rows, '전체_넓이_px': int(m.sum())}
        if v in ('front', 'back') and len(rows) >= 1:
            # 좌우 대칭: 마스크를 중심선(가로 0)에 대해 뒤집어 겹치는 비율
            r, c = np.nonzero(m)
            lat, z = frame.px_to_H(v, c + 0.5, r + 0.5)
            fx, fy = frame.H_to_px(v, -lat, z)
            fx, fy = np.floor(fx).astype(int), np.floor(fy).astype(int)
            ok = (fy >= 0) & (fy < m.shape[0]) & (fx >= 0) & (fx < m.shape[1])
            e['좌우_대칭'] = round(float(m[fy[ok], fx[ok]].mean()) if ok.any() else 0.0, 3)
        out.setdefault(p, {})[v] = e
    lines = ['부위 | 뷰 | 조각 수 | 넓이(px) | 가로 범위(H) | 높이 범위(H) | 좌우 대칭']
    for p, d in out.items():
        for v, e in d.items():
            for i, r in enumerate(e['조각']):
                lines.append('%s | %s | %s | %d | %s | %s | %s' % (p, v, '%d/%d' % (i + 1, e['조각_수']), r['넓이_px'], r['가로_H'], r['높이_H'],
                                                                 e.get('좌우_대칭', '-') if i == 0 else ''))
    return {'부위': out, '글': '\n'.join(lines)}


def zoom_image(drawing, masks_path, part, view, margin=0.25, min_px=30):
    """부위 둘레를 잘라 키운 RGB 배열과 정보. 조각마다 PALETTE 색 테두리(digest 조각 순서와 같음)."""
    M = _load_masks(masks_path)
    m = M.get((view, part))
    if m is None or not m.any():
        return None, {'이유': '%s 뷰에 %s 트레이스가 없음' % (view, part)}
    r, c = np.nonzero(m)
    h, w = r.max() - r.min() + 1, c.max() - c.min() + 1
    r0 = max(0, int(r.min() - margin * h)); r1 = min(m.shape[0], int(r.max() + margin * h) + 1)
    c0 = max(0, int(c.min() - margin * w)); c1 = min(m.shape[1], int(c.max() + margin * w) + 1)
    img = np.array(drawing[r0:r1, c0:c1, :3], np.uint8)
    for i, (pm, _) in enumerate(pieces(m, min_px)):
        sub = pm[r0:r1, c0:c1]
        edge = sub & ~ndi.binary_erosion(sub)
        img[edge] = PALETTE[i % len(PALETTE)]
    # 정수배로 키운다(보간하지 않음: 픽셀 경계를 그대로). 긴 변 MAX_EDGE 이하
    k = max(1, int(MAX_EDGE // max(img.shape[:2])))
    big = img.repeat(k, 0).repeat(k, 1)
    return big, {'자른_범위_px': [r0, r1, c0, c1], '배율': k, '크기': list(big.shape[:2]), '조각_색': [PALETTE[i % len(PALETTE)] for i in range(len(pieces(m, min_px)))]}


def save_png(arr, path):
    """PNG 쓰기: Rust `mh png`(Blender 를 띄우지 않음, 화소 같음 확인 tests/selftest_rust_score.py). 없으면 Blender(bench/npy2png.py)."""
    import json
    tmp = path + '.npy'
    np.save(tmp, np.ascontiguousarray(arr[:, :, :3], np.uint8))
    mh = os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
    if os.path.exists(mh):
        subprocess.run([mh, 'png', json.dumps({'npy': tmp, 'out': os.path.abspath(path)})], capture_output=True)
    else:
        from build import BLENDER
        subprocess.run([BLENDER, '-b', '-P', os.path.join(ROOT, 'bench', 'npy2png.py'), '--', tmp, os.path.abspath(path)],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    os.remove(tmp)
    return os.path.exists(path)


def kappa(a, b):
    """두 판정자의 Cohen 카파(우연 일치를 뺀 일치). a, b 는 같은 길이의 답 목록."""
    a, b = list(a), list(b)
    if not a:
        return None
    cats = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b)) / len(a)
    pe = sum((a.count(k) / len(a)) * (b.count(k) / len(b)) for k in cats)
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)


def judge(runs, min_share=0.8, max_flip=0.2, min_kappa=0.6):
    """runs: [{'가족': 'claude'|'codex'|..., '순서': 'A'|'B', '답': {문항: 답}}]. 같은 문항을 여러 번 물은 답.
    문항마다: 다수 답, 재현율(다수 답과 같은 비율), 순서 뒤집힘(같은 가족 안에서 A·B 가 다른 비율), 가족별 다수.
    확정 ⇔ 재현율 ≥ min_share, 뒤집힘 ≤ max_flip, 가족별 다수가 모두 같음. 아니면 UNKNOWN.
    가족 간 카파(문항 전체)가 min_kappa 미만이면 전체 판정 UNKNOWN(그 판단은 LLM 에게 맡기지 않는다)."""
    items = sorted({k for r in runs for k in r['답']}, key=str)
    runs = [r for r in runs if r.get('답')]          # 답이 하나도 없는 실행(ERROR)은 뺀다(빈 가족이면 카파가 0 으로 나눴다)
    fams = sorted({r['가족'] for r in runs})
    res = {}
    fam_major = {f: [] for f in fams}
    for it in items:
        ans = [r['답'][it] for r in runs if it in r['답']]
        vals, cnt = np.unique(np.array(ans, dtype=object).astype(str), return_counts=True)
        major = vals[np.argmax(cnt)]
        share = float(cnt.max() / len(ans))
        flips = []
        fm = {}
        for f in fams:
            fa = [r for r in runs if r['가족'] == f and it in r['답']]
            A = [str(r['답'][it]) for r in fa if r['순서'] == 'A']
            B = [str(r['답'][it]) for r in fa if r['순서'] == 'B']
            if A and B:
                flips.append(float(np.mean([x != y for x in A for y in B])))
            if fa:
                v2, c2 = np.unique([str(r['답'][it]) for r in fa], return_counts=True)
                fm[f] = v2[np.argmax(c2)]
                fam_major[f].append(fm[f])
        flip = max(flips) if flips else 0.0
        agree = len(set(fm.values())) == 1
        res[it] = {'다수': major, '재현율': round(share, 3), '순서_뒤집힘': round(flip, 3), '가족별': fm,
                   '판정': '확정' if share >= min_share and flip <= max_flip and agree else 'UNKNOWN'}
    kap = None
    if len(fams) >= 2:
        kap = kappa(fam_major[fams[0]], fam_major[fams[1]])
    overall = 'UNKNOWN' if (kap is not None and kap < min_kappa) else ('PASS' if all(r['판정'] == '확정' for r in res.values()) else 'UNKNOWN')
    return {'판정': overall, '가족_카파': None if kap is None else round(kap, 3), '문항': res}
