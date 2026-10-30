from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import SERVER_ROOT, load_config
from app.services.catalog import CatalogStore
from app.services.contracts import CatalogStorage

BASELINE_VERSION = 1


def _digest(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _schema(store: CatalogStore) -> list[dict[str, str]]:
    rows = store.connection.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    return [{"type": kind, "name": name, "sql": " ".join(sql.split())} for kind, name, sql in rows]


def _record_inventory(store: CatalogStore, include_digests: bool) -> list[dict[str, Any]]:
    inventory = []
    source_ids = [row[0] for row in store.connection.execute("SELECT id FROM source_files ORDER BY id")]
    for source_id in source_ids:
        cursor = store.connection.execute(
            "SELECT record_index, event_date, title, payload_json, kind FROM source_records WHERE source_id = ? ORDER BY record_index",
            (source_id,),
        )
        digest = hashlib.sha256()
        count = 0
        start_date = None
        end_date = None
        while True:
            rows = cursor.fetchmany(1000)
            if not rows:
                break
            for record_index, event_date, title, payload_json, kind in rows:
                if include_digests:
                    digest.update(_digest([source_id, record_index, event_date, title, payload_json, kind]).encode("ascii"))
                count += 1
                if event_date:
                    start_date = event_date if start_date is None else min(start_date, event_date)
                    end_date = event_date if end_date is None else max(end_date, event_date)
        inventory.append({
            "source_id": source_id,
            "records": count,
            "start_date": start_date,
            "end_date": end_date,
            "records_sha256": digest.hexdigest() if include_digests else None,
        })
    return inventory


def _snapshots(store: CatalogStore) -> list[dict[str, str]]:
    exists = store.connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'snapshots'").fetchone()
    if not exists:
        return []
    rows = store.connection.execute("SELECT key, value_json FROM snapshots ORDER BY key").fetchall()
    return [{"key": key, "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()} for key, value in rows]


def catalog_queries(store: CatalogStorage, limit: int) -> dict[str, Any]:
    summary = store.summary()
    kinds = [group["kind"] for group in summary["groups"]]
    queries: dict[str, Any] = {
        "summary": summary,
        "overview:all": store.overview(None),
        "tags:all": store.list_tags(None),
        "files:all": store.list_files(None, None, 0, limit),
        "records:all": store.list_records(None, None, None, 0, limit),
    }
    for kind in kinds:
        queries[f"overview:{kind}"] = store.overview(kind)
        queries[f"tags:{kind}"] = store.list_tags(kind)
        queries[f"files:{kind}"] = store.list_files(kind, None, 0, limit)
        queries[f"records:{kind}"] = store.list_records(None, None, None, 0, limit, kind)
    selected_tags = [item["tag"] for item in queries["tags:all"][:2]]
    for tag in selected_tags:
        queries[f"records:tag:{tag}"] = store.list_records(None, None, None, 0, limit, tag=tag)
    if selected_tags:
        for match in ("any", "all"):
            queries[f"records:tags:{match}"] = store.list_records(None, None, None, 0, limit, tags=selected_tags, match=match)
    return queries


def build_baseline(database_path: Path, query_limit: int = 20, include_record_digests: bool = True) -> dict[str, Any]:
    if not 1 <= query_limit <= 100:
        raise ValueError("基线查询分页大小必须在 1 到 100 之间")
    store = CatalogStore(database_path)
    try:
        payload = {
            "schema": _schema(store),
            "sources": store.list_files(None, None, 0, 100000)["items"],
            "record_inventory": _record_inventory(store, include_record_digests),
            "snapshots": _snapshots(store),
            "queries": catalog_queries(store, query_limit),
        }
    finally:
        store.close()
    return {
        "baseline_version": BASELINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_limit": query_limit,
        "includes_record_digests": include_record_digests,
        "payload": payload,
    }


def compare_baselines(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    differences = []
    if expected.get("baseline_version") != actual.get("baseline_version"):
        return [f"baseline_version: {expected.get('baseline_version')!r} != {actual.get('baseline_version')!r}"]
    if expected.get("query_limit") != actual.get("query_limit"):
        differences.append(f"query_limit: {expected.get('query_limit')!r} != {actual.get('query_limit')!r}")
    if expected.get("includes_record_digests") != actual.get("includes_record_digests"):
        differences.append("includes_record_digests: 摘要选项不一致")

    def compare(left: Any, right: Any, path: str) -> None:
        if type(left) is not type(right):
            differences.append(f"{path}: 类型 {type(left).__name__} != {type(right).__name__}")
        elif isinstance(left, dict):
            for key in sorted(left.keys() | right.keys()):
                if key not in left:
                    differences.append(f"{path}.{key}: 基线中不存在")
                elif key not in right:
                    differences.append(f"{path}.{key}: 当前结果中不存在")
                else:
                    compare(left[key], right[key], f"{path}.{key}")
        elif isinstance(left, list):
            if len(left) != len(right):
                differences.append(f"{path}: 列表长度 {len(left)} != {len(right)}")
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                compare(left_item, right_item, f"{path}[{index}]")
        elif left != right:
            differences.append(f"{path}: {left!r} != {right!r}")

    compare(expected.get("payload"), actual.get("payload"), "payload")
    return differences


def write_baseline(baseline: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成或核对 SQLite 存储迁移基线")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path, default=SERVER_ROOT / "data" / "migration" / "catalog-baseline.json")
    parser.add_argument("--compare", type=Path, help="与已有基线比较，不覆盖该文件")
    parser.add_argument("--query-limit", type=int, default=20)
    parser.add_argument("--skip-record-digests", action="store_true")
    args = parser.parse_args()
    database = args.database or load_config().database_path
    actual = build_baseline(database, args.query_limit, not args.skip_record_digests)
    if args.compare:
        expected = json.loads(args.compare.read_text(encoding="utf-8"))
        differences = compare_baselines(expected, actual)
        if differences:
            print(f"基线核对失败：{len(differences)} 处差异")
            for difference in differences[:20]:
                print(difference)
            if len(differences) > 20:
                print(f"另有 {len(differences) - 20} 处差异未显示")
            return 1
        print(f"基线核对通过：{len(actual['payload']['sources'])} 个文件，{actual['payload']['queries']['summary']['total_records']} 条记录")
        return 0
    write_baseline(actual, args.output)
    print(f"基线已写入 {args.output}：{len(actual['payload']['sources'])} 个文件，{actual['payload']['queries']['summary']['total_records']} 条记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
