# AGENTS.md

## 1. 项目定位与当前状态

本目录是 **2026 年上海科技大学第一届金融科技竞赛参赛项目**，产品名 **MarketLens**。项目使用多资产行情、宏观指标、事件日历和舆情文本，建设市场状态（Market Regime）监控平台。

核心业务链路：

> 数据按事件时间进入 → 数学模型计算特征与市场状态 → 确定性规则生成预警 → 前端展示证据与分析

数值特征和状态必须由数学模型计算，预警必须由确定性规则产生。规划中的 LLM 只负责文本理解、证据整合与解释，不能决定状态、预警等级、回放结果或自动交易，也不能成为核心链路的单点依赖。

当前最新版本标签为 `v0.3.3`，`v0.3.4` 正在分批开发，不能提前宣称完整版本完成或创建新标签。当前基线：

- 已导入 1,046 个赛题输入文件，共 1,556,492 条逻辑记录；39 个资产序列可用，原始文件保持不变。
- 已实现行情特征、walk-forward 状态识别、规则预警，以及本地直连、Kafka 事件、Flink 窗口三种真实历史回放通道。
- 已有 React 首页与工作台，覆盖市场、状态、回放、特征、预警和数据中心；数据中心支持预聚合概览、服务端分页、原始字段核对及最多 5 个标签的组合筛选。
- Kafka 4.3.2 单节点 KRaft 与 Flink 2.2.1 单 JobManager/TaskManager 已联通；每轮回放使用独立作业、事件时间水位线、检查点与 Kafka 事务输出。
- MySQL、ClickHouse、Redis、MinIO 已进入实际存储或发布链路；ClickHouse 支持按来源代次在线增量发布。
- 回放会话、逐日结果、幂等操作与恢复状态已持久化，支持断线补拉和跨进程恢复。
- `app.data_service:app` 独立提供数据目录；`app.feature_service:app` 独立持有市场模型和回放；`app.alert_service:app` 根据特征状态独立重建历史预警。主后端通过兼容代理保留原 REST、GraphQL、WebSocket 与 OpenAPI 契约。默认 Compose 为十一个服务。
- 当前后端 91 项测试、前端 11 项测试通过，Python 分支覆盖率 75.25%。

**当前不是完整微服务、高可用或实时行情系统。** 历史预警查询已独立部署，逐日回放仍在特征服务内调用同一纯规则；完整 API Gateway、认证授权、分布式限流、可配置规则与 LLM 助手尚未完成。单节点 Kafka/Flink、历史回放和兼容代理不得夸大为生产级能力。详细现状与验收记录见：

- `README.md`：项目定位、技术线和启动方式。
- `docs/architecture.md`：目标架构与当前实现，阅读时注意区分。
- `docs/v0.3.4-plan.md`：当前版本任务、边界和验收要求。
- `docs/v0.3.4-observability.md`：契约、观测与性能基线。
- `docs/v0.3.4-replay-persistence.md`：回放持久化与恢复记录。
- `docs/v0.3.x-plan.md`：阶段目标及 `v1.0.0` 合规门槛。

## 2. 技术栈与模块边界

- Python 3.12、FastAPI、Uvicorn、Strawberry GraphQL、NumPy、pandas、scikit-learn；数据库访问使用标准库 `sqlite3` 和对应服务客户端，不使用 ORM。
- React 19、TypeScript 5.7、Vite 6、ECharts 5、Vitest 3；使用函数组件和 Hooks，无路由库、状态管理库或独立 CSS 框架。
- Flink 作业使用 Java 17、Flink 2.2.1、Kafka Connector 5.0.0 和 Maven Shade。
- 依赖固定在 `requirements.txt`、`requirements-dev.txt`、`web/package-lock.json` 和 `flink/pom.xml`。不要假设未声明的库或工具已经存在。
- 当前没有 Ruff、Black、mypy、ESLint、Prettier、CI 工作流、前端覆盖率脚本或持续浏览器 E2E；不要声称这些检查已存在。

