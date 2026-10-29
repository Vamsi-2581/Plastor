# -*- coding: utf-8 -*-
"""fitloop.py — 도면 마스크만 보고 이름 있는 핸들(Hook·Lattice)을 움직여 메시 오차를 줄이는 반복 루프.

측정 → 민감도(핸들을 조금 움직여 지표 변화) → 이동량 계산 → Hook/Lattice 적용 → 재측정을 반복한다.
걸음마다 기록: 수정 대상, 수정 전 오차, 핸들, 이동량, 수정 후 오차, 부작용 검사, 체크포인트.

재사용: 변형은 Blender 내장 Hook·Lattice 수정자. 래스터·좌표는 fixtures/bison_head/ref_trace_iou.py·ref_trace_common.py.
이 파일에는 특정 크리처의 숫자·부위 이름이 없다(도면 틀·규칙·핸들은 모두 spec JSON 이 준다).

실행(Blender 안에서만 돈다):
  blender -b -P fitloop.py -- doctor
  blender -b -P fitloop.py -- attach <spec.json>   # OBJ → 규칙으로 정점 그룹 → 핸들 생성 → step00.blend
  blender -b -P fitloop.py -- run <spec.json>      # 반복 루프(체크포인트 stepNN.blend, steps.jsonl, summary.json)
  blender -b -P fitloop.py -- hash <file.blend> <메시이름>   # 체크포인트의 정점 해시(복원 검증)
"""
import hashlib
import importlib
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
_R = None


def ref():
    """재사용 모듈(ref_trace_iou 의 raster·Scene)을 불러온다. 그 모듈이 `import trace_common` 을 하므로 이름을 맞춰 준다."""
    global _R
    if _R is None:
        fx = os.path.join(HERE, 'fixtures', 'bison_head')
        sys.path.insert(0, fx)
        sys.modules['trace_common'] = importlib.import_module('ref_trace_common')
        _R = importlib.import_module('ref_trace_iou')
    return _R


def set_frame(fr):
    """도면 틀(패널 좌표) 값을 래스터 모듈에 넣는다: 1H=H_bu 블렌더 단위, px_per_H, 발바닥 행, 이미지 크기."""
    R = ref()
    R.S = fr['H_bu'] / fr['px_per_H']
    R.GROUND = fr['ground_row']
    R.SHAPE = tuple(fr['shape'])
    return R


