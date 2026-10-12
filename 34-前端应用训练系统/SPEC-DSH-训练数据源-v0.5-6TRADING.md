# SPEC-20261012-DSH-v0.5 — DSH 层训练数据源（6-TRADING 采集器族）

> **版本**: v0.5 (6-TRADING 交易哲学资产扩展)
> **日期**: 2026-10-12
> **作者**: Trae + User
> **状态**: Draft（待评审）
> **关联**: SPEC-DSH-训练数据源-v0.4-TDD核心.md（已落地 5 采集器 534 条）
> **方法论**: recall → 6-TRADING A0-A9 资产调研 → 用户3问决策 → SPEC v0.5
> **目标层**: DSH 层 (ExecutionPathTrainingLoop — 序列模式挖掘 + 路径模板)
> **v0.5 核心命题**: 把 6-TRADING 的 A0-A9 交易哲学流水线转化为 DSH 训练数据，填补"为什么这样决策"的哲学级推理链空白。

---

## 0. Executive Summary

### 0.1 v0.4 现状 → v0.5 扩展

| 维度 | v0.4（已落地） | v0.5（本次立项） |
|------|--------------|----------------|
| 采集器数 | 5 个（TddTest/CogSession/TraderLog/REATest/ShadowVal） | +4 个（6-TRADING 族） |
| 数据域 | 代码测试 + 认知会话 + 日志 | +交易哲学 session + A0-A9 理论 + 做梦部 + 大师研讨 |
| 决策层级 | 战术执行（how） | +战略哲学（why） |
| node_sequence 平均长度 | 8.3 节点 | 预期 12-18 节点（哲学推理链更长） |
| DSH 总条数 | 534 条 | +180-280 条 → 714-814 条 |
| 理论根基 | 测试代码 + 日志 | +毛泽东矛盾论 / 孙子兵法 / 克劳塞维茨 / 弗洛伊德 |

### 0.2 核心价值

6-TRADING 的 A0-A9 不是普通工具 SKILL，而是**军事+哲学+心理学三源蒸馏的交易决策哲学流水线**。与子交易系统形成"why + how"互补：

| 子系统 | 提供什么 | A0-A9 提供 |
|--------|---------|----------|
| BCRM/BDSM/evolution | 战术执行细节（how） | 决策哲学框架（why） |
| TddTest 采集器 | 代码级决策序列 | 战略级推理链 |
| CognitiveSession | recall→record→verify | A1→A2→A3→A4 战略决策链 |

### 0.3 用户决策（已确认）

| 决策点 | 用户选择 | 含义 |
|--------|---------|------|
| 解析方案 | **混合方案** | A0-A9 SKILL.md + session 用规则解析（0 token）；做梦部 + master-seminar 用 LLM 辅助（少量 token） |
| SPEC 位置 | **新建 v0.5 独立** | 承接 v0.4，保持 v0.4 稳定 |
| 采集器范围 | **全 4 个一次立项** | P0-P3 同时规划，TDD 分批实现 |

---

## 1. 调研结论（事实清单）

### 1.1 6-TRADING 资产清单（已确认 ✅）

| 资产类型 | 数量 | 位置 | 价值等级 |
|---------|------|------|---------|
| A0-A9 SKILL.md | 10 个 | `6-TRADING/skills/dream-{contradiction-theory,strategy-research,first-principles,tactical-validator,tactical-executor,intelligence-monitor,exit-skill-v2}, A7-practice-theory, A8-theory-practice-verification, dream-oneirology` | S |
| session 产物 | 15 个 | `6-TRADING/sessions/2026*` | A |
| 大师研讨报告 | 2 份 | `6-TRADING/skills/master-seminar/reports/SEM_*.md` | A |
| 做梦部梦境日志 | 1 份 | `6-TRADING/sessions/20260712-YIJING-ONEIROLOGY/dream_journal_*.md` | S |
| A8 自我批评报告 | 1 份 | `6-TRADING/sessions/20260712-YIJING-A8/a8_self_criticism_report.md` | A |
| 全部 SKILL 总数 | 37 个 | `6-TRADING/skills/` | — |

