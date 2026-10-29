//! 도면 좌표틀(설계서 3절): 화면 픽셀 ↔ H 단위. 파이썬 build.Frame·harness.pack.Pack 과 같은 식(같은 연산 순서).
use serde_json::Value;

#[derive(Clone, Debug)]
pub struct Panel {
    pub center_x: f64,
    pub ground_row: f64,
    pub sign: f64,
}

#[derive(Clone, Debug)]
pub struct Frame {
    pub pp_h: f64,
    pub panels: std::collections::BTreeMap<String, Panel>,
}

impl Frame {
    /// 팩(pack.json: panels.{뷰}.center_x) 또는 trace meta(meta.json: panels.{뷰}.중심선_x) 를 읽는다.
    pub fn load(path: &str) -> Result<Frame, String> {
        let s = std::fs::read_to_string(path).map_err(|e| format!("{}: {}", path, e))?;
        let v: Value = serde_json::from_str(&s).map_err(|e| e.to_string())?;
        let pp_h = v["px_per_H"].as_f64().ok_or("px_per_H 없음")?;
        let g_meta = v.get("ground_row_grid").or(v.get("발바닥_행")).and_then(|x| x.as_f64()).unwrap_or(0.0);
        let mut panels = std::collections::BTreeMap::new();
        for (name, p) in v["panels"].as_object().ok_or("panels 없음")? {
            let panel = if let Some(cx) = p.get("center_x").and_then(|x| x.as_f64()) {
                Panel { center_x: cx, ground_row: p["ground_row"].as_f64().unwrap_or(v["ground_row"].as_f64().unwrap_or(0.0)), sign: p["sign"].as_f64().unwrap_or(-1.0) }
            } else {
                Panel { center_x: p["중심선_x"].as_f64().ok_or("중심선_x 없음")?, ground_row: g_meta, sign: p["x부호(화면x→캐릭터)"].as_f64().unwrap_or(-1.0) }
            };
            panels.insert(name.clone(), panel);
        }
        Ok(Frame { pp_h, panels })
    }

    pub fn px_to_h(&self, view: &str, px: f64, py: f64) -> (f64, f64) {
        let p = &self.panels[view];
        (p.sign * (px - p.center_x) / self.pp_h, (p.ground_row - py) / self.pp_h)
    }

    pub fn h_to_px(&self, view: &str, lat: f64, z: f64) -> (f64, f64) {
        let p = &self.panels[view];
        (p.center_x + p.sign * lat * self.pp_h, p.ground_row - z * self.pp_h)
    }
}
