"""옛 머리(OBJ, 머리 공간 좌표)를 H 좌표로 올려 새 머리와 같은 측정표로 비교한다.

변환(머리 공간 hu → H): 옛 조립 규칙 = 머리 메시 × 0.65 를 neck 앵커가 상체 neck 뼈에 오게 붙임
  → H 좌표 = (v - neck_hu) / 0.92 + 상체 neck 뼈 위치(H).   (0.65 / 0.598 = 1 / 0.92)
- 높이(Z): 옛 스크립트 주석 "몸통 neck 뼈 높이 4.78H, 턱 4.485H" 를 따른다(근거는 주석뿐).
- 앞뒤(Y): 상체 neck 뼈의 앞뒤 위치는 상체 부품 anchors.json(bison_bp/torso)에 있는데 저장소에 없다.
  → 확정할 수 없어 UNKNOWN. 대신 (a) 앞뒤 위치와 무관한 지표, (b) 옛 머리에 가장 유리한 앞뒤 정렬(상한)로 비교한다.
"""
import os

import numpy as np

from .export import read_obj
from .measure import evaluate_gates, measure_mesh, FAMILY_KO
from .util import jload

NECK_BONE_Z_H = 4.78


def to_H(V_hu, anchors, yn):
    H = anchors['H_hu']
    neck = np.array(anchors['neck']['pos'])                      # (x, y 위, z 앞)
    X = V_hu[:, 0] / H
    Z = NECK_BONE_Z_H + (V_hu[:, 1] - neck[1]) / H
    Y = yn + (V_hu[:, 2] - neck[2]) / H
    return np.stack([X, Y, Z], 1)


def head_only(rep):
    """머리가 단독으로 만드는 윤곽만: 옆 앞끝 전 구간, 옆 뒤끝·반폭은 어깨·혹 위쪽(z≥4.85·4.75)."""
    best = (0.0, '-', 0.0)
    for b in rep['bands']:
        if b.get('missing'):
            continue
        cand = [('side_f', b['side_f']['e'])]
        if b['z'] >= 4.85:
            cand.append(('side_b', b['side_b']['e']))
        if b['z'] >= 4.75:
            cand.append(('width', b['width']['e']))
        for fam, e in cand:
            if abs(e) > best[0]:
                best = (abs(e), fam, b['z'])
    return best


def _row(label, a, b):
    return '| %s | %s | %s |' % (label, a, b)


def _inv(rep):
    """앞뒤 정렬과 무관한 지표: 코끝-후두 앞뒤 거리, 코끝-턱끝 높이 차."""
    lm = {x['name']: x for x in rep['landmarks'] if 'model' in x}
    out = {}
    if '코끝' in lm and '후두' in lm:
        out['코끝-후두 앞뒤'] = lm['코끝']['model'][1] - lm['후두']['model'][1]
    if '코끝' in lm and '턱끝' in lm:
        out['코끝-턱끝 높이'] = lm['코끝']['model'][2] - lm['턱끝']['model'][2]
        out['코끝-턱끝 앞뒤'] = lm['코끝']['model'][1] - lm['턱끝']['model'][1]
    return out


