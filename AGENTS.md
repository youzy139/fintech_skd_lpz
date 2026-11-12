# AGENTS.md

2026-11-12 当前版本：`v0.4.0` 测试里程碑。用户明确要求进入 v0.4.x，每批已汇报并获初步验收的功能/修复在提交推送时同步递增版本及标签，后续为 v0.4.1、v0.4.2 等。整个阶段余项继续单列，不能把竞赛正式门槛当作测试版本升版条件。旧标签不移动，纯文档提交不单独升版。

本版纳入特征/回放契约、Redis 当前特征热读、来源类型与逐文件质量证据；升版前后端 223 项、覆盖率 78.70%，前端 51、构建/Chrome E2E 通过。最新升版复验与 Git/CI 状态见 `docs/releases/v0.4.0.md`；不要引用旧版本结果代替。预览复用 5177/18040，原始数据只读，隔离目录仅含日历/公众号。本版本空卷、实机 ClickHouse 逐文件功能、正式性能、金融效果和竞赛材料仍未完成。

## 1. 项目定位与当前状态

本目录是 **2026 年上海科技大学第一届金融科技竞赛参赛项目**，产品名 **MarketLens**。项目使用多资产行情、宏观指标、事件日历和舆情文本，建设市场状态（Market Regime）监控与历史研究平台。

核心业务链路：

> 原始数据按事件时间进入 → 数学模型计算特征与市场状态 → 确定性规则生成预警 → Web 展示、证据复核与历史回放

项目用于市场监控和研究决策支持，不直接给出买卖指令，不以自动交易或收益率为目标。数值特征和状态必须由数学模型计算，预警必须由确定性规则产生。规划中的 LLM 只负责文本理解、证据整合与解释，不能决定状态、预警等级、回放结果或自动交易，也不能成为核心链路的单点依赖。

当前源码/API、前端包/页面、Compose 镜像声明及 Flink 工件统一为 **`v0.4.0`**；它是 2026-11-12 按用户指示整理的可运行测试里程碑，**不是 `v1.0.0` 正式版**。镜像声明不代表本地已经重建。当前真实基线：

- 已接入 1,046 个赛题输入文件，共 1,556,492 条逻辑记录；资产目录 40 项，39 个资产有有效行情，共 314,318 条有效行情，“全球高收益债”缺少行情文件。文件数、逻辑记录数和有效行情数不得混用。
- 已实现行情特征、walk-forward 状态识别、可配置确定性预警规则、规则版本恢复、统计证据和最近 120 日特征热力图。
- 已实现本地直连、Kafka 事件、Flink 窗口三种真实历史回放通道，以及会话、逐日结果、幂等操作、恢复状态持久化和 WebSocket 断线补拉。
- 已有 React 首页与工作台，覆盖市场、状态、特征、预警、回放、数据中心和系统管理；使用哈希路由、权限导航、懒加载、服务端分页、CSV 导出及错误重试。
- 数据、特征状态/回放、历史预警三个业务服务可独立部署；主后端保留兼容代理，Nginx + FastAPI 仍是对外单入口。默认 Compose 为十一个服务。
- JWT、角色/功能域权限、Redis 共享限流、WebSocket 连接租约、回放计算并发、审计查询与 MinIO 归档、依赖监控和 Redis 熔断已实现；本地开发仍保留无认证单体模式。
- 当前只有多资产行情进入状态模型和回放。经济日历与公众号只按前一状态日提供背景证据，不参与模型或规则；新闻、隐名指标、研究摘要和社媒在时间语义核实前不得接入核心判断。

`v0.3.4` 发布记录载明：后端 162 项、前端 34 项测试通过，Python 分支统计总体覆盖率 77.31%，生产构建和一条完整 Chrome E2E 通过。它们是发布时的历史验收结果，不是后续修改或本次文档整理重新执行的结果；工作后必须重新复验。

