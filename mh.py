r"""ModelerHarness 명령줄 진입점.
실행: "C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe" mh.py <명령> --session sessions/<이름> ...
(시스템 Python 이 없어서 Blender 번들 Python + numpy 를 쓴다. 자기 폴더를 sys.path 에 넣는다.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

from harness.cli import run  # noqa: E402

if __name__ == '__main__':
    sys.exit(run(sys.argv[1:]))
