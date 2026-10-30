# v0.3.3 阶段 B：MySQL 元数据与 MinIO 对象归档

> 当前状态：已在本地真实 MySQL 8.4.13 与固定源码版本 MinIO 上完成全量迁移、重复执行和只读回读校验。SQLite 仍是应用主链路；本阶段没有切换线上读取，也不代表 ClickHouse、Redis 或 Docker Compose 已完成。

## 1. 已实现边界

- `server/migrations/mysql/001_metadata.sql`：`source_files`、`import_batches`、`source_objects` 的版本化 DDL。
- `server/app/services/mysql_metadata.py`：数据库初始化、迁移版本登记、SQLite 元数据复制、文件/汇总查询、对象元数据登记与对账。
- `server/app/services/object_archive.py`：流式 SHA-256、内容寻址对象键、重复对象复用、上传后大小检查和完整回读哈希校验。
- `server/app/services/stage_b_migration.py`：可重复执行、可按来源/数量小样本运行、可只读验证的迁移入口。
- 配置新增 `mysql`、`minio` 两段，默认关闭；密码只从私有配置或环境变量读取。

原始对象键为：

```text
raw/{source_id}/{sha256}/{original_filename}
```

同一来源与内容哈希在 MySQL 中有唯一约束。对象已存在时复用，不重复上传；对象上传成功但元数据登记失败时，重新执行会复用对象并补登记。原始赛题目录不移动、不改写。

## 2. 真实验收结果

- MySQL 8.4.13 以便携目录运行，监听 `127.0.0.1:3307`，未安装 Windows 系统服务。
- 1,046 个文件元数据和 1,046 个导入批次已迁移，和 SQLite 对账无差异。
- MinIO 以 `github.com/minio/minio@RELEASE.2025-09-07T16-13-09Z` 对应的 Go pseudo-version `v0.0.0-20250907161309-07c3a429bfed` 从源码构建，监听 `127.0.0.1:9000`。
- 先归档 2 个文件，再次执行时新上传 0、复用 2，验证重复执行。
- 全量执行新上传 1,044、复用 2，对象元数据合计 1,046。
- 独立 `--verify-only` 全量执行已回读并校验全部 1,046 个对象，无哈希或大小差异。
- 后端 43 项测试通过，分支覆盖率 76.69%；前端 10 项测试与生产构建通过。

MinIO 社区项目已经归档且官方历史二进制下载不可用，因此本次使用固定提交从源码构建，不使用无法追踪的第三方二进制。该版本只用于竞赛本地验证；后续容器交付需要重新评估社区版维护、许可证和供应链风险。

## 3. 本地启动

运行二进制、数据库、对象数据和日志都在被 Git 忽略的 `server/data/` 下。以下命令在仓库根目录的 Git Bash 执行。

### MySQL

首次初始化仅限全新的本地数据目录，会创建无密码的本地 root 账号；不得用于暴露到公网的环境：

```bash
server/data/mysql/mysql-8.4.13-winx64/bin/mysqld.exe \
  --defaults-file=C:/Users/15214/Desktop/project/fintech/server/data/mysql/marketlens.ini \
  --initialize-insecure --console
```

启动：

```bash
nohup server/data/mysql/mysql-8.4.13-winx64/bin/mysqld.exe \
  --defaults-file=C:/Users/15214/Desktop/project/fintech/server/data/mysql/marketlens.ini \
  --console > server/data/mysql/server.log 2>&1 &
```

### MinIO

需要 Go 工具链时，可用固定版本源码构建：

```bash
GOPATH=C:/Users/15214/Desktop/project/fintech/server/data/go \
GOPROXY=https://goproxy.cn,direct \
GOBIN=C:/Users/15214/Desktop/project/fintech/server/data/minio-bin \
  server/data/go-toolchain/go/bin/go.exe install \
  github.com/minio/minio@RELEASE.2025-09-07T16-13-09Z
```

本地启动示例中的凭据只用于本机验证，不能作为正式部署密码：

```bash
MINIO_ROOT_USER=marketlens MINIO_ROOT_PASSWORD=marketlens-local-only \
  nohup server/data/minio-bin/minio.exe server server/data/minio-data \
  --address 127.0.0.1:9000 --console-address 127.0.0.1:9001 \
  > server/data/minio-server.log 2>&1 &
```

## 4. 迁移与校验

```bash
export PYTHONPATH=".;server"
export PYTHONUTF8=1
export MYSQL_ENABLED=true
export MINIO_ENABLED=true
export MINIO_ACCESS_KEY=marketlens
export MINIO_SECRET_KEY=marketlens-local-only

# 只迁移并核对 MySQL 元数据
conda run -n fintech python -m app.services.stage_b_migration --metadata-only

# 小样本对象归档；再次执行应复用对象
conda run -n fintech python -m app.services.stage_b_migration --limit 2

# 全量归档与回读校验
conda run -n fintech python -m app.services.stage_b_migration

# 不上传、不修改对象，只核对元数据并回读全部对象
conda run -n fintech python -m app.services.stage_b_migration --verify-only
```

私有 `server/config.json` 可保存不同配置；真实密码不能写入 `server/config.example.json`、文档、命令历史或 Git。上文示例仅适用于已经明确隔离的本地验证环境。

## 5. 当前限制与下一步

- 应用仍从 SQLite 读取目录和记录，MySQL/MinIO 是已验证的迁移副本，不能称为已完成存储切换。
- 原始文件内容已归档，但标准化行情、特征、状态和预警尚未进入 ClickHouse。
- 尚无统一健康检查、服务自动重启、Docker Compose 或权限体系。
- 下一阶段是 ClickHouse 的 DWD/DWS/ADS 时序表、批量迁移、双读对照与标签/分页一致性验证。
