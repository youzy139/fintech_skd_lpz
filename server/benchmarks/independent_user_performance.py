"""Measure mixed API load with independent synthetic users on local Uvicorn only."""
from __future__ import annotations

import argparse
import concurrent.futures
import http.client
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
from urllib.request import ProxyHandler, Request, build_opener
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "server")]

from app.core.observability import percentile
from app.services.replay_benchmark import git_revision
from server.benchmarks.api_performance import SCENARIOS, call, summarize
from server.benchmarks.e2e_server import prepare


def execute_mixed(base_url: str, paths: list[str], tokens: list[str], rounds: int, timeout: float, caller=call) -> dict:
    if not tokens or not paths or rounds < 1:
        raise ValueError("tokens、paths 和 rounds 必须有效")
    assignments = [(tokens[index % len(tokens)], paths[(index % len(tokens) + index // len(tokens)) % len(paths)]) for index in range(len(tokens) * rounds)]
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tokens)) as pool:
        results = list(pool.map(lambda item: caller(base_url, item[1], item[0], timeout), assignments))
    elapsed = time.perf_counter() - started
    durations = [item[0] for item in results]
    statuses = [item[1] for item in results]
    by_scenario = {}
    for path in paths:
        indices = [index for index, assignment in enumerate(assignments) if assignment[1] == path]
        scenario_durations = [durations[index] for index in indices]
        scenario_statuses = [statuses[index] for index in indices]
        by_scenario[path] = summarize(scenario_durations, scenario_statuses)
    return {
        **summarize(durations, statuses, elapsed),
        "wall_ms": round(elapsed * 1000, 3),
        "users": len(tokens),
        "rounds": rounds,
        "p95_within_50ms": percentile(durations, 0.95) < 50,
        "scenarios": by_scenario,
    }


def execute_persistent(base_url: str, paths: list[str], tokens: list[str], rounds: int, timeout: float) -> dict:
    if not tokens or not paths or rounds < 1:
        raise ValueError("tokens、paths 和 rounds 必须有效")
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or not parsed.hostname or not parsed.port:
        raise ValueError("长连接基准只支持明确的本地 HTTP 地址")

    def run_user(user_index: int) -> list[tuple[float, int]]:
        connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
        results = []
        try:
            for round_index in range(rounds):
                started = time.perf_counter()
                try:
                    path = paths[(user_index + round_index) % len(paths)]
                    connection.request("GET", path, headers={"Accept": "application/json", "Authorization": "Bearer " + tokens[user_index]})
                    response = connection.getresponse()
                    response.read()
                    status = response.status
                except (OSError, http.client.HTTPException):
                    status = 0
                    connection.close()
                    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=timeout)
                results.append(((time.perf_counter() - started) * 1000, status))
        finally:
            connection.close()
        return results

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tokens)) as pool:
        nested = list(pool.map(run_user, range(len(tokens))))
    elapsed = time.perf_counter() - started
    results = [item for user_results in nested for item in user_results]
    durations = [item[0] for item in results]
    statuses = [item[1] for item in results]
    round_metrics = []
    for round_index in range(rounds):
        current = [user_results[round_index] for user_results in nested]
        round_metrics.append(summarize([item[0] for item in current], [item[1] for item in current]))
    return {
        **summarize(durations, statuses, elapsed),
        "wall_ms": round(elapsed * 1000, 3),
        "users": len(tokens),
        "rounds": rounds,
        "connection_mode": "one_keep_alive_connection_per_user",
        "round_metrics": round_metrics,
        "p95_within_50ms": percentile(durations, 0.95) < 50,
    }


