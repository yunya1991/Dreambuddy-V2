---
name: screen2-trigger
description: 每日 Screen2 日线预设触发调度。优先委托 dream-screen2-second SKILL，缺失时降级到 web_search + 内联 A1/A2/A3 分析。
category: trading
triggers:
  - cron: "30 7 * * 1-5"
---

# SKILL: screen2-trigger
# 触发时机: 每工作日 07:30 (cron)
# 角色: 调度层 — 优先委托 dream-screen2-second，缺失时内联降级

## ⚠️ FIRST: 解决名称冲突（如果此 skill 加载失败）

本 skill 存在已知冲突：`skills/screen2-trigger.md`（裸 .md 文件）与 `skills/trading/screen2-trigger/SKILL.md`（目录版本）同名导致加载器歧义。

**如果 cron 触发时提示 "skill not found" 或有歧义错误，说明冲突仍存在。此时按本 skill 的降级路径（P1-F1~F5）直接执行内联分析，不要中止。**

长期修复：手动删除裸文件 `C:\Users\luke.zhang\.hermes\skills\screen2-trigger.md`。

## 职责
调度执行 Screen2 日线预设全流程。主路径委托 `dream-screen2-second` SKILL；若该 SKILL 不存在或 API key 缺失，切换至内联降级路径完成分析，然后更新状态并推送飞书通知。

---

## Phase-0 前置检查

```
1. read_session_state() — 优先用 read_file()，若报 File not found 则降级到 execute_code + open()
2. 检查 screen1_valid_until：
   - 已过期 → 标注过期，但仍继续（Screen2 可基于历史 Screen1 方向执行）
   - 未过期 → 继续
3. 检查 screen1_blocked_reason：
   - 非 null → 输出"Screen1 被阻塞，Screen2 无法执行" 退出
```

> **路径解析陷阱**: 会话状态文件路径 `C:\Users\luke.zhang\.claude\projects\C--Users-luke-zhang\memory\project_trading_session_state.md` 中的 `C--Users-luke-zhang` 目录名会导致 `read_file` 路径转义失败（报 File not found），此时用 `execute_code` + Python `open()` 替代。此问题也影响所有 `6-TRADING/sessions/` 下产物的读取。

---

## Phase-1 执行 Screen2 分析

### 主路径：委托 dream-screen2-second SKILL

```
skill_view("dream-screen2-second")
```

若 SKILL 存在，按该 SKILL 内部流程执行（A1/A2/A3 → backtest → Bayesian opt → C4 归档）。
等待返回结果后跳至 Phase-2。

### 降级路径：内联执行（dream-screen2-second 不存在时）

当 `dream-screen2-second` SKILL 不存在或加载失败时，**不要中止**，切换至内联降级模式：

#### P1-F1: Phase-0 数据采集（降级）
- 优先使用终端运行 `python C:/tmp/screen2_runner.py --date YYYYMMDD --basis <screen1_basis>`
- 若脚本因 API key 缺失失败（TAVILY_API_KEY / DASHSCOPE_API_KEY 未设置），降级到：
  - `web_search` + `web_extract` 采集 BTC 价格、资金费率、ETF 流向、恐惧贪婪指数、宏观新闻
  - 关键数据点：BTC 现价、Screen1 基准价漂移、ETF 10日净流、F&G 指数、宏观背景（地缘/利率/黄金/DXY）
  - 数据来源标记为 `hermes_web_search_inline`

#### P1-F2: 漂移检查
- 漂移 = (现价 - screen1_btc_price_basis) / screen1_btc_price_basis
- >10%：标注 PRICE_DRIFT_CRITICAL，仍需先重跑 Screen1，但 Screen2 可继续
- 5-10%：标注 PRICE_DRIFT_WARNING，继续执行
- <5%：OK，继续

#### P1-F3: A1/A2/A3 内联分析
由编排层直接完成分析推理（不调用 qwen_analyst.py）：

**A1 矛盾分析** — 识别 Screen1 方向与当前市场信号的矛盾点：
- 费率矛盾：资金费率 vs 持仓方向（极度负费率后恢复 = 轧空风险）
- ETF 流矛盾：机构流向 vs 价格行为
- 情绪矛盾：恐惧贪婪 vs 趋势延续
- 跨市场矛盾：黄金/BTC 背离
- 输出: contradiction_score (0-10), bias_flags, summary

