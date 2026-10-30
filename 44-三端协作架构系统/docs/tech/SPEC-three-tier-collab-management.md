# SPEC — 三端协同管理体系（云端主训 / GitHub 中枢 / 本地评审辅训）

> 日期：2026-10-29
> 来源：千问一轮评估（8.5/10）+ 现状资产盘点修正 + 本地整合
> 上游：[千问调研报告](three-tier-collab-qwen-research.md)
> 阶段：SPEC（待评审）
> 目标读者：项目 owner（单人维护）

---

## 零、本文档的立场修正（最重要）

千问报告的 6 项 gap 已逐项对齐现状。**核心结论：本 SPEC 以"演进现有资产"为主，"新建"仅 2 项。**

| # | 千问建议 | 现状资产 | 修正结论 |
|---|---|---|---|
| 1 | 新建 `skills/registry.yaml` | `1-ARCHITECTURE/skills/_registry/registry.json`（schema 1.0，**185 个 SKILL**，含 depends_on/provides/cognitive_links/content_hash） | **禁止新建**。扩展 schema：新增 `role`（researcher/trader/risk/operator/coordinator）+ `category: collaboration` |
| 2 | 部署 MLflow | `12-三屏趋势系统/ml/models/registry.json`（**已含 versions/current/baseline + train/test/walk_forward ROC AUC + overfit_gap**） | **禁止引入 MLflow**（4C16G 无余量）。扩展现有注册表新增 `state` 字段实现状态机 |
| 3 | G4 非交易时段禁部署 | 加密货币 7×24 无"非交易时段" | 改用**波动率分位门禁**：ATR 20 日分位 >90% 或资金费率异常 → 禁部署（推迟至下个窗口） |
| 4 | 模型热加载（MLflow tag 监听） | v15/yijing/continual-training 均为轮询架构，无 tag 监听 | 降级为**版本号文件轮询**：`models/current.json` 版本变更 → 服务下一次轮询周期自动 reload（延迟 ≤ 轮询周期，秒级） |
| 5 | 自我 RACI（本人即 A 批准者） | 已有 `dream-science-peer-review`（Devil's Advocate）、`dream-acceptance-verify`（验收门禁） | A 角色**由 AI 评审 SKILL 承担**，本人保留最终否决权，解决"自我批准"失效问题 |
| 6 | 新建风控独立通道 | 已有 `trailing-stop-runner(--real)`、风控 timer、`alpha_decay_gate`、`actr_activation` | **禁止新建**。映射已有资产，仅在门禁链中显式登记为"风控独立线" |
| 7 | 本地=开发+辅训 | **用户修正（2026-10-29）：本地第一职责是云端各维度评审**，开发为辅 | RACI/SKILL/P0 全部按"评审中枢"重排（见 §一、§一之五、§七） |

**已有 CI 资产**（不需重建）：`.github/workflows/ci.yml`（lint+test）、`drift-guard.yml`（漂移守卫，PR 三类 change_class + 4h 定时）、`agent-*-guard.yml`（协作门禁）。

---

## 一、三端职责矩阵（流程级 RACI）

角色定义沿用千问"一人四帽"：`R`=执行、`A`=批准（AI 评审门禁代行）、`C`=被咨询、`I`=被通知。

> **定位（用户确认 2026-10-29）**：**本地 = 云端评审中枢（第一职责）+ 代码开发（第二职责）+ 辅助训练（后期）**。
> 三端关系一句话：**云端负责"跑"，GitHub 负责"存与证"，本地负责"审"**——本地对云端的代码、运行、日志、数据、模型、风控、安全七个维度行使评审权（详见 §一之五）。

