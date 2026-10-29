"""참조 팩: 도면 패널 좌표계, 높이별 윤곽(profile), 실루엣 다각형, 랜드마크 규칙, 부위 범위.

랜드마크는 규칙으로만 정의한다(좌표를 손으로 적지 않는다). 같은 규칙(`pick`)을 도면에도 모델에도 똑같이 적용한다.
"""
import os
import subprocess

import numpy as np

from .util import HarnessError, jdump, jload

BLENDER_EXE = r'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
VIEWS = ('front', 'side', 'back')


# ---------------------------------------------------------------- 규칙 적용 (도면·모델 공용)
def _score(direction, u, v):
    """dir 문자열('+Y','-Z' 등) → 점수 배열. 옆 뷰는 u=Y, 정면·뒤 뷰는 u=X, v=Z."""
    sign = 1.0 if direction[0] == '+' else -1.0
    ax = direction[1].upper()
    return sign * (v if ax == 'Z' else u)


def pick(rule, u, v):
    """극점 규칙을 점 집합(u,v)에 적용해 고른 점의 번호를 돌려준다. 없으면 None."""
    u = np.asarray(u, float)
    v = np.asarray(v, float)
    m = np.ones(len(u), bool)
    eps = 1e-9
    if 'z' in rule:
        m &= (v >= rule['z'][0] - eps) & (v <= rule['z'][1] + eps)
    lat = 'y' if rule['view'] == 'side' else 'x'
    if lat in rule:
        m &= (u >= rule[lat][0] - eps) & (u <= rule[lat][1] + eps)
    if not m.any():
        return None
    s = _score(rule['dir'], u, v)
    best = s[m].max()
    cand = m & (s >= best - 1e-6)
    if cand.sum() > 1:
        # 같은 점수가 여럿이면 규칙의 tie 방향(없으면 주축이 아닌 쪽의 큰 값)으로 고른다
        tie = rule.get('tie') or ('+Z' if rule['dir'][1].upper() != 'Z' else ('+Y' if rule['view'] == 'side' else '+X'))
        s2 = _score(tie, u, v)
        best2 = s2[cand].max()
        cand &= s2 >= best2 - 1e-6
    return int(np.flatnonzero(cand)[0])


