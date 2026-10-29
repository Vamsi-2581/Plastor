# -*- coding: utf-8 -*-
# 추적(docs/추적_체계.md): R-017
"""3D 모델 검사(harness/model_check.py) 자체 시험. 정답을 아는 해석적 도형으로 진단이 맞게 갈리는지 본다.
실행: python tests/selftest_model.py (끝 코드 0 = PASS)"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from harness import vendor  # noqa: E402,F401
from harness.model_check import check, project, voxelize  # noqa: E402

RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


class FakePack:
    """정면 중심 150, 옆 중심 450, 발바닥 행 280, 1H = 100px."""
    ppH = 100.0
    panels = {'front': {'center_x': 150.0, 'ground_row': 280.0, 'sign': -1}, 'side': {'center_x': 450.0, 'ground_row': 280.0, 'sign': -1}}

    def H_to_px(self, view, lat, z):
        p = self.panels[view]
        return p['center_x'] + p['sign'] * np.asarray(lat, float) * self.ppH, p['ground_row'] - np.asarray(z, float) * self.ppH


def mesh(fn, lo, hi, step=0.01):
    from skimage.measure import marching_cubes
    xs, ys, zs = [np.arange(a, b, step) for a, b in zip(lo, hi)]
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    vol = np.pad(fn(X, Y, Z).astype(float), 1)
    v, f, _, _ = marching_cubes(vol, 0.5)
    v = (v - 1) * step + np.array([xs[0], ys[0], zs[0]])
    return v, f[:, ::-1].copy()


def main():
    pk = FakePack()
    shape = (300, 600)
    # 1. 단면: 둥근 관과 상자 관(가로로 뻗은 뿔)
    rnd = mesh(lambda X, Y, Z: (Y ** 2 + (Z - 1.5) ** 2 <= 0.1 ** 2) & (np.abs(X) <= 0.6), (-0.7, -0.2, 1.3), (0.7, 0.2, 1.7))
    box = mesh(lambda X, Y, Z: (np.abs(Y) <= 0.09) & (np.abs(Z - 1.5) <= 0.09) & (np.abs(X) <= 0.6), (-0.7, -0.2, 1.3), (0.7, 0.2, 1.7))
    tr = {}
    for nm, m in (('둥근', rnd), ('상자', box)):
        occ, lo = voxelize(*m, 0.01)
        for v in ('front', 'side'):
            tr[(v, nm)] = project(occ, lo, 0.01, pk, v, shape)
    R = check(pk, {'둥근': rnd, '상자': box}, tr, voxel=0.01, shape=shape)
    fr, fb = R['부위']['둥근']['단면_채움비'], R['부위']['상자']['단면_채움비']
    kinds_r = [d['종류'] for d in R['부위']['둥근']['진단']]
    kinds_b = [d['종류'] for d in R['부위']['상자']['진단']]
    ok('단면: 둥근 관은 통과, 상자 관은 상자 단면으로 진단', fr is not None and fr < 0.9 and '상자 단면' in kinds_b and '상자 단면' not in kinds_r,
       '채움비 둥근 %s 상자 %s' % (fr, fb))
    ok('재투영: 자기 투영과 비교하면 IoU ≥ 0.98', all(d['IoU'] >= 0.98 for p in R['부위'].values() for d in p['뷰'].values()),
       str({p: {v: d['IoU'] for v, d in r['뷰'].items()} for p, r in R['부위'].items()}))
    # 2. 그림 모순: 옆 트레이스만 위로 12px 더 그려졌다(AI 도면처럼). 모델은 정면에 맞음 → '그림 모순'
    ear = mesh(lambda X, Y, Z: ((X - 0.3) / 0.15) ** 2 + (Y / 0.08) ** 2 + ((Z - 1.0) / 0.2) ** 2 <= 1, (0.1, -0.15, 0.75), (0.5, 0.15, 1.25))
    occ, lo = voxelize(*ear, 0.01)
    tf, ts = project(occ, lo, 0.01, pk, 'front', shape), project(occ, lo, 0.01, pk, 'side', shape)
    r0 = np.flatnonzero(ts.any(1)).min()
    ts2 = ts.copy()
    for k in range(1, 13):
        ts2[r0 - k] = ts[r0 + 2]
    R2 = check(pk, {'귀': ear}, {('front', '귀'): tf, ('side', '귀'): ts2}, voxel=0.01, shape=shape)
    k2 = [(d['종류'], d.get('뷰')) for d in R2['부위']['귀']['진단']]
    ok('그림 모순: 한 뷰만 높이가 다르면 모델링 오차가 아니라 그림 모순', ('그림 모순', 'side') in k2 and not any(k == '모델링 오차' for k, _ in k2), str(k2))
    # 3. 모델링 오차: 트레이스는 서로 맞는데 모델이 작다
    small = mesh(lambda X, Y, Z: ((X - 0.3) / 0.12) ** 2 + (Y / 0.065) ** 2 + ((Z - 1.0) / 0.2) ** 2 <= 1, (0.1, -0.15, 0.75), (0.5, 0.15, 1.25))
    R3 = check(pk, {'귀': small}, {('front', '귀'): tf, ('side', '귀'): ts}, voxel=0.01, shape=shape)
    k3 = [d['종류'] for d in R3['부위']['귀']['진단']]
    ok('모델링 오차: 트레이스가 서로 맞으면 모델 쪽 오차로 진단', '모델링 오차' in k3 and '그림 모순' not in k3, str(k3))
    # 4. 떠 있는 조각
    head = mesh(lambda X, Y, Z: X ** 2 + Y ** 2 + (Z - 1.0) ** 2 <= 0.2 ** 2, (-0.25, -0.25, 0.75), (0.25, 0.25, 1.25))
    far = mesh(lambda X, Y, Z: ((X - 0.6) / 0.15) ** 2 + (Y / 0.08) ** 2 + ((Z - 1.0) / 0.2) ** 2 <= 1, (0.4, -0.15, 0.75), (0.8, 0.15, 1.25))
    R4 = check(pk, {'머리': head, '귀': far}, {}, voxel=0.01, shape=shape)
    ok('떠 있는 조각: 머리와 닿지 않은 귀를 찾는다', any('귀' in f['부위'] for f in R4['떠있는_조각']), str(R4['떠있는_조각']))
    ear_on = mesh(lambda X, Y, Z: ((X - 0.2) / 0.15) ** 2 + (Y / 0.08) ** 2 + ((Z - 1.0) / 0.2) ** 2 <= 1, (0.0, -0.15, 0.75), (0.4, 0.15, 1.25))
    R5 = check(pk, {'머리': head, '귀': ear_on}, {}, voxel=0.01, shape=shape)
    ok('떠 있는 조각: 붙어 있으면 없음', not R5['떠있는_조각'], str(R5['떠있는_조각']))
    # 5. 가림: 머리가 귀 뒤로 이어진다. 트레이스 머리는 귀 자리를 뺐지만, 모델 머리가 그 자리에 있는 것은 오차가 아니다
    big = mesh(lambda X, Y, Z: X ** 2 + Y ** 2 + (Z - 1.0) ** 2 <= 0.3 ** 2, (-0.35, -0.35, 0.65), (0.35, 0.35, 1.35))
    occ_h, lo_h = voxelize(*big, 0.01)
    th = {v: project(occ_h, lo_h, 0.01, pk, v, shape) for v in ('front', 'side')}
    front_ear = mesh(lambda X, Y, Z: (X ** 2 + (Y - 0.25) ** 2) / 0.12 ** 2 + ((Z - 1.0) / 0.12) ** 2 <= 1, (-0.15, 0.1, 0.85), (0.15, 0.4, 1.15))
    occ_e, lo_e = voxelize(*front_ear, 0.01)
    te = project(occ_e, lo_e, 0.01, pk, 'front', shape)
    R6 = check(pk, {'머리': big}, {('front', '머리'): th['front'] & ~te, ('front', '코'): te, ('side', '머리'): th['side']}, voxel=0.01, shape=shape)
    i6 = R6['부위']['머리']['뷰']['front']
    ok('가림: 다른 부위가 앞을 가린 자리는 오차로 세지 않는다', i6['IoU'] >= 0.98 and i6['가림_제외_px'] > 100 and not R6['부위']['머리']['진단'], str(i6))
    # 5b. 합친 메시: 겹쳐 있기만 한 두 공은 '합쳐지지 않음', 한 덩어리는 통과(들소 14차에서 복셀 검사가 놓친 것)
    from harness.model_check import merged_check
    two = mesh(lambda X, Y, Z: (X ** 2 + Y ** 2 + (Z - 1) ** 2 <= 0.04) | ((X - 0.15) ** 2 + Y ** 2 + (Z - 1) ** 2 <= 0.04), (-0.25, -0.25, 0.75), (0.4, 0.25, 1.25))
    sep_v = np.vstack([head[0], ear_on[0]]); sep_f = np.vstack([head[1], ear_on[1] + len(head[0])])
    m_one, m_two = merged_check(*two), merged_check(sep_v, sep_f)
    ok('합친 메시: 겹쳐 있기만 한 조각은 합쳐지지 않음, 한 덩어리는 통과', not m_one['진단'] and m_one['몸_수'] == 1 and any(d['종류'] == '합쳐지지 않음' for d in m_two['진단']),
       '한 덩어리 %s / 겹친 둘 %s' % (m_one['몸_수'], m_two['몸_수']))
    # 5c. 둥근 헐: 휜 둥근 뿔에서 실루엣은 헐과 같고(≥0.99) 부피는 헐보다 정답에 가깝다(bench/sweep_bench.py 의 한 장면)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bench'))
    import sweep_bench as SB
    from harness.hull import build_hull
    from harness.model_check import iou as _iou
    from harness.sweep import build_round_hull
    pk2, vx, shp = SB.FakePack(), 0.01, (420, 800)
    Tv, lo2 = SB.horn_volume(np.random.default_rng(503), vx)
    f2, s2 = project(Tv, lo2, vx, pk2, 'front', shp), project(Tv, lo2, vx, pk2, 'side', shp)
    Vh, Fh, _ = build_hull(pk2, f2, s2, voxel=vx, smooth=1.0, master='front')
    Vr, Fr, _ = build_round_hull(pk2, f2, s2, (0, 0, 2.8), voxel=vx)
    vh, vr = SB.vol_iou(Vh, Fh, Tv, lo2, vx), SB.vol_iou(Vr, Fr, Tv, lo2, vx)
    o2, l2 = voxelize(Vr, Fr, vx)
    sf, ss = _iou(project(o2, l2, vx, pk2, 'front', shp), f2), _iou(project(o2, l2, vx, pk2, 'side', shp), s2)
    ok('둥근 헐: 휜 뿔에서 부피는 헐보다 정답에 가깝고 실루엣은 ≥ 0.99', vr > vh and sf >= 0.99 and ss >= 0.99, '부피 헐 %.3f → 둥근 %.3f, 실루엣 %.3f %.3f' % (vh, vr, sf, ss))
    # 6. 카드: 앞 단계(그림 모순)가 남으면 그 카드만, 결정하면 다음 단계로. 교훈은 그 단계·진단에 맞는 것 최대 4개
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import model_loop as ML
    RR = {'부위': {'귀': {'뷰': {}, '진단': [{'종류': '그림 모순', '뷰': 'side', '설명': 'x'}]},
                   '머리': {'뷰': {'side': {'IoU': 0.8}}, '진단': [{'종류': '모델링 오차', '뷰': 'side', '설명': 'y'}]}}}
    v1, t1 = ML.card(RR, '머리')
    v2, t2 = ML.card(RR, '머리', [{'부위': '귀', '종류': '그림 모순', '결정': '정면 따름', '근거': 'z'}])
    n_less = t1.split('## 관련 교훈')[1].split('##')[0].count('- [')
    ok('카드: 그림 모순이 남으면 단계 1 카드만, 결정하면 단계 2', v1 == 'FAIL' and t1.startswith('# 단계 1') and '단계 2. 큰 형태' not in t1 and t2.startswith('# 단계 2') and '(결정됨) 귀' in t2,
       t1.splitlines()[0] + ' / ' + t2.splitlines()[0])
    ok('카드: 교훈은 1~4개, 단계 1 교훈만', 1 <= n_less <= 4 and all(1 in e['단계'] for e in ML.lessons(1, [('귀', {'종류': '그림 모순'})])), '%d개' % n_less)
    # 7. 조사 단계: 같은 진단이 2번 이어지면 '막힘' 절과 검색어, 1번뿐이면 없다. 판정은 그대로 FAIL
    h2 = [{'시각': 't1', '진단': [['귀', '그림 모순']]}, {'시각': 't2', '진단': [['귀', '그림 모순'], ['머리', '모델링 오차']]}]
    v3, t3 = ML.card(RR, '머리', [], history=h2)
    v4, t4 = ML.card(RR, '머리', [], history=h2[-1:])
    sec = t3.split('## 막힘: 조사 단계')[1] if '## 막힘: 조사 단계' in t3 else ''
    ok('조사 단계: 같은 진단 2번 연속이면 막힘 절·검색어·2번 연속 표시, 판정 FAIL 유지',
       v3 == 'FAIL' and ML.stuck(h2) == [('귀', '그림 모순')] and 'inconsistent multi-view drawings' in sec and '2번 연속' in sec and sec.count('\n- inconsistent') + sec.count('\n- ') >= 2,
       '막힘 %s' % ML.stuck(h2))
    ok('조사 단계: 기록 한 번뿐이면 막힘 절 없음', v4 == 'FAIL' and '## 막힘: 조사 단계' not in t4 and ML.stuck(h2[-1:]) == [], '')
    bad = RESULTS.count(False)
    print('\n3D 모델 검사 자체 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
