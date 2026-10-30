# v0.3.3 阶段 C：ClickHouse 分析时序与双读

> 当前状态：阶段 C 已完成本地真实服务验收。WSL 2 + Ubuntu 上运行 ClickHouse 26.11.1.901，全量迁移、计数核对和两轮典型双读查询均通过。应用主读仍为 SQLite，ClickHouse 尚未承接 Web 流量。

## 1. 已实现代码

- `server/migrations/clickhouse/001_analytics.sql`：DWD/DWS/ADS 版本化表结构。
- `server/app/services/clickhouse_store.py`：文件、概览、标签和记录分页的 ClickHouse 读实现。
- `server/app/services/clickhouse_migration.py`：SQLite 分批迁移、市场结果迁移、计数核对和典型查询对照。
- `server/app/services/stage_c_migration.py`：全量影子重建与只读校验入口。
- `server/tests/test_clickhouse_storage.py`：schema、重复迁移、血缘、空数据和友好记录契约测试。

应用仍使用 SQLite。`CLICKHOUSE_ENABLED` 只用于迁移工具，不会在 Web 启动时静默切换存储。

## 2. 数据边界

| 层 | 表 | 内容 |
| --- | --- | --- |
| DWD | `dwd_source_files` | 文件目录和迁移版本 |
| DWD | `dwd_source_records` | 标准化来源记录、原始 JSON、来源路径、导入批次和事件日期 |
| DWD | `dwd_source_record_tags` | 记录级检索标签 |
| DWS | `dws_source_daily_stats`、`dws_source_fields`、`dws_source_tag_stats` | 数据概览与筛选统计 |
| DWS | `dws_market_features` | 当前状态日快照中的六类特征，不包含尚未持久化的全部历史特征日 |
| ADS | `ads_market_states` | 市场状态、模型版本、训练截止日、特征和贡献 JSON |
| ADS | `ads_alerts` | 预警、证据、阈值与规则配置版本 |

大表按事件月份分区，排序键围绕来源、记录和事件日期设计。研究文件不会各自产生一个分区。原始对象仍以 MinIO 为 ODS，ClickHouse 记录通过 `source_id`、导入批次和转换版本回溯。

## 3. 迁移策略

当前采用**影子库全量重建**：

1. 初始化数据库和版本化 schema。
2. 清空仅用于迁移的 ClickHouse 分析表，不影响 SQLite、MySQL 或 MinIO。
3. 每个来源按 1,000 条记录、5,000 条标签分批写入。
4. 写入统计、状态日特征、市场状态和预警。
5. 核对各表计数，并复用 SQLite 基线中的全局/分类概览、标签、分页和组合筛选查询。
6. 任一差异都返回退出码 1，不切换应用主读。

重复执行会重新构建，不累积重复记录。该策略不是在线增量同步，也不保证重建中途可服务；后续切换前仍需增量批次、原子发布和完整内容摘要。

## 4. 本地运行环境

已启用 WSL 2 + Ubuntu，并下载 ClickHouse 26.11.1.901 官方构建。二进制保存在被 Git 忽略的 `server/data/clickhouse/clickhouse`，运行数据位于 WSL 用户的 `~/marketlens-clickhouse`，不能放在 `/mnt/c`，否则分区重命名会遇到 DrvFS 权限错误。

启动命令：

```bash
wsl.exe -- bash -lc 'cd "$HOME/marketlens-clickhouse" && exec /mnt/c/Users/15214/Desktop/project/fintech/server/data/clickhouse/clickhouse server -- --listen_host=127.0.0.1 > /mnt/c/Users/15214/Desktop/project/fintech/server/data/clickhouse/server-native.log 2>&1'
```

服务需要持续运行，日志应重定向到文件，避免任务输出上限或默认超时终止服务。不得为了验收把数据上传到未经批准的公共服务。

真实初始化已验证并修正：先连接默认库创建目标库、空日期使用非空分区表达式、ISO 日期在写入边界转换为日期对象。写入按事件月份分组，每批最多 50 个分区、10,000 行，避免稀疏历史数据即使行数很少也跨越过多分区，同时合并同月数据减少请求数。

## 5. 验收命令

```bash
export PYTHONPATH=".;server"
export PYTHONUTF8=1
export CLICKHOUSE_ENABLED=true
# 如设置了密码，通过环境或私有配置提供，不写入 Git

# 全量重建并核对
conda run -n fintech python -m app.services.stage_c_migration

# 不重建，只核对计数与典型查询
conda run -n fintech python -m app.services.stage_c_migration --verify-only
```

默认 ClickHouse HTTP 地址为 `127.0.0.1:8123`，数据库为 `marketlens`。真实验收至少需要：1,556,492 条来源记录、全部标签与统计、3,340 个状态日及对应预警计数一致；所有典型双读查询无差异；随后再补全量内容摘要、性能测量和固定区间三通道回归。

## 6. 当前验证结果

- ClickHouse 26.11.1.901 真实全量迁移完成：1,046 个文件、1,556,492 条记录、1,143,750 条标签、20,040 条状态日特征、3,340 个状态日和 1,127 条预警。
- 两轮独立 `--verify-only` 均通过全部表计数与典型双读查询，应用主读未切换。
- 后端 48 项测试通过，分支覆盖率 74.65%；前端 10 项测试与生产构建通过。
- 全量影子重建和校验不是在线增量发布；尚未完成全量内容摘要、查询性能报告、Redis、Docker Compose 和完整三通道回归。
