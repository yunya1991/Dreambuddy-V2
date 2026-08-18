# 6-TRADING Claude Code 协作方案 v1.0

> **文档定位**: 本文档是 Claude Code 协作系统的**源文件**，Claude 的记忆文件从此处同步。
>
> **更新规则**: 修改此文档 → 告知 Claude "同步记忆" → Claude 读取此文档更新记忆系统。
>
> **版本**: v1.1 | 创建日期: 2026-05-26 | 更新: 2026-05-27

---

## 一、系统概述

### 1.1 设计目标

构建一个由 Claude Code 驱动的 6-TRADING 自动化协作系统，实现：
- **定期执行**：通过 CronCreate 定时触发三屏分析
- **多 Agent 协作**：并行子代理分别执行 A1/A2/A3 研究
- **结构化输出**：每次研究产出标准 session 文件夹
- **状态持久化**：关键状态写入 Claude 记忆跨会话保留
- **渐进代码化**：SKILL 先行，稳定后逐步代码化

### 1.2 与 DREAM-AGENT 的关系（方案 C）

DREAM-AGENT 系统作为 6-TRADING **开发治理系统**，而非运行时驱动器：
- DREAM-AGENT 负责：新 SKILL 开发、A 系列迭代、跨 SKILL 接口变更（走 Phase 0-8）
- 6-TRADING 负责：实时执行 A0-A9，独立自驱

---

## 二、三团队分工

### Team A — 研究预设（Screen 1 + Screen 2）

| 屏 | 周期 | 使用 SKILL | 输出 |
|----|------|-----------|------|
| Screen 1 | 周线 | dream-screen1-first | 方向 + 合约/现货马丁选择 |
| Screen 2 | 日线 | dream-screen2-second | 三大预设（入场/加仓/TP-SL） |

**执行方式**：
- Screen 1：并行启动 3 个子 Agent（A1/A2/A3），主 Agent 综合输出
- Screen 2：顺序执行 A1→A2→A3（基于 Screen 1 方向约束），计算马丁阶梯

**触发时机**：
- Screen 1：每周日 20:00（CronCreate）
- Screen 2：每工作日 07:30（CronCreate）

---

### Team B — 实时执行层（Screen 3 完整接管）

**完整流水线**：
```
读 Screen 2 presets
  → A7 门禁（SKILL: A7-practice-theory）
    → BLOCK → 中止，写入 team-b/a7-gate.json
  → A4 实时验证（scripts/a4_validation_executor.py）
    → FAIL → 等待，不执行
  → Gate C（skills/dream-pretrade-gatekeeper/pretrade_gatekeeper.py）
    → BLOCK → 中止，写入 gate-c/pretrade-check.json
  → A5 下单（scripts/dream_trade_exec.py）
    → 写入 team-b/execution-log.md
  → 开启 A6 监控 + A9 止损循环
    → A6 加仓信号 → 追加 team-b/a6-events.jsonl
    → A9 离场信号 → 写入 team-b/a9-exit.json
```

**触发时机**：每工作日 09:00 状态检查（CronCreate）

---

### Gate C — 代码级执行门禁（独立检查点）

- 文件：`6-TRADING/skills/dream-pretrade-gatekeeper/pretrade_gatekeeper.py`
- 在 Team B A5 下单前同步运行
- 输出 PASS/BLOCK + reason_codes
- **硬约束**：BLOCK 必须中止，不可绕过

---

### Process D — 复盘（A8 驱动）

- 触发：每周一 06:00（CronCreate）
- 读取上周所有 sessions/ 的 session-summary.md
- 执行 A8（A8-theory-practice-verification SKILL）
- 输出 review/a8-reflection.md + Screen 1 参数调整建议

---

## 三、会话文件夹规范

### 3.1 路径规则

```
6-TRADING/sessions/{YYYYMMDD}-{SYMBOL}-{TRIGGER}/
```

