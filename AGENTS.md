# AGENTS.md

## 项目概览

本目录是 **2026 年上海科技大学第一届金融科技竞赛参赛项目**，产品名为 **MarketLens**，当前版本为 `v0.3.3` 测试版本。项目基于多资产行情、宏观指标、事件日历和舆情文本，建设市场状态（Market Regime）监控平台，覆盖数据接入、特征计算、状态识别、风险预警和可视化。

当前已经实现的本地闭环：

- 发现并导入全部 1,046 个赛题输入文件，本地 SQLite 中共有 1,556,492 条逻辑记录，当前文件级导入错误为 0。
- 读取 39 个可用资产序列，保留原始交易日历、`close`/`yield` 字段差异及数据质量统计。
- 计算市场收益、年化波动率、动量、趋势和资产相关性，使用滚动历史窗口内的 StandardScaler、PCA 与 KMeans 逐日识别状态。
- 生成高波动、相关性异常和状态切换预警。
- 提供 REST、GraphQL、WebSocket、OpenAPI 和简单进程内限流；真实历史回放支持本地直连、Kafka 事件和 Flink 窗口三种输入通道，最终由同一 Python 模型计算特征、状态和预警。
- Kafka 4.3.2 单节点 KRaft 与 Flink 2.2.1 单 JobManager/TaskManager 已实际联通。每次回放运行使用独立 Java 作业和独立事件时间水位线，完成 1d 窗口、去重和迟到分流，使用检查点与 Kafka 事务输出；连续运行、重开和 Savepoint 停止与恢复已验证。
- React 工作台包含网站首页、市场总览、状态分析、历史回放、特征分析、预警中心和数据中心；首页使用轻量摘要，各主要页面按需加载。数据中心提供预聚合概览、时间覆盖、字段目录、友好内容、服务端分页和安全的原始字段核对；最多 5 个标签支持并集/交集、去重总数和组合筛选。
- 已有后端 pytest、前端 Vitest、分支覆盖率配置和生产构建流程。

**当前实现不是完整分布式系统。** 本地默认 SQLite，可通过 `STORAGE_MODE=distributed` 显式切换 ClickHouse 主读；MySQL/MinIO 已进入发布链路，Redis 可回源。ClickHouse 按来源代次在线发布已实现并完成真实小文件重发，但独立微服务、完整认证授权和 LLM 助手未落地。Docker Desktop、八个默认容器和可选 Flink 已真实启动，全量导入、对象回读、Kafka/Flink 回放、Nginx WebSocket、Chrome、故障恢复及干净源码目录与空卷复验均已通过。真实历史回放不等于实时行情，不得把竞赛目标或性能指标描述成已经达标。

`v0.3.0` 完成本地回放，`v0.3.1` 完成 Kafka，`v0.3.2` 完成 Flink，当前最新版本标签 `v0.3.3` 完成分布式存储、在线增量发布与容器部署。`v0.3.4` 首批契约、观测、计时、基准和 Flink 连续回放修复已通过用户体验确认，后端 67 项、前端 10 项测试通过，覆盖率 73.01%；完整版本尚未打标签。下一步实现会话持久化与后端重启恢复；完整待办见 `docs/v0.3.4-plan.md` 与 `docs/v0.3.4-observability.md`。

核心业务流程为“状态判断 → 预警决策 → 分析建议”。数值特征与状态由数学模型计算，预警由确定性规则产生；规划中的 LLM 只负责文本理解、证据整合与解释，不应成为核心链路的单点依赖。

## 技术栈与关键配置

