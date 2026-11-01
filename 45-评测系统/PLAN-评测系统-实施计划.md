# PLAN — 45-评测系统实施计划

> 版本：v1.0（2026-11-01）
> 依据：[SPEC v1.0](SPEC-评测系统.md)、[调研报告](docs/调研报告-世界级评测基准-v1.0.md)
> 约束：单机 4C16G（腾讯云）+ PostgreSQL + Redis + systemd；Python 为主；不引入 k8s；不引入独立调度集群
> 原则：契约先行 → 灰度受理 → 统计校准 → 评测器接入 → 强制门禁 → 世界级加固

---

## 0. 交付物清单

| # | 交付物 | 路径 | 验收 |
|---|---|---|---|
| D1 | EvalSpec/Request/Report/Evidence JSON Schema | `contracts/schemas/` | jsonschema 校验通过，契约测试 GREEN |
| D2 | 注册表 + 阈值配置 | `core/registry.py`、`config/thresholds.yaml` | 可加载、版本化、非法配置拒绝启动 |
| D3 | 受理与归档服务 | `core/gateway.py`、`core/reporter.py`、`storage/` | 幂等受理、报告可查询、证据可验证 |
| D4 | 执行编排 | `core/dispatcher.py`、`core/runner.py` | 并行、重试、取消、超时均有用例 |
| D5 | 门禁裁决 | `core/gate.py` | PASS/BLOCK/INCONCLUSIVE 三态与 CI 规则 |
| D6 | 通用准入验证器（E3 模式） | `evaluators/common/` | 三层校验出分、证据完整 |
| D7 | 金融类评测器 | `evaluators/finance/` | 功能/高可用/合规/回测四类可执行 |
| D8 | AI 类评测器 | `evaluators/ai/` | 体验/自动/压测/人工/防泄漏可执行 |
| D9 | 工程类评测器 | `evaluators/engineering/` | 扫描/测试/基准/追溯可执行 |
| D10 | API + CLI | `api/routes.py`、`api/cli.py` | submit/get/cancel/gate 全通 |
| D11 | 沙箱与证据链 | `storage/evidence.py`、`storage/object_store.py` | 离线验证通过、沙箱隔离验证 |
| D12 | SLO 看板与告警 | `docs/运维-监控与告警.md` | 关键指标可见、告警可触发 |

---

## 1. 里程碑与任务

### P0 — 契约与骨架（门禁：契约测试 GREEN + 空跑受理）

| ID | 任务 | 产出 | 验收 | 依赖 |
|---|---|---|---|---|
| P0-1 | 冻结领域模型与字段 | `contracts/schemas/eval_spec.v1.json`、`eval_request.v1.json`、`eval_report.v1.json`、`evidence.v1.json` | 字段与 SPEC §3/§4/§12 一致；未知字段拒绝 | — |
| P0-2 | 建 PG 八表与迁移 | `storage/migrations/001_init.sql` | `psql` 建表成功；唯一键与 FK 正确 | P0-1 |
| P0-3 | Threshold Registry + 配置 | `config/thresholds.yaml`、`core/registry.py` | 版本化加载；缺字段拒绝；变更写审计 | P0-1 |
| P0-4 | 受理骨架 + 幂等 | `core/gateway.py` | 同 Idempotency-Key 重复提交返回同一 eval_id | P0-1/P0-2 |
| P0-5 | 报告归档骨架 | `core/reporter.py`、`storage/repo.py` | 空评测可生成报告并查询 | P0-2 |
| P0-6 | API 骨架 + CLI 骨架 | `api/routes.py`、`api/cli.py` | submit/get/cancel/gate 契约测试通过 | P0-4/P0-5 |
| P0-7 | 测试矩阵骨架 | `tests/` | pytest 全绿；覆盖率 ≥0.80（新增行） | 全部 |

**RED→GREEN 顺序**：先写契约测试（schema 缺字段、幂等重复、非法阈值），再实现。

### P1 — 灰度受理（门禁：全分支可受理、零拦截副作用）

| ID | 任务 | 产出 | 验收 | 依赖 |
|---|---|---|---|---|
| P1-1 | env_manifest 校验器 | `core/gateway.py` | 缺 endpoints/资源不可达即拒；用例覆盖 | P0-4 |
| P1-2 | 受理→排队→执行占位 | `core/runner.py` + Celery | 任务可入队/取消/重试；状态机正确 | P0-4 |
| P1-3 | 只受理不拦截模式 | 配置开关 `gate.shadow=true` | verdict 记录但不阻断回调 | P1-2 |
| P1-4 | 41 索引登记 | `storage/repo.py` | 报告 URI 可从 41 检索 | P0-5 |
| P1-5 | 灰度观测指标 | 指标埋点 | 受理量/成功率/耗时可见 | P1-2 |

