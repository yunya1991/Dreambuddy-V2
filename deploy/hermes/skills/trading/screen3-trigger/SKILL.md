# SKILL: screen3-trigger
# 触发时机: 每工作日 09:00
# 角色: 调度层 — 不内联执行逻辑，全部委托官方 SKILL

## 职责
调度执行 Screen3 入场/监控/离场全流程，委托 `dream-screen3-third` SKILL 完成所有执行，
然后更新状态并推送飞书通知。

---

## Phase-0 前置检查

```
1. read_session_state()
2. 检查 screen2_presets 是否存在：
   - 不存在 → 输出"等待 Screen2 完成" 退出
3. 检查 screen2_presets.date 新鲜度：
   - 与 today 差距 > 1 天 → 输出 "SCREEN2_PRESETS_STALE，建议重新运行 Screen2"，记录警告，继续执行
4. 检查 screen1_blocked_reason：
   - 非 null → 输出"Screen1 被阻塞，Screen3 无法执行" 退出
5. 检查 team_b_consecutive_skips：
   - >= 7 → 记录 team_b_sleepwalk_alert=true，继续执行（由 dream-screen3-third 内部处理 P006）
```

---

## Phase-0.5 Gate-C 预审批（飞书交互卡片）

在调用 `dream-screen3-third` 前，若当前为 `no_position` 路径，先推送审批卡片：

```
1. 从 screen2_presets 读取入场参数（方向/入场价/马丁层数/止损）
2. 推送审批请求到飞书 Trading-RiskControl 群
3. 等待人工批准（timeout=3600s）：
   - 批准 → 继续 Phase-1
   - 拒绝 → 写 SKIP episode，不执行入场，退出
   - 超时 → 按拒绝处理
```

Hermes gateway 会自动在飞书群发出带 [批准] [拒绝] 按钮的审批卡片。
你点击按钮后，gateway 解锁等待线程，SKILL 继续执行。

> 若 `position_status = holding`（监控/离场路径），跳过此步骤直接进 Phase-1。

---

## Phase-1 执行 Screen3

委托官方 SKILL，不重复其内部逻辑：

```
use_skill("dream-screen3-third")
```

`dream-screen3-third` 内部完整执行（根据持仓状态自动路由）：

**无持仓路径（no_position）：**
- dream-strategy-parser → Regime 路由
- dream-signal-scoring-spec（8维评分）+ dream-risk-position-sizing + dream-execution-cost-model 并行
- A7-practice-theory 实践门禁
- dream-pretrade-gatekeeper Gate C（含 ACH 竞争性假设分析）
- dream-tactical-validator A4 验证
- dream-tactical-executor A5 入场执行
- learning-episode-writer B9 写 episode.json（ENTER/SKIP 均写）
- C4 产物归档

**持仓路径（holding）：**
- dream-intelligence-monitor A6 监控（内部处理阈值预警 + 异常检测）
- dream-exit-skill-v2 A9 离场评估（四层决策链）
- 离场后 C4 产物归档

等待 `dream-screen3-third` 返回结果后继续。

---

## Phase-2 状态更新

**ENTER 情况：**
```
write_session_state({
  "current_session_id": <result.session_id>,
  "current_position": {
    "status":     "holding",
    "entry_price": <result.btc_price>,
    "direction":   <result.direction>,
    "episode_id":  <result.episode_id>,
    "entry_date":  <today>
  },
  "team_b_consecutive_skips": 0
})
```

**SKIP 情况：**
```
write_session_state({
  "current_session_id":     <result.session_id>,
  "team_b_consecutive_skips": <result.consecutive_skip_count>,
  "team_b_sleepwalk_alert":   <result.sleepwalk_alert>
})
```

**EXIT 情况（持仓路径离场）：**
```
write_session_state({
  "current_position":   {"status": "no_position"},
  "current_session_id": <result.session_id>,
  "last_exit_date":     <today>,
  "last_exit_pnl":      <result.realized_pnl>
})
```

若 `team_b_sleepwalk_alert = true` → 立即触发 `process-d-trigger` SKILL（提前复盘）。

---

## Phase-3 飞书推送 + 多维表格归档

根据结果路由推送：

**入场/跳过（no_position 路径）→ 交易台 + 多维表格 + 任务：**
```bash
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py execution \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<result.session_id>

python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py bitable \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<result.session_id>

# ENTER 时创建持仓监控任务，SKIP 时关闭日线预设任务
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py task \
  <enter 或 skip> C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<result.session_id>
```

**离场（holding 路径 A9）→ 先飞书审批，批准后推送 + 多维表格更新：**

A9 decision = `EXIT` 时，Hermes gateway 先发审批卡片到 Trading-RiskControl 等待批准，
批准后再执行：
```bash
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py a9 \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<result.session_id>

python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py bitable \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<result.session_id>

# 关闭持仓监控任务，创建复盘任务
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py task exit \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<result.session_id>
```

- 任意步骤失败 → 打印错误，**不阻塞**，继续完成

---

## 输出格式（ENTER）

```
=== Screen3 完成 ===
委托: dream-screen3-third ✓
路径: 入场评估
Gate C: PASS | 信号得分: 72% | A7: 36/40
入场价: $73,200 | 方向: SHORT
Episode: 20260603-BTC-SCREEN3-090012 → GitHub ✓
飞书推送: 交易台 ✓
下一步: A6 监控将每 4h 自动运行
```

## 输出格式（SKIP）

```
=== Screen3 完成 ===
委托: dream-screen3-third ✓
路径: 入场评估
Gate C: SKIP | 原因: ENTRY_ZONE_NOT_REACHED
连续 SKIP: 3 次
Episode: 已归档
飞书推送: 交易台 ✓
下一步: 明日 09:00 再次检查
```

---

## 失败处理

| 场景 | 处理 |
|------|------|
| `dream-screen3-third` 异常 | 输出错误，写 SKIP episode，更新 skip 计数 |
| 状态写入失败 | 记录错误，仍执行飞书推送 |
| 飞书推送失败 | 打印错误，**不阻塞** |
