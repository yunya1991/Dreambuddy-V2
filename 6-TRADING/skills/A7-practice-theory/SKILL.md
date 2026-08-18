
### 投递后验证（强制调用AD SKILL）

完成秘书邮箱投递后，必须调用 `artifact-alignment-manager` SKILL 执行双通道验证：

1. **调用方式**: 触发词「产物投递验证」或加载 `artifact-alignment-manager` SKILL
2. **验证内容**:
   - ✅ 秘书邮箱文件存在 + frontmatter完整（含 tags, by_a_phase）
   - ✅ 前端产物中心文件存在（`~/.workbuddy/artifacts/trading/`）
   - ✅ `index.json` 已更新（含 `chain_phase` + `tags`）
   - ✅ 前端详情页返回 200
3. **不通过**: 按 AD SKILL 第四章步骤修复，重新验证
4. **通过**: 投递完成

> ⚠️ 没有 AD SKILL 验证通过 = 投递未完成


---
name: "A7-practice-theory"
description: "📘 实践论SKILL - 基于毛泽东《实践论》的交易实践指导框架。为A4(战术验证)和A5(战术执行)提供系统的实践论指导，建立'实践→认识→实践'的完整闭环。触发词：实践论、实践指导、认识来源、真理标准、实践验证、认识修正、反馈循环、复盘反思"
version: "2.1 (正式上线版)"
created: "2026-04-26"
updated: "2026-04-29"
status: "已上线运行"
---

## 【合规要求】⭐ v2.1 新增

### §合规 问题处理流程

> ⚠️ **合规约束**: 遇到任何问题必须按以下顺序处理：

```
遇到问题
    ↓
Step 1️⃣ 查FAQ
  → WORKSPACE/.workbuddy/faq/OKX_FAQ.md（OKX相关）
  → WORKSPACE/.workbuddy/faq/技术_FAQ.md（技术相关）
  → WORKSPACE/.workbuddy/faq/运营_FAQ.md（运营相关）
    ↓ 有解 → 执行 ✓
    ↓ 无解 → Step 2

Step 2️⃣ 查治理文档
  → ~/.workbuddy/skills/dream-governance-manager/governance_docs/
    ↓ 有解 → 执行 + 补充FAQ ✓
    ↓ 无解 → Step 3

Step 3️⃣ 联网搜索
  → 使用 tavily/agent-reach 搜索
    ↓ 有解 → 执行 + 归档经验 ✓
    ↓ 无解 → Step 4

Step 4️⃣ 自主分析
    ↓ 有解 → 执行 + 输出报告 + 归档 ✓
    ↓ 无解 → 升级处理
```

### §合规 常见问题索引

| 问题类型 | FAQ位置 | 备注 |
|:---|:---|:---|
| OKX API错误 | `faq/OKX_FAQ.md` | CLI命令/API签名 |
| 账户查询问题 | `faq/OKX_FAQ.md` | 权限/配置文件 |
| 技术实现问题 | `faq/技术_FAQ.md` | 脚本/工具问题 |
| 流程协作问题 | `faq/运营_FAQ.md` | 制度/规范问题 |
| 合规判定问题 | `dream-governance-manager/` | 治理文档 |

### §合规 违规处理

| 违规类型 | 判定条件 | 处罚 |
|:---|:---|:---|
| 跳步违规 | 未查FAQ直接联网/分析 | 记过一次 |
| FAQ缺失 | 问题存在但未查阅 | 警告 |
| 归档缺失 | 问题解决但未归档 | 记录 |

---

# 📘 A7 实践论SKILL v2.1 - 交易实践指导框架 (正式上线版)

## 📢 上线声明

**上线时间**: 2026-04-26  
**创建者**: WorkBuddy AI Agent  
**应用对象**: A4(战术验证) + A5(战术执行)  
**核心目标**: 建立"实践→认识→实践"的完整闭环  

## 🔗 与A4-A5集成状态

