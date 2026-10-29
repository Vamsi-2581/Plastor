---
channel: geeknews
target: Show GN
title: Show GN: Plastor – LLM 이 크리처 도면으로 3D 모델을 만들되, "완료"는 시험만 말할 수 있는 하네스
url: https://github.com/endlessGold/Plastor
---
LLM 은 "이 뿔은 휜 관이다" 같은 이름 붙이기는 잘하지만, 정확한 숫자, 여러 뷰를 하나의 입체로 합치기, 자기 결과 검사는 못 합니다. 그래서 일을 나눴습니다. 모델은 부위와 도형 종류만 고르고, Rust 도구가 재고 맞추고 합칩니다(SDF 원형). 통과는 실제로 돈 검사만 낼 수 있고, 모델이 좌표를 쓰면 MCP 서버가 거부합니다.

정직한 현재: 3D 정답이 있는 합성 크리처 12개에서 부피 IoU 0.92(옛 방식 0.59). 실제 손그림에서는 아직 실패합니다. 실루엣만으로는 깊이를 몰라 머리가 납작해집니다. 셀 셰이딩 명암 띠·크로스 컨투어로 깊이를 읽는 것이 지금 풀어야 할 문제입니다.

GTX 750 Ti·i5-3470 에서 돌고 유료 API 가 없습니다. 빠른 시작은 cargo 만 있으면 빌드 뒤 1분 안. MIT. 사람이든 AI 에이전트든 기여자를 찾습니다. 이슈마다 시작 전에 적은 통과 조건이 있습니다.

로드맵(한국어): https://github.com/endlessGold/Plastor/blob/main/ROADMAP.md
