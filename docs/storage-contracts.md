# 存储契约与 SQLite 迁移基线

> 当前状态：v0.3.3 阶段 A 的本地实现。这里定义的是存储边界和迁移校验工具，不代表 MySQL、ClickHouse、Redis 或 MinIO 已接入。

## 1. 边界

`server/app/services/contracts.py` 定义服务层存储协议，`market_core/` 不依赖这些协议或任何 Web/数据库框架。

- `CatalogReader`：数据概览、标签、文件和记录分页等读取。
- `CatalogWriter`：文件变化检查、分批导入和统计重建。
- `CatalogStorage`：完整目录读写与关闭。
- `SnapshotStorage`：当前市场质量、状态和预警快照的写入与关闭。当前没有启动恢复语义，不能把它描述为模型缓存。

现有 `CatalogStore` 与 `SnapshotStore` 是上述协议的 SQLite 实现。`MarketService` 可以继续依赖同一行为，后续分布式实现必须通过相同契约和真实结果对照，而不是只满足方法名。

回放会话暂不纳入上述协议：当前会话、锁、订阅者和后台任务仍在进程内，待 v0.3.4 明确定义恢复语义后再设计持久化接口，避免把内存行为误写成已经可恢复。

## 2. 一致性要求

新存储实现至少需要保持：

- 文件和记录标识稳定，重复导入不会生成重复事实。
- 原始 JSON 的内容、空值、事件日期和字段类型语义不变。
- 文件/记录计数与实际行一致，日期边界、标签并集/交集、去重总数和分页顺序一致。
- 列表顺序为事件日期倒序，再按来源 ID 和记录序号保持确定性。
- 标签仅作检索，不能因迁移变成模型情绪因子。
- 快照序列化内容可核对；时间戳等运行元数据不参与业务结果一致性判断。
- 任何计数相同但内容不同的迁移都必须失败，不能只核对总数。

## 3. 基线内容

`server/app/services/migration_baseline.py` 生成带 `baseline_version` 的 JSON 报告：

- SQLite 表和索引定义。
- 全部文件的目录元数据。
- 每个来源的实际记录数、最早/最晚事件日期和逐记录 SHA-256 链式摘要。
- 市场快照按键的内容摘要。
- 全局及分类型概览、标签、文件分页、记录分页，以及单标签、双标签并集/交集的典型查询结果。

默认报告位置为 `server/data/migration/catalog-baseline.json`，运行数据不会进入 Git。`generated_at` 只记录生成时间，不参与差异比较；摘要选项和分页大小必须一致。

记录摘要包含来源 ID、记录序号、事件日期、标题、规范化原始 JSON 和类型，因此能发现“记录数不变但内容改变”。使用 `--skip-record-digests` 可只做轻量清点，但这种报告不能用于证明内容一致。

## 4. 使用方法

在仓库根目录执行：

```bash
# 使用当前配置的数据库生成完整基线
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.migration_baseline

# 指定数据库和报告位置
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.migration_baseline \
  --database server/data/market.db \
  --output server/data/migration/catalog-baseline.json

# 迁移或回归后与既有基线比较；不一致返回退出码 1
PYTHONPATH=".;server" PYTHONUTF8=1 conda run -n fintech python -m app.services.migration_baseline \
  --compare server/data/migration/catalog-baseline.json
```

完整摘要需要顺序读取所有记录，真实库耗时会随数据量增长，这是有意的全量校验，不应放在 Web 请求或每次后端启动中执行。日常单元测试使用小型固定数据库。

## 5. 迁移使用顺序

1. 在变更前生成完整 SQLite 基线并保留报告。
2. 新实现先通过存储契约和小型数据集测试。
3. 分批迁移后用相同语义生成新实现报告，逐字段解释差异；当前比较工具面向 SQLite，后续 ClickHouse 适配器需复用相同报告结构。
4. 在双读一致前不切换主路径，不删除 SQLite 或原始文件。
5. 切换后重新运行固定日期三通道回放，分别验证市场结果；存储基线一致不能代替模型与页面验收。

当前真实基线已覆盖 1,046 个文件和 1,556,492 条逻辑记录。该数字是本次生成结果，后续原始数据若合法变化，应生成新基线并说明原因，不能为了通过校验强行维持旧总数。
