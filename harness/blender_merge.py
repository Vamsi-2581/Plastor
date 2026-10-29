# -*- coding: utf-8 -*-
"""부위 메시를 줄이고 머리 코어와 하나로 합친다(Blender 내장: Decimate, Boolean Union, 필요하면 Voxel Remesh).
실행: blender -b -P harness/blender_merge.py -- <출력.obj> <비율> <코어.obj> <부위1.obj> [부위2.obj ...]
  비율: 부위 Decimate(COLLAPSE) 비율(예 0.08). 코어는 줄이지 않는다.
출력: 합친 OBJ(H 단위 그대로) + 표준출력에 정점·삼각형 수, 열린 변 수, 비다양체 변 수.
"""
import os
import sys

import bmesh
import bpy

argv = sys.argv[sys.argv.index('--') + 1:]
out, ratio, core, parts = argv[0], float(argv[1]), argv[2], argv[3:]
bpy.ops.wm.read_factory_settings(use_empty=True)


def load(path):
    bpy.ops.wm.obj_import(filepath=path, forward_axis='Y', up_axis='Z')
    ob = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = ob
    return ob


def stats(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    openE = sum(1 for e in bm.edges if e.is_boundary)
    nonman = sum(1 for e in bm.edges if not e.is_manifold)
    n = (len(bm.verts), sum(len(f.verts) - 2 for f in bm.faces), openE, nonman)
    bm.free()
    return n


def volume(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    v = bm.calc_volume(signed=True)
    bm.free()
    return v


base = load(core)
print('MERGE 코어 정점 %d 삼각형 %d 열린변 %d 비다양체변 %d' % stats(base))
for p in parts:
    ob = load(p)
    before = stats(ob)
    m = ob.modifiers.new('d', 'DECIMATE')
    m.ratio = ratio
    bpy.ops.object.modifier_apply(modifier='d')
    print('MERGE 부위 %s 정점 %d → %d' % (p.rsplit('/', 1)[-1].rsplit('\\', 1)[-1], before[0], stats(ob)[0]))
    bpy.context.view_layer.objects.active = base
    va, vb = volume(base), volume(ob)
    keep = base.data.copy()
    # 자기 교차 허용은 부피를 잃었을 때만 다시 시도한다. 부위 메시 안에 작은 조각이 큰 조각과 겹쳐 있으면(합성 뿔 밑동)
    # 끈 채로는 합집합이 본체를 통째로 지웠다(M0 합성 6종 전부, 정점 48093 → 1912, 수정_기록 44).
    # 늘 켜면 잘 되던 경우에 열린 변·떨어진 조각이 생겼다(빌드 시험 비율 0.5, 들소 몸 수 1 → 11).
    for use_self in (False, True):
        b = base.modifiers.new('u', 'BOOLEAN')
        b.operation = 'UNION'
        b.solver = 'EXACT'
        b.use_self = use_self
        b.object = ob
        bpy.ops.object.modifier_apply(modifier='u')
        vc = volume(base)
        print('MERGE 부피 코어 %.5f 부위 %.5f → %.5f%s' % (va, vb, vc, ' (자기 교차 허용)' if use_self else ''))
        if vc >= 0.97 * max(va, vb):     # 합집합은 두 입력 중 큰 것보다 작아질 수 없다
            break
        if not use_self:
            base.data = keep.copy()          # 되돌리고 다시
    else:
        print('MERGE 실패 합집합이 부피를 잃음 %s (%.5f < %.5f)' % (os.path.basename(p), vc, max(va, vb)))
    bpy.data.objects.remove(ob, do_unlink=True)
bpy.ops.object.select_all(action='DESELECT')
base.select_set(True)
bpy.context.view_layer.objects.active = base
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.select_all(action='SELECT')
# 불리언 찌꺼기 청소: 넓이 0 인 면과 떨어진 낱면(합성 시험에서 정점 3개짜리 조각이 남았다)
nv0 = len(base.data.vertices)
bpy.ops.mesh.dissolve_degenerate(threshold=1e-6)
bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=True)
bpy.ops.mesh.select_all(action='SELECT')
# 구멍 메우기: 줄인 부위가 우연히 조금 깨지면 불리언 뒤에 열린 변이 남는다(같은 장면에서 비율 0.5 만 열린 변 8, 실험 2 에서 0.2 가 3)
bpy.ops.mesh.fill_holes(sides=0)
bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.quads_convert_to_tris()
bpy.ops.object.mode_set(mode='OBJECT')
print('MERGE 찌꺼기 청소 정점 %d → %d' % (nv0, len(base.data.vertices)))
print('MERGE 합친 메시 정점 %d 삼각형 %d 열린변 %d 비다양체변 %d' % stats(base))
bpy.ops.wm.obj_export(filepath=out, export_selected_objects=True, forward_axis='Y', up_axis='Z', export_materials=False, export_uv=False, export_normals=False)
print('MERGE 저장', out)