### ✅ 集成已完成
- ✅ A4 (dream-tactical-validator) 已集成A7门禁检查
- ✅ A5 (dream-tactical-executor) 已集成A7门禁检查
- ✅ A4/A5执行前必须通过A7门禁检查

### 📋 集成点详情
- **A4调用A7**: 在Step 0之前，执行A7门禁检查（4项检查）
- **A5调用A7**: 在Step 1之前，执行A7门禁检查（5项检查）
- **门禁结果处理**: PASS→继续；FAIL→返回重新验证

## 📊 监控与复盘机制

### ✅ 已建立机制
- ✅ A7实践论应用监控机制 (monitoring/a7_monitoring.md)
- ✅ A7实践论复盘机制 (review/a7_review_mechanism.md)
- ✅ 每日/每周/每月/事件驱动复盘
- ✅ 监控指标和报告模板

### 📅 自动化时间表
- **每日监控**: 23:59 自动执行
- **每周复盘**: 周日 20:00
- **每月复盘**: 月末最后一个周日 20:00
- **事件驱动复盘**: 重大事件后即时

## 🎯 核心功能

### 1. A7门禁检查
| 检查类型 | 检查项 | 数量 |
|:---|:---|:---:|
| A4门禁检查 | 认识来源充分性/验证设计合理性/反馈机制完整性/真理标准明确性 | 4项 |
| A5门禁检查 | 验证充分性/认识正确性/执行纪律/风险可控/反馈机制 | 5项 |

### 2. 实践日志记录
| 日志类型 | 模板文件 | 用途 |
|:---|:---|:---|
| A4实践日志 | templates/practice_log.json | 记录A4验证过程 |
| A5实践报告 | templates/practice_report.json | 记录A5执行结果 |
| 真理验证 | templates/truth_verification.json | 验证实践结果 |

### 3. 复盘机制
| 复盘类型 | 频率 | 参与者 |
|:---|:---:|:---|
| 每日复盘 | 每天 | A4/A5执行者 |
| 每周复盘 | 每周 | A1-A5团队 |
| 每月复盘 | 每月 | A1-A6 + 用户 |
| 事件驱动复盘 | 即时 | A1-A6 + 用户 |

## 📁 完整文件结构

```
/Users/zhangjiangtao/.workbuddy/skills/A7-practice-theory/
├── ✅ SKILL.md (主入口，v2.0正式上线版)
├── ✅ theory/practice_theory_core.md (实践论核心思想)
├── ✅ workflows/recognize_stage.md (A1-A3认识阶段)
├── ✅ workflows/practice_verify.md (A4实践验证)
├── ✅ workflows/practice_execute.md (A5实践执行)
├── ✅ workflows/practice_reflect.md (复盘反思)
├── ✅ templates/practice_log.json (A4实践日志)
├── ✅ templates/practice_report.json (A5实践报告)
├── ✅ templates/truth_verification.json (真理验证)
├── ✅ references/application_cases.md (应用案例)
├── ✅ gates/a7_practice_gate.py (门禁检查实现)
├── ✅ monitoring/a7_monitoring.md (监控机制)
├── ✅ review/a7_review_mechanism.md (复盘机制)
├── ⏳ test_cases/ (测试案例)
│   ├── a7_gate_test_case_001.md
│   └── complete_test_data.json
└── ⏳ gates/ (门禁检查脚本)
    ├── a7_practice_gate.py
    ├── test_a7_gate.py
    └── simple_test.py
```

## 🚀 上线后工作计划

### 第一阶段：磨合期 (1-2周)
1. 在实际A4-A5执行中测试A7门禁检查
2. 收集A7门禁检查通过率数据
3. 优化A7门禁检查逻辑
4. 完善实践日志记录

### 第二阶段：优化期 (2-4周)
1. 分析A7门禁检查失败原因
2. 优化A7门禁检查算法
3. 建立A7实践论应用最佳实践
4. 完善监控和复盘机制