**A2 第一性原理** — 六因子加权评分：
| 因子 | 权重 | 说明 |
|------|------|------|
| ETF 供需 | 25 | ETF 净流方向推断机构仓位变化 |
| 市场结构 | 20 | 高低点序列、均线位置、距 ATH 回撤 |
| 宏观地缘 | 15 | 战争/停火、利率、油价、DXY |
| 情绪仓位 | 15 | F&G 指数、资金费率拥挤度 |
| 链上费率 | 10 | 永续合约费率方向 |
| 跨市场 | 15 | 黄金、美股与 BTC 相关性 |
- 评分: 每因子 -weight 到 +weight（负=偏空，正=偏多）
- **trend_confidence = |raw_score| / max_score**（勿用中性归一化！）
- 输出: trend_confidence, screen1_alignment_pct, direction, summary

**A3 三情景推演**：
- S1 (45%): 主情景 — 延续 Screen1 方向
- S2 (30%): 对冲情景 — 方向反转的条件与应对
- S3 (25%): 黑天鹅 — 极端事件的触发与预案
- 每个情景: entry_zone, TP, SL, martingale_layers, invalidation
- 单笔总敞口 ≤ 150 USDT（宪法约束）
- 红队审查: red_team_flag, black_swan_triggers

#### P1-F4: 产物写入
创建 session 目录并写入全部产物：
```
6-TRADING/sessions/{YYYYMMDD}-BTC-SCREEN2/
├── meta.json                        ← feishu_notify 必需
└── team-a/screen2/
    ├── daily-presets.json           ← 主预设文件
    ├── martingale-grid.json         ← 马丁格参数
    ├── a1-contradiction.md          ← A1 矛盾分析
    ├── a2-first-principles.md       ← A2 第一性原理
    └── a3-scenarios.md              ← A3 情景推演
```

**meta.json 格式**（feishu_notify.py screen2 依赖）:
```json
{
  "session_id": "YYYYMMDD-BTC-SCREEN2",
  "screen1_direction": "SHORT|BULL",
  "screen1_price": <number>,
  "screen1_score": <number>,
  "btc_price_at_analysis": <number>,
  "date": "YYYY-MM-DD"
}
```

**daily-presets.json 必须包含 feishu 兼容字段**（详见 `references/feishu-screen2-format.md`）:
- `direction`, `entry_price`, `take_profit`, `stop_loss`, `max_layers`, `interval_pct`

**martingale-grid.json 必须包含**: `max_layers`, `interval_pct`

#### P1-F5: GitHub 提交
```bash
cd /c/tmp/Dreambuddy-V2
git add 6-TRADING/sessions/{YYYYMMDD}-BTC-SCREEN2/
git commit -m "Screen2 daily preset: {session_id} | {direction} ${price} | trend_confidence={conf}"
git pull --rebase origin main && git push origin main
```
若 git push 因远程领先被拒，先 `git pull --rebase` 再 push。

---

## Phase-2 状态更新

更新 `project_trading_session_state.md` 中的 `screen2_presets` 字段：
```json
{
  "screen2_presets": {
    "session_id": "<session_id>",
    "date": "<today>",
    "btc_price_at_analysis": <number>,
    "status": "WAIT_FOR_ENTRY_SIGNAL",
    "entry_zone": [<low>, <high>],
    "preferred_entry": <number>,
    "invalidation": "<condition>",
    "recommended_action": "WAIT_FOR_ENTRY_SIGNAL",
    "trend_confidence": <0-1>,
    "red_team_flag": false,
    "price_drift_warning": false,
    "martingale_grid": { ... },
    "data_context": { ... }
  },
  "last_screen2_date": "<today>"
}
```

**重要**: trend_confidence 使用方向确信度（0-1），不是中性归一化值。
若主路径（dream-screen2-second）返回异常，记录错误但不更新状态。

---

## Phase-3 飞书推送 + 任务创建

**前置条件**: 使用 `lark-cli` 前需先绑定 Hermes:
```bash
lark-cli config bind --source hermes --identity bot-only
```
若未绑定，lark-cli 会返回 `not_configured` 错误。详见 `references/feishu-integration-architecture.md` 第九节完整诊断流程。

