---
name: modeler
description: 도면(정면·옆·뒤)으로 크리처 3D 메시를 만들고 다듬고 잴 때 쓴다. 좌표를 눈대중으로 적지 않고 하네스 도구만 쓴다. build.py 파이프라인(트레이스 → 본체 → 부위 → 합치기 → 검사 → 각도 그림 → 리깅 → 카드), M0 과제 묶음 채점, Rust 도구(mh), 단계 카드. "도면대로 메시", "크리처 머리 모델링", "부피·실루엣 재기", "M0", "기준선", "하네스로 만들어" 같은 요청에 쓴다.
---

# modeler: 숙련 모델러처럼, 도면에 충실하게

## 늘 지키는 것
- **좌표를 쓰지 않는다.** 이름(부위·뷰), 종류(공·휜 관·판), 상대값만 준다. 숫자는 도구가 잰다.
- 판정은 PASS·FAIL·UNKNOWN·ERROR 넷. 통과는 실행한 검증기(자체 시험·관문·채점기 끝 코드)의 PASS 뿐.
- 기준은 돌리기 전에 적는다(`docs/계획_숙련모델러.md`, `bench/loop/plan.json`). 실패에 맞춰 바꾸지 않는다.
- 샘플(들소)을 고치는 게 아니라 하네스를 고친다: 일반 규칙 + 회귀 시험 + 합성 과제로 확인.
- 다음 할 일은 **카드 한 장만** 본다(`mh_tool.py card`). 이 문서 전체를 매번 다시 읽지 않는다.

## LLM 이 약한 곳은 도구로(docs/조사_LLM한계.md)
- **세지 말고 `digest` 를 읽는다**: 조각 수·넓이·H 범위·좌우 대칭은 도구 숫자. 그림에서 세기·크기 눈대중 금지(세기는 최신 모델도 약함).
- **작은 부위는 `zoom`**: 전체 그림은 긴 변 1568px 로 줄어 들어온다. 부위 이름으로 확대 그림을 받아 본다(조각 색 = digest 조각 순서).
- **시점 합치기는 도구가**: 정면·옆을 머릿속에서 3D 로 합쳐 판단하지 않는다(헐·맞추기·digest 의 H 범위).
- **판단은 `judge` 로 모은다**: 순서 바꿔 두 번 이상·두 가족, 재현율·순서 뒤집힘·카파 미달이면 UNKNOWN. 같은 답이 반복된다고 옳은 것은 아니다.
- **스스로 '됐다'고 하지 않는다**: 통과는 검증기 PASS 만. 그림은 숫자로 교차 확인(와이어프레임 가짜 선·겹친 구 부피 합 오류를 그렇게 잡았다).

## 공정 순서(숙련자 방식, 앞 관문 FAIL 이면 뒤로 안 감)
읽기(설계도: 부위 이름·종류·짝·붙는 곳) → 블록아웃(큰 덩어리·비율) → 1차 형태(실루엣) → 2차(부위) → 합치기 → 리깅 준비.
부위마다 연산자를 고른다: 머리 = 공/헐, 뿔·꼬리 = 휜 관(둥근 헐), 귀 = 판, 갈기 = 덩어리. 도면 > 아트 판단(아트 판단은 도면이 말하지 않는 뒤·안쪽·단면에만).

## 도구
```bash
PY="/c/Program Files/Blender Foundation/Blender 5.2/5.2/python/bin/python.exe"
"$PY" mh_tool.py list                                  # 도구 층(받는 값에 좌표 없음, 결과 {판정, 요약, 파일}): digest·zoom·judge 포함
"$PY" build.py --spec <build.json> [--from 단계] [--only 단계]   # 한 명령 파이프라인, 단계 판정은 <out>/build_steps.json
"$PY" bench/m0.py harness [과제...]                    # M0 과제(합성 6·실제 2)를 지금 하네스로 → 장부 bench/m0/ledger.jsonl
"$PY" bench/m0.py score <과제> <OBJ> <기준선이름>        # 실루엣 IoU·부피 IoU(합성)·몸 수·지문
"$PY" bench/m0.py table                                # 장부 요약
rust/target/release/mh.exe list                        # Rust 도구(hull, voxsil). 빌드: cd rust && cargo build --release
```
- 복셀화는 Rust 가 있으면 자동으로 Rust(칸 단위로 같음, 80~170배 빠름). 끄려면 `MH_RUST=0`.
- Blender 안의 일(합치기·각도 그림·리깅·fitloop)은 `blender -b -P <스크립트>` 파이썬. Rust 로 옮기지 않는다(bpy 만 됨).
- 고리 케이지(`mh.py`)·fitloop 의 자세한 규칙: [참고_고리케이지_fitloop.md](참고_고리케이지_fitloop.md).

## 이미 밟은 함정(다시 밟지 않기)
- 합친 메시는 몸 수·닫힘만으로 믿지 않는다. **합집합이 본체를 오류 없이 지울 수 있다** → 부피를 잰다(`MERGE 부피`·`MERGE 실패` 줄, 수정_기록 44).
- 단계는 출력 폴더의 **이전 결과를 입력으로 읽지 않는다**(숨은 입력 → 재현성 FAIL, 수정_기록 45). 재현성은 같은 과제를 두 번 돌려 지문으로.
- 두 뷰 헐은 **다른 부위에 가려진 곳을 비었다고 본다** → 머리 부피가 정답의 57~70%, 뿔 11~15%(M0 진단). 실루엣이 좋아도 부피를 따로 잰다.
- 채점기도 틀린다: 겹친 조각은 조각별로 복셀화, 복셀은 도면 1.5px 이하(새 머리 0.62 → 0.98 은 채점기 문제였음).
- 크기 문턱 하나로 부위 방식을 고르지 않는다(작은 부위 SAM FAIL, 수정_기록 43). SAM 은 사양 `method_by_part` 에 부위마다.
- Rust 로 옮길 때는 파이썬판이 기준: `tests/selftest_rust.py` 로 대조. JSON 실수는 `float_roundtrip` 로 정확히 읽는다.

## 자체 시험(끝 코드 0 = PASS)
`tests/selftest_trace.py`(18) · `selftest_model.py`(13) · `selftest_build.py`(9) · `selftest_rig.py`(5) · `selftest_api.py`(9) · `selftest_rust.py`(12) · `selftest_metrics.py`(5) · `selftest_aids.py`(5) · `selftest_ringcage.py`(12) · `selftest.py`(15)

## 보고(사람에게, 한국어)
판정표, 숫자는 실행 결과 그대로, 확인 못 한 것은 UNKNOWN 과 이유, 기록은 `docs/수정_기록.md`·`docs/교훈.jsonl`.
