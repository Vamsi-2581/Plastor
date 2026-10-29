# -*- coding: utf-8 -*-
"""G0 목표 검증: 하네스가 맞추려는 목표(팩의 윤곽 표)가 도면 이미지의 실제 경계 위에 있는지 잰다.
이유: 관문 G1~G4 는 '모델이 목표에 맞는가'만 본다. 목표 자체가 거칠게 오려낸 다각형이면 숫자가 모두 PASS 여도 도면과는 다르다
(들소 머리 3~6차에서 실제로 겪음). 그래서 목표 윤곽의 각 점이 도면 색 경계(기울기) 위에 있는지 본다.
규칙은 값을 보기 전에 정했다: 창 ±WIN px 안에 색 기울기 ≥ GRAD 가 있으면 '지지됨', 지지 비율 ≥ RATIO 이면 PASS.
한계: 머리와 목처럼 원래 경계가 없는 곳을 자르는 선도 '지지 안 됨'으로 나온다(그 부분은 사람이 컷 선이라고 승인해야 한다).
"""
import numpy as np

WIN = 3        # px
GRAD = 20.0    # 이웃 픽셀 색 차(0~255 유클리드)
RATIO = 0.80    # 이상 PASS
RATIO_FAIL = 0.50   # 미만 FAIL, 그 사이는 UNKNOWN(경계 지지가 약해 사람이 확인). 대조: 도면과 맞는 부위 0.45~0.84, 20px 어긋난 대조 0.11~0.20


def _grad(img):
    f = img.astype(float)
    gx = np.zeros(img.shape[:2])
    gx[:, 1:-1] = np.linalg.norm(f[:, 2:] - f[:, :-2], axis=2) / 2.0
    return gx


def target_check(pack, views=('front', 'side')):
    img = pack.drawing()
    if img is None:
        return {'verdict': 'UNKNOWN', 'why': '도면 이미지 없음'}
    img = img[..., :3]
    gx = _grad(img)
    h, w = gx.shape
    views = [v for v in views if v not in pack.exclude]
    per, bad_rows = {}, []
    for v in views:
        P = pack.prof[v]
        for edge in ('lo', 'hi'):
            ok = 0
            miss = []
            for z, lat in zip(pack.z, P[edge]):
                px, py = pack.H_to_px(v, lat, z)
                r, c = int(round(float(py))), int(round(float(px)))
                if not (0 <= r < h and WIN <= c < w - WIN):
                    miss.append(float(z)); continue
                if gx[r, c - WIN:c + WIN + 1].max() >= GRAD:
                    ok += 1
                else:
                    miss.append(float(z))
            n = len(pack.z)
            per['%s_%s' % (v, edge)] = {'지지': ok, '전체': n, '비율': round(ok / n, 3), '지지_없는_높이': [round(m, 2) for m in miss]}
    tot = sum(p['전체'] for p in per.values())
    sup = sum(p['지지'] for p in per.values())
    ratio = sup / tot if tot else 0.0
    verdict = 'PASS' if ratio >= RATIO else ('UNKNOWN' if ratio >= RATIO_FAIL else 'FAIL')
    worst = sorted(per.items(), key=lambda kv: kv[1]['비율'])[:2]
    why = '목표 윤곽의 %.0f%% 가 도면 경계 위(기준 %.0f%%)' % (100 * ratio, 100 * RATIO)
    if verdict != 'PASS':
        why += '; 나쁜 윤곽: ' + ', '.join('%s %.0f%%' % (k, 100 * v['비율']) for k, v in worst)
    return {'verdict': verdict, 'why': why, 'ratio': round(ratio, 3), 'per': per, 'params': {'win_px': WIN, 'grad': GRAD, 'pass_min': RATIO, 'fail_below': RATIO_FAIL}}
