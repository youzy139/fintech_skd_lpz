# MarketLens 开发恢复摘要

## 当前基线

- 最新标签仍为 `v0.3.3`，完整 `v0.3.4` 未完成，不创建新标签。
- `origin/main` 已同步到 `1d39262`，包含已验收的 Kafka/Flink 异常治理。不要重复实现或提交该批。
- 正式网站运行于 `http://localhost:5173`，前端、readiness、认证状态均为 HTTP 200；正式身份库、原始赛题数据和运行卷未重建或删除。
- 当前依赖监控与 Redis 熔断批次已完成实现、自动化和真实故障验收，尚未获得用户页面体验确认，不得提交或推送。

## 当前批次

- `GET /api/system/dependencies` 独立探测 MySQL、ClickHouse、Redis、MinIO、Kafka、Flink，返回 `ok/disabled/unavailable`、实际耗时、探测方式与异常类型，不泄露地址、凭据或异常正文。
- 管理员顶部新增“系统监控”，展示依赖、限流/租约熔断和目录缓存熔断。接口需要管理员权限，普通账号和服务身份不可用于管理。
- 新增线程安全 `CircuitBreaker`：连续失败 3 次打开，30 秒后允许一个半开探测；成功自动闭合，失败重新打开。Compose 可用 `REDIS_CIRCUIT_FAILURES`、`REDIS_CIRCUIT_RECOVERY_SECONDS` 配置。
- 熔断覆盖目录缓存、共享限流、WebSocket 和回放计算租约。打开时缓存回源、读取采用既有限流降级；管理、登录、回放和连接操作仍失败关闭。
- 真实 DNS 消失演练使用隔离库 41,413 条真实科技帖子：前三次故障建立存在系统等待，30 秒窗口内后续读取少于 0.001 秒；写操作快速 503；恢复后自动闭合且回到 Redis 模式。正式六项依赖最终均为 `ok`。
- 最终回归：后端 143 项、前端 22 项通过，Python 分支覆盖率 76.62%，前端生产构建和 Compose 配置通过。
- 专项记录为 `docs/v0.3.4-dependencies.md`；可复现脚本为 `server/benchmarks/redis_circuit_acceptance.py`，原始报告位于忽略目录 `server/data/benchmarks/`。

## 边界与后续

- 熔断不消除达到阈值前的 DNS/连接等待，也不是 Redis 持久化、高可用或业务写入降级。监控探针不替代原业务 readiness。
- 审计保留/归档和 Caffeine/Redis 缓存职责仍未完成，不能声称本批已经覆盖。
- 当前下一顺序：用户验收并推送本批 → 审计归档与缓存职责 → 可配置预警规则、规则版本、阈值、证据链和状态热力图 → 性能、CI/E2E 与竞赛交付材料。

## 工作约束

每批须用户实际体验并明确确认后才能提交/推送。原始 PPT/PDF、教程、竞赛数据与 `server/data/` 运行文件不纳入 Git；不得输出凭据。原 `AGENTS.md` 按用户此前要求保留，其旧基线结合当前计划阅读。
