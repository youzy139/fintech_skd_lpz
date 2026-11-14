package com.marketlens.flink;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;

final class DailyEventDeduplicator {
    @FunctionalInterface
    interface StateReader {
        HashSet<String> read() throws Exception;
    }

    @FunctionalInterface
    interface StateWriter {
        void write(HashSet<String> value) throws Exception;
    }

    private final HotEventDedupCache hotEventIds;

    DailyEventDeduplicator(long maximumEntries) {
        this.hotEventIds = new HotEventDedupCache(maximumEntries);
    }

    MarketDayEvent deduplicate(String key, Iterable<MarketDayEvent> elements, StateReader stateReader, StateWriter stateWriter) throws Exception {
        HashSet<String> seen = null;
        MarketDayEvent result = null;
        List<String> checkedEventIds = new ArrayList<>();
        for (MarketDayEvent event : elements) {
            if (hotEventIds.contains(key, event.eventId)) continue;
            if (seen == null) {
                seen = stateReader.read();
                if (seen == null) seen = new HashSet<>();
            }
            checkedEventIds.add(event.eventId);
            if (!seen.add(event.eventId)) continue;
            if (result != null) throw new IllegalArgumentException("Conflicting batches for " + key);
            result = event;
        }
        if (seen == null) return null;
        stateWriter.write(seen);
        hotEventIds.rememberAll(key, checkedEventIds);
        return result;
    }
}
