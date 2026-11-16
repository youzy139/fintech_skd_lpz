"""Run real-Chrome cold/hot page benchmarks on isolated synthetic services."""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.core.observability import percentile
from app.services.page_performance import source_sha256
from app.services.replay_benchmark import git_revision
from server.benchmarks.independent_user_performance import wait_ready

MODES = ("cold_empty_context", "hot_repeat_reload", "slow_4g_reference")


def summarize_samples(samples: Sequence[dict[str, Any]], target_ms: float | None) -> dict[str, Any]:
    successful = [item for item in samples if item.get("success")]
    durations = [float(item["ready_ms"]) for item in successful]
    p95 = percentile(durations, 0.95)
    return {
        "attempt_count": len(samples),
        "successful_count": len(successful),
        "failed_count": len(samples) - len(successful),
        "sample_count": len(durations),
        "latency_ms": {
            "p50": percentile(durations, 0.5),
            "p95": p95,
            "p99": percentile(durations, 0.99),
            "min": round(min(durations), 3) if durations else None,
            "max": round(max(durations), 3) if durations else None,
            "mean": round(sum(durations) / len(durations), 3) if durations else None,
        },
        "target_p95_ms": target_ms,
        "p95_within_target": p95 < target_ms if p95 is not None and target_ms is not None else None,
    }


def summarize_mode(samples: Sequence[dict[str, Any]], routes: Sequence[dict[str, Any]], mode: str, target_ms: float | None) -> dict[str, Any]:
    selected = [item for item in samples if item["mode"] == mode]
    return {
        **summarize_samples(selected, target_ms),
        "by_page": {route["id"]: summarize_samples([item for item in selected if item["page"] == route["id"]], target_ms) for route in routes},
    }