Phase-2 成功后，顺序执行：

```bash
# 1. 推送至交易台
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py screen2 \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<result.session_id>

# 2. 创建飞书任务"日线预设"
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py task screen2_done \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<result.session_id>
```

> **feishu_notify.py 支持的全部通知类型与五群组架构详见** `references/feishu-integration-architecture.md`。Screen1/execution/a6_monitor/a6_alert/a9/escalate/review/bitable 等通知由各自触发阶段独立调用，不在此 SKILL 范围内。

**常见错误修复**:
- `No such file or directory: '.../meta.json'` → 确保 meta.json 已创建（P1-F4）
- feishu 卡片字段为空 → 确保 daily-presets.json 包含 `direction`, `entry_price`, `take_profit`, `stop_loss`
- 任意步骤失败 → 打印错误，**不阻塞**，继续完成

---

## 输出格式

```
=== Screen2 完成 ===
委托: dream-screen2-second ✓ (或 hermes-agent-inline 降级)
Session: YYYYMMDD-BTC-SCREEN2
BTC 价格: $XX,XXX（Screen1 基准 $XX,XXX）
方向: SHORT/BULL | 趋势置信度: 0.XX
红队标志: true/false
价格漂移: ±X.X%（OK/WARNING/CRITICAL）
推荐操作: WAIT_FOR_ENTRY_SIGNAL
马丁格: N层 | 总敞口 150 USDT
飞书推送: 交易台 ✓ | 任务创建: ✓
GitHub: push ✓ (<commit_hash>)
下一步: Screen3 将在 09:00 自动检查入场条件
```

---

## 飞书集成参考

本 SKILL 使用飞书进行通知推送、任务管理和审批。以下参考文件提供完整集成架构和故障排查：
- `references/feishu-integration-architecture.md` — 五群组模型、通知类型、Bitable/审批/流程设计
- `references/feishu-screen2-format.md` — Screen2 产物格式要求（feishu_notify.py 依赖）
- `references/lark-cli-setup.md` — lark-cli 绑定 Hermes 配置流程

## 失败处理

| 场景 | 处理 |
|------|------|
| `dream-screen2-second` 不存在 | **切换降级路径（P1-F1~F5）**，不中止 |
| `dream-screen2-second` 执行异常 | 输出错误详情，切换降级路径继续 |
| API key 全部缺失 | 降级到 web_search + 内联分析，标注数据来源 |
| `screen2_runner.py` 失败 | 降级到 web_search + 内联分析 |
| 状态写入失败 | 记录错误，仍执行飞书推送（用内存数据） |
| 飞书推送失败 | 打印错误，**不阻塞**；若持续失败，参考 `references/feishu-gateway-troubleshooting.md` |
| GitHub push 失败 | 打印错误，不阻塞（产物已本地保存） |
| Hermes Bot 飞书无响应 | Gateway 可能未注册平台 → `hermes gateway restart`；`send_message` 无频道 → 在群内发消息触发 session 注册 |
| **terminal 工具不可用**（bash `cd` 路径错误） | 使用 `execute_code` + `subprocess.run()` 替代所有 Python 脚本调用（screen2_runner.py、feishu_notify.py、git 命令）。`execute_code` 使用 Python 原生路径解析，不受 MSYS bash 限制。 |
| **`read_file` 无法找到文件**（路径包含 `C--Users-luke-zhang` 等特殊目录名时 `read_file` 报 File not found） | 降级到 `execute_code` + Python `open()` 读取文件。`execute_code` 的 `os.path` 能正确解析 Windows 路径，`read_file` 有时会因路径转义失败。读取会话状态文件、产物文件时优先尝试 `read_file`，失败则立即切到 `execute_code`。 |
| **Screen3 入场检查无专用 SKILL**（`screen3-trigger` 不存在） | 由编排层内联执行 Screen3 检查：读取当前状态 → web_search 获取 BTC 现价 → 计算漂移、检查入场区间 → 更新 `team_b_status`/`team_b_consecutive_skips` → 输出决策报告。完整内联检查流程见 `references/screen3-inline-check.md`。 |