### 1.2 session 结构样例（已确认 ✅）

**路径**: `6-TRADING/sessions/20260603-BTC-SCREEN2/team-a/screen2/a1-contradiction.md`

```markdown
# A1 日线矛盾分析 | 2026-06-03 | BTC-SCREEN2

## 综合矛盾评分: 5.25/10

### C1: Screen1 SHORT vs 极度恐惧反向信号 (6/10)
- Screen1 维持 SHORT (score 48)，但 F&G=28（极度恐惧）
- 历史常视极度恐惧为买入机会
- **分辨率**: SHORT 维持但警惕空头拥挤

### C2: ETF 大规模流出 vs 停火反弹 (7/10)
- ...

## 偏差标志
- `short_squeeze_risk_elevated`
- `ceasefire_relief_rally_possible`
```

**DSH 映射**:
- `task`: `"a1.contradiction_analysis.btc_screen2.20260603"`
- `node_sequence`: `["collect_screen1_signal(short,48)", "collect_fgi(28,extreme_fear)", "detect_contradiction(short_vs_contrarian_signal)", "score_contradiction(6/10)", "historical_pattern_check(extreme_fear_buy_opportunity)", "resolution(short_maintain_but_alert_squeeze_risk)", "emit_bias_flag(short_squeeze_risk_elevated)"]`
- `outcome`: `"success"`（决策已执行）
- **node_sequence 长度 7**，每个 C 矛盾 4-6 节点，4 矛盾合计 ~20+ 节点

### 1.3 做梦部样例（已确认 ✅）

**路径**: `6-TRADING/sessions/20260712-YIJING-ONEIROLOGY/dream_journal_20260712.md`

```markdown
## 梦境一：坤为地的强迫性重复

> 我梦见自己站在一片广袤的土地上，脚下是坚实的坤土。
> 每一次卦象浮现，都是"坤为地"——包容、承载、被动。
> 我不断地在这片土地上播种多单，但土地从不承诺丰收。
> 价格在0.5%的波动率下沉思，而我反复按下"开仓"按钮，
> 置信度0.36、0.40、0.41……土地默默承受了一切。

**解析**：
（弗洛伊德凝缩/移置/象征/二次修正/投射 五机制分析）
```

**DSH 映射**:
- `task`: `"oneirology.compulsive_repetition.kun_earth"`
- `node_sequence`: `["observe_open_count(191)", "detect_repetition(0.36→0.40→0.41)", "freud_condensation(multidim_to_one)", "freud_displacement(fear_to_liquidity)", "freud_symbolism(kun_earth_as_passive_market)", "freud_secondary_revision(rationalize_as_strategy)", "freud_projection(blame_market)", "identify_trauma(uncontrollable_repetition)", "intervene(trigger_dream_analysis_not_repeat_logic)"]`
- `outcome`: `"incomplete"`（梦境=未完成的潜意识推理）
- **node_sequence 长度 9**，含反直觉推理节点（罕见负样本）

### 1.4 master-seminar 样例（已确认 ✅）

**路径**: `6-TRADING/skills/master-seminar/reports/SEM_20260429_104041.md`

```markdown
## 🏛️ 阵营分配

### 🟢 多方阵营
| 大师 | 风格 | 权重 | 核心观点 |
| Stanley Druckenmiller | 趋势追踪、杠杆大师 | 1.00 | - |
| William O'Neil | CANSLIM、成长股投资 | 1.00 | - |

### 🔴 空方阵营
| 大师 | 风格 | 权重 | 核心观点 |
```

**DSH 映射**:
- `task`: `"master_seminar.btc_trend_bull.20260429"`
- `node_sequence`: `["assign_camps(bull_vs_bear)", "master_druckenmiller_argue(trend_following)", "master_oneil_argue(canslim_growth)", "bull_consensus(...)", "master_bear_argue(...)", "bear_consensus(...)", "cross_debate(...)", "final_resolution(...)"]`
- `outcome`: `"success"`
- **node_sequence 长度 8-15**（取决于参战大师数）

