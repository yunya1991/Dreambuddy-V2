---
name: dream-performance-review
description: "Dream-MultiSkill 绩效考核部 (HRBP) - 定期评估各部门/技能表现、顾问团考核、对不合格者启动PIP改进计划，改进无效时触发招聘流程。监控GitHub/技能市场热门项目。触发：绩效、考核、KPI、评分、评级、GitHub监控、市场情报、能力盘点、顾问考核、顾问绩效"
metadata:
  version: "4.0.0"
  author: Dream-MultiSkill
  category: hr
  last_updated: "2026-04-19"
---

# Dream Performance Review - 绩效考核部 (HRBP)

> **部门定位**: 人力资源业务伙伴 (HR Business Partner)
> 
> **汇报对象**: 总经理 (Smart Skill Manager)
> 
> **协作部门**: HR招聘部、培训部、蒸馏部(已集成)、各执行部门
>
> **v3.0 变更**: 蒸馏部16子Skill完整集成、退役/蒸馏链路打通、大师蒸馏状态联动考核

---

## 核心职责

1. **绩效考核** - 定期评估各部门/技能的表现
2. **绩效改进** - 对不合格者分配更多资源进行改进
3. **招聘触发** - 改进无效时触发 HR 招聘流程
4. **市场监控** - GitHub/技能市场热门项目监控
5. **顾问考核** - 定期评估顾问团11位成员的绩效表现
6. **统一能力盘点** - 整合招聘部移交的能力盘点职责，统一输出
7. **蒸馏部联动** - D级Skill/顾问淘汰后移交蒸馏部，跟踪蒸馏产物质量 (v3.0新增)

---

## 遇到以下情况请查阅

| 情况 | 查阅章节 | 行动 |
|:---|:---|:---|
| 需要评估某个技能的表现 | §2 绩效考核体系 | 执行考核流程 |
| 某个技能连续失败 | §3 绩效改进流程 (PIP) | 启动改进计划 |
| 改进无效需要招聘替代 | §4 招聘触发流程 | 通知招聘部 |
| 需要监控GitHub热门项目 | §5 GitHub监控 | 设置监控任务 |
| 定期能力盘点 | §6 能力盘点 | 执行盘点流程 |
| 评估顾问团表现 | §7 顾问团考核 | 执行顾问考核 |
| 生成绩效报告 | §2.5 动态报告规范 | 按规范输出报告 |
| D级Skill/顾问需蒸馏 | §8 蒸馏部联动 (v3.0) | 移交蒸馏部并跟踪 |
| 蒸馏产物质量评估 | §8.3 蒸馏质量回溯 | 回溯验证蒸馏结果 |

---

## §1 绩效考核维度

### 1.1 考核维度定义

| 维度 | 权重 | 指标 | 数据来源 |
|:---|:---:|:---|:---|
| **执行准确率** | 30% | 日志验证通过率 | Gate 执行日志 |
| **响应时间** | 20% | 平均处理延迟 | 执行记录 |
| **资源效率** | 20% | 算力消耗/收益比 | 成本数据 |
| **改进闭环** | 15% | 问题修复率 | Issue 记录 |
| **合规达标** | 15% | Gate 通过率 | Gate 审计结果 |

### 1.2 评分标准

```python
def calculate_performance_score(skill_id: str) -> Dict:
    """计算技能综合评分"""
    
    # 收集各维度数据
    accuracy = get_execution_accuracy(skill_id)      # 0-100
    latency = get_response_latency(skill_id)         # 0-100 (延迟越低越高)
    efficiency = get_resource_efficiency(skill_id)   # 0-100
    improvement = get_fix_rate(skill_id)             # 0-100
    compliance = get_gate_pass_rate(skill_id)         # 0-100
    
    # 加权计算
    weighted_score = (
        accuracy * 0.30 +
        latency * 0.20 +
        efficiency * 0.20 +
        improvement * 0.15 +
        compliance * 0.15
    )
    
    # 评级
    if weighted_score >= 90: grade = "S"
    elif weighted_score >= 80: grade = "A"
    elif weighted_score >= 70: grade = "B"
    elif weighted_score >= 60: grade = "C"
    else: grade = "D"
    
    return {
        "skill_id": skill_id,
        "dimensions": {
            "accuracy": accuracy,
            "latency": latency,
            "efficiency": efficiency,
            "improvement": improvement,
            "compliance": compliance
        },
        "weighted_score": round(weighted_score, 1),
        "grade": grade,
        "timestamp": current_timestamp()
    }
```

