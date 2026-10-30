# 金融市场状态监控平台

2026 年上海科技大学第一届金融科技竞赛参赛项目。

本项目计划基于多资产行情、宏观指标、事件日历和舆情文本，建设覆盖数据接入、统一存储、实时特征计算、市场状态识别、风险预警和可视化的分布式监控平台。

## 项目最终目的

MarketLens 要解决的不是“让 AI 猜明天涨还是跌”，而是：

> 把分散的行情、宏观事件和文本信息整理成可追溯的证据，识别当前处于什么市场环境，在波动、资产联动或状态切换出现异常时及时提示，并解释为什么提示。

最终用户应当能够通过一个 Web 平台完成三件事：

1. **判断环境**：市场当前更像趋势上涨、高波动还是其他状态，主要依据是什么。
2. **发现风险**：哪些指标越过历史异常阈值，哪些资产联动或市场状态发生了变化。
3. **理解并复核**：查看相关行情、特征、预警规则和后续可能关联的新闻/宏观证据，而不是只看到一个无法解释的 AI 结论。

项目定位为市场监控与研究决策支持，**不直接给出买卖指令，不以自动交易或收益率为目标**。风险预警表示“值得关注的统计异常”，不表示风险事件必然发生。

## 我们使用什么数据

全部数据来自赛题提供的历史数据，原始文件只读保留，不移动、不改写。

| 数据类别 | 当前规模 | 在项目中的用途 |
| --- | --- | --- |
| 多资产行情 | 39 个可用资产，314,318 条有效行情 | 计算收益、波动、动量、趋势和资产相关性，是当前市场状态模型的主要输入 |
| 宏观指标 | 31 个 sheet，104,122 条记录 | 后续补充宏观环境特征；字段含义和发布日期需逐项核实 |
| 宏观事件日历 | 185,753 条记录 | 后续按实际公布时间关联宏观事件，不能把统计期误当作发布日期 |
| 商品期货日成交额 | 1,924 条记录 | 后续补充商品市场活跃度和流动性观察 |
| 新闻 | 900,704 条逻辑记录 | 后续做文本检索、事件证据和情绪/主题研究 |
| 科技社媒帖子 | 41,413 条记录 | 后续观察科技主题传播及相关事件证据 |
| 公众号文章索引 | 7,218 条记录 | 按日期、标题、链接和相关方检索；不是文章全文 |
| 全球研究摘要 | 1,000 篇 Markdown | 后续用于研究观点检索和证据整合 |

当前只有**多资产行情**进入市场状态和预警模型。其他数据已经完成接入、检索和原始对象归档，但不能因为“已经入库”就声称已经增强模型。

## 从数据到结果的分析链路

```text
赛题原始文件
  → 文件发现、流式解析、质量检查与原始归档
  → 按事件时间组织数据，保留来源与血缘
  → 行情清洗和滚动特征计算
  → walk-forward 市场状态识别
  → 确定性规则生成风险预警
  → Web 看板、历史回放与证据复核
  → 后续由 LLM 整合文本证据并生成可降级解释
```

具体分为四层：

### 1. 数据层：先保证数据可信、可查、可追溯

- CSV 使用标准解析器流式读取，Excel 处理目标工作簿，保留原始字段、空值和异常证据。
- 建立文件、记录、标签、导入批次、日期和字段统计，支持分页与组合筛选。
- 使用内容哈希和迁移基线检查“总数没变但内容变了”等隐蔽问题。
- 宏观值按公布时间、文本按发布时间进入模型，防止在历史分析中使用当时尚不可知的信息。

### 2. 特征层：把价格变成可比较的市场指标

当前真实计算：

- 市场收益：各价格资产对数收益的横截面均值。
- 波动率：市场收益的 20 日滚动标准差，再年化。
- 动量：各资产 60 日涨跌幅的均值。
- 趋势：价格相对 20 日均线的偏离程度。
- 相关性：60 日窗口内资产收益成对相关系数的均值。

债券 `yield` 不作为价格处理；不同资产保留自己的交易日历，不为了对齐而伪造行情。

### 3. 判断与预警层：模型负责识别，规则负责提示

- 使用滚动历史窗口内的 StandardScaler、PCA 和 KMeans 识别市场状态。
- 每个识别日的训练数据严格早于该日，降低未来数据泄漏风险。
- 根据历史分位数识别高波动、相关性异常，并检测市场状态切换。
- 每条结果保留事件日期、模型版本、特征、状态和预警，便于复核。

后续 LLM 只负责文本结构化、证据整合和自然语言解释，**不直接修改数值特征、市场状态或预警等级**。

