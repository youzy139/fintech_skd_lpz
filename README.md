# 金融市场状态监控平台

2026-11-12：用户要求继续开发，按约定初步验收并授权提交/推送已汇报的特征契约和 Redis 缓存两批。软件保持 `0.3.5`，不创建 `v0.4.0` 标签；下文 11-11 的“待体验”保留为历史状态。本日复验后端 202 项、覆盖率 78.18%，前端 43 项和生产构建通过。

2026 年上海科技大学第一届金融科技竞赛参赛项目。

2026-11-11 开发进展：`v0.3.5` 已推送，状态身份说明见 [发布记录](docs/releases/v0.3.5.md)。`v0.4.0` 完成特征定义/版本接口、新回放计算契约和 Redis 当前特征快照热读；特征页读取真实快照，监控页显示实际特征服务缓存状态。Redis 8.0.5 合成数据实测通过命中、TTL、损坏修复、断连/熔断恢复和 20 次认证 API 读取。开发批后端 201 项、覆盖率 78.18%，前端 43 项、生产构建和 Chrome E2E 通过。隔离预览为 `http://127.0.0.1:5177/#/features`，Redis 仅监听回环 `16379`。尚无真实数据、多实例或正式延迟结论；镜像构建受 Docker Engine 未运行阻塞。新开发批尚未提交，待用户体验。

当前版本：**v0.3.5 测试版**。本版修正重训编号置换造成的额外状态切换，保留旧回放算法与结果。用户已初步验收并授权提交/推送；镜像重建、人工事件标注和正式性能验收仍有缺口。见 [发布说明](docs/releases/v0.3.5.md)。

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
| 部署与治理 | Compose、Nginx、三个业务服务、JWT 权限及共享限流/审计已验收；订阅连接租约已部署并通过用户体验验收，见 [连接治理](docs/v0.3.4-connections.md) |

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
- `v0.3.4` 非有限值批次的自动化回归为后端 131 项、前端 20 项通过，Python 分支覆盖率 76.33%，前端生产构建通过；账号权限、共享限流/审计、连接租约和计算并发均已通过用户验收。早期历史非有限值已在 REST、WebSocket、持久化读取和前端类型中统一为缺失值，真实 2015-01-05 回放及 Chrome 验收通过，用户已明确验收完毕；既有并发记录见 [计算并发说明](docs/v0.3.4-replay-capacity.md)。
- `v0.3.3` 的默认八个容器服务已真实启动并完成全量导入；全部 1,046 个对象回读、Kafka/Flink 容器回放、Nginx WebSocket、真实 Chrome 和 Redis 停服回源均已验收。`v0.3.4` 新增独立数据、特征状态与预警服务后，默认编排为十一个服务；跨进程查询、真实回放、WebSocket 和停止/恢复均已验收。

这些效果证明的是**数据处理、模型链路和工程可靠性**，不代表已经获得投资收益、预测准确率优势或生产级高可用能力。

2026-11-02 入口评估与账号权限已通过用户验收：本阶段保留 Nginx + FastAPI，见 [评估报告](docs/v0.3.4-gateway-evaluation.md) 与 [选型 ADR](docs/adr-001-api-entrance.md)。用户已创建正式管理员，原身份库保持不变。Redis 共享配额、管理员审计页、订阅连接上限、回放计算并发、Kafka/Flink 异常治理、依赖监控与 Redis 熔断均已通过用户验收；配置与故障边界见各专项文档。Compose 默认开启认证，其他首次部署按 [认证说明](docs/v0.3.4-authentication.md) 设置账号。预警规则与证据批次为后端 150 项、前端 23 项，分支覆盖率 77.22%；真实规则、证据、首页一致性、重启、回滚及用户页面体验验收均通过。本批已本地提交，尚未推送。

补充治理批次的工程验证已完成：审计支持到期 MinIO 归档、在线保留下限、SHA-256 回读与按需查看；目录采用进程内有界 LRU + Redis 两级缓存，不为无目录读取的 Flink 强行引入 Caffeine；状态页新增 120 日特征热力图。后端 155 项、前端 26 项通过，分支覆盖率 77.17%，真实 ClickHouse/Redis/MinIO 验收通过，用户已确认提交本批。详见 [补充治理记录](docs/v0.3.4-supplemental-governance.md)。

