from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from app.core.config import SERVER_ROOT, load_config

SIDECAR_SUFFIX = ".source-name.json"


def _write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare_research_sources(source_root: Path, output_root: Path) -> dict[str, int]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if source_root == output_root:
        raise ValueError("派生目录不能与原始摘要目录相同")
    sources = sorted(source_root.glob("*.md"))
    if not sources:
        raise ValueError(f"未发现研究摘要：{source_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "manifest.json"
    if manifest_path.is_file():
        previous = set(json.loads(manifest_path.read_text(encoding="utf-8"))["generated_files"])
    else:
        previous = set()
    generated = set()
    copied = 0
    unchanged = 0
    for source in sources:
        digest = hashlib.sha256(source.name.encode("utf-8")).hexdigest()[:16]
        target_name = f"{source.stem[:10]}-{digest}"
        markdown_name = target_name + ".md"
        sidecar_name = target_name + SIDECAR_SUFFIX
        target = output_root / markdown_name
        if target.is_file() and target.read_bytes() == source.read_bytes():
            unchanged += 1
        else:
            temporary = target.with_suffix(".tmp")
            shutil.copy2(source, temporary)
            temporary.replace(target)
            copied += 1
        _write_json(output_root / sidecar_name, {"original_name": source.name})
        generated.update((markdown_name, sidecar_name))
    for name in sorted(previous - generated):
        path = output_root / name
        if path.is_file():
            path.unlink()
    _write_json(manifest_path, {"generated_files": sorted(generated), "source_count": len(sources)})
    return {"sources": len(sources), "copied": copied, "unchanged": unchanged, "removed": len(previous - generated)}


def main() -> int:
    parser = argparse.ArgumentParser(description="为 Linux 容器生成短文件名研究摘要副本，不修改原始文件")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path, default=SERVER_ROOT / "data" / "container-sources" / "research")
    args = parser.parse_args()
    source_root = args.source or load_config().data_root / "全球资金信息摘要" / "上科大版本摘要"
    result = prepare_research_sources(source_root, args.output)
    print(f"容器研究摘要副本完成：{result}；目录：{args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