| 文件 | 实际用途 |
| --- | --- |
| `environment.yml` | Conda 环境 `fintech`，仅固定 Python 3.12 和 pip |
| `requirements.txt` | 固定版本的运行依赖：FastAPI、Uvicorn、aiokafka、NumPy、pandas、scikit-learn、Strawberry GraphQL、openpyxl、PyMySQL、minio、clickhouse-connect、redis 等 |
| `requirements-dev.txt` | 引入运行依赖，并增加 pytest、pytest-cov、httpx |
| `pyproject.toml` | 只配置 pytest 路径和 Coverage；不是 Python 包构建配置，也不声明项目依赖 |
| `server/config.example.json` | 无密钥运行配置模板，包含数据目录、SQLite、模型、回放、Kafka、Flink、MySQL、MinIO、ClickHouse、Redis 和 CORS 参数 |
| `flink/pom.xml` | Flink 2.2.1、Kafka Connector 5.0.0、Java 17 与 Maven Shade 构建 |
| `web/package.json` | React 19、TypeScript 5.7、Vite 6、ECharts 5、Vitest 3 及前端脚本 |
| `web/package-lock.json` | npm 锁文件，锁文件版本为 3 |
| `web/tsconfig.json` | TypeScript 严格模式、ES2022、Bundler 模块解析、`noEmit` |
| `web/vite.config.ts` | React 插件、开发代理和 Vitest 的 jsdom 配置 |
| `.gitignore` | 忽略原始数据、本地密钥、私有配置、SQLite、依赖目录和构建/测试产物 |

后端使用 Python 3.12 和标准库 `sqlite3`，不依赖 ORM。前端使用函数组件和 React Hooks，无路由库、状态管理库或独立 CSS 框架。当前没有配置 Ruff、Black、mypy、ESLint、Prettier，也没有前端覆盖率脚本；不要声称这些检查已存在。

`server/app/core/config.py` 优先读取 `MARKETLENS_CONFIG` 指定文件，其次是被 Git 忽略的 `server/config.json`，最后回退 `server/config.example.json`；`DATA_ROOT`、`DATABASE_PATH` 和各服务地址可用环境变量覆盖。相对路径基于所选配置文件目录。默认模型参数为：分析起点 2015-01-01、最少历史 504 个有效特征日、训练窗口 756 日、每 63 日重训、20 日波动窗口、60 日动量窗口、3 个聚类、随机种子 42。`STORAGE_MODE=local|distributed` 显式选择目录主读，distributed 必须同时 `CLICKHOUSE_ENABLED=true`，否则拒绝启动；本地默认 SQLite，distributed 使用 ClickHouse，不会静默切换。Kafka 默认关闭，用 `KAFKA_ENABLED=true` 开启，地址与主题由 `KAFKA_BOOTSTRAP_SERVERS`、`KAFKA_TOPIC` 覆盖；`aiokafka` 生产者没有公开 `retries` 参数。Flink 默认关闭，用 `FLINK_ENABLED=true` 开启，`FLINK_REST_URL` 默认 `http://127.0.0.1:8081`，Flink 模式要求 Kafka 同时启用；`FLINK_CHECKPOINT_DIR`、`FLINK_CHECKPOINT_INTERVAL_MS`、`FLINK_JOB_START_TIMEOUT_MS` 和 `FLINK_JOB_STOP_TIMEOUT_MS` 控制作业存储与生命周期。MySQL/MinIO/ClickHouse/Redis 默认关闭，密码分别通过 `MYSQL_PASSWORD`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`CLICKHOUSE_PASSWORD`、`REDIS_PASSWORD` 或私有配置注入，示例配置不得包含真实凭据。Redis 默认 `127.0.0.1:6379`、TTL 60 秒，缓存键包含当前发布代次摘要和全部查询参数，故障自动回到显式主存储。

## 目录与模块职责

