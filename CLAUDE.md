# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概览

MarketLens 是 2026 年上海科技大学金融科技竞赛项目：多资产行情 → 特征 → walk-forward 市场状态 → 确定性规则预警 → Web 展示/历史回放的监控与研究平台。当前源码与工件声明为 **v0.5.0 测试版**，不是 v1.0.0，也不是实时行情、高可用或可暴露公网的生产系统。项目约束、数据口径和验收规则的完整版本见 `AGENTS.md`，本文件是面向编码的补充摘要；两者冲突时以 `AGENTS.md` 为准。

核心红线：

- 原始赛题文件只读，不得重写、移动或补造缺失数据；`上科大数据合集/`、`server/config.json`、`server/data/`、`.env`、运行数据库和测试产物均被 Git 忽略。
- 数值特征与状态必须由模型计算，预警必须由确定性规则产生；LLM 不能决定状态、预警等级或回放结果。
- 不得把历史回放描述为实时流，不得把局部基准外推为正式性能/金融效果，不得编造验收结果或用户反馈。未实际运行的检查必须明确说未运行。
- 文档与提交说明使用中文，提交沿用 Conventional Commits 风格。
- 每批编译和检查后必须复用固定验收网址并打开网站，当前合成预览固定为前端 `5174`、后端 `18000`，不得新增预览端口；先检查进程归属，E2E 与手动预览不得同时占用这组端口。用户已授权停止经命令行核实属于本项目、由我们启动的预览进程以完成检查，随后同端口重启；前端优先直接启动 Vite 的 node 入口，避免 npm 子进程残留。
- 每批已汇报并获初步验收的功能/修复才提交推送，并同步递增版本与标签；纯文档不升版。用户说“继续开发”即视为前一批已初步验收，不重复索要确认。
- 升版须同步 `web/package.json`、`web/package-lock.json`、`server/app/version.py`、`flink/pom.xml` 及 `compose.yaml` / `compose.flink.yaml` 中的镜像标签；`scripts/check_versions.py` 以 Web 包版本为基准核对。

## 常用命令

本地基准为 Windows + Git Bash + Conda 环境 `fintech`（Python 3.12）+ Node 22。除特别说明外均在仓库根目录执行。

```bash
# 环境与依赖
conda env create -f environment.yml
conda run -n fintech python -m pip install -r requirements-dev.txt
cp server/config.example.json server/config.json  # 可选私有配置；已有环境跳过创建
cd web && npm ci --cache .npm-cache && cd ..

# 导入原始数据（首次或增量；旧库统计回填加 --rebuild-stats）
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.import_data

# 本地单体后端 / 前端
PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000
cd web && npm run dev        # http://localhost:5173，代理 /api /graphql /ws 到 8000

# 本地多服务（分四个终端按依赖顺序启动；主后端仍是前端唯一入口）
PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.data_service:app --app-dir server --host 127.0.0.1 --port 8001
DATA_SERVICE_URL=http://127.0.0.1:8001 PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.feature_service:app --app-dir server --host 127.0.0.1 --port 8002
DATA_SERVICE_URL=http://127.0.0.1:8001 FEATURE_SERVICE_URL=http://127.0.0.1:8002 PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.alert_service:app --app-dir server --host 127.0.0.1 --port 8003
DATA_SERVICE_URL=http://127.0.0.1:8001 FEATURE_SERVICE_URL=http://127.0.0.1:8002 ALERT_SERVICE_URL=http://127.0.0.1:8003 PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8000

# 后端测试（pyproject 已配置 pythonpath 和 branch coverage）
PYTHONUTF8=1 conda run -n fintech python -m pytest --cov=market_core --cov=server/app --cov-report=term-missing --cov-fail-under=30 server/tests
PYTHONUTF8=1 conda run -n fintech python -m pytest server/tests/test_models.py
PYTHONUTF8=1 conda run -n fintech python -m pytest server/tests/test_models.py::test_walk_forward_history_does_not_change_when_future_is_appended

# 101 独立合成用户真实 HTTP 基准（固定 18000，被占用时先停止所属预览）
PYTHONUTF8=1 conda run -n fintech python server/benchmarks/independent_user_performance.py --output server/data/benchmarks/independent-users.json

# 前端测试 / 构建
cd web && npm test
cd web && npm test -- src/App.test.tsx          # 单个测试文件
cd web && npm run build                          # tsc -b && vite build

# 真实浏览器 E2E（启动合成后端 + 独立 Vite 5174；本地默认用已装 Chrome）
cd web && npm run test:e2e
cd web && npm run test:e2e:install               # 无本机 Chrome 时先安装 Chromium
cd web && E2E_CHANNEL=chromium npm run test:e2e  # 显式改用 Chromium；CI 自动使用它
cd web && npx playwright test e2e/workspace.spec.ts -g "管理员可以复核市场证据并完成真实两日回放"

# 版本一致性（提交前必须运行；CI 也会跑）
python scripts/check_versions.py

# Flink JAR 与容器
mvn -B -ntp -f flink/pom.xml package
cp .env.example .env    # 填入本地强密码，不提交、不打印
PYTHONPATH=".;server" PYTHONUTF8=1 python -m app.services.prepare_container_data
docker compose config
docker compose up --build
```