### 4. 展示与验证层：不仅给结论，还能重放过程

- Web 平台展示市场总览、状态时间轴、特征、预警和数据中心。
- 历史回放逐日提供当时可见的数据，再计算特征、状态和预警，不是简单播放预计算答案。
- 本地直连用于快速开发与结果基准；Kafka 验证事件传输；Flink 验证日窗口、乱序迟到和故障恢复。

## 技术路线总览

| 层次 | 技术选型与职责 |
| --- | --- |
| 领域与模型 | Python、NumPy、pandas、scikit-learn；`market_core/` 独立实现数据、特征、状态与预警，不依赖 Web 框架 |
| 服务接口 | FastAPI、REST、GraphQL、WebSocket、OpenAPI；`server/` 负责配置、存储、组装和接口 |
| 前端 | React、TypeScript、Vite、ECharts；只展示真实 API 数据 |
| 本地持久化 | SQLite 是默认主读与迁移基线，支持全量/增量导入、分页、标签和模型快照 |
| 分布式存储 | ClickHouse 支持显式主读和按来源代次在线发布；MySQL 管理元数据，MinIO 保存原始对象，Redis 8.0.5 提供可回源热点缓存 |
| 事件与流处理 | Kafka 负责事件传输与重放，Flink 负责事件时间窗口、去重、迟到分流、检查点与 Savepoint |
| 智能增强 | 暂定 DeepSeek，用于文本理解、证据整合和解释；尚未接入，且不是核心链路依赖 |
| 部署与治理 | 后端/前端/Flink Dockerfile、Compose 和 Nginx 已通过默认容器及干净空卷验收；服务拆分、认证权限和分布式限流为后续工作 |

## 为了什么结果，目前达成了什么效果

### 最终交付结果

- 一个可以浏览、筛选和追溯多源数据的数据中心。
- 一套可复现的市场状态判断与风险预警结果。
- 一个能观察时间推进、异常变化和触发证据的 Web 监控平台。
- 一套可验证数据一致性、时间正确性、故障恢复和部署能力的工程链路。
- 后续增加有证据、可降级的智能分析，而不是独立聊天机器人。

### 已经真实验证的工程效果

- 1,046 个输入文件全部接入，共 1,556,492 条逻辑记录，首次全量导入无失败文件。
- 真实行情特征、walk-forward 市场状态和规则预警已经形成完整闭环。
- 数据中心能够服务端分页、组合筛选和展示友好内容，不需要向浏览器一次加载整库。
- 本地、Kafka、Flink 三通道在固定四日真实回放中结果一致；Flink Savepoint 停止与恢复已验证。
- SQLite 全量迁移基线重复核对通过；MySQL 元数据和 MinIO 原始对象已完成全量迁移，1,046 个对象独立回读哈希通过。
- ClickHouse 已完成真实全量迁移与双读；新增按来源代次的在线发布后，真实研究文件连续重发通过内容摘要、计数和全局典型查询核对。
- SQLite 与 ClickHouse 两种显式主读的五组真实 API 结果一致，两实例同日真实回放结果一致；Redis 已验证命中、版本失效和故障回源。
- 当前后端 57 项测试、前端 10 项测试通过，后端分支覆盖率 73.27%，前端生产构建通过。
- 默认八个容器服务已真实启动并完成全量导入；全部 1,046 个对象回读、Kafka/Flink 容器回放、Nginx WebSocket、真实 Chrome 和 Redis 停服回源均已验收。

这些效果证明的是**数据处理、模型链路和工程可靠性**，不代表已经获得投资收益、预测准确率优势或生产级高可用能力。

### 尚未达成

- 新闻、社媒、宏观和商品数据尚未进入回放模型。
- LLM 助手、完整权限、独立微服务和分布式限流尚未完成。
- 当前处理的是历史数据回放，不是实时行情；单节点 Kafka/Flink 也不是高可用集群。
- ClickHouse 冷查询和 Redis 热缓存尚未达到正式版性能目标，完整模型回测、性能和故障恢复报告尚未形成。

## 当前状态

当前版本为 `v0.3.3` 测试版本；阶段 A～E 的部署实现、干净源码目录与全新数据卷复验及整体验收均已完成，并已通过用户体验确认：

