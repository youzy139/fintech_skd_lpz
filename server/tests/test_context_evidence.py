from __future__ import annotations

from dataclasses import replace

from app.core.config import load_config
from app.services.alert import AlertService
from app.services.alert_rules import AlertRuleManager
from app.services.context_evidence import attach_context
from test_alert_service import FakeFeatureClient, sample_states


DEFAULTS = {"volatility_quantile": 0.9, "correlation_quantile": 0.9, "minimum_history": 60, "regime_change_enabled": True}


class FakeCatalog:
    def __init__(self, unavailable=None):
        self.unavailable = unavailable
        self.calls = []
        self.closed = False

    def list_records(self, source_id, query, date, offset, limit, kind=None, **kwargs):
        assert date == "2024-02-29"
        self.calls.append((kind, date, offset, limit))
        if kind == self.unavailable:
            raise RuntimeError("offline")
        payload = {"OccurDate": "2024-02-29", "OccurTime": "09:30"} if kind == "calendar" else {"日期": "2024-02-29", "文章标题": "此前公开的文章"}
        return {"total": 2, "items": [{"source_id": f"{kind}-source", "record_index": 1, "source_path": f"{kind}.xlsx", "kind": kind, "event_date": date, "title": "此前公开的经济事件" if kind == "calendar" else "此前公开的文章", "payload": payload, "tags": []}]}

    def close(self):
        self.closed = True


def service_with_catalog(tmp_path, catalog):
    config = replace(load_config(), database_path=tmp_path / "alert.db")
    rules = AlertRuleManager(tmp_path / "rules.db", DEFAULTS)
    service = AlertService(config, FakeFeatureClient(sample_states()), rules, catalog)
    service.initialize()
    return service


def test_context_uses_only_previous_state_date_and_preserves_source_time(tmp_path):
    catalog = FakeCatalog()
    service = service_with_catalog(tmp_path, catalog)
    evidence = service.alert_evidence("HIGH_VOLATILITY", "2024-03-01")
    assert catalog.calls == [("calendar", "2024-02-29", 0, 6), ("publication", "2024-02-29", 0, 6)]
    assert evidence["context"]["cutoff_date"] == "2024-02-29"
    assert evidence["context"]["status"] == "ok"
    calendar, publication = evidence["context"]["sources"]
    assert calendar["items"][0]["source_timestamp"] == "2024-02-29T09:30"
    assert calendar["items"][0]["time_basis"].startswith("经济日历")
    assert publication["items"][0]["source_timestamp"] is None
    assert {item["kind"] for item in evidence["context"]["excluded"]} == {"news", "indicator", "research", "social"}
    assert all(item["source_date"] < evidence["event_time"] for source in evidence["context"]["sources"] for item in source["items"])
    service.close()
    assert catalog.closed


def test_unavailable_context_does_not_hide_market_rule_evidence(tmp_path):
    service = service_with_catalog(tmp_path, FakeCatalog(unavailable="calendar"))
    evidence = service.alert_evidence("HIGH_VOLATILITY", "2024-03-01")
    assert evidence["state"]["features"]["volatility"] == 0.8
    assert evidence["context"]["status"] == "degraded"
    assert evidence["context"]["sources"][0]["status"] == "unavailable"
    assert evidence["context"]["sources"][1]["total"] == 2
    service.close()


def test_no_previous_state_or_catalog_never_fabricates_context():
    evidence = {"previous_state": None}
    assert attach_context(evidence, None)["context"]["status"] == "no_previous_state"
    evidence = {"previous_state": {"date": "2024-02-29"}}
    assert attach_context(evidence, None)["context"]["status"] == "disabled"


class AllowlistCatalog:
    def __init__(self):
        self.calls = []

    def list_records(self, source_id, query, date, offset, limit, kind=None, **kwargs):
        self.calls.append((source_id, kind, date, offset, limit))
        expected = {"calendar": {"calendar-a", "calendar-b"}, "publication": {"publication-a"}}
        if source_id not in expected[kind]:
            return {"total": 0, "items": []}
        payload = {"OccurDate": date, "OccurTime": "09:30"} if kind == "calendar" else {"日期": date}
        return {
            "total": 2 if source_id == "calendar-a" else 1,
            "items": [{
                "source_id": source_id,
                "record_index": 1,
                "source_path": source_id + ".csv",
                "kind": kind,
                "event_date": date,
                "title": source_id,
                "payload": payload,
                "tags": [],
            }],
        }


def test_context_allowlist_never_queries_or_aggregates_other_sources():
    catalog = AllowlistCatalog()
    allowed = {"calendar-a", "calendar-b", "publication-a", "unrelated"}
    evidence = attach_context({"previous_state": {"date": "2024-02-29"}}, catalog, limit=2, allowed_sources=allowed)

    assert catalog.calls
    assert {call[0] for call in catalog.calls} == allowed
    assert all(call[0] is not None and call[2] == "2024-02-29" for call in catalog.calls)
    assert evidence["context"]["source_scope"] == "allowlist"
    calendar, publication = evidence["context"]["sources"]
    assert calendar["total"] == 3
    assert [item["record_id"] for item in calendar["items"]] == ["calendar-a:1", "calendar-b:1"]
    assert publication["total"] == 1
    assert [item["record_id"] for item in publication["items"]] == ["publication-a:1"]