class Pack:
    def __init__(self, path):
        path = os.path.abspath(path)
        self.path = path
        self.dir = os.path.dirname(path)
        self.d = jload(path)
        self.name = self.d['name']
        f = self.d['files']
        self.profile_raw = jload(self._rel(f['profile']))
        self.silh = jload(self._rel(f['silhouette'])) if f.get('silhouette') else None
        self.ppH = float(self.d['px_per_H'])
        self.ground = float(self.d['ground_row'])
        self.panels = self.d['panels']
        self.roi_z = tuple(self.d['roi']['z'])
        self.top_z = float(self.d['roi']['top_z'])
        self.parts = self.d.get('parts', {})
        self.landmarks = self.d.get('landmarks', {})
        self._drawing = None
        self._build_rows()

    def _rel(self, p):
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.dir, p))

    # ------------------------------------------------------------ 윤곽 표 (roi 안, *_core 행)
    def _build_rows(self):
        z0, z1 = self.roi_z
        self.exclude = set(self.d.get('exclude_views', []))
        need = [k for k in VIEWS if k not in self.exclude]
        rows = []
        self.assumed = []
        for r in self.profile_raw['rows']:
            if z0 - 1e-9 <= r['h'] <= z1 + 1e-9 and all(r.get(k + '_core') for k in need):
                rows.append(r)
        if self.d.get('extend_one_view') and len(rows) >= 3:
            rows = self._extend_rows(rows, need, z0, z1)
        if len(rows) < 3:
            raise HarnessError('roi %s 안에 *_core 행이 3개 미만이다' % (self.roi_z,))
        self.z = np.array([r['h'] for r in rows])
        self.prof = {}
        for k in need:
            lo = np.array([r[k + '_core']['min'] for r in rows])
            hi = np.array([r[k + '_core']['max'] for r in rows])
            hw = np.array([r[k + '_core']['half_width'] for r in rows])
            self.prof[k] = {'lo': lo, 'hi': hi, 'hw': hw}
        for k in self.exclude:
            if k in VIEWS and k != 'front':
                self.prof[k] = {a: b.copy() for a, b in self.prof['front'].items()}      # 제외한 뷰는 자리만 채움(판정에서 빠짐)
        # 모델은 좌우 대칭이라 정면과 뒤 도면 반폭의 평균을 폭 목표로 쓴다(둘의 차이는 도면 불일치로 보고)
        # pack.json 의 exclude_views 에 'back' 이 있으면 뒤 도면을 폭 목표와 띠 오차 판정에서 뺀다(도면 정의 불일치 시, 사용자 승인 필요)
        if 'back' in self.exclude:
            self.hw_target = self.prof['front']['hw'].copy()
        else:
            self.hw_target = 0.5 * (self.prof['front']['hw'] + self.prof['back']['hw'])
        self.fb_gap = np.abs(self.prof['front']['hw'] - self.prof['back']['hw'])

    def _extend_rows(self, full, need, z0, z1):
        """한 뷰에만 윤곽이 있는 높이(정면에만 있는 볏, 옆에만 있는 턱 끝)도 행으로 넣는다.
        빠진 뷰의 폭은 가장 가까운 '모든 뷰가 있는 행'의 폭 비율로 채우고(중심은 그 행 중심), self.assumed 에 (높이, 뷰)로 남긴다.
        이유: 고리 케이지가 두 뷰 공통 높이만 만들어 볏(5.3H 위)과 턱 맨 아래(4.55H 아래)가 모델에서 빠졌다(들소 9차).
        가정이므로 그 높이의 띠 오차·3/4 비율은 그 뷰에 대해 의미가 없다(보고에 '가정' 행 수를 쓴다)."""
        import copy as _copy
        hs_full = np.array([r['h'] for r in full])
        out = []
        for r in self.profile_raw['rows']:
            if not (z0 - 1e-9 <= r['h'] <= z1 + 1e-9):
                continue
            have = [k for k in need if r.get(k + '_core')]
            if len(have) == len(need):
                out.append(r)
                continue
            if not have or not any(k in have for k in ('front', 'side')):
                continue
            ref = full[int(np.argmin(np.abs(hs_full - r['h'])))]
            src = 'front' if 'front' in have else 'side'
            ratio = r[src + '_core']['half_width'] / max(ref[src + '_core']['half_width'], 1e-6)
            r2 = _copy.deepcopy(r)
            for k in need:
                if r.get(k + '_core'):
                    continue
                if k == 'back' and r.get('front_core'):
                    c = r['front_core']                               # 뒤는 정면 거울(좌우 대칭)
                    r2['back_core'] = {'min': -c['max'], 'max': -c['min'], 'half_width': c['half_width'], 'center_offset': -c['center_offset']}
                else:
                    c = ref[k + '_core']
                    hw = c['half_width'] * ratio
                    r2[k + '_core'] = {'min': c['center_offset'] - hw, 'max': c['center_offset'] + hw, 'half_width': hw, 'center_offset': c['center_offset']}
                self.assumed.append((round(r['h'], 3), k))
            out.append(r2)
        return out

    def edge(self, view, which, z):
        """높이 z 에서 view 의 윤곽 값(lo|hi|hw|hwt). 행 사이는 선형 보간, 밖은 끝값."""
        if which == 'hwt':
            return np.interp(z, self.z, self.hw_target)
        return np.interp(z, self.z, self.prof[view][which])

    def part_at(self, z, y=None):
        for name, p in self.parts.items():
            if 'z' in p and not (p['z'][0] - 1e-9 <= z <= p['z'][1] + 1e-9):
                continue
            if y is not None and 'y' in p and not (p['y'][0] - 1e-9 <= y <= p['y'][1] + 1e-9):
                continue
            return name
        return '-'

    # ------------------------------------------------------------ 도면 패널 변환 (설계서 3절)
    def px_to_H(self, view, px, py):
        p = self.panels[view]
        return p['sign'] * (np.asarray(px, float) - p['center_x']) / self.ppH, (p['ground_row'] - np.asarray(py, float)) / self.ppH

    def H_to_px(self, view, lat, z):
        p = self.panels[view]
        return p['center_x'] + p['sign'] * np.asarray(lat, float) * self.ppH, p['ground_row'] - np.asarray(z, float) * self.ppH

    def drawing(self):
        if self._drawing is None:
            path = self._rel(self.d['files'].get('drawing') or 'drawing.npy')
            if not os.path.exists(path):
                return None
            self._drawing = np.load(path)
        return self._drawing

    # ------------------------------------------------------------ 랜드마크 (규칙 → 도면 목표)
    def silhouette_points(self, view, source):
        """뷰별 (가로, 높이) 점 집합. source='core' 는 윤곽 행, 아니면 외곽 실루엣 dense 다각형."""
        if source == 'core' or not self.silh:
            P = self.prof[view]
            return np.concatenate([P['lo'], P['hi']]), np.concatenate([self.z, self.z])
        pts = np.array(self.silh['panels'][view]['dense_H'], float)
        return pts[:, 0], pts[:, 1]

    def contour_value(self, view, z, edge, source):
        """높이 z 에서 윤곽 끝(lo|hi) 의 가로 좌표."""
        if source == 'core' or not self.silh:
            return float(self.edge(view, edge, z))
        pts = np.array(self.silh['panels'][view]['dense_H'], float)
        u, v = pts[:, 0], pts[:, 1]
        u2, v2 = np.roll(u, -1), np.roll(v, -1)
        cross = ((v - z) * (v2 - z) <= 0) & (v != v2)
        t = (z - v[cross]) / (v2[cross] - v[cross])
        xs = u[cross] + t * (u2[cross] - u[cross])
        if len(xs) == 0:
            return None
        return float(xs.min() if edge == 'lo' else xs.max())

    def landmark_target(self, name):
        """랜드마크의 도면 목표. {axes:'yz', x/y/z: 값 또는 None, conf, view} (규칙이 안 맞으면 error 키)."""
        L = self.landmarks[name]
        rule = L['rule']
        out = {'name': name, 'rule': rule, 'view': L['view'], 'conf': L.get('conf', '규칙'), 'x': None, 'y': None, 'z': None}
        view = L['view']
        src = L.get('source', 'silhouette')
        if rule == 'extreme':
            u, v = self.silhouette_points(view, src)
            i = pick(L, u, v)
            if i is None:
                return {**out, 'error': '도면에서 규칙에 맞는 점이 없다'}
            lat, z = float(u[i]), float(v[i])
        elif rule == 'contour_at':
            z = float(L['z'])
            lat = self.contour_value(view, z, 'hi' if L['edge'] in ('front', 'out', '+') else 'lo', src)
            if lat is None:
                return {**out, 'error': '높이 %.2f 에서 윤곽이 없다' % z}
        elif rule == 'manual':
            # 정면 픽셀이 주 좌표(X,Z). 옆 픽셀이 있으면 높이 불일치(도면 불일치 경고)와 깊이 Y 참고값만 낸다.
            x, z1 = self.px_to_H('front', *L['front_px'])
            out['x'], out['z'] = float(x), float(z1)
            out['axes'] = 'xz'
            if 'side_px' in L:
                y, z2 = self.px_to_H('side', *L['side_px'])
                out['y_side'] = float(y)
                out['z_gap'] = float(abs(z1 - z2))
            return out
        else:
            return {**out, 'error': '알 수 없는 규칙 ' + str(rule)}
        out['z'] = float(z)
        if view == 'side':
            out['y'] = lat
            out['axes'] = 'yz'
        else:
            out['x'] = lat
            out['axes'] = 'xz'
        return out


