# AGENTS.md

## 项目概览

本目录是 **2026 年上海科技大学第一届金融科技竞赛参赛项目**，产品名为 **MarketLens**，当前版本为 `v0.2.2` 测试版本。项目基于多资产行情、宏观指标、事件日历和舆情文本，建设市场状态（Market Regime）监控平台，覆盖数据接入、特征计算、状态识别、风险预警和可视化。

当前已经实现的本地闭环：

- 发现并导入全部 1,046 个赛题输入文件，本地 SQLite 中共有 1,556,492 条逻辑记录，当前文件级导入错误为 0。
- 读取 39 个可用资产序列，保留原始交易日历、`close`/`yield` 字段差异及数据质量统计。
- 计算市场收益、年化波动率、动量、趋势和资产相关性，使用滚动历史窗口内的 StandardScaler、PCA 与 KMeans 逐日识别状态。
- 生成高波动、相关性异常和状态切换预警。
- 提供 REST、GraphQL、WebSocket 历史回放、OpenAPI 和简单进程内限流。
- React 工作台包含网站首页、市场总览、状态分析、特征分析、预警中心和数据中心；首页使用轻量摘要，市场页面与数据中心按需加载。数据中心提供预聚合概览、时间覆盖、字段目录、友好内容、服务端分页和安全的原始字段核对。
- 已有后端 pytest、前端 Vitest、分支覆盖率配置和生产构建流程。

**当前实现不是分布式系统。** SQLite 是本地持久化方案；Kafka/Flink、MySQL/ClickHouse/Redis/MinIO、独立微服务、完整认证授权、LLM 助手和 Docker Compose 均未落地。不得把竞赛目标、架构规划或性能指标描述成已经实现或已经验收的能力。

核心业务流程为“状态判断 → 预警决策 → 分析建议”。数值特征与状态由数学模型计算，预警由确定性规则产生；规划中的 LLM 只负责文本理解、证据整合与解释，不应成为核心链路的单点依赖。

## 技术栈与关键配置

| 文件 | 实际用途 |
| --- | --- |
| `environment.yml` | Conda 环境 `fintech`，仅固定 Python 3.12 和 pip |
| `requirements.txt` | 固定版本的运行依赖：FastAPI、Uvicorn、NumPy、pandas、scikit-learn、Strawberry GraphQL、openpyxl 等 |
| `requirements-dev.txt` | 引入运行依赖，并增加 pytest、pytest-cov、httpx |
| `pyproject.toml` | 只配置 pytest 路径和 Coverage；不是 Python 包构建配置，也不声明项目依赖 |
| `server/config.example.json` | 无密钥运行配置模板，包含数据目录、SQLite 路径、模型、预警、回放和 CORS 参数 |
| `web/package.json` | React 19、TypeScript 5.7、Vite 6、ECharts 5、Vitest 3 及前端脚本 |
| `web/package-lock.json` | npm 锁文件，锁文件版本为 3 |
| `web/tsconfig.json` | TypeScript 严格模式、ES2022、Bundler 模块解析、`noEmit` |
| `web/vite.config.ts` | React 插件、开发代理和 Vitest 的 jsdom 配置 |
| `.gitignore` | 忽略原始数据、本地密钥、私有配置、SQLite、依赖目录和构建/测试产物 |

后端使用 Python 3.12 和标准库 `sqlite3`，不依赖 ORM。前端使用函数组件和 React Hooks，无路由库、状态管理库或独立 CSS 框架。当前没有配置 Ruff、Black、mypy、ESLint、Prettier，也没有前端覆盖率脚本；不要声称这些检查已存在。

`server/app/core/config.py` 优先读取被 Git 忽略的 `server/config.json`，不存在时回退到 `server/config.example.json`。配置中的相对路径均相对于所选配置文件所在的 `server/` 目录解析。默认模型参数为：分析起点 2015-01-01、最少历史 504 个有效特征日、训练窗口 756 日、每 63 日重训、20 日波动窗口、60 日动量窗口、3 个聚类、随机种子 42。

## 目录与模块职责

