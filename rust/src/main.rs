//! mh: ModelerHarness 도구(Rust 판, docs/설계_러스트.md). 약속은 파이썬 mh_tool.py 와 같다.
//! 사용: mh <도구> '<JSON>'  → 표준출력 {"판정", "요약", "파일"}, 끝 코드 PASS 0 · FAIL 1 · UNKNOWN 2 · ERROR 3.
//! 받는 값에 좌표는 없다(파일 경로·부위 이름·설정만).
mod anatomy;
mod fit;
mod frame;
mod grid;
mod hull;
mod loopeng;
mod mcp;
mod mesh;
mod npy;
mod png;
mod scene;
mod score;
mod trace;
mod voxel;

use grid::Mask2;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::time::Instant;

fn masks(path: &str) -> Result<BTreeMap<(String, String), Mask2>, String> {
    let mut out = BTreeMap::new();
    for (k, a) in npy::read_npz(path)? {
        let mut it = k.splitn(2, '|');
        let (v, p) = (it.next().unwrap_or("").to_string(), it.next().unwrap_or("").to_string());
        if a.shape.len() != 2 {
            return Err(format!("{} 는 2차원이 아님", k));
        }
        out.insert((v, p), Mask2 { h: a.shape[0], w: a.shape[1], d: a.as_bool() });
    }
    Ok(out)
}

fn s(a: &Value, k: &str) -> Result<String, String> {
    a[k].as_str().map(|x| x.to_string()).ok_or(format!("'{}' 가 필요함", k))
}

/// 부위 헐 하나 → OBJ.
fn t_hull(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let t = Instant::now();
    let fr = frame::Frame::load(&s(a, "frame")?)?;
    let m = masks(&s(a, "masks")?)?;
    let part = s(a, "part")?;
    let mf = m.get(&("front".into(), part.clone())).ok_or("정면 트레이스 없음")?;
    let ms = m.get(&("side".into(), part.clone())).ok_or("옆 트레이스 없음")?;
    let o = hull::HullOpt {
        voxel: a["voxel"].as_f64().unwrap_or(0.008),
        smooth: a["smooth"].as_f64().unwrap_or(1.5),
        master_front: a["master"].as_str().map(|x| x == "front").unwrap_or(false),
        section_n: a["section_n"].as_f64(),
    };
    let out = s(a, "out")?;
    match hull::build_hull(&fr, mf, ms, &o) {
        Ok((mesh, mut info)) => {
            mesh::write_obj(&out, &mesh)?;
            info["걸린초"] = json!((t.elapsed().as_secs_f64() * 100.0).round() / 100.0);
            Ok(("PASS".into(), info, vec![out]))
        }
        Err(e) => Ok(("FAIL".into(), json!({"이유": e}), vec![])),
    }
}

