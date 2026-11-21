---
name: dream-three-tier-collab
description: '三端协同编排（本地评审中枢 / GitHub 存证 / 云端运行）：云端八维评审 D1-D8、RACI 职责速查、门禁链 G1-G7+、排查 SLA、双轨模型生命周期、模块租约与角色分离（G3.5）、技术文档双向同步与云端终审（R8）、意图路由与红线。Invoke when 评审云端、排查云端故障、判断部署窗口、模型 promote 决策、双端并行开发、领租约、判断谁开发谁测试、文档同步、文档终审、或需要明确三端职责边界时。'
version: 1.3.0
created: 2026-10-29
updated: 2026-10-30
status: active
category: collaboration
role: coordinator
tier:
- local
- github
- cloud
triggers:
- 三端
- 三端协同
- 云端评审
- 八维评审
- 评审云端
- 门禁链
- 部署窗口
- 模型生命周期
- 排查云端
- 三端职责
- 双端
- 双端协作
- 模块租约
- 租约
- 开发冲突
- 角色分离
- 文档同步
- 双向同步
- 闭环
depends_on:
- cloud-review.sh
- cloud-logs.sh
- g4-volatility-gate.py
- lease.py
- docs_sync.sh
- lease-guard.yml
- dream-code-commit-sync-workflow
- dream-code-deploy-pipeline
- dream-bugfix-workflow
- dream-acceptance-verify
- dream-skill-index-governance
provides:
- three-tier-routing
- cloud-review-checklist
- gate-chain
- model-lifecycle-boundary
- module-lease
- sod-gate
- doc-bidirectional-sync
---

# Dream Three-Tier Collab — 三端协同编排

> 上游 SPEC：`.trae/documents/SPEC-three-tier-collab-management.md`
> 定位：**编排型 SKILL，只做路由，不重复实现已有能力**。
> 一句话：**云端负责"跑"，GitHub 负责"存与证"，本地负责"审"**；本地第一职责是云端各维度评审中枢，代码开发为辅。

> **双位置存储**：
> - `.trae/skills/dream-three-tier-collab/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/dream-three-tier-collab/SKILL.md`（项目级索引发现）

---

## 零、云端八维评审清单（本地第一职责）

> 评审原则：**只读**（SSH 只读查询 + 只读 API）。任何评审动作**不得**改变云端运行态；发现问题 → 登记 P0/P1/P2 → 走门禁链修复。

| 维度 | 评审内容 | 入口 | 频率 | 产出 |
|---|---|---|---|---|
| D1 代码一致性 | 云端 HEAD == origin/main；无未提交本地改动 | `ssh dreambuddy-remote 'cd ~/dreambuddy && git rev-parse HEAD && git status --porcelain'` vs `git ls-remote origin main` | 每次部署后 + 每周 | drift 报告 |
| D2 运行健康 | 22 服务 active、13 timer 触发、端口监听 | `systemctl list-units/list-timers`、`ss -tlnp` | 每日 | 健康快照 |
| D3 日志质量 | error/warn 趋势；**静默服务识别**（日志停更即视为异常） | `bash 37-一键启动脚本/cloud-logs.sh errors` / `-f` | 每日 | 异常清单 |
| D4 数据链路 | 18-DB→19-DAL→快照→API→前端 字段契约/量级/缺失 | `data-troubleshoot` SKILL | 每周 + 前端异常时 | 链路诊断报告 |
| D5 模型质量 | walk_forward 趋势、overfit_gap 恶化、生产漂移 | `12-三屏趋势系统/ml/models/registry.json` + 交易胜率 | 每次训练后 | 模型评审意见（G7/promote 的必需输入） |
| D6 风控行为 | 实盘记录合规、trailing-stop 触发、熔断有效性 | 交易日志只读 | 每日 | 风控日报 |
| D7 安全面 | 端口暴露、凭据落盘、ufw、GitHub 权限 | 只读审计 | 每月 | 安全审计报告 |
| D8 成本/资源 | CPU/内存/磁盘水位、账单、LLM/token/API 费用 | `free -h` / `df -h` / `top`、云账单、Actions usage | 每周水位 + 每月账单 | 资源/成本月报 |

- 统一产出目录：`.trae/documents/review-reports/YYYY-MM-DD-<维度>.md`
- 汇总脚本：`bash 37-一键启动脚本/cloud-review.sh`（D2/D3/D6 一页摘要）
- 资源红线：内存 >85% 或磁盘 >80% → 登记 P1；月成本超预算基线 20% → 架构优化评审
- **D5 是 promote 的显式输入：无当次 D5 报告不 promote（12-ML 轨）**

