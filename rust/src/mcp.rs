//! 추적(docs/추적_체계.md): R-011 R-012 R-013 R-015 R-018 R-019
//! 하네스 MCP 서버(`mh mcp`, stdio JSON-RPC 2.0, 루프 항목 4e). 도구 묶음이 아니라 하네스 역할을 한다:
//! 에피소드·상태, 관찰(읽기만), 행동(좌표 없음), 검증 관문(통과는 관문의 PASS 만, 기준은 서버 안 고정),
//! 판단 모음, 기억(교훈 검색), 예산(같은 관문 FAIL 3번이면 행동 도구를 막고 '조사 필요'), 모든 호출 기록(trace.jsonl).
use crate::fit::Kind;
use crate::frame::Frame;
use crate::grid::Mask2;
use crate::npy;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::{BufRead, Write};
use std::time::Instant;

const FAIL_LIMIT: u64 = 3;
const RULES_TEXT: &str = "하네스 규칙: (1) 판정은 PASS·FAIL·UNKNOWN·ERROR 넷, 통과는 verify_gate 가 낸 PASS 만. (2) 좌표·정점 값을 쓰지 않는다: 부위 이름·연산자(덩어리|관|판)·도면 요소 분류만 쓴다, 숫자는 도구가 잰다. (3) 순서: episode_start → observe_* → act_blueprint → act_fit → verify_* → verify_gate. (4) 같은 관문이 3번 FAIL 이면 행동 도구가 막힌다: memory_lessons 로 조사하고 act_blueprint 를 고친 뒤 episode_reset_budget 로 다시. (5) 세기·크기는 그림에서 세지 말고 observe_digest 숫자를 읽는다. (6) 판단이 엇갈리면 judge 로 모은다.";

fn ep_dir(id: &str) -> String {
    format!("episodes/{}", id)
}

fn load_state(id: &str) -> Result<Value, String> {
    let p = format!("{}/state.json", ep_dir(id));
    serde_json::from_str(&std::fs::read_to_string(&p).map_err(|_| format!("에피소드 {} 없음(episode_start 먼저)", id))?).map_err(|e| e.to_string())
}

fn save_state(id: &str, st: &Value) -> Result<(), String> {
    std::fs::write(format!("{}/state.json", ep_dir(id)), serde_json::to_string_pretty(st).unwrap()).map_err(|e| e.to_string())
}

fn masks(path: &str) -> Result<BTreeMap<(String, String), Mask2>, String> {
    let mut out = BTreeMap::new();
    for (k, a) in npy::read_npz(path)? {
        let mut it = k.splitn(2, '|');
        let (v, p) = (it.next().unwrap_or("").to_string(), it.next().unwrap_or("").to_string());
        out.insert((v, p), Mask2 { h: a.shape[0], w: a.shape[1], d: a.as_bool() });
    }
    Ok(out)
}

fn s(a: &Value, k: &str) -> Result<String, String> {
    a[k].as_str().map(String::from).ok_or(format!("'{}' 가 필요함", k))
}

/// 좌표처럼 보이는 숫자 목록 인자를 거부(하네스 규칙 2).
fn reject_coords(a: &Value) -> Result<(), String> {
    fn walk(v: &Value) -> bool {
        match v {
            Value::Array(x) => (x.len() >= 2 && x.iter().all(|e| e.is_number())) || x.iter().any(walk),
            Value::Object(m) => m.values().any(walk),
            _ => false,
        }
    }
    if walk(a) { Err("좌표·숫자 목록은 받지 않는다(하네스 규칙 2): 부위 이름·연산자·분류만".into()) } else { Ok(()) }
}

