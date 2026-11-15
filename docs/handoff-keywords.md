# MarketLens 项目接手关键词

更新日期：2026-11-16。本文供下一位接手模型快速建立上下文，不能替代 `AGENTS.md`、`CLAUDE.md` 和实际代码。复制关键词后仍须阅读链接文档、检查 Git 工作区和复核当前数据，不能把本文数字当作未来批次的复验结果。

## 1. 可直接复制给接手模型

```text
你正在接手 MarketLens（2026 年上海科技大学金融科技竞赛）。先读 AGENTS.md、CLAUDE.md、README.md、docs/roadmap.md、docs/release-readiness.md、docs/v0.6.8-api-fast-path-performance.md，再运行 git status、git log 和 scripts/check_versions.py 核对实际状态。

当前基线是 v0.6.8；允许同版本追加提交，既有标签不移动。目录快速路径和统一 40 线程后，五类服务端路由 p95 约 33ms，但客户端新连接 p95 370.721ms、长连接 340.145ms，整体 API <50ms 仍未通过。不要把服务端分段、局部微基准或最后一轮热结果当成整体达标。

继续关闭真实强制缺口，不编造验收、金融效果、团队信息、事件标注或用户反馈。原始赛题数据只读；模型计算特征/状态，确定性规则生成预警，LLM 不参与状态、等级或回放结果。历史回放不是实时流。

每批检查后使用固定 5174/18000 验收，先核实进程归属，E2E 与手动预览不得同时占用。未获用户授权不提交；同一目标整体未奏效时不升版。允许提交时保持用户指定版本，使用中文 Conventional Commits；升版才同步八处版本声明并创建新标签。推送后必须核对准确提交的远端 CI。
```

## 2. 核心关键词

### 项目与模型

- **MarketLens / 上科大金融科技竞赛 / 研究决策支持 / 非自动交易**
- **多资产行情 → 特征 → walk-forward 市场状态 → 确定性预警 → Web / 历史回放**
- **StandardScaler → PCA → KMeans / centroid-alignment-v1 / cluster 局部编号 / regime_id 稳定身份**
- **训练切片排除识别日 / 无未来泄漏 / 完整滚动历史 / 旧回放结果不改写**
- **confidence 是相对距离 / 不是预测正确率 / ARI 不是金融事件准确率**
- **本地直连、Kafka、Flink 共用同一 Python 模型 / Java 不形成第二套金融算法**
- **历史回放不是实时流 / 单节点不是高可用 / 局部结果不是生产 SLA**

### 当前性能基线

- **v0.6.8 同版本追加 / 既有标签不移动 / 不创建 v0.6.9**
- **目录 data_version 精确 SHA-256 / PRAGMA data_version / 自身导入主动失效 / 外部连接触发重算**
- **非阻塞本地快速路径 / 目录锁竞争回退 / 缓存锁竞争回退 / 未命中回退 / 远程目录回退**
- **版本键仍逐次核对 / 权限先于缓存 / 不缓存账号裁剪结果 / miss 只计一次**
- **SERVER_THREAD_POOL_SIZE / AnyIO + asyncio.to_thread / 有界 40 线程 / readiness 前预热**
- **五类服务端路由 p95 33.368～33.697ms / 客户端整体仍未通过**
- **新连接 p95 423.317→370.721ms / 长连接 338.736→340.145ms / 后者上升**
- **长连接首轮 p95 450.194ms / 冷轮次不排除 / 全部 1,010 请求成功**
- **真实目录微基准平均减少 99.658% / 仅 SQLite 查询 / 不是 HTTP 提升**

### 验收与 Git

- **固定前端 5174 / 后端 18000 / strictPort / 不自动递增 / 不新增预览端口**
- **先检查 LISTENING 和命令行归属 / 只停止本项目且由我们启动的进程**
- **E2E 与手动预览互斥 / 前端直接启动 Vite node 入口并显式传入 web 根目录**
- **用户“继续开发”是前一已汇报批次的初步验收 / 但版本和提交方式以用户最新明确要求为准**
- **同一目标整体未奏效不升版 / 用户可明确要求同版本提交 / 标签不移动**
- **中文文档 / Conventional Commits / 精确暂存本批文件 / 不纳入用户原有修改**
- **升版八处声明 / check_versions.py / 锁文件只改根包两处 / npm ci 干跑**
- **本地通过不等于远端通过 / 核对准确提交的 backend、frontend、browser-e2e、flink、containers**

### 数据与安全

- **原始赛题文件只读 / 上科大数据合集、server/config.json、server/data、.env、运行数据库和测试产物不进 Git**
- **密码和密钥只从环境变量或忽略的私有配置注入 / 不进源码、文档、命令、日志、夹具或历史**
- **真实 auth-bootstrap.txt 不提交、不截图、不记录、不复述**
- **close 才进入收益和相关性 / yield 是百分数不是价格 / 不为缺失资产伪造行情**
- **非有限数值传输 null / 不输出非法 JSON NaN / 不用零代替缺失**
- **SQLite 本地目录 / ClickHouse distributed 主读 / Redis 不是事实源 / MySQL 元数据 / MinIO 原始对象**
- **JWT、角色、market/catalog、资产和来源白名单 / 受限账号不能读取全市场聚合结果**

### 下阶段强制缺口

- **API 客户端冷轮次与 p95 / 混合读写 / 持续吞吐 / 端到端 / 资源和故障矩阵**
- **Redis 热特征 <10ms / 真实 Redis、多实例、权限和故障复验 / 不用合成验证代替正式性能**
- **页面冷/热加载 / 慢网络 / Nginx、多进程和跨实例**
- **干净源码与空卷 Compose / 升级回退 / Savepoint / 候选部署**
- **真实金融事件标注、独立复核、episode 回测和误报报告 / 不得自动生成标注**
- **生命周期执行、全量来源质量、文本发布时间核实 / 未核实文本不得进入核心判断**
- **Flink 实时特征职责的可追溯确认 / 团队信息、竞赛 PDF、MP4 和最终提交回执**

## 3. 常用复核命令

```bash
# 后端完整回归
PYTHONUTF8=1 conda run -n fintech python -m pytest --cov=market_core --cov=server/app --cov-report=term-missing --cov-fail-under=30 server/tests

# 前端测试、构建与固定端口 E2E（执行前确认 5174/18000 没有手动预览）
npm --prefix web test
npm --prefix web run build
npm --prefix web run test:e2e

# 101 独立合成用户真实 HTTP 基准
PYTHONUTF8=1 conda run -n fintech python server/benchmarks/independent_user_performance.py --output server/data/benchmarks/independent-users.json

# 真实目录只读微基准
MARKETLENS_CONFIG="C:/Users/15214/Desktop/project/fintech/server/config.example.json" PYTHONPATH=. PYTHONUTF8=1 conda run -n fintech python server/benchmarks/catalog_version_performance.py

# 版本与暂存范围
python scripts/check_versions.py
git diff --check
git status --short
```

## 4. 接手后首先停止做的事情

- 不把旧文档中的“当前”数字当作新批复验结果。
- 不把同机、单进程、小样本或合成数据测量外推到公网、生产容量或金融效果。
- 不为获得更高版本号而提交整体未奏效的优化；也不因局部未达标而回滚已经验证正确且有证据的改进。
- 不修改原始赛题文件，不读取或输出真实账号和初始化凭据。
- 不让 LLM 决定状态、预警等级、回放结果或金融事件标签。
- 不移动既有标签，不把上一提交的 CI 成功套用到新提交。
