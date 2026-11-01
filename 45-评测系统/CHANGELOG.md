# CHANGELOG — 45 评测系统

> 记录方式：里程碑 + 变更条目 + 提交哈希；对应 PLAN 任务编号。
> 根门禁（PLAN §2.6）：45 自身变更 = pytest 全绿 + 人工评审 + 本 CHANGELOG 更新，不调用自身评测器。

## [0.5.0] — 2026-11-01 — P4 世界级加固

### P4-1 证据签名与 Merkle 根
- 新增 `storage/evidence.py`：`chain_hash`（与 reporter 既有公式一致）、`append_entry`（自动链接 prev_hash）、`verify_chain`（逐条重算 + 前向链接校验，篡改/断链/乱序检出）
- `merkle_root` 按 RFC 6962 思路：空树 `SHA256("")`、叶子 `H(0x00||hash)`、节点 `H(0x01||L||R)`、奇数叶按最大 2 的幂切分；顺序敏感
- `build_bundle` / `verify_bundle`：证据包 = 证据链 + 报告 JSON + Merkle 根 + HMAC-SHA256 签名，可离线验证（版本/链/链头/根/报告哈希/签名六重校验，fail-closed）
- 签名密钥仅由 `EVAL_EVIDENCE_KEY` 注入，签名主体由 `EVAL_EVIDENCE_SIGNER` 标注；`Reporter(signed_by=...)` 使证据链条目携带签名主体
- CLI 新增 `evalctl evidence --eval-id --out` 与 `evalctl evidence --verify <bundle> [--require-signature]`（0 通过 / 4 失败）
- 测试：26 个用例（链链路、字段篡改、断链乱序、Merkle 空/单/双/奇/顺序、包篡改四类、错密钥、缺密钥、CLI 构建与验证）；storage/evidence.py 覆盖率 96%
- 签名采用 HMAC-SHA256（§13.3 同族）；Sigstore/in-toto 与 WORM 留待 P4-2 及后续升级
- commit: `3b58782962`

### P4-2 WORM 对象存储
- 新增 `storage/object_store.py`：`LocalWormStore`（只读落盘 + 元数据 `sha256/version_id/retention_until/mode`，保留期内覆盖与删除均 `WormViolation`）、`MinioWormStore`（MinIO Object Lock，依赖缺失 fail-closed）
- 保留期策略可配：`config/object_store.yaml`（`mode` / `root` / `bucket` / `retention_days`），默认按 SPEC §15 分级（证据 365 / 报告 1095 / 审计 365 天）；环境变量 `EVAL_WORM_MODE` / `EVAL_WORM_ROOT` / `EVAL_WORM_ENDPOINT` / `EVAL_WORM_BUCKET` / `EVAL_WORM_SECURE` 覆盖
- `archive_bundle` 将证据包写入 `evidence/<eval_id>.json` 并回填 `uri/sha256/version_id/retention_until`；CLI `evalctl evidence --archive` 完成归档接线
- 安全：对象 key 拒绝绝对路径与 `..` 穿越；未知 mode / MinIO 缺依赖均报错，不静默降级
- 测试：22 个用例（读写回环、只读权限、锁内覆盖/删除拒绝、到期后版本追加、穿越拒绝、策略默认与覆盖、YAML 加载、装配失败闭合、归档与 CLI 归档）；storage/object_store.py 覆盖率 98%
- commit: `f9cd70d325`

### P4-3 gVisor 沙箱
- 新增 `config/sandbox.yaml`：`runtime: gvisor` + `strict: true`（缺 runsc 即 fail-closed），cpu=1 / mem=2g / pids=256 / timeout=1800s / network=none / 只读 rootfs / 非 root / `mount_allowlist=/tmp/eval-work`
- 新增 `core/sandbox.py`：`SandboxPolicy.load`、`validate_request`（逃逸拦截：特权容器、Docker socket、宿主根、/proc /sys /dev、host 网络、root 用户、未登记挂载、非只读挂载、缺镜像/命令）、`build_command`（runsc + 只读 + 非 root + cap-drop ALL + no-new-privileges + cpu/mem/pids 配额 + tmpfs）、`check_runtime`（gvisor/docker/none 路由）
- CLI 新增 `evalctl sandbox --check`（策略合法性 + runtime 可用性；0 通过 / 4 拒绝），支持 `--config` / `EVAL_SANDBOX_CONFIG`
- 测试：29 个用例（10 类逃逸用例、硬化参数、挂载只读、strict 缺 runsc 拒绝、非 strict 降级、docker/none/未知 runtime 路由、CLI 三态）；core/sandbox.py 覆盖率 97%
- 编译类开销 ≤20% 属云端实测门（本机无 runsc，未在本轮测量；strict 下不会静默直跑）
- commit: `PENDING`