```text
.
├── market_core/                  # 独立领域与算法核心，不依赖 FastAPI、server 或 web
│   ├── domain/
│   │   ├── market.py            # 资产、数据质量和预警数据类
│   │   ├── events.py            # Kafka 日批次事件结构与校验
│   │   ├── replay.py            # 回放时钟、逐日输入与结果数据类
│   │   ├── sources.py           # 来源文件、来源记录和导入结果数据类
│   │   └── tags.py              # 确定性主题关键词与结构字段标签规则
│   ├── ingestion/
│   │   ├── assets.py            # 资产目录读取、行情校验、重复日期与非法行处理
│   │   └── sources.py           # 固定数据源发现及 CSV、Excel、Markdown 流式适配
│   └── models/
│       ├── features.py          # 多资产行情面板与市场特征
│       ├── regime.py            # walk-forward 状态识别及连续回放识别会话
│       ├── replay.py            # 可见历史、逐日特征/状态/预警计算
│       └── alerts.py            # 高波动、相关性异常和状态切换规则
├── server/
│   ├── app/
│   │   ├── api/                 # system、market、data、replay 路由与请求契约
│   │   ├── core/config.py       # 配置加载、路径解析和 Kafka 环境变量覆盖
│   │   ├── core/observability.py # 请求 ID、错误契约、结构化日志与进程内指标
│   │   ├── services/
│   │   │   ├── import_data.py   # 全量/增量导入及旧库统计回填入口
│   │   │   ├── contracts.py     # 目录读写与快照存储协议
│   │   │   ├── cache.py         # Redis JSON 缓存、内容版本键与故障回源包装
│   │   │   ├── catalog.py       # 文件、记录、预聚合概览和导入批次的 SQLite 存取
│   │   │   ├── migration_baseline.py # SQLite 全量内容摘要、查询基线与差异核对
│   │   │   ├── mysql_metadata.py # MySQL 元数据 schema 迁移、复制与对账
│   │   │   ├── object_archive.py # MinIO 内容寻址归档与回读哈希
│   │   │   ├── stage_b_migration.py # 阶段 B 幂等迁移与只读校验入口
│   │   │   ├── clickhouse_store.py # ClickHouse 主读、当前代次视图、发布指针和查询锁
│   │   │   ├── clickhouse_migration.py # 分批迁移、派生快照与双读对照
│   │   │   ├── online_publish.py  # 按来源暂存、内容核对和在线代次发布
│   │   │   ├── prepare_container_data.py # 生成短文件名摘要副本并保留原名元数据
│   │   │   ├── stage_c_migration.py # 阶段 C 全量重建与只读校验入口
│   │   │   ├── kafka.py         # aiokafka 生产消费、去重、乱序缓存、位点提交和阶段计时
│   │   │   ├── flink.py         # 每运行作业提交、首检查点就绪、健康检查与 Savepoint 生命周期
│   │   │   ├── market.py        # 应用组装：加载资产、计算特征/状态/预警并保存快照
│   │   │   ├── replay.py        # 日期输入、三通道会话、运行 ID、阶段计时、控制与订阅
│   │   │   ├── replay_benchmark.py # 固定区间的三通道性能基准与结果容差核对
│   │   │   └── storage.py       # quality、states、alerts 快照写入
│   │   └── main.py              # FastAPI、GraphQL、WebSocket、路由与中间件组装
│   ├── migrations/              # MySQL 与 ClickHouse 版本化 DDL
│   ├── tests/                   # 核心、导入、SQLite、存储契约、对象归档、ClickHouse、回放、Kafka 和接口测试
│   ├── config.example.json      # 可提交的配置模板
│   ├── kafka.example.properties # 单节点 KRaft 配置模板
│   ├── start-flink.sh           # Windows Git Bash 本地 Flink 集群启动
│   ├── config.json              # 可选本地私有配置，Git 忽略
│   └── data/                    # SQLite、Kafka、Flink 和验收运行时产物，Git 忽略
├── flink/
│   ├── pom.xml                  # Java 17、Flink 2.2.1 与 Kafka Connector 5.0.0 构建
│   └── src/main/java/           # Kafka 日窗口、去重、水位线、迟到和检查点作业
├── web/
│   ├── src/App.tsx              # 工作台外壳及各主要页面按需加载
│   ├── src/Landing.tsx          # 产品首页与轻量摘要
│   ├── src/ReplayCenter.tsx     # 回放控制、进度、当日结果和 WebSocket 订阅
│   ├── src/SourceCatalog.tsx    # 数据概览、标签筛选、友好内容、分页和原始核对
│   ├── src/Chart.tsx            # 按需注册 ECharts 的图表包装组件
│   ├── src/api.ts               # fetch 封装
│   ├── src/types.ts             # API 数据类型
│   ├── src/motion.ts            # 回到顶部动画与减少动态效果适配
│   ├── src/styles.css           # 集中样式
│   └── src/*.test.tsx           # Vitest + Testing Library 测试
├── docs/architecture.md         # 目标架构与当前实现的混合设计文档，阅读时注意区分
├── README.md                    # 启动、测试、版本和项目定位
└── 上科大数据合集/              # 原始竞赛输入，Git 忽略
```

