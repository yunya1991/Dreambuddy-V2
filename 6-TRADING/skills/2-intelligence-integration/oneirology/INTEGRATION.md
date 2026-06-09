# dream-oneirology 集成规范 (Process D — OE)

> **原始 SKILL**: dream-multiskill-v2/skills/2-INTELLIGENCE/dream-oneirology/SKILL.md v2.0.0
> **集成团队**: Process D (Step 0 并行分析)
> **触发时机**: 每周一 06:00 Process D，与 D1 (A8批评) **并行运行**

---

## 一、职责

从弗洛伊德《梦的解析》五大机制的视角，分析 Team B 决策 episodes 中的「被压制判断 / 强迫性重复 / 维度凝缩 / 叙事二次修正」，提供 A8 批评之外的第二视角。

**关键定位**: 纯顾问输出，**无 Gate 权力**，不能阻断任何执行，仅供 A8 和 D3 提案参考。

---

## 二、四大分析模块（6-TRADING 版）

### 模块 1: 强迫性重复检测（P006 预警）

- **触发条件**: `consecutive_skip_count >= 3`（早于 P006 的 7 次门槛，提前预警）
- **分析**: 连续 SKIP 的真实原因是系统性恐惧还是市场机会确实不存在？引用的理由是否雷同？
- **输出**: `compulsive_skip_analysis`

### 模块 2: 维度凝缩检测

- **触发条件**: A1/A2/A3 三个子 Agent 的方向评分差异 > 25 分
- **分析**: 哪个评分维度被 8 维总分「压缩」掉了？总分共识是否遮盖了重要分歧？
- **输出**: `condensation_flags`

### 模块 3: 被压制判断提取

- **触发条件**: `red_team_flag = true`（IA-A3 标记）且 Gate C 最终为 PASS
- **分析**: 红队分析提出了反论，但系统仍然 PASS 了。被压制的反向信号是什么？压制原因合理吗？
- **输出**: `suppressed_judgments`

### 模块 4: 叙事二次修正检测

- **触发条件**: 上周存在 SKIP → ENTER → PnL < 0 的序列
- **分析**: 入场归因中是否存在「事后编织」的叙事？数据是否被强行解释为支持入场的理由？
- **输出**: `narrative_distortion`

---

## 三、输出规范

写入 `sessions/{latest_session}/review/oneirology-report.json`:

```json
{
  "analysis_ts": "2026-05-26T06:05:00+08:00",
  "trigger_session": "20260526-BTC",
  "analyst": "dream-oneirology v2.0",
  "disclaimer": "本报告为顾问视角，不具有门禁权力，仅供 A8 批评和 D3 提案参考",
  "compulsive_skip_analysis": {
    "is_traumatic": false,
    "consecutive_count": 3,
    "likely_cause": "资金费率负值导致系统性规避 SHORT 方向",
    "recommendation": "检查 F_SHORT_SQUEEZE_UNDERWEIGHTED 是否过度激活"
  },
  "condensation_flags": [],
  "suppressed_judgments": [],
  "narrative_distortion": {
    "detected": false,
    "evidence": null
  },
  "dream_summary": "系统在 SHORT 方向上存在轻度创伤反应。建议 D3 提案中设定资金费率风险的合理上限，而非无限规避。"
}
```

---

## 四、与 A8/D2/D3 的接口

| 产物字段 | 用途 |
|---------|------|
| `compulsive_skip_analysis` | A8 `bias_audit` 的补充输入（P006 梦游早期预警） |
| `condensation_flags` | D2 lesson 提炼参考（被压制维度的规律价值） |
| `suppressed_judgments` | D3 proposal 潜在方向（Gate 阈值是否过严）|
| `narrative_distortion` | A8「纸上谈兵」检测补充（归因一致性） |

---

## 五、运行限制

| 约束 | 说明 |
|------|------|
| 无 Gate 权力 | `oneirology-report` 中任何发现不能直接阻断 Screen1/2/3 |
| 非强制 | 若分析无法完成，不阻断 Process D 其他步骤 |
| 宪法约束 | 所有「大胆观点」必须标注为 `advisory`，不得伪装为决策指令 |
| 触发阈值 | 若上周 episodes 数量 < 3，跳过模块 2/3/4，仅执行模块 1 |

---

*最后更新: 2026-05-26*