---

## 一、三端职责速查（RACI）

`R`=执行，`A`=批准（AI 评审门禁代行，本人保留最终否决权），`C`=被咨询，`I`=被通知。

| 流程节点 | 本地 | GitHub | 云端 |
|---|---|---|---|
| 云端八维评审 | **R/A** | C | C |
| 技术方案设计/评审 | **R/A** | — | — |
| 技术文档终审（`review/approved/`） | C（只出 feedback 意见） | C（存证） | **R/A**（R8：终审权归云端） |
| 代码开发 | **R** | 托管 | — |
| 代码评审 | C | **A**（CI + drift-guard） | — |
| 架构/数据流审查 | **R/A** | — | I |
| 模型训练（主） | I | 存 Release | **R/A** |
| 模型训练（辅） | R（后期） | 存 Release | I |
| 模型注册/评估 | **A（评审指标）** | — | R |
| 模型 Promote | **A**（AI 评审 + 本人否决） | — | R |
| 部署上线 | **A（审窗口）** | A（CI 门禁） | **R** |
| 健康检查 | **A（只读审）** | — | R |
| 故障排查 | **R** | 查 CI 日志 | C |
| Postmortem | **R/A** | 归档 | I |
| 风控熔断 | **A**（审实盘行为） | 规则 PR | R |
| SKILL 治理 | **R/A** | 索引归档 | I |

---

## 二、门禁链 G1-G7（含 G3.5）

```
设计 → 开发 → PR CI → 独立测试/评审 → 部署窗口 → 部署验证 → 健康检查 → 模型评估
 G1    G2     G3      G3.5              G4        G5        G6        G7
```

| 门 | 位置 | 检查 | 失败处理 | 实现 |
|---|---|---|---|---|
| G1 设计门 | 本地 | design doc 存在且过 `dream-science-peer-review` | 无 doc 禁止开 PR（重大变更） | `.trae/documents/` |
| G2 Pre-commit | 本地 | ruff/black + secret 扫描（只查 staged） | 阻止 commit | `.pre-commit-config.yaml` + `scripts/precommit_secret_scan.py` |
| G3 PR CI | GitHub | 单测 + 集成 + 依赖扫描 + drift-guard + **lease-guard** | PR failed，禁止 merge | `.github/workflows/ci.yml`、`drift-guard.yml`、`lease-guard.yml` |
| G3.5 独立测试/评审门 | GitHub | ① 存在 test/review 租约且非开发方 ② 证据含命令/退出码/日志 ③ reviewer ≠ author | 不得 merge（与 G3 同等阻断） | `lease.py check-pr` + PR 评论 |
| G4 部署窗口 | 云端 | ATR20 分位 ≤90%、|资金费率| ≤0.001、无 P0 告警 | 拦截 exit 4，推迟到低波动窗口 | `37-一键启动脚本/g4-volatility-gate.py`（`update.sh` 步骤 1/5 调用） |
| G5 部署验证 | 云端 | systemd 启动 + 端口 + 版本号比对 | 自动回滚上一 tag | `31-分布式计算部署/phase*` |
| G6 健康检查 | 云端 | API 30s 响应、PG/Redis 连通 | 连续 3 次失败 → 回滚 + 告警 | watchdog |
| G7 模型 Eval | 云端 | 新模型 vs production（walk_forward 为主） | 不达标保持 staging | `ml/version_manager.py` `evaluate()` |

**G4 hotfix 豁免**：仅 P0 故障热修，需 `bash update.sh --g4-hotfix "原因"` 显式确认，脚本自动写 `.trae/documents/review-reports/YYYY-MM-DD-g4-hotfix.md` 并留 24h 补审；非 hotfix 一律不得豁免。

---

## 三、排查 SLA 与升级路径

| 级别 | 定义 | 时限 | 处置 |
|---|---|---|---|
| P0 | 实盘中断 / 持仓失控 | 15 分钟 | 本地+云端并行；30 分钟无结论立即回滚上一稳定 tag |
| P1 | 数据延迟 / 服务降级 | 2 小时 | 查日志 → 修复 → 走门禁链重新部署 |
| P2 | 非关键告警 / 指标偏差 | 24 小时 | 记入待办，随下次迭代 |

升级路径：云端告警 → 本地 `cloud-logs.sh errors` 汇总 → 定位 → 超时回滚 → 写 Postmortem。

---

## 四、模型生命周期：双轨（不合并）

