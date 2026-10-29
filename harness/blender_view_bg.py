# -*- coding: utf-8 -*-
"""헤드리스 각도 그림: blender -b -P harness/blender_view_bg.py -- <OBJ> <출력 폴더> <이름:고도:방위,...> [solid,normal,wire]
창을 띄우지 않는다(사용자 지적 "헤드리스로 테스트하지?"). Workbench 렌더, 정사영 카메라를 모델 중심에 맞춘다.
그림 종류(K1): solid 회색 음영(view_<이름>.png), normal 법선 색(_normal), wire 와이어프레임 겹침(_wire).
음영만 보면 깨진 메시·뒤집힌 면·계단이 멀쩡해 보인다(자유조사 4, 통합 계획 X18)."""
import math
import os
import sys

import bpy
import mathutils

argv = sys.argv[sys.argv.index('--') + 1:]
obj, out, spec = argv[0], argv[1], argv[2]
modes = (argv[3] if len(argv) > 3 else 'solid').split(',')
os.makedirs(out, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=obj, forward_axis='Y', up_axis='Z')
objs = [o for o in bpy.data.objects if o.type == 'MESH']
pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
c = sum(pts, mathutils.Vector()) / len(pts)
rad = max((p - c).length for p in pts)
sc = bpy.context.scene
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'
sc.display.shading.color_type = 'SINGLE'
sc.render.resolution_x = sc.render.resolution_y = 700
sc.render.film_transparent = False
cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 2.3 * rad
cam.data.clip_end = 100 * rad
wire = None
if 'wire' in modes:
    # 와이어프레임: 같은 메시를 복제해 Wireframe 수정자로 가는 선을 만들고 어두운 색으로 겹친다(렌더에는 화면 겹침이 안 나와서)
    src = objs[0]
    wire = src.copy()
    wire.data = src.data.copy()
    sc.collection.objects.link(wire)
    m = wire.modifiers.new('w', 'WIREFRAME')
    m.thickness = rad * 0.004
    m.use_replace = True
    m.use_even_offset = False       # 켜 두면 뾰족한 꼭짓점에서 선이 화면 밖까지 튀었다(가짜 결함, K1 확인)
    wire.color = (0.05, 0.05, 0.05, 1)
    for o in objs:
        o.color = (0.8, 0.8, 0.8, 1)
    wire.hide_render = True
for item in spec.split(','):
    name, el, az = item.split(':')
    rot = mathutils.Euler((math.radians(float(el)), 0, math.radians(float(az))), 'XYZ')
    cam.rotation_euler = rot
    cam.location = c + rot.to_matrix() @ mathutils.Vector((0, 0, 5 * rad))
    for mode in modes:
        sh = sc.display.shading
        if mode == 'normal':
            sh.light, sh.color_type = 'MATCAP', 'SINGLE'
            sh.studio_light = 'check_normal+y.exr'
        else:
            sh.light, sh.color_type = 'STUDIO', ('OBJECT' if mode == 'wire' else 'SINGLE')
        if wire is not None:
            wire.hide_render = mode != 'wire'
        suffix = '' if mode == 'solid' else '_' + mode
        sc.render.filepath = os.path.join(out, 'view_%s%s.png' % (name, suffix))
        bpy.ops.render.render(write_still=True)
        print('VIEW', name, mode, sc.render.filepath)
