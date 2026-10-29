from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.errors import KafkaError

from market_core.domain.events import MarketDayEvent
from market_core.domain.replay import ReplayDayInput


class KafkaReplayPipeline:
    def __init__(self, session_id: str, dates: tuple[date, ...], catalog, settings: dict[str, Any]):
        self.session_id = session_id
        self.run_id = uuid4().hex
        self.dates = dates
        self.catalog = catalog
        self.settings = settings
        self.producer: AIOKafkaProducer | None = None
        self.consumer: AIOKafkaConsumer | None = None
        self.buffered: dict[date, tuple[ReplayDayInput, Any]] = {}
        self.pending: dict[str, Any] = {}
        self.processed_ids: set[str] = set()
        self.processed_offsets: set[tuple[TopicPartition, int]] = set()
        self.next_offsets: dict[TopicPartition, int] = {}
        self.stats = {"produced_events": 0, "consumed_events": 0, "duplicate_events": 0, "retry_count": 0, "commit_count": 0}

    async def start(self) -> None:
        if not self.settings.get("enabled", False):
            raise RuntimeError("Kafka 事件通道尚未启用")
        self.consumer = AIOKafkaConsumer(
            self.settings["topic"],
            bootstrap_servers=self.settings["bootstrap_servers"],
            group_id=f"marketlens-{self.session_id}-{self.run_id}",
            client_id=f"marketlens-replay-{self.session_id}",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            isolation_level="read_committed" if self.settings.get("read_committed") else "read_uncommitted",
        )
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.settings["bootstrap_servers"],
            client_id=f"marketlens-producer-{self.session_id}",
            acks="all",
            enable_idempotence=True,
            retry_backoff_ms=self.settings.get("retry_backoff_ms", 200),
        )
        await self.consumer.start()
        await self.producer.start()
        for event_date in self.dates:
            event = MarketDayEvent.from_batch(self.session_id, self.run_id, self.catalog.read(event_date))
            await self.producer.send_and_wait(
                self.settings.get("produce_topic", self.settings["topic"]),
                key=event.event_date.isoformat().encode("utf-8"),
                value=json.dumps(event.to_dict(), ensure_ascii=False).encode("utf-8"),
            )
            self.stats["produced_events"] += 1
        if self.settings.get("emit_end_of_input"):
            control = MarketDayEvent.end_of_input(self.session_id, self.run_id, self.dates[-1])
            await self.producer.send_and_wait(
                self.settings.get("produce_topic", self.settings["topic"]),
                key=control.event_date.isoformat().encode("utf-8"),
                value=json.dumps(control.to_dict(), ensure_ascii=False).encode("utf-8"),
            )

    async def _commit_message(self, message: Any) -> None:
        partition = TopicPartition(message.topic, message.partition)
        self.next_offsets.setdefault(partition, message.offset)
        self.processed_offsets.add((partition, message.offset))
        next_offset = self.next_offsets[partition]
        while (partition, next_offset) in self.processed_offsets:
            self.processed_offsets.remove((partition, next_offset))
            next_offset += 1
        if next_offset != self.next_offsets[partition]:
            await self.consumer.commit({partition: next_offset})
            self.next_offsets[partition] = next_offset
            self.stats["commit_count"] += 1

    async def _get_message(self) -> Any:
        max_retries = self.settings.get("consumer_max_retries", 3)
        for attempt in range(max_retries + 1):
            try:
                return await self.consumer.getone()
            except KafkaError as error:
                if attempt == max_retries:
                    raise RuntimeError("Kafka 消费在重试后仍然失败") from error
                self.stats["retry_count"] += 1
                await asyncio.sleep(self.settings.get("retry_backoff_ms", 200) / 1000 * (attempt + 1))

    async def next(self, expected_date: date) -> ReplayDayInput:
        if expected_date in self.buffered:
            batch, message = self.buffered.pop(expected_date)
            self.pending[batch.event_id] = message
            return batch
        while True:
            message = await self._get_message()
            partition = TopicPartition(message.topic, message.partition)
            self.next_offsets.setdefault(partition, message.offset)
            event = MarketDayEvent.from_dict(json.loads(message.value.decode("utf-8")))
            if event.session_id != self.session_id or event.run_id != self.run_id:
                await self._commit_message(message)
                continue
            self.stats["consumed_events"] += 1
            if event.event_id in self.processed_ids:
                self.stats["duplicate_events"] += 1
                await self._commit_message(message)
                continue
            if event.event_date not in self.dates:
                await self._commit_message(message)
                continue
            batch = event.to_batch()
            if event.event_date == expected_date:
                self.pending[event.event_id] = message
                return batch
            if event.event_date in self.buffered:
                raise ValueError(f"事件日期 {event.event_date} 存在不同的重复批次")
            self.buffered[event.event_date] = (batch, message)

    async def ack(self, batch: ReplayDayInput) -> None:
        if not batch.event_id or batch.event_id not in self.pending:
            raise RuntimeError("无法确认未知行情事件")
        message = self.pending.pop(batch.event_id)
        await self._commit_message(message)
        self.processed_ids.add(batch.event_id)

    async def close(self) -> None:
        if self.consumer:
            await self.consumer.stop()
        if self.producer:
            await self.producer.stop()
