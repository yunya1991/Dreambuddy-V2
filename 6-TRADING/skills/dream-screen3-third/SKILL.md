---
title: "第三屏: 实时执行层 SKILL v1.1"
summary: "三屏交易体系执行层 - A7门禁→A4验证→A5入场→A6监控→A9离场 完整闭环"
trigger:
  - "第三屏"
  - "screen3"
  - "实时执行"
  - "入场执行"
  - "A5执行"
  - "监控加仓"
  - "止盈止损"
  - "紧急离场"
  - "Screen 3"
version: "1.0"
updated: "2026-05-27"
depends:
  - dream-screen2-second
  - A7-practice-theory
  - dream-tactical-validator
  - dream-tactical-executor
  - dream-intelligence-monitor
  - dream-exit-skill-v2
  - dream-pretrade-gatekeeper
---

# 第三屏: 实时执行层 SKILL (dream-screen3-third)

> **SKILL 定位**: 三屏交易体系的**执行层**
>
> **核心职责**: 接收第二屏预设，执行入场-加仓-止盈止损-离场完整闭环
>
> **执行周期**: 由 CronCreate 每工作日 09:00 检查触发，持仓期持续监控
>
> **版本**: v1.1 | 创建日期: 2026-05-26 | 更新日期: 2026-05-27

---

## 一、在三屏体系中的位置

```
┌─────────────────────────────────────────────────────────┐
│              三屏交易体系调用链                            │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  第一屏 (dream-screen1-first)                           │
│    → 输出: 周线方向 + 合约/现货马丁选择                   │
│         │                                               │
│         ▼                                               │
│  第二屏 (dream-screen2-second)                          │
│    → 输出: 三大预设价位表（入场/加仓/TP-SL）               │
│         │                                               │
│         ▼                                               │
│  【本SKILL】第三屏 (dream-screen3-third)                 │
│    → 接收第二屏预设 → 完整执行闭环                        │
│         │                                               │
│         ▼                                               │
│  输出: 仓位状态 + 执行日志 + 离场结果                     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 核心原则

| 原则 | 说明 |
|------|------|
| ✅ 以第二屏预设为参考基准 | 不独立判断方向，基于预设调整 |
| ✅ A7 门禁为首要前置检查 | A7 SKIP 则整体中止，不绕过 |
| ✅ Gate C 为最后代码门禁 | 硬规则检查，BLOCK 则不下单 |
| ✅ A6+A9 持仓期持续运行 | 不间断监控，实时调整止盈止损 |
| ❌ 不独立判断方向 | 方向来自第一屏 |
| ❌ 不修改阶梯结构 | 马丁阶梯由第二屏计算 |

---

## 二、执行流水线

### 2.1 整体流程图

```
┌──────────────────────────────────────────────────────────────┐
│                   第三屏执行流水线                             │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  输入: 第二屏 daily-presets.json                              │
│    │                                                         │
│    ▼                                                         │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Phase 0: 状态检查                                    │    │
│  │  读取 memory 当前持仓状态                             │    │
│  │  → no_position: 进入入场流程                          │    │
│  │  → holding: 进入监控流程                              │    │
│  └───────────────────┬─────────────────────────────────┘    │
│                       │                                      │
│          ┌────────────┴────────────┐                        │
│          ▼                         ▼                        │
│  【入场流程】                  【监控流程】                   │
│  Phase 1: A7 门禁              Phase 4: A6 监控检查          │
│    ↓ SKIP → 中止                ↓ 加仓信号 → 执行加仓        │
│  Phase 2: A4 验证              Phase 5: A9 止盈止损检查      │
│    ↓ FAIL → 等待                ↓ 离场信号 → 执行离场        │
│  Phase 3: Gate C 门禁                                       │
│    ↓ BLOCK → 中止                                           │
│  Phase 3.5: A5 下单                                         │
│    ↓ 成功 → 进入监控流程                                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

### 2.2 Phase 0: 状态检查（必须执行）

```yaml
Phase 0: 状态检查
  ────────────────────────────────────────────────────────
  步骤:
    1. 读取 memory/project_trading_session_state.md
    2. 检查 current_position.status
    3. 检查 screen2_presets 是否存在且未过期

  分支:
    status = no_position AND presets 存在:
      → 进入入场流程（Phase 1）
    status = holding:
      → 进入监控流程（Phase 4）
    presets 不存在或过期:
      → 警告：第二屏预设缺失，无法执行
      → 建议触发 Screen 2 重新生成

  输出:
    → 写入 team-b/position-state.json (当前状态快照)
```