宏观与文本背景批次已完成工程验证：预警证据只关联前一状态日的经济日历和公众号，保留来源时间口径，不参与模型或规则；新闻、指标、研究和社媒在时间语义未核实前继续排除。后端 158 项、前端 26 项通过，分支覆盖率 77.34%，真实日期与数据服务故障降级验证通过，右侧证据抽屉已通过用户页面验收。详见 [背景证据记录](docs/v0.3.4-context-evidence.md)。

性能与 CI 批次已形成首轮基线：顺序 API p95 为 16–27ms，100 路并发 p95 为 1.84–2.33s；单体 WebSocket 推送 p95 为 14.67ms；两日三通道结果一致但吞吐远低于 10 万条/秒目标，未宣称性能全面达标。后端 160 项、前端 26 项、真实 Chrome E2E 完整流程通过，覆盖率 77.25%。详见 [性能基线](docs/v0.3.4-performance.md) 与 [CI/E2E 说明](docs/v0.3.4-ci-e2e.md)。

### 2026-11-11 前端重构与发布准备

本批重构首页、桌面/移动工作台与统一视觉，加入哈希路由、权限导航、资产筛选、CSV 导出、特征历史图和错误重试；修复非有限行情、缺失资产统计及回放初始化覆盖用户日期的问题。安全修复后锁定 ECharts 6.1.0、Vite 6.4.6、Vitest 4.1.12。后端 162 项、前端 34 项及真实 Chrome 完整流程通过，分支统计模式总体覆盖率 77.31%，生产/容器构建通过，npm 官方审计无已知漏洞。

最新验收与剩余门槛统一见 [正式版准备清单](docs/release-readiness.md)、[数据质量报告](docs/data-quality-report.md)、[ER 与数据流](docs/data-model.md)、[产品技术方案稿](docs/submission/product-technical-design.md) 和 [演示脚本](docs/submission/demo-script.md)。本批按用户授权纳入 v0.3.4 测试版，仍未满足 v1.0.0 全部条件。

### 浅色金融终端重构（用户授权本地提交，版本保持 0.3.4）

在 `v0.3.4` 已发布基线之后，当前工作区进一步将首页、市场、状态、特征、预警、回放、数据中心、登录和系统管理统一为浅色专业金融终端：顶栏与深色侧导航、高密度表格、资产目录三栏研究布局、红涨绿跌和紧凑移动端。账号权限、审计记录、系统监控纳入 `#/accounts`、`#/audit`、`#/system` 哈希路由，支持刷新和浏览器后退。页面继续使用真实 API，不加入模拟实时报价或交易功能。

前端按页面拆分懒加载模块，普通折线图与状态散点/热力图分别注册，共享图表销毁和尺寸监听；预警证据抽屉支持键盘焦点循环，回放技术耗时按需展开。顶部账号栏使用固定定位，桌面和移动端分别保留 52/50px 内容空间，修复主页滚动到底部时顶栏向上裁切的问题；浏览器回归同时检查定位方式、完整可见性和顶部坐标。2026-11-11 用户明确要求保存当前本地状态，本批据此授权本地提交，版本保持 `0.3.4`，不移动既有标签；本次未推送，不补记用户页面体验结果，也不表示 `v1.0.0` 或赛题性能达标。

当前工作区实测：后端 162 项、前端 39 项测试通过，Python 分支统计总体覆盖率 77.31%；一条扩展 Chrome 全流程通过，覆盖管理路由、全部主要页面、真实两日回放及移动退出登录。生产构建、前端 Docker 镜像和 Flink Maven 构建通过，npm 官方审计 0 个已知漏洞。最大图表共享包约 480.07kB，已消除 500kB 构建提示。新终端可通过 `http://localhost:5175` 预览，代理真实后端 readiness 为 200；原 `5173` 环境未替换，仍需用户登录实际体验。

### 尚未达成

- 新闻、社媒、宏观和商品数据尚未进入回放模型。
- LLM 助手、OAuth2/OIDC 与行级权限尚未完成；已有 Redis 共享限流与协作式租约不等于完整身份平台或资源硬隔离。
- 当前处理的是历史数据回放，不是实时行情；单节点 Kafka/Flink 也不是高可用集群。
- ClickHouse 冷查询和 Redis 热缓存尚未达到正式版性能目标，完整模型回测、性能和故障恢复报告尚未形成。

## 后续版本计划

