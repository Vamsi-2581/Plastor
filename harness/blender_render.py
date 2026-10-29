"""선택: Eevee 4방향 렌더 + 도면 한 장 (blender -b -P). 하네스 쪽: OBJ 를 내보내고 blender 를 부른다."""
import os
import subprocess

from .export import write_obj
from .pack import BLENDER_EXE
from .util import HarnessError, jdump

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sheet(ses, cage, out, obj=None):
    pack = ses.pack
    tmpdir = os.path.dirname(os.path.abspath(out))
    os.makedirs(tmpdir, exist_ok=True)
    if obj is None:
        obj = os.path.join(tmpdir, '_sheet_model.obj')
        V, F, _ = cage.mesh()
        write_obj(obj, V, F, None)
    npy = pack._rel(pack.d['files'].get('drawing') or 'drawing.npy')
    params = {'root': ROOT, 'obj': os.path.abspath(obj), 'out': os.path.abspath(out),
              'drawing': npy if os.path.exists(npy) else None,
              'px_per_H': pack.ppH, 'ground_row': pack.ground, 'panels': pack.panels,
              'zc': 4.95, 'yc': 0.15}
    pj = os.path.join(tmpdir, '_sheet_params.json')
    jdump(pj, params)
    script = os.path.join(ROOT, 'harness', 'blender_sheet.py')
    r = subprocess.run([BLENDER_EXE, '-b', '-P', script, '--', pj], capture_output=True, text=True)
    if not os.path.exists(out):
        raise HarnessError('Eevee 렌더 실패: ' + (r.stdout + r.stderr)[-800:])
    for f in (pj,):
        if os.path.exists(f):
            os.remove(f)
    return out
