//! 추적(docs/추적_체계.md): R-024
//! 해부 규칙 사전 검사·벌점(루프 항목 4b, rules/anatomy_rules.json). 맞춘 도형(Inst)에서 규칙마다 값을 재고,
//! 범위_사실 밖은 '주의', 범위_스타일 밖은 '위반'. 맞추기 손실에는 '위반' 정도만 벌점으로 더한다(스타일은 허용).
use crate::fit::{Ell, Inst};
use serde_json::{json, Value};
use std::collections::BTreeMap;

#[derive(Clone, Debug)]
pub struct Rule {
    pub id: String,
    pub parts: Vec<String>,
    pub real: [f64; 2],
    pub style: [f64; 2],
    pub why: String,
    pub conf: f64,
}

pub struct Rules {
    pub rules: Vec<Rule>,
    pub pairs: Vec<String>,
}

pub fn load(path: &str) -> Result<Rules, String> {
    let v: Value = serde_json::from_str(&std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?).map_err(|e| e.to_string())?;
    let r2 = |x: &Value| [x[0].as_f64().unwrap_or(0.0), x[1].as_f64().unwrap_or(0.0)];
    let rules = v["규칙"].as_array().ok_or("규칙 없음")?.iter().map(|r| Rule {
        id: r["id"].as_str().unwrap_or("").into(),
        parts: r["부위"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default(),
        real: r2(&r["범위_사실"]),
        style: r2(&r["범위_스타일"]),
        why: r["근거"].as_str().unwrap_or("").into(),
        conf: r["확신"].as_f64().unwrap_or(0.5),
    }).collect();
    let pairs = v["짝_부위"].as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default();
    Ok(Rules { rules, pairs })
}

fn flat(e: &Ell) -> f64 {
    let mn = e.r.iter().cloned().fold(f64::INFINITY, f64::min);
    let mx = e.r.iter().cloned().fold(0.0, f64::max);
    mn / mx.max(1e-9)
}

/// 부위별 인스턴스(짝 부위는 거울 사본까지 포함된 전체)에서 규칙 값들. 반환 [(규칙 id, 부위, 값)].
pub fn measure(parts: &BTreeMap<String, Vec<Inst>>, rules: &Rules) -> Vec<(String, String, f64)> {
    let mut out = Vec::new();
    let head: Option<Ell> = parts.get("머리").and_then(|v| v.first()).and_then(|i| i.ells().into_iter().max_by(|a, b| (a.r[0] * a.r[1] * a.r[2]).partial_cmp(&(b.r[0] * b.r[1] * b.r[2])).unwrap()));
    let horn_root_z: Option<f64> = parts.get("뿔").and_then(|v| v.iter().filter_map(|i| if let Inst::Tube { ctrl, .. } = i { Some(ctrl[0][2]) } else { None }).reduce(f64::max));
    for r in &rules.rules {
        for p in &r.parts {
            let Some(insts) = parts.get(p) else { continue };
            match r.id.as_str() {
                "덩어리_납작함" | "판_두께" => {
                    for i in insts {
                        if let Inst::Blob(es) = i {
                            for e in es {
                                out.push((r.id.clone(), p.clone(), flat(e)));
                            }
                        }
                    }
                }
                "두개골_둥글기" => {
                    if let Some(h) = &head {
                        out.push((r.id.clone(), p.clone(), h.r[0] / h.r[1].max(1e-6)));
                    }
                }
                "짝_개수" | "다리_개수" => out.push((r.id.clone(), p.clone(), insts.len() as f64)),
                "짝_대칭" => {
                    let c: Vec<([f64; 3], f64)> = insts.iter().map(|i| {
                        let es = i.ells();
                        let n = es.len().max(1) as f64;
                        let c = [0, 1, 2].map(|k| es.iter().map(|e| e.c[k]).sum::<f64>() / n);
                        (c, es.iter().map(|e| e.r[0]).sum::<f64>() / n)
                    }).collect();
                    for (a, ra) in c.iter().filter(|(c, _)| c[0] > 0.0) {
                        if let Some((b, rb)) = c.iter().filter(|(c, _)| c[0] < 0.0).min_by(|x, y| {
                            let d = |q: &[f64; 3]| (q[0] + a[0]).powi(2) + (q[1] - a[1]).powi(2) + (q[2] - a[2]).powi(2);
                            d(&x.0).partial_cmp(&d(&y.0)).unwrap()
                        }) {
                            let size = ra.max(*rb).max(0.02) * 4.0;
                            let d = ((a[0] + b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt() + (ra - rb).abs();
                            out.push((r.id.clone(), p.clone(), d / size));
                        }
                    }
                }
                "뿔_뿌리_높이" => {
                    if let Some(h) = &head {
                        for i in insts {
                            if let Inst::Tube { ctrl, .. } = i {
                                out.push((r.id.clone(), p.clone(), (ctrl[0][2] - h.c[2]) / h.r[2]));
                            }
                        }
                    }
                }
                "뿔_가늘어짐" => {
                    for i in insts {
                        if let Inst::Tube { rad, .. } = i {
                            out.push((r.id.clone(), p.clone(), rad[rad.len() - 1] / rad[0].max(1e-6)));
                        }
                    }
                }
                "뿔_굵기" => {
                    if let Some(h) = &head {
                        for i in insts {
                            if let Inst::Tube { rad, .. } = i {
                                out.push((r.id.clone(), p.clone(), rad.iter().cloned().fold(0.0, f64::max) / h.r[0]));
                            }
                        }
                    }
                }
                "귀_아래" => {
                    if let (Some(h), Some(hz)) = (&head, horn_root_z) {
                        for i in insts {
                            let es = i.ells();
                            let cz = es.iter().map(|e| e.c[2]).sum::<f64>() / es.len().max(1) as f64;
                            out.push((r.id.clone(), p.clone(), (cz - hz) / h.r[2]));
                        }
                    }
                }
                "다리_땅" => {
                    for i in insts {
                        let lo = i.ells().iter().map(|e| e.c[2] - e.r[2]).fold(f64::INFINITY, f64::min);
                        out.push((r.id.clone(), p.clone(), lo));
                    }
                }
                _ => {}
            }
        }
    }
    out
}

fn outside(x: f64, r: [f64; 2]) -> f64 {
    if x < r[0] { r[0] - x } else if x > r[1] { x - r[1] } else { 0.0 }
}

/// 검사 보고: 규칙마다 값과 판정(정상·주의·위반), 근거·확신.
pub fn check(parts: &BTreeMap<String, Vec<Inst>>, rules: &Rules) -> Value {
    let byid: BTreeMap<&str, &Rule> = rules.rules.iter().map(|r| (r.id.as_str(), r)).collect();
    let items: Vec<Value> = measure(parts, rules).into_iter().map(|(id, p, v)| {
        let r = byid[id.as_str()];
        let level = if outside(v, r.style) > 0.0 { "위반" } else if outside(v, r.real) > 0.0 { "주의" } else { "정상" };
        json!({"규칙": id, "부위": p, "값": (v * 1000.0).round() / 1000.0, "판정": level, "범위_사실": r.real, "범위_스타일": r.style,
               "근거": if level == "정상" { "".to_string() } else { r.why.clone() }, "확신": r.conf})
    }).collect();
    let viol = items.iter().filter(|x| x["판정"] == "위반").count();
    let warn = items.iter().filter(|x| x["판정"] == "주의").count();
    json!({"위반": viol, "주의": warn, "항목": items})
}

/// 맞추기 벌점(픽셀 단위로 손실에 더함): 스타일 범위 밖 정도 × 무게 × 확신. 한 부위의 인스턴스만 본다(머리·뿔 뿌리 맥락은 ctx).
pub fn penalty(part: &str, insts: &[Inst], ctx: &BTreeMap<String, Vec<Inst>>, rules: &Rules) -> f64 {
    const W: f64 = 3000.0;
    let mut m: BTreeMap<String, Vec<Inst>> = ctx.clone();
    m.insert(part.to_string(), insts.to_vec());
    let byid: BTreeMap<&str, &Rule> = rules.rules.iter().map(|r| (r.id.as_str(), r)).collect();
    measure(&m, rules).into_iter().filter(|(_, p, _)| p == part).map(|(id, _, v)| {
        let r = byid[id.as_str()];
        if id.contains("개수") { 0.0 } else { W * r.conf * outside(v, r.style) }
    }).sum()
}