### P1.5 — 统计校准（门禁：SLA≥90%、零误拦截、阈值定版）

| ID | 任务 | 产出 | 验收 | 依赖 |
|---|---|---|---|---|
| P1.5-1 | 真实提交数据回流 | 数据报表 | 每类 ≥30 次真实评测样本 | P1 |
| P1.5-2 | Wilson/bootstrap 校准 | 阈值修订记录 | 全部加权项给出 CI 与 min_n | P1.5-1 |
| P1.5-3 | 误拦截率评估 | 报告 | Wilson 上界 ≤1%，否则修订阈值 | P1.5-2 |
| P1.5-4 | 阈值定版与审批 | Threshold Registry 新版 | 双人审批 + 生效日期 | P1.5-3 |

### P2 — 评测器接入（门禁：各评测器出分 + 来源登记完整）

| ID | 任务 | 产出 | 验收 | 依赖 |
|---|---|---|---|---|
| P2-1 | 通用准入验证器（E3） | `evaluators/common/` | 网络/内容/交叉三层用例全通 | P0-1 |
| P2-2 | 防泄漏切分组件 | `evaluators/common/split.py` | purged+embargo 单测；给定样例可验证无泄漏 | P2-1 |
| P2-3 | 金融-功能与高可用 | `evaluators/finance/` | 5 类故障注入模板可执行；RTO/RPO 判定 | P2-2 |
| P2-4 | 金融-回测内核 | `evaluators/finance/backtest.py` | DSR/PSR/PBO/N_trials 计算正确（对照论文示例） | P2-3 |
| P2-5 | AI-自动评测与裁判 | `evaluators/ai/` + `scorers/model/` | 校准集 κ/α 达标；顺序对调生效 | P2-2 |
| P2-6 | AI-压测与人工工作流 | `evaluators/ai/` + `scorers/human/` | 压测达标率、分层抽样可执行 | P2-5 |
| P2-7 | 工程-扫描与追溯 | `evaluators/engineering/` | 秘密/漏洞/三方一致/旁路痕迹判定 | P2-1 |
| P2-8 | 工程-测试与基准 | `evaluators/engineering/` | diff coverage 自算、pycg 对照、Scorecard | P2-7 |
| P2-9 | 评测器注册与版本锁定 | Registry | 未注册评测器拒绝执行 | 全部 |

### P3 — 强制门禁（门禁：无凭证被拒 + 全链路审计）

| ID | 任务 | 产出 | 验收 | 依赖 |
|---|---|---|---|---|
| P3-1 | 凭证签发与校验 | `core/gate.py` | eval_id 绑定 run/spec/verdict/有效期 | P2-9 |
| P3-2 | 部署流水线卡点 | 部署脚本改造 | 无有效凭证拒绝部署；过期拒绝 | P3-1 |
| P3-3 | L0 沉淀卡点 | L0 流程改造 | 无凭证拒绝沉淀 | P3-1 |
| P3-4 | 27 双凭证校验 | 对接接口 | 27 审批缺失或 45 凭证缺失均拒绝 | P3-2 |
| P3-5 | 审计全链路验证 | 审计查询 | 申请→执行→判定→回滚全可查 | P3-4 |

### P4 — 世界级加固（门禁：离线验证 + 隔离验证 + SLO 达标）

| ID | 任务 | 产出 | 验收 | 依赖 |
|---|---|---|---|---|
| P4-1 | 证据签名与 Merkle 根 | `storage/evidence.py` | 离线验证脚本通过；篡改可检出 | P3-1 |
| P4-2 | WORM 对象存储 | `storage/object_store.py` | 对象锁生效；保留期策略可配 | P4-1 |
| P4-3 | gVisor 沙箱 | 运行配置 | 逃逸用例被拦；编译类开销 ≤20% | P2-7 |
| P4-4 | 人工评测工作流 | `scorers/human/` | 抽样/双标/α/仲裁全流程可跑 | P2-6 |
| P4-5 | SLO 看板与告警 | 监控配置 | 9 项 KPI 可见；积压/达标告警可触发 | P1-5 |
| P4-6 | 季度 baseline 回归 | 定时任务 | golden set 回归报告自动生成 | P4-5 |