后续任务统一见 [版本路线与交付计划](docs/roadmap.md)：`v0.3.5` 正确性修复 → `v0.4.0` 数据与特征治理 → `v0.5.0` 性能优化 → `v0.6.0` 模型与应用效果 → `v0.9.0` 候选交付验收 → `v1.0.0` 正式交付。自定义看板、CEP、完整特征平台与 LLM 解释助手暂列 `v1.1.0` 扩展，强制要求不得延后。

竞赛截止 2026-12-31，正式版目标 12-28，保留提交缓冲；日期为计划，发布依赖实际验收。当前源码版本为 `v0.3.5`，既有 `v0.3.4` 标签不移动。

`v0.3.5` 状态身份专项已实现跨重训中心对齐，区分局部簇编号与稳定身份，并为旧回放保留原算法。真实历史切换预警 525→500（减少 27、增加 2，均在重训边界），数值计算和两类分位数预警一致；这不代表金融误报率已经改善。实现、兼容边界和验证见 [专项报告](docs/v0.3.5-regime-identity.md)，效果标注方法见 [评估协议草案](docs/model-evaluation-protocol.md)。本批已获用户初步验收及提交/推送授权；协议团队确认、人工标注和镜像重建仍待完成。

## 当前状态

当前版本为 `v0.3.5` 测试版，用户已初步验收并授权提交/推送状态身份修正及兼容方案。范围与限制见 [发布说明](docs/releases/v0.3.5.md)；性能达标、当前版本空卷复验、模型效果和竞赛终稿仍待完成，不代表 `v1.0.0`。以下 `v0.3.3` 阶段 A～E 的部署与空卷复验为历史验收记录：

- 1,046 个输入文件全部登记并导入本地 SQLite，共 1,556,492 条逻辑记录，首次全量导入无失败文件。
- 39 个可用资产包含 314,318 条行情记录；新闻 900,704 条、科技 41,413 条、宏观日历 185,753 条、研究摘要 1,000 篇，指标工作簿 31 个 sheet 全部处理。
- 数据中心按类型提供时间覆盖、预聚合记录量趋势、字段目录和友好内容列表；原始文件与字段下沉到核对区，HTML 不会注入页面。
- 概览统计随流式导入更新，旧数据库可从已入库记录回填；类型与文件明细均按日期倒序、服务端分页，每页默认 20 条，不把整库发送到浏览器。
- 数据中心支持确定性主题与结构标签，最多同时选择 5 个标签，支持任一标签并集、全部标签交集、组合筛选后的去重总数和记录级标签；可与类型、标题、日期和文件共同筛选。标签只用于检索，不表示情绪或投资判断。
- 首页使用轻量摘要，市场页面与数据中心按需加载；展开原始文件目录时才请求文件分页。
- 计算市场收益、20 日年化波动率、60 日动量、趋势和资产相关性。
- 使用滚动训练窗口内的 StandardScaler、PCA 与 KMeans 逐日识别状态，训练数据严格早于识别日。
- 生成高波动、相关性异常和状态切换预警，提供 REST、GraphQL、WebSocket 和 OpenAPI。
- 真实历史回放按事件日期逐日读取行情，只使用当日及此前历史重新计算特征、状态和预警；支持范围选择、暂停、继续、0.5～10 倍速和重开。会话、逐日结果、运行证据和恢复状态持久化到 SQLite；后端重启后可从已保存位置继续，WebSocket 重连按序列号补拉，控制接口支持幂等键。
- 回放支持本地直连、Kafka 事件和 Flink 窗口三种通道。单节点 Kafka 4.3.2 KRaft 与 `aiokafka` 已实际联通，日批次按日期作 key，消费者去重、缓存乱序、重试并在模型处理成功后手动提交连续位点。
- Flink 2.2.1 每次回放运行使用独立 Java 作业、消费者组和事件时间水位线，完成 1d 窗口、去重和迟到分流。后端等待作业与首检查点就绪后发送行情，结束时按作业 ID 停止并生成 Savepoint。连续运行、重开、乱序迟到、三通道一致性和 Savepoint 恢复均已验证；页面展示运行与作业证据。
- `v0.3.4` 已拆分 REST 路由，增加请求 ID、稳定错误码、结构化日志、readiness 和进程内延迟指标；回放快照与页面增加运行 ID、结果序列、恢复状态、Flink 作业 ID、Savepoint、模型初始化、通道初始化及逐日阶段耗时。
- 首页与工作台支持双向导航、平滑过渡、锚点滚动和精确回到顶部。

