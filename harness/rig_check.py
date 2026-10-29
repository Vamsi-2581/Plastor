# -*- coding: utf-8 -*-
"""단계 5. 리깅 준비 검사기(Blender 안에서 돈다).
실행: blender -b -P harness/rig_check.py -- <merged.obj> <out.json> [--parts a.obj b.obj ...]
--parts 를 주면 부위마다(연결 성분마다) 머리 뼈 자식 뼈를 하나씩 더한다(부속 부위에 열 확산이 닿게).
(a) 한 덩어리·닫힘  (b) 좌우 대칭(보고만)  (c) 시험 뼈대 3개에 자동 가중치(ARMATURE_AUTO)가 붙는지.
판정 PASS 는 덩어리 1·열린변 0·가중치0_비율 <= 0.01 이고 Bone Heat 경고가 없을 때. 비대칭도는 판정에 넣지 않는다.
"""
import json
import os
import sys
import tempfile

import bmesh
import bpy
from mathutils import Vector, kdtree

ZERO_LIMIT = 0.01
SYM_LIMIT = 0.01


def import_obj(path):
    before = set(bpy.data.objects)
    if hasattr(bpy.ops.wm, 'obj_import'):
        bpy.ops.wm.obj_import(filepath=path)
    else:
        bpy.ops.import_scene.obj(filepath=path)
    new = [o for o in bpy.data.objects if o not in before and o.type == 'MESH']
    if not new:
        raise RuntimeError('OBJ 에서 메시를 못 읽음')
    if len(new) > 1:
        bpy.ops.object.select_all(action='DESELECT')
        for o in new:
            o.select_set(True)
        bpy.context.view_layer.objects.active = new[0]
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def topology(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    open_edges = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    seen, comps = set(), 0
    for v in bm.verts:
        if v.index in seen:
            continue
        comps += 1
        st = [v]
        seen.add(v.index)
        while st:
            c = st.pop()
            for e in c.link_edges:
                o = e.other_vert(c)
                if o.index not in seen:
                    seen.add(o.index)
                    st.append(o)
    bm.free()
    return comps, open_edges


def bbox(obj):
    vs = [obj.matrix_world @ v.co for v in obj.data.vertices]
    lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    return lo, hi


def asymmetry(obj):
    vs = [v.co.copy() for v in obj.data.vertices]
    n = len(vs)
    kd = kdtree.KDTree(n)
    for i, v in enumerate(vs):
        kd.insert(v, i)
    kd.balance()
    lo, hi = bbox(obj)
    mid = (lo.x + hi.x) / 2.0       # 거울면은 X 경계 상자 중앙(형태 자체의 대칭을 잰다)
    tot = sum(kd.find(Vector((2 * mid - v.x, v.y, v.z)))[2] for v in vs)
    diag = (hi - lo).length
    return (tot / n) / diag if diag > 0 else 0.0


def part_bones(path, c, min_verts=20):
    """부위 OBJ 의 연결 성분마다 (머리점, 꼬리점): 중심 c 에 가장 가까운 점 -> 그 점에서 가장 먼 점."""
    po = import_obj(path)
    pts = [po.matrix_world @ v.co for v in po.data.vertices]
    bm = bmesh.new()
    bm.from_mesh(po.data)
    bm.verts.ensure_lookup_table()
    seen, comps = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        seen.add(v.index)
        st, comp = [v], [v.index]
        while st:
            cur = st.pop()
            for e in cur.link_edges:
                o = e.other_vert(cur)
                if o.index not in seen:
                    seen.add(o.index)
                    st.append(o)
                    comp.append(o.index)
        comps.append(comp)
    bm.free()
    bpy.data.objects.remove(po, do_unlink=True)
    out = []
    for comp in comps:
        if len(comp) < min_verts:
            continue
        near = min(comp, key=lambda i: (pts[i] - c).length_squared)
        far = max(comp, key=lambda i: (pts[i] - pts[near]).length_squared)
        out.append((pts[near].copy(), pts[far].copy()))
    return out


def rig_test(obj, parts=()):
    """시험 뼈대 3개(+부위 뼈)를 붙이고 자동 가중치를 건다. (0 정점 비율, 경고 여부, 예외, 정점그룹 수)"""
    S = 1.0
    if os.environ.get('RIG_PREP', '1') == '1':
        # 알려진 Bone Heat 실패 원인 손보기(Blender Artists·CG Cookie 사례): 겹친 정점 합치기, 작고 촘촘한 메시는 10배로 키워 가중치
        import bmesh
        from mathutils import Matrix
        S = 10.0
        obj.data.transform(Matrix.Scale(S, 4))
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5 * S)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()
    lo, hi = bbox(obj)
    c = (lo + hi) / 2
    extra = []
    for pp in parts:
        for k, (h, t) in enumerate(part_bones(pp, c / S)):
            extra.append(('부위_%s_%d' % (os.path.splitext(os.path.basename(pp))[0], k), h * S, t * S))
    arm_d = bpy.data.armatures.new('rig_test')
    arm = bpy.data.objects.new('rig_test', arm_d)
    bpy.context.scene.collection.objects.link(arm)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, h, t in (('목', Vector((c.x, c.y, lo.z)), c),
                       ('머리', c, Vector((c.x, c.y, hi.z))),
                       ('턱', c, Vector((c.x, hi.y, lo.z)))):
        b = arm_d.edit_bones.new(name)
        b.head, b.tail = h, t
    head_bone = arm_d.edit_bones['머리']
    for name, h, t in extra:
        b = arm_d.edit_bones.new(name)
        b.head, b.tail = h, t
        b.parent = head_bone
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    # Blender 가 stdout 으로 내는 경고를 잡아 둔다
    sys.stdout.flush()
    tmp = tempfile.TemporaryFile(mode='w+b')
    saved = os.dup(1)
    os.dup2(tmp.fileno(), 1)
    err = None
    try:
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    except Exception as e:
        err = repr(e)
    finally:
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)
    tmp.seek(0)
    log = tmp.read().decode('utf-8', 'replace')
    tmp.close()
    warn = 'Bone Heat Weighting: failed' in log
    zero = sum(1 for v in obj.data.vertices if sum(g.weight for g in v.groups) < 1e-6)
    return zero / max(1, len(obj.data.vertices)), warn, err, len(obj.vertex_groups)


