# -*- coding: utf-8 -*-
"""Blender(Eevee)로 합성 도면 렌더: bench/scene.py 의 creature() 도형을 실제 메시로 만들고 툰 셰이딩으로 정면·옆 정사영.
정답: 부위마다 고유 발광색(조명·앤티에일리어싱 없이)으로 한 번 더 렌더 → 색으로 부위 번호.
실행: blender -b -P bench/blender_scene.py -- <seed> <출력 폴더> [outline]
출력: color_front.png, color_side.png, id_front.png, id_side.png, parts.json(부위→발광색)
"""
import json
import math
import os
import sys

import bpy
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from scene import H, PPH, W, ZOFF, GROUND, creature  # noqa: E402

argv = sys.argv[sys.argv.index('--') + 1:]
SEED, OUT = int(argv[0]), os.path.abspath(argv[1])
OUTLINE = len(argv) > 2 and argv[2] == 'outline'
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(SEED)
prims, pal = creature(rng)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'BLENDER_EEVEE'
sc.render.resolution_x, sc.render.resolution_y = W, H
sc.render.film_transparent = True              # 배경은 투명으로 렌더하고 나중에 합성(월드 빛이 톤을 다 밝히지 않게)
sc.view_settings.view_transform = 'Standard'
world = bpy.data.worlds.new('w'); sc.world = world
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (0, 0, 0, 1)
world.node_tree.nodes['Background'].inputs[1].default_value = 0.0

PART_ID = {}
def part_color(name):
    if name not in PART_ID:
        k = len(PART_ID) + 1
        PART_ID[name] = [(k * 53) % 256, (k * 97 + 40) % 256, (k * 151 + 80) % 256]
    return PART_ID[name]


TH = (0.12, 0.4)                                  # 확산 밝기 계단(어두움|중간|밝음)


def toon_mat(base):
    m = bpy.data.materials.new('toon')
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    o = nt.nodes.new('ShaderNodeOutputMaterial')
    dif = nt.nodes.new('ShaderNodeBsdfDiffuse'); dif.inputs[0].default_value = (1, 1, 1, 1)
    s2r = nt.nodes.new('ShaderNodeShaderToRGB')
    ramp = nt.nodes.new('ShaderNodeValToRGB'); ramp.color_ramp.interpolation = 'CONSTANT'
    tone = [0.72, 0.88, 1.06]
    els = ramp.color_ramp.elements
    els[0].position = 0.0; els[1].position = TH[0]
    els.new(TH[1])
    for e, t in zip(sorted(els, key=lambda e: e.position), tone):
        c = np.clip(base * t / 255.0, 0, 1) ** 2.2
        e.color = (*c, 1)
    em = nt.nodes.new('ShaderNodeEmission')
    nt.links.new(dif.outputs[0], s2r.inputs[0]); nt.links.new(s2r.outputs[0], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], em.inputs[0]); nt.links.new(em.outputs[0], o.inputs[0])
    return m


def id_mat(rgb):
    m = bpy.data.materials.new('id')
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    o = nt.nodes.new('ShaderNodeOutputMaterial'); em = nt.nodes.new('ShaderNodeEmission')
    em.inputs[0].default_value = (*((np.array(rgb) / 255.0) ** 2.2), 1)
    nt.links.new(em.outputs[0], o.inputs[0])
    return m


mats = {k: toon_mat(v) for k, v in pal.items() if k != '배경'}
objs = []
for p in prims:
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, location=tuple(p['c']))
    ob = bpy.context.object
    ob.scale = tuple(p['r'])
    ob.data.materials.append(mats[p['mat']])
    bpy.ops.object.shade_smooth()
    ob['part'] = p['part']
    objs.append(ob)

sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sc.collection.objects.link(sun)
L = np.array([0.45, 0.55, 0.7]); L /= np.linalg.norm(L)
sun.rotation_euler = (0, 0, 0)
sun.rotation_mode = 'QUATERNION'
from mathutils import Vector  # noqa: E402
sun.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(Vector(tuple(L)))
sun.data.energy = 1.2

cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
sc.collection.objects.link(cam); sc.camera = cam
cam.data.type = 'ORTHO'
cam.data.ortho_scale = W / PPH
zc = (GROUND - H / 2) / -PPH + ZOFF + (GROUND - H / 2) / PPH * 0 + (GROUND - H / 2) / PPH
# 패널 중심(행 H/2)의 높이 = (GROUND − H/2)/PPH + ZOFF
zc = (GROUND - H / 2) / PPH + ZOFF
if OUTLINE:
    sc.render.use_freestyle = True
    sc.render.line_thickness = 1.0


def shoot(view, kind):
    if view == 'front':
        cam.location = (0, 20, zc); cam.rotation_euler = (math.radians(90), 0, math.radians(180))
    else:
        cam.location = (-20, 0, zc); cam.rotation_euler = (math.radians(90), 0, math.radians(-90))   # 앞(+Y)이 화면 왼쪽
    sc.render.filepath = os.path.join(OUT, '%s_%s.png' % (kind, view))
    sc.render.image_settings.color_mode = 'RGBA'
    bpy.ops.render.render(write_still=True)


for v in ('front', 'side'):
    shoot(v, 'color')
# 정답 렌더: 발광 고유색, 앤티에일리어싱 최소, 선 끔
sc.render.use_freestyle = False
sc.render.filter_size = 0.0
sc.eevee.taa_render_samples = 1
world.node_tree.nodes['Background'].inputs[0].default_value = (0, 0, 0, 1)
for ob in objs:
    ob.data.materials[0] = id_mat(part_color(ob['part']))
for v in ('front', 'side'):
    shoot(v, 'id')
json.dump({k: v for k, v in PART_ID.items()}, open(os.path.join(OUT, 'parts.json'), 'w', encoding='utf-8'), ensure_ascii=False)
json.dump({k: list(map(float, v)) for k, v in pal.items()}, open(os.path.join(OUT, 'pal.json'), 'w', encoding='utf-8'), ensure_ascii=False)
print('BLSCENE 완료', OUT)