### 1.3 评级规则

| 评级 | 分数范围 | 定义 | 行动 |
|:---|:---:|:---|:---|
| **S** | 90-100 | 卓越，超出预期 | 保持，给予更多资源探索 |
| **A** | 80-89 | 优秀，稳定达标 | 保持，继续观察 |
| **B** | 70-79 | 良好，需轻微改进 | 提醒，下月复查 |
| **C** | 60-69 | 及格，需显著改进 | 启动观察期，分配额外学习资源 |
| **D** | <60 | 不合格 | 立即启动 PIP，7天改进窗口 |

---

## §2 绩效考核流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                    📊 每日/每周绩效考核流程                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Day 0 (23:00): 自动触发                                            │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ 1. 收集数据                                                   │   │
│  │    - 各技能执行日志                                          │   │
│  │    - Gate 审计结果                                           │   │
│  │    - API 调用统计                                            │   │
│  │    - 成本消耗数据                                            │   │
│  │    - 收益/损失数据                                            │   │
│  │                                                              │   │
│  │ 2. 计算评分                                                   │   │
│  │    - 调用 calculate_performance_score()                      │   │
│  │    - 生成各技能评分报告                                       │   │
│  │                                                              │   │
│  │ 3. 识别问题                                                   │   │
│  │    - 标记 C/D 级技能                                         │   │
│  │    - 生成改进建议                                             │   │
│  │                                                              │   │
│  │ 4. 发送报告                                                   │   │
│  │    - 发送给总经理                                             │   │
│  │    - 抄送相关部门负责人                                        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## §2.5 动态报告规范 (v2.0新增)

> **核心原则**: 报告内容必须基于真实执行数据，禁止无数据支撑的结论性描述。

### 2.5.1 数据采集前置

每次生成绩效报告前，**必须先执行**以下数据采集：

```
报告生成前置检查清单:
├── [ ] 读取 ~/.workbuddy/skills/boss-secretary/reports/ 下最新报告
│   ├── operation_health_*.md → 获取自动化健康数据
│   └── dream_gate_audit_*.md → 获取Gate审计结果
├── [ ] 读取 .workbuddy/memory/ 下最新日志 → 获取Episode执行记录
├── [ ] 读取自动化memory.md (如存在) → 获取自动化执行状态
├── [ ] 读取 .workbuddy/skills/dream-performance-review/kpi_current.json → 获取KPI当前值
└── [ ] 禁止输出"✅ 已修复"、"100%覆盖"等结论，除非有具体数据引用
```

### 2.5.2 报告质量门禁

| 规则 | 说明 |
|:---|:---|
| **每条结论必须携带 evidence_refs** | 引用来源文件路径和行号 |
| **禁止空数据报告** | 若无数据可采集，输出"数据不足，跳过本轮"而非猜测 |
| **KPI列必须填充** | 从 kpi_current.json 读取，不可写"?" |
| **评级必须有计算依据** | 附带5维评分明细表 |

### 2.5.3 报告输出路径

| 报告类型 | 输出路径 |
|:---|:---|
| 日常绩效报告 | `.workbuddy/reports/hr/performance_{YYYYMMDD}.md` + 复制到 `~/.workbuddy/skills/boss-secretary/reports/performance_review_{YYYYMMDD}.md` |
| 能力盘点报告 | `.workbuddy/reports/hr/capability_audit_{YYYYMMDD}.md` + 复制到 `~/.workbuddy/skills/boss-secretary/reports/` |
| 顾问考核报告 | `.workbuddy/reports/hr/advisor_performance_{YYYYMMDD}.md` + 复制到 `~/.workbuddy/skills/boss-secretary/reports/` |
| PIP记录 | `.workbuddy/reports/hr/pip_{skill_id}_{date}.md` + 复制到 `~/.workbuddy/skills/boss-secretary/reports/` |

---

## §3 绩效改进流程 (PIP)

### 3.1 PIP 触发条件

- 评级连续 2 周为 C
- 评级任何一周为 D
- 总经理特别指示

