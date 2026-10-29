"""측정·보고 (눈). 모든 숫자는 메시를 높이 평면으로 잘라 얻는다(래스터 없이 해석적).

수리 대기열 형식(stage, failure, measured_delta, proposed_action, acceptance_gate)은
RobLe3/cc-blender-skill(MIT)의 fit_repair_queue.py 형식을 따른다.
"""
import numpy as np

from .cage import SIDE, edge_counts, is_closed, ring_self_intersections, signed_volume
from .pack import pick
from .util import ERROR, FAIL, PASS, UNKNOWN

DEFAULT_GATES = {
    'G1': {'iou_min': 0.90, 'band_max': 0.10},
    'G2': {'main_max': 0.05, 'manual_max': 0.08},
    'G3': {'ratio_lo': 0.80, 'ratio_hi': 0.92},
    'G4': {'iou_min': 0.95, 'band_max': 0.05, 'sym_max': 1e-6, 'tri_budget': 2000},
}
FAMILY_KO = {'front': '정면 반폭', 'back': '뒤 반폭', 'side_f': '옆 앞끝', 'side_b': '옆 뒤끝', 'width': '반폭(정면·뒤 평균)'}
BAND_FAMILIES = ('front', 'back', 'side_f', 'side_b')


# ---------------------------------------------------------------- 평면 자르기
def unique_edges(F):
    return edge_counts(F)[0]


def slice_points(V, E, h, eps=1e-7):
    """높이 h 평면과 메시 변의 교점(변 위의 정점 포함). 윤곽 다각형의 꼭짓점들이다."""
    a, b = V[E[:, 0]], V[E[:, 1]]
    lo = np.minimum(a[:, 2], b[:, 2])
    hi = np.maximum(a[:, 2], b[:, 2])
    m = (lo <= h + eps) & (hi >= h - eps)
    a, b = a[m], b[m]
    dz = b[:, 2] - a[:, 2]
    flat = np.abs(dz) < 1e-12
    t = np.where(flat, 0.0, (h - a[:, 2]) / np.where(flat, 1.0, dz))
    t = np.clip(t, 0.0, 1.0)
    pts = a + t[:, None] * (b - a)
    if flat.any():                       # 평면 위에 놓인 변은 두 끝점 모두
        pts = np.concatenate([pts, b[flat]])
    pts[:, 2] = h
    return pts


def slab_extents(V, E, zs):
    out = []
    for h in zs:
        p = slice_points(V, E, h)
        if len(p) == 0:
            out.append(None)
        else:
            out.append(p)
    return out


def _iou(lo_m, hi_m, lo_t, hi_t):
    inter = np.clip(np.minimum(hi_m, hi_t) - np.maximum(lo_m, lo_t), 0, None)
    union = (hi_m - lo_m) + (hi_t - lo_t) - inter
    return float(inter.sum() / max(union.sum(), 1e-12))


# ---------------------------------------------------------------- 랜드마크 (모델 쪽)
def model_landmark(name, L, tgt, V, E, roi=None):
    """같은 규칙으로 모델에서 점을 찾는다. 돌려주는 값: 위치(x,y,z), 정점 번호(스냅용) 또는 None."""
    rule, view = L['rule'], L['view']
    if rule == 'extreme':
        # 도면 윤곽 표가 있는 높이 범위 안의 정점만 본다(도면에 없는 아래쪽 목 덩어리는 규칙 밖)
        keep = np.flatnonzero((V[:, 2] >= roi[0] - 1e-9) & (V[:, 2] <= roi[1] + 1e-9)) if roi else np.arange(len(V))
        u = (V[:, 1] if view == 'side' else V[:, 0])[keep]
        i = pick(L, u, V[keep, 2])
        if i is None:
            return None
        i = int(keep[i])
        return {'idx': i, 'pos': V[i].tolist()}
    if rule == 'contour_at':
        z = float(L['z'])
        p = slice_points(V, E, z)
        if len(p) == 0:
            return None
        col = 1 if view == 'side' else 0
        hi = L['edge'] in ('front', 'out', '+')
        val = p[:, col].max() if hi else p[:, col].min()
        # 스냅할 정점: 이 윤곽점과 가장 가까운 정점(옆은 Y·Z, 정면은 X·Z 거리)
        d = np.hypot(V[:, col] - val, V[:, 2] - z)
        if view == 'side':
            d = d + 1e-6 * np.abs(V[:, 0])              # 같은 거리면 중심선 쪽
        i = int(np.argmin(d))
        pos = V[i].tolist()
        pos[col] = float(val)
        pos[2] = z
        return {'idx': i, 'pos': pos, 'contour': True}
    if rule == 'manual':
        tx, tz = tgt['x'], tgt['z']
        p = slice_points(V, E, min(max(tz, V[:, 2].min()), V[:, 2].max()))
        ymid = 0.5 * (p[:, 1].max() + p[:, 1].min()) if len(p) else V[:, 1].mean()
        cand = (V[:, 1] >= ymid) & (V[:, 0] * (1 if tx >= 0 else -1) >= 0)
        if not cand.any():
            return None
        d = np.where(cand, np.hypot(V[:, 0] - tx, V[:, 2] - tz), np.inf)
        i = int(np.argmin(d))
        return {'idx': i, 'pos': V[i].tolist()}
    return None


