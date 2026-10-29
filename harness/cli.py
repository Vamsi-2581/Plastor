"""명령줄: 모든 명령은 '현재 버전 읽기 → 적용 → 측정 → 새 버전 저장 → 짧은 보고(20줄 이하)' 순서."""
import argparse
import os
import sys
import time

import numpy as np

from . import ops
from .export import read_obj, write_obj
from .measure import evaluate_gates, measure_mesh, summary_lines
from .pack import Pack, build_bison
from .session import Session
from .target_check import target_check
from .util import ERROR, EXIT, FAIL, PASS, UNKNOWN, HarnessError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _zpair(v):
    return None if v is None else (float(v[0]), float(v[1]))


def build_parser():
    p = argparse.ArgumentParser(prog='mh.py', description='ModelerHarness v0.1')
    sub = p.add_subparsers(dest='cmd', required=True)

    def add(name, session=True, **kw):
        s = sub.add_parser(name, **kw)
        if session:
            s.add_argument('--session', required=True, help='세션 폴더(예: sessions/bison_a)')
        return s

    s = add('pack-build', session=False, help='들소 머리 팩 만들기(도면 webp 는 blender -b 로 한 번 읽어 .npy 캐시)')
    s.add_argument('--no-drawing', action='store_true')
    s = add('init'); s.add_argument('--pack', required=True); s.add_argument('--rings', type=int); s.add_argument('--z', type=float, nargs=2); s.add_argument('--n', type=float, default=2.5)
    s = add('fit'); s.add_argument('--view', required=True); s.add_argument('--z', type=float, nargs=2); s.add_argument('--strength', type=float, default=1.0); s.add_argument('--blend', type=int, default=0)
    s = add('snap'); s.add_argument('name'); s.add_argument('--falloff', type=float, default=0.15)
    s = add('round'); s.add_argument('--z', type=float, nargs=2, required=True); s.add_argument('--n', type=float, required=True)
    s = add('narrow'); s.add_argument('--part'); s.add_argument('--z', type=float, nargs=2); s.add_argument('--width', type=float); s.add_argument('--from-landmark', dest='from_landmark')
    s = add('shift'); s.add_argument('--z', type=float, nargs=2, required=True); s.add_argument('--dy', type=float, default=0.0); s.add_argument('--tilt', type=float, default=0.0)
    s = add('add_ring'); s.add_argument('--z', type=float, required=True)
    s = add('remove_ring'); s.add_argument('--i', type=int, required=True)
    s = add('smooth'); s.add_argument('--z', type=float, nargs=2, required=True); s.add_argument('--k', type=float, default=0.5)
    add('undo')
    s = add('goto'); s.add_argument('version')
    add('log')
    s = add('measure'); s.add_argument('--full', action='store_true')
    s = add('gate'); s.add_argument('stage', nargs='?', default='all')
    s = add('show'); s.add_argument('--views', default='front,side,back,q34')
    s = add('export'); s.add_argument('--obj', required=True); s.add_argument('--project')
    s = add('compare-obj'); s.add_argument('--obj', required=True); s.add_argument('--ynb', default='best'); s.add_argument('--out')
    s = add('sheet'); s.add_argument('--out'); s.add_argument('--obj')
    add('stats')
    return p


def _report(ses, cage, version=None, save=True):
    V, F, info = cage.mesh()
    rep = measure_mesh(V, F, ses.pack, cage, version)
    if not hasattr(ses.pack, '_tc'):
        ses.pack._tc = target_check(ses.pack)          # 목표만의 검사라 메시와 무관, 한 번만
    rep['target_check'] = ses.pack._tc
    gates = evaluate_gates(rep, ses.gates)
    rep['gates'] = gates
    if save:
        ses.save_report(rep, version)
    return rep, gates, (V, F, info)


def _summary(rep, gates):
    return {'iou': rep['iou'], 'band_max': rep['band_max'].get('value'),
            'landmarks': {x['name']: round(x['dist'], 4) for x in rep['landmarks'] if 'dist' in x},
            'volume34': rep['volume34_summary'], 'tris': rep['mesh']['tris'],
            'gates': {k: v['verdict'] for k, v in gates.items()}}


def _print(lines):
    for ln in lines:
        print(ln)


def _argstr(ns, skip=('cmd', 'session')):
    out = []
    for k, v in vars(ns).items():
        if k in skip or v is None or v is False:
            continue
        out.append('--%s %s' % (k, ' '.join(map(str, v)) if isinstance(v, (list, tuple)) else v) if k != 'name' else str(v))
    return ' '.join(out)


