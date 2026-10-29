//! 추적(docs/추적_체계.md): R-035
//! 분기 루프 엔진(루프 항목 4g, 사용자 "러스트 자체를 비선형 분기 조건부 루프 엔지니어링처럼"). docs/루프_작업목록.md 의 분기 규칙을 상태 기계로 둔다.
//! LLM 은 loop_next 가 준 행동 하나만 하고 loop_report 로 알린다. 판정은 엔진이 기준 명령을 직접 돌린 끝 코드로만(LLM 이 적은 판정은 무시),
//! 완료는 추적 관문(trace_check {항목}) PASS 가 조건. 비선형: 선행 미완 건너뜀, 보류 항목은 '깨우는_항목'이 완료되면 다시 열림, '전제_바뀜'으로 순서 바꿈.
use serde_json::{json, Value};
use std::io::Write;

const PLAN: &str = "loop/plan.json";
const MAX_TRY: u64 = 2;

fn now() -> u64 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn load(p: &str) -> Result<Value, String> {
    serde_json::from_str(&std::fs::read_to_string(p).map_err(|e| format!("{} 못 읽음: {}", p, e))?).map_err(|e| format!("{} JSON 오류: {}", p, e))
}

fn save(p: &str, v: &Value) -> Result<(), String> {
    std::fs::write(p, serde_json::to_string_pretty(v).unwrap()).map_err(|e| e.to_string())
}

fn log(p: &str, rec: Value) {
    let lp = std::path::Path::new(p).with_file_name("log.jsonl");
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(lp) {
        let _ = writeln!(f, "{}", json!({"유닉스초": now(), "기록": rec}));
    }
}

fn strs(v: &Value) -> Vec<String> {
    v.as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default()
}

fn verdict_of(code: i32) -> &'static str {
    match code { 0 => "PASS", 1 => "FAIL", 2 => "UNKNOWN", _ => "ERROR" }
}

/// 지금 할 항목: 진행 중이 있으면 그것, 없으면 선행이 다 완료인 첫 대기(진행으로 바꿈).
fn pick(items: &mut [Value]) -> Option<usize> {
    if let Some(i) = items.iter().position(|it| it["상태"] == "진행") {
        return Some(i);
    }
    let done: Vec<String> = items.iter().filter(|it| it["상태"] == "완료").map(|it| it["id"].as_str().unwrap_or("").to_string()).collect();
    let i = items.iter().position(|it| it["상태"] == "대기" && strs(&it["선행"]).iter().all(|d| done.contains(d)))?;
    items[i]["상태"] = json!("진행");
    if items[i]["단계"].is_null() {
        items[i]["단계"] = json!(if strs(&items[i]["기준"]).is_empty() { "기준_필요" } else { "구현" });
    }
    Some(i)
}

fn action(it: &Value) -> (String, String) {
    let st = it["단계"].as_str().unwrap_or("구현");
    let msg = match st {
        "기준_필요" => "기준부터 적는다(돌리기 전): 끝 코드 0 = PASS 인 기준 명령(시험 스크립트)을 만들고 loop_report {종류: 기준, 명령: [...]}",
        "구현" => "구현한다. 끝나면 loop_report {종류: 구현_끝}. 엔진이 기준 명령을 직접 돌려 판정한다(보고에 적은 판정은 무시)",
        "진단" => "FAIL 원인을 진단한다. loop_report {종류: 진단, 진단, 원인_앎: true|false}. 원인을 알면 한 번에 하나만 바꿔 다시",
        "조사" => "조사한다(웹 3번까지, 논문·기존 도구 먼저). loop_report {종류: 조사, 내용}",
        "가설" => "반증 조건 있는 가설 하나. loop_report {종류: 가설, 가설, 반증}",
        "마지막_시도" => "가설대로 한 번 더 구현. loop_report {종류: 구현_끝}. 또 PASS 가 아니면 보류",
        "환경_고치기" => "ERROR: 환경·코드를 한 번 고친다. loop_report {종류: 구현_끝}. 또 ERROR 면 보류",
        "판정_수단" => "UNKNOWN: 판정 수단(검사기·합성 정답)을 먼저 만든다. loop_report {종류: 기준_고침, 이유, 명령?} 또는 {종류: 보류_요청, 이유, 단서}",
        "추적_채우기" => "기준은 PASS 인데 추적 관문이 PASS 가 아니다: 장부(trace/registry.json)에 이 자리 항목을 적고 표지·mh trace_verify. 끝나면 loop_report {종류: 추적_끝}",
        "뒤에서_돌림" => "뒤에서 도는 계산을 기다린다(알림이 깨움). 끝나면 loop_report {종류: 뒤_끝}",
        _ => "알 수 없는 단계",
    };
    (st.to_string(), msg.to_string())
}