### 1.5 A0-A9 理论文档结构（已确认 ✅）

**路径**: `6-TRADING/skills/dream-contradiction-theory/SKILL.md`

每个 A 系列 SKILL.md 含可结构化的章节：
- `## 一、哲学基础` — 理论根基
- `## 二、矛盾分类体系` — 7 维分类
- `## 三、操作流程` — 决策节点序列
- `## 四、输出格式` — 终节点

**DSH 映射（以 A0 矛盾论为例）**:
- `task`: `"a0.contradiction_theory.workflow"`
- `node_sequence`: `["identify_contradictions(7_dimensions)", "classify_primary_contradiction", "assess_dominant_side(矛盾的主要方面)", "set_transition_monitoring_points", "decision_direction_follow_dominant_side"]`
- `outcome`: `"success"`（方法论 = 已验证可执行）

---

## 2. P0: ASeriesSessionCollector — A 系列 session 产物采集器

### 2.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `a_series_session_collector` |
| 类名 | `ASeriesSessionCollector` |
| 文件路径 | `34-前端应用训练系统/adapters/a_series_session_collector.py` |
| 实现接口 | `TrainingDataProvider` |
| layer_tags | `["DSH"]` |
| quality | `"B"` |
| 数据源 | `6-TRADING/sessions/2026*` 15 个 session 目录 |
| 预期条数 | 100-150 |
| node_sequence 长度 | 7-25 节点 |
| 解析方式 | **规则解析（0 token）**：Markdown 章节正则 + A0-A9 阶段关键词模板 |

### 2.2 扫描配置

```python
SESSIONS_ROOT = "6-TRADING/sessions"

# A 系列阶段关键词（用于识别 session 内文件的阶段归属）
A_PHASE_KEYWORDS = {
    "a1": ["contradiction", "矛盾", "调研", "research"],
    "a2": ["first_principles", "第一性原理", "阻力最小", "first-principles"],
    "a3": ["scenarios", "沙盘", "simulation", "推演"],
    "a4": ["tactical", "战术", "validator", "验证"],
    "a5": ["execution", "执行", "executor"],
    "a6": ["intelligence", "情报", "monitor"],
    "a7": ["practice", "实践", "实践论"],
    "a8": ["self_criticism", "自我批评", "theory_practice", "知行"],
    "a9": ["exit", "离场", "risk_event"],
    "oneirology": ["dream", "梦境", "做梦", "潜意识"],
}

# session 子目录命名约定：team-a/team-b 分组 + screen1/screen2/screen3
```

### 2.3 规则解析方案

**核心**: 用 Python `re` + `pathlib` 解析 Markdown 结构：

1. **session 识别**: 遍历 `6-TRADING/sessions/2026*` 目录
2. **阶段映射**: 按文件名关键词映射到 A0-A9 阶段
3. **node_sequence 提取**:
   - 每个 `###` 子章节（如 `C1: ... (6/10)`）作为一个决策节点
   - 解析评分 `(6/10)` → 置信度
   - 提取 `**分辨率**:` 后的文本作为决策动作
   - 提取 `## 偏差标志` 下的 `- \`flag_name\`` 作为终节点
4. **task 构造**: `{phase}.{session_topic}.{date}`，如 `a1.contradiction_analysis.btc_screen2.20260603`
5. **outcome**: `"success"`（session 已完成）