```text
.
├── market_core/                  # 独立领域与算法核心，不依赖 FastAPI、server 或 web
│   ├── domain/
│   │   ├── market.py            # 资产、数据质量和预警数据类
│   │   ├── sources.py           # 来源文件、来源记录和导入结果数据类
│   │   └── tags.py              # 确定性主题关键词与结构字段标签规则
│   ├── ingestion/
│   │   ├── assets.py            # 资产目录读取、行情校验、重复日期与非法行处理
│   │   └── sources.py           # 固定数据源发现及 CSV、Excel、Markdown 流式适配
│   └── models/
│       ├── features.py          # 多资产行情面板与市场特征
│       ├── regime.py            # walk-forward 标准化、PCA、KMeans 状态识别
│       └── alerts.py            # 高波动、相关性异常和状态切换规则
├── server/
│   ├── app/
│   │   ├── core/config.py       # 配置加载与路径解析
│   │   ├── services/
│   │   │   ├── import_data.py   # 全量/增量导入及旧库统计回填入口
│   │   │   ├── catalog.py       # 文件、记录、预聚合概览和导入批次的 SQLite 存取
│   │   │   ├── market.py        # 应用组装：加载资产、计算特征/状态/预警并保存快照
│   │   │   └── storage.py       # quality、states、alerts 快照写入
│   │   └── main.py              # FastAPI、REST、GraphQL、WebSocket、CORS 与限流入口
│   ├── tests/                   # 核心、导入、SQLite 和接口测试
│   ├── config.example.json      # 可提交的配置模板
│   ├── config.json              # 可选本地私有配置，Git 忽略
│   └── data/                    # SQLite 等运行时产物，Git 忽略
├── web/
│   ├── src/App.tsx              # 工作台外壳及首页/市场/数据中心按需加载
│   ├── src/Landing.tsx          # 产品首页与轻量摘要
│   ├── src/SourceCatalog.tsx    # 数据概览、标签筛选、友好内容、分页和原始核对
│   ├── src/Chart.tsx            # 按需注册 ECharts 的图表包装组件
│   ├── src/api.ts               # fetch 封装
│   ├── src/types.ts             # API 数据类型
│   ├── src/motion.ts            # 回到顶部动画与减少动态效果适配
│   ├── src/styles.css           # 集中样式
│   └── src/App.test.tsx         # Vitest + Testing Library 测试
├── docs/architecture.md         # 目标架构与当前实现的混合设计文档，阅读时注意区分
├── README.md                    # 启动、测试、版本和项目定位
└── 上科大数据合集/              # 原始竞赛输入，Git 忽略
```

`server/app/api/` 当前只有空包文件，实际接口集中定义在 `server/app/main.py`。不要根据目录名假定已经拆成多个 API 路由或微服务。

## 当前运行架构与数据流

1. `python -m app.services.import_data` 按固定清单发现资产 CSV、4 个 Excel 工作簿、科技帖子 CSV、新闻 CSV 和研究摘要 Markdown。
2. `CatalogStore` 将文件元数据写入 `source_files`，将每条原始记录以 JSON 写入 `source_records`，同步累计 `source_daily_stats`、`source_fields`、`source_record_tags` 和 `source_tag_stats`，并在 `import_batches` 记录批次。默认每 1,000 条逻辑记录提交一次；Excel 使用只读模式。文件大小、修改时间和成功状态均未变化时跳过重导。记录冗余保存 `kind`，配合日期与标签索引避免大表全排序；旧库打开时自动补充字段和索引，`--rebuild-stats` 同时重建统计与标签。标签由 `market_core/domain/tags.py` 的确定性关键词和结构字段生成，仅用于检索，不表示情绪或投资判断。标签关联表冗余保存事件日期，筛选时直接复用标签计数与日期索引；本地共享 SQLite 连接通过可重入锁串行访问，避免并发请求互相干扰游标。
3. `MarketService.initialize()` 在后端启动时重新读取原始资产文件，计算全部历史特征、状态和预警；结果保存在内存中供接口查询，同时写入 SQLite 的 `snapshots` 表。
4. `SnapshotStore` 当前只提供保存和关闭方法，没有快照读取或启动恢复逻辑；不能把快照描述成已经生效的模型缓存。
5. 首页只请求轻量摘要；市场页面进入工作台后加载市场数据，数据中心独立请求预聚合概览和当前页记录，文件目录只在展开时加载。GraphQL 与 WebSocket 已在后端提供，但当前页面没有使用它们。
6. Vite 开发服务器把 `/api`、`/graphql` 代理到 `localhost:8000`，把 `/ws` 代理为 WebSocket。生产构建输出到 `web/dist/`；仓库尚无统一的生产启动或静态文件托管流程。

