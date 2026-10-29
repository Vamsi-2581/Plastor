# -*- coding: utf-8 -*-
r"""한 명령 파이프라인: 트레이스 → 본체 → 부위 → 합치기 → 3D 검사 → 각도 그림 → 다음 카드.
그동안 부위 헐과 합치기는 그때그때 쓴 임시 코드로 했다(같은 결과를 다시 못 만들고, 합치기가 조각 5개로 깨진 것도 몰랐다).
이제 모든 단계가 이 파일의 사양(build.json)으로만 돈다. 단계마다 입력 지문을 적어 두고, 입력이 같으면 다시 돌리지 않는다.

실행(Blender 번들 python):
  python build.py --spec sessions/<이름>/build.json [--from 단계] [--only 단계]
단계: trace, body, parts, merge, check, views, rig, card
build.json:
  out          결과 폴더
  frame        {"pack": 팩 경로} 또는 {"meta": trace_meta.json} (도면 좌표틀)
  trace        {"spec": trace 사양} 또는 {"masks": masks.npz}(이미 만든 트레이스)
  body         {"part": "머리", "obj": 본체 OBJ(mh.py export 결과)} 또는 {"part": "머리", "method": "hull"}
  parts        [{"name": "뿔", "method": "hull", "master": "front", "smooth": 1.5, "embed_px": 8}, ...]  embed_px: 본체 속으로 박는 폭(기본 8, 0 이면 끔)
               method: "hull"(기본) 또는 "round"(둥근 헐: 뿔·꼬리처럼 길쭉한 부위, 실루엣 같고 단면 둥긂)
               cesn: 둥근 헐 표면 제한 이완 횟수(기본 0). 복셀 계단이 줄지만 가는 부위 실루엣이 떨어진다(합성 뿔 1.000→0.95)
  merge        {"ratio": 0.06}
판정: 단계마다 PASS·FAIL·UNKNOWN·ERROR. 합친 메시가 한 덩어리가 아니면 merge FAIL.
"""
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
from harness.export import write_obj  # noqa: E402

BLENDER = os.path.join('C:' + os.sep, 'Program Files', 'Blender Foundation', 'Blender 5.2', 'blender.exe')
STEPS = ['trace', 'body', 'parts', 'merge', 'check', 'views', 'rig', 'card']


class Frame:
    """도면 좌표틀(설계서 3절). 팩 없이 trace_meta 만으로도 만든다(합성 시험)."""

    def __init__(self, ppH, panels):
        self.ppH = float(ppH)
        self.panels = panels                     # {뷰: {center_x, ground_row, sign}}

    @classmethod
    def load(cls, fr, base):
        if fr.get('pack'):
            from harness.pack import Pack
            return Pack(_rel(base, fr['pack']))
        m = json.load(open(_rel(base, fr['meta']), encoding='utf-8'))
        g = float(m.get('ground_row_grid', m.get('발바닥_행', 0)))
        pan = {v: {'center_x': float(p['중심선_x']), 'ground_row': g, 'sign': int(p['x부호(화면x→캐릭터)'])} for v, p in m['panels'].items()}
        return cls(m['px_per_H'], pan)

    def px_to_H(self, view, px, py):
        p = self.panels[view]
        return p['sign'] * (np.asarray(px, float) - p['center_x']) / self.ppH, (p['ground_row'] - np.asarray(py, float)) / self.ppH

    def H_to_px(self, view, lat, z):
        p = self.panels[view]
        return p['center_x'] + p['sign'] * np.asarray(lat, float) * self.ppH, p['ground_row'] - np.asarray(z, float) * self.ppH


def _rel(base, p):
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