`server/app/api/` 在 `v0.3.4` 首批实施中已拆出 `system.py`、`market.py`、`data.py` 和 `replay.py`，请求模型位于 `contracts.py`，共享取值位于 `dependencies.py`；GraphQL 和 WebSocket 仍由 `main.py` 组装。这是 FastAPI 模块拆分，不是独立微服务。

## 当前运行架构与数据流

1. `python -m app.services.import_data` 按固定清单发现资产 CSV、4 个 Excel 工作簿、科技帖子 CSV、新闻 CSV 和研究摘要 Markdown。
2. `CatalogStore` 将文件元数据写入 `source_files`，将每条原始记录以 JSON 写入 `source_records`，同步累计 `source_daily_stats`、`source_fields`、`source_record_tags` 和 `source_tag_stats`，并在 `import_batches` 记录批次。默认每 1,000 条逻辑记录提交一次；Excel 使用只读模式。文件大小、修改时间和成功状态均未变化时跳过重导。记录冗余保存 `kind`，配合日期与标签索引避免大表全排序；旧库打开时自动补充字段和索引，`--rebuild-stats` 同时重建统计与标签。标签由 `market_core/domain/tags.py` 的确定性关键词和结构字段生成，仅用于检索，不表示情绪或投资判断。标签关联表冗余保存事件日期，筛选时直接复用标签计数与日期索引；本地共享 SQLite 连接通过可重入锁串行访问，避免并发请求互相干扰游标。
3. `MarketService.initialize()` 在后端启动时重新读取原始资产文件，计算全部历史特征、状态和预警；结果保存在内存中供接口查询，同时写入 SQLite 的 `snapshots` 表。
4. `SnapshotStore` 当前只提供保存和关闭方法，没有快照读取或启动恢复逻辑；不能把快照描述成已经生效的模型缓存。
5. 首页只请求轻量摘要；市场页面进入工作台后加载市场数据，数据中心独立请求预聚合概览和当前页记录，文件目录只在展开时加载。GraphQL 当前页面没有使用；历史回放页通过 WebSocket 接收真实逐日结果。
6. `ReplayManager` 创建独立会话，`ReplayDataCatalog` 只查询当前事件日期的行情，`HistoricalMarketReplay` 为每个会话维护可见历史并重新计算特征、状态和预警。会话保留事件时间与 UTC 处理时间，完成状态只在最后结果保存后发布；宏观与文本尚未进入回放模型。
7. Kafka 通道以 `event_date` 为 key 发送 `market.replay.day.v1` 日批次，包含会话、运行、事件和处理时间。消费者按运行过滤、按事件 ID 去重、缓存乱序，处理成功后手动提交连续位点；其他运行消息的跳过提交也会计入 `commit_count`。
8. Flink 每次运行由后端启动独立作业和消费者组，source 先过滤当前会话与运行，再建立最多 2 天乱序的事件时间水位线和 1d 窗口。后端等待 RUNNING 与首检查点后生产；控制事件以最后事件日期加 3 天关闭窗口，更晚事件进入迟到主题。Kafka 事务输出到 `marketlens.features.days.v1`，后端以 `read_committed` 消费，结束只停止本作业并生成 Savepoint。三种通道共用 Python 模型，Kafka/Flink 不代替原始持久化。
9. `online_publish` 将变化来源按新代次写入 ClickHouse 暂存数据，核对元数据、计数、记录摘要与标签后更新 `catalog_publications`；六个 `active_source_*` 视图只读最新生效代次。失败保留旧代次，MySQL 元数据与 MinIO 对象先于发布核对。本地默认 SQLite，distributed 主读为 ClickHouse，Redis 故障不切换事实源。共享 ClickHouse 客户端的高层 Web 查询使用可重入锁，避免同会话并发错误。
10. Windows 原始研究摘要含超过 Linux 255 字节限制的文件名，必须先由 `prepare_container_data` 生成短文件名副本及 `.source-name.json`，解析器据此恢复原始日期、机构、标题与正文；原文件不改写。生产由非特权 Nginx 同源托管并代理 `/api`、`/graphql` 和 `/ws`，默认八个容器与可选 Flink 已真实验收。