| # | 流程节点 | 本地(macOS) | GitHub | 云端(腾讯云) | 现状映射 |
|---|---|---|---|---|---|
| 1 | **云端八维评审** | **R/A** | C | C（被审对象） | 本 SPEC §一之五（核心） |
| 2 | 技术方案设计/评审 | **R/A** | — | — | `.trae/documents/` design doc |
| 3 | 代码开发 | **R** | 托管 | — | feature 分支 |
| 4 | 代码评审 | C | **A**（CI+drift-guard） | — | `ci.yml` + `drift-guard.yml` |
| 5 | 架构/数据流审查 | **R/A** | — | I | 本 SPEC 所属流程 |
| 6 | 模型训练（主） | I | 存储 Release | **R/A** | `dreambuddy-continual-training.timer`(30min) |
| 7 | 模型训练（辅） | R（后期） | 存储 Release | I | 本地 oneshot |
| 8 | 模型注册/评估 | **A（评审指标）** | — | R | `ml/models/registry.json` + eval |
| 9 | 模型 Promote | **A**（AI 评审+本人否决） | — | R | 人工调用 promote 脚本 |
| 10 | 部署上线 | **A（审部署窗口）** | A（CI 门禁） | **R** | `31-分布式计算部署/phase*/` |
| 11 | 健康检查 | **A（只读审）** | — | R | systemd watchdog |
| 12 | 故障排查 | **R** | 查 CI 日志 | C | `37-一键启动脚本/cloud-logs.sh` |
| 13 | Postmortem | **R/A** | 归档 | I | 新增模板 |
| 14 | 风控熔断 | **A（审实盘行为）** | 规则 PR | R | `trailing-stop-runner` + 风控 timer |
| 15 | SKILL 治理 | **R/A** | 索引归档 | I | `dream-skill-index-governance` |

### 排查 SLA 与升级路径

| 级别 | 定义 | 响应时限 | 处置 |
|---|---|---|---|
| P0 | 实盘交易中断 / 持仓失控 | 15 分钟 | 本地+云端并行排查；无法定位立即**回滚上一稳定 tag** |
| P1 | 数据延迟 / 服务降级 | 2 小时 | 本地查日志 → 修复 → 走门禁链重新部署 |
| P2 | 非关键告警 / 指标偏差 | 24 小时 | 记入待办，随下次迭代处理 |

**升级路径**：云端告警 → 本地收到 → `cloud-logs.sh errors` 汇总 → 定位 → 若 30 分钟无结论 → 回滚 → 写 Postmortem。

### 一之五、云端八维评审体系（本地第一职责的操作化）

> 评审原则：**只读为主**（SSH 只读查询 + 只读 API），**任何评审动作不得改变云端运行态**；发现问题 → 登记问题清单（P0/P1/P2）→ 走门禁链修复，**禁止评审通道直接改云端**。

| 维度 | 评审内容 | 工具/入口 | 频率 | 产出 |
|---|---|---|---|---|
| **D1 代码一致性** | 云端部署 commit 是否 == origin/main；有无未 commit 的云端本地改动 | `ssh dreambuddy-remote 'cd ~/dreambuddy && git rev-parse HEAD && git status --porcelain'` vs `git ls-remote origin main`；CI 侧 drift-guard | 每次部署后 + 每周 | drift 报告 |
| **D2 运行健康** | 22 服务 active 状态、13 timer 触发记录、端口监听完整性 | `systemctl list-units/list-timers`、`ss -tlnp`（只读） | 每日 | 健康快照 |
| **D3 日志质量** | 关键服务 error/warn 趋势；**静默服务识别**（须读 unit 的 `StandardOutput` 指定文件，`journalctl` 无应用日志 ≠ 静默；例：yijing-polling-trader → `/home/luke/logs/yijing/trader.log`） | `37-一键启动脚本/cloud-logs.sh errors` / `-f` | 每日 | 异常清单 |
| **D4 数据链路** | 18-DB→19-DAL→快照→API→前端 字段契约、量级、缺失 | `data-troubleshoot` SKILL | 每周 + 前端异常时 | 链路诊断报告 |
| **D5 模型质量** | walk_forward 指标趋势、overfit_gap 恶化、生产漂移 | `ml/models/registry.json` 评审 + 交易胜率 | 每次训练后 | 模型评审意见（喂 G7，有效期 24h） |
| **D6 风控行为** | 实盘交易记录合规性、trailing-stop 触发、熔断有效性 | 交易日志只读评审 | 每日 | 风控日报 |
| **D7 安全面** | 端口暴露面、凭据落盘位置、ufw 规则、GitHub 权限 | 只读审计命令 | 每月 | 安全审计报告 |
| **D8 成本/资源总量** | 云端 CPU/内存/磁盘水位（4C16G 是否触顶）、腾讯云账单、LLM token 与外部数据 API 费用、GitHub Actions 用量、未来按需 GPU 租用预算 | `free -h` / `df -h` / `top`（只读）、云账单、GitHub Actions usage | 每周（水位）+ 每月（账单） | 资源/成本月报 |

