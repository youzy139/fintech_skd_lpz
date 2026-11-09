"""Real rule-version, evidence, restart and rollback acceptance via the main API."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener


OPENER = build_opener(ProxyHandler({}))


def api(base_url: str, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    request = Request(base_url + path, data=None if payload is None else json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method=method)
    with OPENER.open(request, timeout=120) as response:
        return json.load(response)


def wait_ready(base_url: str) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if api(base_url, "/api/health/ready")["status"] == "ok":
                return
        except OSError:
            pass
        time.sleep(1)
    raise TimeoutError("rule acceptance service not ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18030")
    parser.add_argument("--alert-container", default="marketlens-rule-alert")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat()}
    try:
        initial = api(args.base_url, "/api/alert-rules")["active"]
        initial_alerts = api(args.base_url, "/api/alerts?limit=1000")
        changed_settings = {**initial["settings"], "volatility_quantile": 0.95, "correlation_quantile": 0.95}
        changed = api(args.base_url, "/api/alert-rules", "PUT", changed_settings)
        assert changed["version"] != initial["version"]
        changed_alerts = api(args.base_url, "/api/alerts?limit=1000")
        assert changed_alerts and all(item["rule_version"] == changed["version"] for item in changed_alerts)
        home = api(args.base_url, "/api/home/summary")
        assert home["alert_count"] == len(changed_alerts)
        selected = changed_alerts[0]
        evidence = api(args.base_url, f"/api/alerts/{selected['rule']}/{selected['date']}")
        assert evidence["rule_version"] == changed["version"]
        assert evidence["state"]["date"] == selected["date"]
        linked = api(args.base_url, evidence["evidence_links"][0]["url"])
        assert linked == [evidence["state"]]
        subprocess.run(["docker", "restart", args.alert_container], check=True, capture_output=True)
        wait_ready(args.base_url)
        restarted = api(args.base_url, "/api/alert-rules")["active"]
        assert restarted["version"] == changed["version"]
        restored = api(args.base_url, f"/api/alert-rules/{initial['version']}/activate", "POST", {})
        assert restored["version"] == initial["version"]
        restored_alerts = api(args.base_url, "/api/alerts?limit=1000")
        if restored_alerts != initial_alerts:
            difference = next(({"index": index, "before": before, "after": after} for index, (before, after) in enumerate(zip(initial_alerts, restored_alerts)) if before != after), {"lengths": [len(initial_alerts), len(restored_alerts)]})
            raise AssertionError(json.dumps(difference, ensure_ascii=False))
        report.update({
            "passed": True,
            "initial": {"version": initial["version"], "alerts": len(initial_alerts)},
            "changed": {"version": changed["version"], "alerts": len(changed_alerts)},
            "evidence": {"date": selected["date"], "rule": selected["rule"], "state_link_consistent": True},
            "home_alert_count_consistent": True,
            "restart_preserved_version": True,
            "rollback_restored_alerts": True,
        })
    except Exception as error:
        report.update({"passed": False, "failure": {"type": type(error).__name__, "message": str(error)}})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