2026-11-11 当前工作区终端化重构已复验：后端 162 项、前端 39 项测试通过，Python 分支统计总体覆盖率 77.31%；一条扩展 Chrome E2E 通过，覆盖全部主要页面、管理路由、真实两日回放和移动退出登录。生产构建、前端 Docker 镜像、Flink Maven 构建及 npm 官方审计通过。最大图表共享包约 480.07kB，不再有 500kB 体积提示。真实后端预览为 `http://localhost:5175`，此前代理 readiness 200。用户随后明确要求提交当前本地状态、版本保持 `0.3.4`，本批据此授权本地提交；不补记用户页面体验结果，未推送、不移动既有标签。Docker、Maven 和审计结果为本批先前记录，提交前重新执行的检查见 `docs/releases/v0.3.4.md`。

**当前不是实时行情、高可用或完整生产安全系统。** Kafka/Flink 是单节点验证环境，兼容代理不是独立通用 API Gateway；OAuth2/OIDC、行级权限、LLM 助手尚未实现。正式性能目标、`v0.3.4` 空卷启动、完整模型效果与故障报告、竞赛终稿和演示视频仍有缺口。不要把历史回放称为实时流，不要把局部查询耗时当成端到端性能。

`v0.3.5` 状态身份专项已获用户初步验收及提交/推送授权，软件/工件声明同步为 `0.3.5`。新状态采用 `centroid-alignment-v1`：原始特征单位的中心经前次训练尺度归一化后作全局一对一匹配；`cluster` 是局部编号，`regime_id` 是匹配身份，标签后缀使用后者。旧回放快照缺少 `model_identity` 时沿用 `local-cluster-v1`，不得重写已保存逐日结果。最终后端 177 项、前端 39 项、生产构建、Chrome 和四日真实三通道对照通过，分支统计总体覆盖率 77.44%。工程证据、历史差异及限制见 `docs/v0.3.5-regime-identity.md`，事件标注尚未完成。用户要求整理推送本版后继续开发；镜像重建、评估协议团队确认和人工标注继续列为缺口，不能补造验收。

状态与验收以以下文档为准：

`v0.4.0` 已实现特征定义/回放契约、Redis 当前快照热读、来源类型和逐文件治理。缓存只读已计算当前快照，历史回放仍读持久化结果；损坏/TTL/熔断回同一权威快照。既有真实 Redis 8.0.5 合成验证含命中、TTL、损坏修复、拒绝连接、熔断恢复及 20 次认证 API，不是正式性能验收。目录证据不扫描原始大文件，字段空缺不是必填缺失，重复/语义异常未评估，无生命周期执行器。详细验证与保留缺口见 `docs/releases/v0.4.0.md` 及三份 v0.4.0 专项报告。

- `README.md`：项目定位、完整启动方式、实测结果和已知限制。
- `docs/releases/v0.4.0.md`：当前测试版范围、验证与余项；`docs/releases/v0.3.5.md` 保留状态身份历史发布记录。
- `docs/release-readiness.md`：最新验收记录和 `v1.0.0` 未完成门槛。
- `docs/roadmap.md`：后续任务、目标版本与版本出口；当前软件 v0.4.0，v0.4.1 起递进数据/特征治理余项，然后 v0.5.0 性能、v0.6.0 模型效果、v0.9.0 候选、v1.0.0 正式交付。规划不等于实现。
- `docs/data-quality-report.md`：数据计数、缺失、时间和字段口径。
- `docs/data-model.md`：当前实装实体、存储与数据流。
- `docs/architecture.md`：同时包含早期目标架构和历史演进，阅读时必须区分目标、历史状态与当前实现。

## 2. 技术栈与关键配置

- **领域与后端**：Python 3.12、FastAPI、Uvicorn、Strawberry GraphQL、NumPy、pandas、scikit-learn、PyJWT；SQLite 使用标准库 `sqlite3`，不使用 ORM。Kafka、ClickHouse、Redis、MySQL、MinIO 分别使用已固定的客户端依赖。
- **前端**：React 19、TypeScript 5.7（`strict: true`）、Vite 6.4.6、ECharts 6.1.0、Vitest 4.1.12、Testing Library、Playwright 1.65。使用函数组件和 Hooks，没有路由库、状态管理库或独立 CSS 框架。CI 和前端 Docker 构建使用 Node 22。
- **流处理**：Java 17、Flink 2.2.1、Kafka Connector `5.0.0-2.2`、Maven Shade；Kafka 为 4.3.2 单节点 KRaft。Java 作业只处理事件、窗口和容错，不实现另一套金融算法。
- **部署**：Docker Compose、非特权 Nginx、MySQL 8.4.13、ClickHouse 25.8.4.13、Redis 8.0.5、固定版本源码构建的 MinIO。后端容器以非 root 用户运行。

