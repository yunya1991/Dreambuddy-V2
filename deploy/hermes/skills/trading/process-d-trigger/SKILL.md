# SKILL: process-d-trigger
# 触发时机: 每周一 06:00 / P006 sleepwalk_alert 触发时提前执行
# 角色: 调度层 — 不内联分析逻辑，全部委托官方 SKILL

## 职责
调度执行 Process D 三级学习闭环复盘，按序委托各官方 SKILL 完成所有分析，
然后更新状态并推送飞书复盘室。

---

## Phase-0 前置状态读取

```
1. read_session_state()
2. 提取 last_process_d、team_b_sleepwalk_alert、last_retrospective_score、screen1_session_id
3. 若 team_b_sleepwalk_alert = true → 在输出中标注 "P006 提前触发"
4. 确认 episode 数据范围（last 7 天）
```

---

## Phase-0.5 语义检索 — 拉本周决策上下文

使用 `session_search` 拉取本周关键决策对话，作为 A8 复盘和做梦部分析的补充输入：

```python
# P0.5-1: Screen1 方向决策上下文
session_search(query="Screen1 direction BTC bull bear decision", sort="newest", limit=3)
# P0.5-2: 入场/跳过决策链
session_search(query="Gate C entry approval SKIP skip_rate", sort="newest", limit=3)
# P0.5-3: 用户手动干预/纠正
session_search(query="纠正 不对 修改 调整 策略 参数", sort="newest", limit=3)
```

**目的**：
- 审计决策链中的推理偏误（对比 session_search 中的推理 vs 最终决策）
- 识别被忽略的预警信号（session 中提到但决策时未采纳的观点）
- 发现用户手动纠正的模式（高频纠正 = 策略信号失效）

**产物**：将检索到的对话摘要写入 `review/session_context.json`，供 Phase-1 的 `dream-oneirology` 和 `A8-theory-practice-verification` 交叉引用。

> 若 session_search 无结果（新系统），标注 `session_context: empty`，正常继续。

---

## Phase-1 A8 知行合一批评 + 做梦部分析（并行）

委托官方 SKILL，不重复其内部评分逻辑：

**并行执行：**

```
use_skill("dream-oneirology")          # 做梦部：强迫性重复/维度凝缩/被压制判断
use_skill("A8-theory-practice-verification")  # A8：知行一致性评分 + 偏见审计
```

`dream-oneirology` 内部完成：
- 输入 last 7 天 episode.json
- 检测：强迫性重复 / 维度凝缩 / 被压制判断 / 叙事二次修正
- 输出 review/oneirology-report.json

`A8-theory-practice-verification` 内部完成：
- 确认偏见 / 群体思维 / 过度自信三项偏见审计
- 参考 oneirology-report.json + review/session_context.json 补充 bias_audit
- 输出 review/a8-reflection.json（含 retrospective_score / key_findings）

等待两者均完成后继续。

---

## Phase-2 量化数据分析

```
use_skill("dream-data-analysis")
```

`dream-data-analysis` 内部完成：
- composite_confidence 趋势 / skip 率 / 梦游风险等级
- 与 oneirology-report 交叉验证
- 输出 review/data-analysis-report.json

---

## Phase-3 知识库更新

```
use_skill("dream-knowledge")
```

`dream-knowledge` 内部完成：
- 将本周 Screen1 结论写入 knowledge/strategy_scores/
- 若有 A9 离场结果，更新对应策略胜率/RR
- 识别新市场状态模式，写入 knowledge/regime_patterns/

---

## Phase-4 规律提炼

```
use_skill("learning-episode-writer")
```

`learning-episode-writer` 内部完成：
- 输入 last 20 episodes + data-analysis-report + oneirology-report
- 规律提炼（min_frequency=3, min_severity=2, cooldown=10）
- F_前缀失败规律 / S_前缀成功规律命名
- 输出 review/weekly-lessons.json（lessons_delta: added/updated/deprecated）

---

## Phase-5 改进提案生成

基于 weekly-lessons.json + data-analysis-report 的 calibration_suggestions，
生成 review/weekly-proposals.json：

- 提案类型：`martingale_param_update` / `gate_threshold_update` / `trigger_prompt_patch`
- 强制字段：`rollback_plan_id` + `evidence_refs[]`
- 状态：`pending_review`（⚠️ H009 宪法约束：禁止自动部署，须人工审核）