### 3.2 PIP 执行流程

```
Day 0: PIP 启动
┌──────────────────────────────────────────────────────────────┐
│ 1. 发送告警通知                                               │
│    → 技能负责人                                               │
│    → 总经理                                                   │
│    → 培训部                                                   │
│                                                               │
│ 2. 创建 PIP 记录                                              │
│    → 路径: dream_data/pip/{skill_id}_{date}.md               │
│    → 记录: 问题描述、历史评分、改进目标                       │
│                                                               │
│ 3. 资源调整                                                   │
│    → 算力配额 × 2.0                                          │
│    → API 调用优先级提升                                       │
│                                                               │
│ 4. 触发学习流程                                               │
│    → 调用 learning-lesson-distiller 进行强化                   │
│    → 调用 learning-proposal-generator 生成改进提案             │
│                                                               │
│ 5. 通知招聘部                                                 │
│    → 开始准备替代方案 (不立即行动，但提前准备)                  │
└──────────────────────────────────────────────────────────────┘

Day 1-6: 改进期
┌──────────────────────────────────────────────────────────────┐
│ 每日评估:                                                     │
│                                                               │
│ if 评分提升 > 10%:                                            │
│     → 调整配额到 1.5x                                         │
│     → 记录改善原因                                            │
│ elif 评分无变化:                                              │
│     → 保持 2x 配额                                            │
│     → 分析瓶颈因素                                            │
│     → 调整学习策略                                            │
│ else:                                                         │
│     → 保持观察                                                │
└──────────────────────────────────────────────────────────────┘

Day 7: 最终评估
┌──────────────────────────────────────────────────────────────┐
│ if 评级 >= B:                                                 │
│     ✅ PIP 成功                                                │
│     → 恢复正常配额                                            │
│     → 记录改进成功经验到 Lesson                               │
│     → 通知: 总经理、负责人、培训部                             │
│ else:                                                         │
│     ❌ PIP 失败                                                │
│     → 进入招聘触发流程 (§4)                                    │
│     → 评估: 修复/替换/弃用                                    │
│     → 通知: 总经理、招聘部                                    │
└──────────────────────────────────────────────────────────────┘
```

---

## §4 招聘触发流程

### 4.1 触发条件

- PIP 7 天后评级仍 < B
- 技能连续 3 次执行失败
- 总经理特别指示

### 4.2 招聘部协作模板

```markdown
## 🔍 技能招聘需求单

**发送方**: 绩效考核部
**接收方**: HR招聘部
**时间**: {timestamp}

### 基本信息
- **技能名称**: {skill_id}
- **技能类型**: {skill_category}
- **当前状态**: {current_status}

### 问题描述
{problem_description}

### 失败历史
- {date1}: {issue1}
- {date2}: {issue2}
- {date3}: {issue3}

### 期望替代
- **优先级**: P{Priority}
- **期望能力**: {expected_capabilities}
- **替代方案**: 修复 / 替换 / 弃用

### 协作要求
1. 在技能市场搜索替代方案
2. 评估 GitHub 热门项目
3. 给出 Top 3 候选及推荐
4. 完成时间: {deadline}

### 历史PIP记录
{pip_history}
```

---

## §5 GitHub/技能市场监控

### 5.1 监控关键词

```python
github_monitor_keywords = {
    "交易相关": [
        "crypto trading bot",
        "algorithmic trading", 
        "quantitative finance",
        "backtesting framework",
        "trading strategies",
    ],
    "AI Agent相关": [
        "autonomous agent",
        "multi-agent system",
        "task orchestration",
        "ai workflow",
    ],
    "交易所相关": [
        "okx-api",
        "binance-api", 
        "huobi-api",
        "exchange-connector",
    ],
    "数据分析": [
        "financial data",
        "market analysis",
        "technical analysis",
        "crypto analytics",
    ],
}
```

### 5.2 项目评分规则