关键文件：

| 文件 | 作用 |
| --- | --- |
| `environment.yml` | 最小 Conda 环境：Python 3.12 和 pip |
| `requirements.txt`、`requirements-dev.txt` | 固定 Python 运行与测试依赖 |
| `pyproject.toml` | pytest 路径和 branch coverage 配置；不是完整 Python 包构建配置 |
| `web/package.json`、`web/package-lock.json` | 前端脚本与锁定依赖 |
| `web/vite.config.ts` | Vite 开发代理和 Vitest jsdom 配置 |
| `web/playwright.config.ts` | 真实浏览器、合成后端与 Vite 测试服务编排 |
| `web/tsconfig.json` | TypeScript 严格编译选项 |
| `flink/pom.xml` | Java 17/Flink 依赖和可执行 Shade JAR |
| `server/config.example.json` | 本地无密钥默认配置 |
| `deploy/config/container.json` | Compose 的分布式无密钥配置 |
| `compose.yaml`、`compose.dev.yaml`、`compose.flink.yaml` | 完整、精简开发、可选 Flink 编排 |
| `.github/workflows/ci.yml` | 后端、前端、浏览器、Flink 和容器 CI |

不要假设未声明的库或工具已经存在。当前没有配置 Ruff、Black、mypy、ESLint 或 Prettier，也没有前端覆盖率脚本；不要声称这些检查已存在或已通过。

## 3. 代码组织与模块边界

```text
market_core/
  domain/                  # 资产、事件、回放、来源、标签等领域结构
  ingestion/               # 行情、CSV、Excel、新闻和 Markdown 解析
  models/                  # 特征、walk-forward 状态、回放、确定性预警
server/
  app/
    api/                   # auth、system、market、data、replay 路由与请求契约
    core/                  # 配置、认证、限流/租约、熔断、序列化、日志与指标
    services/              # 目录、存储、缓存、远程客户端、回放、发布与迁移
    main.py                # 单体或兼容代理，组合 GraphQL/OpenAPI/WebSocket
    data_service.py        # 独立数据目录服务，不加载模型或回放
    feature_service.py     # 独立特征状态与回放服务
    alert_service.py       # 独立历史预警、规则与证据服务
  tests/                   # pytest 行为、接口和服务契约测试
  benchmarks/              # 独立合成数据 E2E 后端等验收工具
  migrations/              # MySQL、ClickHouse SQL
  config.example.json      # 无密钥模板
  data/                    # 私有身份库、SQLite、运行和验收产物，Git 忽略
web/
  src/                     # React 页面、API 类型、图表、样式和 Vitest
  e2e/                     # Playwright 真实浏览器流程
  scripts/                 # 竞赛方案 PDF 草稿导出
  nginx.conf               # 静态站点及 REST/GraphQL/WebSocket 同源代理
flink/                     # Java 事件时间窗口、去重、迟到与容错作业
clickhouse/、minio/        # 固定版本镜像构建
deploy/config/             # 容器配置
docs/                      # 架构、质量、部署、专项验收、发布和交付材料
.github/workflows/         # 持续集成
上科大数据合集/             # 原始竞赛输入，Git 忽略
```

职责约束：