**评审节奏**：D2/D3/D6 每日（可脚本化汇总成一页）；D1/D5 事件驱动；D4/D8水位 每周；D7/D8账单 每月。
**评审产出统一入口**：`.trae/documents/review-reports/YYYY-MM-DD-<维度>.md`，问题分级后进门禁链。其中 **D5 评审意见是 §4.2 promote 决策的显式输入**——执行 promote 脚本前必须引用当次 D5 评审报告路径，无报告不 promote。**报告有效期**：promote 时刻距报告生成 ≤24 小时，且报告时间必须晚于该版本的 `eval_gate.evaluated_at`；超期或 eval 重跑后须重新出报告（过期报告一律视为"无报告"）。
**资源红线**：云端内存水位 >85% 或磁盘 >80% 即登记 P1 问题；月度总成本超预算基线 20% 即触发架构优化评审。**预算基线定义**：默认取近 3 个月滚动平均账单（含云服务器 + LLM token + 外部数据 API + GitHub Actions 超额），首次 D8 月报时由本人确认并落盘 `.trae/documents/review-reports/budget-baseline.md`，此后每季度复核一次。

### 一之六、评审意见闭环（2026-10-30 云端评审）

云端产出 `44-三端协作架构系统/review/feedback/2026-10-30-doc-review.md`，结论「有条件通过」，必改 4 项 / 建议 3 项，处置如下：

| 编号 | 评审意见 | 处置 | 状态 |
|---|---|---|---|
| M1 | D5 报告需定义时效，防止过期报告绕过"无报告不 promote" | §一之五 明确有效期 24h 且须晚于 `eval_gate.evaluated_at` | ✅ 已对齐 |
| M2 | G4 阈值需注明数据来源、计算周期与评审归属 | §二 增补「G4 参数来源与周期」，阈值变更归 D6 | ✅ 已对齐 |
| M3 | `budget-baseline.md` 未落盘，D8 月报前必须完成 | 纳入 P0-0 验收标准 | ✅ 已对齐 |
| M4 | SKILL 引用的 cloud-review.sh / g4-volatility-gate.py / precommit_secret_scan.py 当时不存在 | 三者均已实现并入库（提交 `568c01582c`/`db3cbcf1d2`） | ✅ 已关闭 |
| S1 | yijing-polling-trader 日志停留 2026-10-17 悬案 | **误判已关闭**：unit 的 StandardOutput 重定向到 `/home/luke/logs/yijing/trader.log`，该文件当日 00:26 仍在写入（轮询 #1475，69MB）；进程 CPU 50.7%、运行 12 天。D3 判定方法已修正为"读 StandardOutput 文件" | ✅ 已关闭 |
| S2 | hotfix「本人显式确认」缺留痕渠道 | §二 固定为 `--g4-hotfix "原因"` + `hotfix-log.jsonl` | ✅ 已对齐 |
| S3 | D1 评审命令依赖 SSH 别名 | SKILL 增补前置检查（`ssh dreambuddy-remote true`） | ✅ 已对齐 |

### 一之七、风控独立线（P1-4，登记已有资产，不新建）

风控线**独立于**策略信号线，只由风控资产驱动；任何策略、模型、SKILL 一律不得关闭或放宽。

