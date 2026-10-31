from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.services.flink import FlinkJobManager, FlinkReplayPipeline
from app.services.kafka import KafkaReplayPipeline


FLINK_SETTINGS = {
    "rest_url": "http://jobmanager:8081",
    "output_topic": "features",
    "late_topic": "late",
    "checkpoint_interval_ms": 5000,
    "checkpoint_dir": "file:///opt/flink/checkpoints",
    "job_start_timeout_ms": 1000,
    "job_stop_timeout_ms": 1000,
}
KAFKA_SETTINGS = {"bootstrap_servers": "kafka:9092", "topic": "input"}


def test_job_start_uses_run_isolation_and_waits_for_checkpoint():
    manager = FlinkJobManager(FLINK_SETTINGS)
    calls = []

    def request(path, payload=None, method=None):
        calls.append((path, payload, method))
        if path == "/jars":
            return {"files": [{"id": "jar-v2", "uploaded": 2, "entry": [{"name": "com.marketlens.flink.DailyWindowJob"}]}]}
        if path == "/jars/jar-v2/run":
            return {"jobid": "job-1"}
        if path == "/jobs/job-1":
            return {"state": "RUNNING"}
        if path == "/jobs/job-1/checkpoints":
            return {"latest": {"completed": {"id": 1}}}
        raise AssertionError(path)

    manager._request_sync = request
    job_id = asyncio.run(manager.start("session-1", "run-1", KAFKA_SETTINGS, "file:///savepoint"))
    assert job_id == "job-1"
    run = next(payload for path, payload, _ in calls if path.endswith("/run"))
    assert run["savepointPath"] == "file:///savepoint"
    assert ["--sessionId", "session-1"] == run["programArgsList"][12:14]
    assert ["--runId", "run-1"] == run["programArgsList"][14:16]
    assert ["--groupId", "marketlens-flink-run-1"] == run["programArgsList"][16:18]
    assert ["--inputTopic", "input"] == run["programArgsList"][2:4]
    isolated = manager._program_args("session-1", "run-1", {**KAFKA_SETTINGS, "topic": "output", "produce_topic": "input"})
    assert ["--inputTopic", "input"] == isolated[2:4]


def test_job_start_timeout_cancels_only_the_new_job():
    manager = FlinkJobManager({**FLINK_SETTINGS, "job_start_timeout_ms": 0})
    calls = []

    def request(path, payload=None, method=None):
        calls.append((path, method))
        if path == "/jars":
            return {"files": [{"id": "jar", "entry": [{"name": "com.marketlens.flink.DailyWindowJob"}]}]}
        if path == "/jars/jar/run":
            return {"jobid": "job-timeout"}
        if path == "/jobs/job-timeout" and method == "PATCH":
            assert payload == {"action": "cancel"}
            return {}
        raise AssertionError((path, method))

    manager._request_sync = request
    with pytest.raises(TimeoutError):
        asyncio.run(manager.start("session", "run", KAFKA_SETTINGS))
    assert calls[-1] == ("/jobs/job-timeout", "PATCH")


def test_job_stop_returns_savepoint_location():
    manager = FlinkJobManager(FLINK_SETTINGS)

    def request(path, payload=None, method=None):
        if path == "/jobs/job-1":
            return {"state": "RUNNING"}
        if path == "/jobs/job-1/stop":
            assert payload == {"drain": False, "targetDirectory": "file:///opt/flink/checkpoints"}
            return {"request-id": "trigger-1"}
        if path == "/jobs/job-1/savepoints/trigger-1":
            return {"status": {"id": "COMPLETED"}, "operation": {"location": "file:///savepoints/savepoint-1"}}
        raise AssertionError(path)

    manager._request_sync = request
    assert asyncio.run(manager.stop("job-1")) == "file:///savepoints/savepoint-1"


def test_pipeline_starts_job_before_kafka_and_stops_own_job(monkeypatch):
    events = []

    class Jobs:
        async def start(self, session_id, run_id, settings):
            events.append(("job-start", session_id, run_id))
            return "job-1"

        async def stop(self, job_id):
            events.append(("job-stop", job_id))
            return "file:///savepoint"

    async def kafka_start(self):
        events.append(("kafka-start",))

    async def kafka_close(self):
        events.append(("kafka-close",))

    monkeypatch.setattr(KafkaReplayPipeline, "start", kafka_start)
    monkeypatch.setattr(KafkaReplayPipeline, "close", kafka_close)

    async def scenario():
        pipeline = FlinkReplayPipeline("session", (date(2024, 1, 1),), None, KAFKA_SETTINGS, FLINK_SETTINGS)
        pipeline.jobs = Jobs()
        await pipeline.start()
        await pipeline.close()
        assert pipeline.savepoint_path == "file:///savepoint"

    asyncio.run(scenario())
    assert events[0][:2] == ("job-start", "session")
    assert events[1:] == [("kafka-start",), ("kafka-close",), ("job-stop", "job-1")]