### 特征、模型与预警口径

- 只有 `field == "close"` 的资产进入价格收益和相关性计算，`yield` 序列不当作价格。
- 不同资产按日期外连接，不统一填充交易日。收益为正价格的一阶对数差分，市场收益是当日资产收益的横截面均值。
- 波动率为市场收益的滚动标准差乘以 `sqrt(252)`；动量为各资产 60 日涨跌幅的均值；趋势为价格相对 20 日均线的偏离均值；相关性为 60 日窗口内资产收益成对相关系数的均值。
- 状态模型实际使用 `market_return`、`volatility`、`momentum`、`correlation` 四个特征；`trend` 和 `sample_count` 随结果输出，但不参与当前 PCA/KMeans 拟合。
- 每个识别日的训练切片都排除当日，模型版本记录训练数据截止日。扩展未来数据不应改变已经产生的历史结果。
- 状态名称由聚类中心的确定性规则映射，并带聚类编号；贡献值是当前特征相对训练窗口的标准化偏离，不表示因果贡献。
- 高波动和高相关性预警使用此前至少 60 个状态日的历史分位数；状态标签变化会生成状态切换预警。
- 回放首日之前的可见历史只用于滚动窗口和模型预热，之后逐日追加输入；相同输入和配置的状态、特征与预警必须与原 walk-forward 结果一致，实际处理时间除外。

### 对外接口

- REST：`/api/health`、`/api/home/summary`、`/api/assets`、`/api/assets/{code}/series`、`/api/regimes/latest`、`/api/regimes`、`/api/features/latest`、`/api/alerts`、`/api/data/quality`、`/api/data/summary`、`/api/data/overview`、`/api/data/tags`、`/api/data/records`、`/api/data/files`、`/api/data/files/{source_id}/records`。
- 系统观测：`/api/health/ready` 检查市场快照与目录可读性；`/api/system/metrics` 提供当前进程的路由延迟分位数、错误数、WebSocket 连接和回放会话数，不是跨实例指标。HTTP 响应带 `X-Request-ID`；错误保留 `detail`，并增加 `error.code`、`error.message`、`error.request_id`。日志不记录查询参数或正文。
- 回放 REST：`/api/replay/calendar`、`/api/kafka/status`、`/api/flink/status`、`/api/replay/sessions`、`/api/replay/sessions/current`、`/api/replay/sessions/{id}`，以及会话的 `start`、`pause`、`resume`、`speed`、`restart` 子路径。创建会话的 `mode` 为 `local`、`kafka` 或 `flink`，对应通道未启用时返回 422。快照包含 `run_id`、`flink_job_id`、`savepoint_path` 和真实 `timing`。
- GraphQL：`/graphql`，当前查询字段只有 `assets`、`latestState`、`sourceSummary`。
- WebSocket：`/ws/replay/{session_id}` 发送会话快照和真实逐日计算结果；旧 `/ws/replay` 仍按预计算历史状态发送最多 100 条消息，仅保留作回归对照。两者都不是 Kafka/Flink 实时流。
- OpenAPI：FastAPI 自动提供 `/docs`。
- 限流：按客户端 IP 在单进程内限制为每 60 秒 240 个 HTTP 请求，超出返回 429；它不是分布式限流，也不覆盖 WebSocket 消息级控制。

