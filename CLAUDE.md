# ModelerHarness

LLM이 숙련 모델러처럼 도면에 충실한 3D 메시를 만들게 하는 무료 로컬 하네스. 설계는 `docs/설계서.md`, 배경 조사는 `docs/조사_보고서.md`.
첫 사용처는 케라투라(`E:\작업물\Projects\Keratoura`)의 크리처 유닛이지만, 이 저장소는 케라투라와 독립이다(케라투라 파일을 고치지 않는다).

## 최우선 규칙

- 모든 산출물(보고, 문서, 커밋 메시지, 코드 주석)은 한국어. 코드 식별자·명령어·경로·오류 원문만 원문.
- 판정은 PASS·FAIL·UNKNOWN·ERROR 넷뿐. 통과는 실행한 검증기(selftest, 관문, 끝 코드)가 낸 PASS로만.
- 성공 조건(설계서 12절)을 실패에 맞춰 고치지 않는다. 바꾸려면 사용자 승인.
- 수치·성능을 지어내지 않는다. 확인 못 하면 UNKNOWN과 이유.

## 고정된 기술 결정

- 실행: Blender 5.2 번들 Python `"C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe"` + numpy. 시스템 Python 없음. PIL·scipy·cv2 없음.
- 이미지 읽기·Eevee 렌더만 `"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" -b -P ...`.
- 새 설치·MCP·GPU·학습 모델: **오픈소스 모델·도구 내려받기와 설치는 묻지 않고 진행**(사용자 2026-10-30 "왜 나한테 승인받음?", 루프 중 묻지 말 것). 단 GitHub 공개 게시는 올리기 직전에 공개 범위만 확인. 승인된 것: Rust(사용자 "파이썬이 없으면 안 되는 부분 제외 전부 러스트": 제어·도구 층·MCP 까지, 파이썬은 bpy·학습 모델 일꾼만. 크레이트 serde_json·zip, 옮김 지도는 `docs/설계_러스트.md` 7장), .vendor(vtracer·scipy·scikit-image·opencv·trimesh), MCP for Blender(`uvx mcp-for-blender`, 로컬 범위 `blender-local` 로 등록, 원격 전송 끔, 보기·재기용. Blender 창이 떠 있어야 동작).
- 좌표: H 단위, X 오른쪽 +, Y 앞 +, Z 위(발바닥 0). 설계서 3절.

## 명령

본체는 `build.py` 의 둥근 헐 + 제한 이완(들소 16차) 또는 `mh.py`(고리 케이지, 관문 G1~G4)로 만들고, 나머지는 한 명령 `build.py`(trace → body → parts → merge → check → views → rig → card)로 돈다. 임시 코드로 헐·합치기를 하지 않는다. 다듬기는 `bridge.py` → `fitloop.py`. 스킬은 두 개: `.claude/skills/modeler/SKILL.md`(만들기·재기), `.claude/skills/modeler-loop/SKILL.md`(스스로 판단하는 실험 루프).

```bash
PY="/c/Program Files/Blender Foundation/Blender 5.2/5.2/python/bin/python.exe"
B="/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"
# 자체 시험(끝 코드 0 = PASS)
"$PY" tests/selftest_ringcage.py          # 1단계 12개
"$PY" tests/selftest.py                   # 2단계 15개(Blender 호출, 약 50초)
"$PY" tests/selftest_trace.py             # 트레이싱 18개
"$PY" tests/selftest_model.py             # 3D 모델 검사·단계 카드 10개
"$PY" tests/selftest_build.py             # 파이프라인 처음부터 끝까지 7개(약 40초)
"$PY" tests/selftest_rig.py               # 단계 5 리깅 준비 검사기 5개
"$PY" tests/selftest_rust.py              # Rust 도구 대조 12개(먼저 cd rust && cargo build --release)
# 과제 묶음·장부와 실험 루프
"$PY" bench/m0.py harness | table          # M0 과제(합성 6·실제 2), 장부 bench/m0/ledger.jsonl
"$PY" bench/auto_loop.py --hours 4         # 계획 bench/loop/plan.json, 멈추면 bench/loop/판단_필요.md
# 도구 층: LLM 이 쓰는 일은 이 도구들로(받는 값에 좌표 없음, 결과는 {판정, 요약, 파일})
"$PY" mh_tool.py list
"$PY" mh_tool.py card '{"out": "results/bison_head_try15"}'
"$PY" tests/selftest_api.py               # 도구 층 9개
# 한 명령 파이프라인(단계마다 판정·입력 지문은 <out>/build_steps.json, 카드는 <out>/card.md)
"$PY" build.py --spec sessions/<이름>/build.json [--from 단계] [--only 단계]
# 루프: 모델을 뷰에 재투영해 재고, 막힌 단계 카드 한 장만 따른다
"$PY" model_loop.py check --pack <팩> --masks <masks.npz> --part 머리=<OBJ> ... --body 머리 --out <폴더>
"$PY" model_loop.py next --check <폴더>/model_check.json
"$PY" -m harness.blender_view <OBJ> <폴더>    # 3/4·위·아래 그림(헤드리스). --mcp 는 창을 띄운 MCP 판
# 1단계: 만들기
"$PY" mh.py <명령> --session sessions/<이름> ...      # init 은 --pack packs/<이름>/pack.json
# 연결과 2단계: 다듬기
"$PY" bridge.py --pack packs/head_only/pack.json --obj <OBJ> --masks fixtures/bison_head/target_head --out sessions/<이름>
"$B" -b -P fitloop.py -- attach sessions/<이름>/spec.json
"$B" -b -P fitloop.py -- run sessions/<이름>/spec.json
```

검증 상태: 자체 시험 7종 PASS. 들소 머리 16차(`results/bison_head_try16_round_cesn`)는 카드 단계 1~5 PASS(머리 그림 모순 1건은 정면 따름으로 결정). 머리 전체 모양이 아직 각지고, 가는 부위 표면 계단은 실루엣을 지키며 줄이는 방법을 못 찾았다(수정_기록 보류 항목).

## 비용

- 긴 출력은 `grep`/`tail`로 걸러 본다. 그림은 관문 통과 때와 사람에게 넘길 때만 본다.
- 하위 에이전트는 Sonnet, 동시에 최대 2개. 작은 일은 직접 한다.