def wait_frontend(process: subprocess.Popen, base_url: str, timeout: float) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"基准前端提前退出，退出码 {process.returncode}")
        try:
            with opener.open(base_url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("等待隔离基准前端就绪超时")


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="隔离合成服务上的真实 Chrome 页面冷/热加载与 Slow 4G 参考基准")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--backend-port", type=int, default=18000)
    parser.add_argument("--frontend-port", type=int, default=5174)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--slow-rounds", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--ready-timeout", type=float, default=180)
    parser.add_argument("--output", type=Path, default=ROOT / "server/data/benchmarks/page-performance.json")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("页面性能基准只能监听本机")
    if not 1 <= args.backend_port <= 65535 or not 1 <= args.frontend_port <= 65535 or args.backend_port == args.frontend_port:
        parser.error("固定前后端端口无效")
    if args.rounds < 1 or args.slow_rounds < 0 or min(args.timeout, args.ready_timeout) <= 0:
        parser.error("轮次和超时参数无效")
    for port in (args.backend_port, args.frontend_port):
        with socket.socket() as reservation:
            if reservation.connect_ex((args.host, port)) == 0:
                parser.error(f"固定基准端口 {port} 已被占用；请先停止所属预览，不自动更换端口")

    backend_url = f"http://{args.host}:{args.backend_port}"
    frontend_url = f"http://{args.host}:{args.frontend_port}"
    backend: subprocess.Popen | None = None
    frontend: subprocess.Popen | None = None
    with tempfile.TemporaryDirectory(prefix="marketlens-page-performance-") as directory:
        raw_path = Path(directory) / "browser.json"
        environment = dict(os.environ)
        environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "server")])
        environment["VITE_API_TARGET"] = backend_url
        try:
            backend = subprocess.Popen(
                [sys.executable, str(ROOT / "server/benchmarks/e2e_server.py")],
                cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            wait_ready(backend, backend_url, args.ready_timeout)
            frontend = subprocess.Popen(
                ["node", str(ROOT / "web/node_modules/vite/bin/vite.js"), str(ROOT / "web"), "--host", args.host, "--port", str(args.frontend_port), "--strictPort"],
                cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            wait_frontend(frontend, frontend_url, 30)
            subprocess.run(
                [
                    "node", str(ROOT / "web/scripts/page-performance.mjs"),
                    "--base-url", frontend_url, "--output", str(raw_path),
                    "--rounds", str(args.rounds), "--slow-rounds", str(args.slow_rounds), "--timeout", str(args.timeout * 1000),
                ],
                cwd=ROOT, env=environment, check=True, timeout=max(300, args.timeout * args.rounds * 20),
            )
        finally:
            stop_process(frontend)
            stop_process(backend)
        raw = json.loads(raw_path.read_text(encoding="utf-8"))

    routes = raw["routes"]
    samples = raw["samples"]
    expected = len(routes) * (2 * args.rounds + args.slow_rounds)
    if raw.get("schema") != "page-performance-browser-v1" or len(samples) != expected:
        raise ValueError("真实 Chrome 页面基准样本不完整")
    measurement = {
        "cold_empty_context": summarize_mode(samples, routes, "cold_empty_context", 2000),
        "hot_repeat_reload": summarize_mode(samples, routes, "hot_repeat_reload", 2000),
        "slow_4g_reference": summarize_mode(samples, routes, "slow_4g_reference", None),
    }
    primary = [measurement["cold_empty_context"], measurement["hot_repeat_reload"]]
    primary_complete = all(group["attempt_count"] == len(routes) * args.rounds and group["failed_count"] == 0 for group in primary)
    page_results = {}
    for route in routes:
        cold = measurement["cold_empty_context"]["by_page"][route["id"]]
        hot = measurement["hot_repeat_reload"]["by_page"][route["id"]]
        slow = measurement["slow_4g_reference"]["by_page"][route["id"]]
        page_results[route["id"]] = {
            "label": route["label"],
            "cold_p95_ms": cold["latency_ms"]["p95"],
            "hot_p95_ms": hot["latency_ms"]["p95"],
            "slow_4g_p95_ms": slow["latency_ms"]["p95"],
            "cold_samples": f"{cold['successful_count']}/{cold['attempt_count']}",
            "hot_samples": f"{hot['successful_count']}/{hot['attempt_count']}",
            "slow_4g_samples": f"{slow['successful_count']}/{slow['attempt_count']}",
            "passes_provisional_target": bool(cold["p95_within_target"] and hot["p95_within_target"]),
        }
    target_passed = primary_complete and all(item["passes_provisional_target"] for item in page_results.values())
    report = {
        "report_type": "browser_page_performance",
        "performance_version": "browser-page-performance-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_sha256(),
        "complete": all(group["failed_count"] == 0 for group in measurement.values()) and primary_complete,
        "configuration": {
            "data_profile": "synthetic-e2e",
            "pages": len(routes),
            "rounds_per_page": args.rounds,
            "slow_4g_rounds_per_page": args.slow_rounds,
            "viewport": raw["viewport"],
            "measurement_boundary": "从 Node 发起 goto/reload 到页面特定可用条件满足，包含本机网络、静态资源、懒加载、API、React 渲染和必要图表 canvas；不含首次管理员初始化和浏览器进程启动",
            "cold_definition": "同一 Chrome 进程的新浏览器上下文、空 HTTP 缓存；后端保持运行，不是操作系统或公网冷启动",
            "hot_definition": "同一路由新上下文先完成一次不计时预热，再在同一上下文 reload；每轮均保留，不是 SPA 点击切换",
            "slow_4g_definition": "Chrome DevTools 模拟 150ms RTT、下行 1.6Mbps、上行 768kbps；仅作参考，不判定本机 <2s 目标",
            "timeout_seconds": args.timeout,
            "pacing_excluded_from_latency": "每次导航及热加载预热前按页面等待：系统 12s、数据 5s、其他 1.5s；不关闭既有 read/query/admin 限流，避免单账号测量本身超过每分钟配额",
            "request_failure_policy": "net::ERR_ABORTED 作为重复 effect、导航或上下文关闭的主动中止单独保留；其他 requestfailed、非预期 HTTP 4xx/5xx（含 429）和任何 pageerror 均计为失败",
            "frontend_url": frontend_url,
            "backend_url": backend_url,
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "node": raw["node"],
            "cpu_count": os.cpu_count(),
            "git_revision": os.getenv("MARKETLENS_GIT_REVISION") or git_revision(),
            "browser": raw["browser"],
            "resource_usage": "not_collected",
        },
        "routes": routes,
        "measurement": measurement,
        "page_results": page_results,
        "samples": samples,
        "target_evaluation": {
            "provisional_latency_statistic": "p95",
            "target_p95_ms": 2000,
            "primary_profiles": ["cold_empty_context", "hot_repeat_reload"],
            "all_primary_samples_successful": primary_complete,
            "all_pages_below_2s": target_passed,
            "passes_provisional_target": target_passed,
            "note": "只判定桌面本机合成服务的新上下文冷加载和同上下文热 reload；Slow 4G、移动端、公网和真实赛题数据单独复验",
        },
        "limitations": [
            "独立合成三资产和临时管理员；不是完整真实赛题目录或正式账号的页面性能",
            "同机 Vite 开发服务与单进程 FastAPI；不是 Nginx、生产静态构建、多进程或公网部署",
            "冷加载复用同一 Chrome 进程且后端保持运行，不是冷机器、冷浏览器进程或冷后端",
            "仅桌面 1440×1000；未覆盖移动端、慢 CPU、不同浏览器和辅助技术耗时",
            "Slow 4G 为 DevTools 网络模拟，不是真实运营商网络；资源使用和错误率之外的容量指标未采集",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "browser": raw["browser"],
        "pages": len(routes),
        "samples": len(samples),
        "successful": sum(item["success"] for item in samples),
        "cold_p95_ms": measurement["cold_empty_context"]["latency_ms"]["p95"],
        "hot_p95_ms": measurement["hot_repeat_reload"]["latency_ms"]["p95"],
        "slow_4g_p95_ms": measurement["slow_4g_reference"]["latency_ms"]["p95"],
        "passes_provisional_target": target_passed,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