## 构建、运行与部署

本地文档以 **Windows + Git Bash + Conda + Node.js** 为基准。在仓库根目录执行后端命令，在 `web/` 执行前端命令。

### 首次安装

```bash
# 已存在 fintech 环境时跳过创建
conda env create -f environment.yml
conda run -n fintech python -m pip install -r requirements-dev.txt

# 可选：创建本地配置；不创建时使用 example 配置
cp server/config.example.json server/config.json

cd web
npm install --cache .npm-cache
```

### 导入原始数据

回到仓库根目录执行：

```bash
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.import_data

# 仅升级旧版数据库时回填概览统计；不会重读原始文件
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.import_data --rebuild-stats
```

这里的 `PYTHONPATH` 使用 Windows 的 `;` 分隔符，使 Python 同时找到 `market_core` 和 `server/app`。首次全量导入会处理大型新闻文件并生成较大的 SQLite 数据库；后续执行会跳过未变化且已成功导入的文件。日期与字段统计随新导入生成，旧库只需执行一次统计回填。不要用普通单元测试代替首次真实数据导入。

### 启动开发环境

```bash
# 仓库根目录；首次初始化会重新计算真实历史特征
PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000
```

另开终端：

```bash
cd web
npm run dev
```

访问 `http://localhost:5173`；后端文档为 `http://localhost:8000/docs`，GraphQL 为 `http://localhost:8000/graphql`。

前端生产构建：

```bash
cd web
npm run build
```

仓库提供后端、前端、Flink、ClickHouse 和 MinIO Dockerfile，以及默认、精简开发和可选 Flink Compose；生产入口为 Nginx。可选 Flink 编排会先创建输入、输出和迟到主题并禁止按墙钟清理，再提交作业。Docker Desktop 已安装，默认八个服务和可选 Flink 已真实启动，`docker compose config`、全量导入、核心 API、回放、页面和故障恢复均已验收。Windows 原始研究摘要含超长文件名，首次及变化后必须先运行 `python -m app.services.prepare_container_data` 生成短文件名副本，详见 `docs/stage-e-deployment.md`。

## 测试与质量验证

后端完整测试和覆盖率：

```bash
PYTHONUTF8=1 conda run -n fintech python -m pytest --cov=market_core --cov=server/app --cov-report=term-missing server/tests
```

`pyproject.toml` 已设置 `pythonpath = [".", "server"]`、默认测试目录 `server/tests`、分支覆盖率和 `fail_under = 30`。也可以在激活环境后运行 `python -m pytest`，但完整验收应保留覆盖率参数。

前端测试与构建：

```bash
cd web
npm test
npm run build
```

当前测试基线：

- `v0.3.4` 当前后端 67 项测试通过，覆盖数据、模型、回放、接口、存储、在线发布、请求观测、Flink 生命周期、阶段计时和基准汇总。
- 后端总体分支覆盖率为 73.01%，高于 30% 的竞赛门槛；阶段 B/C/D/E 已真实验收。Flink Java 作业不计算在 Python 覆盖率内，Maven `clean package` 已通过。
- 前端 10 项测试通过，覆盖既有首页、工作台、数据中心、标签与滚动行为，以及回放控制、WebSocket 当日结果、Kafka 与 Flink 通道创建参数和真实计时面板。
- 后端接口测试使用 fake service、固定行情或 fake Kafka 消息，前端测试 mock `fetch`、WebSocket 和图表；这些单元与集成测试不代替真实 broker、Flink 集群和页面验收。
- 最终容器数据为 1,046 个文件、1,556,492 条记录；全部 MinIO 对象已回读核对。真实 Chrome 已检查首页、工作台、数据中心和 `v0.3.4` 回放计时面板，无 500 或浏览器错误；Nginx WebSocket 已收到真实逐日回放。
- 本地历史环境已在 2026-04-27 至 2026-04-30 完成四天三通道 `1e-12` 容差一致性；`v0.3.4` 的每运行独立 Flink 作业已通过连续两轮、暂停继续、同会话重开、不同日期、乱序去重、超迟分流和 Savepoint 恢复。最新 Chrome 截图为 `server/data/v034-flink-independent.png`，详见 `docs/v0.3.4-observability.md`。
- 当前没有 CI 工作流、可持续运行的浏览器端 E2E 测试套件、覆盖全部竞赛指标的正式性能压测报告或前端覆盖率统计。