注意：

- 没有配置 Ruff、Black、mypy、ESLint 或 Prettier，前端也没有覆盖率脚本；不要声称这些检查存在或通过。
- `npm run test:e2e` 使用 `server/benchmarks/e2e_server.py` 的独立合成数据与临时身份库（端口 18000），不读取正式数据或账号。
- 小样本两日回放、单进程指标和合成 E2E 页面耗时不能外推为吞吐、并发或公网冷启动性能。

## 架构与模块边界

```text
market_core/            纯领域与算法，禁止依赖 server/ 或 web/
  domain/               资产、事件、回放、来源、标签数据结构
  ingestion/            行情、CSV/Excel、新闻/Markdown 流式解析
  models/               features / regime / alerts / replay / feature_contracts
server/app/
  api/                  auth、system、market、data、replay 路由与请求契约
  core/                 config、auth、governance、observability、leases、resilience、serialization
  services/             目录/存储/缓存/远程客户端/回放/发布/迁移等服务实现
  main.py               单体或兼容代理，组装 REST/GraphQL/WebSocket
  data_service.py       独立数据目录服务（8001）
  feature_service.py    独立特征、状态与回放服务（8002）
  alert_service.py      独立历史预警、规则与证据服务（8003）
web/src/                React 页面、API 类型、ECharts 封装与 Vitest
flink/                  Java 事件时间窗口、Caffeine 热点去重、迟到与容错作业
deploy/config/          Compose 分布式无密钥配置
docs/                   架构、数据口径、专项验收、发布记录与交付材料
```

关键职责：

- 数据服务拥有文件、记录、标签、导入批次与目录缓存；特征服务拥有模型、状态历史、回放会话与逐日预警；预警服务从特征服务读取状态，并用同一纯规则重建历史预警视图。
- 主后端设置 `FEATURE_SERVICE_URL` 后只做远程代理与 WebSocket 中继，不得再创建第二份模型/回放管理器；特征服务自身不得设置该变量形成自调用。
- 不设置远程 URL 时保留本地单体模式，用于开发、算法回归与回退。Nginx + FastAPI 仍是对外单入口，前端只访问主后端。
- 回放预警在特征服务内直接调用 `market_core.models.alerts.generate_alerts`，不增加逐日网络依赖；修改/恢复规则只重建当前视图，不改写已保存回放结果。

存储事实源不能混淆：

- SQLite：本地目录主读与迁移基线；distributed 模式下仍保存原始导入暂存、模型快照、回放、身份和规则。
- ClickHouse：`STORAGE_MODE=distributed` 时的目录主读，按来源代次在线发布；distributed 必须显式 `CLICKHOUSE_ENABLED=true`，不会静默切换。
- MySQL 存文件/批次元数据；MinIO 存原始对象与到期审计归档；Redis 是跨实例目录缓存、共享限流和租约，不是另一个事实源。
- 缓存键必须包含数据版本和查询参数；账号裁剪结果不得进入共享缓存。

## 配置与运行模式

`server/app/core/config.py` 按顺序选择配置：`MARKETLENS_CONFIG` → `server/config.json` → `server/config.example.json`，相对路径基于所选配置文件目录。

- `STORAGE_MODE=local|distributed`；`KAFKA_ENABLED`、`FLINK_ENABLED` 默认关闭，Flink 依赖 Kafka 与 Flink REST。
- `DATA_SERVICE_URL`、`FEATURE_SERVICE_URL`、`ALERT_SERVICE_URL` 决定是否走远程服务；独立预警服务必须设置 `FEATURE_SERVICE_URL`，需要背景证据时同时设置 `DATA_SERVICE_URL`。远程 HTTP 调用有界超时，不做无界自动重试，失败返回明确 503。
- `AUTH_ENABLED` 本地默认 `false`，Compose 固定 `true`；角色 `observer` / `analyst` / `admin`，功能域 `market` / `catalog`，另有账号级资产/来源 ID 白名单。
- 多服务模式必须保持一致的认证开关、身份库和签名信任域，直接访问 8001–8003 也不能绕过鉴权。首次启用认证没有默认账号；一次性初始化凭据写入身份库旁的 `auth-bootstrap.txt`，创建首位管理员后删除，不得提交、截图、记录或在回复中复述。
- `RATE_LIMIT_MODE=local|redis`；WebSocket 与回放计算使用带续租和过期时间的租约。本地内存限流直接在事件循环执行，Redis 限流保留线程池隔离。
- 目录进程内 LRU 默认启用，即使没有 Redis；`CATALOG_LOCAL_CACHE_ENABLED=false` 可关闭。`SERVER_THREAD_POOL_SIZE=1..256` 仅在显式设置时调整 AnyIO 工作线程，默认 40。
- 密码和密钥只通过环境变量或被忽略的私有配置注入，不得进入源码、文档、命令、日志、测试夹具或 Git 历史。

