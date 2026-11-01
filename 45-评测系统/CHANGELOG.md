# CHANGELOG — 45 评测系统

> 记录方式：里程碑 + 变更条目 + 提交哈希；对应 PLAN 任务编号。
> 根门禁（PLAN §2.6）：45 自身变更 = pytest 全绿 + 人工评审 + 本 CHANGELOG 更新，不调用自身评测器。

## [0.4.0] — 2026-11-01 — P3 强制门禁

### P3-1 凭证签发与校验
- 新增 `core/gate.py`：`issue` 仅 PASS 可签发（BLOCK/INCONCLUSIVE 拒绝），`verify` 以库内报告重算绑定并校验新鲜度
- 凭证绑定 `eval_id + run_id + spec_hash + verdict + thresholds_version + expires_at`，并记录 `evaluator_id@version`（P2-9 版本锁定落地，供复算）
- 有效期取报告判定时刻 +7 天（`CREDENTIAL_TTL_DAYS`），边界闭区间；过期不可重签，必须重新评测
- 校验失败码：`unknown_eval_id` / `no_report` / `verdict_not_pass` / `binding_mismatch` / `purpose_mismatch` / `expired`（fail-closed）
- 测试：19 个用例（签发绑定、BLOCK/INCONCLUSIVE 拒绝、篡改 spec_hash/expires_at/purpose、过期边界）；core/gate.py 覆盖率 96%
- 签名与 Merkle 根留待 P4-1
- commit: `待填`

## [0.3.0] — 2026-11-01 — P2 评测器接入（P2-1~P2-9 已交付）

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
- commit: `280fef9010`

### P2-5 AI-自动评测与裁判
- 新增 `scorers/model/calibration.py`：Cohen's κ、Krippendorff's α（nominal）
- 新增 `scorers/model/position_swap.py`：顺序对调两遍评审、映射回 A/B、flip 留痕
- 新增 `evaluators/ai/judge.py`：A-H4 判定（样本≥200、κ≥0.60、α≥0.67，否则 INCONCLUSIVE）
- 测试：16 个用例（含 κ=0.666667 / α=0.657143 参考值、首位偏好检出）；evaluators+scorers 覆盖率 95%
- commit: `7078853d88`

### P2-6 AI-压测与人工工作流
- 新增 `evaluators/ai/stress.py`：A-W2 达标率（p95/吞吐/错误率三阈值 + 样本≥30 + 目标 0.80）
- 新增 `scorers/human/sampling.py`：分层抽样（每层至少 1、比例分配、余数给最大小数层、固定 seed 可复算）
- 测试：13 个用例；evaluators+scorers 覆盖率 95%
- commit: `0ce8af2afb`

### P2-7 工程-扫描与追溯
- 新增 `evaluators/engineering/scan.py`：E-H1 秘密泄露、E-H2 漏洞（CRITICAL / HIGH 有修复版本）、E-H3 三方一致（build digest ↔ SBOM + attestation）、E-H5 旁路痕迹（8 条模式）
- 四个 hard item 各自出分；命中即 BLOCK
- 测试：14 个用例（含 6 类旁路痕迹参数化）；engineering 覆盖率 100%
- commit: `9a396ef1db`

### P2-8 工程-测试与基准
- 新增 `evaluators/engineering/tests.py`：E-H4 diff coverage 按 base_sha 自算（缺 base_sha/job 签名即 BLOCK，无新增行 INCONCLUSIVE）、E-W5 pycg F1、E-W6 Scorecard
- 阈值：diff coverage ≥0.80、pycg F1 ≥0.70、Scorecard ≥7.0
- 测试：16 个用例；engineering 覆盖率 100%
- commit: `e6256d31c4`

### P2-9 评测器注册与版本锁定
- 新增 `evaluators/registry.py`：`(name, version)` 唯一注册、重复注册拒绝；`resolve` 未注册/错版本抛 `EvaluatorNotFoundError`（默认拒绝执行）；`lock` 钉住当前版本写入报告；版本格式 `MAJOR.MINOR.PATCH`
- `load_defaults()` 注册 P2 全部 7 个内置评测器（`e3`、`finance-availability`、`finance-backtest-stats`、`ai-judge-calibration`、`ai-stress`、`engineering-scan`、`engineering-tests`，均为 `1.0.0`）
- 测试：13 个用例（含非法版本参数化、重复注册、锁定后新增版本不影响已锁定引用）
- commit: `71a84f8624`

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