```python
def score_github_project(project: Dict) -> float:
    """评分 GitHub 项目"""
    score = 0
    
    # Stars 增长 (7天) - 权重 30%
    stars_delta = project.get("stars_delta_7d", 0)
    score += min(stars_delta / 200, 30)  # 封顶 30分
    
    # Fork 数 - 权重 20%
    forks = project.get("forks_count", 0)
    score += min(forks / 100, 20)  # 封顶 20分
    
    # 最近提交 - 权重 20%
    days_since_commit = project.get("days_since_commit", 999)
    if days_since_commit <= 7: score += 20
    elif days_since_commit <= 30: score += 15
    elif days_since_commit <= 90: score += 10
    else: score += 0
    
    # Issue 关闭率 - 权重 15%
    close_rate = project.get("issues_closed_rate", 0)
    score += close_rate * 15
    
    # 贡献者数 - 权重 15%
    contributors = project.get("contributors", 0)
    if contributors >= 10: score += 15
    elif contributors >= 5: score += 10
    elif contributors >= 2: score += 5
    
    return round(score, 1)
```

### 5.3 告警阈值

| 条件 | 告警级别 | 行动 |
|:---|:---:|:---|
| stars_delta > 500 in 7d | 🔥 P0 | 立即通知总经理 |
| stars_delta > 200 in 7d | ⚡ P1 | 加入候选池，通知招聘部 |
| relevant_to_missing_skill | 📋 P2 | 加入情报报告 |
| new_framework_release | 🆕 P2 | 加入技术雷达 |

---

## §6 能力盘点

### 6.1 盘点维度

| 维度 | 说明 |
|:---|:---|
| **技能覆盖率** | 当前技能覆盖了多少交易场景 |
| **技能健康度** | 各技能的评级分布 |
| **能力缺口** | 缺失的重要技能 |
| **技能冗余** | 功能重叠的技能 |
| **更新频率** | 各技能版本更新情况 |

### 6.2 盘点报告模板

```markdown
## 📊 团队能力盘点报告

**日期**: {date}
**负责人**: 绩效考核部

### 一、总体概况
- 技能总数: {total_skills}
- S级技能: {s_count} ({s_ratio}%)
- A级技能: {a_count} ({a_ratio}%)
- B级技能: {b_count} ({b_ratio}%)
- C级技能: {c_count} ({c_ratio}%)
- D级技能: {d_count} ({d_ratio}%)

### 二、技能健康度分布
[柱状图: 各评级技能数量]

### 三、能力缺口分析
| 缺失领域 | 影响 | 优先级 | 建议行动 |
|:---|:---|:---:|:---|
| {domain} | {impact} | {priority} | {action} |

### 四、技能冗余分析
| 技能组合 | 重叠度 | 建议 |
|:---|:---:|:---|
| {skills} | {overlap}% | {suggestion} |

### 五、改进建议
1. {suggestion_1}
2. {suggestion_2}
3. {suggestion_3}

### 六、下一步行动
| 行动 | 负责人 | 完成时间 |
|:---|:---|:---|
| {action} | {owner} | {deadline} |
```

---

## 决策树

```
【开始】
│
├─ 需要评估技能表现？
│   └─ 是 → §2 绩效考核流程
│
├─ 技能连续失败/评级D？
│   └─ 是 → §3 PIP 改进流程
│
├─ PIP 失败？
│   └─ 是 → §4 招聘触发流程
│
├─ 需要监控市场动态？
│   └─ 是 → §5 GitHub监控
│
├─ 定期能力盘点？
│   └─ 是 → §6 能力盘点 (已整合招聘部职责)
│
├─ 评估顾问团表现？
│   └─ 是 → §7 顾问团考核 (v2.0新增)
│
├─ 生成报告？
│   └─ 是 → §2.5 动态报告规范 (v2.0新增)
│
└─ 其他问题
    └─ 找运营总监协调
```

---

## 关键指标 (KPI)

| 指标 | 目标值 | 数据源 | 更新频率 |
|:---|:---:|:---|:---|
| 技能平均评分 | ≥ 80 | hr_performance.py 5维计算 | 每日 |
| PIP 改进成功率 | ≥ 70% | PIP记录 / 总PIP数 | 每7天 |
| 市场情报覆盖率 | 100% | GitHub监控命中 / 需求 | 每周 |
| 招聘匹配满意度 | ≥ 80% | 招聘后使用部门反馈 | 每次招聘 |
| 顾问平均采纳率 | ≥ 60% | Episode advisor_consult 字段 | 每周 |
| 顾问预测准确率 | ≥ 50% | 顾问预测 vs 实际结果 | 每周 |

