# -*- coding: utf-8 -*-
"""켜 둔 Blender(MCP 애드온, localhost:9876)로 모델을 여러 각도에서 찍는다. 도면에 없는 각도(3/4·위·아래)를 보는 눈.
3D 루프의 재투영은 정면·옆만 잰다. 판자 뿔처럼 3/4 에서만 보이는 실패가 있어 그림을 따로 남긴다(판정은 사람·LLM 이 그림으로).
규칙: 여기서는 보기만 한다. 모델을 고치는 코드는 보내지 않는다(모델링은 하네스 명령으로만).
실행: python -m harness.blender_view <OBJ> <출력 폴더> [--mcp]   (기본은 헤드리스, --mcp 는 창을 띄운 MCP 판)
Blender 가 안 켜져 있으면 직접 띄우고(애드온이 자동으로 9876 을 연다), 다 찍으면 자기가 띄운 것만 닫는다. 사람이 켤 필요 없다.
"""
import json
import os
import socket
import subprocess
import sys
import time

BLENDER = os.path.join('C:' + os.sep, 'Program Files', 'Blender Foundation', 'Blender 5.2', 'blender.exe')

ANGLES = {'3/4_앞왼': (75, 135), '3/4_앞오른': (75, -135), '3/4_뒤': (75, 45), '위': (5, 180), '아래': (175, 180)}


def send(t, params, host='localhost', port=9876, timeout=120):
    s = socket.create_connection((host, port), timeout=timeout)
    s.sendall(json.dumps({'type': t, 'params': params}).encode())
    buf = b''
    while True:
        ch = s.recv(65536)
        if not ch:
            break
        buf += ch
        try:
            return json.loads(buf.decode())
        except ValueError:
            continue
    raise RuntimeError('Blender 응답이 끊김')


def _up(host='localhost', port=9876):
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def ensure_blender(wait=90):
    """켜진 Blender 가 없으면 띄운다. 반환: 띄운 프로세스(이미 켜져 있었으면 None)."""
    if _up():
        return None
    env = dict(os.environ, BLENDERMCP_NO_UPDATE_CHECK='1')
    p = subprocess.Popen([BLENDER], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.time()
    while time.time() - t0 < wait:
        if _up():
            time.sleep(1.0)
            return p
        time.sleep(1.0)
    p.terminate()
    raise RuntimeError('Blender MCP 애드온이 %d초 안에 열리지 않음' % wait)


def views_bg(obj, out, angles=ANGLES, modes='solid,normal,wire'):
    """기본: 창 없이 헤드리스 렌더(blender -b). 반환 {각도: 파일 또는 None}."""
    spec = ','.join('%s:%g:%g' % (n.replace('/', '-'), el, az) for n, (el, az) in angles.items())
    r = subprocess.run([BLENDER, '-b', '-P', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'blender_view_bg.py'), '--',
                        os.path.abspath(obj), os.path.abspath(out), spec, modes], capture_output=True, text=True, encoding='utf-8', errors='replace')
    files = {}
    for n in angles:
        f = os.path.abspath(os.path.join(out, 'view_%s.png' % n.replace('/', '-')))
        files[n] = f if os.path.exists(f) else None
    if not any(files.values()):
        raise RuntimeError('헤드리스 렌더 실패: ' + r.stderr[-400:])
    return files


def views(obj, out, angles=ANGLES, size=900):
    """MCP 판(창이 뜬다): 대화하며 직접 볼 때만. 루프는 views_bg 를 쓴다."""
    proc = ensure_blender()
    try:
        return _views(obj, out, angles, size)
    finally:
        if proc is not None:
            proc.terminate()


def _views(obj, out, angles=ANGLES, size=900):
    os.makedirs(out, exist_ok=True)
    code = '''
import bpy, math, mathutils
for o in [o for o in bpy.data.objects if o.get("mh_view")]:
    bpy.data.objects.remove(o)
before = set(bpy.data.objects)
bpy.ops.wm.obj_import(filepath=%r, forward_axis='Y', up_axis='Z')
new = [o for o in bpy.data.objects if o not in before]
for o in new:
    o["mh_view"] = 1
pts = [o.matrix_world @ v.co for o in new for v in o.data.vertices]
c = sum(pts, mathutils.Vector()) / len(pts)
r = max((p - c).length for p in pts)
print(len(new), round(r, 3), tuple(round(x, 3) for x in c))
''' % os.path.abspath(obj)
    r = send('execute_code', {'code': code})
    if r.get('status') != 'success':
        raise RuntimeError(str(r)[:300])
    info = r['result']['result'].split()
    rad, files = float(info[1]), {}
    for name, (el, az) in angles.items():
        code = '''
import bpy, math, mathutils
objs = [o for o in bpy.data.objects if o.get("mh_view")]
pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
c = sum(pts, mathutils.Vector()) / len(pts)
for a in bpy.context.screen.areas:
    if a.type == 'VIEW_3D':
        rv = a.spaces[0].region_3d
        rv.view_perspective = 'ORTHO'
        rv.view_rotation = mathutils.Euler((math.radians(%f), 0, math.radians(%f)), 'XYZ').to_quaternion()
        rv.view_location = c
        rv.view_distance = %f
        a.spaces[0].shading.type = 'SOLID'
        a.spaces[0].overlay.show_floor = False
''' % (el, az, 3.2 * rad)
        send('execute_code', {'code': code})
        f = os.path.abspath(os.path.join(out, 'view_%s.png' % name.replace('/', '-')))
        rr = send('get_viewport_screenshot', {'max_size': size, 'filepath': f, 'format': 'png'})
        files[name] = f if rr.get('status') == 'success' and os.path.exists(f) else None
    return files


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    fn = views if '--mcp' in sys.argv else views_bg
    for k, v in fn(sys.argv[1], sys.argv[2]).items():
        print('VIEW', k, v or '실패')