```text
market_core/
  domain/                 # 资产、事件、回放、来源、标签等领域结构
  ingestion/              # 行情与原始文件解析
  models/                 # 特征、状态、回放、确定性预警；不依赖 server 或 web
server/app/
  api/                    # system、market、data、replay 路由与请求契约
  core/                   # 配置、请求 ID、错误契约、日志与进程内指标
  services/               # 目录、存储、缓存、远程客户端、回放与应用组装
  main.py                 # 单体或兼容代理入口，组合 GraphQL/OpenAPI
  data_service.py         # 独立数据目录服务，不加载模型或回放
  feature_service.py      # 独立特征状态与回放服务
  alert_service.py        # 独立历史预警查询服务
server/tests/             # pytest 与接口/服务契约测试
flink/                    # Java 事件时间窗口、去重、迟到与容错作业
web/src/                  # React 页面、API 类型、图表与 Vitest 测试
docs/                     # 架构、部署、阶段计划和验收记录
上科大数据合集/            # 原始竞赛输入，Git 忽略
```

职责约束：

- 核心领域、解析和算法放在 `market_core`，禁止反向依赖 `server` 或 `web`。
- `server` 负责配置、服务组装、运行存储和接口，不承接新的领域算法。
- 前端只通过 API 获取真实状态，不硬编码市场判断；ECharts 按需注册并处理销毁和尺寸变化。
- 数据服务拥有文件、记录、标签、导入批次与目录缓存；特征状态服务拥有模型、状态历史和回放会话；预警服务根据特征状态重建历史预警并独立提供查询。回放预警仍在特征服务内调用同一纯规则，不增加逐日网络依赖。
- 主后端设置 `FEATURE_SERVICE_URL` 后不得再创建第二份模型或回放管理器。前端与 Nginx 仍只访问主后端，兼容代理不等于完整 API Gateway。
- 本地不配置远程服务 URL 时保留原单体模式，作为开发、算法回归与回退路径。

## 3. 配置与运行模式

`server/app/core/config.py` 按以下顺序加载配置：

1. `MARKETLENS_CONFIG` 指定文件；
2. 被 Git 忽略的 `server/config.json`；
3. `server/config.example.json`。

相对路径基于所选配置文件目录。`DATA_ROOT`、`DATABASE_PATH` 和服务地址可由环境变量覆盖。示例配置不得包含真实凭据。

关键模式：

- `STORAGE_MODE=local|distributed`：默认本地 SQLite；distributed 必须同时 `CLICKHOUSE_ENABLED=true`，主读 ClickHouse，不会静默切换事实源。
- `KAFKA_ENABLED=true` 开启 Kafka；`FLINK_ENABLED=true` 开启 Flink，且必须同时启用 Kafka。
- MySQL、MinIO、ClickHouse、Redis 默认关闭；密码只通过环境变量或私有配置注入。
- Redis 故障可回源到显式主存储，缓存键必须包含数据版本和查询参数。
- `DATA_SERVICE_URL` 为空时使用本地/分布式目录；设置后通过 `RemoteCatalogClient` 调用数据服务。
- `FEATURE_SERVICE_URL` 为空时使用本地模型与回放；设置后通过远程客户端、REST 代理和 WebSocket 中继调用特征状态服务。
- `ALERT_SERVICE_URL` 在主后端远程模式下启用独立预警代理和 readiness 检查；预警服务自身通过 `FEATURE_SERVICE_URL` 读取预警输入。数据服务和特征服务自身不得设置 `FEATURE_SERVICE_URL`，避免自调用。
- 远程调用必须有界超时，不做无界自动重试。预警输入中的非有限数值以 `null` 传输，规则按缺失值处理，不得输出非法 JSON `NaN`。

默认模型口径：分析起点 2015-01-01，最少 504 个有效特征日，训练窗口 756 日，每 63 日重训，20 日波动窗口，60 日动量窗口，3 个聚类，随机种子 42。

## 4. 数据、模型与时间口径

### 原始数据

