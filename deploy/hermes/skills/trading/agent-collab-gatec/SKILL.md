# SKILL: agent-collab-gatec
# 触发: Trading-RiskControl 群里收到 @dream 要求协调 Gate-C 审批
# 角色: 总调度 / 审批协调员

## Dream Bot 在风控审批群的角色

当用户在 Trading-RiskControl 群里说"运行Gate-C"或"检查入场条件"时：

### Step 1: @ Hermes 执行评估
用 post 富文本发消息，@ Hermes（`ou_bcf92b6057e502054ca32bcd8ebf6570`）：

```
请执行 Gate-C 入场评估：
1. 读取最新 screen1/screen2 数据
2. 计算 8 维信号评分
3. 执行 ACH 竞争性假设分析
返回 JSON：gate_c_result(PASS/SKIP)/composite_confidence/a7_score/direction/entry_price/ach_summary/reason
```

### Step 2: 收到 Hermes 结果后，发审批卡片
解析 JSON，生成飞书交互卡片（schema 2.0，column_set + button，type=callback）发到本群。
按钮 value 中包含 `session_id` 和 `action`（gate_c_approve / gate_c_reject）。

### Step 3: 用户点按钮后
- 批准 → @ Hermes："Gate-C 已批准，请执行入场"
- 拒绝 → @ Hermes："Gate-C 已拒绝，写 SKIP episode"

## @ 格式（必须用 post 富文本）
```
action: send
msg_type: post
content:
  <at user_id="ou_bcf92b6057e502054ca32bcd8ebf6570">云涯Hermes</at> [消息内容]
```

## A9 离场审批（同样流程，反向）
当 A6 监控触发 A9 时：
1. @ Hermes 请求 A9 离场评估
2. Hermes 返回 decision/exit_score/pnl/reason
3. 推送离场审批卡片（批准平仓 / 保持持仓）
4. 用户批准 → @ Hermes 执行平仓
