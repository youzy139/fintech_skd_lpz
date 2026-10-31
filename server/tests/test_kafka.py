from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from aiokafka import TopicPartition
from aiokafka.errors import KafkaError
from fastapi.testclient import TestClient

import app.main as main_module
from app.core.config import load_config
from app.main import create_app
from app.services.kafka import KafkaReplayPipeline
from market_core.domain.events import MarketDayEvent
from market_core.domain.replay import AssetObservation, ReplayDayInput
from server.tests.test_replay import sample_series


SETTINGS = {
    "enabled": True,
    "bootstrap_servers": "127.0.0.1:9092",
    "topic": "test.replay.days",
    "topic_partitions": 1,
    "consumer_max_retries": 3,
    "retry_backoff_ms": 0,
}


class FakeConsumer:
    def __init__(self, messages=(), failures=()):
        self.messages = list(messages)
        self.failures = list(failures)
        self.commits = []

    async def getone(self):
        if self.failures:
            raise self.failures.pop(0)
        return self.messages.pop(0)

    async def commit(self, offsets):
        self.commits.append(offsets)


class FakeProducer:
    def __init__(self):
        self.sent = []

    async def start(self):
        pass

    async def send_and_wait(self, topic, key, value):
        self.sent.append((topic, key, value))

    async def stop(self):
        pass


def message(event: MarketDayEvent, offset: int):
    return SimpleNamespace(topic="test.replay.days", partition=0, offset=offset, value=json.dumps(event.to_dict()).encode())


def pipeline(dates=(date(2024, 1, 1), date(2024, 1, 2))):
    return KafkaReplayPipeline("session", tuple(dates), None, SETTINGS)


def event(pipeline: KafkaReplayPipeline, day: date):
    batch = ReplayDayInput(day, (AssetObservation("A", day, 100.0),))
    return MarketDayEvent.from_batch("session", pipeline.run_id, batch)


def test_market_day_event_round_trip_and_validation():
    original = event(pipeline(), date(2024, 1, 1))
    restored = MarketDayEvent.from_dict(original.to_dict())
    assert restored.to_batch() == original.to_batch()
    payload = original.to_dict()
    payload["payload"]["observations"][0]["event_date"] = "2024-01-02"
    try:
        MarketDayEvent.from_dict(payload)
        assert False, "跨日期事件应被拒绝"
    except ValueError as error:
        assert "跨日期" in str(error)


def test_out_of_order_events_wait_and_commit_only_contiguous_offsets():
    async def scenario():
        pipe = pipeline()
        later, earlier = event(pipe, date(2024, 1, 2)), event(pipe, date(2024, 1, 1))
        consumer = FakeConsumer([message(later, 0), message(earlier, 1)])
        pipe.consumer = consumer
        first = await pipe.next(date(2024, 1, 1))
        assert first.event_date == date(2024, 1, 1)
        await pipe.ack(first)
        assert consumer.commits == []
        second = await pipe.next(date(2024, 1, 2))
        await pipe.ack(second)
        assert consumer.commits == [{TopicPartition("test.replay.days", 0): 2}]
    asyncio.run(scenario())


def test_duplicate_delivery_is_skipped_and_committed():
    async def scenario():
        pipe = pipeline()
        first, second = event(pipe, date(2024, 1, 1)), event(pipe, date(2024, 1, 2))
        consumer = FakeConsumer([message(first, 0), message(first, 1), message(second, 2)])
        pipe.consumer = consumer
        batch = await pipe.next(date(2024, 1, 1))
        await pipe.ack(batch)
        following = await pipe.next(date(2024, 1, 2))
        assert following.event_date == date(2024, 1, 2)
        assert pipe.stats["duplicate_events"] == 1
        await pipe.ack(following)
        assert consumer.commits[-1] == {TopicPartition("test.replay.days", 0): 3}
    asyncio.run(scenario())