def landmark_report(pack, V, E):
    out = []
    for name, L in pack.landmarks.items():
        tgt = pack.landmark_target(name)
        item = {'name': name, 'rule': L['rule'], 'conf': tgt.get('conf', '규칙'), 'target': {k: tgt[k] for k in 'xyz'}}
        if 'error' in tgt:
            item.update(verdict=UNKNOWN, why=tgt['error'])
            out.append(item)
            continue
        m = model_landmark(name, L, tgt, V, E, (pack.roi_z[0], pack.top_z))
        if m is None:
            item.update(verdict=UNKNOWN, why='모델에서 규칙에 맞는 점이 없다')
            out.append(item)
            continue
        axes = tgt['axes']
        diff = {}
        for ax in axes:
            k = 'xyz'.index(ax)
            diff[ax] = m['pos'][k] - tgt[ax]
        item.update(axes=axes, model=m['pos'], vertex=m['idx'], diff=diff,
                    dist=float(np.sqrt(sum(v * v for v in diff.values()))))
        if 'z_gap' in tgt:
            item['도면_높이_불일치'] = tgt['z_gap']
        out.append(item)
    return out


# ---------------------------------------------------------------- 대칭 오차
def symmetry_error(V):
    """거울(-x)에 가장 가까운 정점과의 거리의 최댓값."""
    Mv = V * np.array([-1.0, 1.0, 1.0])
    worst = 0.0
    for s in range(0, len(V), 400):
        d = np.linalg.norm(V[s:s + 400, None, :] - Mv[None, :, :], axis=2).min(axis=1)
        worst = max(worst, float(d.max()))
    return worst


