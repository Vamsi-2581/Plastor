r"""자체 시험 (설계서 "최종 범위" 2번). 끝 코드 0 = PASS.

정답 도형(타원체 + 코 돌기)의 정면·옆 직교 래스터를 목표 도면 마스크로 삼는다.
핸들(Hook·Lattice)을 알려진 양만큼 틀어 망가뜨린 도형에서 시작해, fitloop 이 도면 마스크만 보고 되돌리는지 본다.
확인: 코끝 오차 감소, 알려진 이동량 복구(10% 안), 대상 밖 보존, 체크포인트 복원(undo), 결정론, 반복 기록 항목, 하드코딩 금지.

실행: "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" tests/selftest.py
(내부에서 blender -b -P fitloop.py 를 부른다. 새 설치 없음.)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import fitloop  # noqa: E402  (bpy 는 함수 안에서만 불러서 Blender 밖에서도 import 된다)

BLENDER = os.environ.get('BLENDER') or r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
RESULTS = []

# 합성 도면 틀(임의 값): 1H = 0.5 블렌더 단위, 1H = 150px
FRAME = {'H_bu': 0.5, 'px_per_H': 150.0, 'ground_row': 650.0, 'shape': [700, 900], 'xc': {'front': 300.0, 'side': 600.0}}
SABOTAGE = {'hook_dy': -0.30, 'hook_dz': 0.25, 'lat_sx': 0.50}       # 알려진 틀어짐(H 단위, 배율-1)


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok)))
    print('%s %s %s' % ('PASS' if ok else 'FAIL', name, detail))


def blender(*args):
    r = subprocess.run([BLENDER, '-b', '-P', os.path.join(ROOT, 'fitloop.py'), '--'] + list(args), capture_output=True, text=True, encoding='utf-8', errors='replace')
    lines = [x for x in r.stdout.splitlines() if x.startswith('FITLOOP')]
    return r.returncode, lines, r.stdout + r.stderr


# ---------------------------------------------------------------- 정답 도형: 타원체 + 코 돌기 (H 단위 → 블렌더 단위)
def truth_mesh(nu=40, nv=24, bump=0.5, sigma=0.5, elev=-30.0):
    U = []
    for j in range(1, nv):
        th = np.pi * j / nv
        for i in range(nu):
            ph = 2 * np.pi * i / nu
            U.append([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)])
    U.append([0, 0, 1])
    U.append([0, 0, -1])
    U = np.array(U)
    F = []
    for j in range(nv - 2):
        for i in range(nu):
            a, b = j * nu + i, j * nu + (i + 1) % nu
            c, d = (j + 1) * nu + i, (j + 1) * nu + (i + 1) % nu
            F += [(a, c, d), (a, d, b)]
    top, bot = len(U) - 2, len(U) - 1
    for i in range(nu):
        F.append((top, i, (i + 1) % nu))
        F.append((bot, (nv - 2) * nu + (i + 1) % nu, (nv - 2) * nu + i))
    F = np.array(F)
    C = np.array([0, 0.3, 2.0])
    ax = np.array([0.6, 0.8, 0.9])
    P = C + U * ax
    n = U / ax
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    b = np.array([0, np.cos(np.radians(elev)), np.sin(np.radians(elev))])
    ang = np.arccos(np.clip(U @ b, -1, 1))
    P = P + n * (bump * np.exp(-ang ** 2 / (2 * sigma ** 2)))[:, None]
    vol = np.einsum('ij,ij->i', P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum()
    if vol < 0:
        F = F[:, ::-1]
    return P * FRAME['H_bu'], F


def write_obj(path, V, F):
    with open(path, 'w', newline='\n') as f:
        for p in V:
            f.write('v %.7f %.7f %.7f\n' % tuple(p))
        for a, b, c in F:
            f.write('f %d %d %d\n' % (a + 1, b + 1, c + 1))


def make_spec(tmp, name, out):
    Vt, Ft = truth_mesh()
    obj = os.path.join(tmp, 'truth.obj')
    write_obj(obj, Vt, Ft)
    fitloop.set_frame(FRAME)
    masks = fitloop.masks_of(Vt, Ft, FRAME, ['front', 'side'])
    for v, m in masks.items():
        np.save(os.path.join(tmp, 'target_%s.npy' % v), m)
    nose = {'rule': 'extreme', 'view': 'side', 'dir': '+Y', 'z': [1.2, 2.0]}
    spec = {
        'frame': FRAME, 'mesh_obj': obj, 'mesh_object': 'head', 'out': out,
        'target_masks': {v: os.path.join(tmp, 'target_%s.npy' % v) for v in ('front', 'side')},
        'handles': [
            {'name': 'CTRL_코끝', 'kind': 'hook', 'axes': 'yz', 'select': {'rule': nose, 'radius': 0.9}, 'init': {'y': SABOTAGE['hook_dy'], 'z': SABOTAGE['hook_dz']}},
            {'name': 'LATTICE_주둥이', 'kind': 'lattice', 'axes': 'x', 'select': {'rule': nose, 'center_offset': [0, -0.2, -0.27], 'size': [1.8, 1.1, 0.9]}, 'init': {'x': SABOTAGE['lat_sx']}},
        ],
        'metrics': [
            {'name': '코끝', 'kind': 'extreme', 'view': 'side', 'dir': '+Y', 'z': [1.2, 2.0]},
            {'name': '주둥이폭', 'kind': 'width', 'view': 'front', 'z': 1.4},
        ],
        'protected': [
            {'name': '뒤통수', 'kind': 'edge', 'view': 'side', 'z': 2.0, 'edge': 'lo'},
            {'name': '윗머리폭', 'kind': 'width', 'view': 'front', 'z': 2.6},
            {'name': '윗머리앞', 'kind': 'edge', 'view': 'side', 'z': 2.6, 'edge': 'hi'},
        ],
        'report': [{'name': 'IoU옆', 'kind': 'iou', 'view': 'side', 'z': [1.0, 3.0]}, {'name': 'IoU정면', 'kind': 'iou', 'view': 'front', 'z': [1.0, 3.0]}],
        'step_frac': 0.5, 'tol': 0.008, 'max_steps': 10,
    }
    return spec


def main():
    tmp = tempfile.mkdtemp(prefix='fitloop_selftest_')
    try:
        # 0) 환경
        code, lines, raw = blender('doctor')
        check('doctor 전부 PASS', code == 0 and any('판정 PASS' in x for x in lines), lines[-1] if lines else raw[-200:])

        # 1) 하드코딩 금지: fitloop.py 에 특정 도면 틀 숫자·크리처 이름이 없다
        src = open(os.path.join(ROOT, 'fitloop.py'), encoding='utf-8').read()
        bad = [t for t in ('150.5', '943', '0.598', '321.5', '751.5', '1536', '들소', 'bison_bp', 'Keratoura') if t in src]
        check('fitloop.py 에 들소 전용 숫자·이름 없음', not bad, '발견: %s' % bad if bad else 'grep 0건')

        # 2) 핸들 만들기(규칙 → 정점 그룹 → Hook·Lattice) + 틀어 놓기
        out1 = os.path.join(tmp, 'run1')
        spec = make_spec(tmp, 'head', out1)
        sp1 = os.path.join(tmp, 'spec1.json')
        json.dump(spec, open(sp1, 'w', encoding='utf-8'), ensure_ascii=False)
        code, lines, raw = blender('attach', sp1)
        att = json.load(open(os.path.join(out1, 'attach.json'), encoding='utf-8')) if os.path.exists(os.path.join(out1, 'attach.json')) else {}
        check('핸들 연결: 처음엔 메시가 안 움직임', code == 0 and att.get('핸들_연결_후_변화(BU)', 1) < 1e-5, '변화 %s' % att.get('핸들_연결_후_변화(BU)'))
        hs = att.get('handles', {})
        check('핸들 정점 그룹 기록(정점 수·bbox)', all(v.get('정점수', 0) > 0 and 'bbox_H' in v for v in hs.values()) and len(hs) == 2,
              ', '.join('%s %d개' % (k, v.get('정점수', 0)) for k, v in hs.items()))

        # 3) 반복 루프
        code, lines, raw = blender('run', sp1)
        summ_p = os.path.join(out1, 'summary.json')
        if not os.path.exists(summ_p):
            check('fitloop run 실행', False, raw[-400:])
            return finish()
        S = json.load(open(summ_p, encoding='utf-8'))
        recs = [json.loads(x) for x in open(os.path.join(out1, 'steps.jsonl'), encoding='utf-8') if x.strip()]
        check('fitloop run 실행', code == 0 and len(recs) >= 1, '걸음 %d, %.0f초' % (S['걸음_수'], S['걸린_시간_초']))
        e0 = np.hypot(S['시작_오차']['코끝_lat'], S['시작_오차']['코끝_z'])
        e1 = np.hypot(S['최종_오차']['코끝_lat'], S['최종_오차']['코끝_z'])
        check('코끝 오차가 시작값의 20% 이하(10걸음 이내)', e1 <= 0.2 * e0 and S['걸음_수'] <= 10, '%.4fH → %.4fH (%.0f%%), %d걸음' % (e0, e1, 100 * e1 / e0, S['걸음_수']))

        true_move = {'CTRL_코끝.dy': -SABOTAGE['hook_dy'], 'CTRL_코끝.dz': -SABOTAGE['hook_dz'], 'LATTICE_주둥이.sx': -SABOTAGE['lat_sx']}
        diffs = {k: abs(S['실제_이동량'][k] - v) / abs(v) for k, v in true_move.items()}
        check('알려진 정답 이동량을 10% 안으로 되찾음', all(d <= 0.10 for d in diffs.values()),
              ', '.join('%s 찾은 %+.3f / 정답 %+.3f (차이 %.1f%%)' % (k, S['실제_이동량'][k], v, 100 * diffs[k]) for k, v in true_move.items()))
        check('대상 밖 띠 오차 증가 ≤ 0.02H', S['대상밖_띠_최대_증가'] <= 0.02, '최대 증가 %.4fH' % S['대상밖_띠_최대_증가'])
        iou = S['IoU_전→후']
        check('옆·정면 IoU 가 수정 전보다 낮아지지 않음', all(b >= a - 1e-9 for a, b in iou.values()), ', '.join('%s %.3f→%.3f' % (k, a, b) for k, (a, b) in iou.items()))
        h_end = recs[-1]['부작용']['메시_전→후']
        check('메시 건전성 유지(열린 변·퇴화 면 0, 안쪽 면 증가 없음)', h_end[1]['열린_변'] == 0 and h_end[1]['퇴화_면'] == 0 and h_end[1]['안쪽_향한_면'] <= h_end[0]['안쪽_향한_면'] + 5,
              '전 %s 후 %s' % (h_end[0], h_end[1]))
        need = ['수정_대상', '수정전_오차', '핸들', '이동량', '수정후_오차', '부작용', '체크포인트']
        check('반복 기록에 7개 항목이 모두 있음', all(all(k in r for k in need) for r in recs), '걸음 %d개 × %s' % (len(recs), need))
        sums = [sum(abs(v) for v in r['수정후_오차'].values()) for r in recs]
        first = sum(abs(v) for v in recs[0]['수정전_오차'].values())
        check('반복에 따라 오차 합이 줄어듦(걸음마다 늘어도 픽셀 잡음 0.02H 이내, 끝은 처음의 20% 이하)',
              all(r_after <= r_before + 0.02 for r_after, r_before in zip(sums, [first] + sums[:-1])) and sums[-1] <= 0.2 * first,
              ' → '.join('%.3f' % x for x in [first] + sums))

        # 4) 체크포인트 복원(undo): 이전 단계 체크포인트를 열면 그 단계 정점 해시와 같다
        if len(recs) >= 2:
            prev = recs[-2]
            code, lines, raw = blender('hash', prev['체크포인트'], 'head')
            got = lines[-1].split()[-1] if lines else ''
            check('undo(체크포인트 복원) 후 정점 해시 = 이전 단계 해시', got == prev['vhash'], '%s == %s' % (got, prev['vhash']))
        code, lines, raw = blender('hash', os.path.join(out1, 'step00.blend'), 'head')
        got = lines[-1].split()[-1] if lines else ''
        check('시작 체크포인트 복원 해시 일치', got == att['step00']['vhash'], got)

        # 5) 결정론: 같은 시작 파일에서 한 번 더 → 최종 해시·오차표 동일
        out2 = os.path.join(tmp, 'run2')
        spec2 = dict(spec, out=out2, start_blend=os.path.join(out1, 'step00.blend'))
        sp2 = os.path.join(tmp, 'spec2.json')
        json.dump(spec2, open(sp2, 'w', encoding='utf-8'), ensure_ascii=False)
        code, lines, raw = blender('run', sp2)
        S2 = json.load(open(os.path.join(out2, 'summary.json'), encoding='utf-8')) if os.path.exists(os.path.join(out2, 'summary.json')) else {}
        check('같은 명령열 두 번 → 최종 해시·오차표 동일', S2.get('최종_vhash') == S['최종_vhash'] and S2.get('최종_오차') == S['최종_오차'],
              '%s / %s' % (S['최종_vhash'], S2.get('최종_vhash')))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return finish()


def finish():
    bad = [r for r in RESULTS if not r[1]]
    print('\n자체 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - len(bad)))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
