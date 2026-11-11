"""Export reviewable identity evidence without run IDs, topics or Savepoint paths."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=ROOT / "server/data/benchmarks/regime-identity.json")
    parser.add_argument("--channels", type=Path, default=ROOT / "server/data/benchmarks/regime-identity-channels.json")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/v0.3.5-regime-identity-results.json")
    args = parser.parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    channels = json.loads(args.channels.read_text(encoding="utf-8"))
    summary = {
        "audit": audit,
        "channels": {key: channels[key] for key in ("passed", "data", "days", "model_settings", "limitation")},
        "raw_report_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.audit, args.channels)},
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
    }
    summary["channels"]["results"] = {
        mode: {"days": len(value["days"]), "stats": value["stats"], "savepoint_created": bool(value["savepoint"])}
        for mode, value in channels["results"].items()
    }
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("Wrote sanitized correctness evidence")


if __name__ == "__main__":
    main()