- 核心领域、解析和算法放在 `market_core`，禁止反向依赖 `server` 或 `web`。
- `server` 负责配置、运行存储、服务组装、治理和接口，不承接新的领域算法。
- 前端只通过 API 获取真实状态，不硬编码市场判断。ECharts 按需注册图表/组件，处理 `ResizeObserver`、窗口尺寸变化、事件解绑和 `dispose()`。
- 当前工作区的终端化前端使用 `Workspace` 统一布局，`MarketOverview`、`RegimeAnalysis`、`FeatureAnalysis` 和 `Accounts` 分离页面职责；账号、审计和系统监控分别使用 `#/accounts`、`#/audit`、`#/system`。普通折线图通过 `Chart` 加载，状态散点/热力图通过 `RegimeChart` 加载，共享 `EChartsCanvas` 生命周期。浅色金融终端采用红涨绿跌，缺失值不附加涨跌颜色。顶部账号栏使用 `fixed` 定位，`app-frame` 在桌面/移动端分别预留 52/50px，避免主页滚动到底部时顶栏被裁切；该批次已获用户明确本地提交授权，不改变既有 `v0.3.4` 标签。
- 数据服务拥有文件、记录、标签、导入批次和目录缓存；特征服务拥有模型、状态历史、回放会话和逐日回放预警；预警服务从特征服务读取状态，用同一纯规则重建当前历史预警视图。
- 回放预警仍在特征服务内调用 `market_core.models.alerts.generate_alerts`，不增加逐日网络依赖。修改或恢复规则版本会重建当前历史预警视图，不改写已保存的回放结果。
- 主后端设置 `FEATURE_SERVICE_URL` 后不得再创建第二份模型或回放管理器。前端与 Nginx 只访问主后端；REST 代理须保留查询、正文、幂等键、状态码、控制响应头和错误结构，WebSocket 中继须保留上游关闭码。
- 不配置远程服务 URL 时保留本地单体模式，用于开发、算法回归和回退。

## 4. 配置、运行模式与存储事实源

`server/app/core/config.py` 按以下顺序选择配置文件：

1. `MARKETLENS_CONFIG` 指定文件；
2. 被 Git 忽略的 `server/config.json`；
3. `server/config.example.json`。

相对路径基于所选配置文件目录。`DATA_ROOT`、`DATABASE_PATH`、`CORS_ORIGINS`、存储/服务地址和组件开关可由环境变量覆盖；密码优先从环境变量注入。认证、限流、连接和审计保留策略的部分设置由对应模块直接读取环境变量，详见 `server/app/core/`、`compose.yaml` 和专项文档。

关键模式：

- `STORAGE_MODE=local|distributed`：默认本地 SQLite；`distributed` 必须同时 `CLICKHOUSE_ENABLED=true`，目录主读为 ClickHouse，不会静默切换事实源。
- `KAFKA_ENABLED=true` 开启 Kafka；Flink 通道依赖 Kafka，使用 `FLINK_ENABLED=true` 时必须同时配置可用的 Kafka 与 Flink REST。
- MySQL、MinIO、ClickHouse、Redis 在本地示例配置中默认关闭；Compose 显式开启。Redis 缓存故障可回到同一显式主存储，普通读取可按既定路径降级；管理、写入和租约操作失败关闭，不能承诺所有查询在 Redis 消失后仍可用。
- `DATA_SERVICE_URL` 为空时使用本地/分布式目录；设置后通过 `RemoteCatalogClient` 调用数据服务。
- `FEATURE_SERVICE_URL` 为空时使用本地模型与回放；设置后主后端通过远程客户端、REST 代理和 WebSocket 中继调用特征服务。特征服务自身不得设置该变量形成自调用。
- 独立预警服务必须设置 `FEATURE_SERVICE_URL`，需要背景证据时同时设置 `DATA_SERVICE_URL`。主后端的 `ALERT_SERVICE_URL` 在远程特征模式下启用预警代理和 readiness 检查。
- `RATE_LIMIT_MODE=local|redis`：本地默认进程内限制，Compose 使用 Redis Lua 共享配额。WebSocket 与回放计算还使用带续租和过期时间的连接/计算租约，默认每账号 3 个订阅、每服务 100 个连接、最多 2 个运行中回放。
- 远程 HTTP 调用必须有界超时，不做无界自动重试。非有限数值以 `null` 传输，规则按缺失值处理，不得输出非法 JSON `NaN`。

存储职责不能混淆：