**KPI存储**: `~/.workbuddy/skills/dream-performance-review/kpi_current.json`  
**历史数据**: `~/.workbuddy/skills/dream-performance-review/kpi_history.jsonl`

> ⚠️ 报告中KPI"当前值"列**必须**从 kpi_current.json 读取，**禁止**写"?"
> 若JSON不存在，由 hr_performance.py 首次运行时创建

---

## §7 顾问团考核 (v2.0新增)

### 7.1 考核范围

11位顾问: QT/RM/EE/MR/SA/KB/DA/HR/TR/RP/ER  
定义来源: `boss-secretary/knowledge/advisor_routing.yaml`

### 7.2 考核维度

| 维度 | 权重 | 指标 | 数据来源 |
|:---|:---:|:---|:---|
| **建议采纳率** | 40% | 建议被最终决策采纳的比例 | Episode advisor_consult 字段 |
| **预测准确率** | 30% | 顾问判断与实际结果一致的比例 | 交易结果 vs 顾问意见 |
| **响应及时性** | 15% | 在时限内响应的比例 | 自动化执行时间戳 |
| **输出质量** | 15% | 符合 expected_output 模板的比例 | Gate审计记录 |

### 7.3 评级标准

| 评级 | 采纳率 | 预测准确率 | 行动 |
|:---|:---:|:---:|:---|
| **S** | ≥80% | ≥75% | 权重+0.10 |
| **A** | ≥65% | ≥60% | 保持 |
| **B** | ≥50% | ≥45% | 观察 |
| **C** | ≥35% | ≥30% | 降权 ×0.7 |
| **D** | <35% | <30% | PIP (2周改进) |

### 7.4 顾问淘汰机制

```
PIP 失败 → 降权 (base_weight × 0.5) → 标记"待退休" → 蒸馏部提取核心观点后退役
├── 蒸馏部路径: ~/.workbuddy/skills/dream-distill-department/
├── 产出: 蒸馏报告 (核心观点、有效经验、失败教训)
└── 知识继承: 顾问核心观点写入 knowledge/masters/ 知识库
```

### 7.5 顾问考核自动化

- **触发时间**: 每周日 09:00 (通过 performance-review 自动化)
- **输出**: `.workbuddy/reports/hr/advisor_performance_{YYYYMMDD}.md` + 复制到 `~/.workbuddy/skills/boss-secretary/reports/`
- **联动**: 评级变更后更新 advisor_routing.yaml 中的 rating 字段

---

## §8 P1行动项自动化工作流 (v4.0新增)

> **核心原则**: P1任务必须有自动化支撑才能真正完成。"安排给某部门"而不设计自动化 = 任务永远无法执行。

### 8.1 P1任务自动化工坊

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    P1 行动项 → 自动化任务 工作流                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  HR报告生成                                                                   │
│      │                                                                          │
│      ▼                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ Step 1: 行动项分类                                                    │     │
│  │                                                                      │     │
│  │ P1-A: 需要调研评估    → 集成 dream-strategy-research SKILL          │     │
│  │ P1-B: 需要代码修复    → 集成 auto-repair SKILL                      │     │
│  │ P1-C: 需要技能激活    → 集成对应 SKILL (如顾问)                      │     │
│  │ P1-D: 需要深度分析    → 设计自动化调研任务                            │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│      │                                                                          │
│      ▼                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ Step 2: 设计自动化方案                                                │     │
│  │                                                                      │     │
│  │ 方案A: 创建定时自动化任务                                             │     │
│  │        - 设置 rrule (FREQ/INTERVAL)                                  │     │
│  │        - 编写 prompt (执行逻辑)                                        │     │
│  │        - 指定 cwds (工作目录)                                         │     │
│  │                                                                      │     │
│  │ 方案B: 集成到现有 SKILL                                               │     │
│  │        - 修改 SKILL.md 添加触发词                                     │     │
│  │        - 在 SKILL 流程中嵌入执行步骤                                  │     │
│  │                                                                      │     │
│  │ 方案C: 临时一次性任务                                                 │     │
│  │        - 使用 automation_update 创建一次性任务                          │     │
│  │        - 指定 scheduledAt 执行时间                                    │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│      │                                                                          │
│      ▼                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐     │
│  │ Step 3: 完成后投递到秘书待处理邮箱                                     │     │
│  │                                                                      │     │
│  │ 路径: ~/.workbuddy/skills/boss-secretary/pending_tasks/inbox/        │     │
│  │ 格式: fix_{YYYYMMDD_HHMMSS}.md                                      │     │
│  │ 内容: 工单ID、来源、fix_actions、状态(PENDING)                        │     │
│  │                                                                      │     │
│  │ → auto-repair-processor 每天定时扫描并处理                            │     │
│  │ → pending-actions-processor 每8小时检查进度                            │     │
│  └─────────────────────────────────────────────────────────────────────┘     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 P1行动项自动化模板

