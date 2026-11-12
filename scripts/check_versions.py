from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads((ROOT / "web/package.json").read_text(encoding="utf-8"))
    expected = package["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", expected):
        print("web/package.json: expected a three-part release version")
        return 1
    lock = json.loads((ROOT / "web/package-lock.json").read_text(encoding="utf-8"))
    declarations = {
        "web/package-lock.json": lock["version"],
        "web/package-lock.json packages[root]": lock["packages"][""]["version"],
    }
    module = ast.parse((ROOT / "server/app/version.py").read_text(encoding="utf-8"))
    declarations["server/app/version.py"] = next(
        ast.literal_eval(node.value) for node in module.body
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)
    )
    pom = ET.parse(ROOT / "flink/pom.xml").getroot()
    declarations["flink/pom.xml"] = pom.findtext("{http://maven.apache.org/POM/4.0.0}version")
    for filename, images in {
        "compose.yaml": ("backend", "frontend"), "compose.flink.yaml": ("flink",),
    }.items():
        content = (ROOT / filename).read_text(encoding="utf-8")
        for image in images:
            values = re.findall(rf"(?m)^\s*image:\s*marketlens-{image}:([^\s#]+)\s*$", content)
            declarations[f"{filename} marketlens-{image}"] = values[0] if len(values) == 1 else None
    failures = [f"{name}: {value!r} != {expected!r}" for name, value in declarations.items() if value != expected]
    if failures:
        print("\n".join(failures))
        return 1
    print(f"MarketLens {expected}: {len(declarations) + 1} version declarations agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