- **SQLite**：本地目录主读和迁移基线；即使 distributed 模式也仍承担原始导入暂存、模型快照、回放、身份和规则等运行状态，不能描述为已完全移除。
- **ClickHouse**：distributed 模式的目录主读，按来源代次在线发布。新代次通过内容摘要、计数等核对后才切换发布指针；多文件发布不是跨库单一事务，失败保留旧代次。
- **MySQL**：文件和导入批次等元数据。
- **MinIO**：原始对象和到期审计归档；对象写入/核对与在线记录处理不是跨库原子事务，未启用对象锁，不宣称防管理员篡改。
- **Redis**：跨实例目录缓存、共享限流和租约；Python 数据服务另用有界 LRU 作进程内一级缓存。缓存键必须包含数据版本和查询参数，不得让 Redis 成为另一个事实源。Flink 没有目录热点，不引入无实际用途的 Caffeine。

## 5. 数据、模型、规则与回放口径

### 原始数据与解析

- 原始文件只读；除非任务明确要求，不得重写、覆盖或批量移动。保留原始 payload、来源文件、记录序号和事件时间，派生数据与原始层分开。
- 资产目录为 40 项，有效行情为 39 项；不得补造“全球高收益债”数据。行情加载剔除 NaN 和正负无穷，空序列不计入已加载资产。
- `指标集1_数据.xlsx` 有 31 个 sheet，字段经过脱敏；不得编造指标含义、赋予经济解释或强制转成日频。Excel 第一行是表头，目标工作簿处理全部 sheet。
- 新闻 CSV 约 1.83 GiB、900,704 条逻辑记录，无表头且正文含 HTML、链接和嵌入换行；当前只校验 11 列并以 `column_N` 保存。必须使用标准 CSV 解析器流式读取，不能按物理行解析或擅自命名字段。
- CSV 使用 UTF-8/UTF-8-SIG；大型文件分批读取和写入。科技帖子、公众号、日历、商品成交额和研究摘要保留原始字段、来源和事件日期；研究摘要从文件名提取日期、机构与标题。
- Windows 原始研究摘要可能超过 Linux 文件名长度限制。容器部署前用 `prepare_container_data` 在 `server/data/container-sources/research/` 生成短文件名副本及名称元数据，不改原文件。
- 标签由确定性关键词和结构字段生成，只用于检索，不代表情绪、因果或投资判断。目录最多组合 5 个标签，支持任一标签并集和全部标签交集。

### 特征与状态

- 只有 `field == "close"` 的资产进入价格收益与相关性计算；`yield` 是百分数，不是价格或小数。
- 不同资产按日期外连接，不统一填充交易日。收益为正价格的一阶对数差分，市场收益为当日资产收益横截面均值。
- 波动率为市场收益 20 日滚动标准差乘 `sqrt(252)`；动量为各资产 60 日涨跌幅均值；趋势为价格相对 20 日均线的偏离均值；相关性为 60 日资产收益成对相关系数均值，相关计算最少 20 个观测。
- 当前 StandardScaler + PCA + KMeans 只使用 `market_return`、`volatility`、`momentum`、`correlation`；`trend` 和 `sample_count` 只展示，不参与拟合。
- 默认模型参数：分析起点 2015-01-01，最少 504 个有效特征日，训练窗口 756 日，每 63 日重训，20 日波动窗口，60 日动量窗口，3 个聚类，随机种子 42。
- 每个识别日的训练切片必须排除当日，模型版本记录训练截止日；追加未来数据不得改变既有历史结果。状态名称由聚类中心确定性映射。本批新模型跨重训继承匹配身份，不能把局部 `cluster` 与 `regime_id` 混用；同名不同中心仍保留各自身份，跨独立训练的编号不保证可比。
- `confidence` 是聚类距离经指数权重归一化得到的相对值，不是预测正确率；贡献值是标准化偏离，不是因果贡献。

### 预警与证据

- 三类规则为 `HIGH_VOLATILITY`、`HIGH_CORRELATION` 和 `REGIME_CHANGE`。前两类使用此前状态日的历史分位数，默认至少 60 个历史状态日；状态标签变化生成切换预警。
- 可配置分位数范围为 0.50～0.99，历史窗口为 10～1000 个状态日，可开关状态切换规则。规则版本由规范化配置的 SHA-256 确定性生成。
- 统计证据保留当日/前一状态、实际值、阈值、历史日数、模型版本和训练截止日，不表示因果关系。
- 背景证据只关联前一状态日及此前的经济日历和公众号，保留来源时间口径；目录故障不应破坏核心统计证据。其他文本和宏观类型在时间语义未核实前继续排除。

