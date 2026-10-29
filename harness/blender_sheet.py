# blender -b -P 로 실행되는 쪽: OBJ(하네스 좌표 H, X 오른쪽 Y 앞 Z 위)를 Eevee 로 정면·옆·뒤·3/4 네 방향 렌더하고,
# 위쪽 줄에는 같은 틀로 오려 낸 도면(정면·옆·뒤)을 붙여 한 장으로 저장한다.
# 사용: blender -b -P blender_sheet.py -- <params.json>
import json
import os
import sys

import bpy
import numpy as np

params = json.load(open(sys.argv[sys.argv.index('--') + 1], encoding='utf-8'))
sys.path.insert(0, params['root'])
from harness.render import write_png  # noqa: E402

TW, TH = 560, 440                     # 칸 크기
ORTHO = 2.1                           # 칸 가로가 덮는 H 길이 → 1H = 266px
ZC, YC = params['zc'], params['yc']
BG = 225 / 255.0

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
for eng in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
    try:
        sc.render.engine = eng
        break
    except TypeError:
        continue
sc.render.resolution_x, sc.render.resolution_y = TW, TH
sc.render.resolution_percentage = 100
sc.render.image_settings.file_format = 'PNG'
sc.view_settings.view_transform = 'Standard'
w = bpy.data.worlds.new('w')
w.use_nodes = True
w.node_tree.nodes['Background'].inputs[0].default_value = (BG, BG, BG, 1)
w.node_tree.nodes['Background'].inputs[1].default_value = 0.8
sc.world = w

bpy.ops.wm.obj_import(filepath=params['obj'], forward_axis='Y', up_axis='Z')
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
mat = bpy.data.materials.new('m')
mat.use_nodes = True
bsdf = mat.node_tree.nodes['Principled BSDF']
bsdf.inputs['Base Color'].default_value = (0.55, 0.38, 0.26, 1)
bsdf.inputs['Roughness'].default_value = 0.8
for o in objs:
    o.data.materials.clear()
    o.data.materials.append(mat)
    for p in o.data.polygons:
        p.use_smooth = True

sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
sun.data.energy = 3.0
sun.rotation_euler = (np.radians(50), np.radians(10), np.radians(30))
sc.collection.objects.link(sun)
tgt = bpy.data.objects.new('tgt', None)
tgt.location = (0, YC, ZC)
sc.collection.objects.link(tgt)

D = 6.0
a = np.radians(35)
cams = {'front': (0, D, ZC), 'side': (-D, YC, ZC), 'back': (0, -D, ZC), 'q34': (D * np.sin(a), D * np.cos(a), ZC + 0.18 * D)}
tiles = {}
tmp = os.path.dirname(params['out'])
for name, loc in cams.items():
    cam = bpy.data.objects.new('cam_' + name, bpy.data.cameras.new('cam_' + name))
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = ORTHO
    cam.data.clip_start, cam.data.clip_end = 0.1, 50
    cam.location = loc
    c = cam.constraints.new('TRACK_TO')
    c.target = tgt
    c.track_axis, c.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'
    sc.collection.objects.link(cam)
    sc.camera = cam
    fp = os.path.join(tmp, '_tile_%s.png' % name)
    sc.render.filepath = fp
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(fp)
    px = np.empty(TW * TH * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(TH, TW, 4)[::-1, :, :3]
    tiles[name] = (np.clip(px, 0, 1) * 255 + 0.5).astype(np.uint8)
    bpy.data.images.remove(img)
    os.remove(fp)

# 도면 오리기: 같은 틀(가로 ORTHO H, 중심 = (YC 또는 0, ZC))
draw = np.load(params['drawing']) if params.get('drawing') else None
ppH = params['px_per_H']
ground = params['ground_row']
top = []
s = TW / ORTHO
for name in ('front', 'side', 'back'):
    if draw is None:
        top.append(np.full((TH, TW, 3), 225, np.uint8))
        continue
    pan = params['panels'][name]
    lat_c = YC if name == 'side' else 0.0
    uu = lat_c + (np.arange(TW) + 0.5 - TW / 2) / s            # 화면 오른쪽 방향의 캐릭터 좌표(렌더 쪽 규칙)
    # 도면 패널의 화면 좌우: px = center_x + sign * lateral * ppH (정면·옆은 sign=-1 → lateral 이 클수록 화면 왼쪽)
    lat = lat_c - (np.arange(TW) + 0.5 - TW / 2) / s * (-pan['sign'])
    px = pan['center_x'] + pan['sign'] * lat * ppH
    zz = ZC + (TH / 2 - (np.arange(TH) + 0.5)) / s
    py = ground - zz * ppH
    xi = np.clip(np.round(px - 0.5).astype(int), 0, draw.shape[1] - 1)
    yi = np.clip(np.round(py - 0.5).astype(int), 0, draw.shape[0] - 1)
    top.append(draw[yi][:, xi])
blank = np.full((TH, TW, 3), 235, np.uint8)
top.append(blank)
gap = np.full((TH, 6, 3), 255, np.uint8)
row1 = np.concatenate([x for t in top for x in (t, gap)][:-1], 1)
row2 = np.concatenate([x for t in (tiles['front'], tiles['side'], tiles['back'], tiles['q34']) for x in (t, gap)][:-1], 1)
bar = np.full((6, row1.shape[1], 3), 255, np.uint8)
write_png(params['out'], np.concatenate([row1, bar, row2], 0))
print('시트 저장', params['out'], 'engine=', sc.render.engine)
