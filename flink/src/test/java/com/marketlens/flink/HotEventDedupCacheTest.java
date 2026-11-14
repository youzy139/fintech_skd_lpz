package com.marketlens.flink;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HotEventDedupCacheTest {
    @Test
    void scopesEventIdsToWindowAndBoundsLocalCache() {
        HotEventDedupCache cache = new HotEventDedupCache(2);
        cache.rememberAll("day-1", List.of("event-a"));

        assertTrue(cache.contains("day-1", "event-a"));
        assertFalse(cache.contains("day-2", "event-a"));
        assertFalse(cache.contains("day-1", "event-b"));

        cache.rememberAll("day-1", List.of("event-b", "event-c"));
        assertEquals(2, cache.estimatedSize());
        assertEquals(2, List.of("event-a", "event-b", "event-c").stream().filter(eventId -> cache.contains("day-1", eventId)).count());
    }

    @Test
    void rejectsUnboundedOrInvalidConfiguration() {
        assertThrows(IllegalArgumentException.class, () -> new HotEventDedupCache(0));
        assertThrows(IllegalArgumentException.class, () -> new HotEventDedupCache(-1));
    }
}
