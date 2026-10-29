# -*- coding: utf-8 -*-
"""K1 채점 항목 시험(docs/구현계획_통합.md K1 기준 1~5, 돌리기 전에 적음).
실행: python tests/selftest_metrics.py (끝 코드 0 = PASS)"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'bench'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from harness import metrics as K  # noqa: E402
from harness.vendor import ndi  # noqa: E402,F401

RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def field_mesh(f, lo, voxel, level=0.0):
    from skimage.measure import marching_cubes
    v, fc, _, _ = marching_cubes(np.pad(f, 1, constant_values=f.min()), level)
    return lo + (v - 1) * voxel, fc[:, ::-1].copy()


def grid(lo, hi, voxel):
    ax = [np.arange(lo[k], hi[k], voxel) + voxel / 2 for k in range(3)]
    return np.meshgrid(*ax, indexing='ij'), np.array(lo, float)


def main():
    vx = 0.01
    (X, Y, Z), lo = grid((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), vx)
    # 1. 3/4 폭 비: 타원체(반지름 0.3·0.4·0.3) 대 같은 크기 상자
    ell = (X / 0.3) ** 2 + (Y / 0.4) ** 2 + (Z / 0.3) ** 2 <= 1
    box = (np.abs(X) <= 0.3) & (np.abs(Y) <= 0.4) & (np.abs(Z) <= 0.3)
    qe, qb = K.quarter_ratio(ell, vx), K.quarter_ratio(box, vx)
    ok('3/4 폭 비: 타원체 0.70~0.76, 상자 ≥ 0.97', 0.70 <= qe <= 0.76 and qb >= 0.97, '타원체 %.3f 상자 %.3f' % (qe, qb))
    # 2. 거칠기: 매끈한 구(거리장) 대 0.02H 칸 계단 구
    sd = 0.3 - np.sqrt(X ** 2 + Y ** 2 + Z ** 2)
    Vs, Fs = field_mesh(sd, lo, vx)
    (X2, Y2, Z2), lo2 = grid((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0.02)
    st = (X2 ** 2 + Y2 ** 2 + Z2 ** 2 <= 0.09).astype(float)
    Vt, Ft = field_mesh(st, lo2, 0.02, 0.5)
    rs, rt = K.roughness(Vs, Fs), K.roughness(Vt, Ft)
    # v1(이웃 면 각 평균)은 1차에서 FAIL(계단 9.45° < 10°)이라 버렸다. 판정에 세지 않고 값만 남긴다
    print('기록 거칠기 v1(버림): 매끈 %.2f° 계단 %.2f°' % (rs, rt))
    # 2b. 거칠기 v2(국소 평균 법선과의 각): 구 + 아직 안 본 타원체
    r2s, r2t = K.roughness_v2(Vs, Fs), K.roughness_v2(Vt, Ft)
    ee = 1 - np.sqrt((X / 0.3) ** 2 + (Y / 0.4) ** 2 + (Z / 0.25) ** 2)
    Ve, Fe = field_mesh(ee, lo, vx)
    (X3, Y3, Z3), lo3 = grid((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5), 0.015)
    et = (((X3 / 0.3) ** 2 + (Y3 / 0.4) ** 2 + (Z3 / 0.25) ** 2) <= 1).astype(float)
    Vu, Fu = field_mesh(et, lo3, 0.015, 0.5)
    r2e, r2u = K.roughness_v2(Ve, Fe), K.roughness_v2(Vu, Fu)
    ok('거칠기 v2: 매끈 구 < 5°, 계단 구 > 15°, 매끈 타원체 < 5°, 계단 타원체 > 15°', r2s < 5 and r2t > 15 and r2e < 5 and r2u > 15,
       '구 %.2f°/%.2f° 타원체 %.2f°/%.2f°' % (r2s, r2t, r2e, r2u))
    # 3. 랜드마크: 머리 타원체를 앞으로 0.05H 옮기면 코끝 잔차 0.05 ± 0.005, 안 옮기면 ≤ 0.01
    head = K.cell_points(ell, lo, vx)
    t = K.landmarks(head)
    r0 = K.landmark_residuals(K.landmarks(head), t)['코끝']
    r1 = K.landmark_residuals(K.landmarks(head + [0, 0.05, 0]), t)['코끝']
    ok('랜드마크: 옮김 0.05±0.005, 그대로 ≤ 0.01', abs(r1 - 0.05) <= 0.005 and r0 <= 0.01, '옮김 %.4f 그대로 %.4f' % (r1, r0))
    # 4. 부위 채점이 진단 스크립트와 같은 값(합성 기본 뿔 = 하네스 둥근 헐 part_뿔.obj, 정답 뿔+뿔 밑동, 0.01H)
    import m0
    from harness.model_check import load_obj, voxelize
    seed, opt = m0.SYNTH_ALL['synth_basic']
    P = m0._prims(seed, opt)
    V, F = load_obj(os.path.join(ROOT, 'bench/m0/synth_basic/base2/part_뿔.obj'))
    o, l = voxelize(V, F, 0.01)
    mine, gt, _ = K.common_grid(o, l, P, ('뿔', '뿔 밑동'), 0.01)
    v4 = float((mine & gt).sum() / max((mine | gt).sum(), 1))
    ok('부위 부피: 진단 스크립트와 같은 입력이면 0.35 ± 0.01', abs(v4 - 0.35) <= 0.01, '%.4f' % v4)
    # 5. M0 다시 채점: 지문·기존 점수 그대로(장부의 마지막 ②하네스 줄과 비교)
    rows = [json.loads(x) for x in open(os.path.join(ROOT, 'bench/m0/ledger.jsonl'), encoding='utf-8')]
    old = [r for r in rows if r['과제'] == 'synth_basic' and r['기준선'] == '②하네스'][-1]
    new = m0.score('synth_basic', os.path.join(ROOT, 'bench/m0/synth_basic/base2/merged.obj'), '시험_K1', 'selftest_metrics(장부 제외)')
    same = new['지문'] == old['지문'] and new['실루엣'] == old['실루엣'] and new['부피'] == old['부피']
    ok('M0 다시 채점: 지문·실루엣·부피 그대로', same, '지문 %s/%s 부피 %s/%s' % (old['지문'], new['지문'], old['부피'], new['부피']))
    bad = RESULTS.count(False)
    print('\nK1 채점 항목 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