| 资产 | 位置 | 触发 | 动作 |
|---|---|---|---|
| `trailing-stop-runner --real` | 云端 systemd | 持仓跟踪止损触发 | 平仓/减仓 |
| 组合风险熔断（`--enable-portfolio-risk-fuses`、仓位上限） | 云端交易进程 | 组合风险越界 | 拒绝新开仓 + 告警 |
| `alpha_decay_gate` | 信号层 | alpha 衰减超阈 | 降权/停用策略 |
| `actr_activation` | 执行层 | 激活度异常 | 降档执行 |
| G4 部署窗口门（阈值变更归属本线） | 部署前 | 波动率分位/资金费率异常 | 禁止部署 |

**硬约束**：①风控判定优先于策略信号，冲突以风控为准；②**禁止**为提升收益关闭/放宽任何风控开关；③风控参数变更**必须**经 D6 评审并留报告；④风控线由 `cloud-review.sh` 的 D6 段每日汇总，异常登记 P0/P1。

---

## 二、协作流水线（G1-G7 门禁链）

```
本地设计 → 本地开发 → GitHub PR → CI门禁 → 云端部署 → 健康检查 → 模型评估
   G1        G2/G3      G4        G5        G6        G7
```

| 门 | 名称 | 执行位置 | 检查内容 | 失败处理 | 现状 |
|---|---|---|---|---|---|
| G1 | 设计门 | 本地 | design doc 存在且经 `dream-science-peer-review` 评审 | 无 doc → 禁止开 PR（重大变更） | 🆕 |
| G2 | Pre-commit | 本地 | lint、secret 扫描、commit message | 阻止 commit | 🆕 复用 `ci.yml` 的 ruff/black |
| G3 | PR CI | GitHub | 单测+集成+依赖扫描+**drift-guard** | PR 标记 failed，禁止 merge | ✅ 已有 |
| G4 | 部署窗口门 | GitHub/云端 | ATR20 日线分位 ≤90%、\|资金费率\| ≤0.001、无 P0 告警、云端健康 | 不满足 → 推迟至下个部署窗口（exit 4） | 🆕 `g4-volatility-gate.py` |
| G5 | 部署验证 | 云端 | systemd 启动 + 端口监听 + 版本号比对 | 失败 → **自动回滚上一 tag** | ✅ `phase*` 脚本 |
| G6 | 健康检查 | 云端 | API 30s 响应、PG/Redis 连通 | 连续 3 次失败 → 回滚 + 告警 | 🆕 watchdog |
| G7 | 模型 Eval 门 | 云端 | 新模型 vs Production 指标对比（walk_forward 为主） | 不达标 → 保持 staging | 🆕 |

**原则**：G5/G6 自动回滚（无需人工）；G3 失败必须本地修，**禁止 force merge**；G4 是 7×24 场景下替代"非交易时段"的唯一有效门禁。
**G4 参数来源与周期**：ATR20 取 18-DB 日线（1D）最近 21 根 K 线算 ATR(20)，分位窗口 90 日、日频更新；资金费率取交易所 funding rate 当期值（8h 结算）。阈值变更**必须**经 D6 风控行为评审并留报告，不得由部署脚本自行调整。
**G4 紧急豁免**：P0 故障的 hotfix（hotfix 分支 + 本人显式确认）可豁免 G4 直接部署；确认渠道固定为 `update.sh --g4-hotfix "<原因>"`（原因文本必填），脚本自动写 `.trae/documents/review-reports/hotfix-log.jsonl` 并生成 24h 补审记录；无参数/口头确认一律不视为豁免，非 hotfix 变更不得豁免。

---

## 三、SKILL 治理体系（扩展，非新建）

### 3.1 存量资产

`1-ARCHITECTURE/skills/_registry/registry.json`：
- `schema_version: 1.0`，`total_count: 185`
- 每项含 `name / description / version / path / location_role / status / category / triggers / depends_on / provides / cognitive_links / content_hash`
- 配套 `dep-graph.json`（依赖图）、`pending_sync_queue.json`（同步队列）
- 治理 SKILL 已存在：`dream-skill-index-governance`（注册表/版本/生命周期/冲突/漂移）

