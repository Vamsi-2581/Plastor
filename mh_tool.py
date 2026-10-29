# -*- coding: utf-8 -*-
r"""하네스 도구 층(harness/api.py)의 명령줄 창구. MCP 등 다른 창구도 같은 도구를 부른다.
  python mh_tool.py list                                  # 도구 목록·받는 값
  python mh_tool.py <도구> '<JSON 인자>'                  # 예: python mh_tool.py card '{"out": "results/bison_head_try15"}'
결과는 JSON 한 덩어리({"판정", "요약", "파일"}). 끝 코드: PASS 0, FAIL 1, UNKNOWN 2, ERROR 3.
"""
import json
import sys

from harness import api

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


def main(argv):
    if not argv or argv[0] == 'list':
        print(json.dumps(api.describe(), ensure_ascii=False, indent=1))
        return 0
    args = json.loads(argv[1]) if len(argv) > 1 else {}
    r = api.call(argv[0], **args)
    print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    return {'PASS': 0, 'FAIL': 1, 'UNKNOWN': 2, 'ERROR': 3}[r['판정']]


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