def run(argv):
    t0 = time.time()
    p = build_parser()
    ns = p.parse_args(argv)
    cmd = ns.cmd
    try:
        return _dispatch(ns, argv, t0)
    except HarnessError as e:
        print('ERROR: %s' % e)
        if getattr(ns, 'session', None) and os.path.exists(os.path.join(ns.session, 'state.json')):
            try:
                Session(ns.session).log(cmd, argv, {'verdict': ERROR, 'why': str(e)}, time.time() - t0)
            except Exception:
                pass
        return EXIT[ERROR]


def _dispatch(ns, argv, t0):
    cmd = ns.cmd
    if cmd == 'pack-build':
        path = build_bison(ROOT) if not ns.no_drawing else __import__('harness.pack', fromlist=['x']).build_pack(
            os.path.join(ROOT, 'fixtures', 'bison_head'), os.path.join(ROOT, 'packs', 'bison_head'),
            __import__('harness.pack', fromlist=['x']).BISON_SPEC, with_drawing=False)
        P = Pack(path)
        print('팩 생성: %s (윤곽 행 %d개 z%.2f~%.2f, 꼭대기 %.2f, 랜드마크 %s)' % (path, len(P.z), P.z[0], P.z[-1], P.top_z, ', '.join(P.landmarks)))
        print('도면 정면·뒤 반폭 차이 최대 %.3fH (도면 불일치, 폭 목표는 평균)' % P.fb_gap.max())
        return 0

    if cmd == 'init':
        pack = Pack(ns.pack)
        cage, info = ops.op_init(pack, ns.rings, _zpair(ns.z), ns.n)
        wall = time.time() - t0
        tmp = Session.__new__(Session)                 # 보고 계산용 임시(세션 만들기 전에 측정)
        tmp.pack, tmp.gates, tmp.dir = pack, None, ''
        V, F, _ = cage.mesh()
        rep = measure_mesh(V, F, pack, cage, 'v000')
        pack._tc = target_check(pack)
        rep['target_check'] = pack._tc
        gates = evaluate_gates(rep, None)
        ses = Session.create(ns.session, ns.pack, cage, {'cmd': cmd, 'args': argv, 'summary': {**_summary(rep, gates), 'info': info}, 'wall': wall})
        rep['gates'] = gates
        ses.save_report(rep, 'v000')
        print('[v000] init → 고리 %d개 z%.2f~%.2f' % (info['고리'], *info['높이']))
        _print(summary_lines(rep, gates))
        return 0

    ses = Session(ns.session)
    cage = ses.load_cage()
    pack = ses.pack

    mutating = {
        'fit': lambda: ops.op_fit(cage, pack, ns.view, _zpair(ns.z), ns.strength, ns.blend),
        'snap': lambda: ops.op_snap(cage, pack, ns.name, ns.falloff),
        'round': lambda: ops.op_round(cage, _zpair(ns.z), ns.n),
        'narrow': lambda: ops.op_narrow(cage, pack, ns.part, ns.width, ns.from_landmark, _zpair(ns.z)),
        'shift': lambda: ops.op_shift(cage, _zpair(ns.z), ns.dy, ns.tilt),
        'add_ring': lambda: ops.op_add_ring(cage, ns.z),
        'remove_ring': lambda: ops.op_remove_ring(cage, ns.i),
        'smooth': lambda: ops.op_smooth(cage, _zpair(ns.z), ns.k),
    }
    if cmd in mutating:
        new, info = mutating[cmd]()
        rep0 = None
        vid_next = 'v%03d' % len(ses.state['versions'])
        rep, gates, _ = _report(ses, new, vid_next, save=False)
        wall = time.time() - t0
        vid = ses.commit(new, cmd, argv, {**_summary(rep, gates), 'info': info}, wall)
        ses.save_report(rep, vid)
        print('[%s] %s %s → %s' % (vid, cmd, _argstr(ns), ', '.join('%s=%s' % kv for kv in info.items())))
        _print(summary_lines(rep, gates))
        return 0

    if cmd == 'undo':
        v = ses.undo()
        c = ses.load_cage()
        ses.log('undo', argv, {}, time.time() - t0, version=v, hash=c.hash())
        print('[%s] undo → 현재 버전 %s (해시 %s)' % (v, v, c.hash()))
        return 0
    if cmd == 'goto':
        ses.move(ns.version)
        c = ses.load_cage()
        ses.log('goto', argv, {}, time.time() - t0, version=ns.version, hash=c.hash())
        print('[%s] goto → 현재 버전 %s (해시 %s)' % (ns.version, ns.version, c.hash()))
        return 0
    if cmd == 'log':
        cur = ses.current_id()
        for r in ses.read_log():
            s = r.get('summary', {})
            g = s.get('gates')
            print('%s %-11s %s %s%s' % (r.get('version', '    -'), r['cmd'], r.get('hash', '')[:8], ' '.join(r['args'][1:3]) if r['args'] else '',
                  ' G1-4=' + '/'.join(v[0] for v in g.values()) if g else ''))
        print('현재 버전 %s' % cur)
        return 0
    if cmd == 'measure':
        rep, gates, _ = _report(ses, cage, ses.current_id())
        ses.log('measure', argv, _summary(rep, gates), time.time() - t0, version=ses.current_id())
        print('[%s] measure' % ses.current_id())
        _print(summary_lines(rep, gates))
        if ns.full:
            print('높이 띠 오차 (모델-도면, H): z  정면  뒤  옆앞  옆뒤  부위  고리')
            for b in rep['bands']:
                if b.get('missing'):
                    continue
                print(' %.2f %+.3f %+.3f %+.3f %+.3f %s %s' % (b['z'], b['front']['e'], b['back']['e'], b['side_f']['e'], b['side_b']['e'], b['part'], b['rings']))
            print('3/4 비율(45° 폭/상자 상한, 타원 하한): ' + ' '.join('z%.2f:%.2f(%.2f)' % (v['z'], v['ratio'], v['ellipse']) for v in rep['volume34']))
        return 0
    if cmd == 'gate':
        rep, gates, _ = _report(ses, cage, ses.current_id())
        stages = list(gates) if ns.stage == 'all' else [ns.stage.upper()]
        worst = PASS
        for st in stages:
            if st not in gates:
                raise HarnessError('관문 %s 가 없다(G1~G4)' % st)
            g = gates[st]
            print('%s %s: %s' % (st, g['verdict'], g['why']))
            if 'values' in g:
                print('   값: ' + ', '.join('%s=%s' % (k, ('%.4f' % v) if isinstance(v, float) else v) for k, v in g['values'].items()))
            order = [PASS, UNKNOWN, FAIL, ERROR]
            if order.index(g['verdict']) > order.index(worst):
                worst = g['verdict']
        ses.log('gate', argv, {'gates': {k: gates[k]['verdict'] for k in stages}}, time.time() - t0, version=ses.current_id())
        return EXIT[worst]
    if cmd == 'show':
        from . import render
        rep, gates, (V, F, info) = _report(ses, cage, ses.current_id())
        out = os.path.join(ses.dir, 'show_%s.png' % ses.current_id())
        render.show(ses.pack, V, F, rep, out, [v.strip() for v in ns.views.split(',')])
        ses.log('show', argv, {'out': out}, time.time() - t0, version=ses.current_id())
        print('겹침 그림 저장: %s (빨강=모델 외곽, 초록=도면 윤곽 목표, 띠 색=오차 초록<0.03<노랑<0.05<주황<0.10<빨강)' % out)
        return 0
    if cmd == 'export':
        V, F, info = cage.mesh()
        write_obj(ns.obj, V, F, ns.project, header='세션 %s %s 해시 %s' % (os.path.basename(ses.dir), ses.current_id(), cage.hash()))
        ses.log('export', argv, {'obj': ns.obj, 'project': ns.project}, time.time() - t0, version=ses.current_id())
        print('내보냄: %s (정점 %d 삼각형 %d%s)' % (ns.obj, len(V), len(F), ' 단위=' + ns.project if ns.project else ' 단위=H'))
        return 0
    if cmd == 'compare-obj':
        from . import oldhead
        txt = oldhead.compare(ses, cage, ns.obj, ns.ynb, ns.out)
        ses.log('compare-obj', argv, {'out': ns.out}, time.time() - t0, version=ses.current_id())
        print(txt)
        return 0
    if cmd == 'sheet':
        from . import blender_render
        out = ns.out or os.path.join(ses.dir, 'sheet_%s.png' % ses.current_id())
        blender_render.sheet(ses, cage, out, ns.obj)
        ses.log('sheet', argv, {'out': out}, time.time() - t0, version=ses.current_id())
        print('Eevee 4방향 렌더(도면 옆): %s' % out)
        return 0
    if cmd == 'stats':
        rows = ses.read_log()
        mut = [r for r in rows if r['cmd'] in ('init', 'fit', 'snap', 'round', 'narrow', 'shift', 'add_ring', 'remove_ring', 'smooth')]
        wall = sum(r.get('wall_s', 0) for r in rows)
        print('명령 %d개(모양을 바꾼 것 %d개), 명령 실행 시간 합계 %.1f초, 시작 %s 마지막 %s' % (len(rows), len(mut), wall, rows[0]['ts'], rows[-1]['ts']))
        return 0
    raise HarnessError('알 수 없는 명령 ' + cmd)
