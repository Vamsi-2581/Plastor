"""공용 도구: 해시, 판정 상수, 끝 코드."""
import hashlib
import json

import numpy as np

PASS, FAIL, UNKNOWN, ERROR = 'PASS', 'FAIL', 'UNKNOWN', 'ERROR'
EXIT = {PASS: 0, FAIL: 1, UNKNOWN: 2, ERROR: 3}


class HarnessError(Exception):
    """값 범위 위반·없는 이름 등 명령 거부 사유. 판정은 ERROR."""


def _norm(o):
    if isinstance(o, dict):
        return {str(k): _norm(v) for k, v in sorted(o.items())}
    if isinstance(o, (list, tuple)):
        return [_norm(v) for v in o]
    if isinstance(o, np.ndarray):
        return _norm(o.tolist())
    if isinstance(o, (np.floating, float)):
        return round(float(o), 9) + 0.0      # -0.0 을 0.0 으로
    if isinstance(o, (np.integer, int)) and not isinstance(o, bool):
        return int(o)
    return o


def sha(o):
    """정규화한 JSON 의 sha256 앞 16자리. 같은 매개변수 → 같은 해시."""
    s = json.dumps(_norm(o), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(s.encode('utf-8')).hexdigest()[:16]


def mesh_sha(V, F):
    q = np.round(np.asarray(V, float), 6) + 0.0
    h = hashlib.sha256()
    h.update(q.astype('<f8').tobytes())
    h.update(np.asarray(F, '<i8').tobytes())
    return h.hexdigest()[:16]


def check_range(name, v, lo, hi):
    if not (lo <= v <= hi):
        raise HarnessError('%s=%g 는 허용 범위 %g~%g 밖이다' % (name, v, lo, hi))
    return v


def jdump(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def jload(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)
