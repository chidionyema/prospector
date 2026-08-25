//! `prospector-pack build <pack.json> <ledger.json> <out_dir>` and `prospector-pack bench <pack.json> <ledger.json>`.
use std::path::Path;

use prospector_pack::ir::{FetchLedger, Pack};

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    let (cmd, pack_path, ledger_path) = match args.as_slice() {
        [_, c, p, l, ..] => (c.as_str(), p, l),
        _ => return Err("usage: prospector-pack build|bench <pack.json> <ledger.json> [out_dir]".into()),
    };
    let ledger: FetchLedger = serde_json::from_slice(&std::fs::read(ledger_path).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    let json = std::fs::read(pack_path).map_err(|e| e.to_string())?;
    let pack = Pack::load(&json, &ledger).map_err(|e| e.to_string())?;
    match cmd {
        "build" => {
            let out = args.get(4).ok_or("out_dir required")?;
            let (bundle, t) = prospector_pack::build(&pack).map_err(|e| e.to_string())?;
            for (name, bytes) in &bundle {
                let path = Path::new(out).join(name);
                if let Some(d) = path.parent() {
                    std::fs::create_dir_all(d).map_err(|e| e.to_string())?;
                }
                std::fs::write(&path, bytes).map_err(|e| e.to_string())?;
                println!("{:>9} bytes  {}", bytes.len(), name);
            }
            println!("{}", serde_json::to_string(&t).map_err(|e| e.to_string())?);
            Ok(())
        }
        "bench" => {
            let runs: u32 = args.get(4).and_then(|s| s.parse().ok()).unwrap_or(5);
            let mut best: Option<prospector_pack::Timings> = None;
            let mut sizes = std::collections::BTreeMap::new();
            for _ in 0..runs {
                let (bundle, t) = prospector_pack::build(&pack).map_err(|e| e.to_string())?;
                for (k, v) in &bundle {
                    sizes.insert(k.clone(), v.len());
                }
                best = Some(match best {
                    Some(b) if b.total_ms <= t.total_ms => b,
                    _ => t,
                });
            }
            let b = best.ok_or("no runs")?;
            println!("{}", serde_json::to_string(&serde_json::json!({"input_bytes": json.len(), "runs": runs, "best": b, "bytes": sizes})).map_err(|e| e.to_string())?);
            Ok(())
        }
        other => Err(format!("unknown command {other}")),
    }
}

fn main() {
    if let Err(e) = run() {
        eprintln!("prospector-pack: {e}");
        std::process::exit(1);
    }
}