修改解析、模型或接口时，应增加与行为对应的测试；不要只验证模块可导入。完整链路、真实页面、部署和性能仍需单独验证。

## 原始数据组织与处理约定

```text
上科大数据合集/
├── 目标资产价格变量/              # 39 个资产序列 CSV + 代码对照.csv
├── 全球资金信息摘要/
│   └── 上科大版本摘要/            # 1,000 篇中文 Markdown 摘要
├── 新闻/无标题.csv                # 无表头大型新闻 CSV
├── 科技.csv                       # X/Twitter 帖子与互动数据
├── 日历数据.xlsx
├── 商品期货日成交额.xlsx
├── 指标集1_数据.xlsx
└── 公众号.xlsx
```

当前实际数据口径：

| 数据 | 规模与字段 | 注意事项 |
| --- | --- | --- |
| 资产目录与行情 | 目录 40 条；39 个可用行情 CSV，共 314,318 条有效行情；另有目录自身的 1 条汇总来源记录差异，SQLite 的 `asset` 组为 40 个文件、314,358 条记录 | 行情字段为 `date,close` 或 `date,yield`；“全球高收益债”标记缺失且无行情文件 |
| `指标集1_数据.xlsx` | `X01`–`X31` 共 31 个 sheet，SQLite 共 104,122 条记录 | 脱敏字段只有 `日期` 和 `序列N`；频率不一且有空值，不得编造业务含义或强制转为日频 |
| `商品期货日成交额.xlsx` | 1,924 条记录 | 保留 `成交额（万亿元）` 单位 |
| `日历数据.xlsx` | 185,753 条记录 | 7 个原始字段；前值、预测值、实际值可能为空，国家字段为数值编码 |
| `新闻/无标题.csv` | 900,704 条逻辑记录，11 列，无表头，约 1.83 GiB | 第 10 列作为事件日期；正文含 HTML、链接和嵌入换行，不能按物理行解析，也不得擅自命名正式业务列 |
| `科技.csv` | 41,413 条逻辑记录，32 个有名字段 | 保留正文、作者、URL、互动计数和采集快照；正文可能跨物理行 |
| `公众号.xlsx` | 7,218 条记录 | 只有日期、链接、文章标题、相关方，是文章索引而非全文 |
| 研究摘要 | 1,000 个 Markdown 文件，每文件 1 条记录 | 从文件名提取日期、机构和标题，正文保留在 JSON payload |

补充约束：

- 债券 `yield` 是百分数，不是小数或价格；外汇名称已明确报价方向，不得颠倒。
- 多个期货序列是连续或主力连续且未复权，具体以 `代码对照.csv` 备注为准。资产重复日期当前由后读值覆盖并计数，非法行跳过并计数。
- CSV 使用 UTF-8/UTF-8-SIG 和标准 CSV 解析器；大型文件采用迭代读取或分批写入。Excel 第一行是表头，指标工作簿必须处理所有 sheet。
- 保留原始 payload、来源文件、原始日期和必要的采集时间；派生数据与原始层分开。除非任务明确要求，不要重写、覆盖或批量移动原始文件。
- 日期对齐、缺失填充、时区、宏观公布时间和特征窗口必须有明确口径，避免未来数据泄漏。宏观、事件和文本数据当前已入库，但尚未进入状态模型特征。
- 原始文件数量、逻辑记录数和资产有效行情数是不同指标，不要混用。