/// OBJ 를 복셀화해 뷰마다 비추고 트레이스와 IoU. dump 를 주면 칸(npy)과 원점(json)을 쓴다(대조 시험용).
fn t_voxsil(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let t = Instant::now();
    // 메시: OBJ 또는 npy 두 개(verts float64 (n,3), faces int64 (m,3)). npy 는 실수를 그대로 넘겨 파이썬판과 칸이 같다
    let m = if let (Some(vp), Some(fp)) = (a["verts_npy"].as_str(), a["faces_npy"].as_str()) {
        let (va, fa) = (npy::read_npy(vp)?, npy::read_npy(fp)?);
        let vd = match va.data { npy::ArrData::F64(v) => v, _ => return Err("verts 는 float64".into()) };
        let fd = match fa.data { npy::ArrData::I64(v) => v, _ => return Err("faces 는 int64".into()) };
        mesh::Mesh { v: vd.chunks_exact(3).map(|c| [c[0], c[1], c[2]]).collect(), f: fd.chunks_exact(3).map(|c| [c[0] as u32, c[1] as u32, c[2] as u32]).collect() }
    } else {
        mesh::load_obj(&s(a, "obj")?)?
    };
    let fr = a["frame"].as_str().map(frame::Frame::load).transpose()?;
    let voxel = a["voxel"].as_f64().unwrap_or(0.01);
    let (occ, lo) = voxel::voxelize(&m, voxel);
    let t_vox = t.elapsed().as_secs_f64();
    let mut info = json!({"칸": occ.d.iter().filter(|&&x| x).count(), "격자": occ.n, "원점": lo, "실루엣": {}});
    let mut files = vec![];
    if let Some(d) = a["dump"].as_str() {
        npy::write_npy(&format!("{}_occ.npy", d), &npy::Arr { shape: occ.n.to_vec(), data: npy::ArrData::Bool(occ.d.clone()) })?;
        files.push(format!("{}_occ.npy", d));
    }
    if let Some(mp) = a["masks"].as_str() {
        let mk = masks(mp)?;
        let parts: Option<Vec<String>> = a["parts"].as_array().map(|v| v.iter().filter_map(|x| x.as_str().map(String::from)).collect());
        let fr = fr.as_ref().ok_or("masks 를 주면 frame 도 필요함")?;
        for view in ["front", "side"] {
            let mut refm: Option<Mask2> = None;
            for ((v, p), mm) in &mk {
                if v != view || parts.as_ref().map(|ps| !ps.contains(p)).unwrap_or(false) {
                    continue;
                }
                let r = refm.get_or_insert_with(|| Mask2::new(mm.h, mm.w));
                for (x, y) in r.d.iter_mut().zip(&mm.d) {
                    *x |= *y;
                }
            }
            if let Some(r) = refm {
                if r.count() > 0 {
                    let pm = voxel::project(&occ, lo, voxel, fr, view, r.h, r.w);
                    info["실루엣"][view] = json!((grid::iou(&pm, &r) * 1e4).round() / 1e4);
                }
            }
        }
    }
    info["걸린초"] = json!({"복셀화": (t_vox * 100.0).round() / 100.0, "전체": (t.elapsed().as_secs_f64() * 100.0).round() / 100.0});
    Ok(("PASS".into(), info, files))
}

/// npy(행·열·RGB uint8) → PNG. Blender 없이.
fn t_png(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let arr = npy::read_npy(&s(a, "npy")?)?;
    if arr.shape.len() != 3 || arr.shape[2] < 3 {
        return Err("(행, 열, 3) 배열이어야 함".into());
    }
    let (h, w, c) = (arr.shape[0], arr.shape[1], arr.shape[2]);
    let src = match arr.data { npy::ArrData::U8(v) => v, _ => return Err("uint8 이어야 함".into()) };
    let rgb: Vec<u8> = (0..h * w).flat_map(|i| [src[i * c], src[i * c + 1], src[i * c + 2]]).collect();
    let out = s(a, "out")?;
    png::write_rgb(&out, w, h, &rgb)?;
    Ok(("PASS".into(), json!({"크기": [h, w]}), vec![out]))
}

/// 채점(파이썬 bench/m0.py score 와 같은 항목). {frame, obj, truth(npz), prims?(json), ref_parts?}
fn t_score(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let fr = frame::Frame::load(&s(a, "frame")?)?;
    let truth = masks(&s(a, "truth")?)?;
    let prims = match a["prims"].as_str() { Some(p) => Some(score::load_prims(p)?), None => None };
    let rp: Option<Vec<String>> = a["ref_parts"].as_array().map(|v| v.iter().filter_map(|x| x.as_str().map(String::from)).collect());
    let rp2: Option<Vec<&str>> = rp.as_ref().map(|v| v.iter().map(|x| x.as_str()).collect());
    let r = score::score(&fr, &s(a, "obj")?, &truth, prims.as_deref(), rp2.as_deref())?;
    Ok(("UNKNOWN".into(), r, vec![]))
}

/// 3D 정답 크리처 과제 하나 만들기(생성기 v2). {out, seed, inject?: none|side_height|twin}
fn t_scene(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let out = s(a, "out")?;
    let r = scene::make_task(&out, a["seed"].as_u64().ok_or("seed 가 필요함")?, a["inject"].as_str().unwrap_or("none"))?;
    Ok(("PASS".into(), r, vec![out]))
}

