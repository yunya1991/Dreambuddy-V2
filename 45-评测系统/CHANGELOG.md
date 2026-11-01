# CHANGELOG — 45 评测系统

> 记录方式：里程碑 + 变更条目 + 提交哈希；对应 PLAN 任务编号。
> 根门禁（PLAN §2.6）：45 自身变更 = pytest 全绿 + 人工评审 + 本 CHANGELOG 更新，不调用自身评测器。

## [0.3.0] — 2026-11-01 — P2 评测器接入（进行中）

### P2-1 通用准入验证器（E3 三层）
- 新增 `evaluators/common/e3.py`：网络层（object_ref 可达、端点健康、资源可解析）、内容层（schema、category↔object_type、哈希一致）、交叉层（commit / 泛化声明一致性）
- 出分三个 hard item（`E3-network` / `E3-content` / `E3-cross`）：fatal → BLOCK，预算超时 → INCONCLUSIVE，否则 PASS
- 探针 / fetcher / resolver 可注入，默认不联网（fail-closed + 未验证告警）；L1 预算 60s
- 测试：22 个用例；evaluators 覆盖率 91%
- commit: `0a76134f1c`

### P2-2 防泄漏切分组件
- 新增 `evaluators/common/split.py`：purged_kfold（标签窗口重叠剔除 + 测试后 embargo）、walk_forward（扩展窗口 + 尾部 purge）
- `verify_no_leakage` 对生成切分返回空、对人工泄漏样例返回违规（PLAN P2-2 验收）
- 测试：22 个用例（含参数校验与精确索引断言）
- commit: `11962b90d4`

### P2-3 金融-功能与高可用
- 新增 `evaluators/finance/availability.py`：5 类故障模板（pod-kill / 网络延迟 / 交易所 API 超时 / DB 主备切换 / 磁盘写满）+ 目标占位符渲染 + 可注入执行器
- 出分 F-H2 hard item：订单 RPO=0、订单 RTO≤30s、行情 RTO≤60s；缺故障类型 / 未恢复 / 证据不全 → BLOCK
- 测试：20 个用例；evaluators 覆盖率 94%
- commit: `fbdfc62871`

### P2-4 金融-回测内核
- 新增 `evaluators/finance/backtest.py`：PSR（Bailey 公式）、DSR（期望最大 Sharpe 基准）、PBO（CSCV S=16）、`_sharpe`
- 出分 F-H6 overfit（N_trials 未登记 / PBO>0.50 → BLOCK）与 F-H7 significance（DSR<0.95、OOS<100、折数<5 → INCONCLUSIVE）
- 测试：25 个用例（含论文公式参考值 0.975602 / 0.519755 / 2.530603、PBO 极端样例）；evaluators 覆盖率 95%
- commit: `待填`

## [0.2.0] — 2026-11-01 — P1 灰度受理（只受理不拦截）

### P1-1 env_manifest 语义校验器
- 新增 `core/validators.py`：endpoints URL 语义 + 去重、可达性探针可注入、secret_refs 明文密钥识别（§15）
- 实盘（`gate.shadow=false`）硬拒，影子模式仅告警、照常受理
- commit: `0535a2075d`

### P1-2 受理 → 排队 → 执行占位
- 新增 `core/runner.py`：InProcessQueue（high/normal 双队列、去重、可撤销）；状态机 queued→running→succeeded/failed/cancelled；瞬时失败指数退避重试、硬性失败不重试；检查点取消
- 中断/持久队列适配（Celery）留待 P1-2b
- commit: `12690c5e50`

### P1-3 只受理不拦截（判定回调影子路由）
- 新增 `core/callbacks.py`：ShadowDispatcher 只记录 would-dispatch；RecordingDispatcher 实盘回调且 fail-soft；`build_dispatcher` 按 `gate.shadow` 统一路由
- Runner 默认影子分发；`create_app` 支持装配 runner（受理即入队）
- commit: `0245e389ed`

### P1-5 灰度观测指标
- 新增 `core/metrics.py`：受理量/状态/判定/分类/积压/成功率/耗时 + Runner 执行统计
- 新增 `GET /api/v1/eval/metrics`（注册于 `{eval_id}` 之前）
- commit: `78fbfea85a`

### P1-4 报告落盘与 41 索引登记
- 新增 `storage/index_publisher.py`：`artifacts/reports/<eval_id>.json` + `file://` URI；同 eval_id 内容不一致即拒（证据不可变）；41 索引钩子 fail-open
- commit: `7bf3262acd`

### P1.5 状态
- **未启动**：前置为每类 ≥30 次真实评测样本；当前无 `EVAL_PG_DSN` 部署，`eval_requests` 无真实数据（P1.5-1 阻塞）

## [0.1.0] — 2026-11-01 — P0 骨架

- P0-1 评测契约四件套（eval_request / eval_spec / eval_report / evidence + 契约测试）— `3e0db93c2c`
- P0-2 PG 八表迁移 `001_init.sql`（+ 002 eval_items kind/status）— `61319dae67`
- P0-3 Threshold Registry + `thresholds.yaml`（15 项，`TH-2026Q4@1`）— `5f92859f88`
- P0-4 受理网关：契约校验 + 类别匹配 + 幂等受理 + 影子模式默认 — `f471da8036`
- P0-5 报告归档：reporter + storage/repo 双实现 + 证据哈希链 — `8b4a219ca0`
- P0-6 API 路由 + evalctl CLI（退出码 0/2/3/4）— `cadefe1b44`
- P0-7 覆盖率达标（core/api/storage 96%，各模块 ≥86%）— `4b31cc2435`

### 基线约定
- `config/categories.yaml` 中 `gate.shadow=true` 为**硬约束默认**：转实盘前不得置为 false（认知库 VM-1793535439164）
- 测试：`cd 45-评测系统 && .venv/bin/python -m pytest tests -q`