---

### 2.3 Phase 1: A7 门禁（前置强制检查）

> **使用 SKILL**: `A7-practice-theory`
>
> **定位**: 理论与实践一致性检查，确认当前市场状态与第二屏分析逻辑一致

```yaml
Phase 1: A7 门禁
  ────────────────────────────────────────────────────────
  输入:
    - 第二屏 strategy-type.json（方向、策略类型）
    - 第二屏 daily-presets.json（三大预设）
    - 当前市场实时状态（价格、波动率）

  执行:
    调用 A7-practice-theory SKILL
    检查: 第一屏/第二屏的理论判断 vs 当前实盘情况

  输出 PASS:
    → 写入 team-b/a7-gate.json: {result: "PASS"}
    → 继续 Phase 2

  输出 SKIP:
    → 写入 team-b/a7-gate.json: {result: "SKIP", reason: "..."}
    → 整体中止，不进行后续步骤
    → 更新 session meta.json status = "a7_skipped"
    → 提示: 需重新运行第二屏 Screen 2

  a7-gate.json 格式:
    {
      "result": "PASS | SKIP",
      "reason": "理论实践一致/不一致说明",
      "market_state": "当前市场状态简述",
      "timestamp": "ISO8601"
    }
```

---

### 2.4 Phase 2: A4 实时验证

> **使用脚本**: `scripts/a4_validation_executor.py`（已有）
>
> **定位**: 验证 A3 推演结论在当前市场是否仍然有效

```yaml
Phase 2: A4 实时验证
  ────────────────────────────────────────────────────────
  输入:
    - 第二屏 A3 沙盘推演结论（screen2/raw/a3-daily.md）
    - 当前实时行情（价格/K线/指标）
    - 最新消息面信号

  执行:
    调用 scripts/a4_validation_executor.py
    验证: A3 方向判断是否仍然有效
    检查: 是否有新矛盾出现
    评估: 入场置信度评分

  输出 PASS (置信度 ≥ 60%):
    → 写入 team-b/a4-validation.json
    → 可能输出调整后入场价位（如有调整）
    → 继续 Phase 3

  输出 FAIL (置信度 < 60%):
    → 写入 team-b/a4-validation.json: {result: "FAIL", confidence: x}
    → 不下单，等待下次检查周期
    → 记录等待原因

  a4-validation.json 格式:
    {
      "result": "PASS | FAIL",
      "confidence": 0.0-1.0,
      "direction_valid": true/false,
      "adjusted_entry_price": null,
      "reason": "验证说明",
      "timestamp": "ISO8601"
    }
```

---

### 2.5 Phase 3: Gate C 代码门禁

> **使用脚本**: `skills/dream-pretrade-gatekeeper/scripts/pretrade_gatekeeper.py`（已有）
>
> **定位**: 硬规则代码检查，所有软性判断已在 A7/A4 完成

```yaml
Phase 3: Gate C 代码门禁
  ────────────────────────────────────────────────────────
  输入 (来自第二屏预设 + 当前账户状态):
    - strategy_directive（策略指令）
    - data_health（数据完整性）
    - scores_result（信号评分）
    - position_result（仓位计算）
    - account_snapshot（账户快照：回撤、dream_mode）

  执行:
    python skills/dream-pretrade-gatekeeper/scripts/pretrade_gatekeeper.py

  输出 PASS:
    → 写入 gate-c/pretrade-check.json: {pass: true, reason_codes: []}
    → 继续 Phase 3.5 (A5 下单)

  输出 BLOCK:
    → 写入 gate-c/pretrade-check.json: {pass: false, reason_codes: [...]}
    → 整体中止，禁止下单
    → 常见 BLOCK 原因:
      - 账户今日最大回撤超限
      - 数据质量不达标（candles/funding缺失）
      - 仓位计算失败
      - dream_mode 降级

  pretrade-check.json 格式:
    {
      "pass": true/false,
      "reason_codes": ["CODE1", "CODE2"],
      "scores": {},
      "position": {},
      "timestamp": "ISO8601"
    }
```

---

### 2.6 Phase 3.5: A5 入场下单

> **使用脚本**: `scripts/dream_trade_exec.py`（已有）

