# -*- coding: utf-8 -*-
"""K0 Codex 답 받기: 문항 폴더(정답 없는 사본)에서 codex exec 에 그림을 붙여 묻고 답 JSON 을 저장한다.
  python bench/k0_codex.py <문항 폴더> <A|B> <출력.json>"""
import json
import os
import re
import subprocess
import sys

qdir, order, out = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(os.path.join(qdir, '문항_%s.md' % order), encoding='utf-8').read()
pics = []
for m in re.finditer(r'그림 (\S+\.png)', text):
    if m.group(1) not in pics:
        pics.append(m.group(1))
mapping = '\n'.join('첨부 %d = %s' % (i + 1, p) for i, p in enumerate(pics))
prompt = text + '\n\n첨부 그림 순서(파일 이름):\n' + mapping + '\n\n다른 파일은 열지 말고, 마지막 메시지로 JSON 한 개만 출력하라.'
last = out + '.txt'
cmd = [os.path.expanduser('~/.local/bin/codex.cmd') if os.name == 'nt' else 'codex', 'exec', '-s', 'read-only', '-o', last]
for p in pics:
    cmd += ['-i', os.path.join(qdir, p)]
# 질문은 표준 입력으로: -i 가 파일을 여러 개 받아서 뒤에 붙인 질문 글까지 그림 이름으로 먹었다(첫 실행 답 0개)
r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=qdir)
raw = open(last, encoding='utf-8').read() if os.path.exists(last) else r.stdout
m = re.search(r'\{.*\}', raw, re.S)
ans = json.loads(m.group(0)) if m else {}
json.dump({'가족': 'codex', '순서': order, '답': ans}, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('CODEX', order, '답', len(ans), '끝 코드', r.returncode)
