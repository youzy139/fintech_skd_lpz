# v0.3.3 阶段 D：Redis 热点缓存与故障回源

> 当前状态：阶段 D 已完成本地真实服务验收。Redis 8.0.5 在 WSL 2 中运行，缓存命中、内容版本失效、真实故障回源和 MarketService API 接入均已验证。SQLite 仍是事实数据源。

## 1. 实现边界

- `server/app/services/cache.py`：JSON 缓存、键生成、TTL、命中统计和 `CachedCatalogStore` 回源包装。
- `CatalogStore.data_version()`：根据文件 ID、大小、mtime、状态、记录数、错误数和更新时间生成内容版本。
- `ClickHouseCatalogStore.data_version()`：为后续双读/切换提供同样语义。
- `MarketService`：只有 `REDIS_ENABLED=true` 或私有配置启用时才包装目录存储，默认仍直接读取 SQLite。

缓存不是永久数据库，不保存无法重建的事实，不改变市场模型、预警或回放。

## 2. 缓存键与失效

缓存键由以下信息计算 SHA-256：

```text
namespace + 数据库内容版本 + 查询方法 + 全部查询参数
```

当前 namespace 为 `marketlens:catalog:v1`，默认 TTL 为 60 秒。文件重新导入后，内容版本改变，新查询自动使用新键；旧键按 TTL 过期。即使 Redis 重启或失效通知丢失，也不会因为旧命名空间仍在而返回上一版本结果。

覆盖范围：

- 数据汇总、分类概览和标签目录。
- 文件列表首页、记录查询首页，最多 100 条。
- 标签并集/交集、来源、类型、标题和日期参数均进入缓存键。

大偏移分页直接回源，避免冷数据占满缓存。当前未实现跨实例缓存竞争合并，也不把命中统计暴露为市场指标。

## 3. 真实验收结果

- WSL Ubuntu 安装 Redis 8.0.5；包安装后由系统服务运行，`PING` 返回 `PONG`。
- 使用完整 SQLite：两次汇总结果一致，第二次真实缓存命中；新闻首页总数 900,704、每页 20 条。
- 文件变化测试确认内容版本改变，旧汇总不会被复用。
- 实际停止 Redis 系统服务后，汇总仍返回 1,556,492 条记录，缓存读写各记录一次错误并自动回源；测试后已恢复 Redis。
- “人工智能 + 半导体”新闻交集：SQLite、缓存未命中和命中均为 6,907 条。本次单次测量 SQLite 353.71ms、未命中 392.93ms、命中 6.66ms；这只是当前机器单次验证，不是正式性能报告。
- `REDIS_ENABLED=true` 启动真实 Uvicorn 后，`/api/health` 和连续两次 `/api/data/summary` 均返回正确结果。
- 后端 51 项测试通过，分支覆盖率 74.99%；前端 10 项测试与生产构建通过。

## 4. 配置与启动

Redis 默认无密码、只监听 `127.0.0.1:6379`，本阶段不启用持久化，因为缓存可重建。正式部署必须重新评估密码、TLS、内存上限和淘汰策略。

```bash
# 查看本地服务
wsl.exe -- bash -lc 'redis-cli -h 127.0.0.1 -p 6379 PING'

# 启用后端可选缓存
REDIS_ENABLED=true PYTHONPATH=".;server" PYTHONUTF8=1 \
  C:/ProgramData/miniconda3/envs/fintech/python.exe -m uvicorn app.main:app \
  --host 127.0.0.1 --port 8000
```

私有配置或环境变量可覆盖地址、数据库编号、密码、TTL 和 namespace。真实密码不得进入示例配置或 Git。

## 5. 当前限制

- 缓存只覆盖目录热点查询，不是分布式限流，也不缓存模型计算过程。
- 多实例同时写入同一键时可能有重复计算，但结果仍由同一数据库版本决定。
- SQLite 内容版本每次读取都会生成，后续需要测量并在高并发下优化。
- 在线增量发布、Docker Compose、权限和服务治理仍未完成。