### 历史回放

- 当前回放输入只有资产行情。完整入库不等于模型可见未来；任何一天只能读取当前事件时间及此前已发布的数据。
- 区分 `event_time` 与实际处理时间。宏观必须按核实后的公布时间、文本按自身发布时间进入，不得把统计期当成发布日期。
- 回放首日之前的历史只用于滚动窗口和模型预热；输入按事件日期递增，不为无观测资产伪造行情。相同输入与配置的特征、状态和预警必须与 walk-forward 基准一致。
- 三种通道共用 Python 模型。Kafka 负责事件传输，Flink 负责 1 日事件时间窗口、去重、乱序/迟到、检查点、Savepoint 和 Kafka 事务输出；不得另写 Java 金融算法或跳过必要容错提速。
- 会话、结果、运行 ID、Flink 作业/Savepoint、恢复状态和幂等操作持久化。恢复会重建模型内部状态，不是瞬时高可用切换。
- `/ws/replay/{session_id}` 推送真实快照和增量结果；断线通过会话 ID 与序列号从 REST 补拉，不重复执行模型。旧 `/ws/replay` 仅播放预计算状态作回归对照，两者都不是实时行情流。
- Flink 小数据逐日回放慢于本地是已知现象。优化须先测阶段耗时，不能恢复共享全局水位线、跳过窗口、关闭必要容错或读取未来数据。

## 6. 接口、前端与安全约定

### 接口和前端

- 主要 REST 覆盖健康/就绪、首页摘要、资产、状态、特征、预警/规则/证据、数据质量与目录、回放日历/会话/控制/结果、Kafka/Flink 状态、账号/审计、系统指标和依赖监控。
- GraphQL `/graphql` 当前只有 `assets`、`latestState`、`sourceSummary`，resolver 同样执行功能域鉴权。OpenAPI 由 FastAPI 在 `/docs` 和 `/openapi.json` 提供。
- HTTP 响应带 `X-Request-ID`；错误保留 `detail` 并增加 `error.code/message/request_id`。请求日志只记录路由模板、状态、耗时、请求 ID 等，不记录查询正文、敏感配置或密钥；内部异常和上游地址不得泄露给客户端。
- 首页使用轻量摘要，主要页面和图表按需加载；数据中心不得一次加载整库，文件目录、长文本和原始字段按需查询。
- 新闻、帖子、研究文本和原始字段均是不可信输入。React 按文本渲染，不使用 `dangerouslySetInnerHTML` 展示原始 HTML；缺失值显示为缺失，不填零。
- 前端使用自实现哈希路由和权限导航。Vite 开发服务器将 `/api`、`/graphql`、`/ws` 代理到 `VITE_API_TARGET`（默认 `http://localhost:8000`）；生产由 Nginx 同源代理。

### 认证、授权和限流

- `AUTH_ENABLED` 本地默认 `false`，Compose 固定 `true`。不要在不同进程间混用认证开关、身份库或签名信任域。
- 角色为 `observer`、`analyst`、`admin`；功能域为 `market`、`catalog`。观察者只读，分析员可控制回放，管理员管理账号、规则和系统功能。首页聚合和回放需要两个功能域，功能域不是行级或资产级数据权限。
- 用户 JWT 通过 HttpOnly、SameSite=Strict Cookie 或 Bearer 进入；密码使用随机盐 scrypt。直接业务服务也必须鉴权，内部预警状态接口只允许 alert 服务身份。
- 首次启用认证时没有默认账号密码。运行时生成一次性初始化凭据 `auth-bootstrap.txt`，创建首位管理员后失效；不得提交、截图、记录或在回复中复述其内容。
- WebSocket 连接中持续复核账号、会话和期限；未认证/撤销、权限不足、会话不存在、限流等使用既定关闭码，修改代理时不得破坏这些契约。
- 当前已是 Redis 共享限流和连接/计算租约，不再只是旧的单进程 IP 限制；但它仍不是完整身份平台、资源硬隔离或高可用。OAuth2/OIDC、MFA、行级权限、TLS 部署和密钥轮换工具尚未完成。
- HTTPS 部署应设置 `AUTH_COOKIE_SECURE=true`。当前系统不得描述为可安全暴露公网的生产系统。

