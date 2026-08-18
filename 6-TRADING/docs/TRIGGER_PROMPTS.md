# 6-TRADING 触发提示词规范 v1.3

> **版本**: v1.6 | **更新日期**: 2026-05-27
> **维护说明**: 本文档是 6-TRADING 4 个 CronCreate 定时任务的**权威提示词来源**。
> **多 Claude Code 协作**: 每次修改触发提示词后，必须同步更新本文档，确保所有 Claude Code 实例使用相同版本。
> **同步关系**: 本文档 → Claude Code 本地 `memory/reference_trading_cron_jobs.md`（单向从此同步）
> **v1.3 变更**: 新增 Governance 层（G2 合规/G3 自动修复/G4 升级路由/CC 成本守卫）；Process D 新增 Step 0C/1.5b/1.5c/4.5/4.6；完整提案生命周期闭环（含 R0-R3 分级落地矩阵）
> **v1.4 变更**: 正式绑定 tavily SKILL（4-GENERIC）为 Phase-0 搜索原语；标注 basic/advanced/news/general 模式；新增权威域名白名单注释
> **v1.5 变更**: 压力测试修复（10个缺口）：screen1_session_id 写入记忆、Screen2 漂移恢复机制、sleepwalk 提前触发机制、A9 EXIT 调用 B9+C4、PARALLEL_INCOMPLETE C4、A8/OE 并行 race condition、martingale 参数分隔标记
> **v1.6 变更**: Screen 2 Phase-1 A1/A2/A3 正式由 [qwen-analyst] 驱动（节省 ~70% Claude Token）；新增 screen2_qwen.py 调用规范；降级回退至 Claude 内联分析

---

## 一、CronCreate 任务注册表

| 任务 | Cron 表达式 | 说明 | Job ID | 状态 |
|------|------------|------|--------|------|
| Screen 1 周线分析 | `0 20 * * 0` | 每周日 20:00 | `b9ce16da` | ✅ 运行中 |
| Screen 2 日线预设 | `30 7 * * 1-5` | 每工作日 07:30 | `cd7edd91` | ✅ 运行中 |
| Team B 状态检查 | `0 9 * * 1-5` | 每工作日 09:00 | `a30b1027` | ✅ 运行中 |
| Process D 复盘 | `0 6 * * 1` | 每周一 06:00 | `21514de4` | ✅ 运行中 |

---

## 二、Screen 1 触发提示词（每周日 20:00）