TRIGGER 取值：`SCREEN1` / `SCREEN2` / `TEAMB` / `REVIEW`

### 3.2 目录结构

```
sessions/
  _template/                     ← 模板目录（不做实际交易）
  20260526-BTC-SCREEN1/
    meta.json                    ← 会话元数据（状态机）
    team-a/
      screen1/
        weekly-direction.md      ← 周线综合研判
        strategy-type.json       ← {type, direction, score, valid_until}
        raw/
          a1-contradiction.md    ← A1 原始输出
          a2-first-principles.md ← A2 原始输出
          a3-simulation.md       ← A3 原始输出
      screen2/
        daily-presets.json       ← 三大预设结构化数据
        martingale-grid.json     ← 阶梯计算参数
        order-plan.md            ← 可读版预设表（人工 review 用）
        raw/                     ← A1/A2/A3 日线原始输出
    team-b/
      a7-gate.json               ← {result: PASS/BLOCK, reason, timestamp}
      a4-validation.json         ← A4 验证结果
      execution-log.md           ← A5 执行记录
      position-state.json        ← 当前仓位状态快照
      a6-events.jsonl            ← A6 监控事件流（append-only）
      a9-exit.json               ← A9 离场决策
    gate-c/
      pretrade-check.json        ← {pass, reason_codes, timestamp}
    review/
      a8-reflection.md           ← Process D 复盘输出
    session-summary.md           ← 最终摘要
```

### 3.3 meta.json 状态机

```json
{
  "session_id": "20260526-BTC-SCREEN1",
  "symbol": "BTC-USDT-SWAP",
  "trigger": "cron_screen1_weekly",
  "created_at": "2026-05-26T20:00:00Z",
  "status": "team_a_complete",
  "status_flow": [
    "created → team_a_running → team_a_complete",
    "→ team_b_running → gate_c_check → executing",
    "→ monitoring → closed"
  ],
  "team_a_complete_at": null,
  "team_b_started_at": null,
  "closed_at": null,
  "screen1_direction": null,
  "screen2_presets_ready": false
}
```

---

## 四、CronCreate 定时任务

| 任务 | Cron | Job ID | 状态 |
|------|------|--------|------|
| Screen 1 周线分析 | `0 20 * * 0` | `b9ce16da` | ✅ 运行中 |
| Screen 2 日线预设 | `30 7 * * 1-5` | `cd7edd91` | ✅ 运行中 |
| Team B 状态检查 | `0 9 * * 1-5` | `a30b1027` | ✅ 运行中 |
| Process D 复盘 | `0 6 * * 1` | `21514de4` | ✅ 运行中 |

### 触发提示词

> ⚠️ **触发提示词已迁移至独立规范文档，请勿修改此处（会造成版本分裂）**
>
> **权威来源**: [TRIGGER_PROMPTS.md](TRIGGER_PROMPTS.md) **v1.2**
>
> 当前版本包含：Phase-0 完整数据采集链（P0.1-P0.9）/ IA 偏见注入（A1/A2/A3/GC/A8）/
> ACH 竞争性假设 Gate C / master-seminar 大师辩论 / dream-archive-center 历史情景 /
> dream-oneirology 弗洛伊德分析 / dream-data-analysis 量化复盘 / 三级学习闭环

**多 Claude Code 协作同步规则**：
1. 修改触发提示词 → 先更新 `TRIGGER_PROMPTS.md` → 再同步各 Claude Code 本地 memory
2. Process D D3 输出 `trigger_prompt_patch` 提案 → 人工审核 → 更新 `TRIGGER_PROMPTS.md`
3. 所有 Claude Code 实例以 `TRIGGER_PROMPTS.md` 版本号为准，本地 memory 版本低时须更新

---

## 五、多 Agent 协作模式

### Screen 1 并行模式（3 子代理同时运行）

