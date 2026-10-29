# -*- coding: utf-8 -*-
# 기준선 실험: 도면(정면·옆면 정사영)만 보고 Blender 헤드리스로 만든다.
# 실행: blender.exe -b -P make_model.py -- <태그>
# 좌표: H 단위, X 오른쪽 +(화면 오른쪽이 -X), Y 앞 +, Z 위.
import bpy, bmesh, numpy as np, sys, os
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
TAG = sys.argv[-1] if "--" in sys.argv else "v0"
DRAWING = os.path.join(HERE, "..", "drawing.png")


def px2x(x):  # 정면 화면 x -> X
    return -(x - 150.0) / 160.0


def px2z(y):
    return (930.0 - y) / 160.0


def signed_volume(V, F):
    V = np.asarray(V); s = 0.0
    for f in F:
        for k in range(1, len(f) - 1):
            a, b, c = V[f[0]], V[f[k]], V[f[k + 1]]
            s += np.dot(a, np.cross(b, c))
    return s / 6.0


def fix_winding(V, F):
    if signed_volume(V, F) < 0:
        F = [list(reversed(f)) for f in F]
    return V, F


def ellipsoid(center, radii, ns=48, nr=32):
    cx, cy, cz = center; rx, ry, rz = radii
    V = [[cx, cy, cz + rz]]
    for i in range(1, nr):
        th = np.pi * i / nr
        for j in range(ns):
            ph = 2 * np.pi * j / ns
            V.append([cx + rx * np.sin(th) * np.cos(ph), cy + ry * np.sin(th) * np.sin(ph), cz + rz * np.cos(th)])
    V.append([cx, cy, cz - rz])
    F = []
    for j in range(ns):
        F.append([0, 1 + j, 1 + (j + 1) % ns])
    for i in range(nr - 2):
        a = 1 + i * ns; b = 1 + (i + 1) * ns
        for j in range(ns):
            j2 = (j + 1) % ns
            F.append([a + j, b + j, b + j2, a + j2])
    last = len(V) - 1; a = 1 + (nr - 2) * ns
    for j in range(ns):
        F.append([last, a + (j + 1) % ns, a + j])
    return fix_winding(V, F)


def catmull(P, per=20):
    P = np.asarray(P, float)
    Q = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = []
    for i in range(1, len(Q) - 2):
        p0, p1, p2, p3 = Q[i - 1], Q[i], Q[i + 1], Q[i + 2]
        for t in np.linspace(0, 1, per, endpoint=False):
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    out.append(P[-1])
    return np.array(out)


def tube(ctrl, r_base, r_tip, expo, yscale, n=90, ns=32):
    """ctrl: 제어점(X,Y,Z) 목록(밑동 -> 끝). 단면 타원: 곡선 평면 방향 반지름 r, Y 방향 r*yscale. 밑동·끝 모두 막힘."""
    C = catmull(ctrl)
    seg = np.linalg.norm(np.diff(C, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)]); s /= s[-1]
    t = np.linspace(0, 1, n)
    P = np.stack([np.interp(t, s, C[:, k]) for k in range(3)], 1)
    T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1)[:, None]
    Yax = np.array([0, 1.0, 0])
    V = [P[0].tolist()]
    rings = []
    for i in range(n - 1):
        e2 = Yax - np.dot(Yax, T[i]) * T[i]; e2 /= np.linalg.norm(e2)
        e1 = np.cross(T[i], e2)
        r = r_tip + (r_base - r_tip) * (1 - t[i]) ** expo
        ring = []
        for j in range(ns):
            a = 2 * np.pi * j / ns
            p = P[i] + r * yscale * np.cos(a) * e2 + r * np.sin(a) * e1
            ring.append(len(V)); V.append(p.tolist())
        rings.append(ring)
    V.append(P[-1].tolist()); tip = len(V) - 1
    F = []
    for j in range(ns):
        F.append([0, rings[0][(j + 1) % ns], rings[0][j]])
    for i in range(len(rings) - 1):
        for j in range(ns):
            j2 = (j + 1) % ns
            F.append([rings[i][j], rings[i][j2], rings[i + 1][j2], rings[i + 1][j]])
    for j in range(ns):
        F.append([tip, rings[-1][j], rings[-1][(j + 1) % ns]])
    return fix_winding(V, F)


def mirror_x(V, F):
    V2 = [[-v[0], v[1], v[2]] for v in V]
    return fix_winding(V2, F)