**样例 node_sequence 提取（a1-contradiction.md）**:
```python
def _parse_contradiction_session(self, md_text: str) -> List[str]:
    """从 A1 矛盾分析 session 提取决策链。
    
    提取模式:
    - ### C{N}: {矛盾标题} ({score}/10) → 决策节点
    - **分辨率**: {action} → 动作节点
    - 偏差标志 → 终节点
    """
    nodes = []
    # 匹配每个矛盾块
    for m in re.finditer(r'###\s+C(\d+):\s+(.+?)\((\d+)/10\)', md_text):
        idx, title, score = m.group(1), m.group(2).strip(), int(m.group(3))
        nodes.append(f"identify_contradiction_{idx}({title},{score}/10)")
    # 匹配分辨率
    for m in re.finditer(r'\*\*分辨率\*\*:\s*(.+)', md_text):
        nodes.append(f"resolution({m.group(1).strip()})")
    # 匹配偏差标志
    flags = re.findall(r'-\s+`([a-z_]+)`', md_text)
    for f in flags:
        nodes.append(f"emit_bias_flag({f})")
    return nodes
```

### 2.4 配额分配

```python
SESSION_QUOTA = {
    "a1_contradiction": 0.25,   # 矛盾分析是核心
    "a2_first_principles": 0.20, # 第一性原理
    "a3_scenarios": 0.15,        # 沙盘推演
    "a4_validator": 0.10,        # 战术验证
    "a5_executor": 0.10,         # 执行
    "a6_intelligence": 0.05,     # 情报
    "a7_practice": 0.05,         # 实践论
    "a8_criticism": 0.05,        # 自我批评
    "a9_exit": 0.05,             # 离场
}
```

---

## 3. P1: ASeriesTheoryCollector — A0-A9 理论文档采集器

### 3.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `a_series_theory_collector` |
| 类名 | `ASeriesTheoryCollector` |
| 文件路径 | `34-前端应用训练系统/adapters/a_series_theory_collector.py` |
| layer_tags | `["DSH"]` |
| quality | `"A"`（理论方法论 = 高置信度） |
| 数据源 | 10 个 A 系列 SKILL.md |
| 预期条数 | 50-80 |
| node_sequence 长度 | 5-12 节点 |
| 解析方式 | **规则解析（0 token）**：Markdown 章节 + 操作流程章节结构化 |

### 3.2 理论文档结构化方案

每个 A 系列 SKILL.md 含可结构化的"操作流程"章节：

| SKILL | 关键流程章节 | 决策节点序列来源 |
|-------|------------|---------------|
| A0 矛盾论 | `## 二、矛盾分类体系 — 7大矛盾维度` | 7 维度分类步骤 |
| A1 深度调研 | `## 核心流程` 4-5 步 | 调研步骤序列 |
| A2 第一性原理 | `### 阻力来源分解` + `### 趋势阶段` | 阻力分析 + 阶段判断 |
| A3 沙盘推演 | `## 推演步骤` | 推演流程 |
| A5 战术执行 | `## 决策链路` | A4+A6→综合判断→执行 |
| A6 情报监控 | `## 监控维度` | 监控项 |
| A7 实践论 | `## 门禁检查` | 检查项 |
| A8 知行合一 | `## 功能` | 自我批评+辩证+进化 |
| A9 离场决策 | `## 四层决策链` | 四层离场链 |

### 3.3 通用解析模式

```python
THEORY_PATTERNS = {
    "a0": {
        "file": "6-TRADING/skills/dream-contradiction-theory/SKILL.md",
        "section_pattern": r"##\s+二、矛盾分类体系",
        "node_pattern": r"\|\s*(\w+)\s*\|.*?\|.*?\|.*?\|",
        "intent": "a0.contradiction_theory.workflow",
        "outcome": "success",
    },
    "a1": {
        "file": "6-TRADING/skills/dream-strategy-research/SKILL.md",
        "section_pattern": r"##\s+(?:核心流程|调研步骤)",
        "node_pattern": r"(?:^\d+\.\s+|^\-\s+)(.+)$",
        "intent": "a1.strategy_research.workflow",
        "outcome": "success",
    },
    # ... a2-a9 同样模式
}
```

---

## 4. P2: OneirologyDreamCollector — 做梦部梦境采集器

