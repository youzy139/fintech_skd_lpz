from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import load_config
from app.services.remote_alert import RemoteAlertClient


def main():
    config = load_config()
    client = RemoteAlertClient(config.alert_service["url"], config.alert_service["timeout_seconds"])
    expected = os.getenv("CONTEXT_EXPECT_STATUS", "ok")
    alerts = client.get("/api/alerts?limit=1000")
    selected = None
    for alert in alerts:
        evidence = client.get(f"/api/alerts/{alert['rule']}/{alert['date']}")
        context = evidence["context"]
        if expected == "degraded" and context["status"] == "degraded":
            selected = evidence
            break
        if expected == "ok" and context["status"] == "ok" and any(source["total"] for source in context["sources"]):
            selected = evidence
            break
    if selected is None:
        raise RuntimeError(f"没有找到状态为 {expected} 的真实预警证据")
    context = selected["context"]
    assert context["cutoff_date"] < selected["event_time"]
    assert {source["kind"] for source in context["sources"]} == {"calendar", "publication"}
    assert all(item["source_date"] == context["cutoff_date"] < selected["event_time"] for source in context["sources"] for item in source["items"])
    assert selected["state"] and selected["rule_version"] and selected["alert"]
    if expected == "degraded":
        assert any(source["status"] == "unavailable" for source in context["sources"])
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_status": expected,
        "event_time": selected["event_time"],
        "cutoff_date": context["cutoff_date"],
        "rule": selected["rule"],
        "rule_version": selected["rule_version"],
        "core_evidence_available": True,
        "sources": [{"kind": source["kind"], "status": source["status"], "total": source["total"], "sample_count": len(source["items"])} for source in context["sources"]],
        "excluded": context["excluded"],
    }
    output = Path(__file__).resolve().parents[1] / "data" / "benchmarks" / f"context-evidence-{expected}-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