本地默认 SQLite，`STORAGE_MODE=distributed` 可显式切换 ClickHouse；Kafka/Flink 为单节点验证环境。三个业务服务已独立部署，逐日回放预警仍调用同一纯规则。本批共享身份模块使用独立 SQLite 库；OAuth2/OIDC、行级权限和 LLM 助手尚未实现。Compose 不是高可用系统。

**已知问题：** Flink 连续回放的全局水位线缺陷已修复，但每运行独立作业会增加启动与首检查点等待，小数据逐日回放仍慢于本地。ClickHouse 冷查询约 0.75–1.63 秒，当前分布式 Redis 热查询约 36–71ms，未达正式版 `<10ms` 热访问目标。真实单文件在线重发及全局核对约 30.7 秒，仍有派生刷新与全量核对开销。后续按 [v0.3.4 任务书](docs/v0.3.4-plan.md) 分阶段测量和优化，不通过牺牲一致性或容错提速。

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

上述命令默认保留本地单体目录、模型、预警与回放。需要在本地验证多服务模式时，依次启动数据服务、特征状态服务、预警服务，再启动只负责兼容接入的主后端：

```bash
PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.data_service:app --app-dir server --host 127.0.0.1 --port 8001

DATA_SERVICE_URL=http://127.0.0.1:8001 \
  PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.feature_service:app --app-dir server --host 127.0.0.1 --port 8002

FEATURE_SERVICE_URL=http://127.0.0.1:8002 \
  PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.alert_service:app --app-dir server --host 127.0.0.1 --port 8003

DATA_SERVICE_URL=http://127.0.0.1:8001 FEATURE_SERVICE_URL=http://127.0.0.1:8002 ALERT_SERVICE_URL=http://127.0.0.1:8003 \
  PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000
```

数据、特征状态和预警服务文档分别位于 `http://localhost:8001/docs`、`http://localhost:8002/docs` 和 `http://localhost:8003/docs`，前端仍只访问原地址。远程调用有界超时不自动重试；不可用返回明确 503。主后端在远程模式不创建第二份模型或回放管理器。

## 容器与分布式主读

```bash
cp .env.example .env
# 在 .env 设置本地强密码；不要提交该文件

# Windows 原始摘要含超长中文文件名，首次及摘要变化后先生成短文件名副本
PYTHONPATH=".;server" PYTHONUTF8=1 python -m app.services.prepare_container_data

docker compose config
docker compose up --build
```

预处理只在 `server/data/container-sources/` 生成副本，不修改原始文件。默认编排包含初始化、MySQL、ClickHouse、Redis、MinIO、Kafka、独立数据服务、特征状态服务、预警服务、兼容主后端和 Nginx 前端，共十一个服务；首次全量初始化约需十几分钟。内部服务只在 Compose 网络暴露，主后端统一代理数据、特征和预警接口。精简开发、可选 Flink、在线增量发布、故障验收和 SQLite 回退见 [阶段 E 部署与验收](docs/stage-e-deployment.md)。

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