| 轨道 | 注册表/状态 | 状态枚举 | 消费方 | 归属 |
|---|---|---|---|---|
| **A. 实盘线（V15）** | `14-V15经典马丁策略/data/incremental_trainer_state.json` | `shadow → ab_eval → live` | `incremental_trainer.py` + `hot_swap_models()` | **唯一实盘交易模型路径** |
| **B. 研究/信号线（12-ML）** | `12-三屏趋势系统/ml/models/registry.json` | `none → staging → production → rejected/archived` | `experiments/ab-trading/ml_inference.py`（第三屏 ML 信号） | 研究训练 + 信号修正 |

- 12-ML 热加载：`promote` 原子写 `models/current.json`（version + checksum）→ `ml_inference.py` 每次调用比对版本，变化即 reload；加载失败保留旧模型（FAIL-OPEN）
- 12-ML 回滚：改 `current.json` 指向 `baseline_version`，下一轮询生效
- **禁止跨轨写入**：12-ML 的 promote 不得影响 V15 实盘模型，反之亦然

---

## 五、SKILL 注册/治理

- 唯一注册表：`1-ARCHITECTURE/skills/_registry/registry.json`（schema 1.1，含 `role`/`tier`）
- 校验：`python3 1-ARCHITECTURE/skills/_registry/validate_registry.py`（E1-E6 硬错误；W1 同名/W2 path 漂移/W3 多版本软告警）
- 新增 SKILL 须证明"无现有 SKILL 可覆盖"，category `collaboration` + role `coordinator`
- 语义化版本；`status: deprecated` 保留一周期 → `archived`
- 治理入口：`dream-skill-index-governance`（季度全量审计）

---

## 六、意图路由表

| 意图 | 路由到 |
|---|---|
| 评审云端（八维） | 本 SKILL §零 → `cloud-review.sh` / `cloud-logs.sh` / 只读 systemctl / `data-troubleshoot` / registry 评审 |
| 要改代码 → 走门禁链 | `dream-code-commit-sync-workflow` → `dream-code-deploy-pipeline` |
| 要排查云端 | `cloud-logs.sh` + `dream-bugfix-workflow` |
| 要做架构审查 | `dream-arch-research-orchestrator` |
| 要训练/注册/promote 模型 | 本 SKILL §四（`ml/version_manager.py` promote/rollback CLI） |
| 要双端并行开发 / 领租约 / 判断谁开发谁测试 | 本 SKILL §八 → `lease.py status\|claim`（G3.5 角色分离） |
| 要同步技术文档（本地↔GitHub↔云端） | 本 SKILL §九 → `docs_sync.sh {pull\|push}` |
| 要文档终审 / 判断谁能签发 approved | 本 SKILL §九 + §八 R8 → **仅云端可签发**；本地只出 `review/feedback/` 意见 |
| 要验收 | `dream-acceptance-verify` |
| 要治理 SKILL | `dream-skill-index-governance` |
| 要判断能否部署 | `g4-volatility-gate.py`（G4） |

---

## 七、红线（禁止/必须/默认）

1. **禁止** 本地 + 云端对同一 OKX 账户双实盘
2. **禁止** force merge 绕过 G3
3. **禁止** 引入 ArgoCD/K8s/MLflow 等重型工具（4C8G 资源不允许）
4. **禁止** 未过 G7 的模型 promote 到 production
5. **禁止** 借评审通道直接修改云端运行态（评审只读，修复走门禁链）
6. **禁止** 在已有脚本/SKILL 中隐式跨轨写入模型注册表
7. **必须** 每次 P0 故障后 24h 内写 Postmortem
8. **必须** 变更代码后先 commit 再重启服务
9. **必须** 12-ML promote 前引用当次 D5 评审报告（无报告不 promote）
10. **默认** SKILL 治理走已有 registry，不新建第二套注册表
11. **禁止** 两端同时对同一模块持有 `dev` 租约（模块互斥，见 §八）
12. **禁止** 开发方对自己的模块出具最终测试/评审结论（G3.5 硬阻断）
13. **禁止** 绕过 PR 直推 `main`（`AGENT协作工具/ledger/**` 与租约文件等自动化 bot 白名单除外）
14. **必须** 技术文档终审（`review/approved/`）由云端签发；**禁止** 本地签发最终批准或把文档直接推进到 `approved/`（R8）

---

## 八、双端研发协作（模块租约 + 角色分离）

> 上游 SPEC：`44-三端协作架构系统/docs/tech/SPEC-dual-end-collab-governance.md`
> 一句话：**GitHub 是唯一锁与唯一真源；谁写、谁测由租约决定，开发方不得自证。**

### 8.1 模块定义