/// 다음 행동 하나. {plan?, 사용량?: {주간, 다섯시간}}
pub fn next(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let p = a["plan"].as_str().unwrap_or(PLAN).to_string();
    // 분기 규칙 0: 사용량
    let (wk, h5) = (a["사용량"]["주간"].as_f64().unwrap_or(0.0), a["사용량"]["다섯시간"].as_f64().unwrap_or(0.0));
    if wk >= 98.0 {
        return Ok(("UNKNOWN".into(), json!({"행동": "멈춤", "지시": "주간 사용량 ≥ 98%: 하던 일 커밋, 루프 멈춤, 한 줄 보고"}), vec![]));
    }
    if wk >= 95.0 || h5 >= 90.0 {
        return Ok(("UNKNOWN".into(), json!({"행동": "잠", "지시": "사용량 문턱: 새 일 시작 금지, 돌던 계산만 거두고 5시간 초기화까지 잠"}), vec![]));
    }
    let mut plan = load(&p)?;
    let items = plan["항목"].as_array_mut().ok_or("plan 에 항목 배열 없음")?;
    let Some(i) = pick(items) else {
        let waiting: Vec<Value> = items.iter().filter(|it| it["상태"] == "대기").map(|it| json!({"id": it["id"], "선행": it["선행"]})).collect();
        let r = if waiting.is_empty() { json!({"행동": "끝", "지시": "남은 항목 없음"}) } else { json!({"행동": "막힘", "지시": "선행이 끝나지 않은(보류된) 항목만 남음: 선행을 다시 열거나 전제_바뀜으로 순서를 바꾼다", "대기": waiting}) };
        return Ok(("UNKNOWN".into(), r, vec![]));
    };
    let (st, msg) = action(&items[i]);
    let out = json!({"항목": items[i]["id"], "제목": items[i]["제목"], "행동": st, "지시": msg, "시도": items[i]["시도"].as_u64().unwrap_or(0), "기준": items[i]["기준"]});
    save(&p, &plan)?;
    Ok(("UNKNOWN".into(), out, vec![]))
}

fn crit_fps(it: &Value) -> Value {
    let mut m = serde_json::Map::new();
    for c in strs(&it["기준"]) {
        m.insert(c.clone(), json!(crate::trace::file_fp(&c)));
    }
    Value::Object(m)
}

/// 기준 명령을 돌린다. 판정 하나라도 PASS 가 아니면 가장 나쁜 것(ERROR > UNKNOWN > FAIL).
fn judge_item(it: &Value) -> (String, Value) {
    let mut worst = "PASS";
    let mut rows = vec![];
    for c in strs(&it["기준"]) {
        let v = verdict_of(crate::trace::run_cmd(&c));
        let rank = |x: &str| match x { "PASS" => 0, "FAIL" => 1, "UNKNOWN" => 2, _ => 3 };
        if rank(v) > rank(worst) {
            worst = v;
        }
        rows.push(json!({"명령": c, "판정": v}));
    }
    (worst.to_string(), json!(rows))
}

fn wake(items: &mut [Value], done_id: &str) -> Vec<String> {
    let mut woke = vec![];
    for it in items.iter_mut() {
        if it["상태"] == "보류" && strs(&it["깨우는_항목"]).iter().any(|x| x == done_id) {
            it["상태"] = json!("대기");
            it["단계"] = json!("구현");
            it["시도"] = json!(0);
            it["에러"] = json!(0);
            woke.push(it["id"].as_str().unwrap_or("").to_string());
        }
    }
    woke
}

fn hold(it: &mut Value, why: &str) {
    it["상태"] = json!("보류");
    it["단계"] = Value::Null;
    it["보류_이유"] = json!(why);
}