需要 Java 17 和 Kafka。下载 [Flink 2.2.1](https://dlcdn.apache.org/flink/flink-2.2.1/) 到 `server/data/flink/flink-2.2.1`，下载 Maven 到 `server/data/maven/`。在仓库根目录执行：

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

通过 Flink REST 上传 JAR。正常回放不需要手工提交作业，后端会为每个 `run_id` 独立提交并管理生命周期：

```bash
curl --request POST --form "jarfile=@flink/target/marketlens-flink.jar" http://127.0.0.1:8081/jars/upload
```

手工诊断时使用 Flink 2.2.1 的 `programArgsList` 数组，并把参数名和值分开；`sessionId` 与 `runId` 必填。用上传响应中的 JAR ID 替换 `JAR_ID`：

```bash
JAR_ID=替换为上传响应中的ID
curl --request POST --header "Content-Type: application/json" \
  --data '{"entryClass":"com.marketlens.flink.DailyWindowJob","parallelism":1,"programArgsList":["--bootstrapServers","127.0.0.1:9092","--inputTopic","marketlens.replay.days.v1","--outputTopic","marketlens.features.days.v1","--lateTopic","marketlens.replay.late.v1","--checkpointInterval","5000","--checkpointDir","file:///C:/Users/15214/Desktop/project/fintech/server/data/flink/checkpoints","--sessionId","manual-session","--runId","manual-run"]}' \
  "http://127.0.0.1:8081/jars/$JAR_ID/run"
```

使用 `KAFKA_ENABLED=true FLINK_ENABLED=true` 启动后端，在“历史回放”选择“Flink 窗口”。后端等待作业 RUNNING 和首个检查点后发送行情，窗口结果通过 Kafka 事务提交，后端以 `read_committed` 消费。控制事件以最后事件日期加 3 天推进本运行水位线，不进入窗口或模型。结束通过 `POST /jobs/{jobid}/stop` 生成 Savepoint；恢复时使用相同 JAR、运行参数和 `savepointPath`。当前 REST 配置只表示按需连接，实际可用性以作业、检查点和回放结果为准。

## 测试与构建

```bash
PYTHONUTF8=1 conda run -n fintech python -m pytest --cov=market_core --cov=server/app --cov-report=term-missing server/tests
cd web && npm test && npm run build

# 独立合成数据环境；本地已有 Chrome 时可直接运行
cd web && npm run test:e2e
# 干净环境首次安装 Playwright Chromium
cd web && npm run test:e2e:install && npm run test:e2e
```

## 文档

- [总体架构设计](docs/architecture.md)：项目架构基线与模块职责。
- [v0.3.x 阶段计划](docs/v0.3.x-plan.md)：真实历史回放、Kafka/Flink、分布式存储的实施顺序与验收标准。
- [v0.3.3 任务书](docs/v0.3.3-plan.md)：MySQL、ClickHouse、Redis、MinIO、数据分层血缘、迁移与 Docker Compose；阶段 A～E 及干净空卷验收已完成并发布。
- [存储契约与迁移基线](docs/storage-contracts.md)：SQLite/后续存储的统一边界、全量内容摘要和迁移核对方法。
- [阶段 B 存储运行与验收](docs/stage-b-storage.md)：MySQL/MinIO 启动、全量迁移、幂等重跑与真实回读校验。
- [阶段 C ClickHouse 运行与验收](docs/stage-c-clickhouse.md)：WSL 2 启动、分层 schema、全量影子迁移与真实双读结果。
- [阶段 D Redis 运行与验收](docs/stage-d-redis.md)：热点缓存、内容版本失效、故障回源与真实 API 验证。
- [阶段 E 部署与验收](docs/stage-e-deployment.md)：Docker/Compose、在线增量发布、主读切换、回退、干净空卷复验和后续事项。
- [v0.3.4 发布说明](docs/releases/v0.3.4.md)：测试版范围、验证结果、升级与正式版缺口。
- [v0.3.4 任务书](docs/v0.3.4-plan.md)：原始目标、分批记录与测试版范围收口；未完成项转入后续开发。
- [v0.3.4 首批观测与基准](docs/v0.3.4-observability.md)：请求契约、路由指标、回放计时、三通道实测和连续 Flink 水位线修复。
- [v0.3.4 回放持久化与恢复](docs/v0.3.4-replay-persistence.md)：SQLite 会话结果、重启恢复、断线补拉、幂等控制及真实验收。
- [v0.3.4 Kafka/Flink 异常治理](docs/v0.3.4-replay-faults.md)：broker 重启、租约丢失、进程崩溃、遗留作业精确清理与 Savepoint 接管。
- [v0.3.4 依赖监控与 Redis 熔断](docs/v0.3.4-dependencies.md)：六类依赖探针、管理员监控页、读取降级与写操作失败关闭。
- [v0.3.4 预警规则与证据链](docs/v0.3.4-alert-rules.md)：确定性阈值、规则版本、历史版本恢复、审计和当日状态证据。
- [v0.3.4 宏观与文本背景证据](docs/v0.3.4-context-evidence.md)：前一状态日时间边界、来源时间口径、排除类型与故障降级。
- [v0.3.4 性能与资源基线](docs/v0.3.4-performance.md)：API/并发、WebSocket、三通道结果与未达标边界。
- [v0.3.4 CI 与持续浏览器 E2E](docs/v0.3.4-ci-e2e.md)：GitHub Actions、合成数据环境、真实 Chrome 全流程。
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

版本号采用 `v主版本.次版本.修订号` 的三段式格式，并通过 Git 标签标记版本。本次按用户最新授权发布 `v0.3.5` 测试里程碑；原计划的未完成目标在发布说明和正式版清单中保留。用户要求“继续开发”即表示前一已汇报批次初步验收并可提交/推送；`v1.0.0` 须完成全部正式验收。

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
