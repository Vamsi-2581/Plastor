# Modeling blueprint format (draft, 2026-10-29)

The user asked: “Can tracing information and cross-contour information be written as values in an AI modeling blueprint?” Yes. The 3D builder reads only this blueprint.

**Principle:** tools measure numbers; the LLM writes only names, types, and choices; every value records its source and confidence; a checker validates the blueprint before building.

## Structure

~~~json
{
  "도면": {"뷰": ["front", "side", "back"], "단위": "H", "출처_신뢰": "AI생성"},
  "부위": [
    {
      "이름": "뿔", "종류": "가늘어지는 둥근 관",
      "종류_출처": {"값": "LLM 피아식별", "두가족_일치": true},
      "좌우_짝": {"거울": true, "기준": "front"},
      "중심선": {"점": [[0.21, 0.05, 5.02], [0.45, 0.02, 5.18]], "출처": "트레이싱 가운데선(정면·옆 합침)", "확신": 0.9},
      "단면": [
        {"t": 0.0, "폭": 0.12, "깊이": 0.10, "모양": {"종류": "초타원", "지수": 2.0, "납작함": 0.83},
         "출처": {"폭": "정면 트레이싱", "깊이": "옆 트레이싱", "모양": "그림자 띠 법선"}, "확신": 0.8},
        {"t": 1.0, "폭": 0.02, "깊이": 0.02, "모양": {"종류": "초타원", "지수": 2.0, "납작함": 1.0},
         "출처": {"폭": "정면 트레이싱", "깊이": "옆 트레이싱", "모양": "이름 틀(가늘어지는 둥근 관)"}, "확신": 0.6}
      ],
      "붙는곳": {"부모": "머리", "자리": "위 옆", "박기_px": 8},
      "가정": [],
      "결정": []
    }
  ],
  "그림모순": [{"부위": "머리", "결정": "정면 따름", "근거": "옆 턱이 13px 아래"}]
}
~~~

The JSON example is unchanged from the Korean source. Korean keys are kept as-is; their English meanings are listed here:

| Key | English meaning |
|---|---|
| 도면 | drawing sheet |
| 뷰 | views |
| 단위 | unit |
| 출처_신뢰 | source and confidence |
| 부위 | parts |
| 이름 | name |
| 종류 | type |
| 종류_출처 | source of the type |
| 값 | value |
| 두가족_일치 | agreement between two model families |
| 좌우_짝 | left-right pair |
| 거울 | mirror |
| 기준 | reference |
| 중심선 | centerline |
| 점 | points |
| 출처 | source |
| 확신 | confidence |
| 단면 | cross-sections |
| t | position along the centerline |
| 폭 | width |
| 깊이 | depth |
| 모양 | shape |
| 지수 | exponent |
| 납작함 | flatness |
| 붙는곳 | attachment |
| 부모 | parent |
| 자리 | position |
| 박기_px | embed depth in pixels |
| 가정 | assumptions |
| 결정 | decisions |
| 그림모순 | drawing conflicts |
| 근거 | evidence |

- The cross-section parameter **t** runs from 0 (root) to 1 (tip) along the centerline. Each cross-section is perpendicular to that line.
- Cross-section **shape** uses a superellipse exponent (2 is an ellipse; larger values are more angular) and flatness (flattening beyond the width-to-depth ratio). Fill it in this order: cross-contour (shadow-band normal) → name template → default ellipse (R1.5).
- Allowed **source** values are: “정면 트레이싱” (front tracing), “옆 트레이싱” (side tracing), “그림자 띠 법선” (shadow-band normal), “그림 단면선” (drawn cross-section line), “이름 틀” (name template), “LLM 결정” (LLM decision), and “가정” (assumption).

## Flow

