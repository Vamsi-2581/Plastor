# -*- coding: utf-8 -*-
"""3D 정답 크리처 생성기 v2 시험(docs/설계_러스트.md 7.1, 기준은 돌리기 전에 적음).
  (가) 같은 씨앗 → 같은 파일 지문, (나) 정답 메시가 닫힌 한 덩어리,
  (다) 오류 없는 과제에서 정답 마스크와 정답 메시 투영의 IoU ≥ 0.99(정면·옆),
  (라) 오류 주입 과제(side_height·twin)는 옆 도면 전경이 정답 메시 투영과 IoU < 0.97, 정면은 ≥ 0.99.
      도면 전경은 생성기가 낸 '그린 것' 마스크(drawn_all.npz, 정답 마스크와 같은 '절반 이상' 규칙)로 잰다.
      처음엔 '배경색과 다른 픽셀'로 쟀는데, 반쯤 덮인 가장자리 픽셀까지 들어가 0.5px 뚱뚱했다(시험 방식 결함, 기준 숫자는 그대로).
  (마) 투영 v2(수정_기록 48): 같은 정답 메시를 칸 0.01·0.005·0.0025H 로 비춰도 정답 마스크와 IoU ≥ 0.99(정면·옆).
실행: python tests/selftest_rust_scene.py (끝 코드 0 = PASS). 먼저 cd rust && cargo build --release"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
MH = os.path.join(ROOT, 'rust', 'target', 'release', 'mh.exe' if os.name == 'nt' else 'mh')
RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def mh(tool, args):
    r = subprocess.run([MH, tool, json.dumps(args, ensure_ascii=False)], capture_output=True, text=True, encoding='utf-8')
    return json.loads(r.stdout)


def h(path):
    return hashlib.sha1(open(path, 'rb').read()).hexdigest()[:12]


def proj_iou(d, masks_from_drawing=False, voxel=0.01):
    """정답 메시(gt.obj) 투영 대 (정답 마스크 합집합 | 도면 전경) IoU, 정면·옆."""
    from build import Frame
    from harness.model_check import iou, load_obj, project, voxelize
    fr = Frame.load({'meta': os.path.join(d, 'meta.json')}, ROOT)
    V, F = load_obj(os.path.join(d, 'gt.obj'))
    occ, lo = voxelize(V, F, voxel)
    out = {}
    z = np.load(os.path.join(d, 'drawn_all.npz' if masks_from_drawing else 'truth_all.npz'))
    M = {tuple(k.split('|')): z[k] for k in z.files}
    z.close()
    for v in ('front', 'side'):
        ref = np.any([m for (vv, p), m in M.items() if vv == v], 0)
        out[v] = iou(project(occ, lo, voxel, fr, v, ref.shape), ref)
    return out


def main():
    tmp = tempfile.mkdtemp()
    a, b = os.path.join(tmp, 'a'), os.path.join(tmp, 'b')
    mh('scene', {'out': a, 'seed': 901})
    mh('scene', {'out': b, 'seed': 901})
    fs = ['drawing.npy', 'truth_all.npz', 'prims.json', 'gt.obj']
    ok('(가) 같은 씨앗 → 같은 지문', all(h(os.path.join(a, f)) == h(os.path.join(b, f)) for f in fs), str([h(os.path.join(a, f)) for f in fs]))
    from harness.model_check import load_obj, merged_check
    mc = merged_check(*load_obj(os.path.join(a, 'gt.obj')))
    ok('(나) 정답 메시가 닫힌 한 덩어리', mc['몸_수'] == 1 and mc['닫힘'], '몸 %d 닫힘 %s' % (mc['몸_수'], mc['닫힘']))
    r = proj_iou(a)
    ok('(다) 정답 마스크와 정답 메시 투영 IoU ≥ 0.99', min(r.values()) >= 0.99, str({k: round(v, 4) for k, v in r.items()}))
    det = []
    good = True
    for inj in ('side_height', 'twin'):
        d = os.path.join(tmp, inj)
        mh('scene', {'out': d, 'seed': 902, 'inject': inj})
        q = proj_iou(d, masks_from_drawing=True)
        good &= q['side'] < 0.97 and q['front'] >= 0.99
        det.append('%s 정면 %.4f 옆 %.4f' % (inj, q['front'], q['side']))
    ok('(라) 오류 주입은 옆만 달라짐(옆 < 0.97, 정면 ≥ 0.99)', good, ' | '.join(det))
    rr = {vx: proj_iou(a, voxel=vx) for vx in (0.01, 0.005, 0.0025)}
    ok('(마) 투영 v2: 칸 세 크기 모두 IoU ≥ 0.99', all(min(x.values()) >= 0.99 for x in rr.values()),
       ' | '.join('%g: %.4f/%.4f' % (vx, x['front'], x['side']) for vx, x in rr.items()))
    bad = RESULTS.count(False)
    print('\n생성기 v2 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
