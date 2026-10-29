# ModelerHarness

**A free, local harness that lets an LLM (such as Claude Code) work like a skilled 3D modeler — turning creature model sheets (front, side, back) into 3D meshes that stay faithful to the drawings.**
No paid 3D-generation services and no big GPU: it is developed on a GTX 750 Ti (2 GB), an i5-3470 and 16 GB of RAM, and runs on Blender + Rust + a little Python.

[한국어는 아래에 있습니다 ↓](#한국어)

**Want to help?** We are looking for collaborators: graphics and geometry developers, Blender technical artists, Rust developers, artists with openly licensed creature sheets, and LLM evaluators. See [CONTRIBUTING.md](CONTRIBUTING.md).

**Roadmap:** stages K0–K9, milestones with success criteria fixed before each run, risks and where to help are in [ROADMAP.en.md](ROADMAP.en.md) (plain language, foldable sections). A more detailed Korean version is [ROADMAP.md](ROADMAP.md).

## Vision

General-purpose LLMs can reason about shapes, names and structure, but they are weak exactly where 3D modeling is unforgiving:
they cannot reliably fuse several views into one 3D form, they get precise numbers and coordinates wrong, they cannot verify their own work, and they drift or declare false success on long tasks.

ModelerHarness does not try to make the model "smarter". It surrounds the model with the discipline of a skilled modeler:

- **The LLM decides, tools measure.** The LLM chooses parts, operators (blob, tube, plate) and how to read each drawing element. Deterministic tools fit the primitives, assemble the mesh and compute every number. The LLM never writes coordinates.
- **Only executed verifiers can pass work.** Verdicts are exactly PASS, FAIL, UNKNOWN or ERROR. A pass comes only from a verifier that actually ran. Criteria are written down before running and are never lowered to fit a failure.
- **Research must reach the code.** Every research finding gets an ID and a decision (adopted, deferred, rejected, pending). An adopted finding counts as reflected only when its linked test has run and passed against the current files.
- **The loop is an engine, not a habit.** The branching rules (criteria first → implement → judge → diagnose and retry → research → falsifiable hypothesis → one more try → defer) live in a Rust state machine, not in the model's memory.

The long-term goal: from a creature model sheet to an **editable, rig-ready game asset** (retopology, UVs, texture, rigging, export to Godot) on modest hardware, with every step judged by a verifier. The first user is the creature units of a separate game project.

## How it works: the harness layer

- **MCP server** `mh mcp` (stdio JSON-RPC, registered as `modeler-harness` in `.mcp.json`). Its 14 tools cover:
  - episode state;
  - observation: numeric digest, part zoom, headless renders;
  - action: a blueprint of per-part operators, with coordinate arguments rejected;
  - verification gates: criteria are fixed inside the server, and three FAILs on the same gate block the action tools;
  - judgment aggregation: order swaps, two model families, kappa;
  - lesson search;
  - a full call log in `episodes/<id>/trace.jsonl`.
- **Traceability** (`docs/추적_체계.md`). The decision registry `trace/registry.json` gives every research finding an ID and a decision with its rationale.
  - `mh trace_check` finds findings that were adopted but never designed, implemented or tested; broken links; forgotten findings; conflicts; unknown IDs; and research documents missing from the registry.
  - `mh trace_verify` actually runs the linked tests and records evidence, including file fingerprints.
  - A commit whose message says `루프 X 완료` ("loop item X done") is blocked by `tools/hooks/commit-msg` unless that item's gate passes.
- **Branching loop engine** `mh loop_next` / `mh loop_report`, also available over MCP. The engine:
  - judges by running the criteria commands itself and ignores verdicts the LLM reports;
  - follows FAIL, ERROR and UNKNOWN branches with retry limits;
  - skips items whose prerequisites are unfinished and reopens deferred items when their trigger completes;
  - refuses changed criteria files unless a reason is recorded;
  - marks an item done only when its traceability gate passes.

## Honest status

- On **synthetic creatures with 3D ground truth** (head, neck, torso, legs, tail, horns, ears; half of them with injected drawing errors), **primitive-operator fitting** (`mh fit`) clearly beats the two-view visual hull on 12 held-out tasks:
  - volume IoU 0.92 vs 0.59
  - 3/4 width-ratio error 0.02 vs 0.16
  - roughness 2.0° vs 6.7°
- **It still fails on a real hand-drawn sheet.** The head comes out flat, because silhouettes alone do not determine depth. Next: tone bands (cross-contour), a depth prior, and LLM structure judgments.
- **Self-tests:** the MCP server (12), the traceability checker (11) and the loop engine (17) all pass. Of 104 registered findings, 14 are verified as reflected. The registry as a whole still FAILs, because 29 older findings are not yet linked to code and tests. That list is the remaining work.
- **Not done yet:** LLM capability measurement (K0), texture, retopology and rigging finish, and Godot export.

## Layout

- `rust/` — the `mh` tool in Rust:
  - voxelization and area-based projection, visual hull;
  - scoring: silhouette, volume, 3/4 width ratio, roughness, landmarks;
  - synthetic creature generator, primitive fitting and SDF assembly, anatomy-rule checks;
  - the MCP server, traceability checker and loop engine.
  - `mh list` lists the tools. Input and output are JSON (`{판정, 요약, 파일}` = verdict, summary, files).
- `harness/` — Python on Blender's bundled interpreter: work inside Blender, plus the tracing and pipeline code not yet ported to Rust.
- `rules/anatomy_rules.json` — anatomy rule dictionary: sources, confidence, realistic and stylized ranges.
- `trace/` — decision registry and evidence.
- `bench/` — task bundles, scoring and experiments.
- `tests/` — self-tests (exit code 0 = PASS).
- `docs/` — design, research, diagnosis and logs. These are written in Korean.

## Quick start

```bash
cd rust && cargo build --release && cd ..
rust/target/release/mh.exe bundle '{"out": "bench/v2", "prefix": "dev", "start": 1000, "count": 12}'   # make synthetic tasks
rust/target/release/mh.exe fit '{"frame": "bench/v2/dev_1000/meta.json", "masks": "bench/v2/dev_1000/drawn_all.npz", "out": "out/dev_1000"}'
rust/target/release/mh.exe score '{"frame": "bench/v2/dev_1000/meta.json", "obj": "out/dev_1000/merged.obj", "truth": "bench/v2/dev_1000/truth_all.npz", "prims": "bench/v2/dev_1000/prims.json"}'
rust/target/release/mh.exe trace_check '{}'            # traceability report
rust/target/release/mh.exe loop_next '{}'              # next action from the loop engine (loop/plan.json)
```

The Python parts use Blender 5.2's bundled Python (see the commands section of `CLAUDE.md`).

## Not included in this public copy

Real drawing fixtures (`fixtures/`) and their results (`results/`, `packs/`, `sessions/`, `experiments/`, `bench/m0/real_*`) come from another project's artwork, so they are not published. Some docs and tests point to them and will not run here.
The public copy is built with `tools/publish_public.sh`, which publishes the current state only, with no history.

## License

[MIT](LICENSE). The license covers the code and documents in this repository. It does not cover the unpublished drawing fixtures from the other project, which are not included here.

---

## 한국어

**LLM(Claude Code 등)이 숙련 3D 모델러처럼 일하게 돕는 무료 로컬 하네스. 크리처 도면(정면·옆·뒤)을 보고, 도면에 충실한 3D 메시를 만든다.**
유료 3D 생성 서비스나 큰 GPU 없이 돈다. GTX 750 Ti(2GB)·i5-3470·RAM 16GB에서 개발했고, Blender + Rust + 약간의 파이썬으로 동작한다.

## 비전

범용 LLM은 모양·이름·구조를 따져 볼 수는 있다. 하지만 3D 모델링이 봐주지 않는 바로 그 부분에서 약하다.
여러 뷰를 하나의 3D 형태로 합치지 못하고, 정밀한 숫자·좌표를 틀리고, 자기 작업을 스스로 검증하지 못하고, 긴 작업에서는 길을 잃거나 거짓으로 완료를 선언한다.

ModelerHarness는 모델을 "더 똑똑하게" 만들려 하지 않는다. 대신 숙련 모델러의 규율로 모델을 둘러싼다.

- **판단은 LLM이, 측정은 도구가.** LLM은 부위, 연산자(덩어리·관·판), 도면 요소를 어떻게 읽을지를 정한다. 원형 맞추기, 메시 조립, 모든 숫자 계산은 결정적 도구가 한다. LLM은 좌표를 쓰지 않는다.
- **통과는 실행한 검증기만 낸다.** 판정은 PASS·FAIL·UNKNOWN·ERROR 넷뿐이다. 통과는 실제로 돌린 검증기에서만 나온다. 기준은 돌리기 전에 적고, 실패에 맞춰 낮추지 않는다.
- **조사는 코드까지 가야 한다.** 조사 결과마다 ID와 결정(채택·보류·기각·대기)을 붙인다. 채택한 조사는 연결된 시험이 지금 파일로 실제로 돌아 PASS 했을 때만 '반영됨'으로 센다.
- **루프는 습관이 아니라 엔진이다.** 분기 규칙(기준 먼저 → 구현 → 판정 → 진단·다시 → 조사 → 반증 가능한 가설 → 한 번 더 → 보류)은 모델의 기억이 아니라 Rust 상태 기계에 있다.

장기 목표는 크리처 도면에서 **사람이 고칠 수 있고 리깅 준비가 된 게임 에셋**(리토폴로지·UV·텍스처·리깅·Godot 내보내기)까지 가는 것이다. 수수한 하드웨어에서, 모든 단계를 검증기가 판정한다. 첫 사용처는 다른 게임 프로젝트의 크리처 유닛이다.

**함께하실 분을 찾습니다.** 그래픽스·기하 개발자, Blender 테크니컬 아티스트, Rust 개발자, 공개 라이선스 크리처 도면을 줄 수 있는 아티스트, LLM 평가 경험자. [CONTRIBUTING.md](CONTRIBUTING.md) 를 보세요.

**로드맵:** 단계 K0~K9, 돌리기 전에 정한 성공 기준이 붙은 이정표, 위험, 도울 곳을 쉬운 말로 정리했습니다. [ROADMAP.md](ROADMAP.md)(접어서 볼 수 있음).

## 어떻게 동작하나: 하네스 층

- **MCP 서버** `mh mcp`(stdio JSON-RPC, `.mcp.json`에 `modeler-harness`로 등록). 도구 14개가 맡는 역할은 다음과 같다.
  - 에피소드 상태
  - 관찰: 숫자 요약, 부위 확대, 헤드리스 그림
  - 행동: 부위별 연산자 설계도. 좌표 인자는 거부한다.
  - 검증 관문: 기준은 서버 안에 고정돼 있고, 같은 관문에서 FAIL이 3번 나면 행동 도구가 막힌다.
  - 판단 모음: 순서 바꿈, 두 모델 가족, 카파
  - 교훈 검색
  - 모든 호출 기록: `episodes/<id>/trace.jsonl`
- **추적 체계**(`docs/추적_체계.md`). 결정 장부 `trace/registry.json`에 조사 결과마다 ID와 결정, 근거를 적는다.
  - `mh trace_check`가 찾아내는 것: 채택했는데 설계·구현·시험이 없는 것, 연결 끊김, 잊힌 조사, 충돌, 장부에 없는 ID, 장부에 없는 조사 문서.
  - `mh trace_verify`는 연결된 시험을 실제로 돌리고, 파일 지문과 함께 증거를 남긴다.
  - 커밋 메시지에 `루프 X 완료`가 있으면, 그 항목의 관문이 PASS여야 `tools/hooks/commit-msg`가 커밋을 통과시킨다.
- **분기 루프 엔진** `mh loop_next`·`mh loop_report`(MCP로도 쓸 수 있음). 엔진이 하는 일은 다음과 같다.
  - 기준 명령을 직접 돌려 판정하고, LLM이 보고한 판정은 무시한다.
  - FAIL·ERROR·UNKNOWN 갈래를 시도 한도 안에서 따른다.
  - 선행이 안 끝난 항목은 건너뛰고, 보류 항목은 깨우는 조건이 끝나면 다시 연다.
  - 기준 파일이 바뀌면 이유가 적혀 있지 않은 한 거부한다.
  - 완료는 추적 관문이 PASS일 때만 인정한다.

## 지금 상태(정직하게)

- **3D 정답이 있는 합성 크리처**(머리·목·몸통·다리·꼬리·뿔·귀, 절반은 도면 오류 주입)에서는 **원형 연산자 맞추기**(`mh fit`)가 두 뷰 헐보다 분명히 낫다. 확인 과제 12개 기준:
  - 부피 IoU 0.92 대 0.59
  - 3/4 폭 비 오차 0.02 대 0.16
  - 거칠기 2.0° 대 6.7°
- **실제 손그림 도면에서는 아직 실패한다.** 머리가 납작해진다. 실루엣만으로는 깊이가 정해지지 않기 때문이다. 다음 단계는 톤 띠(크로스 컨투어), 깊이 사전, LLM 구조 판단이다.
- **자체 시험:** MCP 서버(12), 추적 검사기(11), 루프 엔진(17)이 모두 PASS다. 장부에 오른 조사 104개 중 14개가 반영됨으로 확인됐다. 장부 전체는 아직 FAIL이다. 옛 조사 29개가 코드·시험과 연결되지 않았기 때문이고, 그 목록이 남은 일이다.
- **아직 못 한 것:** LLM 판단 능력 측정(K0), 텍스처·리토폴로지·리깅 마감, Godot 내보내기.
- 전체 로드맵은 [ROADMAP.md](ROADMAP.md). 자세한 진단은 `docs/진단_방향재검토.md`, 계획은 `docs/구현계획_통합.md`, 작업 루프는 `docs/루프_작업목록.md`, 기록은 `docs/수정_기록.md`에 있다.

## 구성

- `rust/` — `mh` 도구(Rust)
  - 복셀화·넓이 기준 투영, 비주얼 헐
  - 채점: 실루엣, 부피, 3/4 폭 비, 거칠기, 랜드마크
  - 합성 크리처 생성기, 원형 맞추기와 SDF 조립, 해부 규칙 검사
  - MCP 서버, 추적 검사기, 루프 엔진
  - `mh list`로 도구 목록을 본다. 입출력은 JSON(`{판정, 요약, 파일}`)이다.
- `harness/` — Blender 번들 파이썬. Blender 안에서 하는 일과, 아직 Rust로 옮기지 않은 트레이싱·파이프라인.
- `rules/anatomy_rules.json` — 해부 규칙 사전: 근거, 확신, 사실 범위와 스타일 범위.
- `trace/` — 결정 장부와 증거.
- `bench/` — 과제 묶음, 채점, 실험.
- `tests/` — 자체 시험(끝 코드 0 = PASS).
- `docs/` — 설계, 조사, 진단, 기록(한국어).

## 실행

```bash
cd rust && cargo build --release && cd ..
rust/target/release/mh.exe bundle '{"out": "bench/v2", "prefix": "dev", "start": 1000, "count": 12}'   # 합성 과제 만들기
rust/target/release/mh.exe fit '{"frame": "bench/v2/dev_1000/meta.json", "masks": "bench/v2/dev_1000/drawn_all.npz", "out": "out/dev_1000"}'
rust/target/release/mh.exe score '{"frame": "bench/v2/dev_1000/meta.json", "obj": "out/dev_1000/merged.obj", "truth": "bench/v2/dev_1000/truth_all.npz", "prims": "bench/v2/dev_1000/prims.json"}'
rust/target/release/mh.exe trace_check '{}'            # 추적 보고
rust/target/release/mh.exe loop_next '{}'              # 루프 엔진이 정한 다음 행동(loop/plan.json)
```

파이썬 부분은 Blender 5.2 번들 파이썬을 쓴다(`CLAUDE.md` 명령 절).

## 공개본에서 뺀 것

실제 도면 고정물(`fixtures/`)과 그 결과(`results/`·`packs/`·`sessions/`·`experiments/`·`bench/m0/real_*`)는 다른 프로젝트의 그림에서 나와서 공개하지 않는다. 일부 문서와 시험이 이 파일들을 가리키므로, 그 부분은 여기서 돌지 않는다.
공개본은 `tools/publish_public.sh`로 만든다. 이력 없이 지금 상태만 올린다.

## 라이선스

[MIT](LICENSE). 이 저장소의 코드와 문서에 적용된다. 공개하지 않은 다른 프로젝트의 도면 고정물에는 적용되지 않는다(여기에 들어 있지 않다).
