r"""자체 시험(설계서 12절 1번). 끝 코드 0 = PASS.
합성 타원체 팩에서: init → G1·G4 PASS, 같은 명령열 3회 해시 일치, undo 후 해시가 이전 버전과 일치,
snap 뒤 랜드마크 오차 ≤ 0.01H. 그 밖에 범위 거부(ERROR), OBJ 왕복 측정, 들소 머리 회귀(init → G1 PASS).
실행: "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" tests/selftest.py
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from harness import pack as packmod  # noqa: E402
from harness.cli import run  # noqa: E402
from harness.export import read_obj, write_obj  # noqa: E402
from harness.measure import evaluate_gates, measure_mesh  # noqa: E402
from harness.session import Session  # noqa: E402

RESULTS = []


def check(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print('%s %s %s' % ('PASS' if ok else 'FAIL', name, detail))


def mh(*argv):
    """명령을 같은 프로세스에서 실행하고 (끝 코드, 출력)을 돌려준다."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = run(list(argv))
    return code, buf.getvalue()


# ---------------------------------------------------------------- 합성 타원체 팩
def make_synthetic_pack(d, cz=5.02, ax=0.6, ay=0.8, az=0.9):
    """중심 (0, 0.3, cz), 반축 (ax, ay, az) 타원체. 윤곽 행과 실루엣을 해석적으로 만든다. 눈은 manual."""
    src = os.path.join(d, 'src')
    os.makedirs(src, exist_ok=True)
    rows = []
    for k in range(0, 121):
        h = round(4.0 + 0.05 * k, 4)
        dz = h - cz
        if abs(dz) >= 0.86:
            rows.append({'h': h, 'front_core': None, 'side_core': None, 'back_core': None})
            continue
        s = float(np.sqrt(1 - (dz / az) ** 2))
        row = {'h': h}
        for v in ('front', 'back'):
            row[v + '_core'] = {'min': -ax * s, 'max': ax * s, 'half_width': ax * s, 'center_offset': 0.0}
        row['side_core'] = {'min': 0.3 - ay * s, 'max': 0.3 + ay * s, 'half_width': ay * s, 'center_offset': 0.3}
        rows.append(row)
    json.dump({'표본': {'h_step': 0.05}, 'rows': rows}, open(os.path.join(src, 'profile.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    panel = {'중심선_x': 400.0, '발바닥선_행(눈금)': 900.0, 'x부호(화면x→캐릭터)': 1}
    meta = {'px_per_H': 150.0, 'ground_row_grid': 900.0, 'H_blender': 0.598,
            'panels': {'front': dict(panel), 'side': {**panel, 'x부호(화면x→캐릭터)': -1}, 'back': {**panel, 'x부호(화면x→캐릭터)': 1}}}
    json.dump(meta, open(os.path.join(src, 'trace_meta.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    th = np.linspace(0, 2 * np.pi, 3600, endpoint=False)
    sil = {'panels': {
        'side': {'dense_H': np.stack([0.3 + ay * np.cos(th), cz + az * np.sin(th)], 1).tolist()},
        'front': {'dense_H': np.stack([ax * np.cos(th), cz + az * np.sin(th)], 1).tolist()},
        'back': {'dense_H': np.stack([ax * np.cos(th), cz + az * np.sin(th)], 1).tolist()}}}
    json.dump(sil, open(os.path.join(src, 'silhouette.json'), 'w', encoding='utf-8'))
    eye_x, eye_z = 0.3, cz + 0.28
    spec = {'name': 'synthetic_ellipsoid', 'roi_z': [4.3, 5.7],
            'parts': {'아래': {'z': [4.0, 5.0]}, '위': {'z': [5.0, 6.0]}},
            'landmarks': {
                '코끝': {'rule': 'extreme', 'view': 'side', 'dir': '+Y', 'z': [4.6, 5.4], 'source': 'silhouette'},
                '후두': {'rule': 'contour_at', 'view': 'side', 'edge': 'back', 'z': 5.0, 'source': 'core'},
                '볼폭': {'rule': 'contour_at', 'view': 'front', 'edge': 'out', 'z': 5.1, 'source': 'core'},
                '눈': {'rule': 'manual', 'view': 'front', 'front_px': [400.0 + eye_x * 150.0, 900.0 - eye_z * 150.0], 'conf': '추정'}}}
    return packmod.build_pack(src, os.path.join(d, 'pack'), spec, with_drawing=False)


def main():
    tmp = tempfile.mkdtemp(prefix='mh_selftest_')
    try:
        pk = make_synthetic_pack(tmp)
        P = packmod.Pack(pk)
        check('합성 팩 만들기', len(P.z) >= 20, '윤곽 행 %d개 z%.2f~%.2f 꼭대기 %.2f' % (len(P.z), P.z[0], P.z[-1], P.top_z))

        # 1) init → G1·G4 PASS
        S = os.path.join(tmp, 's_main')
        code, out = mh('init', '--pack', pk, '--session', S)
        check('init 실행', code == 0, '끝 코드 %d' % code)
        code1, o1 = mh('gate', 'G1', '--session', S)
        code4, o4 = mh('gate', 'G4', '--session', S)
        check('init 직후 G1 PASS', code1 == 0, o1.strip().splitlines()[0])
        check('init 직후 G4 PASS', code4 == 0, o4.strip().splitlines()[0])

        # 2) 같은 명령열 3회 → 해시 일치
        seq = [('fit', '--view', 'side'), ('round', '--z', '4.6', '5.4', '--n', '3'),
               ('narrow', '--z', '4.8', '5.2', '--width', '0.8'), ('shift', '--z', '4.8', '5.2', '--dy', '0.05'),
               ('snap', '코끝'), ('add_ring', '--z', '5.025'), ('smooth', '--z', '4.5', '5.5', '--k', '0.3')]
        hashes = []
        for r in range(3):
            Sr = os.path.join(tmp, 's_rep%d' % r)
            mh('init', '--pack', pk, '--session', Sr)
            for c in seq:
                code, out = mh(*c, '--session', Sr)
                if code != 0:
                    check('명령열 실행(%s)' % ' '.join(c), False, out.strip().splitlines()[0])
            ss = Session(Sr)
            rec = ss.version_rec()
            hashes.append((rec['hash'], rec['mesh_hash']))
        check('같은 명령열 3회 해시 일치', len(set(hashes)) == 1, '매개변수·메시 해시 %s' % (hashes[0],))

        # 3) undo 후 해시가 이전 버전과 일치
        ss = Session(Sr)
        prev = ss.version_rec()['parent']
        prev_hash = ss.version_rec(prev)['hash']
        mh('undo', '--session', Sr)
        ss = Session(Sr)
        now_hash = ss.load_cage().hash()
        check('undo 후 해시 = 이전 버전 해시', now_hash == prev_hash and ss.current_id() == prev, '%s == %s (%s)' % (now_hash, prev_hash, prev))
        mh('goto', 'v%03d' % (len(ss.state['versions']) - 1), '--session', Sr)

        # 4) snap → 랜드마크 오차 ≤ 0.01H (일부러 어긋나게 한 뒤)
        Sk = os.path.join(tmp, 's_snap')
        mh('init', '--pack', pk, '--session', Sk)
        mh('shift', '--z', '4.7', '5.3', '--dy', '0.06', '--session', Sk)
        ss = Session(Sk)
        c = ss.load_cage()
        V, F, _ = c.mesh()
        before = {x['name']: x['dist'] for x in measure_mesh(V, F, ss.pack, c)['landmarks']}
        for name in ('코끝', '후두', '볼폭', '눈'):
            mh('snap', name, '--session', Sk)
        ss = Session(Sk)
        c = ss.load_cage()
        V, F, _ = c.mesh()
        rep = measure_mesh(V, F, ss.pack, c)
        after = {x['name']: x['dist'] for x in rep['landmarks']}
        check('snap 뒤 랜드마크 오차 ≤ 0.01H', all(v <= 0.01 for v in after.values()),
              '전 %s → 후 %s' % ({k: round(v, 3) for k, v in before.items()}, {k: round(v, 4) for k, v in after.items()}))
        check('snap 은 좌우 대칭과 닫힘을 지킨다', rep['mesh']['sym_err'] < 1e-9 and rep['mesh']['closed'], '대칭오차 %.1e 닫힘 %s' % (rep['mesh']['sym_err'], rep['mesh']['closed']))

        # 5) 범위 거부(ERROR = 끝 코드 3), 이름 오류
        bad = [('round', '--z', '4.6', '5.4', '--n', '9'), ('fit', '--view', 'side', '--strength', '2'),
               ('snap', '없는이름'), ('narrow', '--z', '4.6', '5.4', '--width', '2'), ('snap', '코끝', '--falloff', '0.9')]
        codes = [mh(*b, '--session', S)[0] for b in bad]
        check('범위 밖·없는 이름은 ERROR(끝 코드 3)로 거부', all(cc == 3 for cc in codes), '끝 코드 %s' % codes)

        # 6) OBJ 왕복: 내보낸 메시를 읽어 같은 측정표로 재면 같은 결과
        ss = Session(S)
        c = ss.load_cage()
        V, F, _ = c.mesh()
        rep_a = measure_mesh(V, F, ss.pack, c)
        obj = os.path.join(tmp, 'x.obj')
        mh('export', '--obj', obj, '--session', S)
        V2, F2 = read_obj(obj)
        rep_b = measure_mesh(V2, F2, ss.pack)
        d_iou = max(abs(rep_a['iou'][k] - rep_b['iou'][k]) for k in rep_a['iou'])
        check('OBJ 왕복 측정 일치', d_iou < 1e-5 and len(V2) == len(V), 'IoU 차이 %.1e 정점 %d' % (d_iou, len(V2)))
        objk = os.path.join(tmp, 'k.obj')
        mh('export', '--obj', objk, '--project', 'keratoura', '--session', S)
        Vk, Fk = read_obj(objk)
        check('케라투라 단위 내보내기(×0.598, y-up)', abs(Vk[:, 1].max() - V[:, 2].max() * 0.598) < 1e-5 and abs(Vk[:, 2].max() - V[:, 1].max() * 0.598) < 1e-5, '높이 %.4f' % Vk[:, 1].max())

        # 7) 들소 머리 회귀(도면 없이): init → G1 PASS, 코끝 ≤ 0.05
        bp = os.path.join(tmp, 'bison_pack')
        pk2 = packmod.build_pack(os.path.join(ROOT, 'fixtures', 'bison_head'), bp, packmod.BISON_SPEC, with_drawing=False)
        Sb = os.path.join(tmp, 's_bison')
        mh('init', '--pack', pk2, '--session', Sb)
        cg, og = mh('gate', 'G1', '--session', Sb)
        ss = Session(Sb)
        c = ss.load_cage()
        V, F, _ = c.mesh()
        rep = measure_mesh(V, F, ss.pack, c)
        nose = next(x['dist'] for x in rep['landmarks'] if x['name'] == '코끝')
        check('들소 머리 회귀: init 직후 G1 PASS·코끝 ≤ 0.05', cg == 0 and nose <= 0.05, '코끝 %.3f' % nose)

        # 8) G0 목표 검증: 도면 경계에 맞춘 목표는 PASS, 20px 어긋난 목표는 PASS 가 아니다. 도면이 없으면 UNKNOWN
        from harness.target_check import target_check
        img = np.full((400, 600, 3), 235, np.uint8)
        yy, xx = np.mgrid[:400, :600]
        img[((xx - 300) / 100.0) ** 2 + ((yy - 200) / 150.0) ** 2 <= 1] = (90, 60, 50)       # 어두운 타원 하나(경계 선명)
        class FakePack:
            exclude = set()
            def __init__(self, shift):
                self.z = np.linspace(-1.0, 1.0, 15)[1:-1] * 0.8
                self.prof = {'front': {'lo': -np.sqrt(1 - (self.z / 1.5 * 1.0) ** 2 * 0 - (self.z / 0.75) ** 2) * 1.0 + shift,
                                       'hi': np.sqrt(1 - (self.z / 0.75) ** 2) * 1.0 + shift}}
            def drawing(self):
                return img
            def H_to_px(self, view, lat, z):
                return 300 + 100.0 * np.asarray(lat), 200 - 150.0 * np.asarray(z) / 0.75
        good = target_check(FakePack(0.0), ('front',))
        off = target_check(FakePack(0.2), ('front',))
        check('G0: 도면 경계에 맞춘 목표 PASS, 어긋난 목표 PASS 아님', good['verdict'] == 'PASS' and off['verdict'] != 'PASS', '맞춤 %.2f 어긋남 %.2f' % (good['ratio'], off['ratio']))
        class NoImg(FakePack):
            def drawing(self):
                return None
        check('G0: 도면 이미지가 없으면 UNKNOWN', target_check(NoImg(0.0), ('front',))['verdict'] == 'UNKNOWN')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [r for r in RESULTS if not r[1]]
    print('\n자체 시험 %s: %d개 중 %d개 통과' % ('PASS' if not bad else 'FAIL', len(RESULTS), len(RESULTS) - len(bad)))
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