```
运行 6-TRADING Team A Screen 1 周线分析：

[Phase-0 强制数据采集 — P0.1-P0.6 HARD BLOCK，P0.4b/P0.9 非阻塞]
[dream-cost-control 前置] 检查今日 Tavily 用量：
  - 用量 >= 95% → 输出 SCREEN_BLOCKED_BUDGET，写入记忆，停止执行
  - 用量 85-95% → P0.4b 降级为跳过（archive_data:"budget_limited"），其余正常
  - 用量 < 85% → 正常执行

P0.1: [tavily TX basic/news] 搜索 "Bitcoin BTC price USD {YYYY-MM-DD} current" → 提取当前价格
      域白名单: coindesk.com, coingecko.com, coinmarketcap.com, tradingview.com
P0.2: [tavily TX basic/news] 搜索 "Bitcoin perpetual futures funding rate {YYYY-MM-DD} OKX Binance" → 提取资金费率方向
      域白名单: coinglass.com, okx.com, binance.com
P0.3: [tavily TX basic/news] 搜索 "Bitcoin spot ETF net inflow outflow {YYYY-MM-DD}" → 提取资金流向（亿USD）
      域白名单: farside.co.uk, coindesk.com, theblock.co
P0.4: [tavily TX advanced/general] 搜索 "Bitcoin macro risk factors {YYYY-MM-DD} Fed geopolitical" → 提取宏观驱动
      域白名单: federalreserve.gov, reuters.com, bloomberg.com, ft.com
P0.4b: [dream-archive-center + tavily TX advanced/general] 搜索 "Bitcoin {macro_keyword} historical price action 2020 2022 2024"
       → 提取 2-3 个历史类比情景（similarity_score/btc_outcome/key_difference）
       → 非 HARD BLOCK：失败或预算限制则 archive_data:"unavailable"，继续执行
P0.5: [tavily TX basic/general] 搜索 "Bitcoin support resistance technical analysis {YYYY-MM-DD}" → 提取关键价格位
      域白名单: tradingview.com, cryptoquant.com, glassnode.com
P0.6: [tavily TX basic/news] 搜索 "Bitcoin fear greed index {YYYY-MM-DD}" → 提取市场情绪
      域白名单: alternative.me, coinmarketcap.com
P0.7: 价格可信度验证 — 若搜索价格与上次记录基价偏差 > 20%，输出 DATA_ALERT 并停止执行
P0.9: [dream-knowledge K1 检索] 查询 knowledge/strategy_scores/ 中最近 5 个 BTC 同向策略：
       → 提取平均胜率、平均 RR、最常见失败原因
       → 如胜率 < 30% 且记录 ≥3，当前 screen1_score 折扣 × 0.85
       → 将检索结果注入 data_context 的 knowledge_context 字段
       → 非 HARD BLOCK：K1 无记录时继续执行
P0.8: 合并以上数据为 data_context（含 historical_analogues + knowledge_context），所有后续 Agent 必须以此作为分析基础
⛔ 若 P0.1-P0.6 任意步骤失败（Tavily 无结果），输出 SCREEN1_BLOCKED，等待人工干预
   → 写入记忆 screen1_blocked_reason: "P0.{N}_TAVILY_NO_RESULT"（N=失败步骤编号）
   → 写入记忆 screen1_session_id: null（本次 Screen1 未完成）
   → [dream-operation-director] 自动触发 SOP-2 升级记录

[Phase-1 分析执行]
1. 读取 memory 中当前会话状态
2. 创建 sessions/{YYYYMMDD}-BTC-SCREEN1/ 文件夹结构
3. 并行启动 3 个子 Agent，将 Phase-0 data_context 注入提示词：
   - A1（矛盾分析）: 执行调研 + [IA-A1] 在输出前检查：锚定偏见/可得性启发/代表性启发
     → 如发现偏见，在 a1-contradiction.md 末尾追加 [BIAS_FLAG: {类型}]
   - A2（第一性原理）: 执行分析 + [IA-A2] 在输出前检查：确认偏见/过度自信/镜像思维
     → 如发现偏见，在 a2-first-principles.md 末尾追加 [BIAS_FLAG: {类型}]
   - A3（沙盘推演）: 执行 S1/S2/S3 情景 + [IA-A3 红队分析]：
     → 构建反论：支持反向的3个最强理由 + 证伪条件 + 最脆弱假设
     → 若红队论据强度 > 主方向40%，在 strategy-type.json 设置 red_team_flag:true
     → 将红队分析写入 a3-simulation.md 末尾的 [RED_TEAM_ANALYSIS] 段落
     → A3 同时输出 phase7_contingency（黑天鹅/极端情景应对方案）写入 strategy-type.json
4. A3 完成后，触发 [master-seminar] 大师阵营辩论：
   - 标准模式：4 位大师（趋势/基本面/均值回归/宏观风险）分多空辩论
   - 强化模式（red_team_flag=true 或 screen1_score<60）：追加黑天鹅/量化大师
   - 输出 master-debate.json（含 screen1_score_adjustment）
   - 按调整规则修正 screen1_score：一致+5/分歧-5/对立-15(MASTER_DEBATE_WARNING)
5. 综合输出 strategy-type.json（含 red_team_flag/phase7_contingency/adjusted score）+ weekly-direction.md
6. C4 产物归档（artifact-alignment-manager）：
   - strategy-type.json / weekly-direction.md / master-debate.json
   - raw/a1-contradiction.md / a2-first-principles.md / a3-simulation.md
7. 更新记忆中的 screen1_direction 状态：
   - screen1_direction / btc_price_basis / data_source / adjusted screen1_score / master_debate_result
   - **screen1_session_id**: 本次 session 文件夹路径（如 "20260526-BTC-SCREEN1"）← 供 Team B Gate C / A5 确定性定位使用
   - screen1_valid_until: 有效期（默认 7 天）
   - screen1_blocked_reason: 若被 SCREEN1_BLOCKED 则写入原因，否则 null
```

