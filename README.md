# 金融市场状态监控平台

2026 年上海科技大学第一届金融科技竞赛参赛项目。

本项目计划基于多资产行情、宏观指标、事件日历和舆情文本，建设覆盖数据接入、统一存储、实时特征计算、市场状态识别、风险预警和可视化的分布式监控平台。

## 当前状态

当前为 `v0.1.1` 测试版本，已跑通真实资产数据到 Web 看板的本地垂直闭环，并新增独立网站首页与工作台导航：

- 读取代码目录中的 39 个可用资产，共 314,318 条行情记录，区分价格与债券收益率。
- 计算市场收益、20 日年化波动率、60 日动量、趋势和资产相关性。
- 使用滚动训练窗口内的 StandardScaler、PCA 与 KMeans 逐日识别状态，训练数据严格早于识别日。
- 生成高波动、相关性异常和状态切换预警。
- 提供 REST、GraphQL、WebSocket 历史回放和 OpenAPI 文档。
- React 看板包含市场总览、状态分析、特征分析、预警中心和数据中心。

本轮尚未接入其余赛题文件，也尚未实现 Kafka/Flink、MySQL/ClickHouse/Redis/MinIO、独立微服务、完整权限、LLM 助手和 Docker Compose。最终竞赛交付仍需完成这些工作。

## 本地启动

要求：Windows + Conda + Node.js。以下命令在仓库根目录的 Git Bash 中执行。

```bash
# 首次创建环境；已存在时跳过
conda create -n fintech python=3.12 pip -y
conda run -n fintech python -m pip install -r requirements-dev.txt

# 可选：复制本地私有配置；config.json 与 server/data/ 不会进入 Git
cp server/config.example.json server/config.json

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

版本号采用 `v主版本.次版本.修订号` 的三段式格式，并通过 Git 标签标记版本。`v0.1.0` 已推送远程，当前补丁版本为 `v0.1.1`。

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