def _fp(*items):
    h = hashlib.sha1()
    for it in items:
        if isinstance(it, str) and os.path.isfile(it):
            h.update(open(it, 'rb').read())
        else:
            h.update(json.dumps(it, ensure_ascii=False, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


class Build:
    def __init__(self, spec_path):
        self.sp = os.path.abspath(spec_path)
        self.base = os.path.dirname(self.sp)
        self.S = json.load(open(self.sp, encoding='utf-8'))
        self.out = _rel(self.base, self.S['out'])
        os.makedirs(self.out, exist_ok=True)
        self.logp = os.path.join(self.out, 'build_steps.json')
        self.log = json.load(open(self.logp, encoding='utf-8')) if os.path.exists(self.logp) else {}
        self.frame = Frame.load(self.S['frame'], self.base)

    def p(self, name):
        return os.path.join(self.out, name)

    def masks_path(self):
        return self.S['trace'].get('masks') and _rel(self.base, self.S['trace']['masks']) or self.p('masks.npz')

    def masks(self):
        z = np.load(self.masks_path())
        return {tuple(k.split('|')): z[k] for k in z.files}

    # ---------------------------------------------------------------- 단계
    def step_trace(self):
        if self.S['trace'].get('masks'):
            return 'PASS', {'트레이스': '기존 masks 사용', '파일': self.masks_path()}, [self.masks_path()]
        import trace as T
        ts = _rel(self.base, self.S['trace']['spec'])
        S = json.load(open(ts, encoding='utf-8'))
        T._CACHE.clear()
        res = T.build(S, ts, write=True)
        np.savez_compressed(self.p('masks.npz'), **{'%s|%s' % k: v for k, v in res['masks'].items()})
        return 'PASS', {'부위': sorted({k[1] for k in res['masks']})}, [ts]

    def _hull(self, M, name, cfg, body=None):
        from harness.hull import build_hull
        from harness.vendor import ndi
        f, s = M.get(('front', name)), M.get(('side', name))
        if f is None or s is None:
            return None, {'이유': '정면·옆 트레이스 중 없음'}
        emb = {}
        if body and cfg.get('embed_px', 8):
            # 부위 박기: 2D 로는 본체와 경계선에서만 닿아, 3D 헐은 다듬기로 줄어 2~5px 떠 있었다(들소 14차, 합치기가 조각 5개).
            # 숙련 모델러처럼 부위를 본체 속으로 조금 넣는다. 본체 실루엣 안으로만 넓혀 합친 모양의 윤곽은 그대로다.
            k = int(cfg.get('embed_px', 8))
            out = []
            for v, m in (('front', f), ('side', s)):
                bm = M.get((v, body))
                if bm is None:
                    out.append(m)
                    continue
                ext = ndi.binary_dilation(m, iterations=k) & bm & ~m
                emb[v] = int(ext.sum())
                out.append(m | ext)
            f, s = out
        if cfg.get('method', 'hull') == 'round':
            # 둥근 헐(뿔·꼬리 같은 길쭉한 부위): 실루엣은 헐과 같고 단면은 둥글다. 뿌리 쪽 = 본체 중심
            from harness.model_check import load_obj
            from harness.sweep import build_round_hull
            # 본체 자신을 만들 때는 앞 실행이 남긴 body.obj 를 보지 않는다: 보면 결과가 앞 결과에 따라 매번 달라졌다
            # (M0 새 머리 재현성 FAIL, 같은 입력 세 번에 실루엣_채운_칸 198130/229469/199338, 수정_기록 45). 본체는 원점(발바닥) 쪽에서 쓴다.
            # 부위는 이번 실행의 body 단계가 만든 본체 중심을 뿌리로 쓴다(body 단계가 먼저 돈다).
            root = load_obj(self.p('body.obj'))[0].mean(0) if body and os.path.exists(self.p('body.obj')) else (0, 0, 0)
            V, F, info = build_round_hull(self.frame, f, s, root, voxel=cfg.get('voxel', 0.008), master=cfg.get('master', 'front'), cesn=cfg.get('cesn', 0))
        else:
            V, F, info = build_hull(self.frame, f, s, voxel=cfg.get('voxel', 0.008), smooth=cfg.get('smooth', 1.5), master=cfg.get('master', 'front'),
                                    section_n=cfg.get('section_n'))
        if V is None:
            return None, info
        if emb:
            info['본체로_박은_px'] = emb
        return (V, F), info

    def step_body(self):
        b = self.S['body']
        if b.get('obj'):
            src = _rel(self.base, b['obj'])
            if not os.path.exists(src):
                return 'ERROR', {'이유': '본체 OBJ 없음 ' + src}, []
            import shutil
            shutil.copyfile(src, self.p('body.obj'))
            return 'PASS', {'본체': b['part'], '출처': src}, [src]
        mesh, info = self._hull(self.masks(), b['part'], b)
        if mesh is None:
            return 'FAIL', info, [self.masks_path()]
        write_obj(self.p('body.obj'), *mesh)
        return 'PASS', dict(info, 방법=b.get('method', 'hull')), [self.masks_path()]

    def step_parts(self):
        M = self.masks()
        rep, verdict = {}, 'PASS'
        for cfg in self.S.get('parts', []):
            mesh, info = self._hull(M, cfg['name'], cfg, body=self.S['body']['part'])
            if mesh is None:
                verdict = 'FAIL'
            else:
                write_obj(self.p('part_%s.obj' % cfg['name']), *mesh)
            rep[cfg['name']] = info
        return verdict, rep, [self.masks_path()]

    def step_merge(self):
        from harness.model_check import load_obj, merged_check
        parts = [self.p('part_%s.obj' % c['name']) for c in self.S.get('parts', []) if os.path.exists(self.p('part_%s.obj' % c['name']))]
        cmd = [BLENDER, '-b', '-P', os.path.join(ROOT, 'harness', 'blender_merge.py'), '--', self.p('merged.obj'),
               str(self.S.get('merge', {}).get('ratio', 0.06)), self.p('body.obj')] + parts
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        lines = [ln for ln in r.stdout.splitlines() if ln.startswith('MERGE')]
        if not os.path.exists(self.p('merged.obj')):
            return 'ERROR', {'이유': '합친 OBJ 없음', '출력': lines[-5:] + r.stderr.splitlines()[-5:]}, []
        mc = merged_check(*load_obj(self.p('merged.obj')))
        lost = [ln for ln in lines if ln.startswith('MERGE 실패')]
        if lost:                          # 불리언이 조용히 본체를 지운 경우(수정_기록 44): 몸 수·닫힘만으로는 못 잡는다
            mc['진단'] = mc['진단'] + [{'종류': '합치기 부피 잃음', '내용': lost}]
        v = 'PASS' if not mc['진단'] else 'FAIL'
        return v, {'합치기': lines, '검사': mc}, [self.p('body.obj')] + parts

    def step_check(self):
        from harness.model_check import check, load_obj, merged_check
        body = self.S['body']['part']
        parts = {body: load_obj(self.p('body.obj'))}
        for c in self.S.get('parts', []):
            f = self.p('part_%s.obj' % c['name'])
            if os.path.exists(f):
                parts[c['name']] = load_obj(f)
        R = check(self.frame, parts, self.masks())
        R['본체'] = body
        if os.path.exists(self.p('merged.obj')):
            mc = merged_check(*load_obj(self.p('merged.obj')))
            R['합친_메시'] = mc
            R['부위']['(합친 메시)'] = {'뷰': {}, '진단': mc['진단']}
        json.dump(R, open(self.p('model_check.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        n = sum(len(r['진단']) for r in R['부위'].values())
        with open(self.p('check_history.jsonl'), 'a', encoding='utf-8') as f:      # 막힘 감지용 기록(조사 단계)
            f.write(json.dumps({'시각': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                '진단': [[p, d['종류']] for p, r in R['부위'].items() for d in r['진단']]}, ensure_ascii=False) + '\n')
        summ = {p: {'IoU': {v: d['IoU'] for v, d in r['뷰'].items()}, '진단': [d['종류'] for d in r['진단']]} for p, r in R['부위'].items()}
        return ('PASS' if n == 0 else 'FAIL'), summ, [self.p('body.obj'), self.masks_path()] + [self.p('merged.obj')] * os.path.exists(self.p('merged.obj'))

    def step_views(self):
        from harness.blender_view import views_bg
        src = self.p('merged.obj') if os.path.exists(self.p('merged.obj')) else self.p('body.obj')
        files = views_bg(src, self.p('views'))
        # 그림은 판정이 아니다(사람·LLM 이 본다). 그래서 UNKNOWN.
        return 'UNKNOWN', {'그림': files}, [src]

    def step_rig(self):
        """단계 5 리깅 준비: 합친 메시에 rig_check.py 를 헤드리스로 돌린다. 메시가 없으면 UNKNOWN."""
        src, outp = self.p('merged.obj'), self.p('rig_check.json')
        if not os.path.exists(src):
            return 'UNKNOWN', {'이유': 'merged.obj 없음'}, []
        if os.path.exists(outp):
            os.remove(outp)
        cmd = [BLENDER, '-b', '-P', os.path.join(ROOT, 'harness', 'rig_check.py'), '--', src, outp]
        # 부위 뼈(--parts) 기본 켬. 처음엔 뼈를 더하자 자동 가중치(Bone Heat)가 통째로 실패했으나(0.017→1.0), 알려진 원인 손보기
        # (rig_check: 겹친 정점 합치기 + 10배 키우기) 뒤 들소 가중치 0 비율 0.0. 끄려면 사양 "rig": {"part_bones": false}
        part_objs = sorted(glob.glob(self.p('part_*.obj')))
        if part_objs and self.S.get('rig', {}).get('part_bones', True):
            cmd += ['--parts'] + part_objs
        r = subprocess.run(cmd,
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
        if not os.path.exists(outp):
            return 'ERROR', {'이유': 'rig_check.json 이 안 생김', '끝코드': r.returncode, '꼬리': r.stdout[-300:]}, [src]
        R = json.load(open(outp, encoding='utf-8'))
        info = {k: R.get(k) for k in ('덩어리', '열린변', '비대칭도', '가중치0_비율', '이유')}
        return R['판정'], info, [src, os.path.join(ROOT, 'harness', 'rig_check.py')]

    def step_card(self):
        import model_loop as ML
        R = json.load(open(self.p('model_check.json'), encoding='utf-8'))
        dp = self.p('model_decisions.json')
        verdict, text = ML.card(R, R.get('본체'), json.load(open(dp, encoding='utf-8')) if os.path.exists(dp) else [],
                                history=ML.read_history(self.p('')), rig=ML.read_rig(self.p('')))
        open(self.p('card.md'), 'w', encoding='utf-8').write(text)
        return verdict, {'카드': self.p('card.md')}, [self.p('model_check.json')] + [dp] * os.path.exists(dp) + [self.p('rig_check.json')] * os.path.exists(self.p('rig_check.json'))

    # ---------------------------------------------------------------- 실행
    def run(self, start=None, only=None):
        todo = [only] if only else STEPS[STEPS.index(start):] if start else STEPS
        cfg_fp = {k: v for k, v in self.S.items() if k != 'out'}
        for st in STEPS:
            if st not in todo:
                continue
            t0 = time.time()
            prev = self.log.get(st)
            try:
                v, info, inputs = getattr(self, 'step_' + st)()
            except Exception as e:  # 단계 실패는 ERROR 로 남기고 멈춘다
                import traceback
                v, info, inputs = 'ERROR', {'예외': repr(e), '자리': traceback.format_exc().splitlines()[-3:]}, []
            fp = _fp(cfg_fp, *inputs)
            self.log[st] = {'판정': v, '정보': info, '입력지문': fp, '초': round(time.time() - t0, 1),
                            '이전과_같은_입력': bool(prev and prev.get('입력지문') == fp)}
            json.dump(self.log, open(self.logp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
            print('BUILD %-6s %-7s %5.1f초 %s' % (st, v, time.time() - t0, json.dumps(info, ensure_ascii=False, default=str)[:300]))
            if v == 'ERROR':
                return 3
        vs = [self.log[s]['판정'] for s in STEPS if s in self.log]
        return 0 if all(x == 'PASS' for x in vs) else (3 if 'ERROR' in vs else 1 if 'FAIL' in vs else 2)


def main(argv):
    sp = argv[argv.index('--spec') + 1]
    start = argv[argv.index('--from') + 1] if '--from' in argv else None
    only = argv[argv.index('--only') + 1] if '--only' in argv else None
    return Build(sp).run(start, only)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
