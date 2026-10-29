# -*- coding: utf-8 -*-
"""SAM 2.1(tiny, CPU) 다리: 거친 다각형(LLM)을 힌트(감싸는 상자 + 안쪽 점)로 바꿔 별도 환경의 작업자(tools/sam_worker.py)를 부른다.
선택 기능(기본 아님, 트레이스 사양 method_by_part {"귀": "sam"}). SAM 단독(bench/sam_bench.py)은 귀에서 나았다: 개발 씨앗 68~79
정면 0.924→0.956·옆 0.671→0.709, 새 씨앗 80~91 정면 0.910→0.945·옆 0.664→0.786. 다른 부위는 우리 방식이 나았다(정면 뿔 0.976 대 0.865).
파이프라인에 넣자 옆 귀 0.664→0.619 로 떨어졌다. 원인: 겹침 해소가 다각형 기준이라 SAM 귀 559px 가 머리로 감(bench/sam_diag.py).
그림 근거 우선(harness/trace.py resolve_overlaps priority) 뒤: 씨앗 80~91 옆 귀 0.777, 새 씨앗 92~103 옆 귀 0.654→0.695·정면 0.927→0.952 → 귀 기본값.
별도 환경이 없으면 ERROR 대신 우리 방식 결과를 그대로 두고 이유를 남긴다(segment.skipped).
"""
import json
import os
import subprocess
import tempfile

import numpy as np

from .vendor import ndi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPY = os.path.join(ROOT, '.venv_sam', 'Scripts', 'python.exe')
WORKER = os.path.join(ROOT, 'tools', 'sam_worker.py')


def _inner(m):
    d = ndi.distance_transform_edt(m)
    y, x = np.unravel_index(np.argmax(d), d.shape)
    return [float(x) + 0.5, float(y) + 0.5]


def segment(crop, polys, keys, tile=None):
    """crop: 뷰 상자 그림. polys {키: 다각형 마스크(crop 크기)}. keys: SAM 으로 딸 키. 반환 {키: 마스크}."""
    segment.skipped = None
    if not os.path.exists(SAMPY):
        segment.skipped = 'SAM 환경(.venv_sam) 없음'
        return {}
    prompts, clip = [], {}
    for k in keys:
        lab, n = ndi.label(polys[k])
        for i in range(1, n + 1):
            m = lab == i
            if m.sum() < 10:
                continue
            ys, xs = np.nonzero(m)
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            if tile and max(y1 - y0, x1 - x0) > 1.5 * tile:
                # 쪼개기(사용자 제안 "SAM 도 부위를 잘게 쪼개서 시키면"): 큰 다각형을 tile 칸으로 나눠 칸마다 상자 + 안쪽 점.
                # 결과는 그 칸 둘레(tile/4)로만 잘라 합친다. SAM 은 작은 부위(귀)에서 낫고 큰 부위(머리·뿔)에서 졌다
                for cy in range(y0, y1, tile):
                    for cx in range(x0, x1, tile):
                        cell = np.zeros_like(m)
                        cell[cy:cy + tile, cx:cx + tile] = True
                        c = m & cell
                        if c.sum() < 0.3 * tile * tile:
                            continue
                        cy_, cx_ = np.nonzero(c)
                        pad = tile // 4
                        pid = '%s|%d_%d_%d' % (k[1], i, cy, cx)
                        prompts.append({'id': pid, 'box': [int(max(cx_.min() - pad, 0)), int(max(cy_.min() - pad, 0)), int(cx_.max() + pad), int(cy_.max() + pad)], 'pos': [_inner(c)]})
                        clip[pid] = (max(cy - pad, 0), cy + tile + pad, max(cx - pad, 0), cx + tile + pad)
                continue
            prompts.append({'id': '%s|%d' % (k[1], i), 'box': [int(x0), int(y0), int(x1 - 1), int(y1 - 1)], 'pos': [_inner(m)]})
    if not prompts:
        return {}
    with tempfile.TemporaryDirectory() as d:
        np.savez(os.path.join(d, 'in.npz'), image=np.ascontiguousarray(crop[..., :3]).astype(np.uint8))
        json.dump(prompts, open(os.path.join(d, 'p.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        r = subprocess.run([SAMPY, WORKER, os.path.join(d, 'in.npz'), os.path.join(d, 'p.json'), os.path.join(d, 'out.npz')],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode:
            segment.skipped = 'SAM 작업자 실패: ' + r.stderr[-300:]
            return {}
        with np.load(os.path.join(d, 'out.npz')) as Z:          # 윈도우: 파일을 닫아야 임시 폴더를 지울 수 있다
            got = {pid: Z[pid] for pid in Z.files}
    out = {}
    for k in keys:
        for pid, m in got.items():
            if pid.rsplit('|', 1)[0] == k[1]:
                if pid in clip:
                    r0, r1, c0, c1 = clip[pid]
                    mm = np.zeros_like(m)
                    mm[r0:r1, c0:c1] = m[r0:r1, c0:c1]
                    m = mm
                out[k] = out.get(k, np.zeros(crop.shape[:2], bool)) | m
    return out