### 3.2 扩展方案（schema 1.1）

新增两个字段，不改现有结构：

```json
{
  "name": "dream-three-tier-collab",
  "role": "coordinator",            // 新增：researcher|trader|risk|operator|coordinator
  "category": "collaboration",      // 新增枚举值
  "tier": ["local", "github", "cloud"]  // 新增：该 SKILL 在三端的生效位置
}
```

### 3.3 治理规则（复用现有机制）

| 规则 | 实现 |
|---|---|
| 注册 | 新 SKILL 提交 PR → CI 校验元数据完整性 → merge 后 `auto_sync_dispatcher` 自动入表（已有） |
| 版本 | 语义化版本；breaking change 升 MAJOR（已有 version 字段） |
| 依赖 | `dep-graph.json` 检测循环依赖（已有） |
| 冲突 | 同 `category` + 同 `role` 下互斥 SKILL 不得同时 active（新增校验脚本） |
| 废弃 | `status: deprecated` 保留 1 个版本周期 → `archived`（已有 status 字段） |
| 审计 | 每季度 `dream-skill-index-governance` 跑一次全量审计（已知机制） |

---

## 四、模型生命周期（云端主训 + 本地辅训）

### 4.1 状态机（扩展现有 registry.json）

```
        ┌────────────────────────────────┐
        ▼                                │
   [none] ──eval ok──> [staging] ──promote──> [production] ──> [archived]
     │                     │                       │
     └──eval fail──> [rejected]              [drift detected]
                          │                       │
                          └──> [archived]   回滚上一 production
```

现有 `12-三屏趋势系统/ml/models/registry.json` 结构：
```json
{"versions":[{"version":"v1","created_at":"...","performance":{"train_roc_auc":0.9994,"test_roc_auc":0.6624,"walk_forward_roc_auc":0.7703,"overfit_gap_accuracy":0.2917,"num_features":25}}],
 "current_version":"v1","baseline_version":"v1","next_version":2}
```

**扩展为**（向后兼容）：
```json
{
  "versions": [{ "version": "v2", "state": "staging", "promoted_at": null,
                 "performance": {...}, "eval_gate": {"passed": true, "vs_production": "+0.03 walk_forward"} }],
  "current_version": "v1",        // = production
  "baseline_version": "v1",
  "next_version": 3
}
```

### 4.2 双路径

| 路径 | 流程 |
|---|---|
| **云端主训** | timer(30min) 训练 → 写 registry `state=none` → 自动 eval（vs production）→ 达标 `staging` / 不达标 `rejected` → 本地确认（AI 评审）→ `promote` 脚本 → `state=production` + 旧版 `archived` → 服务轮询 reload |
| **本地辅训** | 本地训练 → 本地 eval → 达标上传 GitHub Release（带指标摘要）→ 云端 CI 监听 Release 下载 → 注册 `state=none` → 后续同上 |

### 4.3 热加载（修正：不用 MLflow tag 监听）

现有服务是轮询架构，用**版本文件轮询**：
1. promote 脚本原子写 `models/current.json`（含 `version` + `checksum`）
2. 服务在每个轮询周期读 `current.json`，版本号变化 → `mlflow.pyfunc` 不可用，改为直接 `pickle/joblib load` 新 artifact
3. 加载失败 → 保留旧模型 + 告警（FAIL-OPEN）

延迟 = 服务轮询周期（v15=5min / polling=300s），满足"秒级~分钟级"，无需重启。

### 4.4 回滚

- **模型回滚**：改 `current.json` 指向 `baseline_version`（秒级，下一轮询生效）
- **代码+模型全回滚**：`git revert` 到上一 tag → 重跑 `31-分布式计算部署/phase*` 脚本

### 4.5 双轨登记（实盘线与研究线的边界，2026-10-29 对齐现状）

当前仓库存在两条并行的模型生命周期，**不合并、不新建第二套注册表**，各自演进并在此显式登记归属：