### 第三阶段：稳定期 (1个月后)
1. A7实践论SKILL稳定运行
2. 实践→认识→实践循环顺畅
3. A4-A5执行质量持续提升
4. 系统自我进化能力增强

---

## 📊 A7实践论SKILL - 项目总结

### 项目周期
- **Phase 1: 理论准备** (已完成) - 创建A7 SKILL基础结构
- **Phase 2: A4-A5集成** (已完成) - 修改A4/A5增加A7调用点
- **Phase 3: 测试验证** (基本完成) - 创建测试案例和脚本
- **Phase 4: 上线运行** (已完成) - 建立监控和复盘机制

### 项目成果
1. ✅ **完整SKILL结构** -  theory/workflows/templates/references
2. ✅ **A4-A5集成** - 门禁检查点已嵌入执行流程
3. ✅ **门禁检查实现** - a7_practice_gate.py
4. ✅ **监控机制** - 5个核心指标 + 日报/周报
5. ✅ **复盘机制** - 4种复盘类型 + 完整流程

### 项目价值
1. **解决根本问题** - A4-A5实践缺乏系统理论指导
2. **建立实践闭环** - 实践→认识→实践循环
3. **提升执行质量** - 门禁检查确保实践质量
4. **系统自我进化** - 复盘机制推动持续改进

---

*最后更新: 2026-04-26*
*状态: 已上线运行*
*版本: v2.0 (正式上线版)*

# 📘 A7 实践论SKILL v1.1 - 交易实践指导框架 (集成版)

## 🔗 与A4-A5集成说明 (v1.1新增)

### 集成完成状态
- ✅ A4 (dream-tactical-validator) 已集成A7门禁检查
- ✅ A5 (dream-tactical-executor) 已集成A7门禁检查
- ✅ A4/A5执行前必须通过A7门禁检查

### A4调用A7方式
```
A4执行流程:
1. 【A7实践论门禁检查】⚠️ (新增)
   - 调用: use_skill a7-practice-theory
   - 读取: A7-practice-theory/workflows/practice_verify.md
   - 执行: A7门禁检查 (认识来源/验证设计/反馈机制/真理标准)
   - 结果: PASS → 继续; FAIL → 返回A1-A3

2. 【原有流程】Step 0: trading邮箱检查
3. ...
```

### A5调用A7方式
```
A5执行流程:
1. 【A7实践论门禁检查】⚠️ (新增)
   - 调用: use_skill a7-practice-theory
   - 读取: A7-practice-theory/workflows/practice_execute.md
   - 执行: A7门禁检查 (验证充分性/认识正确性/执行纪律/风险可控/反馈机制)
   - 结果: PASS → 继续; FAIL → 返回A4重新验证

2. 【原有流程】Step 1: 仓位决策
3. ...
```

### A7门禁检查内容

**A4门禁检查项**:
1. 认识来源充分性 (A1-A3报告是否完整?)
2. 验证设计合理性 (小仓试探方案是否可行?)
3. 反馈机制完整性 (是否有实践日志记录?)
4. 真理标准明确性 (P&L/胜率/回撤标准是否明确?)

**A5门禁检查项**:
1. 验证充分性 (A4验证样本≥3-5次?)
2. 认识正确性 (A4反馈是否修正了认识?)
3. 执行纪律 (是否有明确的执行纪律和止损?)
4. 风险可控 (实践风险是否在可接受范围?)
5. 反馈机制 (是否有实时反馈机制?)

### A5门禁独立验证 (v2.1 新增 PROP_A8_002) ⚡

> **核心问题**: 原A7门禁由A5自我评分(5/5 PASS)，等于"自己考自己"。
> **修复方案**: 增加独立数据验证环节，从Episode/历史数据中自动提取证据，替代A5主观评分。

