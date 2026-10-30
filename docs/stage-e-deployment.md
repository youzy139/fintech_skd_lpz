# v0.3.3 阶段 E：容器、在线增量发布与主读切换

> 当前状态：部署实现、干净源码目录与全新数据卷复验及整体验收均已完成，用户已确认体验并同意发布 `v0.3.3`。

## 1. 部署文件与实测环境

- `server/Dockerfile`：Python 3.12 后端，固定运行依赖，非 root 用户，pip 使用带重试的 BuildKit 缓存。
- `web/Dockerfile`：Node 构建 React，非特权 Nginx 托管；`web/nginx.conf` 同源代理 REST、GraphQL 和 WebSocket。
- `flink/Dockerfile`：Maven 构建 Java 17 作业，Flink 2.2.1 运行镜像和持久检查点目录。
- `clickhouse/Dockerfile`：从 ClickHouse 官网固定版本安装包构建，强制 SHA-512 校验；当前容器为 25.8.4.13，已完成全量兼容性验收。
- `minio/Dockerfile`：官方历史镜像不可拉取，因此按既有本地验收方式，从 `RELEASE.2025-09-07T16-13-09Z` 固定源码构建，非 root 运行。
- `compose.yaml`：MySQL、ClickHouse、Redis、MinIO、Kafka、初始化、后端和前端八个默认服务。
- `compose.dev.yaml`：仅基础设施，Python/React 可继续本地热更新；Flink 不是默认开发依赖。
- `compose.flink.yaml`：可选 JobManager、TaskManager、Kafka 主题初始化和一次性作业提交；自动创建输入、输出和迟到主题并设置 `retention.ms=-1`，再启动 Flink，避免空卷或重建后因主题不存在反复重启。
- `deploy/config/container.json`、`.env.example`：无密钥配置与空模板；真实 `.env` 不进入 Git 或镜像。
- `server/app/services/prepare_container_data.py`：为 Linux 容器生成短文件名研究摘要副本，保留正文和原始名称元数据。

实测环境为 Docker Desktop 4.97.0、引擎 29.9.2、Compose 5.6.1、WSL 2。默认 bridge 网络提供项目级隔离；不能使用 `internal: true`，否则宿主机端口发布会被阻断。

本机 Docker Hub 直连不可用，经用户确认后仅在本机 Docker 配置使用 DaoCloud 加速。Python/Go 也支持临时构建参数：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
GOPROXY=https://goproxy.cn,direct \
docker compose up --build
```

项目默认值仍为官方 PyPI 和 Go 代理，镜像站配置不写入仓库。所有 Python 包继续执行哈希校验，ClickHouse 安装包固定 SHA-512。

## 2. 启动与数据预处理

先安装 Docker Desktop，复制 `.env.example` 为 `.env` 并设置强随机密码。赛题研究摘要中有超过 Linux 单文件名 255 字节限制的中文名称，Windows 可读取，但 Docker Desktop/WSL 枚举会中断。首次部署及原始摘要变化后，需要先在宿主机执行：

```bash
PYTHONPATH=".;server" PYTHONUTF8=1 python -m app.services.prepare_container_data
```

该命令只在被忽略的 `server/data/container-sources/research/` 生成副本，不移动或改写原始文件。短文件名保持日期并附原名摘要哈希；`.source-name.json` 保留原始文件名，解析时恢复日期、机构、标题和正文。Compose 默认把该目录以只读方式嵌套挂载到研究摘要位置，可用 `CONTAINER_RESEARCH_ROOT` 覆盖。

随后执行一键启动：

```bash
docker compose config
docker compose up --build
```

原始赛题目录默认只读挂载 `./上科大数据合集`，可用 `COMPETITION_DATA_ROOT` 覆盖。`bootstrap` 完成全量/增量导入、模型快照、MySQL 元数据、MinIO 对象和 ClickHouse 发布后才允许后端启动；失败不会带半份当前发布数据启动 Web。

```bash
docker compose logs -f bootstrap
```

页面为 `http://localhost:5173`，后端为 `http://localhost:8000`。首次全量初始化在当前机器约需十几分钟，后续未变化文件会跳过。命名卷在 `down` 后保留；没有备份前不要执行 `down -v`。

精简开发：

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

可选 Flink：

```bash
docker compose -f compose.yaml -f compose.flink.yaml up --build
```

重建后端时应同时重建前端容器，避免 Nginx 继续缓存旧后端 IP：

```bash
docker compose up -d --no-deps --force-recreate --wait backend frontend
```

## 3. 主读、发布与回退

`STORAGE_MODE=local` 默认读取 SQLite；`STORAGE_MODE=distributed` 必须同时显式启用 ClickHouse，否则拒绝启动。distributed 目录主读为 ClickHouse，Redis 故障只回到同一主存储。SQLite 仍承担原始导入暂存、模型快照和迁移基线，不能描述为已完全移除。

在线发布按单个来源文件执行：