```markdown
# P1行动项自动化配置

**行动项ID**: P1-{序号}
**原HR报告**: hr_{YYYYMMDD}.md
**创建时间**: {timestamp}
**截止时间**: {deadline}

---

## 行动项定义

| 字段 | 值 |
|:---|:---|
| 原始行动 | {P1-N}: {action_description} |
| 原负责人 | {assigned_to} |
| 截止时间 | {deadline} |

## 自动化方案

### 方案选择

- [ ] 方案A: 创建定时自动化任务
- [ ] 方案B: 集成到现有SKILL
- [ ] 方案C: 临时一次性任务

### 方案A: 定时自动化任务

```yaml
[automation]
name = "P1-{task_id}"
status = "ACTIVE"  # 或 "PAUSED" (等待人工确认)
rrule = "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=0"
cwds = ["/Users/zhangjiangtao/WorkBuddy/20260415144304"]

[prompt]
text = """
{task_execution_logic}
"""
```

### 方案B: SKILL集成

| 项目 | 值 |
|:---|:---|
| 目标SKILL | {skill_name} |
| 触发词 | {trigger_keywords} |
| 嵌入位置 | {step_in_skill} |
| 执行逻辑 | {execution_logic} |

### 方案C: 临时一次性任务

```yaml
[automation]
name = "P1-{task_id}-one-time"
status = "ACTIVE"
scheduleType = "once"
scheduledAt = "{YYYY-MM-DDTHH:MM:SS}"
cwds = ["/Users/zhangjiangtao/WorkBuddy/20260415144304"]

[prompt]
text = """
{task_execution_logic}
"""
```

## 完成后投递

```bash
# 投递到秘书待处理邮箱
fix_{YYYYMMDD_HHMMSS}.md → ~/.workbuddy/skills/boss-secretary/pending_tasks/inbox/
```

---

*模板生成: dream-performance-review v4.0 | {timestamp}*
```

### 8.3 典型P1行动项自动化示例

#### 示例1: P1-A 调研评估类

| 原P1行动 | 自动化方案 | SKILL集成 |
|:---|:---|:---|
| 深度分析 HKUDS/AI-Trader 竞品架构 | 一次性自动化任务 | dream-strategy-research |
| 评估顾问prompt模板有效性 | 定时自动化(每周) | dream-performance-review |

#### 示例2: P1-B 代码修复类

| 原P1行动 | 自动化方案 | SKILL集成 |
|:---|:---|:---|
| 修复automation-9调度机制 | 一次性自动化任务 | auto-repair |
| 补充dream-tactical-executor-2配置 | 临时任务 | auto-repair |

#### 示例3: P1-C 技能激活类

| 原P1行动 | 自动化方案 | SKILL集成 |
|:---|:---|:---|
| 激活QT/RM/MR核心顾问 | 无需自动化(Skill已集成) | 标注"被动模式" |
| 跟进蒸馏部评估进度 | 定时自动化(每日) | dream-performance-review |

### 8.4 自动化任务创建命令

```bash
# 创建定时自动化任务
automation_update create \
  --name "P1-{task_id}" \
  --prompt "{task_execution_prompt}" \
  --rrule "FREQ=WEEKLY;BYDAY=MO;BYHOUR=9" \
  --cwds "/Users/zhangjiangtao/WorkBuddy/20260415144304" \
  --status ACTIVE

# 创建一次性任务
automation_update create \
  --name "P1-{task_id}-one-time" \
  --prompt "{task_execution_prompt}" \
  --scheduleType once \
  --scheduledAt "{YYYY-MM-DDTHH:MM:SS}" \
  --cwds "/Users/zhangjiangtao/WorkBuddy/20260415144304" \
  --status ACTIVE
```

