package com.marketlens.flink;

import org.junit.jupiter.api.Test;

import java.util.HashSet;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;

class DailyEventDeduplicatorTest {
    private static MarketDayEvent event(String eventId) {
        MarketDayEvent event = new MarketDayEvent();
        event.eventId = eventId;
        return event;
    }

    @Test
    void hotDuplicatesSkipStateReadsAfterTheFirstWindowFiring() throws Exception {
        DailyEventDeduplicator deduplicator = new DailyEventDeduplicator(10);
        HashSet<String> state = new HashSet<>();
        AtomicInteger reads = new AtomicInteger();
        MarketDayEvent original = event("event-a");

        assertSame(original, deduplicator.deduplicate("day-1", List.of(original), () -> {
            reads.incrementAndGet();
            return state;
        }, value -> state.addAll(value)));
        assertNull(deduplicator.deduplicate("day-1", List.of(event("event-a")), () -> {
            reads.incrementAndGet();
            return state;
        }, value -> state.addAll(value)));
        assertEquals(1, reads.get());
        assertEquals(1, state.size());
    }

    @Test
    void coldCacheAfterRestoreStillUsesPersistentState() throws Exception {
        HashSet<String> persisted = new HashSet<>(List.of("event-a"));
        AtomicInteger reads = new AtomicInteger();
        DailyEventDeduplicator restored = new DailyEventDeduplicator(10);

        assertNull(restored.deduplicate("day-1", List.of(event("event-a")), () -> {
            reads.incrementAndGet();
            return persisted;
        }, value -> {
        }));
        assertEquals(1, reads.get());
    }

    @Test
    void sameEventIdOnAnotherDayIsNotDiscarded() throws Exception {
        DailyEventDeduplicator deduplicator = new DailyEventDeduplicator(10);
        HashSet<String> firstDay = new HashSet<>();
        HashSet<String> secondDay = new HashSet<>();
        MarketDayEvent second = event("event-a");

        deduplicator.deduplicate("day-1", List.of(event("event-a")), () -> firstDay, value -> firstDay.addAll(value));
        assertSame(second, deduplicator.deduplicate("day-2", List.of(second), () -> secondDay, value -> secondDay.addAll(value)));
    }

    @Test
    void conflictingUniqueBatchesDoNotPolluteStateOrHotCache() throws Exception {
        DailyEventDeduplicator deduplicator = new DailyEventDeduplicator(10);
        HashSet<String> state = new HashSet<>();
        AtomicInteger writes = new AtomicInteger();
        DailyEventDeduplicator.StateReader reader = () -> new HashSet<>(state);
        DailyEventDeduplicator.StateWriter writer = value -> {
            writes.incrementAndGet();
            state.clear();
            state.addAll(value);
        };

        assertThrows(IllegalArgumentException.class, () -> deduplicator.deduplicate("day-1", List.of(event("event-a"), event("event-b")), reader, writer));
        assertEquals(0, writes.get());
        assertEquals(0, state.size());
        MarketDayEvent retry = event("event-a");
        assertSame(retry, deduplicator.deduplicate("day-1", List.of(retry), reader, writer));
        assertEquals(1, writes.get());
    }
}