```
主 Agent
├── 子 Agent 1: dream-contradiction-theory（A1 周线矛盾分析）
│     输出 → team-a/screen1/raw/a1-contradiction.md
├── 子 Agent 2: dream-first-principles（A2 周线第一性原理）
│     输出 → team-a/screen1/raw/a2-first-principles.md
└── 子 Agent 3: master-seminar（A3 周线沙盘推演）
      输出 → team-a/screen1/raw/a3-simulation.md
          ↓ 三者完成后
主 Agent 综合 → strategy-type.json + weekly-direction.md
```

### Screen 2 顺序模式（依赖 Screen 1 输出）

```
主 Agent 读取 Screen 1 输出
→ A1(日线) → A2(日线) → A3(日线)
→ 马丁阶梯计算（based on 20日波动率）
→ 输出 daily-presets.json
```

---

## 六、现有代码基础

### 已就绪脚本（scripts/）

| 脚本 | 对应角色 | 状态 |
|------|---------|------|
| `a1_research.py` | Team A A1 | ✅ 可用 |
| `a2_first_principles_v2.6_auto.py` | Team A A2 | ✅ 可用 |
| `a4_validation_executor.py` | Team B A4 | ✅ 可用 |
| `a5_guards.py` | Team B A5 门禁 | ✅ 可用 |
| `dream_trade_exec.py` | Team B A5 执行 | ✅ 可用 |
| `dream_strategy_pipeline.py` | 总流水线 | ⚠️ 输出路径需改为 sessions/ |
| `dream_stop_loss_monitor.py` | Team B A9 | ✅ 已修复凭证（v1.1） |
| `screen1_manual_trigger.py` | Team A Screen 1 参考 | ✅ 可参考 |
| `okx_cli.py` | OKX 接口封装 | ✅ 标准接口 |

### 缺口（已补全）

| 缺口 | 补全方式 |
|------|---------|
| Screen 3 SKILL 定义 | ✅ dream-screen3-third/SKILL.md |
| sessions/ 目录规范 | ✅ sessions/_template/ |
| A6 加仓触发（监控中） | 🔄 dream_stop_loss_monitor.py 扩展（Phase 2） |

---

## 七、代码化演进路线

### Phase 1（当前）— SKILL + Claude Code 调度

- 所有分析通过 SKILL 提示词执行
- Claude Code 读取 SKILL 输出写入 session 文件夹
- CronCreate 触发定时执行
- 记忆文件保存跨会话状态

### Phase 2 — 现有代码接管

- `dream_strategy_pipeline.py` 输出路径统一到 `sessions/` 目录
- `dream_stop_loss_monitor.py` 扩展 A6 加仓触发逻辑
- Gate C 完整接入执行流程
- 目标：Team A 的 A1/A2 分析由 Python 脚本执行

### Phase 3 — 补齐缺口

- A6 监控扩展为独立持续运行进程
- A9 21 事件库触发器代码化
- Screen 2 Bayesian 优化自动化

### Phase 4 — 全代码化

- A7/Gate C 规则全部代码化（参考 pretrade_gatekeeper.py 模式）
- dream_strategy_pipeline.py 升级为完整编排器
- CronCreate 可替换为系统级 cron

---

## 八、操作原则

1. **SKILL 先行，代码后跟**：新流程先用 SKILL 跑通，稳定后再代码化
2. **Session 文件夹是真相来源**：任何分析结果必须写入文件夹，不依赖对话上下文
3. **记忆文件是跨会话状态**：仅存持仓方向、Screen1 研判等；per-session 数据在文件夹
4. **Gate 是硬约束**：A7 BLOCK 和 Gate C BLOCK 必须中止，不可绕过
5. **凭证统一走 `~/.okx/config.toml`**：禁止硬编码凭证到代码文件

---

## 九、Claude 记忆文件索引