**独立验证逻辑**:
```python
def a7_independent_verification():
    """A7门禁独立验证 — 从Episode/历史数据自动验证"""
    
    # 读取最近episodes
    episodes = read_recent_episodes(hours=4)  # 最近4h的episode
    
    verification_results = {
        "验证充分性": {
            "self_score": None,     # A5自评分(不再采信)
            "evidence": None,       # 独立证据
            "auto_pass": None,      # 自动验证结果
            "check": lambda: len([e for e in episodes 
                if e.get("a4_scout") is not None]) >= 1
            # 检查: 最近4h有无A4侦察报告
        },
        "认识正确性": {
            "self_score": None,
            "evidence": None,
            "auto_pass": None,
            "check": lambda: any(
                e.get("recognition_correction") for e in episodes)
            # 检查: Episode中是否有认识修正记录
        },
        "执行纪律": {
            "self_score": None,
            "evidence": None,
            "auto_pass": None,
            "check": lambda: all(
                e.get("sl_trigger") is not None for e in episodes 
                if e.get("position"))
            # 检查: 所有持仓episode是否有止损设置
        },
        "风险可控": {
            "self_score": None,
            "evidence": None,
            "auto_pass": None,
            "check": lambda: all(
                float(e.get("unrealized_pnl_pct", 0)) > -5 
                for e in episodes if e.get("position"))
            # 检查: 所有episode浮亏是否在5%以内
        },
        "反馈机制": {
            "self_score": None,
            "evidence": None,
            "auto_pass": None,
            "check": lambda: len(episodes) > 0
            # 检查: 最近4h有无episode记录(反馈=有记录)
        }
    }
    
    # 执行自动验证
    for item, data in verification_results.items():
        data["auto_pass"] = data["check"]()
        data["evidence"] = f"基于{len(episodes)}个episode自动验证"
    
    # 独立验证结果
    all_pass = all(d["auto_pass"] for d in verification_results.values())
    return {
        "verification_type": "INDEPENDENT_AUTO",
        "all_pass": all_pass,
        "details": verification_results,
        "note": "A5自评分不再作为门禁依据，仅使用Episode/历史数据自动验证"
    }
```

**关键规则**:
1. **A5自评分降级为参考**: A7门禁不再采信A5自我评分，改为自动验证
2. **Episode即证据**: episodes/目录中的JSON记录是门禁验证的唯一数据源
3. **4小时窗口**: 检查最近4h的episode数据（与A5报告新鲜度一致）
4. **无Episode=FAIL**: 如果最近4h无任何episode记录，门禁自动FAIL
5. **止损必检**: 执行纪律的验证核心是"所有持仓是否有止损"，无止损=FAIL

---

## 核心思想

# 📘 A7 实践论SKILL - 交易实践指导框架

## 核心思想

> "通过实践而发现真理，又通过实践而证实真理和发展真理。" — 毛泽东《实践论》

本SKILL蒸馏毛泽东《实践论》的核心思想，为Dream-MultiSkill系统提供系统的实践指导框架，重点解决A4(战术验证)和A5(战术执行)中的实践问题。

## 实践论核心原理

### 1. 实践第一性
**原理**: 人的认识，主要地依赖于物质的生产活动，逐渐地了解自然现象、自然性质、自然的规律性。

**交易应用**:
- 所有战略/策略必须经过市场验证（A4小仓试探）
- 禁止纯理论决策，必须"实践→认识→实践"
- 市场认知来自实际操作反馈，不是纸上谈兵

### 2. 认识来源于实践
**原理**: 认识从实践发生，以实践为基础。

**交易应用**:
- A1-A3的战略制定必须基于历史实践数据
- 市场环境变化 → 重新实践验证 → 修正认识
- 避免"本本主义"：不盲目依赖历史规律

### 3. 实践→认识→实践 (螺旋上升)
**原理**: 实践、认识、再实践、再认识，这种形式，循环往复以至无穷。

**交易应用**:
```
A1-A3 (认识) → A4 (实践验证) → 认识修正 → A5 (实践执行) → 复盘 (新认识) → ...
```