## 核心数据与算法口径

- 只有 `field == "close"` 的资产进入收益与相关性；`yield` 是百分数，不是价格。不得为无观测资产伪造行情。
- 特征：市场收益为资产对数收益横截面均值；波动率为 20 日滚动标准差 × √252；动量为 60 日涨跌幅均值；趋势为相对 20 日均线偏离；相关性为 60 日成对相关均值（至少 20 个观测）。
- 模型只用 `market_return`、`volatility`、`momentum`、`correlation`；`trend` 和 `sample_count` 只展示。StandardScaler → PCA → KMeans，默认分析起点 2015-01-01、最少 504 个特征日、训练窗口 756、每 63 日重训、3 簇、种子 42。
- 每个识别日的训练切片必须排除当日；追加未来数据不得改变既有历史结果。`cluster` 是局部编号，`regime_id` 是跨重训匹配身份，标签后缀使用后者；旧快照缺 `model_identity` 时沿用 `local-cluster-v1`，不得重写已保存结果。
- `confidence` 是相对聚类距离，不是预测正确率；特征贡献是标准化偏离，不是因果贡献。
- 预警只有 `HIGH_VOLATILITY`、`HIGH_CORRELATION`、`REGIME_CHANGE`，使用此前状态日的历史分位数（默认至少 60 日），规则版本为规范化配置的 SHA-256。统计证据不表示因果。
- 当前只有行情进入模型与回放；经济日历和公众号仅作为前一状态日的背景证据；新闻、宏观指标、研究摘要、社媒在时间语义核实前不得接入核心判断。
- 回放严格按事件日期递增，只读取当日及此前已发布数据；区分 `event_time` 与处理时间，不得把统计期当发布日期。三种通道（本地直连 / Kafka / Flink）必须共用同一 Python 模型，Java 只做事件、窗口、热点去重缓存和容错；Caffeine 未命中或恢复后必须回源 Flink `ValueState`。

## 前端约定

- React 19 + TypeScript 严格模式，函数组件/Hooks，单引号、无分号；没有路由库、状态管理库或独立 CSS 框架。
- 自实现哈希路由 + 权限导航；页面懒加载，图表面板与状态图表分别注册，共享 `EChartsCanvas` 生命周期，必须处理 `ResizeObserver`、尺寸变化、事件解绑和 `dispose()`。
- 只通过 API 展示真实状态，不硬编码市场判断；缺失值显示为缺失，不填零，不附加涨跌颜色。
- 原始文本/HTML 一律按文本渲染，禁止 `dangerouslySetInnerHTML`。
- 浅色金融终端采用红涨绿跌；顶栏固定定位，`app-frame` 在桌面/移动端分别预留 52/50px。

## 接口与安全约定

- REST 错误保留 `detail`，并增加 `error.code/message/request_id`；响应带 `X-Request-ID`；日志只记录路由模板、状态、耗时等，不记录查询正文、敏感配置或密钥。
- 非有限数值以 `null` 传输，规则按缺失值处理，不得输出非法 JSON `NaN`。
- SQL 必须参数化；动态查询只用代码内固定片段、白名单标识符和占位符。
- WebSocket 关闭码、幂等键、控制响应头和代理错误结构是既有契约，修改代理时不得破坏。

## 修改后的验证要求

- 修改解析、模型、接口、权限或服务边界时增加对应行为测试，重点覆盖时间无未来泄漏、历史结果稳定、非有限值、错误契约和跨服务一致性。
- 完整回归按“后端 pytest + 覆盖率、前端 Vitest、生产构建、Chrome E2E”执行；改动涉及发布状态或验收数字时更新对应 `docs/releases/*`、`README.md` 和 `AGENTS.md`，不得用旧文档推断新结果。
- 本地通过不等于远端 CI 通过；发布后须核对实际 CI 运行状态。
- 更多细节：`AGENTS.md`、`README.md`、`docs/architecture.md`、`docs/data-model.md`、`docs/data-quality-report.md`、`docs/release-readiness.md`、`docs/roadmap.md`。