## [0.4.0] — 2026-11-01 — P3 强制门禁

### P3-1 凭证签发与校验
- 新增 `core/gate.py`：`issue` 仅 PASS 可签发（BLOCK/INCONCLUSIVE 拒绝），`verify` 以库内报告重算绑定并校验新鲜度
- 凭证绑定 `eval_id + run_id + spec_hash + verdict + thresholds_version + expires_at`，并记录 `evaluator_id@version`（P2-9 版本锁定落地，供复算）
- 有效期取报告判定时刻 +7 天（`CREDENTIAL_TTL_DAYS`），边界闭区间；过期不可重签，必须重新评测
- 校验失败码：`unknown_eval_id` / `no_report` / `verdict_not_pass` / `binding_mismatch` / `purpose_mismatch` / `expired`（fail-closed）
- 测试：19 个用例（签发绑定、BLOCK/INCONCLUSIVE 拒绝、篡改 spec_hash/expires_at/purpose、过期边界）；core/gate.py 覆盖率 96%
- 签名与 Merkle 根留待 P4-1
- commit: `5a8af5021d`

### P3-2 部署流水线卡点
- 新增 `deploy/preflight-eval-gate.sh`：直接以 `evalctl enforce --kind deploy` 退出码判定（0 放行 / 2 拦截 / 3 INCONCLUSIVE / 4 异常），禁止解析日志
- 接入 `31-分布式计算部署/phase1/update.sh`（G4 之后、git pull 之前）与 `deploy/deploy.sh`（Phase 2.5）；45 模块缺失时 FAIL-OPEN 告警
- 影子模式（`gate.shadow=true`）只记 `SHADOW_WOULD_BLOCK` 并退出 0；转实盘后同一脚本即阻断，无需改脚本
- 实测：`EVAL_ID=demo-eval-001` 影子观测退出 0（`unknown_eval_id` 记入审计）
- commit: `4961aa8335`

### P3-3 L0 沉淀卡点
- 新增 `integrations/l0_gate.py`：`build_settle_gate(enforcer)` 适配 `L0Foundation.settle` 的 `(allowed, info)` 契约
- `L0Foundation.settle(result, context, gate=...)` 可选注入；未通过不沉淀，门禁自身异常 fail-closed（与数据源 FAIL-OPEN 区分）
- 顺带修复 `_settle_case` 引用未定义 `context` 的历史缺陷（此前案例沉淀被 try/except 静默吞掉）
- 测试：34 新增 3 个注入用例（放行 / 拦截 / 异常 fail-closed）
- commit: `f74e3c0be6`

### P3-4 27 双凭证校验
- 新增 `integrations/approvals.py`：按 JSONL 文件契约读取 27 台账（`id` / `decision` / `ts` ms），`decision ∈ {approve, approved, ok, pass, yes}` 且 24h 内有效（与 27 `_approval_ok` 对齐）；路径 `EVAL_APPROVALS_LOG`，无路径/文件缺失/坏行/读异常一律不通过（fail-closed）
- `Enforcer(require_approval=True)`：27 审批缺失、过期、查询器未装配或查询异常均拒绝，与 45 凭证互不豁免；CLI 暴露 `--approval-id` / `--require-approval`
- 测试：16 个用例；integrations/approvals.py 覆盖率 100%
- commit: `02e3d036ac`

### P3-5 审计全链路验证
- 新增 `storage/audit.py`：门禁裁决 JSONL 审计（`artifacts/audit/enforcement.jsonl`，自动补 `at`、最新在前查询、坏行跳过）
- 新增 `core/audit_trace.py`：一次汇总 `request → run → items → evidence → report → enforcements`，`cancelled` 字段反映取消/回滚，不伪造状态历史
- CLI 新增 `evalctl audit --eval-id`；`enforce` 每次裁决自动落审计
- 测试：5 + 14 + 8 用例；audit_trace 覆盖率 100%、enforcement 94%、storage/audit 89%
- commit: `02e3d036ac`

### P3 汇总
- 45 全量：518 用例全绿（2 个 PG 集成用例因未设 `EVAL_PG_DSN` 跳过）；核心覆盖率 95%

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