| 路径 | 模块 ID |
|---|---|
| `44-.../github/leases/**` | `lease`（申请租约的 PR 自身免租约） |
| `44-.../docs/**`、`44-.../review/**` | `docs:<相对路径>` / `review:<相对路径>` |
| `.github/**` | `root:ci` |
| 其余一级子系统 | 一级目录名 |
| 根级文件 | `root:repo` |
| `hotfix/<id>` 分支 | `hotfix:<id>`（免租约，24h 内补审） |

### 8.2 租约操作

```bash
lease="44-三端协作架构系统/shared/tools/lease.py"
python3 $lease claim   --module 18-数据获取中心 --end local --role dev --task T-001 --session trae-local-a
python3 $lease status
python3 $lease release --module 18-数据获取中心 --task T-001
```

| 规则 | 内容 |
|---|---|
| R1 | 同模块最多 1 个 active `dev` 租约 |
| R2 | `test` 须有同 task 的 dev 租约（active 或已释放，可继承） |
| R3 | 文档 `review` 不要求 dev 前置 |
| R4 | `test`/`review` 的 end 必须 ≠ dev end；同端须独立 `session` 留痕 |
| R5 | 不同模块可并行，不限端 |
| R6 | TTL 默认 24h、上限 72h，超期读取即判 expired |
| R7 | `root:ci` / `root:repo` 同时仅 1 个 active 租约 |
| R8 | **终审权归云端**：`review:approved/**` 仅 `end=cloud` 可持租约；本地申请或把文档推进到 `approved/` 的 PR 一律 exit 2 |

### 8.3 PR 约定（lease-guard 强制）

分支 `feat/<task-id>@<end>`；PR 描述必填 `Task ID / 端 / 角色 / 模块`。改动文件 → 模块 → 必须有覆盖该端+角色的 active 租约，否则阻断。

### 8.4 角色分离（G3.5）

- 开发方（持 dev 租约）**不得**出最终测试/评审结论；由另一端或独立会话执行。
- 测试证据必须含命令、退出码、关键日志行（不接受"已验证"）。
- 端身份可信度分层：L1 声明+租约审计（默认）→ L2 `github/identities.json` 邮箱白名单（存在则生效）→ L3 双 bot/GPG 签名（P1）。
- **明确边界**：共用同一 GitHub 账号时，"端"无法技术性强制验证；门禁防误撞与自证，不防蓄意伪造。

---

## 九、技术文档双向同步

```
本地起草 → PR → main → 云端 docs-sync 拉取(44) → 云端评审+终审(approved) → PR → main → 本地 ff-only 拉取 → 本地开发
云端起草 → PR → main → 本地 ff-only 拉取 → 本地评审(feedback 意见) → PR → main → 云端 docs-sync 拉取 → 云端终审(approved) → 云端开发
```

| 项 | 约定 |
|---|---|
| 真源 | `origin/main`；两端目录均为工作副本 |
| 同步判定 | `HEAD` sha == `origin/main` sha（**不设本地 ACK 状态文件**） |
| 云端拉取 | `fetch` → 校验"待同步提交的全部变更文件"均落在文档路径 → 整提交 `pull --ff-only`；含代码/配置变更即跳过交 `update.sh` + G4；**不做路径级 checkout** |
| 目录状态机 | `docs/{tech,design}`（草稿）→ `review/pending`（待评审）→ `review/feedback/YYYY-MM-DD-<slug>-review.md`（评审意见，评审方任一端可写）→ `review/approved`（**终审，仅云端**） |
| 工具 | `bash 44-三端协作架构系统/shared/tools/docs_sync.sh {status\|pull\|push}` |

---

## 十、闭环状态机

```
[draft] --评审通过--> [reviewed] --dev租约--> [in_dev] --G3.5--> [tested] --G4/G5/G6--> [deployed]
   └--驳回--> [rejected]        └--撤销--> [draft]
```

单一载体原则：**leases = 谁在做；文档 frontmatter `status:` = 生命周期；目录位置 = CI 派生校验**。不新建状态数据库，状态可由 git 历史 + leases + PR 评论重建。

---

## 十一、落地资产

| 资产 | 路径 |
|---|---|
| 租约工具 | `44-三端协作架构系统/shared/tools/lease.py` |
| 租约单测 | `44-三端协作架构系统/shared/tools/test_lease.py`（`python3 test_lease.py`） |
| 文档同步 | `44-三端协作架构系统/shared/tools/docs_sync.sh` |
| CI 门禁 | `.github/workflows/lease-guard.yml` |
| 租约数据 | `44-三端协作架构系统/github/leases/<module-slug>.json` |
| 身份白名单（可选） | `44-三端协作架构系统/github/identities.json` |