# ---------------------------------------------------------------- 팩 만들기
def build_drawing_npy(webp, dst):
    """webp → .npy (blender -b 로 한 번만 읽는다)."""
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, 'blender_readimg.py')
    r = subprocess.run([BLENDER_EXE, '-b', '-P', script, '--', os.path.abspath(webp), os.path.abspath(dst)],
                       capture_output=True, text=True)
    if not os.path.exists(dst):
        raise HarnessError('도면 읽기 실패: ' + (r.stdout + r.stderr)[-400:])


def build_pack(src_dir, out_dir, spec, with_drawing=True):
    """src_dir 의 profile/trace_meta/silhouette(+drawing.webp)로 out_dir/pack.json 을 만든다.
    spec: 부위·랜드마크 규칙·roi (손으로 정하는 것은 규칙뿐, 좌표는 도면에서 계산)."""
    os.makedirs(out_dir, exist_ok=True)
    meta = jload(os.path.join(src_dir, 'trace_meta.json'))
    prof = jload(os.path.join(src_dir, 'profile.json'))
    try:
        rel = os.path.relpath(src_dir, out_dir).replace('\\', '/')
    except ValueError:                                   # 드라이브가 다르면 절대 경로
        rel = os.path.abspath(src_dir).replace('\\', '/')
    panels = {}
    for k in VIEWS:
        p = meta['panels'][k]
        panels[k] = {'center_x': p['중심선_x'], 'ground_row': p['발바닥선_행(눈금)'], 'sign': int(p['x부호(화면x→캐릭터)'])}
    z0, z1 = spec['roi_z']
    valid = [r['h'] for r in prof['rows'] if z0 - 1e-9 <= r['h'] and all(r.get(k + '_core') for k in VIEWS)]
    step = prof['표본']['h_step']
    top_z = round(max(valid) + step, 4)             # 윤곽 표가 끝나는 곳 한 칸 위가 머리 꼭대기
    d = {
        'name': spec['name'], 'version': '0.1',
        'files': {'profile': rel + '/profile.json', 'trace_meta': rel + '/trace_meta.json',
                  'silhouette': rel + '/silhouette.json' if os.path.exists(os.path.join(src_dir, 'silhouette.json')) else None,
                  'drawing_src': rel + '/drawing.webp', 'drawing': 'drawing.npy'},
        'px_per_H': meta['px_per_H'], 'ground_row': meta['ground_row_grid'], 'H_blender': meta['H_blender'],
        'panels': panels,
        'roi': {'z': [z0, min(z1, max(valid))], 'top_z': top_z, 'step': step},
        'parts': spec['parts'], 'landmarks': spec['landmarks'],
    }
    jdump(os.path.join(out_dir, 'pack.json'), d)
    npy = os.path.join(out_dir, 'drawing.npy')
    if with_drawing and not os.path.exists(npy) and os.path.exists(os.path.join(src_dir, 'drawing.webp')):
        build_drawing_npy(os.path.join(src_dir, 'drawing.webp'), npy)
    return os.path.join(out_dir, 'pack.json')