```yaml
Phase 3.5: A5 入场下单
  ────────────────────────────────────────────────────────
  输入:
    - Gate C 通过结果
    - 第二屏预设入场价位（或 A4 调整后价位）
    - 马丁阶梯参数（仓位 = 账户 1/4）

  执行:
    1. 下入场限价单（Level 0）
    2. 同步挂加仓限价单（Level 1-3，基于预设阶梯）
    3. 设置止损条件单（加仓期仅硬性保护）

  下单成功:
    → 写入 team-b/execution-log.md（完整下单记录）
    → 更新 memory current_position.status = "holding"
    → 更新 memory martingale_level = 0
    → 更新 session meta.json status = "monitoring"
    → 进入 Phase 4（监控流程）

  下单失败:
    → 记录错误到 execution-log.md
    → 不更新状态，下次检查周期重试

  execution-log.md 格式:
    # 执行日志 - {timestamp}

    ## 下单参数
    - 交易对: BTC-USDT-SWAP
    - 方向: LONG/SHORT
    - 入场价: $xx,xxx
    - 仓位: x 张 (账户 25%)

    ## 阶梯挂单
    | 层级 | 价格 | 数量 | 状态 |
    ...

    ## 止损设置
    - 止损价: $xx,xxx (Level 3 以下触发)
```

---

### 2.7 Phase 4: A6 实时监控（持仓期）

> **使用 SKILL**: `dream-intelligence-monitor`
> **辅助脚本**: `scripts/dream_stop_loss_monitor.py`（A9 止损部分）

```yaml
Phase 4: A6 实时监控
  ────────────────────────────────────────────────────────
  触发频率:
    正常状态: 每小时运行
    异常状态: 每15分钟运行（价格偏离>3% 或 波动率翻倍）
    紧急状态: 实时监控（21事件库触发）
  Phase 1 当前限制: 每工作日 09:00 CronCreate 入口触发，
    持仓期 A6 子检查在同一周期内重复执行；
    Phase 3 代码化后升级为 dream_stop_loss_monitor.py 持续运行。
  定位: 持仓期间实时监控，识别加仓时机

  监控维度:
    1. 价格触及预设加仓价位 → 触发加仓信号
    2. 支撑位回踩确认
    3. 风险事件实时检测（→ 转交 A9）
    4. Regime 状态变化（→ 转交 A9）

  加仓触发逻辑:
    if 价格 ≤ 预设加仓价位[current_level]:
      AND martingale_level < 3:
      AND 无 A9 风险预警:
        → 触发加仓信号

  加仓执行:
    1. 下加仓限价单（Level current_level+1 价位）
    2. A9 重新计算止盈止损（基于新均价）
    3. 更新 memory martingale_level += 1
    4. 追加 team-b/a6-events.jsonl（append）

  a6-events.jsonl 格式（每行一个事件）:
    {"type": "add_position", "level": 1, "price": 79000, "qty": 5, "timestamp": "..."}
    {"type": "price_alert", "detail": "接近 Level 2 加仓价位", "timestamp": "..."}
    {"type": "risk_alert", "risk": "量能萎缩", "action": "pass_to_a9", "timestamp": "..."}
```

---

### 2.8 Phase 5: A9 止盈止损 + 离场决策

> **使用 SKILL**: `dream-exit-skill-v2`
> **辅助脚本**: `scripts/dream_stop_loss_monitor.py`

```yaml
Phase 5: A9 止盈止损 + 离场决策
  ────────────────────────────────────────────────────────
  触发: 每次监控周期 + A6 风险信号 + 价格到达 TP/SL 位

  四层离场决策链:
  ────────────────────────────────────────────────────────
  【L1】止盈止损层
    加仓期（Level < 3）:
      止损仅作硬性保护（跌破 Level 3 极限价触发）
      止盈暂不启用
    持仓期（Level = 3 三层加满）:
      止损: 基于加仓后均价计算
      止盈: 动态调整（趋势加强+20-50%，趋势衰竭提前止盈）

  【L2】信号反转层
    A2 第一性原理确认趋势反转
    Regime 切换（市场状态改变）
    矛盾论主要矛盾发生转化
    → 立即离场，不等待 L1

  【L3】风险事件层
    21 事件库触发（黑天鹅/政策突变/流动性枯竭）
    → 强制立即离场，不等待

  【L4】参数优化层
    时间止损（持仓超周期未达目标）
    波动率异常（HV/IV 急剧变化）

  ★ 最大回撤硬性止损（独立于四层，优先于一切）:
    回撤计算: (当前权益 - 历史最高权益) / 历史最高权益
    回撤 ≥ 20%: 强制全部平仓，不等待任何 L1-L4 信号
    触发后: 更新 status = "emergency_closed"，写入 a9-exit.json

  离场优先级: L1 < L2 < L3 < L4 < 最大回撤强制止损

  离场执行:
    分批离场: 50% → 30% → 20%（L1止盈）
    全部离场: L2/L3/L4 触发时

  输出:
    → 写入 team-b/a9-exit.json
    → 如离场: 更新 memory current_position.status = "no_position"
    → 如离场: 更新 session meta.json status = "closed"
    → 写入 session-summary.md

  a9-exit.json 格式:
    {
      "triggered": true/false,
      "layer": "L1 | L2 | L3 | L4",
      "reason": "触发原因",
      "exit_type": "partial | full",
      "exit_price": xx,
      "pnl": xx,
      "timestamp": "ISO8601"
    }
```