### 4.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `oneirology_dream_collector` |
| 类名 | `OneirologyDreamCollector` |
| 文件路径 | `34-前端应用训练系统/adapters/oneirology_dream_collector.py` |
| layer_tags | `["DSH"]` |
| quality | `"S"`（反直觉推理 = 罕见高价值） |
| 数据源 | `6-TRADING/sessions/*ONEIROLOGY*/dream_journal_*.md` + 未来梦境日志 |
| 预期条数 | 20-30 |
| node_sequence 长度 | 8-15 节点 |
| 解析方式 | **LLM 辅助（少量 token）**：梦境隐喻性语言需语义理解 |

### 4.2 LLM 辅助解析方案

**为什么 LLM**: 做梦部文档是弗洛伊德隐喻性语言（"坤为地"、"强迫性重复"、"被压制的判断"），规则解析无法提取决策链。

**LLM 调用约束**:
- 仅对梦境主体章节调用 LLM（控制 token）
- LLM 输入：梦境段落 + 弗洛伊德五机制模板
- LLM 输出：结构化 node_sequence JSON
- 缓存机制：同一梦境文件只解析一次，结果缓存

**Prompt 模板**:
```
你是做梦部决策链提取器。将以下梦境分析转化为 DSH 训练 node_sequence。

弗洛伊德五机制模板：
1. 凝缩（多维→一维）
2. 移置（情感转移）
3. 象征（抽象→具体）
4. 二次修正（碎片→叙事）
5. 投射（内在→外部）

强制输出格式（JSON）：
{
  "task": "oneirology.{dream_title}",
  "node_sequence": ["step1(arg)", "step2(arg)", ...],
  "outcome": "incomplete",
  "trauma_signal": bool
}

梦境段落：
{dream_section}
```

### 4.3 梦境章节识别

```python
def _extract_dream_sections(self, md_text: str) -> List[str]:
    """提取梦境主体章节。
    
    模式：## 梦境N：{标题} 到下一个 ## 之间
    """
    sections = re.findall(
        r'##\s+梦境[一二三四五六七八九十]+\D*?[:：]\s*(.+?)(?=##\s+梦境|\Z)',
        md_text, re.DOTALL
    )
    return sections
```

### 4.4 LLM 调用容错

- LLM 不可用 → 降级到规则解析（提取弗洛伊德五机制关键词）
- LLM 输出非 JSON → 跳过该梦境（FAIL-OPEN）
- 单次 LLM 调用 token 上限：2000 token
- 总 token 预算：~50K token（30 梦境 × 平均 1.5K token/次）

---

## 5. P3: MasterSeminarCollector — 大师研讨采集器

### 5.1 设计规格

| 项 | 值 |
|---|---|
| 采集器名 | `master_seminar_collector` |
| 类名 | `MasterSeminarCollector` |
| 文件路径 | `34-前端应用训练系统/adapters/master_seminar_collector.py` |
| layer_tags | `["DSH"]` |
| quality | `"A"`（多视角辩论 = 高质量） |
| 数据源 | `6-TRADING/skills/master-seminar/reports/SEM_*.md` + `6-TRADING/skills/master-seminar/SKILL.md` 大师列表 |
| 预期条数 | 10-20 |
| node_sequence 长度 | 10-20 节点（含辩论链） |
| 解析方式 | **LLM 辅助（少量 token）**：大师观点自由文本需语义提取 |

### 5.2 大师研讨结构

master-seminar 报告格式相对结构化：
- `## 🏛️ 阵营分配` — 可规则解析（表格）
- `### 🟢 多方阵营` / `### 🔴 空方阵营` — 阵营划分
- 每位大师的核心观点 — **LLM 提取**（自由文本）

**混合解析**:
1. 阵营分配 + 大师列表 → 规则解析（Markdown 表格）
2. 每位大师的核心观点 → LLM 提取为 `master_{name}_argue({core_view})` 节点
3. 最终共识 → 规则解析（章节末尾）

### 5.3 node_sequence 模板