def jload(p):
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def jdump(p, o):
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(o, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 측정: 마스크 → 지표 (도면과 모델에 같은 함수)
def masks_of(Vb, F, fr, views):
    """블렌더 좌표(X 오른쪽, Y 앞, Z 위, 단위 BU) 메시를 도면 패널 마스크로. raster 규약은 (x, 위 y, 앞 z)."""
    R = ref()
    Vr = np.stack([Vb[:, 0], Vb[:, 2], Vb[:, 1]], 1)
    sc = R.Scene()
    sc.add('m', Vr, F)
    return {v: R.raster(sc, v, fr['xc'][v]) for v in views}


def _row(fr, z):
    return int(math.floor(fr['ground_row'] - z * fr['px_per_H']))


def _lat(fr, view, px):
    return (fr['xc'][view] - px) / fr['px_per_H']          # + = 캐릭터 오른쪽(정면) / 앞(옆)


def _extents(mask, r):
    if r < 0 or r >= mask.shape[0]:
        return None
    c = np.flatnonzero(mask[r])
    return None if len(c) == 0 else (_lat_px(c[0]), _lat_px(c[-1] + 1))


def _lat_px(v):
    return float(v)


def eval_metrics(metrics, masks, fr):
    """metrics: edge(view,z,edge) / width(view,z) / extreme(view,dir,z[a,b]) / iou(view,z[a,b], target 마스크 필요)."""
    out = {}
    for m in metrics:
        view, kind = m['view'], m['kind']
        mk = masks[view]
        if kind in ('edge', 'width'):
            e = _extents(mk, _row(fr, m['z']))
            if e is None:
                out[m['name']] = float('nan')
                continue
            hi, lo = _lat(fr, view, e[0]), _lat(fr, view, e[1])
            out[m['name']] = (hi if m.get('edge', 'hi') == 'hi' else lo) if kind == 'edge' else hi - lo
        elif kind == 'extreme':
            z0, z1 = sorted(m['z'])
            rows = range(_row(fr, z1), _row(fr, z0) + 1)
            vals = []
            for r in rows:
                e = _extents(mk, r)
                if e is not None:
                    vals.append((r, _lat(fr, view, e[0]) if m['dir'][0] == '+' else _lat(fr, view, e[1])))
            if not vals:
                out[m['name'] + '_lat'] = out[m['name'] + '_z'] = float('nan')
                continue
            best = (max if m['dir'][0] == '+' else min)(v for _, v in vals)
            # 둥근 끝은 한 픽셀 안에 여러 행이 들어오므로, 극점에서 1픽셀 안의 행들의 가운데를 높이로 쓴다(행 하나의 동률 잡음을 줄임)
            rr = [r for r, v in vals if abs(v - best) <= 1.0 / fr['px_per_H'] + 1e-9]
            out[m['name'] + '_lat'] = best
            out[m['name'] + '_z'] = (fr['ground_row'] - (float(np.mean(rr)) + 0.5)) / fr['px_per_H']
    return out


def iou_band(mask_a, mask_b, fr, z):
    z0, z1 = sorted(z)
    r0, r1 = _row(fr, z1), _row(fr, z0) + 1
    a, b = mask_a[r0:r1], mask_b[r0:r1]
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 1.0


# ---------------------------------------------------------------- 정점 선택 규칙 (핸들 만들 때)
def pick_vertex(Vh, rule):
    """극점 규칙(옆 뷰 Y 극점 등)으로 정점 하나를 고른다. Vh: H 단위 블렌더 좌표."""
    lat = Vh[:, 1] if rule['view'] == 'side' else Vh[:, 0]
    z = Vh[:, 2]
    ok = np.ones(len(Vh), bool)
    if 'z' in rule:
        ok &= (z >= min(rule['z']) - 1e-9) & (z <= max(rule['z']) + 1e-9)
    if not ok.any():
        raise ValueError('규칙에 맞는 정점이 없다: %s' % rule)
    s = lat if rule['dir'][0] == '+' else -lat
    s = np.where(ok, s, -np.inf)
    best = s.max()
    cand = np.flatnonzero(s >= best - 1e-9)
    return int(cand[np.argmax(z[cand])])


def mesh_health(Vb, F):
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e.sort(axis=1)
    _, c = np.unique(e, axis=0, return_counts=True)
    a, b, cc = Vb[F[:, 0]], Vb[F[:, 1]], Vb[F[:, 2]]
    n = np.cross(b - a, cc - a)
    area = np.linalg.norm(n, axis=1)
    cen = (a + b + cc) / 3 - Vb.mean(0)
    return {'열린_변': int((c != 2).sum()), '퇴화_면': int((area < 1e-12).sum()),
            '안쪽_향한_면': int((np.einsum('ij,ij->i', n, cen) < 0).sum()),
            '부피': float(np.einsum('ij,ij->i', a, np.cross(b, cc)).sum() / 6)}


def vhash(Vb):
    return hashlib.sha256(np.round(Vb * 1e4).astype('<i8').tobytes()).hexdigest()[:16]


# ---------------------------------------------------------------- Blender 쪽 (bpy)
def _bpy():
    import bpy
    return bpy


def eval_mesh(obj):
    bpy = _bpy()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    a = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', a)
    ev.to_mesh_clear()
    return a.reshape(-1, 3)


def mesh_faces(obj):
    f = np.empty(len(obj.data.polygons) * 3, int)
    obj.data.polygons.foreach_get('vertices', f)
    return f.reshape(-1, 3)


def update():
    _bpy().context.view_layer.update()


class Param:
    """핸들 하나의 매개변수 하나. hook: 빈 객체 위치(H 단위 이동량), lattice: 한 축 배율-1."""

    def __init__(self, handle, axis, fr):
        self.handle, self.axis, self.fr = handle, axis, fr
        self.i = 'xyz'.index(axis)
        self.kind = handle['kind']
        self.name = '%s.%s' % (handle['name'], ('d' if self.kind == 'hook' else 's') + axis)
        # 민감도 걸음은 마스크 한 픽셀(1/px_per_H H)보다 충분히 커야 지표가 변한다: 핸들 이동은 약 8픽셀, 배율은 0.1
        self.delta = handle.get('delta', 8.0 / fr['px_per_H'] if self.kind == 'hook' else 0.1)
        self.limit = handle.get('limit', 1.0)

    def obj(self):
        return _bpy().data.objects[self.handle['name']]

    def get(self):
        o = self.obj()
        if self.kind == 'hook':
            return (o.location[self.i] - o['rest'][self.i]) / self.fr['H_bu']
        pts = [p for p in o.data.points if abs(p.co[self.i]) > 1e-9]
        return pts[0].co_deform[self.i] / pts[0].co[self.i] - 1.0

    def set(self, v):
        o = self.obj()
        if self.kind == 'hook':
            loc = list(o.location)
            loc[self.i] = o['rest'][self.i] + v * self.fr['H_bu']
            o.location = loc
        else:
            for p in o.data.points:
                cd = list(p.co_deform)
                cd[self.i] = p.co[self.i] * (1.0 + v)
                p.co_deform = cd
        update()


def make_params(spec):
    ps = []
    for h in spec['handles']:
        for ax in h['axes']:
            ps.append(Param(h, ax, spec['frame']))
    return ps


def theta(ps):
    return np.array([p.get() for p in ps])


def set_theta(ps, th):
    for p, v in zip(ps, th):
        p.set(float(v))


# ---------------------------------------------------------------- attach: 규칙으로 정점 그룹 → 핸들 생성
def cmd_attach(spec):
    bpy = _bpy()
    fr = spec['frame']
    out = spec['out']
    os.makedirs(out, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=spec['mesh_obj'], forward_axis='Y', up_axis='Z')
    obj = [o for o in bpy.context.scene.objects if o.type == 'MESH'][0]
    obj.name = spec['mesh_object']
    bpy.context.view_layer.objects.active = obj
    Vb = np.array([v.co[:] for v in obj.data.vertices])
    Vh = Vb / fr['H_bu']
    report = {'handles': {}}
    base = eval_mesh(obj)
    for h in spec['handles']:
        sel = h['select']
        idx = pick_vertex(Vh, sel['rule'])
        anchor = Vb[idx]
        info = {'kind': h['kind'], 'anchor_vertex': idx}
        if h['kind'] == 'hook':
            R = sel['radius'] * fr['H_bu']
            members = np.flatnonzero(np.linalg.norm(Vb - anchor, axis=1) <= R)
            emp = bpy.data.objects.new(h['name'], None)
            emp.empty_display_type = 'SPHERE'
            emp.location = tuple(anchor)
            emp['rest'] = [float(x) for x in anchor]
            bpy.context.scene.collection.objects.link(emp)
            update()
            mod = obj.modifiers.new(h['name'], 'HOOK')
            mod.object = emp
            mod.vertex_indices_set([int(i) for i in members])
            mod.falloff_type = 'SMOOTH'
            mod.falloff_radius = R
            mod.use_falloff_uniform = False
            mod.center = tuple(anchor)
            mod.matrix_inverse = emp.matrix_world.inverted()
            info.update({'정점수': int(len(members)), 'bbox_H': [(Vh[members].min(0)).round(3).tolist(), (Vh[members].max(0)).round(3).tolist()]})
        else:
            c = anchor + np.array(sel.get('center_offset', [0, 0, 0])) * fr['H_bu']
            half = np.array(sel['size']) * fr['H_bu'] / 2.0
            d = np.abs(Vb - c) / half
            w = np.clip((1.0 - d.max(axis=1)) / 0.5, 0.0, 1.0)      # 상자 안쪽 절반은 1 → 가장자리 0 (연속)
            w = 0.5 - 0.5 * np.cos(np.pi * w)
            members = np.flatnonzero(w > 0)
            vg = obj.vertex_groups.new(name=h['name'])
            for i in members:
                vg.add([int(i)], float(w[i]), 'REPLACE')
            lat = bpy.data.lattices.new(h['name'])
            lat.points_u = lat.points_v = lat.points_w = 2
            lat.interpolation_type_u = lat.interpolation_type_v = lat.interpolation_type_w = 'KEY_LINEAR'
            lo = bpy.data.objects.new(h['name'], lat)
            lo.location = tuple(c)
            lo.scale = tuple(half * 2)
            bpy.context.scene.collection.objects.link(lo)
            update()
            mod = obj.modifiers.new(h['name'], 'LATTICE')
            mod.object = lo
            mod.vertex_group = h['name']
            info.update({'정점수': int(len(members)), 'bbox_H': [(Vh[members].min(0)).round(3).tolist(), (Vh[members].max(0)).round(3).tolist()]})
        report['handles'][h['name']] = info
    update()
    chk = eval_mesh(obj)
    report['핸들_연결_후_변화(BU)'] = float(np.abs(chk - base).max())          # 0 이어야 한다(처음엔 안 움직임)
    # 시작 상태: 알려진 양만큼 틀어 놓는다(spec 의 init)
    ps = make_params(spec)
    for p in ps:
        init = p.handle.get('init', {}).get(p.axis, 0.0)
        if init:
            p.set(init)
    report['시작_매개변수'] = {p.name: p.get() for p in ps}
    path = os.path.join(out, 'step00.blend')
    bpy.ops.wm.save_as_mainfile(filepath=path)
    V0 = eval_mesh(obj)
    report['step00'] = {'checkpoint': path, 'vhash': vhash(V0)}
    jdump(os.path.join(out, 'attach.json'), report)
    print('FITLOOP attach', json.dumps(report, ensure_ascii=False))


# ---------------------------------------------------------------- run: 반복 루프
def cmd_run(spec):
    bpy = _bpy()
    fr = spec['frame']
    set_frame(fr)
    out = spec['out']
    os.makedirs(out, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=spec.get('start_blend') or os.path.join(out, 'step00.blend'))
    obj = bpy.data.objects[spec['mesh_object']]
    F = mesh_faces(obj)
    views = sorted({m['view'] for m in spec['metrics']} | {m['view'] for m in spec.get('protected', [])} | {m['view'] for m in spec.get('report', [])})
    target_masks = {v: np.load(spec['target_masks'][v]) for v in views}
    fit_m, prot_m, rep_m = spec['metrics'], spec.get('protected', []), spec.get('report', [])
    T = eval_metrics(fit_m + prot_m, target_masks, fr)
    ps = make_params(spec)
    names = [m['name'] for m in fit_m]
    keys = []
    for m in fit_m:
        keys += [m['name'] + '_lat', m['name'] + '_z'] if m['kind'] == 'extreme' else [m['name']]
    w = np.array([m.get('weight', 1.0) for m in fit_m for _ in (range(2) if m['kind'] == 'extreme' else range(1))])
    frac, tol, max_steps = spec.get('step_frac', 0.5), spec.get('tol', 0.01), spec.get('max_steps', 10)

    def measure():
        V = eval_mesh(obj)
        masks = masks_of(V, F, fr, views)
        M = eval_metrics(fit_m + prot_m, masks, fr)
        return V, masks, M

    def err_of(M):
        return np.array([M[k] - T[k] for k in keys])

    V0, masks0, M0 = measure()
    health0 = mesh_health(V0, F)
    prot0 = {m['name']: M0[m['name']] - T[m['name']] for m in prot_m}
    iou0 = {m['name']: iou_band(masks0[m['view']], target_masks[m['view']], fr, m['z']) for m in rep_m}
    th0 = theta(ps)
    steps_path = os.path.join(out, 'steps.jsonl')
    open(steps_path, 'w').close()
    records = []
    t0 = time.time()
    V, masks, M = V0, masks0, M0
    for step in range(1, max_steps + 1):
        e = err_of(M)
        if np.abs(e).max() < tol:
            break
        th = theta(ps)
        # 민감도: 매개변수를 하나씩 조금 움직여 지표 변화를 잰다
        J = np.zeros((len(keys), len(ps)))
        for j, p in enumerate(ps):
            p.set(th[j] + p.delta)
            _, _, Mj = measure()
            J[:, j] = [(Mj[k] - M[k]) / p.delta for k in keys]
            p.set(th[j])
        W = np.diag(w)
        lam = 1e-6 * np.trace(J.T @ W @ J) / max(len(ps), 1) + 1e-12
        dth = -np.linalg.solve(J.T @ W @ J + lam * np.eye(len(ps)), J.T @ W @ e)
        dth = frac * dth                                         # 한 걸음에 남은 오차의 일부만
        lim = np.array([p.limit for p in ps])
        dth = np.clip(dth, -lim, lim)
        set_theta(ps, th + dth)
        V1, masks1, M1 = measure()
        e1 = err_of(M1)
        prot1 = {m['name']: M1[m['name']] - T[m['name']] for m in prot_m}
        iou1 = {m['name']: iou_band(masks1[m['view']], target_masks[m['view']], fr, m['z']) for m in rep_m}
        health1 = mesh_health(V1, F)
        ckpt = os.path.join(out, 'step%02d.blend' % step)
        bpy.ops.wm.save_as_mainfile(filepath=ckpt, copy=True)
        rec = {'step': step,
               '수정_대상': keys,
               '수정전_오차': {k: float(v) for k, v in zip(keys, e)},
               '핸들': [p.name for p in ps],
               '민감도_J': J.round(5).tolist(),
               '이동량': {p.name: float(d) for p, d in zip(ps, dth)},
               '수정후_오차': {k: float(v) for k, v in zip(keys, e1)},
               '매개변수_후': {p.name: float(v) for p, v in zip(ps, th + dth)},
               '부작용': {'대상밖_띠_오차_증가': {k: float(abs(prot1[k]) - abs(prot0[k])) for k in prot1},
                         'IoU_전→후': {k: [iou0[k], iou1[k]] for k in iou1},
                         '메시_전→후': [health0, health1]},
               '체크포인트': ckpt, 'vhash': vhash(V1)}
        records.append(rec)
        with open(steps_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        V, masks, M = V1, masks1, M1
    e_final = err_of(M)
    th_f = theta(ps)
    summary = {'걸음_수': len(records), '시작_오차': {k: float(v) for k, v in zip(keys, err_of(M0))},
               '최종_오차': {k: float(v) for k, v in zip(keys, e_final)},
               '시작_매개변수': {p.name: float(v) for p, v in zip(ps, th0)},
               '최종_매개변수': {p.name: float(v) for p, v in zip(ps, th_f)},
               '실제_이동량': {p.name: float(b - a) for p, a, b in zip(ps, th0, th_f)},
               '대상밖_띠_최대_증가': max([abs(float(abs(M[m['name']] - T[m['name']]) - abs(prot0[m['name']]))) for m in prot_m] or [0.0]),
               'IoU_전→후': {m['name']: [iou0[m['name']], iou_band(masks[m['view']], target_masks[m['view']], fr, m['z'])] for m in rep_m},
               '최종_vhash': vhash(V), '시작_vhash': vhash(V0), '체크포인트': [r['체크포인트'] for r in records],
               '걸린_시간_초': round(time.time() - t0, 2)}
    jdump(os.path.join(out, 'summary.json'), summary)
    print('FITLOOP run', json.dumps({k: summary[k] for k in ('걸음_수', '최종_vhash')}, ensure_ascii=False))


def cmd_hash(path, mesh_name):
    bpy = _bpy()
    bpy.ops.wm.open_mainfile(filepath=path)
    h = vhash(eval_mesh(bpy.data.objects[mesh_name]))
    print('FITLOOP hash', h)


def cmd_doctor():
    bpy = _bpy()
    rows = []

    def chk(name, ok, detail=''):
        rows.append((name, 'PASS' if ok else 'FAIL', detail))

    chk('Blender 버전', bpy.app.version >= (5, 0, 0), '.'.join(map(str, bpy.app.version)))
    chk('numpy', True, np.__version__)
    obj = bpy.data.objects.new('t', bpy.data.meshes.new('t'))
    types = [m.identifier for m in obj.modifiers.bl_rna.functions['new'].parameters['type'].enum_items]
    for t in ('HOOK', 'LATTICE', 'LAPLACIANDEFORM'):
        chk('수정자 ' + t, t in types)
    try:
        p = os.path.join(HERE, '.doctor_write_test')
        open(p, 'w').close()
        os.remove(p)
        chk('쓰기 권한', True, HERE)
    except OSError as e:
        chk('쓰기 권한', False, str(e))
    try:
        ref()
        chk('재사용 모듈(ref_trace_iou)', hasattr(_R, 'raster') and hasattr(_R, 'Scene'))
    except Exception as e:                                          # noqa: BLE001
        chk('재사용 모듈(ref_trace_iou)', False, str(e))
    for r in rows:
        print('FITLOOP doctor %s %s %s' % r)
    ok = all(r[1] == 'PASS' for r in rows)
    print('FITLOOP doctor 판정 ' + ('PASS' if ok else 'FAIL'))
    return ok


def main():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    cmd = argv[0]
    if cmd == 'doctor':
        sys.exit(0 if cmd_doctor() else 1)
    elif cmd == 'attach':
        cmd_attach(jload(argv[1]))
    elif cmd == 'run':
        cmd_run(jload(argv[1]))
    elif cmd == 'hash':
        cmd_hash(argv[1], argv[2])
    else:
        print('알 수 없는 명령', cmd)
        sys.exit(2)


if __name__ == '__main__':
    main()