### 4. 真理的标准是实践
**原理**: 只有人们的社会实践，才是人们对于外界认识的真理性的标准。

**交易应用**:
- P&L和胜率是唯一评判标准
- 策略正确性必须由市场结果验证
- 避免"我认为正确"的主观判断

### 5. 改造世界是目的
**原理**: 马克思主义哲学认为十分重要的问题，不在于懂得了客观世界的规律性，因而能够解释世界，而在于拿了这种对于客观规律性的认识去能动地改造世界。

**交易应用**:
- 盈利是最终目标，不是分析本身
- A5执行是改造市场的实践，不是纸上谈兵
- 所有分析必须可执行、可验证

## A4-A5实践指导框架

### A4战术验证 - 实践验证阶段

**实践论指导**: 认识 → 实践 → 验证

**A7门禁检查 (A4执行前)**:
```python
def a7_a4_practice_gate():
    gates = {
        "认识来源": "A1-A3是否有充分调研? 认识是否来源于实践?",
        "验证设计": "小仓试探方案是否合理? 是否有明确验证标准?",
        "反馈机制": "是否有明确的反馈收集计划? 如何修正认识?",
        "真理标准": "是否定义了成功的评判标准? (P&L/胜率/回撤)",
        "实践纪律": "是否准备了实践记录? (实践日志模板)"
    }
    return evaluate_gates(gates)
```

**A4实践日志模板** (`practice_log_A4.json`):
```json
{
  "episode_id": "A4_20260426_01",
  "recognition": "A1-A3战略认识",
  "practice_design": "小仓试探方案",
  "practice_result": "实践结果 (P&L/胜率)",
  "recognition_correction": "认识修正",
  "truth_verification": "真理验证 (是否达到成功标准)",
  "next_action": "进入A5 / 重新A1-A3 / 调整策略"
}
```

### A5战术执行 - 实践执行阶段

**实践论指导**: 实践 → 新认识 → 再实践

**A7门禁检查 (A5执行前)**:
```python
def a7_a5_practice_gate():
    gates = {
        "验证充分": "A4验证是否充分? 是否有足够样本?",
        "认识正确": "A4反馈是否修正了认识? 认识是否符合当前市场?",
        "执行纪律": "是否有明确的执行纪律和止损? 改造世界需要纪律",
        "风险可控": "实践风险是否在可接受范围? 实践是具体的",
        "反馈机制": "是否有实时反馈机制? 能否根据实践调整?"
    }
    return evaluate_gates(gates)
```

**A5实践执行报告模板** (`practice_report_A5.json`):
```json
{
  "episode_id": "A5_20260426_01",
  "a4_verification": "A4验证结果摘要",
  "practice_execution": "A5执行记录 (入场/止损/止盈/平仓)",
  "real_time_feedback": "实时市场反馈",
  "recognition_update": "认识更新 (基于A5实践)",
  "truth_verification": "真理验证 (P&L结果)",
  "reflection_required": "是否需要复盘? 复盘重点?"
}
```

## 实践反馈循环

### 完整闭环: 实践→认识→实践

```
┌─────────────────┐
│                 A1-A3 (认识阶段)                 │
│  调查研究 → 矛盾分析 → 战略制定 → 形成认识      │
└─────────────────┘
                        ↓
┌─────────────────┐
│                 A4 (实践验证)                    │
│  小仓试探 → 收集反馈 → 验证认识 → 修正认识      │
└─────────────────┘
                        ↓
┌─────────────────┐
│                 A5 (实践执行)                    │
│  大仓执行 → 实时调整 → 获得结果 → 新认识        │
└─────────────────┘
                        ↓
┌─────────────────┐
│                 复盘 (反思阶段)                   │
│  结果分析 → 认识正确性 → 理论修正 → 新认识       │
└─────────────────┘
                        ↓
              (回到A1-A3，螺旋上升)
```

## 常见实践错误与纠正

