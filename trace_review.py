# -*- coding: utf-8 -*-
r"""교정 후보 검토(LLM 판단용). SAM-Veteran·MedSAM-Agent 를 참고해 LLM 은 좌표를 그리지 않고 번호에 답한다.
  python trace_review.py candidates --spec S.json [--base 상대경로 기준 spec]  → <out>/review.png(번호 붙은 후보) + review.json
  (LLM 이 review.png 를 보고 S.json 의 "clicks": [{"id": 3, "결정": "넣기"|"빼기"|"그대로", "근거": "..."}] 를 적는다)
  python trace_review.py apply --spec S.json [--base ...]   → 점을 하나씩 실행, 독립 검사 손실이 나빠지면 그 점을 되돌린다(과교정 방지)
빠진 재질 찾기(Set-of-Mark, v2): 묶기 전체가 아니라 "목록에 없는 물감으로 칠한 군집 번호는?" 한 질문(L13·L18)
  python trace_review.py groups --spec S.json   → <out>/groups.png(군집마다 번호 칸) + groups_prompt_A.txt / _B.txt(목록 순서만 다름)
  (서로 다른 LLM 가족 둘이 따로 답해 groups_A.json / groups_B.json 을 쓴다: {"new": [번호], "part": "부위"})
  python trace_review.py groups_merge --spec S.json [--write]  → 두 답이 같은 번호·부위만 새 재질로(cluster_mats, part_mats 에 더함)
  군집이 모자라면 빠진 재질이 다른 재질과 한 군집에 섞인다: 사양 k 를 12 정도로
"""
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
import trace as T  # noqa: E402
import trace_loop as L  # noqa: E402
from harness.render import write_png  # noqa: E402
from harness.trace import apply_click, click_candidates, overlay, trace_parts_region  # noqa: E402

from harness.groups_review import merge_new, prompt_new, sheet as groups_sheet, stamp as _stamp, cluster_stats  # noqa: E402


def stamp(img, x, y, text, col):
    _stamp(img, x, y, text, col, s=3)


def main(argv):
    cmd, sp = argv[0], argv[argv.index('--spec') + 1]
    base = argv[argv.index('--base') + 1] if '--base' in argv else sp
    S = T.jload(sp)
    if cmd in ('groups', 'groups_merge'):
        return groups_main(cmd, S, sp, base, '--write' in argv)
    T._CACHE.clear()
    res = T.build(S, base, write=False)
    tone = T._CACHE[list(T._CACHE)[0]][-1]
    polys = trace_parts_region.polys
    if cmd == 'candidates':
        cands = click_candidates(res['masks'], res['mat'], tone, polys, S['part_mats'], res['names'], ['front', 'side'], d=S.get('snap_px', 8))
        img = overlay(res['img'], res['masks'], {'all': (0, res['img'].shape[0], 0, res['img'].shape[1])}, scale=1)
        img = img[:res['img'].shape[0], :res['img'].shape[1]].copy()
        tiles = []
        for v, (r0, r1, c0, c1) in res['boxes'].items():
            if v == 'back':
                continue
            t = np.repeat(np.repeat(img[r0:r1, c0:c1], 3, 0), 3, 1).copy()
            for c in cands:
                if c['view'] == v:
                    col = (0, 200, 0) if c['sign'] == '+' else (220, 0, 220)
                    yy, xx = (c['y'] - r0) * 3, (c['x'] - c0) * 3
                    t[max(0, yy - 4):yy + 5, max(0, xx - 4):xx + 5] = col
                    stamp(t, xx + 8, yy - 6, str(c['id']), col)
            tiles.append(t)
        H = max(t.shape[0] for t in tiles)
        write_png(os.path.join(res['out'], 'review.png'), np.concatenate([np.pad(t, ((0, H - t.shape[0]), (0, 10), (0, 0)), constant_values=255) for t in tiles], 1))
        json.dump(cands, open(os.path.join(res['out'], 'review.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        for c in cands:
            print('REVIEW #%d %s|%s %s (%d,%d) %dpx' % (c['id'], c['view'], c['part'], '넣기 후보(초록)' if c['sign'] == '+' else '빼기 후보(자주)', c['x'], c['y'], c['px']))
        return 0
    cands = {c['id']: c for c in json.load(open(os.path.join(res['out'], 'review.json'), encoding='utf-8'))}
    masks = res['masks']
    L0 = L.loss(L.checks(res), res)
    print('APPLY 시작 손실 %.3f' % L0)
    log = []
    for dcs in S.get('clicks', []):
        if dcs['결정'] == '그대로':
            continue
        c = dict(cands[dcs['id']])
        c['sign'] = '+' if dcs['결정'] == '넣기' else '-'
        backup = {k: m.copy() for k, m in masks.items()}
        n = apply_click(masks, res['mat'], tone, polys, c, d=S.get('snap_px', 8))
        L1 = L.loss(L.checks(res), res)
        ok = L1 <= L0 + 0.05
        if not ok:
            masks.clear()
            masks.update(backup)
        log.append({'id': dcs['id'], '결정': dcs['결정'], '픽셀': n, '손실': round(L1, 3), '채택': ok, '근거': dcs.get('근거', '')})
        print('APPLY #%d %s %dpx 손실 %.3f → %s' % (dcs['id'], dcs['결정'], n, L1, '채택' if ok else '되돌림(독립 검사 나빠짐)'))
        if ok:
            L0 = L1
    np.savez_compressed(os.path.join(res['out'], 'masks.npz'), **{'%s|%s' % k: v for k, v in masks.items()})
    json.dump(log, open(os.path.join(res['out'], 'clicks_log.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    write_png(os.path.join(res['out'], 'overlay_clicks.png'), overlay(res['img'], masks, res['boxes']))
    return 0


def groups_main(cmd, S, sp, base, write):
    S0 = dict(S)
    S0.pop('cluster_mats', None)                       # 검토는 기본 묶음 기준으로
    T._CACHE.clear()
    res = T.build(S0, base, write=False)
    img, boxes, C, mat, names, cmap, lab = T._CACHE[list(T._CACHE)[0]]
    out = res['out']
    if cmd == 'groups':
        write_png(os.path.join(out, 'groups.png'), groups_sheet(img, lab, boxes))
        mats = [n for n in names if n != '배경']
        for tag in ('A', 'B'):
            open(os.path.join(out, 'groups_prompt_%s.txt' % tag), 'w', encoding='utf-8').write(prompt_new(mats, sorted(S['part_mats']), tag))
        json.dump({'기본': cmap, '군집': cluster_stats(img, lab, boxes)}, open(os.path.join(out, 'groups.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('GROUPS 군집 %d개 → %s/groups.png, groups_prompt_A.txt(LLM 가족 1), groups_prompt_B.txt(다른 가족)' % (int(lab.max()) + 1, out))
        return 0
    a = T.jload(os.path.join(out, 'groups_A.json'))
    b = T.jload(os.path.join(out, 'groups_B.json'))
    cm, add, info = merge_new(a, b)
    print('GROUPS 빠진 재질', info, 'cluster_mats', cm, 'part_mats_add', add)
    json.dump({'cluster_mats': cm, 'part_mats_add': add, '기록': info}, open(os.path.join(out, 'groups_merge.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if write:
        S['cluster_mats'] = cm
        for part, ms in add.items():
            S['part_mats'][part] = list(dict.fromkeys(S['part_mats'].get(part, []) + ms))
        json.dump(S, open(sp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('GROUPS 사양에 적음', sp)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