| 记忆文件 | 内容 | 更新时机 |
|---------|------|---------|
| `project_trading_system_design.md` | 设计决策、分工、代码化路线 | 方案变更时 |
| `project_trading_session_state.md` | 当前持仓方向、Screen1研判、马丁层级 | 每次 Team A/B 执行后 |
| `reference_trading_cron_jobs.md` | CronCreate Job ID + 触发提示词（从 TRIGGER_PROMPTS.md 同步） | 创建/删除定时任务时 |

**远端规范文档**（GitHub，多 Claude Code 协作权威来源）：

| 文档 | 内容 | 关联记忆文件 |
|------|------|------------|
| [TRIGGER_PROMPTS.md](TRIGGER_PROMPTS.md) | 4 个 CronCreate 完整触发提示词 v1.2 | `reference_trading_cron_jobs.md` |
| [SKILL_REGISTRY.md](SKILL_REGISTRY.md) | 24 个 SKILL 注册表 + Mermaid 流程图 v1.2 | `project_trading_system_design.md` |

**同步规则**：修改远端规范文档后，告知 Claude "同步记忆" 即可更新对应本地记忆文件。

---

> **文档维护**: 此文档由 Claude Code 生成并维护。变更需通过 PR 合入 main 分支。


---

## 十、SKILL 注册表与治理

> **完整注册表**: [SKILL_REGISTRY.md](SKILL_REGISTRY.md)（22 个 SKILL，5 大团队分类 + Mermaid 流程图）

### 团队职能升级（v2.0）

原三团队（Team A/B + Gate C + Process D）扩展为**五职能分类**：

| 职能 | 原名 | SKILL 数 | 核心职责 |
|------|------|---------|---------|
| Governance | — | 1 | dream-constitution 宪法约束（全团队前置）|
| Team A | Team A | 7 | 研究预设（Screen 1/2，纯研究）|
| Team B | Team B | 9 | 入场执行（Screen 3 + episode 记录）|
| Team C | Gate C 扩展 | 4 | 日内监控离场（A6/A7/A9 + 产物归档）|
| Process D | Process D 升级 | 3 | 三级学习闭环（A8→knowledge→distill→propose）|
| Knowledge Base | — | 1 | 策略知识库（dream-knowledge v1.1）|

### 0-CORE SKILL 集成（v2.0 新增）

本次从 dream-multiskill-v2/skills/0-CORE 集成 6 个 SKILL：

| SKILL | 集成位置 | 核心价值 |
|-------|---------|---------|
| dream-constitution v2.9 | Governance（所有团队） | 宪法约束，H001-H009 硬门禁 |
| artifact-alignment-manager | Team C (C4) | session 产物标准化投递 |
| learning-episode-writer | Team B (B9) | 结构化 episode 替换自由格式日志 |
| dream-knowledge v1.1 | Knowledge Base (K1) | 策略知识库，Screen 1 Phase-0 可检索 |
| learning-lesson-distiller | Process D (D2) | episodes→lessons 规律提炼 |
| learning-proposal-generator | Process D (D3) | lessons→proposals 改进提案 |

**集成规范文件**: `skills/0-core-integration/{skill-name}/INTEGRATION.md`

### Process D 三级学习闭环（升级版）

```
A8 批评 (D1) → dream-knowledge 写入 (K1) → lesson-distiller (D2) → proposal-generator (D3)
                                              ↓
                                  weekly-lessons.json + weekly-proposals.json
                                              ↓
                                     人工审核 → 更新触发提示词/参数
```

---

## 十一、宪法合规声明

> 所有 6-TRADING 决策遵循 dream-constitution v2.9，具体映射见 [CONSTITUTION_COMPLIANCE.md](CONSTITUTION_COMPLIANCE.md)。

核心约束：
- H008: Phase-0 Tavily 数据采集未完成 → SCREEN1_BLOCKED
- H001-H003: 无/过期/反向 Screen1 方向 → Gate C HARD_FAIL
- H009: proposals 未人工审核 → 不得自动部署