### 错误1: 理论脱离实际
**表现**: A1-A3分析完美，但A4验证失败
**实践论诊断**: 认识来源于书本，不是实践
**纠正**: 强制A4小仓验证，禁止未验证进入A5

### 错误2: 实践不充分就执行
**表现**: A4只验证1-2次就进入A5
**实践论诊断**: 实践样本不足，认识不牢固
**纠正**: A4门禁检查，要求最小验证样本数

### 错误3: 实践后不反思
**表现**: A5执行后无复盘，重复错误
**实践论诊断**: 没有"再认识"环节，认识不发展
**纠正**: 强制A5后复盘，写入实践日志

### 错误4: 主观真理标准
**表现**: "我认为市场会涨"代替P&L验证
**实践论诊断**: 真理标准不是实践，是主观
**纠正**: 强制P&L和胜率作为唯一标准

## 使用指南

### 触发条件
1. A4战术验证前 - 调用A7门禁检查
2. A5战术执行前 - 调用A7门禁检查
3. A5执行后 - 生成实践报告
4. 定期复盘 - 调用A7反思工作流

### 与其他SKILL的关系
- **A0矛盾论**: 分析工具（认识世界）→ A7提供实践指导（改造世界）
- **A1-A3**: 认识阶段 → A7提供认识方法论
- **A4**: 实践验证 → A7提供验证框架
- **A5**: 实践执行 → A7提供执行纪律
- **A6情报**: 实践环境监测 → A7提供环境与实践的关系指导

### 文件结构
```
A7-practice-theory/
├── SKILL.md                    # 本文件 (主入口)
├── theory/
│   ├── practice_theory_core.md  # 实践论核心思想详解
│   ├── apply_to_trading.md      # 交易应用指南
│   └── dialectical_materialism.md # 辩证唯物主义基础
├── workflows/
│   ├── recognize_stage.md       # 认识阶段工作流 (A1-A3)
│   ├── practice_verify.md       # 实践验证工作流 (A4)
│   ├── practice_execute.md      # 实践执行工作流 (A5)
│   └── practice_reflect.md      # 实践反思工作流 (复盘)
├── templates/
│   ├── practice_log.json        # 实践日志模板 (A4用)
│   ├── practice_report.json     # 实践报告模板 (A5用)
│   └── truth_verification.json  # 真理验证模板 (复盘用)
└── references/
    ├── mao_practice_theory.txt  # 实践论原文
    └── application_cases.md     # 应用案例集
```

## 版本历史
- v1.0 (2026-04-26): 初始版本，建立实践论指导框架

## 产物投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将产物写入交易邮箱。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 实践论门禁部 (A7) |
| **目标邮箱** | 交易邮箱 (trading) |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/trading/` |
| **投递方式** | 直接写入Markdown文件到指定目录 |
| **文件名格式** | `a7_practice_theory_{YYYYMMDD}_{HHMM}.md` |
| **frontmatter必须（完整7字段）** | 见下方YAML代码块 |
| **双通道投递** | 秘书邮箱 + 前端产物中心（`artifact-alignment-manager` SKILL §一） |


> **前端产物center文件frontmatter完整模板（双通道均需包含）**：
> ```yaml
> ---
> title: "产物标题"
> department: governance
> chain_phase: A7
> date: "YYYY-MM-DDTHH:MM:SS"
> type: practice_theory
> status: completed
> tags: "a7 a7 实践论"
> by_a_phase: A7
> ---
> ```
> 完整规范参见 `artifact-alignment-manager` SKILL §三

### 投递检查清单
- [ ] 文件写入 `reports/trading/` 目录
- [ ] 包含完整 YAML frontmatter
- [ ] 投递后通过 `ls reports/trading/a7_*` 验证文件存在

---
**使用时，请遵循实践论基本原理：实践是认识的来源，实践是认识发展的动力，实践是检验真理的唯一标准，实践是认识的目的。**
