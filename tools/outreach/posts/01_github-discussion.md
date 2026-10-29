---
channel: github-discussion
target: Announcements
title: Contributors wanted (humans and AI agents): start here / 함께할 사람을 찾습니다
---
Plastor lets an LLM build 3D creature models from drawings the way a skilled modeler would. The model chooses parts and shape types; Rust tools measure, fit and assemble; and only a check that actually ran can say PASS.

**Where we are:** on 12 held-out synthetic creatures, volume IoU is 0.92 vs 0.59 for the old two-view hull. On a real hand-drawn sheet it still fails: the head comes out flat, because silhouettes alone don't give depth.

**How to start (about a minute after `cargo build`):** follow "Quick start" in the README. Then pick an issue:
- Good first issues: CI on Linux/macOS/Windows (#8), mesh topology check (#10), English docs (#12, #13), traceability backlog (#1)
- Bigger: depth from shading (#2), editable Blender output (#4), game-ready finish (#5), Rust port (#6), LLM A/B test (#7), drawing-error classification (#14)

Every issue has a pass condition written before work starts. AI coding agents are welcome under the same rules (see AGENTS.md); please say which agent did the work.

Roadmap: [English](https://github.com/endlessGold/Plastor/blob/main/ROADMAP.en.md) · [한국어](https://github.com/endlessGold/Plastor/blob/main/ROADMAP.md)

---

LLM 이 숙련 모델러처럼 크리처 도면으로 3D 모델을 만들게 하는 하네스입니다. 처음 하기 좋은 이슈부터 골라 댓글로 "맡겠다"고 남겨 주세요. 질문은 이 토론에 한국어로 남겨도 됩니다.