- 1,046 个输入文件全部登记并导入本地 SQLite，共 1,556,492 条逻辑记录，首次全量导入无失败文件。
- 39 个可用资产包含 314,318 条行情记录；新闻 900,704 条、科技 41,413 条、宏观日历 185,753 条、研究摘要 1,000 篇，指标工作簿 31 个 sheet 全部处理。
- 数据中心按类型提供时间覆盖、预聚合记录量趋势、字段目录和友好内容列表；原始文件与字段下沉到核对区，HTML 不会注入页面。
- 概览统计随流式导入更新，旧数据库可从已入库记录回填；类型与文件明细均按日期倒序、服务端分页，每页默认 20 条，不把整库发送到浏览器。
- 数据中心支持确定性主题与结构标签，最多同时选择 5 个标签，支持任一标签并集、全部标签交集、组合筛选后的去重总数和记录级标签；可与类型、标题、日期和文件共同筛选。标签只用于检索，不表示情绪或投资判断。
- 首页使用轻量摘要，市场页面与数据中心按需加载；展开原始文件目录时才请求文件分页。
- 计算市场收益、20 日年化波动率、60 日动量、趋势和资产相关性。
- 使用滚动训练窗口内的 StandardScaler、PCA 与 KMeans 逐日识别状态，训练数据严格早于识别日。
- 生成高波动、相关性异常和状态切换预警，提供 REST、GraphQL、WebSocket 和 OpenAPI。
- 真实历史回放按事件日期逐日读取行情，只使用当日及此前历史重新计算特征、状态和预警；支持范围选择、暂停、继续、0.5～10 倍速、重开和断线快照恢复。页面展示事件时间、实际处理时间、输入范围、模型版本与当日新增预警。
- 回放支持本地直连、Kafka 事件和 Flink 窗口三种通道。单节点 Kafka 4.3.2 KRaft 与 `aiokafka` 已实际联通，日批次按日期作 key，消费者去重、缓存乱序、重试并在模型处理成功后手动提交连续位点。
- Flink 2.2.1 Java 作业按事件时间水位线完成 1d 窗口、去重和迟到分流，回放结束控制事件只推进水位线、不产生行情。检查点和 Kafka 事务输出已生效，Savepoint 停止与恢复以及恢复后的 4 天一致性回放已验证；页面展示事件计数。
- 首页与工作台支持双向导航、平滑过渡、锚点滚动和精确回到顶部。

本地默认 SQLite，`STORAGE_MODE=distributed` 可显式切换 ClickHouse；Kafka/Flink 为单节点验证环境，独立微服务、完整权限和 LLM 助手仍未完成。Compose 已完成真实启动和核心链路验收，但这仍不是高可用或完整微服务系统。

**已知性能问题：** Flink 小数据逐日回放明显慢于本地直连；ClickHouse 冷查询约 0.75–1.63 秒，当前分布式 Redis 热查询约 36–71ms，未达正式版 `<10ms` 热访问目标。真实单文件在线重发及全局核对约 30.7 秒，仍有派生刷新与全量核对开销。后续按 [v0.3.4 任务书](docs/v0.3.4-plan.md) 分阶段测量和优化，不通过牺牲一致性或容错提速。

## 本地启动

要求：Windows + Conda + Node.js。以下命令在仓库根目录的 Git Bash 中执行。

```bash
# 首次创建环境；已存在时跳过
conda create -n fintech python=3.12 pip -y
conda run -n fintech python -m pip install -r requirements-dev.txt

# 可选：复制本地私有配置；config.json 与 server/data/ 不会进入 Git
cp server/config.example.json server/config.json

# 首次执行全量导入；后续运行会跳过未变化文件，概览统计随导入生成
PYTHONPATH="C:/Users/15214/Desktop/project/fintech/server;C:/Users/15214/Desktop/project/fintech" PYTHONUTF8=1 C:/ProgramData/miniconda3/envs/fintech/python.exe -m app.services.import_data

# 仅旧版数据库需要：从已入库记录回填概览统计，不重新导入原始文件
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.import_data --rebuild-stats

# 启动后端，首次初始化需要计算真实历史特征
PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000
```

另开终端启动前端：

```bash
cd web
npm install --cache .npm-cache
npm run dev
```

访问 `http://localhost:5173`。后端 OpenAPI 文档位于 `http://localhost:8000/docs`，GraphQL 位于 `http://localhost:8000/graphql`。

## 容器与分布式主读

```bash
cp .env.example .env
# 在 .env 设置本地强密码；不要提交该文件

# Windows 原始摘要含超长中文文件名，首次及摘要变化后先生成短文件名副本
PYTHONPATH=".;server" PYTHONUTF8=1 python -m app.services.prepare_container_data

docker compose config
docker compose up --build
```

预处理只在 `server/data/container-sources/` 生成副本，不修改原始文件。默认编排包含初始化、MySQL、ClickHouse、Redis、MinIO、Kafka、后端和 Nginx 前端；首次全量初始化约需十几分钟。精简开发、可选 Flink、在线增量发布、故障验收和 SQLite 回退见 [阶段 E 部署与验收](docs/stage-e-deployment.md)。

