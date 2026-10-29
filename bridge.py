# -*- coding: utf-8 -*-
"""1단계(mh.py) 결과 OBJ → 2단계(fitloop.py) spec.json 연결.
팩(pack.json)의 도면 틀·랜드마크 규칙을 그대로 옮긴다. 좌표를 새로 만들지 않는다.
OBJ 는 H 단위(mh export 기본)라 블렌더 단위(×H_blender)로 바꿔 쓴다. 핸들은 팩 랜드마크 중 extreme 규칙마다 Hook 하나.
실행: python bridge.py --pack packs/head_only/pack.json --obj X.obj --masks fixtures/bison_head/target_head --out work/dir
이후: blender -b -P fitloop.py -- attach <out>/spec.json ; ... -- run <out>/spec.json
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness.export import read_obj, write_obj  # noqa: E402
from harness.pack import Pack  # noqa: E402


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', required=True)
    ap.add_argument('--obj', required=True)
    ap.add_argument('--masks', required=True, help='목표 마스크 접두(<접두>_front.npy, <접두>_side.npy)')
    ap.add_argument('--out', required=True)
    ap.add_argument('--radius', type=float, default=0.9)
    ns = ap.parse_args(argv)
    pk = Pack(ns.pack)
    os.makedirs(ns.out, exist_ok=True)
    Hb = float(pk.d['H_blender'])
    V, F = read_obj(ns.obj)[:2]
    obj = os.path.join(ns.out, 'mesh_bu.obj')
    write_obj(obj, V * Hb, F)
    frame = {'H_bu': Hb, 'px_per_H': pk.ppH, 'ground_row': pk.ground, 'shape': [1024, 1536],
             'xc': {v: float(pk.panels[v]['center_x']) for v in ('front', 'side')}}
    handles, metrics = [], []
    for name, lm in pk.landmarks.items():
        if lm.get('rule') != 'extreme' or lm['view'] != 'side':
            continue
        rule = {k: lm[k] for k in ('rule', 'view', 'dir', 'z')}
        handles.append({'name': 'CTRL_' + name, 'kind': 'hook', 'axes': 'yz', 'select': {'rule': rule, 'radius': ns.radius}, 'init': {}})
        metrics.append({'name': name, 'kind': 'extreme', 'view': lm['view'], 'dir': lm['dir'], 'z': lm['z']})
    if not handles:
        sys.exit('ERROR: 팩에 side extreme 랜드마크가 없어 핸들을 만들 수 없다')
    z0, z1 = pk.roi_z
    spec = {'frame': frame, 'mesh_obj': obj, 'mesh_object': 'head', 'out': os.path.join(ns.out, 'run'),
            'target_masks': {v: ns.masks + '_%s.npy' % v for v in ('front', 'side')},
            'handles': handles, 'metrics': metrics, 'protected': [],
            'report': [{'name': 'IoU옆', 'kind': 'iou', 'view': 'side', 'z': [z0, z1]},
                       {'name': 'IoU정면', 'kind': 'iou', 'view': 'front', 'z': [z0, z1]}],
            'step_frac': 0.5, 'tol': 0.008, 'max_steps': 10}
    p = os.path.join(ns.out, 'spec.json')
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    print('BRIDGE spec', p, '핸들', [h['name'] for h in handles], '정점', len(V))


if __name__ == '__main__':
    main(sys.argv[1:])