### 通用安全红线

- 密钥只能通过环境变量或被 Git 忽略的私有配置注入。严禁把真实凭据写入源码、文档、命令、日志、测试夹具或 Git 历史。
- SQL 必须参数化；动态查询只能组合代码内固定片段、白名单标识符和占位符，用户输入只能作为参数。
- 原始赛题数据、`server/config.json`、`server/data/`、`.env`、运行数据库和构建/测试产物不得进入 Git。赛题 PDF/PPT 等未跟踪资料不要擅自纳入。
- 不用真实赛题账号、身份库或运行卷做自动化测试；E2E 使用独立合成数据和临时身份库。不要为验收生成虚假 AI 协作或性能证据。

## 7. 安装、运行、构建与部署

本地命令以 **Windows + Git Bash + Conda + Node.js** 为基准。除特别说明外，在仓库根目录执行；不要假设 Conda 环境可替代容器化验收。

首次安装：

```bash
conda env create -f environment.yml
conda run -n fintech python -m pip install -r requirements-dev.txt
cp server/config.example.json server/config.json  # 可选私有配置

cd web
npm ci --cache .npm-cache
cd ..
```

已有 `fintech` 环境时跳过创建。导入原始数据并启动本地单体：

```bash
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.import_data
PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000
```

仅旧数据库需要回填目录统计时执行：

```bash
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.import_data --rebuild-stats
```

另开终端启动前端：

```bash
cd web
npm run dev
```

访问 `http://localhost:5173`；OpenAPI 为 `http://localhost:8000/docs`，GraphQL 为 `http://localhost:8000/graphql`。首次后端初始化会计算真实历史特征。

本地多服务模式按依赖顺序启动：

```bash
PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.data_service:app --app-dir server --host 127.0.0.1 --port 8001

DATA_SERVICE_URL=http://127.0.0.1:8001 \
  PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.feature_service:app --app-dir server --host 127.0.0.1 --port 8002

DATA_SERVICE_URL=http://127.0.0.1:8001 FEATURE_SERVICE_URL=http://127.0.0.1:8002 \
  PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.alert_service:app --app-dir server --host 127.0.0.1 --port 8003

DATA_SERVICE_URL=http://127.0.0.1:8001 FEATURE_SERVICE_URL=http://127.0.0.1:8002 ALERT_SERVICE_URL=http://127.0.0.1:8003 \
  PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000
```

三个业务服务文档端口分别为 8001、8002、8003，前端仍只访问 8000/5173。启用认证时还需保持一致的身份配置，具体见 `docs/v0.3.4-authentication.md`。

容器部署：

```bash
cp .env.example .env
# 在 .env 设置本地强密码，不提交、不打印该文件

PYTHONPATH=".;server" PYTHONUTF8=1 python -m app.services.prepare_container_data
docker compose config
docker compose up --build
```

`bootstrap` 完成导入和发布后才启动 Web；首次全量初始化可能需要十几分钟。默认页面为 `http://localhost:5173`，后端为 `http://localhost:8000`。原始目录只读挂载，命名卷在普通 `down` 后保留；**没有备份不要执行 `docker compose down -v`**。

其他编排和构建：

```bash
# 仅基础设施，业务应用继续本地运行
docker compose -f compose.yaml -f compose.dev.yaml up --build

# 默认系统加可选 Flink
docker compose -f compose.yaml -f compose.flink.yaml up --build

# 在仓库根目录构建 Flink JAR
mvn -B -ntp -f flink/pom.xml -DskipTests package

# 重建方案 PDF 草稿；输出到 Git 忽略的 server/data/release/
cd web
npm run docs:submission
```

本地 Kafka/Flink 下载、主题、JAR 上传和 Savepoint 操作见 `README.md`。在线发布、主读切换、回退和故障验收见 `docs/stage-e-deployment.md`；回退必须显式选择原主读，不得让两套 API 同时接受管理写操作。

## 8. 测试、CI 与验收要求

完整本地回归：