# ---------------------------------------------------------------- 본체
def measure_mesh(V, F, pack, cage=None, version=None):
    V = np.asarray(V, float)
    F = np.asarray(F, int)
    E = unique_edges(F)
    z = pack.z
    P = pack.prof
    ext = []
    for h in z:
        p = slice_points(V, E, h)
        ext.append(None if len(p) == 0 else (p[:, 0].min(), p[:, 0].max(), p[:, 1].min(), p[:, 1].max(), p))
    ok = np.array([e is not None for e in ext])
    nan = np.full(len(z), np.nan)
    xmin, xmax, ymin, ymax = nan.copy(), nan.copy(), nan.copy(), nan.copy()
    for k, e in enumerate(ext):
        if e is not None:
            xmin[k], xmax[k], ymin[k], ymax[k] = e[:4]
    hw_m = 0.5 * (xmax - xmin)
    bands = []
    for k, h in enumerate(z):
        if not ok[k]:
            bands.append({'z': float(h), 'missing': True})
            continue
        b = {'z': float(h),
             'front': {'m': hw_m[k], 't': P['front']['hw'][k]},
             'back': {'m': hw_m[k], 't': P['back']['hw'][k]},
             'side_f': {'m': ymax[k], 't': P['side']['hi'][k]},
             'side_b': {'m': ymin[k], 't': P['side']['lo'][k]}}
        for fam in ('front', 'back', 'side_f', 'side_b'):
            b[fam]['e'] = b[fam]['m'] - b[fam]['t']
            b[fam]['m'] = float(b[fam]['m'])
            b[fam]['e'] = float(b[fam]['e'])
        wt = float(pack.hw_target[k])
        b['width'] = {'m': b['front']['m'], 't': wt, 'e': b['front']['m'] - wt}        # 정면·뒤 도면 평균 대비(수리 대기열용)
        b['part'] = pack.part_at(float(h), float(ymax[k]))
        b['part_back'] = pack.part_at(float(h), float(ymin[k]))
        b['rings'] = [] if cage is None else [int(i) for i in np.flatnonzero(np.abs(cage.z - h) < 0.026)]
        bands.append(b)
    # IoU (roi 행 합산, 도면 core 윤곽의 실제 구간과 비교)
    iou = {}
    if ok.all():
        iou['front'] = _iou(xmin, xmax, P['front']['lo'], P['front']['hi'])
        iou['back'] = _iou(xmin, xmax, P['back']['lo'], P['back']['hi'])
        iou['side'] = _iou(ymin, ymax, P['side']['lo'], P['side']['hi'])
    # 띠 오차 최대
    band_max = {'value': None}
    if ok.all():
        best = (-1, None, None)
        for b in bands:
            for fam in (f for f in BAND_FAMILIES if f not in pack.exclude and not (f == 'back' and 'back' in pack.exclude)):
                if abs(b[fam]['e']) > best[0]:
                    best = (abs(b[fam]['e']), fam, b)
        band_max = {'value': float(best[0]), 'family': best[1], 'z': best[2]['z'], 'part': best[2]['part'], 'rings': best[2]['rings']}
    # 3/4 부피: 45° 투영 폭 / 상자 상한
    vol = []
    c45 = np.sqrt(0.5)
    for k, h in enumerate(z):
        if not ok[k]:
            continue
        p = ext[k][4]
        u = c45 * (p[:, 0] - p[:, 1])
        u2 = c45 * (p[:, 0] + p[:, 1])
        w45 = max(u.max() - u.min(), u2.max() - u2.min())
        W = xmax[k] - xmin[k]
        D = ymax[k] - ymin[k]
        box = (W + D) * c45
        ell = np.sqrt((W * W + D * D) / 2.0)
        vol.append({'z': float(h), 'ratio': float(w45 / box), 'ellipse': float(ell / box), 'W': float(W), 'D': float(D)})
    vsum = {}
    if vol:
        r = np.array([v['ratio'] for v in vol])
        vsum = {'min': float(r.min()), 'max': float(r.max()), 'mean': float(r.mean()),
                'ellipse_min': float(min(v['ellipse'] for v in vol)), 'ellipse_max': float(max(v['ellipse'] for v in vol))}
    # 메시 검사
    area2 = np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
    mesh = {'verts': int(len(V)), 'tris': int(len(F)), 'closed': is_closed(F), 'volume': signed_volume(V, F),
            'degenerate': int((area2 < 1e-10).sum()), 'sym_err': symmetry_error(V)}
    if cage is not None:
        mesh['ring_self_intersect'] = ring_self_intersections(cage, V)
        mesh['ring_order_ok'] = bool(np.all(np.diff(cage.z) > 0) and np.all(cage.yf > cage.yb))
    lms = landmark_report(pack, V, E)
    rep = {'version': version, 'bands': bands, 'iou': iou, 'band_max': band_max, 'volume34': vol, 'volume34_summary': vsum,
           'mesh': mesh, 'landmarks': lms,
           'drawing_front_back_gap_max': float(pack.fb_gap.max())}
    rep['worst5'] = worst_items(rep, pack, cage)
    return rep