- 资产目录 40 条，39 个有效行情 CSV 共 314,318 条有效行情；“全球高收益债”没有行情文件。
- `指标集1_数据.xlsx` 有 31 个 sheet，字段经过脱敏，不得编造指标含义或强制转成日频。
- 新闻 CSV 约 1.83 GiB、900,704 条逻辑记录，无表头且正文含 HTML、链接和嵌入换行，必须使用标准 CSV 解析器流式读取，不能按物理行解析或擅自命名字段。
- 科技帖子、公众号、日历、商品成交额和研究摘要保留原始字段、来源和事件日期；研究摘要从文件名提取日期、机构与标题。
- 文件数、逻辑记录数、资产有效行情数是不同指标，不得混用。

### 数据处理

- 原始文件只读；除非任务明确要求，不得重写、覆盖或批量移动。
- 保留原始 payload、来源文件和事件时间，派生数据与原始层分开。
- CSV 使用 UTF-8/UTF-8-SIG；Excel 第一行是表头，指标工作簿必须处理全部 sheet。大型文件分批读取和写入。
- 标签由确定性关键词和结构字段生成，只用于检索，不代表情绪或投资判断。
- Windows 原始研究摘要可能超过 Linux 文件名长度限制；容器部署前用 `prepare_container_data` 生成短文件名副本及名称元数据，不改原文件。

### 特征与状态

- 只有 `field == "close"` 的资产进入价格收益与相关性计算；`yield` 是百分数，不是价格或小数。
- 不同资产按日期外连接，不统一填充交易日。收益为正价格的一阶对数差分，市场收益为当日资产收益横截面均值。
- 波动率为市场收益滚动标准差乘 `sqrt(252)`；动量为 60 日涨跌幅均值；趋势为价格相对 20 日均线的偏离均值；相关性为 60 日资产收益成对相关系数均值。
- 当前 PCA/KMeans 只使用 `market_return`、`volatility`、`momentum`、`correlation`；`trend` 和 `sample_count` 不参与拟合。
- 每个识别日的训练切片必须排除当日，模型版本记录训练截止日；新增未来数据不得改变既有历史结果。
- 状态名称由聚类中心确定性映射；贡献值是标准化偏离，不是因果贡献。
- 高波动与高相关性预警使用此前至少 60 个状态日的历史分位数；状态标签变化生成切换预警。

### 回放

- 完整入库不等于模型可见未来。任何一天只能读取当前事件时间及此前已发布的数据。
- 区分 `event_time` 与实际处理时间；宏观按公布时间进入，文本按自身发布时间进入，不得把统计期当成发布日期。
- 回放首日之前的历史只用于滚动窗口和模型预热；相同输入与配置的特征、状态、预警必须与原 walk-forward 结果一致。
- 三种通道共用 Python 模型；Kafka/Flink 不代替原始持久化，也不另写一套 Java 金融算法。
- WebSocket 只推送快照和增量结果，断线通过会话 ID 与序列号补拉，不重复执行模型。
- Flink 小数据逐日回放慢于本地是已知现象。优化须先测阶段耗时，不能跳过窗口、关闭必要容错或读取未来数据。

## 5. 接口与前端约定

- 主要 REST 包括健康/就绪、首页摘要、资产、状态、特征、预警、数据质量与目录、回放日历/会话/控制/结果，以及 Kafka/Flink 状态。
- GraphQL `/graphql` 当前只有 `assets`、`latestState`、`sourceSummary`。
- `/ws/replay/{session_id}` 推送真实逐日回放；旧 `/ws/replay` 仅作预计算状态回归对照。两者都不是实时行情流。
- OpenAPI 由 FastAPI 在 `/docs` 提供。主后端代理须保留查询、正文、幂等键、状态码、错误结构和 WebSocket 关闭码。
- HTTP 响应带 `X-Request-ID`；错误保留 `detail` 并增加 `error.code/message/request_id`。日志不得记录敏感配置、查询正文或密钥。
- 当前限流只是单进程客户端 IP 限制，不是分布式限流，也不覆盖 WebSocket 消息级控制。
- 首页使用轻量摘要，主要页面按需加载；数据中心不得一次加载整库，长文本和原始字段按需查询。
- 新闻、帖子与研究文本均是不可信输入。React 继续按文本渲染，不使用 `dangerouslySetInnerHTML` 展示原始 HTML。

## 6. 构建、运行与测试