fn tools() -> Vec<Value> {
    let t = |name: &str, desc: &str, props: Value, req: Vec<&str>| json!({"name": name, "description": desc, "inputSchema": {"type": "object", "properties": props, "required": req}});
    let id = json!({"type": "string", "description": "에피소드 id"});
    vec![
        t("harness_rules", "하네스 규칙(판정 넷·좌표 금지·순서·예산). 먼저 읽는다.", json!({}), vec![]),
        t("episode_start", "[상태] 과제 폴더(drawing.npy·meta.json·drawn_all.npz, 있으면 truth_all.npz·prims.json)로 에피소드를 연다.", json!({"task_dir": {"type": "string"}, "id": {"type": "string"}}), vec!["task_dir", "id"]),
        t("episode_status", "[상태] 단계·시도 수·설계도·마지막 판정·막힘 여부.", json!({"id": id}), vec!["id"]),
        t("episode_reset_budget", "[예산] 조사(memory_lessons)와 설계도 수정 뒤 막힌 관문의 시도 수를 되돌린다. 이유를 적어야 한다.", json!({"id": id, "이유": {"type": "string"}}), vec!["id", "이유"]),
        t("observe_digest", "[관찰] 부위·뷰마다 조각 수·넓이(px)·높이 범위(H). 세기·크기는 이 숫자를 읽는다.", json!({"id": id}), vec!["id"]),
        t("observe_zoom", "[관찰] 부위 이름으로 그 부위 둘레를 원래 해상도로 잘라 키운 PNG(긴 변 ≤ 1568).", json!({"id": id, "part": {"type": "string"}, "view": {"type": "string", "enum": ["front", "side", "back"]}}), vec!["id", "part", "view"]),
        t("observe_look", "[관찰] 지금 결과 메시를 헤드리스 Blender 로 3/4·위·아래에서 본 그림(음영·법선·와이어). 깨진 면·계단은 음영만으론 안 보인다.", json!({"id": id}), vec!["id"]),
        t("act_blueprint", "[행동] 설계도: 부위마다 연산자(덩어리|관|판)와 도면 요소 분류(정체성|스타일|불확실|오류|충돌), 근거. 좌표 없음.", json!({"id": id, "parts": {"type": "object", "description": "{부위: {연산자, 분류?, 근거}}"}}), vec!["id", "parts"]),
        t("act_fit", "[행동] 설계도의 연산자로 원형 맞추기 + SDF 조립 → merged.obj. 관문이 막혔으면 거부.", json!({"id": id}), vec!["id"]),
        t("verify_score", "[검증] 채점: 정답이 있으면 3D 정답 대비(부피·실루엣·3/4 폭 비·거칠기·몸 수), 없으면 도면 마스크 대비 실루엣.", json!({"id": id}), vec!["id"]),
        t("verify_anatomy", "[검증] 해부 규칙(rules/anatomy_rules.json) 검사: 위반·주의와 근거.", json!({"id": id}), vec!["id"]),
        t("verify_gate", "[검증 관문] 단계 '형상' 관문: 몸 수 1, 해부 위반 0, 실루엣 평균 ≥ 0.93(기준은 서버 안 고정). PASS 만이 통과. FAIL 3번이면 행동 도구가 막힌다.", json!({"id": id, "단계": {"type": "string", "enum": ["형상"]}}), vec!["id", "단계"]),
        t("judge", "[판단 모음] 같은 문항을 순서 바꿔·두 가족으로 물은 답 → 다수·재현율·순서 뒤집힘·가족 카파, 기준 미달이면 UNKNOWN.", json!({"runs": {"type": "array", "description": "[{가족, 순서, 답: {문항: 답}}]"}}), vec!["runs"]),
        t("verify_trace", "[검증 관문·추적] 조사 → 결정 → 설계 → 구현 → 시험 증거 장부 검사. 항목(루프 자리)을 주면 그 자리 관문: 채택했는데 안 만들었거나 시험 PASS 증거가 없거나 낡았으면 FAIL.", json!({"항목": {"type": "string"}}), vec![]),
        t("loop_next", "[루프 엔진] 지금 할 행동 하나(분기 규칙: 기준 먼저 → 구현 → 엔진이 기준 명령으로 판정 → FAIL 이면 진단·다시(2번)·조사·가설·한 번 더·보류, 완료는 추적 관문 PASS). 사용량을 주면 문턱에서 잠·멈춤.", json!({"사용량": {"type": "object", "description": "{주간, 다섯시간} 퍼센트"}}), vec![]),
        t("loop_report", "[루프 엔진] 한 행동을 끝냈다고 알린다. 종류: 기준|기준_고침|구현_끝|진단|조사|가설|추적_끝|보류_요청|뒤에서_돌림|뒤_끝|전제_바뀜. 보고에 적은 판정은 쓰지 않는다.", json!({"항목": {"type": "string"}, "종류": {"type": "string"}, "명령": {"type": "array"}, "진단": {"type": "string"}, "원인_앎": {"type": "boolean"}, "내용": {"type": "string"}, "가설": {"type": "string"}, "반증": {"type": "string"}, "이유": {"type": "string"}, "순서": {"type": "array"}, "단서": {"type": "string"}, "무엇": {"type": "string"}}), vec!["종류"]),
        t("memory_lessons", "[기억] 교훈(docs/교훈.jsonl) 검색: 단어·진단·부위로.", json!({"단어": {"type": "string"}}), vec![]),
    ]
}