def test_transient_consumer_failure_is_retried():
    async def scenario():
        pipe = pipeline((date(2024, 1, 1),))
        expected = event(pipe, date(2024, 1, 1))
        pipe.consumer = FakeConsumer([message(expected, 0)], [KafkaError("temporary")])
        batch = await pipe.next(date(2024, 1, 1))
        assert batch.event_id == expected.event_id
        assert pipe.stats["retry_count"] == 1
    asyncio.run(scenario())


def test_unacknowledged_event_is_redelivered_after_consumer_restart():
    async def scenario():
        first = pipeline((date(2024, 1, 1),))
        expected = event(first, date(2024, 1, 1))
        consumer = FakeConsumer([message(expected, 0)])
        first.consumer = consumer
        batch = await first.next(date(2024, 1, 1))
        assert consumer.commits == []
        recovered = pipeline((date(2024, 1, 1),))
        recovered.run_id = first.run_id
        recovered_consumer = FakeConsumer([message(expected, 0)])
        recovered.consumer = recovered_consumer
        replayed = await recovered.next(date(2024, 1, 1))
        await recovered.ack(replayed)
        assert replayed.event_id == batch.event_id
        assert recovered_consumer.commits == [{TopicPartition("test.replay.days", 0): 1}]
    asyncio.run(scenario())


def test_producer_uses_date_keys_and_manual_consumer_commit(monkeypatch):
    async def scenario():
        consumer = SimpleNamespace(start=lambda: asyncio.sleep(0), stop=lambda: asyncio.sleep(0))
        producer = FakeProducer()
        monkeypatch.setattr("app.services.kafka.AIOKafkaConsumer", lambda *args, **kwargs: consumer)
        monkeypatch.setattr("app.services.kafka.AIOKafkaProducer", lambda *args, **kwargs: producer)
        pipe = pipeline((date(2024, 1, 1), date(2024, 1, 2)))
        pipe.catalog = SimpleNamespace(read=lambda day: ReplayDayInput(day, (AssetObservation("A", day, 100.0),)))
        await pipe.start()
        await pipe.close()
        assert [item[1].decode() for item in producer.sent] == ["2024-01-01", "2024-01-02"]
        assert pipe.stats["produced_events"] == 2
        assert pipe.timing["consumer_start_ms"] >= 0
        assert pipe.timing["producer_start_ms"] >= 0
        assert pipe.timing["production_ms"] >= 0
    asyncio.run(scenario())


def test_kafka_api_requires_enabled_channel(monkeypatch):
    config = replace(load_config(), kafka={**SETTINGS, "enabled": False})
    monkeypatch.setattr(main_module, "load_config", lambda: config)
    with TestClient(create_app(SimpleNamespace(series=sample_series()), initialize=False)) as http:
        status = http.get("/api/kafka/status")
        assert status.status_code == 200
        assert status.json()["enabled"] is False
        response = http.post("/api/replay/sessions", json={"start_date": "2024-03-04", "end_date": "2024-03-04", "mode": "kafka"})
        assert response.status_code == 422
        local = http.post("/api/replay/sessions", json={"start_date": "2024-03-04", "end_date": "2024-03-04", "mode": "local"})
        assert local.status_code == 201
        assert local.json()["mode"] == "local"


def test_end_of_input_control_advances_replay_without_market_observations():
    control = MarketDayEvent.end_of_input("session", "run", date(2024, 1, 2))
    restored = MarketDayEvent.from_dict(control.to_dict())
    assert restored.event_type == "market.replay.control.v1"
    assert restored.observations == ()
    assert restored.event_date == date(2024, 1, 2)
    payload = control.to_dict()
    payload["payload"]["observations"] = [{"code": "A", "event_date": "2024-01-02", "value": 100}]
    try:
        MarketDayEvent.from_dict(payload)
        assert False, "控制事件不应携带行情"
    except ValueError as error:
        assert "控制事件" in str(error)