---

## Phase-5.5 大师动态进化

基于上周 PnL vs Screen1 预判方向，更新大师权重：

```
# 正确预判大师 → confidence_weight +0.1
# 错误预判大师 → confidence_weight -0.05
更新 knowledge/master_profiles/{id}.json
```

---

## Phase-6 自动进化检查

```bash
python C:/tmp/evolver_runner.py
```

- `EVOLVED`  → 报告"A1 提示词已更新，备份: qwen_analyst_backup_XXXXXX.py"
- `SKIPPED`  → 报告跳过原因
- `GATE_FAIL`→ 报告"进化候选未超越双基线，保留当前提示词"
- 失败 → 记录错误，**不影响主流程**

---

## Phase-7 状态更新

```
write_session_state({
  "last_process_d":           <today>,
  "last_retrospective_score": <a8_result.retrospective_score>,
  "pending_proposals":        <proposals_count>,
  "team_b_sleepwalk_alert":   false
})
```

---

## Phase-8 飞书推送 + 多维表格更新

```bash
# 推送复盘报告至复盘室
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py review \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id>

# 更新多维表格 A8 复盘得分（upsert）
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py bitable \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id>

# 关闭复盘任务 + screen1 任务
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/feishu_notify.py task process_d_done \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id>

# 追加到 Wiki 复盘档案节点（obj_token: HpI4dEIDrojkCyxIfvhcZYBWnRh）
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/wiki_sync.py process_d \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id> > /tmp/process_d_wiki.md && \
lark-cli --profile dream docs +update --api-version v2 \
  --doc HpI4dEIDrojkCyxIfvhcZYBWnRh \
  --command append --doc-format markdown \
  --content @/tmp/process_d_wiki.md

# 更新 Wiki 知识积累节点（strategy_scores 新增一行）
python C:/tmp/Dreambuddy-V2/6-TRADING/scripts/wiki_sync.py knowledge \
  C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id> > /tmp/knowledge_wiki.md && \
lark-cli --profile dream docs +update --api-version v2 \
  --doc SCWFd5dApovzxixt8B2cL2G1nG0 \
  --command append --doc-format markdown \
  --content @/tmp/knowledge_wiki.md

# 更新飞书 OKR KR 进度（ProcessD A8 得分写入 KR4: 7646831232336235462）
A8_SCORE=$(python -c "
import json,sys
from pathlib import Path
p = Path('C:/tmp/Dreambuddy-V2/6-TRADING/sessions/<screen1_session_id>/review/a8-reflection.json')
score = json.loads(p.read_text(encoding='utf-8')).get('retrospective_score', 0) if p.exists() else 0
print(score)
")
lark-cli --profile dream okr +progress-create --as user \
  --target-id 7646831232336235462 \
  --target-type key_result \
  --content "{\"blocks\":[{\"block_element_type\":\"paragraph\",\"paragraph\":{\"elements\":[{\"paragraph_element_type\":\"textRun\",\"text_run\":{\"text\":\"ProcessD A8复盘得分: ${A8_SCORE}/100\"}}]}}]}" \
  --progress-percent "${A8_SCORE}" \
  --progress-status normal \
  --source-title "Dreambuddy ProcessD"
```

- 任意步骤失败 → 打印错误，**不阻塞**

---

## 输出格式

```
=== Process D 复盘完成 ===
触发类型: 定期 / P006 提前触发
委托: dream-oneirology ✓ | A8-theory-practice-verification ✓
      dream-data-analysis ✓ | dream-knowledge ✓ | learning-episode-writer ✓
A8 得分: 78/100
偏见发现: CONFIRMATION_BIAS
改进提案: 2 个（status=pending_review，需人工审核）
自动进化: SKIPPED（episodes=8 < 20）
飞书推送: 复盘室 ✓
状态已更新: last_process_d / 梦游告警已重置
```

---

## 失败处理

| 场景 | 处理 |
|------|------|
| 任意官方 SKILL 异常 | 记录错误，继续执行后续 SKILL，最终汇总失败项 |
| evolver_runner 失败 | 记录错误，不影响主流程 |
| 飞书推送失败 | 打印错误，**不阻塞** |
| GitHub 归档失败 | 标注"归档失败，建议手动写入" |