---

## 三、Screen 2 触发提示词（每工作日 07:30）

```
运行 6-TRADING Team A Screen 2 日线预设：

[dream-cost-control 前置] 检查今日 Tavily 用量（与 Screen 1 共享预算）：
  - 用量 >= 95% → 输出 SCREEN_BLOCKED_BUDGET，停止执行
  - 用量 >= 85% → 标注 TAVILY_BUDGET_WARNING，压缩 Phase-2 查询量
  - 用量 < 85% → 正常执行

[Phase-0 数据采集与漂移检查]
P0.1: [tavily TX basic/news] 搜索获取当前 BTC 价格（域白名单: coindesk.com, coingecko.com）
P0.2: 与记忆中 screen1_btc_price_basis 比对
  - 偏差 > 10%：[内联触发 Screen1] 在当前 Screen2 session 内直接执行 Screen1 全流程
     → Screen1 完成、记忆更新后，**立即自动继续** Screen2 Phase-0 P0.1 重新采集价格并继续
     → 若 Screen1 被 BLOCKED → Screen2 同步终止，不再重试（本日无预设）
     → 写入 Screen2 frontmatter: price_drift_triggered_screen1=true
  - 偏差 5-10%：继续执行，在输出中标注 PRICE_DRIFT_WARNING
  - 偏差 < 5%：正常执行
P0.3: 验证 Screen1 有效期（valid_until 字段），已过期则先触发 Screen1

[Phase-1 日线分析 — A1/A2/A3 由 qwen-analyst 驱动]
1. 创建 sessions/{YYYYMMDD}-BTC-SCREEN2/ 文件夹
2. [qwen-analyst] 调用 C:/tmp/screen2_qwen.py 顺序执行 A1→A2→A3（托管给千问 API，节省 ~70% Claude Token）：
   - A1 日线矛盾分析 → qwen-plus（输出: primary_contradiction / bull_evidence / bear_evidence / contradiction_score / bias_flags）
   - A2 第一性原理   → qwen-plus（输出: trend_confidence / screen1_alignment_pct / reasoning_chain / invalidation_threshold）
   - A3 三情景沙盘   → qwen-max（输出: S1/S2/S3 概率+TP/SL/仓位 / red_team_flag / phase7_contingency）
   Claude Code 职责：Phase-0 Tavily 搜索（P0.1-P0.3）+ 调用 screen2_qwen.py + 写入 GitHub
   ⛔ qwen-analyst 失败（API 超时/返回非 JSON）→ 降级：Claude Code 内联完成 A1/A2/A3 分析（与 Screen 1 相同标准）
3. 计算马丁阶梯参数（auto-repair G3 可自动更新下方标记段内的数值）：
<!-- MARTINGALE_PARAMS_START -->
   - S1基准: L0仓位=30%, TP=+3%, SL=-4%, 间距=1.5%
   - S2Squeeze: L0仓位=20%, TP=+5%, SL=-3%, 间距=2%
   - S3反转: L0仓位=25%, TP=+8%, SL=-5%, 间距=3%
<!-- MARTINGALE_PARAMS_END -->
   生成初始 daily-presets.json

[Phase-2 回测验证与参数优化]（非 HARD BLOCK，失败则降级输出 Phase-1 结果）
4. [dream-data-analysis 趋势上下文] 读取 review/data-analysis-report.json（如存在）：
   - 提取 trend.direction / resistance.resistance_score / trend.trend_confidence
   - trend_confidence < 0.4 → 跳过 Phase-2，标注 phase2_skipped:true，直接输出 Phase-1 结果
5. [dream-backtest A8s] 回测验证 martingale 参数可行性：
   - 输入: Phase-1 初始 daily-presets + trend_context（来自 DA）
   - 输出: backtest_result（胜率/最大回撤/平均 RR）
   - 若回测失败（数据不足/收敛失败）→ phase2_skipped:true，输出 Phase-1 结果
6. [dream-bayesian-opt A9s] 贝叶斯优化马丁格参数：
   - 输入: backtest_result + Phase-1 参数范围
   - 优化目标: maximize RR，约束 max_drawdown < 15%
   - 输出: optimized_params（TP/SL/间距/仓位比例调整建议）

[Phase-3 合并输出]
7. 合并 Phase-1 分析 + Phase-2 优化（或降级结果），输出：
   - daily-presets.json（含 phase2_skipped 标志）
   - martingale-grid.json
   - order-plan.md
8. C4 产物归档
9. 更新记忆中的 screen2_presets 状态
```