---

## 三、输入规范

### 必须输入（来自第二屏）

```json
{
  "screen2_presets": {
    "symbol": "BTC-USDT-SWAP",
    "direction": "LONG",
    "strategy_type": "contract_martin",
    "entry_price": 79800,
    "martingale_levels": [
      {"level": 1, "price": 79000, "size_pct": 0.25},
      {"level": 2, "price": 78200, "size_pct": 0.25},
      {"level": 3, "price": 77500, "size_pct": 0.25}
    ],
    "tp_price": 83000,
    "sl_price": 77000,
    "scenario": 1,
    "grid_interval": 800,
    "valid_until": "2026-05-28T00:00:00Z"
  },
  "screen1_direction": {
    "direction": "LONG",
    "score": 82,
    "strategy_type": "contract_martin",
    "valid_until": "2026-06-09T00:00:00Z"
  }
}
```

---

## 四、输出规范

### 会话文件夹写入清单

| 文件 | 写入时机 | 格式 |
|------|---------|------|
| `team-b/a7-gate.json` | Phase 1 完成 | JSON |
| `team-b/a4-validation.json` | Phase 2 完成 | JSON |
| `gate-c/pretrade-check.json` | Phase 3 完成 | JSON |
| `team-b/execution-log.md` | Phase 3.5 完成 | Markdown |
| `team-b/position-state.json` | Phase 0 + 每次状态变化 | JSON |
| `team-b/a6-events.jsonl` | Phase 4 每次事件 | JSONL (append) |
| `team-b/a9-exit.json` | Phase 5 离场决策 | JSON |
| `session-summary.md` | 会话关闭时 | Markdown |

### 记忆更新清单

每次执行后更新 `memory/project_trading_session_state.md`：

| 字段 | 更新时机 |
|------|---------|
| `current_position.status` | A5 下单成功 / A9 离场 |
| `current_position.entry_price` | A5 下单成功 |
| `martingale_level` | 每次 A6 触发加仓 |
| `active_session_id` | 每次新 session 创建 |

---

## 五、马丁策略约束（硬性）

```yaml
宪法约束（P0不可违背）:
  最大加仓次数: 3次（Level 0-3，共4层）
  单次仓位上限: 账户 25%（四等份原则）
  止损必须设置: 加仓期为硬性保护，持仓期正式启用
  禁止事项:
    ✗ 超过3次加仓
    ✗ 无止损运行
    ✗ 追涨杀跌（上涨时取消加仓单）
    ✗ A9风险预警时继续调整
    ✗ 绕过 A7 门禁或 Gate C
```

---

## 六、与 DREAM-AGENT 协作系统的关系

本 SKILL 运行时不依赖 DREAM-AGENT 的 PR 生命周期。

DREAM-AGENT 的介入时机：
- 本 SKILL 需要结构性变更（如修改 A9 离场逻辑、新增事件库条目）
- 上述变更走 DREAM-AGENT Phase 0-8 开发治理流程
- 日常参数调整（阈值、间隔）直接修改配置文件，无需 DREAM-AGENT

---

## 七、快速参考

```bash
# 触发 Team B Screen 3 检查（CronCreate 每工作日 09:00 自动触发）
# 手动触发时在 Claude Code 中输入:
# "运行 6-TRADING Team B Screen 3 状态检查"

# 查看当前持仓状态
# → 读取 memory/project_trading_session_state.md

# 查看最新执行日志
# → 读取 sessions/{latest}/team-b/execution-log.md

# 查看 Gate C 门禁结果
# → 读取 sessions/{latest}/gate-c/pretrade-check.json
```

---

> **文档维护**: 稳定运行后，Phase 1（A7）和 Phase 3（Gate C）规则将逐步代码化。
> 参考: `skills/dream-pretrade-gatekeeper/scripts/pretrade_gatekeeper.py` 的代码化模式。
