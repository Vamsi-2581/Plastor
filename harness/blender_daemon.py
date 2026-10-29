# -*- coding: utf-8 -*-
"""창 없는 Blender 상주 서버: blender -b -P harness/blender_daemon.py -- [포트]
사용자 지적: "블렌더 창을 열어 편집할 것도 아닌데 헤드리스로 띄워서 작업 못함?" → 된다.
MCP 애드온은 창의 이벤트 처리(타이머)로 명령을 받아 -b 에서는 멈춘다. 이 서버는 스스로 받고 실행하는 고리를 돌린다.
명령 형식은 MCP 애드온과 같다: {"type": "execute_code", "params": {"code": "..."}} → {"status": "success", "result": {"result": 표준출력}}.
그 밖에 get_scene_info, ping, quit. localhost 만 연다. 원격 전송 없음.
"""
import io
import json
import socket
import sys
import traceback
from contextlib import redirect_stdout

import bpy

argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
PORT = int(argv[0]) if argv else 9877
NS = {'bpy': bpy}


def handle(msg):
    t, p = msg.get('type'), msg.get('params', {})
    if t == 'ping':
        return {'status': 'success', 'result': {'blender': bpy.app.version_string}}
    if t == 'quit':
        return {'status': 'success', 'result': 'bye'}
    if t == 'get_scene_info':
        return {'status': 'success', 'result': {'objects': [{'name': o.name, 'type': o.type} for o in bpy.data.objects]}}
    if t == 'execute_code':
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(p['code'], NS)
            return {'status': 'success', 'result': {'executed': True, 'result': buf.getvalue()}}
        except Exception:
            return {'status': 'error', 'message': traceback.format_exc()[-2000:], 'result': {'result': buf.getvalue()}}
    return {'status': 'error', 'message': '모르는 명령 %s' % t}


srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(('127.0.0.1', PORT))
srv.listen(4)
print('DAEMON 대기 127.0.0.1:%d Blender %s' % (PORT, bpy.app.version_string), flush=True)
running = True
while running:
    conn, _ = srv.accept()
    with conn:
        buf = b''
        while True:
            ch = conn.recv(65536)
            if not ch:
                break
            buf += ch
            try:
                msg = json.loads(buf.decode())
                break
            except ValueError:
                continue
        else:
            continue
        if not buf:
            continue
        r = handle(msg)
        conn.sendall(json.dumps(r, ensure_ascii=False, default=str).encode())
        running = msg.get('type') != 'quit'
srv.close()