---

## 四、Team B Screen 3 触发提示词（每工作日 09:00）

```
运行 6-TRADING Team B Screen 3 状态检查：

[auto-repair 前置] 账户隔离快速检查：
  - 读取 memory/project_trading_session_state.md 的 current_account 字段
  - 确认 active_account=dreamdemo（或 A5 已人工确认启用）
  - 如发现账户混淆风险 → 立即停止，写入 governance/account-isolation-alert.json
    → [dream-operation-director] SOP-2 升级人工处理

1. 读取 memory 中当前仓位状态（project_trading_session_state.md）
2. 如 status=no_position 且 Screen2 presets 存在 → 执行入场流程：
   Step0: dream-strategy-parser (Regime路由) → 输出 directive_bias
   → dream-signal-scoring-spec (8维评分) + dream-risk-position-sizing + dream-execution-cost-model [并行]
     ⚠️ 三者必须全部完成才能继续，任意一个失败 → PARALLEL_INPUT_INCOMPLETE → 写 SKIP episode 终止
     → PARALLEL_INPUT_INCOMPLETE 时:
       ① [dream-operation-director] SOP-2 记录故障 SKILL（含 SKILL ID + 错误摘要）
       ② [learning-episode-writer B9] 写 SKIP episode（reason: PARALLEL_INPUT_INCOMPLETE）
       ③ [artifact-alignment-manager C4] 归档本次 episode.json（确保记录不丢失）
   → A7-practice-theory (实践门禁)
   → dream-pretrade-gatekeeper (Gate C)：
     [IA-GC ACH验证] 在最终裁决前执行竞争性假设分析：
       读取 sessions/{最新Screen1_id}/team-a/screen1/strategy-type.json 的 red_team_flag
       假设A（入场有效）vs 假设B（虚假信号）的诊断证据：
         ① 资金费率方向是否与入场方向一致？（诊断性高）
         ② Screen1 btc_price_basis 偏差是否 <5%？（诊断性高）
         ③ A7 gate score 是否 >30/40？（诊断性中）
       若 red_team_flag=true：
         → 自动将 Gate C 信心阈值从 composite_confidence>60 提高到 >70
       若假设B诊断证据数量 ≥ 假设A → Gate C 降级为 SKIP
       → 将 ACH 摘要写入 gate-c/pretrade-check.json 的 ach_summary 字段
         （含 red_team_flag_applied / threshold_used / ach_result）
     Gate C BLOCK 且原因不明 → [dream-operation-director] SOP-2 升级 risk_owner
   → dream-tactical-validator (A4)
   → dream-tactical-executor (A5)：
     读取 sessions/{最新Screen1_session}/team-a/screen1/strategy-type.json
     提取 phase7_contingency 字段（黑天鹅/极端情景应对方案）作为执行约束
     → 若 phase7_contingency 不存在，继续执行（降级为无应急预案模式）
     执行完成后记录成本字段到 episode.json：fee_usdt / slippage_usdt / delay_cost_usdt / total_cost_usdt
   → learning-episode-writer (B9): 无论 ENTER/SKIP 均写 episode.json
     读取 team-b/a7-gate.json 获取 a7_gate_score（优先读文件，失败则 null）
     扫描 sessions/*/team-b/episode.json 计算 consecutive_skip_count（最近20条，遇非SKIP停止）
   → artifact-alignment-manager (C4): 产物归档
     归档: a7-gate.json / gate-c/pretrade-check.json / team-b/episode.json / execution-log.md
3. 如 status=holding → dream-intelligence-monitor (A6) 监控 + dream-exit-skill-v2 (A9) 止盈止损检查
   A9 离场完成后执行以下步骤（顺序）：
   ① [learning-episode-writer B9] 写 EXIT episode（action: EXIT_TP | EXIT_SL | EXIT_FORCED）
      → 填写 outcome: exit_price / pnl_usdt / pnl_pct / max_drawdown_pct / holding_hours / exit_reason
      → consecutive_skip_count 重置为 0
   ② [artifact-alignment-manager C4] 归档离场相关产物
      归档: exit-log.md / episode.json（含 outcome）/ team-b/a9-exit.json
4. 连续 SKIP ≥7 次 → sleepwalk_alert=true → 写入记忆文件，触发提前 Process D
   [提前触发机制]: B9 写入 sleepwalk_alert=true 后，立即在当前 Screen3 session 内
   **内联执行 Process D 触发提示词全流程**（不等待周一 CronCreate）
   → Process D 完成后，memory.sleepwalk_alert 重置为 false
   → 写入 episode.json: sleepwalk_early_review_triggered=true
```