1. Preserve the original tracing → intent layer (differences) → **blueprint-filling tool** (measure the centerline and cross-section width/depth, then infer cross-section shape from shadow normals).
2. The LLM fills in only the part name, type, pair, attachment, and drawing-conflict decisions (no coordinates).
3. **Blueprint check:** project cross-sections into the front and side views and compare their widths with the tracing; check pair symmetry and whether each attachment lies on the parent surface. Build only after PASS.
4. Build (R1 smooth generalized cylinders) → run 3D checks → if something is misaligned, trace it back to the relevant part and cross-section (inverse mapping).

## Validation criteria (set before running)

- On synthetic scenes, the reprojection IoU of a model rebuilt from the blueprint alone must be at least rounded-hull IoU − 0.01, and its volume IoU must be greater than the rounded hull’s.
- If only one part’s cross-section changes, only that part’s mesh may change; fingerprints for all other parts must stay identical.

## Addition: anatomy and perspective information

The user suggested generating anatomy and perspective information at the same time. The example below is unchanged from the Korean source. Korean keys are preserved; their English meanings follow:

~~~json
{
  "해부": {
    "뼈_표지": [
      {"이름": "턱 경첩", "점": [0.0, 0.18, 4.72], "출처": "옆 트레이싱 턱선 꺾임 + 좌우 대칭", "확신": 0.6},
      {"이름": "뿔 뿌리", "부위": "뿔", "점": [0.21, 0.05, 5.02], "출처": "설계도 붙는곳", "확신": 0.9}
    ],
    "덮개_밑_몸": [{"부위": "머리", "덮개": "턱수염", "출처": "해부 보완(amodal)", "가정": true}],
    "비율": {"뿔길이/머리길이": 0.9, "출처": "설계도 측정"}
  },
  "투시": {
    "뷰": {
      "front": {"투영": "정사영", "1H_px": 150.5, "중심선_x": 321.5, "발바닥_행": 943, "투시_징후": 0.02, "빛_방향": [0.45, 0.55, 0.7], "빛_출처": "그림자 띠 경계"},
      "side":  {"투영": "정사영", "투시_징후": 0.08, "빛_방향": [0.40, 0.60, 0.69]}
    },
    "뷰_사이_어긋남": [{"뷰": ["front", "side"], "부위": "머리", "아래끝_px": 13}]
  }
}
~~~

| Key | English meaning |
|---|---|
| 해부 | anatomy |
| 뼈_표지 | bone landmarks |
| 덮개_밑_몸 | body under a cover (amodal completion) |
| 덮개 | cover |
| 비율 | proportions |
| 뿔길이/머리길이 | horn length / head length |
| 투시 | perspective |
| 투영 | projection |
| 1H_px | pixel scale for one H |
| 중심선_x | centerline x-coordinate |
| 발바닥_행 | sole row |
| 투시_징후 | perspective cue |
| 빛_방향 | light direction |
| 빛_출처 | light source |
| 뷰_사이_어긋남 | discrepancy between views |
| 아래끝_px | lower-edge position in pixels |

- **Anatomy:** bone landmarks (skull center, jaw hinge, neck joint, horn, and ear root) become rig-bone positions as-is (R6/R7). Tools measure their positions from tracing and symmetry; the LLM supplies names. Values from the shape dictionary are assumptions.
- **Perspective:** for each view, record whether it is orthographic (for example, left-right size differences for the same part and whether horizontal guide lines are parallel), scale, center, sole row, and light direction (from shadow-band edges, R1.5). If the perspective cue is high, treat that view as non-orthographic and do not count its reprojection error as a modeling error.
- **Uses:** shape decisions (whether a lowered jaw is a drawing error or an open mouth, using the jaw hinge as a reference); drawing conflicts (different light directions across views add +1 evidence); rigging (bone landmarks become the skeleton).
- **Validation:** on synthetic scenes with known orthographic projection, light direction, and bone positions, light-direction error ≤ 10°; detect a view with deliberately added perspective using the perspective cue; bone-landmark position error ≤ 0.05H.
