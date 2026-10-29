# ModelerHarness (Codex 등 다른 에이전트용 규칙, CLAUDE.md 와 같은 내용)

LLM 이 숙련 모델러처럼 도면에 충실한 3D 메시를 만들게 하는 무료 로컬 하네스. 설계는 `docs/설계서.md`.
케라투라(`E:\작업물\Projects\Keratoura`) 파일은 고치지 않는다.

## 최우선 규칙
- 사용자에게 보이는 모든 글(보고, 문서, 커밋 메시지, 코드 주석)은 한국어. 코드 식별자·명령어·경로·오류 원문만 원문.
- 판정은 PASS·FAIL·UNKNOWN·ERROR 넷뿐. 통과는 실행한 검증기(자체 시험, 도구 판정, 끝 코드)가 낸 PASS 로만.
- 성공 조건을 실패에 맞춰 고치지 않는다. 수치를 지어내지 않는다. 확인 못 하면 UNKNOWN 과 이유.
- 새 설치·MCP·GPU·학습 모델은 사용자 승인 없이 쓰지 않는다.

## 일하는 방법: 도구로만
- 하네스 일은 도구 층 `mh_tool.py` 로만 한다. 좌표·정점 값을 손으로 쓰지 않는다. 헐·합치기를 임시 코드로 하지 않는다.
- 다음 할 일은 `card` 도구가 주는 카드 한 장만 본다(고정 규칙 → 관련 교훈 → 실패 측정값).
- 그림 모순처럼 LLM 이 정할 일은 `decide` 도구로 근거와 함께 기록한다.

```bash
PY="/c/Program Files/Blender Foundation/Blender 5.2/5.2/python/bin/python.exe"
"$PY" mh_tool.py list                                       # 도구 목록·받는 값
"$PY" mh_tool.py build  '{"spec": "<build.json>"}'          # 파이프라인(단계 판정)
"$PY" mh_tool.py status '{"out": "<결과 폴더>"}'
"$PY" mh_tool.py card   '{"out": "<결과 폴더>"}'            # 지금 막힌 단계 카드
"$PY" mh_tool.py decide '{"out": "<결과 폴더>", "part": "귀", "kind": "그림 모순", "decision": "...", "reason": "..."}'
"$PY" mh_tool.py views  '{"obj": "<OBJ>", "out": "<그림 폴더>"}'
"$PY" mh_tool.py trace  '{"spec": "<트레이싱 사양>"}'
```
결과는 JSON({판정, 요약, 파일}). 끝 코드: PASS 0, FAIL 1, UNKNOWN 2, ERROR 3.

## 고정된 기술 결정
- 실행: Blender 5.2 번들 Python(위 `$PY`) + numpy. 시스템 Python 없음.
- 좌표: H 단위, X 오른쪽 +, Y 앞 +, Z 위(발바닥 0).
- 자체 시험: `"$PY" tests/selftest_api.py`, `tests/selftest_build.py`, `tests/selftest_model.py`, `tests/selftest_trace.py`.