# ---------------------------------------------------------------- 관문
def evaluate_gates(rep, gates=None):
    g = DEFAULT_GATES if gates is None else {k: {**DEFAULT_GATES[k], **gates.get(k, {})} for k in DEFAULT_GATES}
    out = {}
    iou, bm, mesh = rep['iou'], rep['band_max'], rep['mesh']
    # G1 블록아웃
    c = g['G1']
    if not iou or bm['value'] is None:
        out['G1'] = {'verdict': UNKNOWN, 'why': 'roi 일부 높이에서 모델 단면이 없다'}
    else:
        fails = []
        if min(iou['front'], iou['side']) < c['iou_min']:
            fails.append('IoU 정면 %.3f 옆 %.3f < %.2f' % (iou['front'], iou['side'], c['iou_min']))
        if bm['value'] > c['band_max']:
            fails.append('띠 오차 최대 %.3f > %.2f' % (bm['value'], c['band_max']))
        if not mesh['closed']:
            fails.append('열린 메시')
        out['G1'] = {'verdict': FAIL if fails else PASS, 'why': '; '.join(fails) or '조건 충족',
                     'values': {'iou_front': iou['front'], 'iou_side': iou['side'], 'band_max': bm['value'], 'closed': mesh['closed']}}
    # G2 랜드마크
    c = g['G2']
    fails, unk, vals = [], [], {}
    for lm in rep['landmarks']:
        if lm.get('verdict') == UNKNOWN:
            unk.append('%s: %s' % (lm['name'], lm['why']))
            continue
        lim = c['manual_max'] if lm['rule'] == 'manual' else c['main_max']
        vals[lm['name']] = lm['dist']
        if lm['dist'] > lim:
            fails.append('%s %.3f > %.2f' % (lm['name'], lm['dist'], lim))
    if fails:
        out['G2'] = {'verdict': FAIL, 'why': '; '.join(fails), 'values': vals}
    elif unk:
        out['G2'] = {'verdict': UNKNOWN, 'why': '; '.join(unk), 'values': vals}
    else:
        out['G2'] = {'verdict': PASS, 'why': '조건 충족', 'values': vals}
    # G3 부피 (가설)
    c = g['G3']
    vs = rep['volume34_summary']
    if not vs:
        out['G3'] = {'verdict': UNKNOWN, 'why': '3/4 비율을 계산할 수 없다'}
    else:
        bad = [v for v in rep['volume34'] if not (c['ratio_lo'] <= v['ratio'] <= c['ratio_hi'])]
        out['G3'] = {'verdict': FAIL if bad else PASS,
                     'why': ('%d/%d 띠가 %.2f~%.2f 밖' % (len(bad), len(rep['volume34']), c['ratio_lo'], c['ratio_hi'])) if bad else '모든 띠가 구간 안',
                     'values': vs, 'note': '가설 구간: 들소 3/4 도면을 받으면 보정'}
    # G4 마감
    c = g['G4']
    if not iou or bm['value'] is None:
        out['G4'] = {'verdict': UNKNOWN, 'why': 'roi 일부 높이에서 모델 단면이 없다'}
    else:
        fails = []
        if min(iou['front'], iou['side']) < c['iou_min']:
            fails.append('IoU 정면 %.3f 옆 %.3f < %.2f' % (iou['front'], iou['side'], c['iou_min']))
        if bm['value'] > c['band_max']:
            fails.append('띠 오차 최대 %.3f > %.2f' % (bm['value'], c['band_max']))
        if mesh['sym_err'] > c['sym_max']:
            fails.append('대칭 오차 %.2g' % mesh['sym_err'])
        if mesh['tris'] > c['tri_budget']:
            fails.append('삼각형 %d > 예산 %d' % (mesh['tris'], c['tri_budget']))
        if not mesh['closed']:
            fails.append('열린 메시')
        if mesh.get('ring_self_intersect'):
            fails.append('고리 자기 교차 %s' % mesh['ring_self_intersect'])
        out['G4'] = {'verdict': FAIL if fails else PASS, 'why': '; '.join(fails) or '조건 충족',
                     'values': {'iou_front': iou['front'], 'iou_side': iou['side'], 'band_max': bm['value'],
                                'sym_err': mesh['sym_err'], 'tris': mesh['tris']}}
    # G0 목표 검증: 목표 윤곽이 도면 경계 위에 있지 않으면 G1~G4 의 PASS 를 보증할 수 없다(UNKNOWN 으로 내린다)
    tc = rep.get('target_check')
    if tc and tc.get('verdict') != UNKNOWN or (tc and 'ratio' in tc):
        out['G0'] = {'verdict': tc['verdict'], 'why': tc['why'], 'values': {'ratio': tc.get('ratio')}}
        if tc['verdict'] != PASS:
            for k in ('G1', 'G2', 'G3', 'G4'):
                if out[k]['verdict'] == PASS:
                    out[k] = {**out[k], 'verdict': UNKNOWN, 'why': '모델은 목표에 맞지만 목표가 도면과 맞는지 G0=%s 라 보증 못 함 (%s)' % (tc['verdict'], out[k]['why'])}
    return out