# ---------------------------------------------------------------- 부위 정의
parts = {}
# 머리: 정면 폭 약 100px, 위아래 87~212px(높이 약 114px), 옆 앞면 Y=0.4375
parts["head"] = ellipsoid((0, 0.13, 4.84), (0.31, 0.31, 0.356))
# 주둥이: 정면 타원 지름 53x43px, 옆에서 앞으로 Y=0.58 까지
parts["snout"] = ellipsoid((0, 0.44, 4.69), (0.167, 0.14, 0.14))
# 귀
parts["ear_L"] = ellipsoid((0.445, 0.10, 4.79), (0.14, 0.09, 0.0625))
parts["ear_R"] = ellipsoid((-0.445, 0.10, 4.79), (0.14, 0.09, 0.0625))
# 갈기: 옆면에서 머리 뒤쪽 위에 겹친 큰 타원체. 정면에서는 머리 위로 솟음
parts["mane"] = ellipsoid((0, -0.325, 4.93), (0.36, 0.224, 0.34))
# 이마 앞머리 뭉치: 옆면 머리 윗면의 작은 혹, 정면에서 중앙 약간 한쪽의 작은 돌기
parts["tuft"] = ellipsoid((-0.055, 0.17, 5.14), (0.045, 0.07, 0.09), ns=24, nr=16)
# 뿔: 정면 화면 (x,y) 와 Y(앞뒤) 로 제어점. 화면 왼쪽 뿔 = +X
horn_pts = [  # (px_x, px_y, Y)
    (115, 138, -0.010), (102, 138, -0.008), (87, 137, -0.003), (72, 130, 0.005),
    (58, 118, 0.015), (50, 103, 0.026), (46, 87, 0.034), (46, 70, 0.043),
    (51, 52, 0.055), (58, 37, 0.065), (68, 25, 0.075), (80, 15, 0.082), (95, 8, 0.088)]
ctrl = [(px2x(x), y3, px2z(y)) for x, y, y3 in horn_pts]
parts["horn_L"] = tube(ctrl, r_base=0.075, r_tip=0.004, expo=0.7, yscale=1.1)
parts["horn_R"] = mirror_x(*parts["horn_L"])

# ---------------------------------------------------------------- Blender 로 내보내기
bpy.ops.wm.read_factory_settings(use_empty=True)
objs = []
for name, (V, F) in parts.items():
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in V], [], [tuple(f) for f in F])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    objs.append(ob)
    print(name, "verts", len(V), "volume", round(signed_volume(V, F), 4))

outdir = HERE
obj_path = os.path.join(outdir, "model.obj")
for ob in bpy.context.scene.objects:
    ob.select_set(True)
bpy.ops.wm.obj_export(filepath=obj_path, forward_axis='Y', up_axis='Z', export_selected_objects=False,
                      export_uv=False, export_normals=False, export_materials=False, apply_modifiers=False)
print("총 꼭짓점:", sum(len(v) for v, f in parts.values()))

# ---------------------------------------------------------------- 자기 검사 렌더: 정면·옆 정사영 실루엣을 도면에 겹침
sc = bpy.context.scene
sc.render.engine = 'BLENDER_WORKBENCH'
sc.render.film_transparent = True
sc.render.resolution_x = 300; sc.render.resolution_y = 300
sc.render.image_settings.file_format = 'PNG'
sc.render.image_settings.color_mode = 'RGBA'
sc.display.shading.light = 'FLAT'
sc.display.shading.color_type = 'SINGLE'
sc.view_settings.view_transform = 'Standard'
cam = bpy.data.cameras.new("cam"); cam.type = 'ORTHO'; cam.ortho_scale = 300 / 160.0
cam.clip_start = 0.01; cam.clip_end = 100
co = bpy.data.objects.new("cam", cam); bpy.context.collection.objects.link(co); sc.camera = co


def render(loc, target, path):
    co.location = Vector(loc)
    d = Vector(target) - Vector(loc)
    co.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(path)
    a = np.array(im.pixels[:]).reshape(300, 300, 4)[::-1, :, 3] > 0.5
    return a


fa = render((0, 10, 4.875), (0, 0, 4.875), os.path.join(HERE, "_rf.png"))
sa = render((-10, 0, 4.875), (0, 0, 4.875), os.path.join(HERE, "_rs.png"))

dim = bpy.data.images.load(DRAWING)
W, Hh = dim.size
D = np.array(dim.pixels[:]).reshape(Hh, W, 4)[::-1, :, :3]
big = []
for A, x0 in ((fa, 0), (sa, 300)):
    img = D[0:300, x0:x0 + 300].copy()
    er = A.copy()
    edge = A & ~(np.roll(A, 1, 0) & np.roll(A, -1, 0) & np.roll(A, 1, 1) & np.roll(A, -1, 1))
    img[edge] = [0, 1, 0]
    img3 = np.repeat(np.repeat(img, 2, 0), 2, 1)
    big.append(img3)
out = np.concatenate(big, 1)  # 600 x 1200
o = bpy.data.images.new("cmp", out.shape[1], out.shape[0], alpha=True)
rgba = np.concatenate([out, np.ones(out.shape[:2] + (1,))], 2)
o.pixels = rgba[::-1].reshape(-1).tolist()
o.filepath_raw = os.path.join(HERE, "check_%s.png" % TAG); o.file_format = 'PNG'; o.save()
print("저장:", o.filepath_raw)