---

## 五、Process D 触发提示词（每周一 06:00）

```
运行 6-TRADING Process D 复盘（三级学习闭环 v1.3）：

Step 0 [并行 — A8 + OE + PR 三路]:
  A) [A8-theory-practice-verification] 知行合一批评：
     - 读取上周所有 sessions/*/review/ 和 sessions/*/team-b/episode.json
     - [IA-PD] 偏见审计：确认偏见/群体思维/过度自信三项检查
     - 输出: review/a8-reflection.json（含 retrospective_score, key_findings, bias_audit）
     ⚠️ Step 0 并行约束：A8 不得在 Step0 内读取 OE 输出（OE 同时运行未完成）
        → A8 在 Step 1.5a 完成后，通过 Step 1.5d [可选] 补充 OE 的 compulsive_skip_analysis 到 bias_audit
  B) [dream-oneirology] 弗洛伊德梦分析（无 Gate 权力，纯顾问）：
     - 输入: sessions/*/team-b/episode.json (last 7 days)
     - 检测四大模块: 强迫性重复 / 维度凝缩 / 被压制判断 / 叙事二次修正
     - 触发阈值: consecutive_skip >= 3 → 强迫重复告警（早于 P006 的 7 次）
     - 输出: review/oneirology-report.json（dream_summary + 各模块分析）
  C) [dream-performance-review] 5维量化 SKILL 评分（与 A8/OE 并行）：
     - 评估关键 SKILL: B3/B6/B9/IA/MS/DA/D2/OE（准确率/延迟/效率/改进/合规）
     - D级 SKILL 触发 PIP 标记
     - 输出: review/skill-performance-report.json（含 grade/pip_triggered）

Step 1.5a [DA 量化分析]:
  [dream-data-analysis] episodes 时序统计：
  - 输入: sessions/*/team-b/episode.json (last_20_episodes, last_4_weeks)
  - 计算: composite_confidence MA/EMA趋势 / skip率 / 梦游风险等级
  - 输出: review/data-analysis-report.json
    → trend.direction + resistance.resistance_score + calibration_suggestions
    → sleepwalk_risk: "low|medium|high"（与 OE 模块1交叉验证）

Step 1.5b [CC 成本归因]（与 DA 并行）:
  [dream-cost-control] 成本分析：
  - 输入: episode.json 的 execution.total_cost_usdt 字段 (last_20_episodes)
  - 分析: 按 SKILL ROI 评级（A/B/C/D）+ Tavily 预算状态
  - 输出: review/cost-report.json（含 skill_roi / d_grade_skills / cost_alert）
  - D级 SKILL → 触发 dream-performance-review 重点评估标记

Step 1.5c [RE Token 效率监控]（DA + CC 完成后）:

  [resource-efficiency-analyst] Token 消耗分析（四条铁律严格执行）：
  - 仅读取本次 Process D 产出的最新 1 份报告
  - 无变化则输出"今日数据无异常变化"（≤50字）
  - 输出: review/efficiency-report.md（最多3条建议）

Step 1.5d [A8 + OE 合并补充]（OE 完成后，与 1.5a 完成后执行）:
  [A8-theory-practice-verification 补充更新]（非 HARD BLOCK）：
  - 读取 review/oneirology-report.json 的 compulsive_skip_analysis
  - 将其追加到 a8-reflection.json 的 bias_audit 段（补充内容，不覆盖已有 bias_audit）
  - 非 HARD BLOCK：OE 报告不存在时跳过，a8-reflection.json 不受影响

Step 2 [知识库写入]:
  调用 dream-knowledge (K1)：
  - 将本周 Screen1 结论写入 knowledge/strategy_scores/{session_id}.json
  - 如有 A9 离场结果，更新对应策略的胜率/RR字段
  - 识别新的市场状态模式，写入 knowledge/regime_patterns/

Step 3 [规律提炼]:
  调用 learning-lesson-distiller (D2)：
  - 输入: sessions/*/team-b/episode.json (last_20_episodes)
         + review/data-analysis-report.json（DA 量化证据）
         + review/oneirology-report.json（OE 顾问视角）
         + review/skill-performance-report.json（PR 量化评分）
         + review/cost-report.json（CC ROI 证据）
  - 参数: min_frequency=3, min_severity=2, cooldown=10
  - 输出: review/weekly-lessons.json (lessons_delta: added/updated/deprecated)

Step 4 [改进提案]:
  调用 learning-proposal-generator (D3)：
  - 输入: review/weekly-lessons.json + DA/CC/RE/PR 的 calibration_suggestions
  - 提案类型: trigger_prompt_patch(R2) / martingale_param_update(R1) / gate_threshold_update(R2) / skill_improvement_plan(R1)
  - 强制字段: rollback_plan_id + evidence_refs[]
  - 输出: review/weekly-proposals.json（status=pending_compliance_check）

Step 4.5 [提案合规审查 — 新增]:
  调用 ai-trading-compliance (G2)，对每条提案生成合规回执：
  - 将每条 proposal 包装为 change_bundle.json（含 intent/change_type/rollback_plan/evidence）
  - R0/R1 提案 + decision=pass → 标注 auto_land_allowed=true
  - R2/R3 提案 + decision=pass → 标注 pending_human_review=true
  - decision=fail → 提案退回，写入 a8-reflection.json 的 rejected_proposals 字段
  - 输出: governance/compliance-receipt-{proposal_id}.json（每条提案一个）

Step 4.6 [提案落地 — 新增]:
  调用 auto-repair (G3)：
  - 扫描 compliance-receipt-*.json，执行 auto_land_allowed=true 的提案
  - R0 knowledge_base_update → 自动更新 knowledge/ 对应文件（strategy_scores / regime_patterns）
  - R1 martingale_param_update → 自动更新 TRIGGER_PROMPTS.md 参数段
  - R1 skill_improvement_plan → 自动更新对应 INTEGRATION.md 的 PIP 段
  - R2 trigger_prompt_patch / gate_threshold_update → 写入 governance/pending-approvals.md
    → [dream-operation-director G4] 路由人工审批（通知 risk_owner / strategy_owner）
  - R3 skill_replacement → 直接路由 G4，G3 不处理
  - 输出: governance/auto-repair-report.json

Step 3.5 [大师动态进化]（D1 A8 完成后执行）:
  [master-seminar 进化] 根据上周 PnL vs Screen1 预判方向：
  - 正确预判大师: knowledge/master_profiles/{id}.json confidence_weight +0.1
  - 错误预判大师: knowledge/master_profiles/{id}.json confidence_weight -0.05

Step 5 [产物归档]:
  调用 artifact-alignment-manager (C4)：
  - 归档: a8-reflection.json / oneirology-report.json / data-analysis-report.json
           skill-performance-report.json / cost-report.json / efficiency-report.md
           weekly-lessons.json / weekly-proposals.json
           governance/compliance-receipt-*.json / auto-repair-report.json
  - frontmatter: chain_phase=A8, type=retrospective/lesson_delta/proposal/governance, dept=process-d

Step 6 [记忆更新]:
  更新 project_trading_session_state.md：
  - last_process_d: 当日日期
  - last_retrospective_score: A8 得分
  - pending_proposals: pending_human_review 的 R2 提案数量
  - pending_approvals_path: governance/pending-approvals.md
  - sleepwalk_alert: 重置为 false（如之前为 true）
  - budget_health: 来自 cost-report.json 的 cost_alert.level

⚠️ H009 宪法约束: trigger_prompt_patch 和 gate_threshold_update 即使合规通过，禁止 auto-repair 自动落地，须人工审核后修改 TRIGGER_PROMPTS.md
⚠️ OE 约束: oneirology-report.json 所有结论标注为 advisory，不得直接影响 Screen 执行
⚠️ RE 约束: resource-efficiency-analyst 每次最多 3 条建议，无变化则不输出，不做深度推理
```