## 可选：启动本地 Kafka 事件通道

默认使用本地直连，不需要 broker。Kafka 验证需要 Java 21；将 [Apache Kafka 4.3.2](https://dlcdn.apache.org/kafka/4.3.2/) 的 `kafka_2.13-4.3.2.tgz` 下载并解压到被 Git 忽略的 `server/data/kafka/`。以下命令在仓库根目录的 Git Bash 执行：

```bash
KAFKA_HOME=server/data/kafka/kafka_2.13-4.3.2
cp server/kafka.example.properties server/data/kafka/kraft.properties
CLUSTER_ID=$("$KAFKA_HOME/bin/kafka-storage.sh" random-uuid)
"$KAFKA_HOME/bin/kafka-storage.sh" format -t "$CLUSTER_ID" -c server/data/kafka/kraft.properties

# 保持此进程运行；显式 file URI 用于避免 Windows 路径被 Log4j 误解析
KAFKA_LOG4J_OPTS="-Dlog4j2.configurationFile=file:///$(pwd -W)/$KAFKA_HOME/config/log4j2.yaml" \
  "$KAFKA_HOME/bin/kafka-server-start.sh" server/data/kafka/kraft.properties
```

另开终端创建单分区主题：

```bash
KAFKA_HOME=server/data/kafka/kafka_2.13-4.3.2
KAFKA_LOG4J_OPTS="-Dlog4j2.configurationFile=file:///$(pwd -W)/$KAFKA_HOME/config/tools-log4j2.yaml" \
  "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server 127.0.0.1:9092 \
  --create --if-not-exists --topic marketlens.replay.days.v1 --partitions 1 --replication-factor 1
```

使用 `KAFKA_ENABLED=true` 启动后端；也可用 `KAFKA_BOOTSTRAP_SERVERS` 和 `KAFKA_TOPIC` 覆盖地址与主题，或在私有 `server/config.json` 中设置 `kafka.enabled`。启动后在“历史回放”选择“Kafka 事件”。`/api/kafka/status` 只表示配置和按需连接方式，实际可用性以生产、消费和位点提交成功为准。

## 可选：启动 Flink 日窗口与容错

需要 Java 21 和 Kafka。下载 [Flink 2.2.1](https://dlcdn.apache.org/flink/flink-2.2.1/) 到 `server/data/flink/flink-2.2.1`，下载 Maven 到 `server/data/maven/`。在仓库根目录执行：

```bash
# 编译 Java 作业；按本机 Maven 路径调整
server/data/maven/apache-maven-3.9.16/bin/mvn -f flink/pom.xml package -DskipTests

# Windows + Git Bash；已运行时会直接返回
bash server/start-flink.sh

# 创建正常窗口与迟到主题，并禁止按墙钟时间自动清理历史回放
KAFKA_HOME=server/data/kafka/kafka_2.13-4.3.2
export KAFKA_LOG4J_OPTS="-Dlog4j2.configurationFile=file:///$(pwd -W)/$KAFKA_HOME/config/tools-log4j2.yaml"
for topic in marketlens.features.days.v1 marketlens.replay.late.v1; do
  "$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server 127.0.0.1:9092 \
    --create --if-not-exists --topic "$topic" --partitions 1 --replication-factor 1
  "$KAFKA_HOME/bin/kafka-configs.sh" --bootstrap-server 127.0.0.1:9092 \
    --alter --entity-type topics --entity-name "$topic" --add-config retention.ms=-1
done
```

通过 Flink REST 上传并运行作业：

```bash
curl --request POST --form "jarfile=@flink/target/marketlens-flink.jar" http://127.0.0.1:8081/jars/upload
# 用响应中的 JAR ID 替换下面的 JAR_ID
JAR_ID=替换为上传响应中的ID
curl --request POST --header "Content-Type: application/json" \
  --data '{"entryClass":"com.marketlens.flink.DailyWindowJob","programArgs":"--checkpointInterval=5000 --checkpointDir=file:///C:/Users/15214/Desktop/project/fintech/server/data/flink/checkpoints","parallelism":1}' \
  "http://127.0.0.1:8081/jars/$JAR_ID/run"
```

使用 `KAFKA_ENABLED=true FLINK_ENABLED=true` 启动后端，在“历史回放”选择“Flink 窗口”。作业每 5 秒检查点一次，窗口结果通过 Kafka 事务提交，后端以 `read_committed` 消费。每轮回放末尾的 `market.replay.control.v1` 只推进水位线，不进入窗口或模型。`POST /jobs/{jobid}/savepoints` 可触发 Savepoint；恢复时使用相同 JAR 和 `savepointPath`。当前 REST 配置只表示按需连接，实际可用性以作业 RUNNING、检查点和回放结果为准。

## 测试与构建

```bash
PYTHONUTF8=1 conda run -n fintech python -m pytest --cov=market_core --cov=server/app --cov-report=term-missing server/tests
cd web && npm test && npm run build
```

## 文档

- [总体架构设计](docs/architecture.md)：项目架构基线与模块职责。
- [v0.3.x 阶段计划](docs/v0.3.x-plan.md)：真实历史回放、Kafka/Flink、分布式存储的实施顺序与验收标准。
- [v0.3.3 任务书](docs/v0.3.3-plan.md)：MySQL、ClickHouse、Redis、MinIO、数据分层血缘、迁移与 Docker Compose；阶段 A～E 及干净空卷验收已完成，等待用户体验。
- [存储契约与迁移基线](docs/storage-contracts.md)：SQLite/后续存储的统一边界、全量内容摘要和迁移核对方法。
- [阶段 B 存储运行与验收](docs/stage-b-storage.md)：MySQL/MinIO 启动、全量迁移、幂等重跑与真实回读校验。
- [阶段 C ClickHouse 运行与验收](docs/stage-c-clickhouse.md)：WSL 2 启动、分层 schema、全量影子迁移与真实双读结果。
- [阶段 D Redis 运行与验收](docs/stage-d-redis.md)：热点缓存、内容版本失效、故障回源与真实 API 验证。
- [阶段 E 部署与验收](docs/stage-e-deployment.md)：Docker/Compose、在线增量发布、主读切换、回退、干净空卷复验和后续事项。
- [v0.3.4 任务书](docs/v0.3.4-plan.md)：服务治理、认证权限、监控展示、性能与故障恢复，包含 Flink 回放性能专项；尚未实施。
- [AGENTS.md](AGENTS.md)：数据口径、竞赛约束和开发注意事项。
- 根目录的赛题 PDF 与发布 PPT：正式竞赛要求及评分依据。

后续应在文档中补充数据口径、API、模型验证、部署和测试方法；功能实现后同步更新本文档。

## 开发与模型配置

- 本地环境为 Conda `fintech`，使用 Python 3.12；依赖固定在 `requirements*.txt`。
- Docker Compose 仍是竞赛要求的交付与验收方式，本地 Conda 环境不替代容器化部署。
- LLM 暂定使用 `deepseek-v4.1flash`，仅用于文本理解、证据整合、解释与问答，本轮尚未接入。
- API 基础地址和模型可用性尚未验证，首次实现调用时需确认。
- 本地敏感配置可放入 `.env` 或被忽略的 `server/config.json`，不得提交真实 API Key；`.env.example` 只提供无密钥模板。
- `server/data/` 保存 SQLite 快照等运行时产物，原始赛题数据仍保留在 `上科大数据合集/`。

## 版本约定

版本号采用 `v主版本.次版本.修订号` 的三段式格式，并通过 Git 标签标记版本。当前版本为 `v0.3.3`。本地提交与标签可以先完成，远程推送必须等待实际体验并明确确认。

当前路线是先以 `v0.2.x` 完善数据接入、存储、检索、质量和展示；数据侧稳定后进入 `v0.3.x`，推进真实历史回放、Kafka/Flink 和分布式基础设施。

### 测试版本：`v0.x`

完整 Web 平台及核心链路完成前，所有版本均属于测试版本，主版本号保持为 `0`。

- 首个可运行测试版本建议命名为 `v0.1.0`。
- 测试阶段可以增加功能、调整架构和修改接口，不承诺稳定性或向后兼容。
- 新功能或阶段性里程碑提升次版本号，例如 `v0.1.0 → v0.2.0`。
- 缺陷修复提升修订号，例如 `v0.1.0 → v0.1.1`。

### 正式版本：`v1.x`

完整网页完成，且数据接入、状态识别、预警、核心 API 和 Docker Compose 一键启动均通过端到端验证后，才能发布首个正式版本 `v1.0.0`。不能仅因页面完成就忽略核心功能与部署验收。完整赛题红线、核心功能、性能和材料门槛见 [v0.3.x 阶段计划](docs/v0.3.x-plan.md#8-v100-正式版合规门槛)。

- 正式版本的缺陷修复提升修订号，例如 `v1.0.0 → v1.0.1`。
- 向后兼容的新功能提升次版本号，例如 `v1.0.0 → v1.1.0`。

文档提交、架构讨论和未形成可运行成果的代码不单独创建版本标签。
