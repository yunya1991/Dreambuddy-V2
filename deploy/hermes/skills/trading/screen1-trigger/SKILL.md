# SKILL: screen1-trigger
# 触发时机: 每周日 20:00 / Screen2 检测到价格漂移 >10% / Screen1 有效期过期
# 角色: 调度层 — 不内联分析逻辑，全部委托官方 SKILL

## 职责
调度执行 Screen1 周线研判全流程，委托 `dream-screen1-first` SKILL 完成所有分析，
然后更新状态并推送飞书通知。

---

## Phase-0 前置检查

```
1. read_session_state()
2. 若 screen1_valid_until 未过期 且 非手动触发 → 输出"Screen1 仍有效，跳过" 退出
3. 若当前 current_position.status = "holding" → 记录日志，继续执行（方向评估优先）
```

---

## Phase-1 执行 Screen1 分析

委托官方 SKILL，不重复其内部逻辑：

```
use_skill("dream-screen1-first")
```

`dream-screen1-first` 内部完整执行：
- 注释门禁检查（FULL / PARTIAL / BASELINE）
- B/C/D/E/F 五个维度 SKILL 按依赖顺序运行
- A1（矛盾论）/ A2（第一性原理）/ A3（沙盘推演）合成链
- master-seminar 大师辩论 + red_team_flag 判断
- cross-asset 跨资产配置矩阵
- 产物归档（C4 artifact-alignment-manager）
- 写入 sessions/{YYYYMMDD}-BTC-SCREEN1/ 全部文件

等待 `dream-screen1-first` 返回结果后继续。

---

## Phase-2 状态更新

解析 `dream-screen1-first` 返回的结果，写入会话状态：

```
write_session_state({
  "screen1_direction":        <result.direction>,
  "screen1_score":            <result.adjusted_score>,
  "screen1_btc_price_basis":  <result.btc_price>,
  "screen1_valid_until":      <result.valid_until>,
  "screen1_session_id":       <result.session_id>,
  "last_screen1_date":        <today>,
  "screen1_blocked_reason":   <result.blocked_reason or null>,
  "screen1_gate_level":       <result.gate_level>,
  "screen1_dispatch_model":   <result.synthesis_model>,
  "screen1_clock_stage":      <result.clock_stage>,
  "screen1_skill_regime":     <result.skill_regime>
})
```

若 `dream-screen1-first` 返回 `SCREEN1_BLOCKED` → 写入 `screen1_blocked_reason`，**不执行 Phase-3**，输出错误。

---

## Phase-3 飞书推送 + 多维表格归档

Phase-2 成功后，顺序执行：

```bash
# 1. 推送至研究室（完整七维度 + A1/A2/A3）+ 管理看板（摘要）
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py screen1 \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id>

# 2. 写入多维表格交易记录（upsert，可重复执行）
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py bitable \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id>

# 3. 创建飞书任务"本周研判"
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py task screen1_done \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id>

# 4. 追加到 Wiki 市场研判节点
lark-cli --profile dream docs +update --api-version v2 \
  --doc DnWtdOKpAo18iExwBQBcFalanUg \
  --command append \
  --doc-format markdown \
  --content "$(python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/wiki_sync.py screen1 C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id>)"
```

- 任意步骤失败 → 打印错误，**不阻塞**，继续完成

---

## 输出格式

```
=== Screen1 完成 ===
委托: dream-screen1-first ✓
门禁级别:  [FULL/PARTIAL/BASELINE]
方向:      SHORT | 得分: 48 | 价格: $73,349
象限:      STAGFLATION_LITE | 制度: WEAK_BEAR
有效期至:  2026-06-09
红队标志:  false
飞书推送:  研究室 ✓ | 管理看板 ✓
下一步:    Screen2 将在明日 07:30 自动运行
```

---

## 失败处理

| 场景 | 处理 |
|------|------|
| `dream-screen1-first` 异常 | 输出错误详情，不更新状态，不推送飞书 |
| 状态写入失败 | 记录错误，仍执行飞书推送（用内存数据） |
| 飞书推送失败 | 打印错误，**不阻塞** |
