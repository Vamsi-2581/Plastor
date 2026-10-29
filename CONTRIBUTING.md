# Contributing to ModelerHarness — we are looking for collaborators

[한국어는 아래에 있습니다 ↓](#한국어)

ModelerHarness is a free, local harness that lets an LLM work like a skilled 3D modeler. It turns creature model sheets (front, side and back views) into 3D meshes that stay faithful to the drawings. It runs on modest hardware (a 2 GB GPU is enough) with Blender, Rust and a little Python, and needs no paid services.

The core idea: **the LLM decides, tools measure, and only executed verifiers can pass work.** We are building this in the open and would love help from people who care about any part of it.

## Where we need help

Each area links to an item in the work plan (`docs/루프_작업목록.md`, `docs/구현계획_통합.md`).

| Area | What is needed | Good fit for |
|---|---|---|
| **Depth from drawings** (the current blocker) | Real hand-drawn sheets come out with a flat head, because silhouettes alone do not fix depth. We want to read depth from tone bands and cross-contours (Inverse Toon Shading, CrossShade) and feed it into the fitting loss. Plan K3. | Graphics and geometry developers, researchers |
| **Openly licensed test drawings** | Our real drawing fixtures come from another project and cannot be published. We need creature model sheets (front, side, back) that we may redistribute, ideally with a reference 3D model. | Artists, creature designers |
| **Editable and game-ready output** | Primitives exported as editable Blender objects (curve tubes, blobs). Then QuadriFlow retopology, an automatic bend test for rigging, at most 4 bone influences per vertex, glTF export, and loading in Godot. Plan item 8, K7. | Blender technical artists, riggers |
| **Rust port** | Move tracing and the build pipeline from Python to Rust. Python stays only for `bpy` and ML-model workers. Plan item 7. | Rust developers |
| **Drawing-element classification** | Sort each drawing element as identity, style, uncertain, error or conflict, and ignore true errors. Synthetic tasks with injected errors already exist. Plan item 6. | Developers, researchers |
| **LLM evaluation** | Measure what LLMs can and cannot judge (parts, operators, art quality), and run an A/B test: LLM working through our MCP server vs. automatic fitting without an LLM. Plan K0, item 4e. | People with LLM or VLM evaluation experience |
| **Traceability backlog** (good first issue) | 29 older research findings are adopted but not yet linked to code and tests. `mh trace_check '{}'` lists them. Each one needs a design link, ID markers and a test that really exercises the feature. Plan item 4h. | Anyone. A good way to learn the codebase |
| **English docs** | Most design and research docs are in Korean. Translations or English summaries help everyone. | Bilingual contributors |

## Ground rules (these are what make it a harness)

1. **Four verdicts only:** PASS, FAIL, UNKNOWN, ERROR. Only a verifier that actually ran can produce a pass. "It looks right" is not a pass.
2. **Write criteria before you run.** A pull request that changes behavior states its success criteria first, then shows the test result. Do not lower a criterion to fit a failure. If a test was flawed, fix it and say so, keeping the numbers.
3. **Never invent numbers.** If you could not measure something, report UNKNOWN and the reason.
4. **The LLM never writes coordinates.** Tools accept part names, operators and settings. Numbers come from solvers and measurements.
5. **Research must be traceable.** If your work comes from a paper or tool, add an entry to `trace/registry.json` with an ID, a decision and its rationale. Put the ID marker in the design doc, the code and the test. Then run `mh trace_verify` so the evidence is recorded.
6. **Free and local.** No paid APIs and no large-GPU requirement. Open-source dependencies are fine if you say why they are needed.
7. **No third-party art without permission.** Only add drawings you have the right to redistribute.

## Getting started

```bash
git clone https://github.com/endlessGold/ModelerHarness
cd ModelerHarness/rust && cargo build --release && cd ..
rust/target/release/mh.exe list                   # all tools
rust/target/release/mh.exe trace_check '{}'       # what is reflected, what is still missing
rust/target/release/mh.exe loop_next '{}'         # what the loop engine says to do next (needs loop/plan.json)
```

The Python tests use Blender 5.2's bundled Python, for example `"<Blender>/5.2/python/bin/python.exe" tests/selftest_traceability.py`. Exit code 0 means PASS. Some tests point to unpublished fixtures and will not run in the public copy.

## How to contribute

1. **Open an issue first.** Say what you want to work on and what success would look like. We will agree on criteria before code is written.
2. Keep each pull request to one change, with a test that exits 0 on PASS.
3. In the pull request, include:
   - the criteria;
   - the test output;
   - the trace IDs touched;
   - anything that is still UNKNOWN.
4. English or Korean, whichever you prefer, is fine in issues, pull requests and comments.

## License

ModelerHarness is released under the [MIT License](LICENSE). By submitting a contribution, you agree that it is licensed under the MIT License. Test drawings must come with clear redistribution rights. Say in the pull request under what terms the art may be shared.

---

## 한국어

# ModelerHarness 에 기여하기: 함께할 사람을 찾습니다

ModelerHarness 는 LLM 이 숙련 3D 모델러처럼 일하게 돕는 무료 로컬 하네스입니다. 크리처 도면(정면·옆·뒤)을 도면에 충실한 3D 메시로 만듭니다. 수수한 하드웨어(2GB GPU면 충분)에서 Blender·Rust·약간의 파이썬으로 돌고, 유료 서비스가 필요 없습니다.

핵심 생각: **판단은 LLM 이, 측정은 도구가, 통과는 실행한 검증기만.** 이 프로젝트는 공개로 만들고 있습니다. 어느 부분이든 관심 있는 분의 도움을 기다립니다.

## 도움이 필요한 곳

각 분야는 작업 계획(`docs/루프_작업목록.md`, `docs/구현계획_통합.md`)의 항목과 이어져 있습니다.

| 분야 | 필요한 것 | 어울리는 분 |
|---|---|---|
| **도면에서 깊이 읽기**(지금 막힌 곳) | 실제 손그림 도면은 머리가 납작하게 나옵니다. 실루엣만으로는 깊이가 정해지지 않기 때문입니다. 톤 띠와 크로스 컨투어(Inverse Toon Shading, CrossShade)로 깊이를 읽어 맞추기 손실에 넣고 싶습니다. 계획 K3. | 그래픽스·기하 개발자, 연구자 |
| **공개 라이선스 시험 도면** | 지금 쓰는 실제 도면은 다른 프로젝트 것이라 공개할 수 없습니다. 다시 배포해도 되는 크리처 도면(정면·옆·뒤)이 필요하고, 기준 3D 모델이 함께 있으면 더 좋습니다. | 아티스트, 크리처 디자이너 |
| **고칠 수 있고 게임에 쓸 수 있는 결과물** | 원형을 Blender 에서 고칠 수 있는 객체(커브 관, 덩어리)로 내보내기. 그다음 QuadriFlow 리토폴로지, 리깅용 자동 굽힘 시험, 정점당 영향 뼈 4개 이하, glTF 내보내기, Godot 로드 확인. 계획 항목 8, K7. | Blender 테크니컬 아티스트, 리거 |
| **Rust 이전** | 트레이싱과 빌드 파이프라인을 파이썬에서 Rust 로 옮깁니다. 파이썬은 `bpy` 와 학습 모델 일꾼만 남깁니다. 계획 항목 7. | Rust 개발자 |
| **도면 요소 분류** | 도면 요소를 정체성·스타일·불확실·오류·충돌로 나누고, 진짜 오류는 무시합니다. 오류를 주입한 합성 과제가 이미 있습니다. 계획 항목 6. | 개발자, 연구자 |
| **LLM 평가** | LLM 이 무엇을 판단할 수 있고 없는지 잽니다(부위, 연산자, 아트 품질). 그리고 MCP 서버로 일하는 LLM 판과 LLM 없는 자동 맞추기를 A/B 로 비교합니다. 계획 K0, 항목 4e. | LLM·VLM 평가 경험이 있는 분 |
| **추적 밀린 일**(처음 하기 좋은 일) | 옛 조사 29개가 채택됐지만 코드·시험과 아직 연결되지 않았습니다. `mh trace_check '{}'` 로 목록이 나옵니다. 하나마다 설계 연결, ID 표지, 그 기능을 실제로 재는 시험이 필요합니다. 계획 항목 4h. | 누구나. 코드를 익히기 좋습니다 |
| **영어 문서** | 설계·조사 문서는 대부분 한국어입니다. 번역이나 영어 요약이 모두에게 도움이 됩니다. | 두 언어를 쓰는 분 |

## 기본 규칙(이것이 하네스를 하네스로 만듭니다)

1. **판정은 넷뿐입니다:** PASS·FAIL·UNKNOWN·ERROR. 통과는 실제로 돌린 검증기만 낼 수 있습니다. "맞아 보인다"는 통과가 아닙니다.
2. **돌리기 전에 기준을 적습니다.** 동작을 바꾸는 합치기 요청(PR)은 성공 기준을 먼저 적고, 그다음 시험 결과를 보입니다. 실패에 맞춰 기준을 낮추지 않습니다. 시험에 결함이 있었다면 고치고, 그 사실과 숫자를 그대로 적습니다.
3. **숫자를 지어내지 않습니다.** 재지 못했으면 UNKNOWN 과 이유를 적습니다.
4. **LLM 은 좌표를 쓰지 않습니다.** 도구는 부위 이름·연산자·설정만 받습니다. 숫자는 풀이기와 측정에서 나옵니다.
5. **조사는 추적할 수 있어야 합니다.** 논문이나 도구에서 나온 작업이면 `trace/registry.json` 에 ID·결정·근거를 적습니다. 그 ID 표지를 설계 문서·코드·시험에 넣고, `mh trace_verify` 를 돌려 증거를 남깁니다.
6. **무료이고 로컬입니다.** 유료 API 나 큰 GPU 를 요구하지 않습니다. 오픈소스 의존성은 왜 필요한지 적으면 됩니다.
7. **허락 없는 남의 그림은 넣지 않습니다.** 다시 배포할 권리가 있는 도면만 넣습니다.

## 시작하기

```bash
git clone https://github.com/endlessGold/ModelerHarness
cd ModelerHarness/rust && cargo build --release && cd ..
rust/target/release/mh.exe list                   # 도구 전체
rust/target/release/mh.exe trace_check '{}'       # 반영된 것과 아직 빠진 것
rust/target/release/mh.exe loop_next '{}'         # 루프 엔진이 정한 다음 할 일(loop/plan.json 필요)
```

파이썬 시험은 Blender 5.2 번들 파이썬으로 돌립니다. 예: `"<Blender>/5.2/python/bin/python.exe" tests/selftest_traceability.py`. 끝 코드 0 이 PASS 입니다. 일부 시험은 공개하지 않은 고정물을 가리켜서 공개본에서는 돌지 않습니다.

## 기여하는 방법

1. **먼저 이슈를 엽니다.** 무엇을 할지, 성공하면 어떤 모습일지 적어 주세요. 코드를 쓰기 전에 기준을 함께 정합니다.
2. 합치기 요청 하나에는 변경 하나만 넣고, PASS 면 끝 코드 0 을 내는 시험을 붙입니다.
3. 합치기 요청에 다음을 적습니다.
   - 기준
   - 시험 출력
   - 건드린 추적 ID
   - 아직 UNKNOWN 인 것
4. 이슈·합치기 요청·댓글은 영어든 한국어든 편한 쪽으로 쓰면 됩니다.

## 라이선스

ModelerHarness 는 [MIT 라이선스](LICENSE)로 공개합니다. 기여를 보내면 그 기여도 MIT 라이선스로 낸다는 데 동의하는 것입니다. 시험 도면은 다시 배포할 권리가 분명해야 합니다. 그림을 어떤 조건으로 나눠도 되는지 합치기 요청에 적어 주세요.