## 开发约定

- Python 文件使用 `from __future__ import annotations`、类型标注、数据类和 `pathlib.Path`；沿用当前模块的命名与结构。
- 核心领域、解析和算法放在 `market_core`，禁止反向依赖 `server` 或 `web`。`server` 负责配置、服务组装、运行存储和接口，不应承接领域算法。
- 前端通过 API 获取真实状态，不在页面硬编码市场判断；使用函数组件、TypeScript 严格模式和集中样式。ECharts 继续按需注册组件，新增图表时同步处理实例销毁和尺寸变化。
- SQL 查询保持参数化；动态查询只能组合代码内固定的 SQL 片段，用户输入只能作为参数。
- 修改模块边界、启动命令、配置或数据口径时，同步更新 `README.md`、`docs/architecture.md` 和本文件，保持“当前实现”与“目标架构”分离。
- 当前没有采用 OpenSpec，也没有 `openspec` 配置或命令；培训材料中的 OpenSpec 流程不是仓库现状。
- 版本使用 `v主版本.次版本.修订号`。完整网页、核心 API、数据接入、状态识别、预警和 Docker Compose 端到端验收前保持 `v0.x`；不要仅为文档或架构讨论创建版本标签。
- **任何 `git push` 必须等用户实际体验修改并明确确认后执行。本地测试、提交和标签不能代替用户体验验收。**

## 安全注意事项

- 密钥只能通过 `DEEPSEEK_API_KEY` 等环境变量、本地 `.env` 或被忽略的私有配置注入；`.env.example` 仅保存空模板。严禁把真实凭据写入源码、文档、命令、日志或 Git 历史。当前 LLM 尚未接入，模板中的模型名和基础地址不代表可用性已验证。
- 原始赛题数据、`server/config.json` 和 `server/data/` 均被 Git 忽略。新增外部数据时记录来源，并检查许可和敏感信息。
- 新闻、帖子和研究文本是不可信输入。当前 React 预览按文本渲染，不使用 `dangerouslySetInnerHTML`；修改预览时不得引入 HTML 注入/XSS。
- 数据库访问必须使用参数化查询，避免 SQL 注入和硬编码密码。
- 当前没有用户登录、JWT/OAuth2 或数据权限体系，只有 CORS 和简单内存限流。不要将当前服务直接描述为可安全暴露到公网的生产服务。

## 竞赛目标与尚未验收事项

以下均为目标，不是当前性能或部署事实：

- 数据与计算：Kafka、Flink、事件时间窗口、Checkpoint/Savepoint、历史回放和失败恢复。
- 存储：MySQL、ClickHouse、Redis、MinIO，以及 ODS/DWD/DWS/ADS 分层、分区、生命周期和血缘。
- 服务：API Gateway、独立微服务、认证授权、分布式限流与缓存。
- 模型：把宏观、事件和文本信号纳入特征，完善标签、回测、模型登记及可降级 LLM 分析助手。
- 性能：端到端延迟 `<100ms`、吞吐量 `>10 万条/秒`、特征计算 `<50ms`、状态识别 `<1s`、Redis 热特征访问 `<10ms`、API `<50ms`、WebSocket 推送 `<100ms`、页面加载 `<2s`、并发用户 `>100`。这些指标目前均未形成验收报告。
- 部署：提供 Dockerfile 和 Docker Compose，在干净环境完成一键启动、全部文件导入、核心接口和页面验收。

竞赛必须交付 40 页以内的项目介绍 PDF、含 Dockerfile/Compose/README/覆盖率大于 30% 单元测试的 Git 仓库，以及 5 分钟以内、1080p 的功能与架构演示 MP4。发布材料列出的截止日期为 **2026-12-31**。性能报告、压测报告、ADR、监控截图和合规外部另类数据属于可选加分材料。
