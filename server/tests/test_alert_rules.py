from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.alert_service import create_alert_app
from app.core.config import load_config
from app.main import create_app
from app.services.alert import AlertService
from app.services.alert_rules import AlertRuleManager
from app.services.market import MarketService
from market_core.models.alerts import alert_rule_version, normalize_rule_settings
from server.tests.test_alert_service import FakeFeatureClient, sample_states


DEFAULTS = {"volatility_quantile": 0.9, "correlation_quantile": 0.9, "minimum_history": 60, "regime_change_enabled": True}


def manager(tmp_path):
    return AlertRuleManager(tmp_path / "rules.db", DEFAULTS)


def test_rule_version_is_deterministic_and_validated():
    assert alert_rule_version(DEFAULTS) == alert_rule_version(dict(reversed(list(DEFAULTS.items()))))
    changed = alert_rule_version({**DEFAULTS, "volatility_quantile": 0.95})
    assert changed != alert_rule_version(DEFAULTS)
    for settings in ({**DEFAULTS, "volatility_quantile": 0.1}, {**DEFAULTS, "minimum_history": 1}):
        try:
            normalize_rule_settings(settings)
            assert False
        except ValueError:
            pass


def test_rule_manager_persists_versions_and_reactivation(tmp_path):
    rules = manager(tmp_path)
    initial = rules.current()
    updated = rules.save({**DEFAULTS, "minimum_history": 30}, "admin")
    assert updated["version"] != initial["version"]
    assert rules.describe()["versions"][0]["active"] is True
    assert AlertRuleManager(tmp_path / "rules.db", DEFAULTS).current()["version"] == updated["version"]
    assert rules.activate(initial["version"], "admin")["settings"] == DEFAULTS
    assert AlertRuleManager(tmp_path / "rules.db", DEFAULTS).current()["version"] == initial["version"]


def test_rule_changes_rebuild_alerts_and_preserve_evidence(tmp_path):
    config = replace(load_config(), database_path=tmp_path / "market.db")
    rules = manager(tmp_path)
    service = AlertService(config, FakeFeatureClient(sample_states()), rules)
    service.initialize()
    initial = rules.current()
    assert len(service.list_alerts(100)) == 3
    updated = service.update_alert_rules({**DEFAULTS, "minimum_history": 30, "regime_change_enabled": False}, "admin")
    assert updated["version"] != initial["version"]
    assert {item["rule"] for item in service.list_alerts(100)} == {"HIGH_VOLATILITY", "HIGH_CORRELATION"}
    assert all(item["rule_version"] == updated["version"] for item in service.list_alerts(100))
    evidence = service.alert_evidence("HIGH_VOLATILITY", "2024-03-01")
    assert evidence["state"]["features"]["volatility"] == 0.8
    assert evidence["history_days"] == 60
    assert evidence["parameters"]["minimum_history"] == 30
    assert evidence["evidence_links"][0]["url"] == "/api/regimes?start=2024-03-01&end=2024-03-01"
    service.activate_alert_rule(initial["version"], "admin")
    assert len(service.list_alerts(100)) == 3
    service.close()


def test_alert_rule_api_and_local_monolith_share_behavior(tmp_path):
    config = replace(load_config(), database_path=tmp_path / "local.db")
    service = MarketService.__new__(MarketService)
    service.states = sample_states()
    service.series = []
    service.rule_manager = manager(tmp_path)
    service.store = SimpleNamespace(save=lambda key, value: None)
    service.rebuild_alerts()
    with TestClient(create_app(service, initialize=False)) as http:
        rules = http.get("/api/alert-rules")
        assert rules.status_code == 200
        old_version = rules.json()["active"]["version"]
        response = http.put("/api/alert-rules", json={**DEFAULTS, "minimum_history": 30})
        assert response.status_code == 200
        assert response.json()["version"] != old_version
        evidence = http.get("/api/alerts/HIGH_VOLATILITY/2024-03-01")
        assert evidence.status_code == 200
        assert evidence.json()["rule_version"] == response.json()["version"]
        assert http.post(f"/api/alert-rules/{old_version}/activate").status_code == 200
        assert http.get("/api/alerts/missing/2024-03-01").status_code == 404


def test_independent_alert_service_rule_contract(tmp_path):
    config = replace(load_config(), database_path=tmp_path / "alert.db")
    service = AlertService(config, FakeFeatureClient(sample_states()), manager(tmp_path))
    with TestClient(create_alert_app(service)) as http:
        assert http.get("/api/alert-rules").json()["active"]["settings"]["minimum_history"] == 60
        updated = http.put("/api/alert-rules", json={**DEFAULTS, "minimum_history": 30})
        assert updated.status_code == 200
        assert http.get("/api/alerts/HIGH_VOLATILITY/2024-03-01").json()["parameters"]["minimum_history"] == 30
        assert http.post("/api/alert-rules/missing/activate").status_code == 404
        assert http.get("/api/health/ready").json()["checks"]["alerts"]["rule_version"] == updated.json()["version"]


def test_home_summary_refreshes_when_shared_rule_version_changes(tmp_path):
    service = MarketService.__new__(MarketService)
    service.states = sample_states()
    service.series = []
    service.quality = {"total_rows": 0}
    service.rule_manager = manager(tmp_path)
    service.store = SimpleNamespace(save=lambda key, value: None)
    service.rebuild_alerts()
    assert service.home_summary()["alert_count"] == 3
    service.rule_manager.save({**DEFAULTS, "regime_change_enabled": False}, "other-service")
    assert service.home_summary()["alert_count"] == 2
    assert all(item["rule"] != "REGIME_CHANGE" for item in service.alerts)