| 轨道 | 注册表 / 状态文件 | 状态枚举 | 模型目录 | 消费方 | 职责 |
|---|---|---|---|---|---|
| **A. 实盘线（V15）** | `14-V15经典马丁策略/data/incremental_trainer_state.json` | `shadow → ab_eval → live` | `14-V15经典马丁策略/data/phase_d_models/` | `incremental_trainer.py` + `hot_swap_models()` + V15 systemd timer | **唯一实盘交易模型路径**；状态机、AB 评估、热切换内聚在 V15 |
| **B. 研究/信号线（12-ML）** | `12-三屏趋势系统/ml/models/registry.json` | `none → staging → production → rejected/archived`（本 SPEC P0-2 扩展） | `12-三屏趋势系统/ml/models/{versions,current,baseline}/` | `experiments/ab-trading/ml_inference.py`（三屏第三屏 ML 信号） | 研究训练 + 信号修正；本 SPEC §4.1-4.4 全流程仅作用于本轨 |

**状态映射**（用于评审与文档口径统一，不做代码级转换）：

| 12-ML | V15 实盘 | 含义 |
|---|---|---|
| `none` | `shadow` | 已训练未评估，不参与决策 |
| `staging` | `ab_eval` | eval 通过，等待上线决策 |
| `production` | `live` | 当前生效 |
| `rejected` / `archived` | 无对应（V15 保留历史模型目录） | 淘汰 |

**边界约束（硬约束）**：
- **禁止**让 12-ML 的 `promote` 影响 V15 实盘模型；反之 V15 的 `live` 也不得写入 12-ML registry。
- 实盘模型上线审批按 **V15 自身 AB 评估 + 本地 D5 评审意见**，不引用本 SPEC 的 `evaluate()` 门禁。
- 12-ML 侧 `promote` 前必须引用当次 D5 评审报告（§一之五），无报告不 promote。
- 未来若要统一双轨，须单独立项评审，**不得**在已有 SKILL/脚本中隐式跨轨写入。

---

## 五、风险与反模式（对齐现状修正）

| 风险 | 说明 | 处置 |
|---|---|---|
| 云端单点 | 4C16G 单机 22 服务 + DB | PG/Redis/MinIO 快照异地备份（`dal-backup.timer` 已有 04:00） |
| SKILL 膨胀 | 185 个已相当可观 | 季度审计 + 冲突检测；新增 SKILL 须证明"无现有 SKILL 可覆盖" |
| 模型漂移无感知 | 缺生产监控 | **禁止**叠加重型 Prometheus；复用现有 `overfit_gap` + 交易胜率指标，异常写告警 |
| GitHub 单点 | CI + 模型分发 | 模型 artifact 同步备份到云端 MinIO |
| 无灾备演练 | 回滚流程未验证 | 每季度一次"模拟故障→回滚"演练，记录 RTO |
| 过度工程化 | ArgoCD/K8s/MLflow 对单人是负担 | **禁止**引入；最低可行实现 |

---

## 六、P0/P1/P2 落地计划

### P0（立即，必须先做）

| # | 任务 | 验收标准 | 依赖 | 风险 |
|---|---|---|---|---|
| P0-0 | **云端评审日检脚本化**（D2/D3/D6 汇总一页） | `37-一键启动脚本/cloud-review.sh`：一次执行输出运行健康+日志异常+风控行为三段摘要；首次运行自动创建 `.trae/documents/review-reports/`；并落盘 `budget-baseline.md`（近 3 个月滚动均值，本人确认） | — | 只读查询，零风险 |
| P0-1 | registry schema 1.1 扩展（role/tier 字段） | 185 SKILL 全部补 role；校验脚本通过 | — | 批量误标 → 先用 category 规则推断 |
| P0-2 | 模型 registry 加 `state` 字段 + promote/eval 脚本 | v1 迁为 `production`；新模型走 none→staging→production | P0-1 | 现有训练脚本硬编码 `current_version`，需兼容 |
| P0-3 | G2 pre-commit hook（复用 ci.yml 的 ruff/black） | 本地 commit 触发 lint+secret 扫描 | — | 大仓库 lint 慢 → 只查 staged |
| P0-4 | G4 波动率门禁脚本 | 部署前输出 ATR 分位 + 是否放行 | P0-2 | 分位计算依赖 18-DB 数据 |

