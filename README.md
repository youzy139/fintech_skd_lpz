# 金融市场状态监控平台

2026 年上海科技大学第一届金融科技竞赛参赛项目。

本项目计划基于多资产行情、宏观指标、事件日历和舆情文本，建设覆盖数据接入、统一存储、实时特征计算、市场状态识别、风险预警和可视化的分布式监控平台。

## 当前状态

当前为 `v0.3.2` 测试版本，已完成全量赛题数据接入与真实资产市场监控闭环：

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

当前 SQLite 是本地持久化实现，Kafka 与 Flink 均为本地单节点验证环境，不代表完整分布式改造完成。MySQL/ClickHouse/Redis/MinIO、独立微服务、完整权限、LLM 助手和 Docker Compose 仍是后续工作。

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

## 项目定位

以数据平台为地基、市场状态模型为核心、Web 监控平台为交付主体，LLM 作为可降级的智能分析增强模块。

核心业务流程为：

> 状态判断 → 预警决策 → 分析建议

- 数值特征与市场状态主要由确定性代码和数学模型计算。
- 预警等级由可配置规则与异常检测产生。
- LLM 负责文本信息提取、证据整合、状态解释和自然语言问答，不直接修改核心判断结果。
- 第一版不以自动交易、多 Agent 协作或 RAG 聊天页面作为系统主体。

## 文档

- [总体架构设计](docs/architecture.md)：项目架构基线与模块职责。
- [v0.3.x 阶段计划](docs/v0.3.x-plan.md)：真实历史回放、Kafka/Flink、分布式存储的实施顺序与验收标准。
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

版本号采用 `v主版本.次版本.修订号` 的三段式格式，并通过 Git 标签标记版本。当前版本为 `v0.3.2`。本地提交与标签可以先完成，远程推送必须等待实际体验并明确确认。

当前路线是先以 `v0.2.x` 完善数据接入、存储、检索、质量和展示；数据侧稳定后进入 `v0.3.x`，推进真实历史回放、Kafka/Flink 和分布式基础设施。

### 测试版本：`v0.x`

完整 Web 平台及核心链路完成前，所有版本均属于测试版本，主版本号保持为 `0`。

- 首个可运行测试版本建议命名为 `v0.1.0`。
- 测试阶段可以增加功能、调整架构和修改接口，不承诺稳定性或向后兼容。
- 新功能或阶段性里程碑提升次版本号，例如 `v0.1.0 → v0.2.0`。
- 缺陷修复提升修订号，例如 `v0.1.0 → v0.1.1`。

### 正式版本：`v1.x`

完整网页完成，且数据接入、状态识别、预警、核心 API 和 Docker Compose 一键启动均通过端到端验证后，才能发布首个正式版本 `v1.0.0`。不能仅因页面完成就忽略核心功能与部署验收。

- 正式版本的缺陷修复提升修订号，例如 `v1.0.0 → v1.0.1`。
- 向后兼容的新功能提升次版本号，例如 `v1.0.0 → v1.1.0`。

文档提交、架构讨论和未形成可运行成果的代码不单独创建版本标签。
