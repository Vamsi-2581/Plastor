# -*- coding: utf-8 -*-
"""단계 5 리깅 준비 검사기 자체 시험. 끝 코드 0 = PASS.
(i) 공 하나 -> PASS  (ii) 떨어진 공 두 개 -> FAIL(덩어리 2)  (iii) 카드: rig PASS/FAIL/없음 -> PASS/FAIL/UNKNOWN
"""
import json
import math
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
BLENDER = os.path.join('C:' + os.sep, 'Program Files', 'Blender Foundation', 'Blender 5.2', 'blender.exe')
OUT = os.path.join(ROOT, 'bench', 'out', 'rig_test')
RESULTS = []


def ok(name, cond, detail=''):
    RESULTS.append(bool(cond))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, detail))


def sphere(c, r, nu=24, nv=16):
    """닫힌 UV 구(극점 2개 + 고리). (정점, 면)"""
    V = [(c[0], c[1], c[2] + r)]
    for j in range(1, nv):
        t = math.pi * j / nv
        for i in range(nu):
            p = 2 * math.pi * i / nu
            V.append((c[0] + r * math.sin(t) * math.cos(p), c[1] + r * math.sin(t) * math.sin(p), c[2] + r * math.cos(t)))
    V.append((c[0], c[1], c[2] - r))
    F = []
    for i in range(nu):
        F.append((0, 1 + i, 1 + (i + 1) % nu))
    for j in range(nv - 2):
        for i in range(nu):
            a, b = 1 + j * nu + i, 1 + j * nu + (i + 1) % nu
            F.append((a, a + nu, b + nu)); F.append((a, b + nu, b))
    last = len(V) - 1
    for i in range(nu):
        F.append((last, 1 + (nv - 2) * nu + (i + 1) % nu, 1 + (nv - 2) * nu + i))
    return V, F


def write_obj(path, balls):
    V, F = [], []
    for c, r in balls:
        v, f = sphere(c, r)
        F += [tuple(x + len(V) + 1 for x in t) for t in f]
        V += v
    with open(path, 'w') as fh:
        for v in V:
            fh.write('v %.6f %.6f %.6f\n' % v)
        for f in F:
            fh.write('f %d %d %d\n' % f)


def tube(x0, x1, r, z, nu=24, nx=12):
    """x 방향으로 뻗은 닫힌 관(양끝 덮개). (정점, 면)"""
    V = []
    for j in range(nx + 1):
        x = x0 + (x1 - x0) * j / nx
        for i in range(nu):
            p = 2 * math.pi * i / nu
            V.append((x, r * math.cos(p), z + r * math.sin(p)))
    V.append((x0, 0.0, z)); V.append((x1, 0.0, z))
    F = []
    for j in range(nx):
        for i in range(nu):
            a, b = j * nu + i, j * nu + (i + 1) % nu
            F.append((a, a + nu, b + nu)); F.append((a, b + nu, b))
    c0, c1 = len(V) - 2, len(V) - 1
    for i in range(nu):
        F.append((c0, (i + 1) % nu, i))
        F.append((c1, nx * nu + i, nx * nu + (i + 1) % nu))
    return V, F


def write_vf(path, parts_vf):
    V, F = [], []
    for v, f in parts_vf:
        F += [tuple(x + len(V) + 1 for x in t) for t in f]
        V += v
    with open(path, 'w') as fh:
        for v in V:
            fh.write('v %.6f %.6f %.6f\n' % tuple(v))
        for f in F:
            fh.write('f %d %d %d\n' % f)


def run_rig(obj, outj, parts=()):
    if os.path.exists(outj):
        os.remove(outj)
    cmd = [BLENDER, '-b', '-P', os.path.join(ROOT, 'harness', 'rig_check.py'), '--', obj, outj]
    if parts:
        cmd += ['--parts'] + list(parts)
    r = subprocess.run(cmd,
                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=300)
    return json.load(open(outj, encoding='utf-8')) if os.path.exists(outj) else {'판정': 'ERROR', '이유': [r.stdout[-300:]]}


