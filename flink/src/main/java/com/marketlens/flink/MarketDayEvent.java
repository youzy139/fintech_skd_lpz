package com.marketlens.flink;

import java.util.List;

public class MarketDayEvent {
    public int schemaVersion;
    public String eventType;
    public String eventId;
    public String sessionId;
    public String runId;
    public String eventTime;
    public String replayTime;
    public String source;
    public Payload payload;
    public long windowStart;
    public long windowEnd;
    public int inputRecords;
    public int assetCount;

    public MarketDayEvent() {}

    public static class Payload {
        public List<AssetObservation> observations;

        public Payload() {}
    }
}
