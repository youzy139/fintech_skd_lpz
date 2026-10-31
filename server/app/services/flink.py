from __future__ import annotations

import asyncio
import json
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.kafka import KafkaReplayPipeline


class FlinkJobManager:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.rest_url = settings["rest_url"].rstrip("/")

    def _request_sync(self, path: str, payload: dict[str, Any] | None = None, method: str | None = None) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.rest_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method=method or ("POST" if body is not None else "GET"),
        )
        try:
            with urlopen(request, timeout=float(self.settings.get("request_timeout_seconds", 10))) as response:
                content = response.read()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Flink REST 返回 {error.code}：{detail}") from error
        except URLError as error:
            raise RuntimeError("无法连接 Flink JobManager") from error
        return json.loads(content) if content else {}

    def _jar_id_sync(self) -> str:
        files = self._request_sync("/jars").get("files", [])
        candidates = [
            item for item in files
            if any(entry.get("name") == "com.marketlens.flink.DailyWindowJob" for entry in item.get("entry", []))
        ]
        if not candidates:
            raise RuntimeError("Flink 日窗口 JAR 尚未上传")
        return max(candidates, key=lambda item: item.get("uploaded", 0))["id"]

    def _program_args(self, session_id: str, run_id: str, kafka: dict[str, Any]) -> list[str]:
        arguments = {
            "bootstrapServers": kafka["bootstrap_servers"],
            "inputTopic": kafka.get("produce_topic", kafka["topic"]),
            "outputTopic": self.settings["output_topic"],
            "lateTopic": self.settings["late_topic"],
            "checkpointInterval": int(self.settings["checkpoint_interval_ms"]),
            "checkpointDir": self.settings["checkpoint_dir"],
            "sessionId": session_id,
            "runId": run_id,
            "groupId": f"marketlens-flink-{run_id}",
        }
        return [part for key, value in arguments.items() for part in (f"--{key}", str(value))]

    def _cancel_sync(self, job_id: str) -> None:
        self._request_sync(f"/jobs/{job_id}", {"action": "cancel"}, method="PATCH")

    def _start_sync(self, session_id: str, run_id: str, kafka: dict[str, Any], savepoint_path: str | None = None) -> str:
        jar_id = self._jar_id_sync()
        request = {
            "entryClass": "com.marketlens.flink.DailyWindowJob",
            "parallelism": 1,
            "programArgsList": self._program_args(session_id, run_id, kafka),
        }
        if savepoint_path:
            request["savepointPath"] = savepoint_path
        response = self._request_sync(f"/jars/{jar_id}/run", request)
        job_id = response["jobid"]
        deadline = monotonic() + int(self.settings.get("job_start_timeout_ms", 90000)) / 1000
        try:
            while monotonic() < deadline:
                state = self._request_sync(f"/jobs/{job_id}").get("state")
                if state in {"FAILED", "CANCELED", "FINISHED"}:
                    raise RuntimeError(f"Flink 回放作业启动失败，状态为 {state}")
                if state == "RUNNING":
                    checkpoints = self._request_sync(f"/jobs/{job_id}/checkpoints")
                    if checkpoints.get("latest", {}).get("completed"):
                        return job_id
                sleep(0.25)
            raise TimeoutError("等待 Flink 作业及首个检查点就绪超时")
        except Exception:
            self._cancel_sync(job_id)
            raise

    def _stop_sync(self, job_id: str) -> str | None:
        state = self._request_sync(f"/jobs/{job_id}").get("state")
        if state in {"CANCELED", "FAILED", "FINISHED"}:
            return None
        response = self._request_sync(f"/jobs/{job_id}/stop", {
            "drain": False,
            "targetDirectory": self.settings["checkpoint_dir"],
        })
        trigger_id = response["request-id"]
        deadline = monotonic() + int(self.settings.get("job_stop_timeout_ms", 60000)) / 1000
        while monotonic() < deadline:
            result = self._request_sync(f"/jobs/{job_id}/savepoints/{trigger_id}")
            if result.get("status", {}).get("id") == "COMPLETED":
                return result.get("operation", {}).get("location")
            sleep(0.25)
        raise TimeoutError("等待 Flink Savepoint 停止超时")

    async def start(self, session_id: str, run_id: str, kafka: dict[str, Any], savepoint_path: str | None = None) -> str:
        return await asyncio.to_thread(self._start_sync, session_id, run_id, kafka, savepoint_path)

    async def stop(self, job_id: str) -> str | None:
        return await asyncio.to_thread(self._stop_sync, job_id)

    async def ensure_running(self, job_id: str) -> None:
        details = await asyncio.to_thread(self._request_sync, f"/jobs/{job_id}")
        state = details.get("state")
        if state != "RUNNING":
            raise RuntimeError(f"Flink 回放作业已停止，状态为 {state}")


class FlinkReplayPipeline(KafkaReplayPipeline):
    def __init__(self, session_id: str, dates, catalog, settings: dict[str, Any], flink_settings: dict[str, Any]):
        super().__init__(session_id, dates, catalog, settings)
        self.jobs = FlinkJobManager(flink_settings)
        self.flink_job_id: str | None = None
        self.savepoint_path: str | None = None
        self.timing.update({"job_start_ms": 0.0, "job_stop_ms": 0.0})

    async def start(self) -> None:
        started = monotonic()
        self.flink_job_id = await self.jobs.start(self.session_id, self.run_id, self.settings)
        self.timing["job_start_ms"] = (monotonic() - started) * 1000
        try:
            await super().start()
        except Exception:
            if self.flink_job_id:
                await self.jobs.stop(self.flink_job_id)
            raise

    async def _get_message(self) -> Any:
        while True:
            try:
                return await asyncio.wait_for(super()._get_message(), timeout=1)
            except TimeoutError:
                if self.flink_job_id:
                    await self.jobs.ensure_running(self.flink_job_id)

    async def close(self) -> None:
        try:
            await super().close()
        finally:
            if self.flink_job_id:
                started = monotonic()
                self.savepoint_path = await self.jobs.stop(self.flink_job_id)
                self.timing["job_stop_ms"] = (monotonic() - started) * 1000
