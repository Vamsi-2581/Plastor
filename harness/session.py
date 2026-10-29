"""세션: 폴더, 버전, 기록, 되돌리기.

sessions/<이름>/
  pack.json(링크)  state.json(현재 버전)  v000.json v001.json ...(케이지 매개변수+오프셋)
  log.jsonl(명령·인자·측정 요약·해시)  report_vNNN.json  show_vNNN_*.png  export/
버전 파일은 매개변수 JSON(메시는 그때그때 생성). undo 는 포인터만 옮기고 기록은 지우지 않는다.
"""
import datetime
import os

from .cage import Cage
from .pack import Pack
from .util import HarnessError, jdump, jload, mesh_sha


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec='seconds')


class Session:
    def __init__(self, path):
        self.dir = os.path.abspath(path)
        if not os.path.exists(os.path.join(self.dir, 'state.json')):
            raise HarnessError('세션 %s 가 없다(init 으로 먼저 만든다)' % path)
        self.state = jload(os.path.join(self.dir, 'state.json'))
        link = jload(os.path.join(self.dir, 'pack.json'))
        target = link['link']
        if not os.path.isabs(target):
            target = os.path.normpath(os.path.join(self.dir, target))
        self.pack = Pack(target)
        gp = os.path.join(self.dir, 'gates.json')
        self.gates = jload(gp) if os.path.exists(gp) else None

    # ------------------------------------------------------------ 만들기
    @staticmethod
    def create(path, pack_path, cage, cmd_record):
        d = os.path.abspath(path)
        if os.path.exists(os.path.join(d, 'state.json')):
            raise HarnessError('세션 %s 가 이미 있다. 새 이름을 쓰거나 폴더를 지워라' % path)
        os.makedirs(d, exist_ok=True)
        os.makedirs(os.path.join(d, 'export'), exist_ok=True)
        link = os.path.relpath(os.path.abspath(pack_path), d).replace('\\', '/')
        jdump(os.path.join(d, 'pack.json'), {'link': link})
        jdump(os.path.join(d, 'state.json'), {'created': _now(), 'versions': [], 'current': None})
        s = Session(d)
        s.commit(cage, cmd_record['cmd'], cmd_record['args'], cmd_record.get('summary', {}), cmd_record.get('wall', 0.0))
        return s

    # ------------------------------------------------------------ 버전
    def current_id(self):
        return self.state['current']

    def load_cage(self, vid=None):
        vid = vid or self.state['current']
        return Cage.from_dict(jload(os.path.join(self.dir, vid + '.json')))

    def _save_state(self):
        jdump(os.path.join(self.dir, 'state.json'), self.state)

    def commit(self, cage, cmd, args, summary, wall):
        n = len(self.state['versions'])
        vid = 'v%03d' % n
        parent = self.state['current']
        jdump(os.path.join(self.dir, vid + '.json'), cage.to_dict())
        V, F, _ = cage.mesh()
        rec = {'id': vid, 'parent': parent, 'hash': cage.hash(), 'mesh_hash': mesh_sha(V, F), 'cmd': cmd}
        self.state['versions'].append(rec)
        self.state['current'] = vid
        self._save_state()
        self.log(cmd, args, summary, wall, version=vid, parent=parent, hash=rec['hash'], mesh_hash=rec['mesh_hash'])
        return vid

    def move(self, vid):
        ids = [v['id'] for v in self.state['versions']]
        if vid not in ids:
            raise HarnessError('버전 %s 가 없다(있는 것: %s)' % (vid, ', '.join(ids)))
        self.state['current'] = vid
        self._save_state()

    def undo(self):
        cur = self.state['current']
        rec = next(v for v in self.state['versions'] if v['id'] == cur)
        if rec['parent'] is None:
            raise HarnessError('더 되돌릴 버전이 없다(%s 이 첫 버전)' % cur)
        self.move(rec['parent'])
        return rec['parent']

    def version_rec(self, vid=None):
        vid = vid or self.state['current']
        return next(v for v in self.state['versions'] if v['id'] == vid)

    # ------------------------------------------------------------ 기록
    def log(self, cmd, args, summary, wall, **extra):
        row = {'ts': _now(), 'cmd': cmd, 'args': args, 'wall_s': round(wall, 3), 'summary': summary}
        row.update(extra)
        with open(os.path.join(self.dir, 'log.jsonl'), 'a', encoding='utf-8') as f:
            import json
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

    def read_log(self):
        import json
        p = os.path.join(self.dir, 'log.jsonl')
        if not os.path.exists(p):
            return []
        return [json.loads(x) for x in open(p, encoding='utf-8') if x.strip()]

    def save_report(self, rep, vid=None):
        vid = vid or self.state['current']
        jdump(os.path.join(self.dir, 'report_%s.json' % vid), rep)