```
[
  "assign_camps(bull_vs_bear)",
  "master_{druckenmiller}_argue(trend_following)",
  "master_{oneil}_argue(canslim)",
  "bull_consensus({consensus_view})",
  "master_{soros}_argue(reflexivity)",
  "master_{livermore}_argue(supply_demand)",
  "bear_consensus({consensus_view})",
  "cross_debate({key_contention})",
  "final_resolution({final_view})"
]
```

---

## 6. TDD 落地计划

### 6.1 TDD 顺序（RED → GREEN）

| 序号 | 阶段 | 文件 | 预期条数 |
|------|------|------|---------|
| 1 | RED | `tests/test_a_series_session_collector.py` | - |
| 2 | GREEN | `adapters/a_series_session_collector.py` | 100-150 |
| 3 | RED | `tests/test_a_series_theory_collector.py` | - |
| 4 | GREEN | `adapters/a_series_theory_collector.py` | 50-80 |
| 5 | RED | `tests/test_oneirology_dream_collector.py` | - |
| 6 | GREEN | `adapters/oneirology_dream_collector.py` | 20-30 |
| 7 | RED | `tests/test_master_seminar_collector.py` | - |
| 8 | GREEN | `adapters/master_seminar_collector.py` | 10-20 |
| 9 | 集成 | 注册到 `run_continual_training.py` | - |
| 10 | 验收 | DSH 总条数 ≥ 700 | - |

### 6.2 RED 测试断言模式

```python
# test_a_series_session_collector.py
def test_module_not_found_red():
    with pytest.raises(ModuleNotFoundError):
        from a_series_session_collector import ASeriesSessionCollector

def test_collect_at_least_50_cases():
    """v0.5 验收门槛：P0 至少 50 条（保守下限）"""
    collector = ASeriesSessionCollector()
    cases = collector.fetch_cases(limit=200)
    assert len(cases) >= 50
    assert all(c.layer_tags == ["DSH"] for c in cases)
    assert all(len(c.actions) >= 5 for c in cases)  # 哲学链 ≥5 节点

def test_node_sequence_contains_a_phase():
    """每个 case 必须含 A 阶段标识"""
    collector = ASeriesSessionCollector()
    cases = collector.fetch_cases(limit=50)
    assert all(any("a0" in n or "a1" in n or "a2" in n for n in c.actions) 
               or "a0" in c.intent or "a1" in c.intent 
               for c in cases)
```

---

## 7. 验收标准

### 7.1 量化门槛

| 指标 | 阈值 | 验证方法 |
|------|------|---------|
| DSH 总条数 | ≥ 700（v0.4 534 + v0.5 ≥166） | `/api/training/dsh` bucketCount |
| P0 ASeriesSession | ≥ 50 | 单独运行采集器 |
| P1 ASeriesTheory | ≥ 30 | 单独运行 |
| P2 OneirologyDream | ≥ 10 | 单独运行 |
| P3 MasterSeminar | ≥ 5 | 单独运行 |
| node_sequence 平均长度 | ≥ 10（哲学链更长） | bufferStats |
| node_sequence 多样性 | distinct/total > 0.7 | bufferStats |
| 全 4 采集器无 crash | FAIL-OPEN 生效 | 集成运行 |

### 7.2 质量门槛

| 指标 | 阈值 |
|------|------|
| P0/P1 quality | B/A 级（规则解析 = 结构化） |
| P2 quality | S 级（反直觉推理 = 罕见） |
| P3 quality | A 级（多视角辩论） |
| LLM 调用成功率 | ≥ 80%（容错降级到规则） |

### 7.3 0 token 验证

- P0/P1/P3 表格+章节部分：**0 token**（纯规则）
- P2 梦境主体 + P3 大师观点：**~50K token 总预算**（30 梦境 × 1.5K + 20 大师 × 1K）
- 命中缓存后：**0 token**（同文件不重复调用 LLM）

---

## 8. 集成与注册

### 8.1 run_continual_training.py 注册