---

## 六、版本历史

| 版本 | 日期 | 变更摘要 |
|------|------|---------|
| v1.0 | 2026-05 | 初始版本：Screen1/2/3 + Process D 基础结构 |
| v1.1 | 2026-05 | G1-G6 缺口修复：dream-backtest/bayesian-opt / B3/B4/B5 并行合约 / phase7_contingency |
| v1.2 | 2026-05-26 | 集成 5 个 2-INTELLIGENCE SKILL：IA 偏见注入 / ACH矩阵 / master-seminar / archive-center P0.4b / OE / DA |
| v1.3 | 2026-05-27 | 集成 6 个 3-SUPPORT SKILL：CC Tavily 预算守卫 / AR 账户隔离 / Process D Step 0C/1.5b/1.5c/4.5/4.6 完整提案闭环 |
| v1.4 | 2026-05-27 | 正式绑定 tavily 4-GENERIC SKILL 为 Phase-0 搜索原语；标注 basic/advanced/news/general 模式和权威域名白名单 |
| v1.5 | 2026-05-27 | 压力测试修复：screen1_session_id/blocked_reason 写入记忆；Screen2 漂移内联恢复；sleepwalk 内联 ProcessD；A9 EXIT B9+C4；PARALLEL_INCOMPLETE B9+C4；Step 1.5d A8+OE merge；martingale 参数分隔标记 |
| v1.6 | 2026-05-27 | Screen 2 Phase-1 A1/A2/A3 由 [qwen-analyst] 驱动（C:/tmp/screen2_qwen.py + qwen_analyst.py）；降级回退机制；节省 ~70% Claude Token |

---

## 七、多 Claude Code 协作同步规则

1. **此文档为权威来源** — 所有 Claude Code 实例的触发提示词必须与本文档一致
2. **修改流程**:
   - Process D D3 输出 `trigger_prompt_patch` 类型提案 → G2 合规审查（R2）→ 人工审核
   - 审核通过后，先更新本文档（TRIGGER_PROMPTS.md），再同步各 Claude Code 本地 memory
3. **同步检查**: 每次 Screen 1 前，Claude Code 应比对本文档与本地 `reference_trading_cron_jobs.md` 版本号是否一致
4. **禁止规则**: 任何 Claude Code 实例不得在未更新本文档的情况下，单方面修改本地 memory 中的触发提示词

---

*维护者: 6-TRADING Claude Code 协作系统 | 关联文档: [SKILL_REGISTRY.md](SKILL_REGISTRY.md) | [CLAUDE_CODE_COLLAB_PLAN.md](CLAUDE_CODE_COLLAB_PLAN.md)*