def main():
    os.makedirs(OUT, exist_ok=True)
    one, two = os.path.join(OUT, 'one.obj'), os.path.join(OUT, 'two.obj')
    write_obj(one, [((0, 0, 1), 1.0)])
    write_obj(two, [((0, 0, 1), 1.0), ((5, 0, 1), 1.0)])
    r1 = run_rig(one, os.path.join(OUT, 'one.json'))
    ok('공 하나: PASS, 덩어리 1·열린변 0, 가중치0 비율 <= 0.01', r1['판정'] == 'PASS' and r1.get('덩어리') == 1 and r1.get('열린변') == 0
       and r1.get('가중치0_비율', 1) <= 0.01, json.dumps(r1, ensure_ascii=False))
    ok('공 하나: 비대칭도 보고(대칭이라 0.01 이하)', r1.get('비대칭도') is not None and r1['비대칭도'] <= 0.01, str(r1.get('비대칭도')))
    r2 = run_rig(two, os.path.join(OUT, 'two.json'))
    ok('떨어진 공 둘: FAIL, 덩어리 2', r2['판정'] == 'FAIL' and r2.get('덩어리') == 2, json.dumps(r2, ensure_ascii=False))
    # --parts: 공(본체) + 옆으로 길게 뻗은 관(부속). 부위 뼈를 줘도 자동 가중치가 실패하지 않고 둘 다 기준(0.01 이하)을 지킨다.
    # (이 합성 도형에서는 기본 뼈가 이미 관에 닿아 부위 뼈가 0.0→0.006 으로 조금 나쁘다. 이득은 들소 뿔에서만 확인: 0.032→0.0)
    ball_v, ball_f = sphere((0, 0, 1), 1.0)
    tube_v, tube_f = tube(0.8, 5.0, 0.25, 1.0)
    pb, pt, pm = (os.path.join(OUT, n) for n in ('ball.obj', 'tube.obj', 'ball_tube.obj'))
    write_vf(pb, [(ball_v, ball_f)])
    write_vf(pt, [(tube_v, tube_f)])
    write_vf(pm, [(ball_v, ball_f), (tube_v, tube_f)])
    r3 = run_rig(pm, os.path.join(OUT, 'bt_no.json'))
    r4 = run_rig(pm, os.path.join(OUT, 'bt_parts.json'), [pb, pt])
    ok('공+긴 관: --parts 를 줘도 자동 가중치가 실패하지 않고 둘 다 가중치0_비율 0.01 이하',
       r3.get('가중치0_비율') is not None and r4.get('가중치0_비율') is not None
       and r3['가중치0_비율'] <= 0.01 and r4['가중치0_비율'] <= 0.01,
       '없음 %s -> 있음 %s (정점그룹 %s)' % (r3.get('가중치0_비율'), r4.get('가중치0_비율'), r4.get('정점그룹수')))
    # 카드: 단계 1~4 진단이 없는 최소 입력
    import model_loop as ML
    RR = {'부위': {'머리': {'뷰': {}, '진단': []}}}
    v0, t0 = ML.card(RR, '머리')
    v1, t1 = ML.card(RR, '머리', rig={'판정': 'PASS', '덩어리': 1, '열린변': 0, '비대칭도': 0.0, '가중치0_비율': 0.0, '이유': []})
    v2, t2 = ML.card(RR, '머리', rig=r2)
    ok('카드: rig 없음 UNKNOWN / PASS 면 PASS·단계 5 통과 / FAIL 이면 FAIL·이유 포함',
       v0 == 'UNKNOWN' and v1 == 'PASS' and '단계 5 통과' in t1 and v2 == 'FAIL' and '단계 5. 리깅 준비' in t2 and '덩어리 2개' in t2, '%s %s %s' % (v0, v1, v2))
    bad = RESULTS.count(False)
    print('\n리깅 준비 자체 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - bad))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
