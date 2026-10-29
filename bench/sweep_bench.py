# -*- coding: utf-8 -*-
r"""휜 둥근 뿔 합성 시험: 헐 대 쓸기. 채택 기준(돌리기 전에 정함): 8개 평균에서
3D 부피 IoU(정답 대비) 쓸기 > 헐, 그리고 정면·옆 실루엣 IoU 가 헐보다 0.01 넘게 떨어지지 않음.
정답 뿔 = 휜 중심선(옆으로 뻗다가 위로 휨, 앞뒤로도 기울어짐)을 따라 반지름이 줄어드는 둥근 관. 좌우 한 쌍."""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from harness.hull import build_hull  # noqa: E402
from harness.model_check import iou, project, voxelize  # noqa: E402
from harness.sweep import build_round_hull, build_sweep  # noqa: E402


class FakePack:
    ppH = 100.0
    panels = {'front': {'center_x': 200.0, 'ground_row': 380.0, 'sign': -1}, 'side': {'center_x': 600.0, 'ground_row': 380.0, 'sign': -1}}

    def H_to_px(self, view, lat, z):
        p = self.panels[view]
        return p['center_x'] + p['sign'] * np.asarray(lat, float) * self.ppH, p['ground_row'] - np.asarray(z, float) * self.ppH

    def px_to_H(self, view, px, py):
        p = self.panels[view]
        return p['sign'] * (np.asarray(px, float) - p['center_x']) / self.ppH, (p['ground_row'] - np.asarray(py, float)) / self.ppH


def horn_volume(rng, vox):
    """정답 복셀(격자 원점 lo, 크기 vox)."""
    curl = rng.uniform(0.6, 1.4); fwd = rng.uniform(-0.25, 0.25); r0 = rng.uniform(0.07, 0.11); L = rng.uniform(0.7, 1.0)
    s = np.linspace(0, 1, 200)
    ang = curl * s * np.pi / 2
    cx = 0.2 + L * 0.6 * np.sin(ang + 0.3)
    cz = 3.0 + L * 0.6 * (1 - np.cos(ang + 0.3)) - L * 0.6 * (1 - np.cos(0.3))
    cy = fwd * s * L
    rad = r0 * (1 - 0.8 * s)
    C = np.stack([cx, cy, cz], 1)
    lo = C.min(0) - 0.15; hi = C.max(0) + 0.15
    lo[0] = -hi[0]
    xs, ys, zs = [np.arange(a, b, vox) + vox / 2 for a, b in zip(lo, hi)]
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing='ij')
    occ = np.zeros(X.shape, bool)
    for sign in (1, -1):
        for c, r in zip(C[::2], rad[::2]):
            cc = c * np.array([sign, 1, 1])
            occ |= (X - cc[0]) ** 2 + (Y - cc[1]) ** 2 + (Z - cc[2]) ** 2 <= r ** 2
    return occ, lo


def vol_iou(V, F, truth, lo, vox):
    o, l = voxelize(V, F, vox)
    G = np.zeros(truth.shape, bool)
    s = np.round((l - lo) / vox).astype(int)
    a0 = np.maximum(s, 0); b0 = np.minimum(s + np.array(o.shape), truth.shape)
    G[a0[0]:b0[0], a0[1]:b0[1], a0[2]:b0[2]] = o[a0[0] - s[0]:b0[0] - s[0], a0[1] - s[1]:b0[1] - s[1], a0[2] - s[2]:b0[2] - s[2]]
    return iou(G, truth)


def rough(V, F):
    """표면 거칠기: 이웃한 삼각형 법선 사이 각(도)의 평균. 복셀 계단이면 큼(trimesh)."""
    sys.path.append(os.path.join(ROOT, '.vendor'))
    import trimesh
    m = trimesh.Trimesh(V, F, process=True)
    return float(np.degrees(m.face_adjacency_angles).mean())


def main(n=8, seed0=0):
    pk, vox, shape = FakePack(), 0.01, (420, 800)
    rows = []
    for k in range(seed0, seed0 + n):
        rng = np.random.default_rng(500 + k)
        T, lo = horn_volume(rng, vox)
        tf, ts = project(T, lo, vox, pk, 'front', shape), project(T, lo, vox, pk, 'side', shape)
        Vh, Fh, _ = build_hull(pk, tf, ts, voxel=vox, smooth=1.0, master='front')
        Vs, Fs, info = build_round_hull(pk, tf, ts, root_point=(0, 0, 2.8), voxel=float(os.environ.get("RH_VOX", vox)), smooth=float(os.environ.get("RH_SMOOTH", "0")), taubin=int(os.environ.get("RH_TAUBIN", "0")), sdf_smooth=float(os.environ.get("RH_SDF", "0")), cesn=int(os.environ.get("RH_CESN", "0")))
        r = {}
        for nm, (V, F) in (('헐', (Vh, Fh)), ('쓸기', (Vs, Fs))):
            o, l = voxelize(V, F, vox)
            r[nm] = (vol_iou(V, F, T, lo, vox), iou(project(o, l, vox, pk, 'front', shape), tf), iou(project(o, l, vox, pk, 'side', shape), ts), rough(V, F))
        rows.append(r)
        print('SWEEP %d 부피 헐 %.3f 쓸기 %.3f | 정면 %.3f %.3f | 옆 %.3f %.3f | %s' % (k, r['헐'][0], r['쓸기'][0], r['헐'][1], r['쓸기'][1], r['헐'][2], r['쓸기'][2], info.get('고리')))
    m = {nm: np.mean([r[nm] for r in rows], 0) for nm in ('헐', '쓸기')}
    print('SWEEP 평균 부피 헐 %.3f 쓸기 %.3f | 정면 %.3f %.3f | 옆 %.3f %.3f | 거칠기 헐 %.1f 쓸기 %.1f' % (m['헐'][0], m['쓸기'][0], m['헐'][1], m['쓸기'][1], m['헐'][2], m['쓸기'][2], m['헐'][3], m['쓸기'][3]))
    ok = m['쓸기'][0] > m['헐'][0] and m['쓸기'][1] >= m['헐'][1] - 0.01 and m['쓸기'][2] >= m['헐'][2] - 0.01
    print('SWEEP 판정', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(*(int(a) for a in sys.argv[1:3])))