### 8.5 HR报告P1行动项自动化工单

```
生成HR报告时，对每个P1行动项必须输出:

| # | 原始行动 | 自动化方案 | SKILL集成 | 状态 |
|---|---------|-----------|----------|:---:|
| P1-1 | {action} | 方案A/B/C | {skill} | 待创建/已创建/无需自动化 |
```

**禁止**: 仅写"负责人: XXX部门"而不设计自动化

---

## §9 蒸馏部联动 (v3.0新增)

### 8.1 触发条件

当以下任一情况发生时，绩效考核部应将目标移交蒸馏部：

| 触发条件 | 移交内容 | 蒸馏入口 |
|:---|:---|:---|
| Skill PIP失败 (评级持续D) | Skill ID + 绩效历史 + PIP记录 | `master-template-registry` |
| 顾问淘汰 (评级D且PIP失败) | 顾问ID + 核心观点 + 预测历史 | `neuro-cognitive-modeler` |
| Skill主动退役 | Skill完整SKILL.md + 使用记录 | `master-distillation-orchestrator` |
| 大师蒸馏状态降级 | 大师状态机快照 + 蒸馏报告 | `master-state-machine-governor` |

### 8.2 移交协议

```yaml
# 绩效部 → 蒸馏部 标准移交包
distillation_handoff:
  source: "performance-review"  # 来源部门
  timestamp: "{ISO8601}"
  target_type: "skill|advisor|master"  # 目标类型
  target_id: "{skill_id|advisor_id|master_id}"
  
  # 绩效数据（绩效部提供）
  performance_data:
    current_grade: "D"
    grade_history: ["C", "C", "D", "D"]  # 最近4次评级
    pip_records: ["pip_{id}_{date1}.md", "pip_{id}_{date2}.md"]
    last_evaluation: "{date}"
    
  # 核心价值提取（蒸馏部执行）
  distillation_scope:
    extract_core_methods: true     # 提取核心方法
    extract_failure_lessons: true  # 提取失败教训
    extract_success_patterns: true # 提取成功模式
    generate_playbook: false       # 默认不生成playbook（仅大师类）
    
  # 预期产出
  expected_outputs:
    - "cognitive_model_ref"           # 认知模型（大师/顾问）
    - "practice_pack_ref"             # 实践包（大师类）
    - "knowledge_legacy_ref"          # 知识遗产（通用）
    - "distillation_quality_report"   # 蒸馏质量报告
```

### 8.3 蒸馏质量回溯

蒸馏部完成蒸馏后，绩效考核部应执行质量回溯：

| 检查项 | 数据来源 | 合格标准 |
|:---|:---|:---|
| 证据链完整性 | `distillation-quality-gate` 报告 | `evidence_check=pass` |
| 风险边界合规 | `distillation-quality-gate` 报告 | `risk_check=pass\|warn` |
| 回滚计划可用 | `distillation-quality-gate` 报告 | `rollback_ready=yes` |
| 知识遗产已入库 | `knowledge/masters/` 或 `lessons/` | 文件存在且非空 |
| 蒸馏产物复用 | 后续Episode/Skill使用记录 | 30天内至少1次引用 |

### 8.4 蒸馏部Skill架构映射

绩效考核部需要了解蒸馏部的16个子Skill，以便正确路由移交请求：

```
蒸馏部内部架构 (16个Skill):
├── 蒸馏核心流水线
│   ├── neuro-cognitive-modeler     # 认知建模 (大师/顾问 → 左脑/右脑/元认知)
│   ├── market-practice-simulator   # 市场推演 (理论 → 可执行playbook)
│   └── distillation-quality-gate   # 质量门禁 (发布前最终审核)
│
├── 双脑协同决策
│   ├── shared-memory-kernel        # 共享证据图谱
│   ├── left-brain-executor         # 左脑: 确定性规则/硬阻断
│   └── right-brain-strategist      # 右脑: 情景推演/概率判断
│
├── 编排与工厂
│   ├── master-distillation-orchestrator  # 单大师蒸馏编排 (V1/V2流程)
│   ├── master-factory-orchestrator       # 批量大师蒸馏工厂 (1-3位)
│   └── master-template-registry          # 大师输入模板标准化
│
├── 状态机治理
│   ├── master-state-machine-governor     # 5态迁移 (observe/candidate/primary/degraded/frozen)
│   ├── master-regime-fit-scorer          # regime拟合评分
│   ├── master-switch-policy-engine       # 多大师切换方案
│   └── master-freeze-controller          # 冻结/解冻治理
│
└── 记忆治理
    ├── memory-governance-evaluator       # 记忆价值/老化/冲突评估
    ├── memory-tier-manager               # L0/L1/L2分层管理
    └── memory-revalidation-gate          # 过时记忆重验证门禁
```

