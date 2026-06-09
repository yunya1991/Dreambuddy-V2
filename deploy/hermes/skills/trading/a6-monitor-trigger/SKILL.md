# SKILL: a6-monitor-trigger
# 触发时机: 每 4 小时 (cron: 0 */4 * * *)
# 角色: 调度层 — 持仓守卫 + 委托官方 A6 SKILL + 飞书推送

## 职责
持仓期间定时调用官方 `dream-intelligence-monitor` SKILL 执行完整情报监控，
然后推送至飞书交易台，并在需要时升级风控审批。

---

## Phase-0 持仓守卫（HARD GATE）

```
1. read_session_state()
2. 读取 current_position.status
   - "no_position" → 输出 "[A6] 当前无持仓，跳过监控" 静默退出
   - "holding"     → 继续
3. 读取 current_session_id（当前持仓对应的 session）
```

> 无持仓时不产生任何输出，不写文件，不推送飞书。

---

## Phase-1 执行 A6 情报监控

委托官方 SKILL，不重复其内部监控逻辑：

```
use_skill("dream-intelligence-monitor")
```

`dream-intelligence-monitor` 内部完整执行（v4.9）：
- P0 (必须)：OKX 持仓/账户/价格/资金费率实时数据
- P1 (重要)：ETF 资金流 / 巨鲸交易 / 多空比 / 链上指标
- P2 (常规)：宏观金融 / 地缘政治 / 加密政策
- 异常检测：价格波动 / 成交量 / 资金费率 / 爆仓事件
- A6→做梦部广播（a6_to_oneirology_broadcast.py）
- 生成 a6-monitor.json 写入 session 目录

等待 `dream-intelligence-monitor` 返回结果后继续。

---

## Phase-2 飞书推送

### 2.1 定时报告（每次必推）→ 交易台

```bash
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py a6_monitor \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<current_session_id>
```

### 2.2 阈值预警（由 dream-intelligence-monitor 返回的 alerts 决定）

若 `result.alerts` 非空，逐条推送预警：

```bash
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py a6_alert \
  '<alert_json>'
```

`feishu_notify.py` 内部自动判断是否触发 ESCALATE_TO_HUMAN（三条规则）。

---

## Phase-3 A9 联动（由官方 SKILL 内部决定）

`dream-intelligence-monitor` 检测到 P0 级事件时，内部已自动联动调用
`dream-exit-skill-v2`（A9）。

若 `result.a9_triggered = true`，则额外推送至 **管理看板 + 复盘室**：

```bash
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py a9 \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<current_session_id>
```

---

## 输出格式

**无持仓时（静默退出）:**
```
[A6] 当前无持仓，跳过监控。
```

**正常执行:**
```
=== A6 监控完成 ===
委托: dream-intelligence-monitor ✓
时间:    2026-06-03 08:00
状态:    NORMAL | 无触发事件
飞书推送: 交易台 ✓
```

**有预警时:**
```
=== A6 监控完成 ===
委托: dream-intelligence-monitor ✓
预警:    [MARTIN_TRIGGER] 价格接近加仓线
飞书推送: 交易台 ✓ | 交易台预警 ✓
ESCALATE: 未触发（loss_usdt=320 < 500）
```

---

## 失败处理

| 场景 | 处理 |
|------|------|
| `dream-intelligence-monitor` 异常 | 打印错误，**不阻塞**，跳过飞书推送 |
| 飞书推送失败 | 打印错误，**不阻塞** |