---

## 2. TDD 与质量约定

1. **RED**：先写失败测试，断言真实业务语义（不是“函数存在”）
2. **GREEN**：最小实现；禁止顺手重构无关代码
3. **REFACTOR**：全量测试不退步；新增行覆盖率 ≥0.80
4. **契约测试**：schema 校验、幂等、取消、超时、三态判定必须有独立用例
5. **数值测试**：DSR/PSR/PBO/Wilson/α 用论文或手算样例做基准，禁止只测“返回 float”
6. **根门禁**：45 自身变更 = pytest 全绿 + 人工评审 + CHANGELOG（不调用自身评测器）
7. **提交纪律**：完成一个任务即 commit；重启服务前先 commit（遵循既有 safe-service-restart 约束）

---

## 3. 验收门（Definition of Done）

每个任务完成必须同时满足：

- [ ] 代码 + 测试入库，CI 全绿
- [ ] 新增行覆盖率 ≥0.80
- [ ] 文档更新（SPEC/契约/README 对应章节）
- [ ] 证据字段完整（该任务涉及的报告/日志）
- [ ] 无旁路痕迹（无 `|| true`、无 `--exit-code 0`、无未登记 skip）
- [ ] 回滚路径明确（配置开关/迁移回退）

阶段门：

- P0：空跑受理可演示
- P1：真实分支提交可受理，报告可查
- P1.5：阈值定版且有统计依据
- P2：四类评测器至少各 1 个真实对象跑通
- P3：无凭证部署被真实拒绝
- P4：证据离线验证与沙箱隔离演练通过

---

## 4. 依赖与并行

```
P0-1 ─┬─ P0-2 ── P0-4 ── P0-5 ── P0-6
      ├─ P0-3 ── P0-4
      └─ P0-7

P1-1/P1-2 依赖 P0-4；P1-3 依赖 P1-2；P1-4 依赖 P0-5

P2-1 起可并行：P2-2→P2-3→P2-4（金融）、P2-5→P2-6（AI）、P2-7→P2-8（工程）
P2-9 依赖全部评测器

P3 依赖 P2-9；P4-1 依赖 P3-1；P4-3 依赖 P2-7
```

**可并行分工**：金融链路、AI 链路、工程链路三组独立；P0/P1 串行。

---

## 5. 风险与缓解

| 风险 | 触发信号 | 缓解 |
|---|---|---|
| 契约返工 | P2 发现字段不够 | P0 预留 `extensions` 字段；版本化升级而非改字段 |
| 阈值失准 | 灰度误拦截 >1% | P1.5 全部 CI 校准；只上调放宽需双人审批 |
| 沙箱性能不达标 | 编译类评测超时 | 先测 gVisor 开销；超 20% 改为“沙箱 + 白名单直跑” |
| 回测口径冲突 | 双引擎偏差 >10% | 报告强制说明；冲突样本进入人工裁决清单 |
| 人工评测排期不足 | 样本积压 | 分层抽样 + 双标重叠；必要时缩层不缩 n |
| 单机资源不足 | 队列积压 >10 | high/normal 双队列；评测项并行上限可配 |
| 云端未纳入 git | 目录 untracked | P0 前完成本地纳管与云端同步策略确认 |

---

## 6. 与云端协同

- 当前 `45-评测系统/` 在云端为 **untracked**，本地已纳管 SPEC/PLAN/调研报告
- 建议：本地完成 P0 契约后统一 commit；云端仅拉取，不在云端手改（避免双写分叉）
- 部署走既有 `dream-code-deploy-pipeline`（本地 commit → GitHub CI → 云端 update.sh）
- 同步前需用户确认；本计划不自动推送云端

---

## 7. 决策状态（与 SPEC §20 一致）

| 决策 | 状态 | 落地任务 |
|---|---|---|
| D-01 阈值校准机制（P1.5 Wilson 复核，调松需双人审批） | 已冻结 | P1.5-2/P1.5-3/P1.5-4 |
| D-02 双引擎复算协议（23 内核主判，偏差 10%/20% 分档） | 已冻结 | P2-4 |
| D-03 人工评测（内部双标、每层 100、最多 2 层） | 已冻结 | P2-6/P4-4 |
| D-04 DSR 主判 / Sharpe 参考 | 已冻结 | P2-4/P3-1 |

> 阈值具体数值仍按 P1.5 滚动复核，不作为 P0–P2 的阻塞项。
</content>