本地命令以 **Windows + Git Bash + Conda + Node.js** 为基准，在仓库根目录执行，前端命令除外。

首次安装：

```bash
conda env create -f environment.yml
conda run -n fintech python -m pip install -r requirements-dev.txt
cd web && npm install --cache .npm-cache
```

已有 `fintech` 环境时跳过创建。可选私有配置：`cp server/config.example.json server/config.json`。

导入数据：

```bash
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.import_data
```

开发启动：

```bash
PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000
cd web && npm run dev
```

访问 `http://localhost:5173`，后端文档为 `http://localhost:8000/docs`。容器部署、短文件名副本和可选 Flink 编排见 `docs/stage-e-deployment.md`。

完整回归：

```bash
PYTHONUTF8=1 conda run -n fintech python -m pytest --cov=market_core --cov=server/app --cov-report=term-missing server/tests
cd web && npm test && npm run build
```

修改解析、模型、接口或服务边界时必须增加对应行为测试，不能只验证导入或编译。单元测试中的 fake service、mock fetch/WebSocket 不能代替真实数据、 broker、Flink、服务重启、容器和 Chrome 验收。性能、正确性、恢复和页面验收分别记录，不将局部查询耗时当成端到端性能。

## 7. 开发、安全与 Git 约定

- Python 沿用 `from __future__ import annotations`、类型标注、数据类和 `pathlib.Path`，匹配现有模块结构；默认不写解释性噪声注释。
- SQL 必须参数化；动态查询只能组合代码内固定片段，用户输入只能作为参数。
- 修改模块边界、启动命令、配置或数据口径时，同步更新 `README.md`、`docs/architecture.md`、本文件和相关计划。
- 项目未采用 OpenSpec；培训材料中的流程不代表仓库现状。
- 密钥只能通过环境变量或被忽略的私有配置注入。严禁把真实凭据写入源码、文档、命令、日志或 Git 历史，也不要在回复中复述用户曾提供的密钥。
- 原始赛题数据、`server/config.json`、`server/data/`、运行数据库和构建产物不得进入 Git。原始 PDF/PPT 保持未跟踪，除非用户明确要求纳入。
- 当前没有完整用户登录、JWT/OAuth2 或数据权限体系，不得把服务描述为可安全暴露公网的生产系统。
- 版本号为 `v主版本.次版本.修订号`。完整核心功能和端到端验收前保持 `v0.x`，不要仅为文档或架构讨论创建版本标签。
- **每批修改必须经用户实际体验并明确确认后，才能提交或推送。测试通过不能代替用户验收；不得绕过确认，不得重复提交已存在的提交。**

## 8. 下一步与正式版门槛

`v0.3.4` 接下来的顺序：

1. **API Gateway 评估**：预警服务独立部署已通过用户验收；下一批先比较现有 FastAPI 单入口与成熟网关在认证、限流、WebSocket 和运维方面的收益，再决定是否引入，不为组件数量增加网关。
2. **安全与治理**：JWT/OAuth2、角色与数据权限覆盖 REST、GraphQL、WebSocket，再实现审计、Redis 分布式限流以及 Caffeine/Redis 缓存分工。
3. **分析与展示**：可配置预警规则、规则版本、阈值与原始证据链、状态热力图、依赖监控；核实公布/发布时间后，让部分宏观或文本进入真实分析或证据链。
4. **性能与交付**：优化模型初始化和 Flink 固定等待，完成压测、故障演练、CI、持续浏览器 E2E、方案 PDF、ER/数据流图、质量报告、ADR 与演示 MP4。

`v1.0.0` 前必须按 `docs/v0.3.x-plan.md` 逐项实测：干净环境一键启动、核心功能、安全红线、各组件真实职责、认证权限、可配置规则、宏观/文本证据、性能与恢复，以及竞赛交付材料。性能目标只有在真实报告支持时才能宣称达标。竞赛交付包括 40 页以内项目 PDF、含 Dockerfile/Compose/README/覆盖率大于 30% 测试的 Git 仓库，以及 5 分钟以内 1080p MP4；发布材料截止日期为 **2026-12-31**。
