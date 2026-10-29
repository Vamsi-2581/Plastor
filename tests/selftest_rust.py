# -*- coding: utf-8 -*-
"""Rust 도구(rust/, docs/설계_러스트.md P1)를 파이썬판과 대조한다. 파이썬판이 기준이다.
기준(돌리기 전에 정함, 설계서 3장 P1):
  복셀화: 같은 OBJ 의 칸이 칸 단위로 같고 원점이 같음. 재투영 실루엣 IoU 차 0.
  헐: 같은 마스크로 만든 헐(직사각형·초타원 n=2)의 복셀 IoU ≥ 0.99, 트레이스 대비 실루엣 IoU 차 ≤ 0.005.
  속도는 기록만 한다(판정 아님).
실행: python tests/selftest_rust.py (끝 코드 0 = PASS). 먼저 cargo build --release (rust/)."""
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from build import Frame  # noqa: E402
from harness.hull import build_hull  # noqa: E402
from harness.model_check import iou, load_obj, project, _voxelize_py as voxelize  # noqa: E402  파이썬판이 기준
from harness.export import write_obj  # noqa: E402

MH = os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
RESULTS = []
CASES = [  # (이름, 틀 파일, 마스크, 본체 OBJ)
    ('합성 기본', 'bench/m0/synth_basic/meta.json', 'bench/m0/synth_basic/base2/masks.npz', 'bench/m0/synth_basic/base2/body.obj'),
    ('들소', 'packs/head_traced/pack.json', 'fixtures/bison_head/trace/out_v2/masks.npz', 'bench/m0/real_bison/base2/body.obj'),
    ('새 머리', 'fixtures/bird_head/trace_meta.json', 'fixtures/bird_head/out_sam/masks.npz', 'bench/m0/real_bird/base2/body.obj'),
]


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def mh(tool, args):
    r = subprocess.run([MH, tool, json.dumps(args, ensure_ascii=False)], capture_output=True, text=True, encoding='utf-8')
    return json.loads(r.stdout), r.returncode


def frame_of(p):
    return Frame.load({('pack' if 'pack' in p else 'meta'): os.path.join(ROOT, p)}, ROOT)


def main():
    if not os.path.exists(MH):
        print('ERROR Rust 바이너리 없음:', MH)
        return 3
    tmp = tempfile.mkdtemp()
    for name, fp, mp, obj in CASES:
        fr = frame_of(fp)
        z = np.load(os.path.join(ROOT, mp))
        M = {tuple(k.split('|')): z[k] for k in z.files}
        z.close()
        voxel = min(0.01, 1.5 / fr.ppH)
        # 1. 복셀화·재투영
        t = time.time()
        V, F = load_obj(os.path.join(ROOT, obj))
        occ, lo = voxelize(V, F, voxel)
        t_py = time.time() - t
        dump = os.path.join(tmp, 'd')
        r, code = mh('voxsil', {'frame': os.path.join(ROOT, fp), 'obj': os.path.join(ROOT, obj), 'masks': os.path.join(ROOT, mp), 'parts': ['머리'],
                               'voxel': voxel, 'dump': dump})
        if code != 0:
            ok('%s 복셀화' % name, False, str(r)[:300])
            continue
        ro = np.load(dump + '_occ.npy')
        same = ro.shape == occ.shape and bool((ro == occ).all()) and np.allclose(r['요약']['원점'], lo, atol=0, rtol=0)
        ok('%s 복셀화: 칸 단위로 같음' % name, same, '파이썬 %s %d칸 / Rust %s %d칸, 다른 칸 %s' % (
            occ.shape, occ.sum(), ro.shape, ro.sum(), int((ro != occ).sum()) if ro.shape == occ.shape else '모양 다름'))
        sil_ok = True
        det = []
        for v in ('front', 'side'):
            ref = M[(v, '머리')]
            pi = iou(project(occ, lo, voxel, fr, v, ref.shape), ref)
            ri = r['요약']['실루엣'].get(v)
            sil_ok &= ri is not None and abs(round(pi, 4) - ri) < 1e-9
            det.append('%s 파이썬 %.4f Rust %s' % (v, pi, ri))
        ok('%s 재투영: 실루엣 IoU 같음' % name, sil_ok, ', '.join(det))
        print('속도 %s 복셀화 파이썬 %.2f초 / Rust %.2f초' % (name, t_py, r['요약']['걸린초']['복셀화']))
        # 2. 헐(직사각형·초타원)
        for sec in (None, 2.0):
            t = time.time()
            Vp, Fp, _ = build_hull(fr, M[('front', '머리')], M[('side', '머리')], voxel=0.008, smooth=1.5, master='front', section_n=sec)
            t_py = time.time() - t
            out = os.path.join(tmp, 'h.obj')
            r, code = mh('hull', {'frame': os.path.join(ROOT, fp), 'masks': os.path.join(ROOT, mp), 'part': '머리', 'out': out,
                                  'voxel': 0.008, 'smooth': 1.5, 'master': 'front', 'section_n': sec})
            if code != 0:
                ok('%s 헐 n=%s' % (name, sec), False, str(r)[:300])
                continue
            Vr, Fr = load_obj(out)
            vv = min(0.01, 1.5 / fr.ppH)
            op, lp = voxelize(Vp, Fp, vv)
            orr, lr = voxelize(Vr, Fr, vv)
            # 같은 격자로 맞춰 비교
            g0 = np.minimum(lp, lr)
            sh = np.maximum(np.round((lp - g0) / vv).astype(int) + op.shape, np.round((lr - g0) / vv).astype(int) + orr.shape)
            A = np.zeros(sh, bool)
            B = np.zeros(sh, bool)
            a0 = np.round((lp - g0) / vv).astype(int)
            b0 = np.round((lr - g0) / vv).astype(int)
            A[a0[0]:a0[0] + op.shape[0], a0[1]:a0[1] + op.shape[1], a0[2]:a0[2] + op.shape[2]] = op
            B[b0[0]:b0[0] + orr.shape[0], b0[1]:b0[1] + orr.shape[1], b0[2]:b0[2] + orr.shape[2]] = orr
            vi = float((A & B).sum() / max((A | B).sum(), 1))
            ds = []
            for v in ('front', 'side'):
                ref = M[(v, '머리')]
                ds.append(abs(iou(project(op, lp, vv, fr, v, ref.shape), ref) - iou(project(orr, lr, vv, fr, v, ref.shape), ref)))
            ok('%s 헐 n=%s: 복셀 IoU ≥ 0.99, 실루엣 차 ≤ 0.005' % (name, sec), vi >= 0.99 and max(ds) <= 0.005,
               '복셀 IoU %.4f 실루엣 차 %.4f / %.4f, 시간 파이썬 %.2f초 Rust %.2f초' % (vi, ds[0], ds[1], t_py, r['요약']['걸린초']))
    bad = RESULTS.count(False)
    print('\nRust 대조 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