def main():
    a = sys.argv[sys.argv.index('--') + 1:]
    src, outp = a[0], a[1]
    parts = a[a.index('--parts') + 1:] if '--parts' in a else []
    R = {'판정': 'ERROR', '덩어리': None, '열린변': None, '비대칭도': None, '가중치0_비율': None, '이유': []}
    try:
        obj = import_obj(src)
        comps, open_e = topology(obj)
        R['덩어리'], R['열린변'] = comps, open_e
        R['비대칭도'] = round(asymmetry(obj), 5)
        R['대칭'] = R['비대칭도'] <= SYM_LIMIT
        why = []
        if comps != 1:
            why.append('덩어리 %d개(1개여야 함)' % comps)
        if open_e:
            why.append('열린 변 %d개(0이어야 함)' % open_e)
        z, warn, err, ng = rig_test(obj, parts)
        R['가중치0_비율'] = round(z, 5)
        R['정점그룹수'] = ng
        R['부위_OBJ'] = [os.path.basename(x) for x in parts]
        if err:
            why.append('자동 가중치 예외: ' + err)
        if warn:
            why.append('Bone Heat Weighting 경고(자동 가중치 실패)')
        if z > ZERO_LIMIT:
            why.append('가중치 0 정점 비율 %.4f > %.2f' % (z, ZERO_LIMIT))
        R['이유'] = why
        R['판정'] = 'FAIL' if why else 'PASS'
    except Exception as e:
        import traceback
        R['판정'] = 'ERROR'
        R['이유'] = [repr(e)] + traceback.format_exc().splitlines()[-3:]
    json.dump(R, open(outp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('RIG', json.dumps(R, ensure_ascii=False))


if __name__ == '__main__':
    main()
