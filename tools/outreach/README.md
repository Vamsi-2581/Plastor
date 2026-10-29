# 구인글 올리기 CLI

글 파일(`posts/*.md`)을 사이트별로 올린다. **승인은 사람이 한 번, 그 뒤 처리는 자동.**

```powershell
pwsh tools/outreach/post.ps1 list            # 글마다 상태(승인 안 됨·승인됨·승인 풀림·올림)와 검사(PASS·FAIL)
pwsh tools/outreach/post.ps1 approve all     # 글 전체를 읽고 yes 를 쳐서 승인. 키보드로 친 입력만 받는다
pwsh tools/outreach/post.ps1 run             # 승인된 글을 묻지 않고 처리 → 글쓰기 탭을 한꺼번에 열고 → 올라간 주소를 스스로 찾아 기록
pwsh tools/outreach/post.ps1 run -DryRun     # 아무것도 올리지 않고 무엇을 할지만 보기
pwsh tools/outreach/post.ps1 watch           # 올라간 주소 찾기만 다시(최대 30분, -Minutes 로 바꿈)
pwsh tools/outreach/post.ps1 done 02_hn.md https://news.ycombinator.com/item?id=...   # 끝내 못 찾은 글만 손으로 기록
```

## Chrome 에서 사람이 할 일(최소)

처음 한 번: 각 사이트 로그인(계정이 없으면 가입, Google 로그인 되는 곳은 Google 로).
그 뒤 `run` 한 번이면 탭이 한꺼번에 열린다. 탭마다:

| 탭 | 미리 채워지는 것 | 사람이 할 일 |
|---|---|---|
| GitHub 토론 | (탭 없음, 끝까지 자동) | 없음 |
| Hacker News | 제목·주소 | submit 한 번 |
| Reddit(old.reddit.com) | 제목·본문을 주소에 실어 보냄(로그인을 거쳐도 주소에 남는 것은 확인, 화면 칸에 실제로 들어가는지는 UNKNOWN) | 필요하면 flair 고르고 submit 한 번. 칸이 비어 있으면 `posts/03_reddit-localllama.md` 에서 복사 |
| GeekNews | 제목·주소는 미리 채워지는지 UNKNOWN, 본문은 클립보드 | 비어 있으면 제목·주소 넣고 본문 칸에 Ctrl+V, 등록 |

게시를 누르면 끝이다. 올라간 주소는 `run` 이 이어서 공개 검색·피드로 찾아 기록한다(HN 검색 API, Reddit RSS, GeekNews 피드).

HN·Reddit·GeekNews 는 글쓰기 API 가 없거나(HN·GeekNews), 개인 스크립트에 사전 심사를 요구한다(Reddit, 2026-10-30 외부 자료 기준, 공식 확인 안 함). 가입·봇 검사·게시 클릭을 브라우저로 대신하는 자동화는 그 사이트 규칙 위반이라 계정 정지·스팸 처리 위험이 있어 넣지 않았다.

## 지켜지는 것

- **승인은 글 내용에 묶인다**: 머리말과 본문 전체의 SHA-256. 한 글자만 고쳐도 `list` 에 "승인 풀림"이 뜨고 `run` 이 건너뛴다.
- **자동 실행은 승인할 수 없다**: `approve` 는 입력이 넘겨진 실행(스크립트·AI 에이전트)에서 끝 코드 2 로 멈춘다.
- **올리기 전 검사**: HN 제목 80자 이하, Reddit 제목 300자 이하, HN·GeekNews 는 주소 필요. FAIL 이면 승인도 처리도 안 한다.
- **같은 글을 두 번 올리지 않는다**: 처리한 글은 기록에 남고 `run` 이 건너뛴다.
- 승인·기록은 저장소 밖 `~/.modelerharness/outreach/`(`approved.json`, `posted.jsonl`)에 둔다.

## 글 파일 형식

```markdown
---
channel: github-discussion | hn | reddit | geeknews
target: Announcements | Show HN | LocalLLaMA(서브레딧 이름) | Show GN
title: 제목
url: https://github.com/endlessGold/Plastor   (hn·geeknews 필수)
---
본문
```

## 확인한 것과 못 한 것(2026-10-30)

- 시험(임시 폴더의 가짜 승인으로): 승인됨·승인 풀림 구분, 자동 실행의 승인 거부(끝 코드 2), 승인된 글만 미리보기 처리, HN 제목 81자 FAIL 잡음 → 모두 의도대로.
- 실제로 올림: GitHub 토론 #15(사용자 승인 뒤 `run`).
- 올라간 글 찾기(실제 피드로 시험): GeekNews 있는 글 찾음·없는 글 안 찾음 PASS, HN 안 올린 글 안 찾음 PASS. 처음 GeekNews 판은 피드 제목을 `System.Xml.XmlElement` 로 읽어 모든 글과 일치하는 거짓 양성이 있었고 고침.
- Reddit RSS 는 20초 간격이면 요청 제한(429)에 걸리고, 2분 넘게 쉬면 열린다(200, 두 번 확인). 그래서 2분마다만 본다. 피드 한 번으로 시험: 있는 글 찾음·없는 글 안 찾음 PASS. 찾지 못하면 `done` 으로 기록.
- Reddit 글쓰기 주소의 `title`·`text` 채우기가 실제 화면에 들어가는지는 **UNKNOWN**. 안 되면 클립보드의 본문을 붙여 넣는다.