# ---------------------------------------------------------------- 수리 대기열: 최악 5개
def worst_items(rep, pack, cage=None, limit=5, thr=0.02):
    items = []
    bands = [b for b in rep['bands'] if not b.get('missing')]
    for fam in ('width', 'side_f', 'side_b'):
        run = []
        for b in bands + [None]:
            if b is not None and abs(b[fam]['e']) >= thr and (not run or np.sign(b[fam]['e']) == np.sign(run[-1][fam]['e'])):
                run.append(b)
                continue
            if run:
                e = max(run[i][fam]['e'] for i in range(len(run))) if run[0][fam]['e'] > 0 else min(r[fam]['e'] for r in run)
                z0, z1 = run[0]['z'], run[-1]['z']
                part = run[int(np.argmax([abs(r[fam]['e']) for r in run]))]['part' if fam != 'side_b' else 'part_back']
                rings = sorted({i for r in run for i in r['rings']})
                view = 'width' if fam == 'width' else 'side'
                sign = '모델이 큼' if e > 0 else '모델이 작음'
                stage = 'G1' if abs(e) > DEFAULT_GATES['G1']['band_max'] else 'G4'
                items.append({'mag': abs(e), 'stage': stage,
                              'failure': '%s z%.2f~%.2f %s' % (FAMILY_KO[fam], z0, z1, sign),
                              'measured_delta': round(float(e), 4), 'part': part,
                              'rings': '%d~%d' % (rings[0], rings[-1]) if rings else '-',
                              'proposed_action': 'fit --view %s --z %.2f %.2f' % (view, z0, z1),
                              'acceptance_gate': '띠 오차 ≤ %.2f' % DEFAULT_GATES[stage]['band_max']})
            run = [b] if (b is not None and abs(b[fam]['e']) >= thr) else []
    for lm in rep['landmarks']:
        lim = DEFAULT_GATES['G2']['manual_max'] if lm['rule'] == 'manual' else DEFAULT_GATES['G2']['main_max']
        if lm.get('dist', 0) > lim * 0.4:
            items.append({'mag': lm['dist'], 'stage': 'G2', 'failure': '랜드마크 %s 어긋남 (%s)' % (lm['name'], ' '.join('%s%+.3f' % (a, v) for a, v in lm['diff'].items())),
                          'measured_delta': round(lm['dist'], 4), 'part': '-', 'rings': '-',
                          'proposed_action': 'snap %s' % lm['name'], 'acceptance_gate': '오차 ≤ %.2f' % lim})
    c = DEFAULT_GATES['G3']
    bad = [v for v in rep['volume34'] if not (c['ratio_lo'] <= v['ratio'] <= c['ratio_hi'])]
    if bad:
        z0, z1 = bad[0]['z'], bad[-1]['z']
        low = np.mean([v['ratio'] for v in bad]) < c['ratio_lo']
        items.append({'mag': 0.5 * max(abs(v['ratio'] - np.clip(v['ratio'], c['ratio_lo'], c['ratio_hi'])) for v in bad),
                      'stage': 'G3', 'failure': '3/4 비율 %d띠가 구간 밖(%s)' % (len(bad), '낮음' if low else '높음'),
                      'measured_delta': round(float(np.mean([v['ratio'] for v in bad])), 3), 'part': '-', 'rings': '-',
                      'proposed_action': 'round --z %.2f %.2f --n %s' % (z0, z1, '더 크게(네모)' if low else '더 작게(둥글게)'),
                      'acceptance_gate': '비율 %.2f~%.2f' % (c['ratio_lo'], c['ratio_hi'])})
    items.sort(key=lambda x: -x['mag'])
    for it in items:
        it.pop('mag')
    return items[:limit]


# ---------------------------------------------------------------- 사람이 읽는 요약 (20줄 이하)
def summary_lines(rep, gates):
    iou = rep['iou']
    L = []
    if iou:
        L.append('IoU 정면 %.3f 옆 %.3f 뒤 %.3f | 띠 오차 최대 %.3f (%s z%.2f 부위=%s)' % (
            iou['front'], iou['side'], iou['back'], rep['band_max']['value'], FAMILY_KO[rep['band_max']['family']],
            rep['band_max']['z'], rep['band_max']['part']))
    lm = ' '.join('%s %.3f' % (x['name'], x['dist']) for x in rep['landmarks'] if 'dist' in x)
    L.append('랜드마크 오차: ' + (lm or '없음'))
    vs = rep['volume34_summary']
    if vs:
        L.append('3/4 비율 %.3f~%.3f (타원 하한 %.3f~%.3f)' % (vs['min'], vs['max'], vs['ellipse_min'], vs['ellipse_max']))
    m = rep['mesh']
    L.append('메시: 정점 %d 삼각형 %d 닫힘=%s 대칭오차 %.1e%s' % (m['verts'], m['tris'], m['closed'], m['sym_err'],
                                                        ' 고리교차 %s' % m['ring_self_intersect'] if m.get('ring_self_intersect') else ''))
    L.append('관문: ' + ' '.join('%s=%s' % (k, v['verdict']) for k, v in gates.items()))
    if rep['worst5']:
        L.append('최악 %d (수리 대기열):' % len(rep['worst5']))
        for i, it in enumerate(rep['worst5'], 1):
            L.append(' %d. [%s] %s Δ%+.3f 부위=%s 고리=%s → %s' % (i, it['stage'], it['failure'], it['measured_delta'], it['part'], it['rings'], it['proposed_action']))
    return L