1. SQLite 完成文件导入，MySQL 元数据和 MinIO 内容寻址对象先核对。
2. 新代次文件、记录、标签和统计写入 ClickHouse；只有失败重试存在同代次残留时才清理该代次。
3. 核对元数据、计数、完整记录摘要和标签内容，不只看总数。
4. 核对通过后更新 `catalog_publications`；六个 `active_source_*` 视图通过 `FINAL` 只读取当前代次。
5. 失败保留旧指针，强制重发使用新代次；多文件批次不是跨库单一事务，已成功文件保留，其余文件仍可重试。
6. 刷新可重建市场快照，再执行全局 SQLite/ClickHouse 对照。旧代次暂未自动清理，后续按生命周期策略回收。

常用命令：

```bash
python -m app.services.online_publish --initialize
python -m app.services.online_publish --source-id <source_id>
python -m app.services.online_publish --verify-only
```

回退时停止增量写入，按原本地命令以 `STORAGE_MODE=local` 重启，不删除任何新存储。不要让两套 API 同时接受管理写操作。

## 4. 已真实验收

### 全量数据与容器

- 八个默认服务均通过健康检查，后端和 Nginx 前端可由宿主机访问；可选 Flink 作业为 `RUNNING`。恢复实例时发现缺失 Kafka 主题会导致作业反复重启，已补自动主题初始化并重建验证，随后本地/Flink 同日回放再次一致。
- 最终口径为 1,046 个文件、1,556,492 条逻辑记录、1,000 篇研究摘要，导入错误为 0；市场快照为 3,340 个状态日、20,040 条状态日特征和 1,127 条预警。
- `online_publish --verify-only` 已对 MySQL、ClickHouse、SQLite 和全部 1,046 个 MinIO 原始对象独立回读核对通过。
- 停止并重建全部容器后，未变化文件跳过重导，命名卷数据保留。ClickHouse 25.8.4.13 与本地 26.11 CI 构建的结果口径一致。
- 短文件名副本保留原研究标题、机构、正文和原名元数据；标签交集与本地当前基线一致。

### API、页面与回放

- `/api/health` 明确返回 `storage_mode: distributed`；REST、GraphQL、Nginx 静态页面均实测通过。
- 12 线程并发执行 72 个真实目录请求全部返回 200。修复了 `clickhouse-connect` 同会话并发查询导致的 500，Web 读取使用可重入锁串行化共享客户端。
- 真实 Chrome 完成首页、工作台和数据中心验收，完整记录数正确，无请求失败横幅，浏览器错误为 0。截图位于被忽略的 `server/data/stage-e-landing.png` 和 `stage-e-catalog.png`。
- 本地直连与 Kafka 容器回放的 2026-04-27 结果一致；本地与 Flink 容器回放结果一致，事件生产、消费和窗口提交正常。
- Nginx WebSocket 代理已收到真实 `replay_day` 结果，事件日期和状态正确。

### 故障与回归

- 停止 Redis 后，核心查询仍返回 1,556,492 条记录；恢复后服务健康。
- 实际损坏一个 MinIO 派生对象时回读哈希失败，随后从只读原始文件恢复并再次验证通过。
- 注入 ClickHouse 暂存核对失败时，旧代次和全量查询保持可用；恢复后重试成功，新代次生效且总数不变。
- 后端 57 项测试通过，总体分支覆盖率 73.27%；前端 10 项测试和生产构建通过；默认、开发、Flink Compose 均通过真实 `config` 检查。
- `git diff --check` 通过，真实密钥未写入仓库。

## 5. 干净环境复验与剩余事项

- 已从干净源码导出目录 `server/data/stage-e-clean-checkout/` 和全新 Compose 项目 `marketlens-clean-e` 的空数据卷执行 `docker compose up --build -d --wait`，八个默认服务全部健康，未复用工作目录数据库或运行卷。
- 干净环境 `/api/health` 返回 `distributed`、39 个资产和 3,340 个状态日；`/api/data/summary` 返回 1,046 个文件、1,556,492 条记录、0 个错误。`online_publish --verify-only` 再次核对全部 1,046 个对象通过，本地直连与 Kafka 的 2026-04-27 回放结果一致。
- 干净复验项目已停止，数据卷保留；原体验项目已恢复并通过健康检查。两个环境的派生验收副本、配置和运行卷均不进入 Git。

后续事项：

1. 性能仍不能按正式版目标宣称达标：既有 ClickHouse 冷查询和 Redis 热查询测量偏慢，共享客户端串行化后需要重新测量 p50/p95/p99、并发和资源占用。
2. 长文件名预处理是 Windows 原始数据的必要步骤；正式交付必须保留清晰说明并验证用户从准备数据到启动的完整流程。
3. 微服务、完整认证授权、分布式限流、LLM 助手、宏观/文本进入分析或证据链仍未实现，属于后续版本，不影响本次部署事实，但意味着 `v1.0.0` 尚不能发布。
4. 用户已确认体验并同意发布 `v0.3.3`；`v0.3.4` 按用户要求暂缓，不在本次发布中开始实施。