/// 파일 지문(FNV-1a 64). 묶음 재현 확인용.
fn fnv(path: &str) -> Result<String, String> {
    let b = std::fs::read(path).map_err(|e| format!("{}: {}", path, e))?;
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for x in b {
        h ^= x as u64;
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    Ok(format!("{:016x}", h))
}

/// v2 과제 묶음: {out, prefix, start, count}. 씨앗 start..start+count, 짝수 번째는 오류 없음, 홀수 번째는 side_height·twin 번갈아.
fn t_bundle(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let out = s(a, "out")?;
    let prefix = a["prefix"].as_str().unwrap_or("t");
    let start = a["start"].as_u64().ok_or("start 가 필요함")?;
    let count = a["count"].as_u64().unwrap_or(12);
    let mut list = Vec::new();
    for i in 0..count {
        let seed = start + i;
        let inject = if i % 2 == 0 { "none" } else if (i / 2) % 2 == 0 { "side_height" } else { "twin" };
        let name = format!("{}_{}", prefix, seed);
        let d = format!("{}/{}", out, name);
        scene::make_task(&d, seed, inject)?;
        let fp: Vec<String> = ["drawing.npy", "drawn_all.npz", "truth_all.npz", "prims.json", "gt.obj"].iter().map(|f| fnv(&format!("{}/{}", d, f))).collect::<Result<_, _>>()?;
        list.push(json!({"과제": name, "씨앗": seed, "오류_주입": inject, "지문": fp.join("-")}));
    }
    let man = json!({"묶음": prefix, "과제": list});
    std::fs::write(format!("{}/{}_목록.json", out, prefix), serde_json::to_string_pretty(&man).unwrap()).map_err(|e| e.to_string())?;
    Ok(("PASS".into(), json!({"과제_수": count}), vec![out]))
}

/// 원형 연산자 맞추기(루프 항목 4). {frame, masks, out(폴더), voxel?(헐 초기값 칸, 0.015), iters?(30)} → <out>/merged.obj, fit.json
fn t_fit(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let t = Instant::now();
    let fr = frame::Frame::load(&s(a, "frame")?)?;
    let m = masks(&s(a, "masks")?)?;
    let out = s(a, "out")?;
    std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
    // 해부 규칙 벌점(항목 4b): 기본 켬. 처음 재판정 FAIL(부피 −0.025)은 규칙 탓이 아니라 남아 있던 '뷰 세로 이동' 코드 탓이었다.
    // 그 코드를 끈 뒤 확인 과제 부피 +0.0045·몸 1 이 12/12(PASS). 끄려면 "rules": ""
    let rp = a["rules"].as_str().map(String::from).unwrap_or_else(|| "rules/anatomy_rules.json".into());
    let rules = if rp.is_empty() { None } else { Some(anatomy::load(&rp)?) };
    // 정면 깊이 근거(항목 4d): 그림 전체 크기 float64 npy(값 클수록 가까움, 0 = 없음)
    let depth = match a["depth_front"].as_str() {
        Some(p) => match npy::read_npy(p)?.data { npy::ArrData::F64(v) => Some(v), _ => return Err("depth_front 는 float64".into()) },
        None => None,
    };
    let (ells, mut info, fitted) = fit::fit_all(&fr, &m, a["voxel"].as_f64().unwrap_or(0.015), a["iters"].as_u64().unwrap_or(30) as usize, rules.as_ref(), depth.as_ref(), None)?;
    std::fs::write(format!("{}/fit_insts.json", out), serde_json::to_string(&fit::insts_to_json(&fitted)).unwrap()).map_err(|e| e.to_string())?;
    // 이음: blend > 0 이면 부위끼리 부드러운 합집합(항목 4c), 0 이면 딱딱한 합집합
    // 기본 0.03H(항목 4c PASS: 확인 과제 부피 −0.0002·거칠기 2.71 → 2.00°)
    let blend = a["blend"].as_f64().unwrap_or(0.03);
    let mesh = if blend > 0.0 { fit::assemble_smooth(&ells, 0.01, blend) } else { fit::assemble(&ells, 0.01) };
    let obj = format!("{}/merged.obj", out);
    mesh::write_obj(&obj, &mesh)?;
    let pj: Vec<Value> = ells.iter().map(|(p, e)| json!({"part": p, "c": e.c, "r": e.r})).collect();
    std::fs::write(format!("{}/fit_prims.json", out), serde_json::to_string(&pj).unwrap()).map_err(|e| e.to_string())?;
    info["_도형_수"] = json!(ells.len());
    info["_걸린초"] = json!((t.elapsed().as_secs_f64() * 10.0).round() / 10.0);
    std::fs::write(format!("{}/fit.json", out), serde_json::to_string_pretty(&info).unwrap()).map_err(|e| e.to_string())?;
    Ok(("PASS".into(), info, vec![obj]))
}

/// 해부 검사(항목 4b). {insts(fit_insts.json), rules?}
fn t_anatomy(a: &Value) -> Result<(String, Value, Vec<String>), String> {
    let v: Value = serde_json::from_str(&std::fs::read_to_string(s(a, "insts")?).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    let rules = anatomy::load(a["rules"].as_str().unwrap_or("rules/anatomy_rules.json"))?;
    let r = anatomy::check(&fit::insts_from_json(&v), &rules);
    let verdict = if r["위반"].as_u64().unwrap_or(0) > 0 { "FAIL" } else { "PASS" };
    Ok((verdict.into(), r, vec![]))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(|x| x == "mcp").unwrap_or(false) {
        mcp::serve();
        return;
    }
    let tools: [(&str, &str); 12] = [
        ("loop_next", "분기 루프 엔진: 지금 할 행동 하나(loop/plan.json). {plan?, 사용량?}"),
        ("loop_report", "분기 루프 엔진에 보고: 기준·구현_끝·진단·조사·가설·추적_끝·전제_바뀜 등. 판정은 엔진이 기준 명령을 돌려서. {항목, 종류, ...}"),
        ("trace_check", "추적 검사(docs/추적_체계.md): 조사 → 결정 → 설계 → 구현 → 시험 증거. 누락·충돌·미구현·증거 낡음이면 FAIL. {항목?}"),
        ("trace_verify", "증거 실행: 채택 항목에 걸린 시험을 실제로 돌려 trace/evidence.jsonl 에. {id?, 항목?}"),
        ("anatomy", "해부 규칙 검사: 맞춘 도형(fit_insts.json)을 rules/anatomy_rules.json 으로. 위반 있으면 FAIL. {insts, rules?}"),
        ("fit", "원형 연산자 맞추기(덩어리·관·판) + SDF 조립 → merged.obj. {frame, masks, out, voxel?, iters?}"),
        ("bundle", "v2 과제 묶음(짝수 번째 오류 없음, 홀수 번째 side_height·twin 번갈아) + 지문 목록. {out, prefix, start, count}"),
        ("scene", "3D 정답 크리처 과제(머리·몸통·다리·꼬리·뿔·귀, 정면·옆·뒤, 오류 주입). {out, seed, inject?}"),
        ("png", "npy(행·열·RGB uint8) → PNG. {npy, out}"),
        ("score", "채점: 실루엣·부피·몸 수·거칠기·3/4 폭 비·부위·랜드마크. {frame, obj, truth, prims?, ref_parts?}"),
        ("hull", "부위 비주얼 헐 → OBJ. {frame, masks, part, out, voxel?, smooth?, master?, section_n?}"),
        ("voxsil", "OBJ 복셀화 + 뷰별 실루엣 IoU. {frame, obj, masks?, parts?, voxel?, dump?}"),
    ];
    if args.len() < 2 || args[1] == "list" {
        let v: Vec<Value> = tools.iter().map(|(n, d)| json!({"이름": n, "설명": d})).collect();
        println!("{}", serde_json::to_string_pretty(&json!({"도구": v})).unwrap());
        return;
    }
    let a: Value = match args.get(2).map(|x| serde_json::from_str(x)) {
        Some(Ok(v)) => v,
        _ => json!({}),
    };
    let r = match args[1].as_str() {
        "hull" => t_hull(&a),
        "voxsil" => t_voxsil(&a),
        "png" => t_png(&a),
        "score" => t_score(&a),
        "scene" => t_scene(&a),
        "bundle" => t_bundle(&a),
        "fit" => t_fit(&a),
        "anatomy" => t_anatomy(&a),
        "trace_check" => trace::check(&a),
        "loop_next" => loopeng::next(&a),
        "loop_report" => loopeng::report(&a),
        "trace_verify" => trace::verify(&a),
        o => Err(format!("모르는 도구 {}", o)),
    };
    let (verdict, summ, files) = r.unwrap_or_else(|e| ("ERROR".into(), json!({"이유": e}), vec![]));
    println!("{}", serde_json::to_string(&json!({"판정": verdict, "요약": summ, "파일": files})).unwrap());
    std::process::exit(match verdict.as_str() {
        "PASS" => 0,
        "FAIL" => 1,
        "UNKNOWN" => 2,
        _ => 3,
    });
}