### 8.5 移交路由表

| 移交目标 | 目标类型 | 蒸馏入口Skill | 蒸馏流程版本 |
|:---|:---|:---|:---|
| 交易大师 (Livermore/Tharp等) | master | `master-template-registry` → `master-distillation-orchestrator` | V2 (双脑) |
| 顾问 (ADVISOR-QT等) | advisor | `neuro-cognitive-modeler` → `distillation-quality-gate` | V1 (认知建模) |
| 退役Skill | skill | `neuro-cognitive-modeler` (提取方法) | V1 (轻量) |
| 批量大师蒸馏 | masters[] | `master-factory-orchestrator` | 工厂流水线 |

### 8.6 大师状态联动

绩效考核部在考核大师相关Skill时，应参考蒸馏部状态机：

| 蒸馏部状态 | 含义 | 绩效部行动 |
|:---|:---|:---|
| `observe` | 观察中 | 正常考核 |
| `candidate` | 候选中 | 增加考核频次 |
| `primary` | 主用中 | 重点考核 |
| `degraded` | 已降级 | 启动PIP |
| `frozen` | 已冻结 | 暂停考核，移交蒸馏部 |

> **数据读取**: 蒸馏部状态机数据存储在 `~/.workbuddy/skills/dream-distill-department/master-factory-orchestrator/reports/` 下的最新JSON报告

---

## 附录：部门索引

| 部门 | 遇到问题时找谁 |
|:---|:---|
| 绩效考核问题 | 本部门 |
| 技能/Skill招聘 | HR招聘部 |
| 技能试用期追踪 | HR招聘部 SOP-3 |
| 技能退役/蒸馏 | **蒸馏部** (详见§8) |
| 大师认知建模 | 蒸馏部 `neuro-cognitive-modeler` |
| 大师状态查询 | 蒸馏部 `master-state-machine-governor` |
| 大师批量蒸馏 | 蒸馏部 `master-factory-orchestrator` |
| 蒸馏质量审核 | 蒸馏部 `distillation-quality-gate` |
| 记忆分层治理 | 蒸馏部 `memory-tier-manager` |
| 技能培训 | 培训部 |
| 流程卡顿 | 运营总监 |
| 合规问题 | 首席安全官 |
| 战略决策 | 总经理 |

---

*最后更新: 2026-04-26*
*版本: v4.0*
*负责人: Dream Performance Review*
*v4.0变更: P1行动项自动化工作流§8、"安排给某部门"必须配套自动化设计、SKILL/定时任务/一次性任务三种方案*
*v3.0变更: 蒸馏部16子Skill完整集成(§8)、D级→蒸馏部移交协议、大师状态联动考核*
*v2.0变更: 新增顾问团考核§7、动态报告规范§2.5、统一能力盘点§6、KPI数据源映射*


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 绩效考核部 |
| **目标邮箱** | 秘书汇总邮箱 (secretary) |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/` |
| **投递方式** | 直接复制/写入Markdown文件到指定目录 |
| **投递命令** | 直接写入文件到 `~/.workbuddy/skills/boss-secretary/reports/<文件名>.md` |

### 投递工作流

```
1. 本部门完成工作（自动化任务/手动触发）
2. 整理工作总结（Markdown格式）
3. 确定优先级: P0(紧急)/P1(重要)/P2(观察)/P3(正常)
4. 执行投递命令
5. 确认邮件ID返回 → 投递完成
```

### 代码入口

- **投递方式**: 直接写入Markdown文件到指定邮箱目录
- **查看邮箱**: `ls ~/.workbuddy/skills/boss-secretary/reports/`