def wait_ready(process: subprocess.Popen, base_url: str, timeout: float) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"基准后端提前退出，退出码 {process.returncode}")
        try:
            with opener.open(base_url + "/api/health/ready", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("等待隔离基准后端就绪超时")


def read_json(base_url: str, path: str, token: str, timeout: float):
    request = Request(base_url + path, headers={"Accept": "application/json", "Authorization": "Bearer " + token})
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="至少 101 个独立合成用户的真实 HTTP 混合负载；仅限本机，不是生产容量结论")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--users", type=int, default=101)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--thread-pool-size", type=int)
    parser.add_argument("--ready-timeout", type=float, default=120)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("独立用户基准只能以本机为目标")
    if min(args.users, args.rounds, args.warmup) < 1 or min(args.timeout, args.ready_timeout) <= 0 or not 1 <= args.port <= 65535:
        parser.error("users、rounds、warmup、timeout 和端口参数无效")
    if args.thread_pool_size is not None and not 1 <= args.thread_pool_size <= 256:
        parser.error("thread-pool-size 必须是 1～256")
    with socket.socket() as reservation:
        if reservation.connect_ex((args.host, args.port)) == 0:
            parser.error(f"固定基准端口 {args.port} 已被占用；请先停止所属预览，不自动更换端口")

    base_url = f"http://{args.host}:{args.port}"
    paths = list(SCENARIOS.values())
    with tempfile.TemporaryDirectory(prefix="marketlens-user-performance-") as directory:
        prepare(Path(directory))
        from app.core.auth import auth_store

        store = auth_store()
        password = "synthetic-benchmark-password-123"
        tokens = []
        for index in range(args.users):
            username = f"benchmark-user-{index:03d}"
            store.save_user("benchmark", username, password, "observer", ["market", "catalog"], True, create=True)
            tokens.append(store.login(username, password))
        store.save_user("benchmark", "benchmark-admin", password, "admin", ["market", "catalog"], True, create=True)
        admin_token = store.login("benchmark-admin", password)
        environment = dict(os.environ)
        if args.thread_pool_size is None:
            environment.pop("SERVER_THREAD_POOL_SIZE", None)
        else:
            environment["SERVER_THREAD_POOL_SIZE"] = str(args.thread_pool_size)
        environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "server")])
        command = [
            sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir", str(ROOT / "server"),
            "--host", args.host, "--port", str(args.port), "--log-level", "warning",
        ]
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_ready(process, base_url, args.ready_timeout)
            for index in range(args.warmup):
                call(base_url, paths[index % len(paths)], tokens[index % len(tokens)], args.timeout)
            new_connections = execute_mixed(base_url, paths, tokens, args.rounds, args.timeout)
            persistent = execute_persistent(base_url, paths, tokens, args.rounds, args.timeout)
            measurement = {
                "new_connection_per_request": new_connections,
                "keep_alive_per_user": persistent,
                "server_metrics": read_json(base_url, "/api/system/metrics", admin_token, args.timeout),
            }
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    groups = [measurement["new_connection_per_request"], measurement["keep_alive_per_user"]]
    successful = all(group["successful"] == group["requests"] for group in groups)
    latency_passed = all(group["p95_within_50ms"] for group in groups)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "base_url": base_url, "users": args.users, "rounds": args.rounds, "warmup_requests": args.warmup,
            "concurrent_requests": args.users, "think_time_seconds": 0, "timeout_seconds": args.timeout,
            "scenarios": SCENARIOS, "rate_limit_mode": "local", "measurement_excludes_login": True,
            "server_thread_pool_size": args.thread_pool_size or 40,
        },
        "identity": {
            "type": "independent_synthetic_user_jwt", "users": args.users,
            "unique_sessions": len(set(tokens)), "role": "observer", "domains": ["market", "catalog"],
            "note": "每个账号独立登录会话；不使用服务身份，不读取正式账号或数据",
        },
        "environment": {
            "platform": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count(),
            "git_revision": os.getenv("MARKETLENS_GIT_REVISION") or git_revision(),
            "resource_usage": "not_collected",
        },
        "measurement": measurement,
        "target_evaluation": {
            "provisional_latency_statistic": "p95",
            "independent_users_above_100": args.users > 100,
            "all_requests_successful": successful,
            "api_p95_below_50ms": latency_passed,
            "passes_provisional_target": args.users > 100 and successful and latency_passed,
            "note": "单进程、单机、零思考时间的合成混合读取；不是独立用户完整业务容量或公网性能证明",
        },
    }
    output = args.output or ROOT / "server" / "data" / "benchmarks" / f"independent-users-{int(time.time())}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output), "users": args.users, "requests": sum(group["requests"] for group in groups),
        "new_connection": {"statuses": groups[0]["statuses"], "p95_ms": groups[0]["latency_ms"]["p95"]},
        "keep_alive": {"statuses": groups[1]["statuses"], "p50_ms": groups[1]["latency_ms"]["p50"], "p95_ms": groups[1]["latency_ms"]["p95"], "p99_ms": groups[1]["latency_ms"]["p99"], "throughput_requests_per_second": groups[1]["throughput_requests_per_second"]},
        "passes_provisional_target": report["target_evaluation"]["passes_provisional_target"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