def compare(ses, cage, obj, ynb, out=None):
    pack = ses.pack
    root = os.path.dirname(obj)
    anc = jload(os.path.join(root, 'old_anchors_head.json'))
    V0, F = read_obj(obj)

    def meas(yn):
        V = to_H(V0, anc, yn)
        return V, measure_mesh(V, F, pack)

    sweep = {}
    if ynb == 'best':
        best = (-1, None)
        for yn in np.arange(-0.8, 1.2001, 0.01):
            V, r = meas(float(yn))
            sc = r['iou'].get('side', 0)
            sweep[round(float(yn), 3)] = sc
            if sc > best[0]:
                best = (sc, float(yn))
        yn = best[1]
        yn_note = 'Y 정렬 = 옆 IoU 가 가장 큰 값(옛 머리에 가장 유리한 상한). 실제 neck 뼈 앞뒤 위치는 UNKNOWN'
    else:
        yn = float(ynb)
        yn_note = 'Y 정렬 = 사용자 지정 %.3f' % yn
    Vo, ro = meas(yn)
    go = evaluate_gates(ro, ses.gates)
    Vn, Fn, _ = cage.mesh()
    rn = measure_mesh(Vn, Fn, pack, cage)
    gn = evaluate_gates(rn, ses.gates)

    L = []
    L.append('## 옛 머리 vs 새 머리 (같은 측정표)')
    L.append('')
    L.append('- 옛 머리: `%s` (정점 %d, 삼각형 %d), 머리 공간 → H 변환. 높이 = 몸통 neck 뼈 %.2fH(옛 스크립트 주석). %s' % (os.path.basename(obj), len(V0), len(F), NECK_BONE_Z_H, yn_note))
    L.append('- 선택한 Y 정렬(neck 뼈 앞뒤 위치) = %.3fH' % yn)
    L.append('')
    L.append('| 항목 | 옛 머리 | 새 머리 |')
    L.append('|---|---|---|')
    f3 = lambda x: '%.3f' % x
    for k, ko in (('front', '정면'), ('side', '옆'), ('back', '뒤')):
        L.append(_row('IoU ' + ko, f3(ro['iou'][k]), f3(rn['iou'][k])))
    bo, bn = ro['band_max'], rn['band_max']
    L.append(_row('띠 오차 최대(전 구간, H)', '%.3f (%s z%.2f)' % (bo['value'], FAMILY_KO[bo['family']], bo['z']), '%.3f (%s z%.2f)' % (bn['value'], FAMILY_KO[bn['family']], bn['z'])))
    ho, hn = head_only(ro), head_only(rn)
    L.append(_row('머리 전용 띠 오차 최대(H)', '%.3f (%s z%.2f)' % (ho[0], FAMILY_KO.get(ho[1], ho[1]), ho[2]), '%.3f (%s z%.2f)' % (hn[0], FAMILY_KO.get(hn[1], hn[1]), hn[2])))
    lo = {x['name']: x for x in ro['landmarks']}
    ln = {x['name']: x for x in rn['landmarks']}
    for name in pack.landmarks:
        a = lo.get(name, {})
        b = ln.get(name, {})
        fa = '%.3f' % a['dist'] if 'dist' in a else a.get('verdict', '-')
        fb = '%.3f' % b['dist'] if 'dist' in b else b.get('verdict', '-')
        L.append(_row('랜드마크 %s 오차(H, %s)' % (name, a.get('axes', '')), fa, fb))
    io, i_n = _inv(ro), _inv(rn)
    tgt = {x['name']: x['target'] for x in rn['landmarks']}
    if '코끝' in tgt and '후두' in tgt:
        d_t = tgt['코끝']['y'] - tgt['후두']['y']
        L.append(_row('코끝-후두 앞뒤 거리 (도면 %.3fH)' % d_t, '%.3f (%+.3f)' % (io['코끝-후두 앞뒤'], io['코끝-후두 앞뒤'] - d_t),
                      '%.3f (%+.3f)' % (i_n['코끝-후두 앞뒤'], i_n['코끝-후두 앞뒤'] - d_t)))
    if '코끝' in tgt and '턱끝' in tgt:
        d_z = tgt['코끝']['z'] - tgt['턱끝']['z']
        L.append(_row('코끝-턱끝 높이 차 (도면 %.3fH)' % d_z, '%.3f (%+.3f)' % (io['코끝-턱끝 높이'], io['코끝-턱끝 높이'] - d_z),
                      '%.3f (%+.3f)' % (i_n['코끝-턱끝 높이'], i_n['코끝-턱끝 높이'] - d_z)))
    for g in ('G1', 'G2', 'G3', 'G4'):
        L.append(_row('관문 ' + g, '%s — %s' % (go[g]['verdict'], go[g]['why']), '%s — %s' % (gn[g]['verdict'], gn[g]['why'])))
    vo, vn = ro['volume34_summary'], rn['volume34_summary']
    L.append(_row('3/4 비율 최소~최대 (타원 하한~상한)', '%.3f~%.3f (%.3f~%.3f)' % (vo['min'], vo['max'], vo['ellipse_min'], vo['ellipse_max']),
                  '%.3f~%.3f (%.3f~%.3f)' % (vn['min'], vn['max'], vn['ellipse_min'], vn['ellipse_max'])))
    L.append(_row('삼각형 / 닫힘 / 대칭 오차', '%d / %s / %.1e' % (ro['mesh']['tris'], ro['mesh']['closed'], ro['mesh']['sym_err']),
                  '%d / %s / %.1e' % (rn['mesh']['tris'], rn['mesh']['closed'], rn['mesh']['sym_err'])))
    L.append('')
    if sweep:
        ys = sorted(sweep)
        pick = [y for y in ys if abs(y - yn) in (min(abs(q - yn) for q in ys),)][:1] + [y for y in ys if abs(y - (yn - 0.1)) < 0.006] + [y for y in ys if abs(y - (yn + 0.1)) < 0.006]
        L.append('Y 정렬 민감도(옆 IoU): ' + ', '.join('Y%.2f → %.3f' % (y, sweep[y]) for y in sorted(set(pick))))
    text = '\n'.join(L)
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
    return text
