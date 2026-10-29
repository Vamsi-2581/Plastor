# -*- coding: utf-8 -*-
"""M0 합성 과제 부위별 부피 진단: 정답 마스크 헐·가림 헐·트레이스 헐·하네스 모델을 정답(타원체 합집합 칸)과 비교.
사용: python bench/diag_part_volume.py synth_basic synth_twotone"""
import sys, os, numpy as np
sys.path.insert(0, '.'); sys.path.insert(0, 'bench')
import m0
from build import Frame
from harness.hull import build_hull
from harness.model_check import load_obj, voxelize
vx = 0.01
def vol_iou(V, F, P, names):
    """정답은 겹친 타원체의 합집합 칸으로 센다(부피를 더하면 겹친 곳이 여러 번 세어짐). 반환 (IoU, 정답 덮은 비율, 모델/정답 칸 비)."""
    occ, lo = voxelize(V, F, vx)
    Q = [p for p in P if p['part'] in names]
    glo = np.minimum(lo, np.min([p['c'] - p['r'] for p in Q], 0)) - 2 * vx
    ghi = np.maximum(lo + np.array(occ.shape) * vx, np.max([p['c'] + p['r'] for p in Q], 0)) + 2 * vx
    gs = np.ceil((ghi - glo) / vx).astype(int)
    mine = np.zeros(gs, bool)
    o = np.round((lo - glo) / vx).astype(int)
    mine[o[0]:o[0] + occ.shape[0], o[1]:o[1] + occ.shape[1], o[2]:o[2] + occ.shape[2]] = occ
    pts = glo + (np.indices(gs).reshape(3, -1).T + 0.5) * vx
    gt = np.zeros(len(pts), bool)
    for p in Q:
        gt |= (((pts - p['c']) / p['r']) ** 2).sum(1) <= 1
    gt = gt.reshape(gs)
    return (mine & gt).sum() / max((mine | gt).sum(), 1), (mine & gt).sum() / max(gt.sum(), 1), mine.sum() / max(gt.sum(), 1)
for t in sys.argv[1:]:
    seed, opt = m0.SYNTH_ALL[t]
    P = m0._prims(seed, opt)
    fr = Frame.load({'meta': 'bench/m0/%s/meta.json' % t}, '.')
    z = np.load('bench/m0/%s/truth.npz' % t); TR = {tuple(k.split('|')): z[k] for k in z.files}
    z = np.load('bench/m0/%s/base2/masks.npz' % t); TC = {tuple(k.split('|')): z[k] for k in z.files}
    for part, names, f in [('머리', ('머리',), 'body.obj'), ('뿔', ('뿔', '뿔 밑동'), 'part_뿔.obj'), ('귀', ('귀',), 'part_귀.obj')]:
        def mk(M):
            ks = [k for k in names]
            mf = np.any([M[('front', k)] for k in ks if ('front', k) in M], 0); ms = np.any([M[('side', k)] for k in ks if ('side', k) in M], 0)
            V, F, _ = build_hull(fr, mf, ms, voxel=0.008, smooth=0, master='front')
            return vol_iou(V, F, P, names)
        allv = lambda M, v: np.any([m for (vv, k), m in M.items() if vv == v and k != part and k not in names], 0)
        def mk_occ(M):
            ks = names
            mf = np.any([M[('front', k)] for k in ks if ('front', k) in M], 0); ms = np.any([M[('side', k)] for k in ks if ('side', k) in M], 0)
            V, F, _ = build_hull(fr, mf, ms, voxel=0.008, smooth=0, master='front', occl_front=allv(M, 'front'), occl_side=allv(M, 'side'))
            return vol_iou(V, F, P, names)
        V, F = load_obj('bench/m0/%s/base2/%s' % (t, f))
        r = [mk(TR), mk_occ(TR), mk(TC), vol_iou(V, F, P, names)]
        print(t, part, ' | '.join('%s IoU %.2f 덮음 %.2f 크기 %.2f' % (n, a, b, c) for n, (a, b, c) in zip(['정답마스크 헐', '가림헐', '트레이스 헐', '하네스'], r)))
