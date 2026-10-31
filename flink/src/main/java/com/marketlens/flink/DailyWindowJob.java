package com.marketlens.flink;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import org.apache.flink.api.common.eventtime.SerializableTimestampAssigner;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.functions.MapFunction;
import org.apache.flink.api.common.functions.OpenContext;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.api.common.typeinfo.TypeHint;
import org.apache.flink.api.common.typeinfo.TypeInformation;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.configuration.CheckpointingOptions;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.configuration.ExternalizedCheckpointRetention;
import org.apache.flink.connector.kafka.source.enumerator.initializer.OffsetsInitializer;
import org.apache.flink.streaming.api.CheckpointingMode;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.datastream.SingleOutputStreamOperator;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.windowing.ProcessWindowFunction;
import org.apache.flink.streaming.api.windowing.assigners.TumblingEventTimeWindows;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;
import org.apache.flink.util.ParameterTool;

import java.time.Duration;
import java.time.Instant;
import java.util.Comparator;
import java.util.HashSet;

public class DailyWindowJob {
    private static final ObjectMapper MAPPER = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);

    public static void main(String[] args) throws Exception {
        ParameterTool params = ParameterTool.fromArgs(args);
        String brokers = params.get("bootstrapServers", "127.0.0.1:9092");
        String inputTopic = params.get("inputTopic", "marketlens.replay.days.v1");
        String outputTopic = params.get("outputTopic", "marketlens.features.days.v1");
        String lateTopic = params.get("lateTopic", "marketlens.replay.late.v1");
        String sessionId = params.getRequired("sessionId");
        String runId = params.getRequired("runId");
        String groupId = params.get("groupId", "marketlens-flink-" + runId);
        long checkpointInterval = params.getLong("checkpointInterval", 5000L);
        String checkpointDir = params.get("checkpointDir", "file:///" + System.getProperty("user.dir").replace("\\", "/") + "/server/data/flink/checkpoints");

        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
        env.setParallelism(1);
        env.enableCheckpointing(checkpointInterval, CheckpointingMode.EXACTLY_ONCE);
        env.getCheckpointConfig().setMinPauseBetweenCheckpoints(1000L);
        env.getCheckpointConfig().setExternalizedCheckpointRetention(ExternalizedCheckpointRetention.RETAIN_ON_CANCELLATION);
        Configuration configuration = new Configuration();
        configuration.set(CheckpointingOptions.CHECKPOINT_STORAGE, "filesystem");
        configuration.set(CheckpointingOptions.CHECKPOINTS_DIRECTORY, checkpointDir);
        env.configure(configuration);

        KafkaSource<MarketDayEvent> source = KafkaSource.<MarketDayEvent>builder()
                .setBootstrapServers(brokers)
                .setTopics(inputTopic)
                .setGroupId(groupId)
                .setStartingOffsets(OffsetsInitializer.latest())
                .setValueOnlyDeserializer(new MarketDayEventDeserializer())
                .setProperty("commit.offsets.on.checkpoint", "true")
                .setProperty("enable.auto.commit", "false")
                .build();

        WatermarkStrategy<MarketDayEvent> watermarks = WatermarkStrategy
                .<MarketDayEvent>forBoundedOutOfOrderness(Duration.ofDays(2))
                .withTimestampAssigner((SerializableTimestampAssigner<MarketDayEvent>) (event, timestamp) -> {
                    Instant eventTime = Instant.parse(event.eventTime + "T00:00:00Z");
                    return ("market.replay.control.v1".equals(event.eventType)
                            ? eventTime.plus(Duration.ofDays(3))
                            : eventTime).toEpochMilli();
                })
                .withIdleness(Duration.ofSeconds(30));

        OutputTag<MarketDayEvent> lateEvents = new OutputTag<>("late-market-days") {};
        SingleOutputStreamOperator<MarketDayEvent> windows = env
                .fromSource(source, WatermarkStrategy.noWatermarks(), "Market day Kafka source").uid("market-day-source")
                .filter(event -> sessionId.equals(event.sessionId) && runId.equals(event.runId)).uid("current-run-only")
                .assignTimestampsAndWatermarks(watermarks).uid("run-event-time")
                .filter(event -> "market.replay.day.v1".equals(event.eventType)).uid("market-day-only")
                .keyBy(event -> event.sessionId + "|" + event.runId + "|" + event.eventTime)
                .window(TumblingEventTimeWindows.of(Duration.ofDays(1)))
                .allowedLateness(Duration.ofDays(2))
                .sideOutputLateData(lateEvents)
                .process(new DailyDedupWindow()).uid("daily-dedup-window");

        DataStream<String> output = windows.map(new JsonMapper()).uid("window-json");
        output.sinkTo(kafkaSink(brokers, outputTopic, "marketlens-day-window-v1-" + runId + "-")).uid("window-sink");
        windows.getSideOutput(lateEvents)
                .map(new JsonMapper()).uid("late-json")
                .sinkTo(kafkaSink(brokers, lateTopic, "marketlens-late-window-v1-" + runId + "-")).uid("late-sink");

        env.execute("MarketLens event-time daily windows " + sessionId + "/" + runId);
    }

    private static KafkaSink<String> kafkaSink(String brokers, String topic, String transactionalPrefix) {
        return KafkaSink.<String>builder()
                .setBootstrapServers(brokers)
                .setRecordSerializer(KafkaRecordSerializationSchema.<String>builder()
                        .setTopic(topic)
                        .setValueSerializationSchema(new SimpleStringSchema())
                        .build())
                .setDeliveryGuarantee(org.apache.flink.connector.base.DeliveryGuarantee.EXACTLY_ONCE)
                .setTransactionalIdPrefix(transactionalPrefix)
                .setProperty("transaction.timeout.ms", "60000")
                .build();
    }

    private static class JsonMapper implements MapFunction<MarketDayEvent, String> {
        @Override
        public String map(MarketDayEvent event) throws Exception {
            return MAPPER.writeValueAsString(event);
        }
    }

    private static class DailyDedupWindow extends ProcessWindowFunction<MarketDayEvent, MarketDayEvent, String, TimeWindow> {
        private transient ValueState<HashSet<String>> seenEventIds;

        @Override
        public void open(OpenContext openContext) {
            seenEventIds = getRuntimeContext().getState(new ValueStateDescriptor<>("seen-event-ids", TypeInformation.of(new TypeHint<HashSet<String>>() {})));
        }

        @Override
        public void process(String key, Context context, Iterable<MarketDayEvent> elements, Collector<MarketDayEvent> out) throws Exception {
            HashSet<String> seen = seenEventIds.value();
            if (seen == null) seen = new HashSet<>();
            MarketDayEvent result = null;
            for (MarketDayEvent event : elements) {
                if (!seen.add(event.eventId)) continue;
                if (result != null) throw new IllegalArgumentException("Conflicting batches for " + key);
                result = event;
            }
            seenEventIds.update(seen);
            if (result == null) return;
            result.payload.observations.sort(Comparator.comparing(observation -> observation.code));
            long assets = result.payload.observations.stream().map(observation -> observation.code).distinct().count();
            if (assets != result.payload.observations.size()) throw new IllegalArgumentException("Duplicate asset in " + key);
            result.windowStart = context.window().getStart();
            result.windowEnd = context.window().getEnd();
            result.inputRecords = result.payload.observations.size();
            result.assetCount = (int) assets;
            out.collect(result);
        }
    }
}
