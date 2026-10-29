# -*- coding: utf-8 -*-
"""분해선 부위(뿔·귀 등)를 관으로 만들어 OBJ 로 저장하고, 같은 래스터 함수로 도면 부위 마스크와 IoU 를 잰다.
실행: python parts.py --pack packs/head_jaw/pack.json --parts 뿔 귀 --out results/bison_head_try5
"""
import argparse
import importlib
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'fixtures', 'bison_head'))
import fitloop  # noqa: E402
from harness.export import write_obj  # noqa: E402
from harness.pack import Pack  # noqa: E402
from harness.tube import _mask, build_tube  # noqa: E402


def iou(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else float('nan')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', required=True)
    ap.add_argument('--parts', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ns = ap.parse_args(argv)
    pk = Pack(ns.pack)
    sys.modules['trace_common'] = importlib.import_module('ref_trace_common')
    T = sys.modules['trace_common']
    bun = json.load(open(os.path.join(HERE, 'fixtures', 'bison_head', 'bunhae_dosi1.json'), encoding='utf-8'))
    os.makedirs(ns.out, exist_ok=True)
    Hb = float(pk.d['H_blender'])
    frame = {'H_bu': Hb, 'px_per_H': pk.ppH, 'ground_row': pk.ground, 'shape': [1024, 1536],
             'xc': {v: float(pk.panels[v]['center_x']) for v in ('front', 'side')}}
    fitloop.set_frame(frame)
    rep = {}
    for part in ns.parts:
        V, F, isl = build_tube(pk, bun, part, T)
        if len(F) == 0:
            rep[part] = {'판정': 'UNKNOWN', '이유': '섬 행 수 부족'}
            continue
        write_obj(os.path.join(ns.out, 'part_%s_h.obj' % part), V, F)
        masks = fitloop.masks_of(V * Hb, F, frame, ['front', 'side'])
        r = {"섬": isl, '정점': len(V), '삼각형': len(F)}
        for v in ('front', 'side'):
            r['IoU_' + v] = round(iou(masks[v], _mask(T, bun, v, part)), 3)
        rep[part] = r
        print('PART', part, json.dumps(r, ensure_ascii=False))
    json.dump(rep, open(os.path.join(ns.out, 'parts.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main(sys.argv[1:])