### P1（1 个月内）

| # | 任务 | 验收标准 |
|---|---|---|
| P1-1 | G5/G6 自动回滚 + systemd watchdog | 人为造故障 → 自动回滚成功 |
| P1-2 | 模型热加载（current.json 轮询） | 改 current.json → 服务下一周期换模型 |
| P1-3 | 本地辅训 Release 通道 | 本地训练产物 → Release → 云端注册成功 1 例 |
| P1-4 | 风控独立线登记（映射现有 trailing-stop/风控 timer） | 门禁链文档中显式标注 |

### P2（1-3 个月）

| # | 任务 |
|---|---|
| P2-1 | SKILL 冲突检测 + 依赖循环校验脚本 |
| P2-2 | Postmortem 模板 + GitHub 归档流程 |
| P2-3 | 首次灾备演练（记 RTO/RPO） |
| P2-4 | 季度 SKILL 审计自动化 |

---

## 七、《三端协同》SKILL 设计（交付物）

### 7.1 定位

`dream-three-tier-collab`（category: `collaboration`，role: `coordinator`，tier: 三端）——**编排型 SKILL**，不重复实现已有能力，只做路由：

| 意图 | 路由到 |
|---|---|
| **评审云端（八维）** | 本 SKILL §一之五 评审清单 → 对应工具（cloud-logs.sh / systemctl 只读 / data-troubleshoot / registry.json 评审） |
| 要改代码 → 走门禁链 | `dream-code-commit-sync-workflow` → `dream-code-deploy-pipeline` |
| 要排查云端 | `cloud-logs.sh` + `dream-bugfix-workflow` |
| 要做架构审查 | `dream-arch-research-orchestrator` |
| 要训练/注册模型 | 模型生命周期脚本（本 SPEC §4） |
| 要验收 | `dream-acceptance-verify` |
| 要治理 SKILL | `dream-skill-index-governance` |

### 7.2 内容结构

```markdown
# dream-three-tier-collab
## 零、云端八维评审清单（本地第一职责，D1-D8 操作化）
## 一、三端职责速查（RACI 表）
## 二、门禁链 G1-G7 与失败处理
## 三、排查 SLA 与升级路径（P0/P1/P2）
## 四、模型生命周期状态机与双路径
## 五、SKILL 注册/治理规则
## 六、意图路由表（上表）
## 七、红线（禁止事项）
```

### 7.3 红线（必须写入 SKILL）

1. **禁止**本地 + 云端对同一 OKX 账户双实盘
2. **禁止** force merge 绕过 G3
3. **禁止** 引入 ArgoCD/K8s/MLflow 等重型工具（资源不允许）
4. **禁止** 未过 G7 的模型 promote 到 production
5. **必须** 每次 P0 故障后 24h 内写 Postmortem
6. **必须** 变更代码后先 commit 再重启服务
7. **必须** 评审通道只读——禁止借评审过程直接修改云端运行态（发现问题一律走门禁链修复）
8. **默认** SKILL 治理走已有 registry，不新建第二套注册表

---

## 八、验收标准（整体）

| 维度 | 标准 |
|---|---|
| 文档 | 本 SPEC 通过评审；《三端协同》SKILL 落盘并注册 |
| 门禁 | G1-G7 全部有可执行实现或明确映射 |
| SKILL | 185 个存量 SKILL 补齐 role；新 SKILL 可被 recall 命中 |
| 模型 | 完成一次端到端 none→staging→production→回滚演练 |
| 认知 | SPEC 关键决策 record B 级 + verify |

---

## 九、下一步

1. 用户评审本 SPEC（P0 范围是否认可）
2. 评审通过 → `dream-eng-mgmt-workflow` 出分阶段执行计划
3. P0 落地 → 验收 → `dream-completion-evolution-workflow` 收尾