fn trace(id: &str, tool: &str, args: &Value, verdict: &str, ms: u128) {
    if id.is_empty() {
        return;
    }
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(format!("{}/trace.jsonl", ep_dir(id))) {
        let _ = writeln!(f, "{}", json!({"도구": tool, "입력": args, "판정": verdict, "ms": ms}));
    }
}

fn call(name: &str, a: &Value) -> Result<(String, Value), String> {
    match name {
        "harness_rules" => Ok(("UNKNOWN".into(), json!({"규칙": RULES_TEXT}))),
        "episode_start" => {
            let id = s(a, "id")?;
            let td = s(a, "task_dir")?;
            for f in ["drawing.npy", "meta.json", "drawn_all.npz"] {
                if !std::path::Path::new(&format!("{}/{}", td, f)).exists() {
                    return Err(format!("과제 폴더에 {} 없음", f));
                }
            }
            std::fs::create_dir_all(ep_dir(&id)).map_err(|e| e.to_string())?;
            let m = masks(&format!("{}/drawn_all.npz", td))?;
            let parts: Vec<String> = m.keys().map(|(_, p)| p.clone()).collect::<std::collections::BTreeSet<_>>().into_iter().collect();
            let st = json!({"과제": td, "단계": "형상", "시도": {"형상": 0}, "설계도": {}, "막힘": false, "정답_있음": std::path::Path::new(&format!("{}/prims.json", td)).exists(), "부위": parts});
            save_state(&id, &st)?;
            Ok(("PASS".into(), st))
        }
        "episode_status" => Ok(("UNKNOWN".into(), load_state(&s(a, "id")?)?)),
        "episode_reset_budget" => {
            let id = s(a, "id")?;
            let mut st = load_state(&id)?;
            st["시도"]["형상"] = json!(0);
            st["막힘"] = json!(false);
            st["예산_되돌림_이유"] = a["이유"].clone();
            save_state(&id, &st)?;
            Ok(("PASS".into(), st))
        }
        "observe_digest" => {
            let st = load_state(&s(a, "id")?)?;
            let td = st["과제"].as_str().unwrap();
            let fr = Frame::load(&format!("{}/meta.json", td))?;
            let mut out = Vec::new();
            for ((v, p), m) in masks(&format!("{}/drawn_all.npz", td))? {
                if m.count() == 0 || !fr.panels.contains_key(&v) {
                    continue;
                }
                let rows: Vec<usize> = (0..m.h).filter(|&r| (0..m.w).any(|c| m.get(r, c))).collect();
                let (z1, z0) = (fr.px_to_h(&v, 0.0, rows[0] as f64).1, fr.px_to_h(&v, 0.0, *rows.last().unwrap() as f64 + 1.0).1);
                out.push(json!({"뷰": v, "부위": p, "넓이_px": m.count(), "조각_수": pieces(&m), "높이_H": [(z0 * 1000.0).round() / 1000.0, (z1 * 1000.0).round() / 1000.0]}));
            }
            Ok(("UNKNOWN".into(), json!({"표": out})))
        }
        "observe_zoom" => {
            let id = s(a, "id")?;
            let st = load_state(&id)?;
            let td = st["과제"].as_str().unwrap();
            let (part, view) = (s(a, "part")?, s(a, "view")?);
            let m = masks(&format!("{}/drawn_all.npz", td))?;
            let mk = m.get(&(view.clone(), part.clone())).filter(|x| x.count() > 0).ok_or(format!("{} 뷰에 {} 없음", view, part))?;
            let img = npy::read_npy(&format!("{}/drawing.npy", td))?;
            let (h, w) = (img.shape[0], img.shape[1]);
            let px = match img.data { npy::ArrData::U8(v) => v, _ => return Err("drawing 은 uint8".into()) };
            let (mut r0, mut r1, mut c0, mut c1) = (h, 0, w, 0);
            for r in 0..h {
                for c in 0..w {
                    if mk.get(r, c) {
                        r0 = r0.min(r); r1 = r1.max(r); c0 = c0.min(c); c1 = c1.max(c);
                    }
                }
            }
            let pad = ((r1 - r0).max(c1 - c0) / 4).max(4);
            let (r0, c0, r1, c1) = (r0.saturating_sub(pad), c0.saturating_sub(pad), (r1 + pad).min(h - 1), (c1 + pad).min(w - 1));
            let (ch, cw) = (r1 - r0 + 1, c1 - c0 + 1);
            let k = (1568 / ch.max(cw)).max(1);
            let mut out = vec![0u8; ch * k * cw * k * 3];
            for r in 0..ch * k {
                for c in 0..cw * k {
                    let (sr, sc) = (r0 + r / k, c0 + c / k);
                    let edge = mk.get(sr, sc) && [(0i64, 1i64), (1, 0), (0, -1), (-1, 0)].iter().any(|(dr, dc)| {
                        let (a2, b2) = (sr as i64 + dr, sc as i64 + dc);
                        a2 < 0 || b2 < 0 || a2 >= h as i64 || b2 >= w as i64 || !mk.get(a2 as usize, b2 as usize)
                    });
                    let o = (r * cw * k + c) * 3;
                    let i = (sr * w + sc) * 3;
                    let col = if edge { [255, 0, 200] } else { [px[i], px[i + 1], px[i + 2]] };
                    out[o..o + 3].copy_from_slice(&col);
                }
            }
            let path = format!("{}/zoom_{}_{}.png", ep_dir(&id), view, part);
            crate::png::write_rgb(&path, cw * k, ch * k, &out)?;
            Ok(("UNKNOWN".into(), json!({"그림": path, "배율": k})))
        }
        "observe_look" => {
            let id = s(a, "id")?;
            let st = load_state(&id)?;
            let obj = st["결과"].as_str().ok_or("act_fit 먼저")?.to_string();
            let out = format!("{}/look", ep_dir(&id));
            let blender = std::env::var("MH_BLENDER").unwrap_or_else(|_| "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe".into());
            let abs = |p: &str| std::fs::canonicalize(p).map(|x| x.to_string_lossy().trim_start_matches(r"\\?\").to_string()).unwrap_or(p.to_string());
            std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
            let r = std::process::Command::new(&blender)
                .args(["-b", "-P", &abs("harness/blender_view_bg.py"), "--", &abs(&obj), &abs(&out), "3-4_앞왼:75:135,위:5:180,아래:175:180", "solid,normal,wire"])
                .output().map_err(|e| format!("Blender 실행 실패: {}", e))?;
            let files: Vec<String> = std::fs::read_dir(&out).map_err(|e| e.to_string())?.filter_map(|e| e.ok()).map(|e| format!("{}/{}", out, e.file_name().to_string_lossy())).filter(|f| f.ends_with(".png")).collect();
            if files.is_empty() {
                return Err(format!("헤드리스 렌더 실패: {}", String::from_utf8_lossy(&r.stderr).chars().rev().take(300).collect::<String>().chars().rev().collect::<String>()));
            }
            Ok(("UNKNOWN".into(), json!({"그림": files})))
        }
        "act_blueprint" => {
            reject_coords(a)?;
            let id = s(a, "id")?;
            let mut st = load_state(&id)?;
            let parts = a["parts"].as_object().ok_or("parts 는 {부위: {...}}")?;
            for (p, v) in parts {
                let op = v["연산자"].as_str().unwrap_or("");
                if !["덩어리", "관", "판"].contains(&op) {
                    return Err(format!("{} 의 연산자는 덩어리|관|판 중 하나", p));
                }
                if let Some(c) = v["분류"].as_str() {
                    if !["정체성", "스타일", "불확실", "오류", "충돌"].contains(&c) {
                        return Err(format!("{} 의 분류는 정체성|스타일|불확실|오류|충돌 중 하나", p));
                    }
                }
            }
            st["설계도"] = a["parts"].clone();
            save_state(&id, &st)?;
            Ok(("PASS".into(), json!({"설계도": st["설계도"]})))
        }
        "act_fit" => {
            let id = s(a, "id")?;
            let mut st = load_state(&id)?;
            if st["막힘"].as_bool().unwrap_or(false) {
                return Ok(("FAIL".into(), json!({"이유": "관문 FAIL 이 한도에 닿아 행동이 막혔다: memory_lessons 로 조사, act_blueprint 고친 뒤 episode_reset_budget"})));
            }
            let td = st["과제"].as_str().unwrap().to_string();
            let fr = Frame::load(&format!("{}/meta.json", td))?;
            let m = masks(&format!("{}/drawn_all.npz", td))?;
            let mut kinds: BTreeMap<String, Kind> = BTreeMap::new();
            if let Some(bp) = st["설계도"].as_object() {
                for (p, v) in bp {
                    kinds.insert(p.clone(), match v["연산자"].as_str().unwrap_or("") { "관" => Kind::Tube, "판" => Kind::Plate, _ => Kind::Blob });
                }
            }
            let rules = crate::anatomy::load("rules/anatomy_rules.json").ok();
            let (ells, info, fitted) = crate::fit::fit_all(&fr, &m, 0.015, 30, rules.as_ref(), None, Some(&kinds))?;
            let mesh = crate::fit::assemble_smooth(&ells, 0.01, 0.03);
            let obj = format!("{}/merged.obj", ep_dir(&id));
            crate::mesh::write_obj(&obj, &mesh)?;
            std::fs::write(format!("{}/fit_insts.json", ep_dir(&id)), serde_json::to_string(&crate::fit::insts_to_json(&fitted)).unwrap()).map_err(|e| e.to_string())?;
            st["결과"] = json!(obj);
            save_state(&id, &st)?;
            Ok(("PASS".into(), json!({"OBJ": obj, "부위": info})))
        }
        "verify_score" | "verify_gate" => {
            let id = s(a, "id")?;
            let mut st = load_state(&id)?;
            let td = st["과제"].as_str().unwrap().to_string();
            let obj = st["결과"].as_str().ok_or("act_fit 먼저")?.to_string();
            let fr = Frame::load(&format!("{}/meta.json", td))?;
            let gt = std::path::Path::new(&format!("{}/prims.json", td)).exists();
            let truth = masks(&format!("{}/{}", td, if gt { "truth_all.npz" } else { "drawn_all.npz" }))?;
            let prims = if gt { Some(crate::score::load_prims(&format!("{}/prims.json", td))?) } else { None };
            let sc = crate::score::score(&fr, &obj, &truth, prims.as_deref(), None)?;
            if name == "verify_score" {
                return Ok(("UNKNOWN".into(), sc));
            }
            // 관문(기준 고정): 몸 수 1, 해부 위반 0, 실루엣 평균 ≥ 0.93
            let rules = crate::anatomy::load("rules/anatomy_rules.json")?;
            let iv: Value = serde_json::from_str(&std::fs::read_to_string(format!("{}/fit_insts.json", ep_dir(&id))).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
            let an = crate::anatomy::check(&crate::fit::insts_from_json(&iv), &rules);
            let sil = (sc["실루엣"]["front"].as_f64().unwrap_or(0.0) + sc["실루엣"]["side"].as_f64().unwrap_or(0.0)) / 2.0;
            let checks = json!({"몸_수_1": sc["몸_수"] == 1, "해부_위반_0": an["위반"] == 0, "실루엣_평균_0.93": sil >= 0.93});
            let pass = checks.as_object().unwrap().values().all(|v| v == true);
            let n = st["시도"]["형상"].as_u64().unwrap_or(0) + if pass { 0 } else { 1 };
            st["시도"]["형상"] = json!(n);
            st["막힘"] = json!(!pass && n >= FAIL_LIMIT);
            st["마지막_판정"] = json!(if pass { "PASS" } else { "FAIL" });
            save_state(&id, &st)?;
            let mut r = json!({"관문": "형상", "검사": checks, "실루엣_평균": (sil * 1e4).round() / 1e4, "해부": {"위반": an["위반"], "주의": an["주의"]}, "FAIL_횟수": n});
            if st["막힘"] == true {
                r["다음"] = json!("행동이 막혔다: memory_lessons 로 조사하고 설계도를 고친 뒤 episode_reset_budget");
            }
            Ok((if pass { "PASS" } else { "FAIL" }.into(), r))
        }
        "verify_anatomy" => {
            let id = s(a, "id")?;
            let iv: Value = serde_json::from_str(&std::fs::read_to_string(format!("{}/fit_insts.json", ep_dir(&id))).map_err(|_| "act_fit 먼저".to_string())?).map_err(|e| e.to_string())?;
            let r = crate::anatomy::check(&crate::fit::insts_from_json(&iv), &crate::anatomy::load("rules/anatomy_rules.json")?);
            Ok((if r["위반"].as_u64().unwrap_or(0) > 0 { "FAIL" } else { "PASS" }.into(), r))
        }
        "verify_trace" => crate::trace::check(a).map(|(v, b, _)| (v, b)),
        "loop_next" => crate::loopeng::next(a).map(|(v, b, _)| (v, b)),
        "loop_report" => crate::loopeng::report(a).map(|(v, b, _)| (v, b)),
        "judge" => judge(a["runs"].as_array().ok_or("runs 는 목록")?),
        "memory_lessons" => {
            let q = a["단어"].as_str().unwrap_or("");
            let txt = std::fs::read_to_string("docs/교훈.jsonl").unwrap_or_default();
            let hits: Vec<Value> = txt.lines().filter(|l| q.is_empty() || l.contains(q)).filter_map(|l| serde_json::from_str(l).ok()).take(8).collect();
            Ok(("UNKNOWN".into(), json!({"교훈": hits})))
        }
        o => Err(format!("모르는 도구 {}", o)),
    }
}

/// 2D 연결 조각 수(4 이웃, 30px 이상).
fn pieces(m: &Mask2) -> usize {
    let mut seen = vec![false; m.d.len()];
    let mut n = 0;
    for i in 0..m.d.len() {
        if !m.d[i] || seen[i] {
            continue;
        }
        let mut st = vec![i];
        seen[i] = true;
        let mut size = 0;
        while let Some(j) = st.pop() {
            size += 1;
            let (r, c) = (j / m.w, j % m.w);
            for (dr, dc) in [(0i64, 1i64), (1, 0), (0, -1), (-1, 0)] {
                let (a2, b2) = (r as i64 + dr, c as i64 + dc);
                if a2 >= 0 && b2 >= 0 && (a2 as usize) < m.h && (b2 as usize) < m.w {
                    let k = a2 as usize * m.w + b2 as usize;
                    if m.d[k] && !seen[k] {
                        seen[k] = true;
                        st.push(k);
                    }
                }
            }
        }
        if size >= 30 {
            n += 1;
        }
    }
    n
}

/// 판단 모음(파이썬 harness/llm_aids.judge 와 같은 규칙).
fn judge(runs: &[Value]) -> Result<(String, Value), String> {
    let runs: Vec<&Value> = runs.iter().filter(|r| r["답"].as_object().map(|m| !m.is_empty()).unwrap_or(false)).collect();
    let mut items: Vec<String> = runs.iter().flat_map(|r| r["답"].as_object().unwrap().keys().cloned()).collect();
    items.sort();
    items.dedup();
    let mut fams: Vec<String> = runs.iter().map(|r| r["가족"].as_str().unwrap_or("").to_string()).collect();
    fams.sort();
    fams.dedup();
    let mut res = serde_json::Map::new();
    let mut fam_major: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let major = |xs: &[String]| -> (String, f64) {
        let mut c: BTreeMap<&str, usize> = BTreeMap::new();
        for x in xs { *c.entry(x).or_default() += 1; }
        let (k, n) = c.iter().max_by_key(|(_, n)| **n).map(|(k, n)| (k.to_string(), *n)).unwrap_or_default();
        (k, n as f64 / xs.len().max(1) as f64)
    };
    for it in &items {
        let ans: Vec<String> = runs.iter().filter_map(|r| r["답"][it].as_str().map(String::from)).collect();
        let (mj, share) = major(&ans);
        let mut flip: f64 = 0.0;
        let mut fm = serde_json::Map::new();
        for f in &fams {
            let fa: Vec<&&Value> = runs.iter().filter(|r| r["가족"] == f.as_str() && r["답"][it].is_string()).collect();
            let a_: Vec<&str> = fa.iter().filter(|r| r["순서"] == "A").map(|r| r["답"][it].as_str().unwrap()).collect();
            let b_: Vec<&str> = fa.iter().filter(|r| r["순서"] == "B").map(|r| r["답"][it].as_str().unwrap()).collect();
            if !a_.is_empty() && !b_.is_empty() {
                let d = a_.iter().flat_map(|x| b_.iter().map(move |y| (x != y) as u8 as f64)).sum::<f64>() / (a_.len() * b_.len()) as f64;
                flip = flip.max(d);
            }
            let fx: Vec<String> = fa.iter().map(|r| r["답"][it].as_str().unwrap().to_string()).collect();
            if !fx.is_empty() {
                let (m2, _) = major(&fx);
                fam_major.entry(f.clone()).or_default().push(m2.clone());
                fm.insert(f.clone(), json!(m2));
            }
        }
        let agree = fm.values().map(|v| v.to_string()).collect::<std::collections::BTreeSet<_>>().len() <= 1;
        res.insert(it.clone(), json!({"다수": mj, "재현율": share, "순서_뒤집힘": flip, "가족별": fm, "판정": if share >= 0.8 && flip <= 0.2 && agree { "확정" } else { "UNKNOWN" }}));
    }
    let kap = if fams.len() >= 2 {
        let (a_, b_) = (&fam_major[&fams[0]], &fam_major[&fams[1]]);
        let n = a_.len().min(b_.len());
        if n == 0 { None } else {
            let po = (0..n).filter(|&i| a_[i] == b_[i]).count() as f64 / n as f64;
            let mut cats: Vec<&String> = a_.iter().chain(b_.iter()).collect();
            cats.sort();
            cats.dedup();
            let pe: f64 = cats.iter().map(|k| (a_.iter().filter(|x| x == k).count() as f64 / n as f64) * (b_.iter().filter(|x| x == k).count() as f64 / n as f64)).sum();
            Some(if pe >= 1.0 { 1.0 } else { (po - pe) / (1.0 - pe) })
        }
    } else { None };
    let all_ok = res.values().all(|v| v["판정"] == "확정");
    let verdict = if kap.map(|k| k < 0.6).unwrap_or(false) { "UNKNOWN" } else if all_ok { "PASS" } else { "UNKNOWN" };
    Ok((verdict.into(), json!({"가족_카파": kap, "문항": res})))
}

/// stdio JSON-RPC 2.0 서버(줄마다 메시지 하나).
pub fn serve() {
    // 도구가 rules/·docs/·episodes/ 를 저장소 뿌리 기준으로 쓴다. 띄운 곳이 뿌리가 아니면 MH_ROOT, 없으면 바이너리 위치(rust/target/release)에서 찾는다
    if !std::path::Path::new("rules/anatomy_rules.json").exists() {
        let root = std::env::var("MH_ROOT").ok().map(std::path::PathBuf::from).or_else(|| {
            std::env::current_exe().ok().and_then(|e| e.ancestors().find(|a| a.join("rules/anatomy_rules.json").exists()).map(|a| a.to_path_buf()))
        });
        if let Some(r) = root {
            let _ = std::env::set_current_dir(r);
        }
    }
    let stdin = std::io::stdin();
    let mut out = std::io::stdout();
    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let Ok(req) = serde_json::from_str::<Value>(&line) else { continue };
        let id = req.get("id").cloned();
        let method = req["method"].as_str().unwrap_or("");
        let result: Option<Result<Value, (i64, String)>> = match method {
            "initialize" => Some(Ok(json!({
                "protocolVersion": req["params"]["protocolVersion"].as_str().unwrap_or("2025-06-18"),
                "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
                "serverInfo": {"name": "plastor", "version": env!("CARGO_PKG_VERSION")},
                "instructions": RULES_TEXT}))),
            "ping" => Some(Ok(json!({}))),
            "tools/list" => Some(Ok(json!({"tools": tools()}))),
            "prompts/list" => Some(Ok(json!({"prompts": [{"name": "하네스_규칙", "description": "모델링 에피소드를 시작할 때 읽는 하네스 규칙"}]}))),
            "prompts/get" => Some(Ok(json!({"description": "하네스 규칙", "messages": [{"role": "user", "content": {"type": "text", "text": RULES_TEXT}}]}))),
            "resources/list" => Some(Ok(json!({"resources": [{"uri": "harness://rules", "name": "하네스 규칙", "mimeType": "text/plain"}, {"uri": "harness://anatomy", "name": "해부 규칙 사전", "mimeType": "application/json"}]}))),
            "resources/read" => {
                let uri = req["params"]["uri"].as_str().unwrap_or("");
                let text = if uri == "harness://anatomy" { std::fs::read_to_string("rules/anatomy_rules.json").unwrap_or_default() } else { RULES_TEXT.to_string() };
                Some(Ok(json!({"contents": [{"uri": uri, "mimeType": "text/plain", "text": text}]})))
            }
            "tools/call" => {
                let name = req["params"]["name"].as_str().unwrap_or("").to_string();
                let args = req["params"]["arguments"].clone();
                let t = Instant::now();
                let r = call(&name, &if args.is_null() { json!({}) } else { args.clone() });
                let (verdict, body, is_err) = match r {
                    Ok((v, b)) => (v, b, false),
                    Err(e) => ("ERROR".to_string(), json!({"이유": e}), true),
                };
                trace(args["id"].as_str().unwrap_or(""), &name, &args, &verdict, t.elapsed().as_millis());
                let text = serde_json::to_string(&json!({"판정": verdict, "요약": body})).unwrap();
                Some(Ok(json!({"content": [{"type": "text", "text": text}], "isError": is_err})))
            }
            m if m.starts_with("notifications/") => None,
            _ => Some(Err((-32601, format!("모르는 메서드 {}", method)))),
        };
        if let (Some(r), Some(id)) = (result, id) {
            let msg = match r {
                Ok(v) => json!({"jsonrpc": "2.0", "id": id, "result": v}),
                Err((c, m)) => json!({"jsonrpc": "2.0", "id": id, "error": {"code": c, "message": m}}),
            };
            let _ = writeln!(out, "{}", msg);
            let _ = out.flush();
        }
    }
}