# 들소 머리 팩 규칙. 눈(내부 특징)만 manual 이고 나머지는 모두 실루엣 규칙이다.
BISON_SPEC = {
    'name': 'bison_head',
    'roi_z': [4.25, 5.45],
    'parts': {
        '주둥이': {'z': [4.25, 4.85], 'y': [0.45, 1.2]},
        '두개골': {'z': [4.85, 5.55], 'y': [0.3, 1.0]},
        '목덜미': {'z': [4.25, 5.55], 'y': [-1.0, 0.45]},
    },
    'landmarks': {
        '코끝': {'rule': 'extreme', 'view': 'side', 'dir': '+Y', 'z': [4.4, 4.8], 'source': 'silhouette'},
        '후두': {'rule': 'contour_at', 'view': 'side', 'edge': 'back', 'z': 5.0, 'source': 'core'},
        '턱끝': {'rule': 'extreme', 'view': 'side', 'dir': '-Z', 'y': [0.6, 0.95], 'tie': '+Y', 'source': 'core'},
        '볼폭': {'rule': 'contour_at', 'view': 'front', 'edge': 'out', 'z': 4.6, 'source': 'core'},
        '눈': {'rule': 'manual', 'view': 'front', 'front_px': [294, 202], 'side_px': [653, 212], 'conf': '추정'},
    },
}


def build_bison(root):
    return build_pack(os.path.join(root, 'fixtures', 'bison_head'), os.path.join(root, 'packs', 'bison_head'), BISON_SPEC)