/// 보고. {plan?, 항목, 종류, ...}. 판정 필드는 무시한다.
pub fn report(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let p = a["plan"].as_str().unwrap_or(PLAN).to_string();
    let mut plan = load(&p)?;
    let id = a["항목"].as_str().ok_or("'항목' 이 필요함")?.to_string();
    let kind = a["종류"].as_str().ok_or("'종류' 가 필요함")?.to_string();
    let ignored = !a["판정"].is_null();
    let items = plan["항목"].as_array_mut().ok_or("plan 에 항목 배열 없음")?;
    if kind == "전제_바뀜" {
        let why = a["이유"].as_str().unwrap_or("");
        if why.is_empty() {
            return Ok(("FAIL".into(), json!({"거부": "전제_바뀜에는 이유가 필요하다"}), vec![]));
        }
        let order = strs(&a["순서"]);
        // 적은 항목(완료 아닌 것)을 그 순서로 앞에, 나머지는 원래 순서. 진행 중이던 것은 대기로 돌려 pick 이 새 순서로 고르게
        let mut new: Vec<Value> = order.iter().filter_map(|o| items.iter().find(|it| it["id"] == o.as_str() && it["상태"] != "완료").cloned()).collect();
        let picked: Vec<Value> = new.iter().map(|it| it["id"].clone()).collect();
        new.extend(items.iter().filter(|it| !picked.contains(&it["id"])).cloned());
        for it in new.iter_mut().filter(|it| it["상태"] == "진행") {
            it["상태"] = json!("대기");
        }
        *items = new;
        log(&p, json!({"종류": "전제_바뀜", "이유": why, "순서": order}));
        save(&p, &plan)?;
        return Ok(("PASS".into(), json!({"순서": plan["항목"].as_array().unwrap().iter().map(|it| it["id"].clone()).collect::<Vec<_>>()}), vec![]));
    }
    let i = items.iter().position(|it| it["id"] == id.as_str()).ok_or(format!("항목 {} 없음", id))?;
    let stage = items[i]["단계"].as_str().unwrap_or("구현").to_string();
    let refuse = |m: String| Ok(("FAIL".into(), json!({"거부": m, "지금_단계": stage}), vec![]));
    if items[i]["상태"] != "진행" {
        return refuse(format!("{} 는 진행 중이 아님(상태 {})", id, items[i]["상태"]));
    }
    let mut out = json!({});
    match (kind.as_str(), stage.as_str()) {
        ("기준", "기준_필요") | ("기준_고침", _) => {
            let cmds = strs(&a["명령"]);
            if kind == "기준_고침" && a["이유"].as_str().unwrap_or("").is_empty() {
                return refuse("기준_고침에는 이유가 필요하다(기준을 실패에 맞춰 낮추지 않는다. 시험 결함이면 그 사실을 적는다)".into());
            }
            if !cmds.is_empty() {
                if let Some(m) = cmds.iter().find(|c| !std::path::Path::new(c.as_str()).exists()) {
                    return refuse(format!("기준 명령 파일 없음: {}", m));
                }
                items[i]["기준"] = json!(cmds);
            }
            if strs(&items[i]["기준"]).is_empty() {
                return refuse("기준 명령이 비었다".into());
            }
            items[i]["기준_지문"] = crit_fps(&items[i]);
            items[i]["단계"] = json!("구현");
            if kind == "기준_고침" {
                let n = items[i]["기준_고침_수"].as_u64().unwrap_or(0) + 1;
                items[i]["기준_고침_수"] = json!(n);
            }
            out = json!({"다음": "구현"});
        }
        ("구현_끝", "구현") | ("구현_끝", "마지막_시도") | ("구현_끝", "환경_고치기") | ("추적_끝", "추적_채우기") => {
            if kind == "구현_끝" {
                // 기준 파일이 첫 판정 뒤에 바뀌었으면(이유 없이) 거부
                if items[i]["판정_수"].as_u64().unwrap_or(0) > 0 && crit_fps(&items[i]) != items[i]["기준_지문"] {
                    return refuse("기준 명령 파일이 첫 판정 뒤에 바뀌었다: loop_report {종류: 기준_고침, 이유} 로 이유를 남겨야 돌린다".into());
                }
                if items[i]["판정_수"].as_u64().unwrap_or(0) == 0 && items[i]["기준_지문"].is_null() {
                    items[i]["기준_지문"] = crit_fps(&items[i]);
                }
                let (v, rows) = judge_item(&items[i]);
                items[i]["판정_수"] = json!(items[i]["판정_수"].as_u64().unwrap_or(0) + 1);
                items[i]["마지막_판정"] = json!(v);
                out["판정"] = json!(v);
                out["기준_결과"] = rows;
                match v.as_str() {
                    "PASS" => {}
                    "FAIL" => {
                        if stage == "마지막_시도" {
                            hold(&mut items[i], "가설 뒤 한 번 더도 FAIL");
                        } else {
                            items[i]["단계"] = json!("진단");
                        }
                    }
                    "ERROR" => {
                        let n = items[i]["에러"].as_u64().unwrap_or(0) + 1;
                        items[i]["에러"] = json!(n);
                        if n >= 2 {
                            hold(&mut items[i], "ERROR 두 번");
                        } else {
                            items[i]["단계"] = json!("환경_고치기");
                        }
                    }
                    _ => items[i]["단계"] = json!("판정_수단"),
                }
                if v != "PASS" {
                    out["다음"] = items[i]["단계"].clone();
                    out["상태"] = items[i]["상태"].clone();
                    log(&p, json!({"항목": id, "종류": kind, "판정": v, "다음": out["다음"]}));
                    save(&p, &plan)?;
                    return Ok((v, out, vec![]));
                }
            }
            // 기준 PASS(또는 추적_끝) → 추적 관문
            let place = items[i]["추적_자리"].as_str().unwrap_or(&id).to_string();
            let (gv, gb, _) = crate::trace::check(&json!({"항목": place, "registry": a["registry"], "evidence": a["evidence"]}))?;
            out["추적_관문"] = json!({"판정": gv, "문제_항목": gb["문제_항목"]});
            if gv == "PASS" {
                items[i]["상태"] = json!("완료");
                items[i]["단계"] = Value::Null;
                let woke = wake(items, &id);
                out["다음"] = json!("완료");
                out["깨움"] = json!(woke);
            } else {
                items[i]["단계"] = json!("추적_채우기");
                out["다음"] = json!("추적_채우기");
            }
        }
        ("진단", "진단") => {
            let d = a["진단"].as_str().unwrap_or("");
            if d.is_empty() {
                return refuse("진단 내용이 비었다".into());
            }
            let tries = items[i]["시도"].as_u64().unwrap_or(0);
            let knows = a["원인_앎"].as_bool().unwrap_or(false);
            let mut hist = items[i]["진단_기록"].as_array().cloned().unwrap_or_default();
            hist.push(json!(d));
            items[i]["진단_기록"] = json!(hist);
            if knows && tries < MAX_TRY {
                items[i]["시도"] = json!(tries + 1);
                items[i]["단계"] = json!("구현");
            } else {
                items[i]["단계"] = json!("조사");
            }
            out = json!({"다음": items[i]["단계"], "시도": items[i]["시도"]});
        }
        ("조사", "조사") => {
            if a["내용"].as_str().unwrap_or("").is_empty() {
                return refuse("조사 내용이 비었다".into());
            }
            items[i]["조사"] = a["내용"].clone();
            items[i]["단계"] = json!("가설");
            out = json!({"다음": "가설"});
        }
        ("가설", "가설") => {
            if a["가설"].as_str().unwrap_or("").is_empty() || a["반증"].as_str().unwrap_or("").is_empty() {
                return refuse("가설에는 반증 조건이 있어야 한다".into());
            }
            items[i]["가설"] = json!({"가설": a["가설"], "반증": a["반증"]});
            items[i]["단계"] = json!("마지막_시도");
            out = json!({"다음": "마지막_시도"});
        }
        ("보류_요청", "판정_수단") => {
            hold(&mut items[i], a["이유"].as_str().unwrap_or("판정 수단 없음"));
            items[i]["단서"] = a["단서"].clone();
            out = json!({"다음": "보류"});
        }
        ("뒤에서_돌림", _) => {
            items[i]["돌아갈_단계"] = json!(stage);
            items[i]["단계"] = json!("뒤에서_돌림");
            items[i]["뒤"] = a["무엇"].clone();
            out = json!({"다음": "뒤에서_돌림"});
        }
        ("뒤_끝", "뒤에서_돌림") => {
            items[i]["단계"] = items[i]["돌아갈_단계"].clone();
            out = json!({"다음": items[i]["단계"]});
        }
        _ => return refuse(format!("지금 단계 '{}' 에서는 '{}' 보고를 받지 않는다", stage, kind)),
    }
    if ignored {
        out["무시함"] = json!("보고에 적은 판정은 쓰지 않는다(판정은 엔진이 기준 명령을 돌려서)");
    }
    log(&p, json!({"항목": id, "종류": kind, "결과": out}));
    save(&p, &plan)?;
    Ok(("PASS".into(), out, vec![]))
}