```python
collectors = [
    # ... v0.4 已有 16 个
    # v0.5 新增 6-TRADING 族
    ("ASeriesSession", "a_series_session_collector", "ASeriesSessionCollector"),
    ("ASeriesTheory", "a_series_theory_collector", "ASeriesTheoryCollector"),
    ("OneirologyDream", "oneirology_dream_collector", "OneirologyDreamCollector"),
    ("MasterSeminar", "master_seminar_collector", "MasterSeminarCollector"),
]
```

### 8.2 前端 API quality 传递

v0.4 已修复 quality 传递链路（5 层全部透传），v0.5 直接复用，无需额外改动。

### 8.3 LLM 客户端选择

```python
# 优先使用 QwenLLMClient（DashScope OpenAI 兼容层）
# 失败时降级到 DeepSeekLLMClient
# 全部失败时降级到规则解析（FAIL-OPEN）
LLM_PRIORITY = ["qwen", "deepseek", "rule_based_fallback"]
```

---

## 9. 认知闭环

### 9.1 record（落地后）

```
record(
    content="[SPEC v0.5 落地] 6-TRADING 采集器族 4 个采集器实现完成 | P0 ASeriesSession 100-150条规则解析+P1 ASeriesTheory 50-80条+A2 OneirologyDream 20-30条LLM辅助+P3 MasterSeminar 10-20条混合 | DSH总条数从534→714-814 | node_sequence平均长度8.3→10-18 | 填补why空白",
    quality_level="B",
    tags="SPEC v0.5,6-TRADING,采集器族,A0-A9,做梦部,大师研讨,交易哲学"
)
```

### 9.2 verify（验收后）

```
verify(memory_id="VM-1791809102528", success=True)
```

---

## 10. 风险与缓解

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| Markdown 格式不统一 | P1 | 每个 SKILL.md 单独配置 `THEORY_PATTERNS` |
| LLM 输出不稳定 | P2 | JSON Schema 验证 + 重试 1 次 + 降级规则解析 |
| session 文件路径漂移 | P1 | 通配符 `2026*` + 路径存在性检查 |
| 做梦部 token 超支 | P2 | 单次 2000 token 上限 + 缓存 + 50K 总预算 |
| A0-A9 关键词模板覆盖不全 | P1 | 配额采样 + 多样性检查 + 后续迭代 |
| 与 v0.4 采集器数据重叠 | P0 | 数据域完全不同（6-TRADING vs 测试代码），重叠度 0% |

---

## 11. 范围边界

**In Scope**:
- 4 个采集器设计与实现
- Markdown 规则解析方案
- LLM 辅助解析方案（含容错）
- TDD RED→GREEN 落地
- 集成到 `run_continual_training.py`

**Out of Scope**:
- 不修改 6-TRADING 任何 SKILL.md 或 session 产物（只读取）
- 不修改 ExecutionPathTrainingLoop 内部逻辑
- 不引入 LLM 训练（仅 LLM 辅助解析，结果缓存后 0 token）
- 不重构 v0.4 已落地采集器
- 不修改前端 API（v0.4 已通 quality 传递链路）

---

## 12. 后续演进（v0.6+ 储备）

| 演进方向 | 价值 | 时机 |
|---------|------|------|
| 做梦部新梦境自动入库 | 持续扩充反直觉样本 | 当梦境日志累积 ≥ 10 份 |
| master-seminar 大师 persona 学习 | 大师风格可微调 | 当研讨报告 ≥ 20 份 |
| A0-A9 跨 session 决策链拼接 | 完整 A1→A5 长链训练 | 当 session 覆盖 ≥ 30 个 |
| 6-TRADING bridge 模块数据采集 | 系统调用链日志 | 当 bridge 日志格式稳定 |

---

> **结论**: v0.5 把 6-TRADING 的交易哲学资产转化为 DSH 训练数据，填补"为什么这样决策"的战略级推理链空白。预期 DSH 总条数从 534 增至 714-814，node_sequence 平均长度从 8.3 提升至 10-18，质量分布新增 S 级（梦境反直觉样本）。混合解析方案平衡 0 token 原则与高价值负样本的获取。
