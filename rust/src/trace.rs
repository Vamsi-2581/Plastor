//! 추적(docs/추적_체계.md): R-014
//! 추적 체계(docs/추적_체계.md): 조사 → 결정 → 설계 → 구현 → 검증을 장부(trace/registry.json)로 묶고 자동 검사한다.
//! 연결(파일 안 ID 표지)과 실제 반영(연결된 시험을 돌린 PASS 증거, 그때 파일 지문 = 지금 지문)을 따로 본다.
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::io::Write;

const REG: &str = "trace/registry.json";
const EVI: &str = "trace/evidence.jsonl";
const STATES: [&str; 4] = ["채택", "보류", "기각", "대기"];

/// 파일 지문(FNV-1a 64). 증거가 낡았는지 가르는 데만 쓴다.
fn fp(path: &str) -> Option<String> {
    let b = std::fs::read(path).ok()?;
    let mut h: u64 = 0xcbf29ce484222325;
    // 줄바꿈(CRLF↔LF) 변환만으로 증거가 낡았다고 하지 않게 CR 은 건너뛴다
    for x in b.into_iter().filter(|&c| c != 13u8) {
        h ^= x as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    Some(format!("{:016x}", h))
}

fn list(v: &Value) -> Vec<String> {
    match v {
        Value::String(s) if !s.is_empty() => vec![s.clone()],
        Value::Array(a) => a.iter().filter_map(|x| x.as_str().map(String::from)).filter(|s| !s.is_empty()).collect(),
        _ => vec![],
    }
}

/// 글 안의 ID 표지(R- + 세 자리, 앞뒤가 숫자·글자가 아님).
fn ids_in(text: &str) -> BTreeSet<String> {
    let b = text.as_bytes();
    let mut out = BTreeSet::new();
    let mut i = 0;
    while i + 5 <= b.len() {
        if b[i] == b'R' && b[i + 1] == b'-' && b[i + 2..i + 5].iter().all(|c| c.is_ascii_digit())
            && (i == 0 || !b[i - 1].is_ascii_alphanumeric())
            && (i + 5 == b.len() || !b[i + 5].is_ascii_digit())
        {
            out.insert(String::from_utf8_lossy(&b[i..i + 5]).to_string());
            i += 5;
        } else {
            i += 1;
        }
    }
    out
}

fn has_id(path: &str, id: &str) -> bool {
    std::fs::read_to_string(path).map(|t| ids_in(&t).contains(id)).unwrap_or(false)
}

fn load_registry(p: &str) -> Result<Vec<Value>, String> {
    let v: Value = serde_json::from_str(&std::fs::read_to_string(p).map_err(|e| format!("{} 못 읽음: {}", p, e))?).map_err(|e| format!("{} JSON 오류: {}", p, e))?;
    match v {
        Value::Array(a) => Ok(a),
        Value::Object(m) => Ok(m.get("항목").and_then(|x| x.as_array()).cloned().unwrap_or_default()),
        _ => Err("장부는 항목 배열".into()),
    }
}

/// 시험 파일마다 마지막 증거.
fn load_evidence(p: &str) -> BTreeMap<String, Value> {
    let mut m = BTreeMap::new();
    for l in std::fs::read_to_string(p).unwrap_or_default().lines() {
        if let Ok(v) = serde_json::from_str::<Value>(l) {
            if let Some(t) = v["시험"].as_str() {
                m.insert(t.to_string(), v);
            }
        }
    }
    m
}

fn walk(dir: &str, exts: &[&str], out: &mut Vec<String>) {
    let Ok(rd) = std::fs::read_dir(dir) else { return };
    for e in rd.flatten() {
        let p = e.path();
        let s = p.to_string_lossy().replace('\\', "/");
        if p.is_dir() {
            if !s.contains("/target") && !s.contains("/.vendor") && !s.contains("/__pycache__") {
                walk(&s, exts, out);
            }
        } else if exts.iter().any(|x| s.ends_with(x)) {
            out.push(s);
        }
    }
}

fn is_research_doc(name: &str) -> bool {
    name.ends_with(".md") && (name.starts_with("조사_") || name.ends_with("_조사.md") || name.starts_with("자유조사_"))
}

/// 장부 검사. {항목?: 루프 항목·자리 이름(그 자리 항목만 관문으로), registry?, evidence?}
pub fn check(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let reg = load_registry(a["registry"].as_str().unwrap_or(REG))?;
    let evi = load_evidence(a["evidence"].as_str().unwrap_or(EVI));
    let only = a["항목"].as_str().map(String::from);
    let mut ids = BTreeSet::new();
    let mut dup = vec![];
    for e in &reg {
        let id = e["id"].as_str().unwrap_or("").to_string();
        if !ids.insert(id.clone()) {
            dup.push(id);
        }
    }
    let state_of: BTreeMap<String, String> = reg.iter().map(|e| (e["id"].as_str().unwrap_or("").to_string(), e["상태"].as_str().unwrap_or("").to_string())).collect();
    let mut rows = vec![];
    let mut counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut n_problem = 0;
    for e in &reg {
        let id = e["id"].as_str().unwrap_or("");
        let st = e["상태"].as_str().unwrap_or("");
        let place = list(&e["자리"]);
        if let Some(o) = &only {
            if !place.iter().any(|p| p == o) {
                continue;
            }
        }
        let mut probs: Vec<String> = vec![];
        if ids_in(id).len() != 1 || id.len() != 5 {
            probs.push("형식: id 는 R- 뒤에 숫자 세 자리".into());
        }
        if dup.iter().any(|d| d == id) {
            probs.push("형식: id 겹침".into());
        }
        if !STATES.contains(&st) {
            probs.push(format!("형식: 상태 '{}' 는 채택|보류|기각|대기 가 아님", st));
        }
        if e["조사"].as_str().unwrap_or("").is_empty() {
            probs.push("형식: 조사 내용 없음".into());
        }
        if e["근거"].as_str().unwrap_or("").is_empty() {
            probs.push("형식: 근거 없음".into());
        }
        let src = list(&e["출처"]);
        if src.is_empty() {
            probs.push("형식: 출처 없음".into());
        }
        for s in &src {
            if !s.starts_with("http") && !std::path::Path::new(s).exists() {
                probs.push(format!("출처 파일 없음: {}", s));
            }
        }
        if (st == "보류" || st == "기각") && e["다시_볼_조건"].as_str().unwrap_or("").is_empty() {
            probs.push("형식: 보류·기각에 다시 볼 조건 없음".into());
        }
        if st == "대기" && place.is_empty() {
            probs.push("잊힘: 대기인데 자리(루프 항목·로드맵) 없음".into());
        }
        let (design, imp, tests) = (list(&e["설계"]), list(&e["구현"]), list(&e["시험"]));
        // 연결 검사: 어느 상태든 적힌 파일은 있어야 하고 ID 표지가 있어야 한다
        for (kind, fs) in [("설계", &design), ("구현", &imp), ("시험", &tests)] {
            for f in fs.iter() {
                if !std::path::Path::new(f).exists() {
                    probs.push(format!("연결 끊김: {} 파일 없음 {}", kind, f));
                } else if !has_id(f, id) {
                    probs.push(format!("연결 끊김: {} 에 표지 {} 없음", f, id));
                }
            }
        }
        let mut status = st.to_string();
        if st == "채택" {
            if design.is_empty() {
                probs.push("미설계: 채택인데 설계 연결 없음".into());
            }
            if imp.is_empty() {
                probs.push("미구현: 채택인데 구현 연결 없음".into());
            }
            if tests.is_empty() {
                probs.push("미검증: 채택인데 시험 연결 없음".into());
            }
            // 실제 반영: 시험마다 PASS 증거 + 그때 지문 = 지금 지문(구현·시험 파일)
            for t in &tests {
                match evi.get(t) {
                    None => probs.push(format!("증거 없음: {} 를 돌린 기록 없음(mh trace_verify)", t)),
                    Some(ev) => {
                        if ev["판정"] != "PASS" {
                            probs.push(format!("시험 FAIL: {} (끝 코드 {})", t, ev["끝코드"]));
                        }
                        for f in imp.iter().chain(std::iter::once(t)) {
                            if ev["지문"][f.as_str()].as_str() != fp(f).as_deref() {
                                probs.push(format!("증거 낡음: {} 가 시험 뒤에 바뀜(또는 그 시험 지문에 없음)", f));
                            }
                        }
                    }
                }
            }
            if probs.is_empty() {
                status = "반영됨".into();
            }
        }
        for c in list(&e["충돌"]) {
            if st == "채택" && state_of.get(&c).map(|s| s == "채택").unwrap_or(false) {
                probs.push(format!("충돌: 채택끼리 충돌 {}", c));
            }
        }
        if let Some(r) = e["대체"].as_str() {
            if st == "채택" && state_of.get(r).map(|s| s == "채택").unwrap_or(false) {
                probs.push(format!("충돌: 대체된 {} 가 아직 채택", r));
            }
        }
        if !probs.is_empty() {
            n_problem += 1;
            status = "문제".into();
        }
        *counts.entry(status.clone()).or_default() += 1;
        rows.push(json!({"id": id, "상태": st, "판정": status, "자리": place, "조사": e["조사"], "문제": probs}));
    }
    // 전체 검사일 때만: 없는 ID 표지, 장부에 없는 조사 문서
    let mut global = vec![];
    if only.is_none() {
        let mut files = vec![];
        for d in ["rust/src", "harness", "tests", "bench", "tools"] {
            walk(d, &[".rs", ".py", ".sh"], &mut files);
        }
        walk("docs", &[".md"], &mut files);
        if let Ok(rd) = std::fs::read_dir(".") {
            for e in rd.flatten() {
                let s = e.file_name().to_string_lossy().to_string();
                if s.ends_with(".py") {
                    files.push(s);
                }
            }
        }
        for f in files.iter().filter(|f| !f.ends_with("docs/추적_체계.md")) {
            for x in ids_in(&std::fs::read_to_string(f).unwrap_or_default()) {
                if !ids.contains(&x) {
                    global.push(format!("없는 ID: {} 에 {} (장부에 없음)", f, x));
                }
            }
        }
        let srcs: BTreeSet<String> = reg.iter().flat_map(|e| list(&e["출처"])).collect();
        if let Ok(rd) = std::fs::read_dir("docs") {
            for e in rd.flatten() {
                let n = e.file_name().to_string_lossy().to_string();
                if is_research_doc(&n) && !srcs.contains(&format!("docs/{}", n)) {
                    global.push(format!("등록 안 된 조사 문서: docs/{}", n));
                }
            }
        }
    }
    let pass = n_problem == 0 && global.is_empty() && !rows.is_empty();
    let verdict = if rows.is_empty() { "UNKNOWN" } else if pass { "PASS" } else { "FAIL" };
    let problems: Vec<&Value> = rows.iter().filter(|r| r["판정"] == "문제").collect();
    Ok((verdict.into(), json!({"범위": only.unwrap_or("전체".into()), "항목_수": rows.len(), "판정별": counts, "문제_항목": problems, "전체_문제": global,
        "반영됨": rows.iter().filter(|r| r["판정"] == "반영됨").map(|r| r["id"].clone()).collect::<Vec<_>>()}), vec![]))
}

/// 시험·기준 명령 하나를 돌려 끝 코드(.py 는 MH_PY, 없으면 Blender 번들 파이썬).
pub fn run_cmd(t: &str) -> i32 {
    let py = std::env::var("MH_PY").unwrap_or_else(|_| "C:/Program Files/Blender Foundation/Blender 5.2/5.2/python/bin/python.exe".into());
    let mut cmd = if t.ends_with(".py") { let mut c = std::process::Command::new(&py); c.arg(t); c } else { std::process::Command::new(t) };
    cmd.output().map(|o| o.status.code().unwrap_or(-1)).unwrap_or(-1)
}

pub fn file_fp(p: &str) -> Option<String> {
    fp(p)
}

/// 증거 실행기: 채택 항목에 걸린 시험을 실제로 돌려 끝 코드와 그때 지문을 trace/evidence.jsonl 에 남긴다.
/// {id?: [..] 또는 항목?: 자리 이름, registry?, evidence?}. 파이썬 시험은 MH_PY(없으면 Blender 번들 파이썬)로.
pub fn verify(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let reg = load_registry(a["registry"].as_str().unwrap_or(REG))?;
    let ev_path = a["evidence"].as_str().unwrap_or(EVI).to_string();
    let want = list(&a["id"]);
    let place = a["항목"].as_str();
    let mut tests: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for e in &reg {
        if e["상태"] != "채택" {
            continue;
        }
        let id = e["id"].as_str().unwrap_or("").to_string();
        if !want.is_empty() && !want.contains(&id) {
            continue;
        }
        if let Some(p) = place {
            if !list(&e["자리"]).iter().any(|x| x == p) {
                continue;
            }
        }
        for t in list(&e["시험"]) {
            tests.entry(t).or_default().extend(list(&e["구현"]));
        }
    }
    if tests.is_empty() {
        return Ok(("UNKNOWN".into(), json!({"이유": "돌릴 시험이 걸린 채택 항목이 없음"}), vec![]));
    }
    let mut out = vec![];
    let mut all = true;
    if let Some(d) = std::path::Path::new(&ev_path).parent() {
        let _ = std::fs::create_dir_all(d);
    }
    for (t, imp) in &tests {
        let t0 = std::time::Instant::now();
        let code = run_cmd(t);
        let verdict = match code { 0 => "PASS", 1 => "FAIL", 2 => "UNKNOWN", _ => "ERROR" };
        all &= code == 0;
        let mut f = serde_json::Map::new();
        for p in imp.iter().chain(std::iter::once(t)) {
            if let Some(h) = fp(p) {
                f.insert(p.clone(), json!(h));
            }
        }
        let secs = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        let rec = json!({"시험": t, "끝코드": code, "판정": verdict, "지문": f, "유닉스초": secs, "걸린초": (t0.elapsed().as_secs_f64() * 10.0).round() / 10.0});
        let mut fh = std::fs::OpenOptions::new().create(true).append(true).open(&ev_path).map_err(|e| e.to_string())?;
        writeln!(fh, "{}", rec).map_err(|e| e.to_string())?;
        out.push(json!({"시험": t, "판정": verdict, "걸린초": rec["걸린초"]}));
    }
    Ok((if all { "PASS" } else { "FAIL" }.into(), json!({"시험": out}), vec![ev_path]))
}