### 特征、模型与预警口径

- 只有 `field == "close"` 的资产进入价格收益和相关性计算，`yield` 序列不当作价格。
- 不同资产按日期外连接，不统一填充交易日。收益为正价格的一阶对数差分，市场收益是当日资产收益的横截面均值。
- 波动率为市场收益的滚动标准差乘以 `sqrt(252)`；动量为各资产 60 日涨跌幅的均值；趋势为价格相对 20 日均线的偏离均值；相关性为 60 日窗口内资产收益成对相关系数的均值。
- 状态模型实际使用 `market_return`、`volatility`、`momentum`、`correlation` 四个特征；`trend` 和 `sample_count` 随结果输出，但不参与当前 PCA/KMeans 拟合。
- 每个识别日的训练切片都排除当日，模型版本记录训练数据截止日。扩展未来数据不应改变已经产生的历史结果。
- 状态名称由聚类中心的确定性规则映射，并带聚类编号；贡献值是当前特征相对训练窗口的标准化偏离，不表示因果贡献。
- 高波动和高相关性预警使用此前至少 60 个状态日的历史分位数；状态标签变化会生成状态切换预警。

### 对外接口

- REST：`/api/health`、`/api/home/summary`、`/api/assets`、`/api/assets/{code}/series`、`/api/regimes/latest`、`/api/regimes`、`/api/features/latest`、`/api/alerts`、`/api/data/quality`、`/api/data/summary`、`/api/data/overview`、`/api/data/tags`、`/api/data/records`、`/api/data/files`、`/api/data/files/{source_id}/records`。
- GraphQL：`/graphql`，当前查询字段只有 `assets`、`latestState`、`sourceSummary`。
- WebSocket：`/ws/replay`，按历史状态发送消息并携带事件时间与回放时间；单次最多 100 条状态消息。这不是 Kafka/Flink 实时流。
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

仓库当前没有 Dockerfile、Compose 文件、Kubernetes 配置或一键部署脚本，当前环境也没有可用的 Docker 命令。不能把本地 Conda + Vite 启动描述为已经完成容器化交付。

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

- 后端 20 项测试通过，覆盖多行新闻 CSV、社媒日期规范化、全部指标 sheet、研究摘要元数据、资产重复/非法数据、字段校验、增量导入、统计与标签回填、标签词边界和组合筛选、90 次并发目录查询、概览与分页、walk-forward 防未来泄漏、预警证据、REST、GraphQL 和 WebSocket。
- 后端当前总体分支覆盖率为 81.82%，高于 30% 的竞赛门槛；`import_data.py` 的命令行主流程仍未被自动化测试覆盖。
- 前端 5 项测试通过，覆盖轻量首页、工作台导航、数据中心独立加载、类型切换、标签筛选与清除、服务端翻页、文件按需目录、安全文本和精确回到顶部。
- 后端接口测试使用 fake service，前端测试 mock `fetch` 和图表；这些测试本身不是原始数据到页面的完整端到端验收。
- 已对真实 1,556,492 条记录回填统计和标签，验证八类数据概览、标签目录与每页 20 条查询；新闻普通分页约 14 毫秒，新闻“人工智能”标签筛选从约 1.46 秒优化到约 17 毫秒。真实 Chrome 已检查首页、工作台、数据中心、日期、标签筛选、记录标签和清除筛选。
- 当前没有 CI 工作流、可持续运行的浏览器端 E2E 测试套件、容器部署验收、性能压测报告或前端覆盖率统计。

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
