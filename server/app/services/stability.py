from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from market_core.domain.market import AssetSeries
from market_core.models.evaluation import EVALUATION_VERSION, evaluate_stability
from market_core.models.feature_contracts import feature_contract, market_input_version, model_parameters
from market_core.models.features import build_market_features
from market_core.models.model_card import build_model_card

SOURCE_FILES = (
    "market_core/models/evaluation.py",
    "market_core/models/regime.py",
    "market_core/models/features.py",
    "market_core/models/model_card.py",
)


def build_stability_report(
    series: list[AssetSeries],
    settings: Mapping[str, Any],
    training_windows: Sequence[int] = (504, 756),
    refit_intervals: Sequence[int] = (63, 126),
    random_seeds: Sequence[int] = (42, 2026),
    catalog_missing_assets: Sequence[str] = (),
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    features = build_market_features(
        series,
        int(settings["volatility_window"]),
        int(settings["momentum_window"]),
        str(settings["analysis_start"]),
    )
    report, daily = evaluate_stability(features, settings, training_windows, refit_intervals, random_seeds)
    root = Path(__file__).resolve().parents[3]
    contract = feature_contract(dict(settings))
    report.update({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_version": market_input_version(series),
        "feature_version": contract["feature_version"],
        "model_parameters": model_parameters(dict(settings)),
        "loaded_assets": len(series),
        "model_card": build_model_card(series, features, daily[report["reference_run_id"]], str(settings["analysis_start"]), catalog_missing_assets),
        "source_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES},
    })
    return report, daily


def stability_report_path(database_path: Path) -> Path:
    return database_path.parent / "benchmarks" / "regime-stability.json"


def write_json(path: Path, payload: Any) -> bytes:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return encoded


def write_stability_bundle(report: dict[str, Any], daily: dict[str, list[dict[str, Any]]], output: Path) -> None:
    daily_payload = {
        "schema_version": 1,
        "evaluation_version": report["evaluation_version"],
        "evaluation_id": report["evaluation_id"],
        "runs": daily,
    }
    daily_path = output.with_name(output.stem + "-daily.json")
    encoded = write_json(daily_path, daily_payload)
    report["daily_results"] = {
        "file": daily_path.name,
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "run_count": len(daily),
        "state_days": sum(len(states) for states in daily.values()),
    }
    write_json(output, report)


def load_stability_report(database_path: Path, metadata: Mapping[str, Any]) -> dict[str, Any]:
    path = stability_report_path(database_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError("尚未生成模型稳定性报告，请先运行只读评估脚本") from None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("模型稳定性报告不可读取，请重新生成") from error
    expected = {
        "evaluation_version": EVALUATION_VERSION,
        "input_version": metadata.get("input_version"),
        "feature_version": metadata.get("feature_contract", {}).get("feature_version"),
        "model_parameters": metadata.get("model_parameters"),
    }
    if report.get("report_type") != "regime_stability" or any(report.get(key) != value for key, value in expected.items()):
        raise ValueError("稳定性报告与当前输入、特征或模型配置不匹配，请重新生成")
    return report
