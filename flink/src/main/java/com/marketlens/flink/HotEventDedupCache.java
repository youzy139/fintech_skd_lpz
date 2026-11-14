package com.marketlens.flink;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;

import java.util.Collection;

/** Volatile hot-key cache; Flink ValueState remains the durable dedup authority. */
final class HotEventDedupCache {
    private record CacheKey(String windowKey, String eventId) {}

    private final Cache<CacheKey, Boolean> cache;

    HotEventDedupCache(long maximumEntries) {
        if (maximumEntries < 1) throw new IllegalArgumentException("dedupCacheEntries must be positive");
        this.cache = Caffeine.newBuilder().maximumSize(maximumEntries).build();
    }

    boolean contains(String windowKey, String eventId) {
        return cache.getIfPresent(new CacheKey(windowKey, eventId)) != null;
    }

    void rememberAll(String windowKey, Collection<String> eventIds) {
        for (String eventId : eventIds) {
            cache.put(new CacheKey(windowKey, eventId), Boolean.TRUE);
        }
    }

    long estimatedSize() {
        cache.cleanUp();
        return cache.estimatedSize();
    }
}