```bash
PYTHONUTF8=1 conda run -n fintech python -m pytest --cov=market_core --cov=server/app --cov-report=term-missing --cov-fail-under=30 server/tests

cd web
npm test
npm run build
```

真实浏览器 E2E：

```bash
cd web
npm run test:e2e:install  # 本机已有可用 Chrome 时可跳过
npm run test:e2e
```

- pytest 通过 `pyproject.toml` 设置 `pythonpath = [".", "server"]`、默认测试目录和分支覆盖率；30% 是最低下限，不代表发布时实际覆盖率。
- Vitest 使用 jsdom 和 Testing Library，排除 `e2e/**`。前端行为测试中的 mock fetch、图表替身和后端 fake service 只验证组件/契约，不能代替真实 API、存储、broker、Flink、重启、容器和 Chrome 验收。
- Playwright 启动 `server/benchmarks/e2e_server.py` 和独立 Vite 端口；后者代理到真实 FastAPI 单体。测试后端生成 3 个合成资产、1,000 个工作日和独立身份库，不读取正式数据或账号。本地默认使用已安装 Chrome，CI 使用 Playwright Chromium。
- 修改解析、模型、接口、权限或服务边界时必须增加对应行为测试，特别是时间无未来泄漏、历史结果稳定、非有限值、错误契约和跨服务一致性；不能只验证导入或编译。
- 性能、正确性、恢复、真实数据和页面验收分别记录。小样本两日回放、单进程指标和合成 E2E 页面耗时不能外推为持续吞吐、独立用户并发或公网冷启动性能。

`.github/workflows/ci.yml` 在 main 推送和 Pull Request 时运行：

1. Python 3.12 后端完整 pytest 和 30% 分支覆盖率门槛；
2. Node 22 前端 `npm ci`、官方 registry 高危/严重漏洞审计、Vitest 和生产构建；
3. Playwright Chromium E2E，失败上传报告；
4. Java 17 Maven Flink 包构建；
5. 默认 + Flink Compose 配置校验及 backend/frontend 镜像构建。

CI 不使用真实赛题数据，也不替代 Kafka/Flink 实机、真实卷恢复和用户页面验收。本地通过不等于远端 CI 通过，发布后必须核对实际运行状态。

## 9. 开发风格、文档与 Git 约定

- Python 沿用 `from __future__ import annotations`、类型标注、数据类、`pathlib.Path` 和现有模块结构；使用 4 空格缩进，默认不写解释性噪声注释。
- TypeScript 保持严格类型、函数组件/Hooks、现有单引号和无分号风格；避免新增路由、状态管理或 CSS 框架，除非任务明确要求并同步依赖与文档。
- 沿用中文领域术语和现有 API 错误文本；文档使用项目主要语言中文，提交说明沿用仓库现有 Conventional Commits 风格。
- 修改模块边界、启动命令、配置、接口或数据口径时，同步更新 `README.md`、`docs/architecture.md`、相关专项文档和本文件；修改发布状态或验收数字时更新对应发布记录，不能靠旧文档推断新结果。
- 项目未采用 OpenSpec；培训材料中的流程不代表仓库现状。
- 版本号为 `v主版本.次版本.修订号`。每批已获初步验收、准备提交推送的可运行功能或修复须同步递增软件版本及标签，同系列按 v0.4.1、v0.4.2 递进，不能为等待整阶段完成而长期停在旧版；新大阶段升次版本。纯文档提交不单独升版。提交前运行 `python scripts/check_versions.py`，后端从 `app.version`、页面从前端包取版本；包/锁文件/镜像/Flink 一致性纳入 CI。v1.0.0 仍须满足全部正式门槛。
- **每批功能修改须经用户初步验收后提交/推送。用户明确约定：要求“继续开发”即表示前面已完成并汇报的批次已初步验收，可整理提交和推送；不重复索要确认。此授权不代表后续尚未完成的新批次自动验收，也不等于竞赛正式提交或生产部署授权。**
- 正式交付包括 40 页以内产品技术方案 PDF、含 Dockerfile/Compose/README 和覆盖率大于 30% 测试的 Git 仓库，以及 5 分钟以内 1080p MP4。方案草稿生成器和演示脚本已经存在，不等于终稿或视频已完成。
