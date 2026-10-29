# -*- coding: utf-8 -*-
"""창 없는 Blender 상주 서버(blender_daemon.py)의 손님 쪽. 없으면 띄우고, 명령을 보내고, 다 쓰면 끈다.
  from harness.blender_client import Blender
  with Blender() as b:
      print(b.run("import bpy; print(len(bpy.data.objects))"))
"""
import json
import os
import socket
import subprocess
import time

BLENDER = os.path.join('C:' + os.sep, 'Program Files', 'Blender Foundation', 'Blender 5.2', 'blender.exe')
DAEMON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'blender_daemon.py')


def send(msg, port=9877, timeout=600):
    s = socket.create_connection(('127.0.0.1', port), timeout=timeout)
    s.sendall(json.dumps(msg).encode())
    s.shutdown(socket.SHUT_WR)
    buf = b''
    while True:
        ch = s.recv(65536)
        if not ch:
            break
        buf += ch
    s.close()
    return json.loads(buf.decode())


class Blender:
    def __init__(self, port=9877, keep=False):
        self.port, self.keep, self.proc = port, keep, None

    def up(self):
        try:
            return send({'type': 'ping'}, self.port, timeout=2)['status'] == 'success'
        except OSError:
            return False

    def __enter__(self):
        if not self.up():
            self.proc = subprocess.Popen([BLENDER, '-b', '--factory-startup', '-P', DAEMON, '--', str(self.port)],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            t0 = time.time()
            while not self.up():
                if time.time() - t0 > 60 or self.proc.poll() is not None:
                    raise RuntimeError('창 없는 Blender 가 뜨지 않음')
                time.sleep(0.3)
        return self

    def run(self, code):
        r = send({'type': 'execute_code', 'params': {'code': code}}, self.port)
        if r['status'] != 'success':
            raise RuntimeError(r.get('message', str(r))[-800:])
        return r['result']['result']

    def __exit__(self, *a):
        if self.proc is not None and not self.keep:
            try:
                send({'type': 'quit'}, self.port, timeout=5)
            except OSError:
                pass
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
