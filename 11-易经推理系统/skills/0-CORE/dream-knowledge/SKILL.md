---
name: dream-knowledge
description: |
  📚 知识库SKILL - 核心交易策略和工具的动态知识库
  
  核心能力：
  1. 知识沉淀：联网搜索/实践复盘 → 评分 → 入库
  2. 知识检索：按评分排序，高评分优先
  3. 知识进化：实践反馈驱动评分调整
  4. 定期维护：72h自动评估和清理
  
  触发词：
  - 知识沉淀、知识入库、新策略入库
  - 知识检索、查找策略、找工具
  - 知识进化、评分更新、策略复盘
  - 知识库维护、知识评估

version: 1.0.0
created: 2026-04-27
updated: 2026-04-27
license: Internal
---

# 📚 Dream-Knowledge: 知识库SKILL (v1.0)

> 核心交易策略和工具的动态知识库，沉淀→评估→检索→进化闭环

---

## 🎯 SKILL目标

1. **知识沉淀**: 将联网搜索和实践复盘转化为可量化评估的知识
2. **高效检索**: 评分排序，高质量策略优先获取
3. **持续进化**: 实践反馈驱动评分动态调整
4. **质量保障**: 内置评分体系和证据链管理

---

## 📊 评估体系

### 评分维度 (总分100分)

```yaml
scoring_dimensions:
  # 基础质量 (30分)
  logic_completeness:
    max: 10
    desc: "入场/出场/风控逻辑是否完整"
    
  parameter_clarity:
    max: 10
    desc: "参数是否明确可执行"
    
  executability:
    max: 10
    desc: "是否可以在实盘中执行"
  
  # 实证表现 (40分)
  historical_win_rate:
    max: 20
    desc: "历史验证胜率"
    
  risk_reward_ratio:
    max: 10
    desc: "风险收益比表现"
    
  practice_count:
    max: 10
    desc: "实战验证次数"
  
  # 适用广度 (15分)
  regime_coverage:
    max: 10
    desc: "适用的Regime数量"
    
  tool_compatibility:
    max: 5
    desc: "工具兼容范围"
  
  # 进化潜力 (15分)
  optimization_space:
    max: 10
    desc: "可优化/迭代空间"
    
  extensibility:
    max: 5
    desc: "扩展性评分"
```

### 分级标准

| 等级 | 分数 | 标记 | 用途 |
|:---|:---:|:---:|:---|
| S级 | ≥80 | ⭐⭐⭐ | 首选策略，优先检索 |
| A级 | 60-79 | ⭐⭐ | 标准策略，正常检索 |
| B级 | 40-59 | ⭐ | 参考备选，需谨慎 |
| C级 | <40 | ❌ | 归档或淘汰 |

---

## 🔄 核心流程

### 流程1: 知识沉淀

```
输入: 联网搜索结果 / 实践复盘 / 蒸馏产物
    ↓
Step1: 提取策略/工具信息
    ↓
Step2: 执行评估打分
    ↓
Step3: 检查证据链
    ↓
Step4: 写入知识库
    ↓
Step5: 更新索引
    ↓
输出: 知识入库确认 + 评分报告
```

### 流程2: 知识检索

```
输入: 当前Regime / 工具类型 / 关键词
    ↓
Step1: 定位分类目录
    ↓
Step2: 按评分排序
    ↓
Step3: 筛选高分知识
    ↓
Step4: 输出带证据链的结果
    ↓
输出: 高分策略列表
```

### 流程3: 知识进化

```
输入: 实践反馈 / 复盘结果
    ↓
Step1: 定位知识条目
    ↓
Step2: 分析反馈结果
    ↓
Step3: 调整评分
    ↓
Step4: 更新级别
    ↓
Step5: 记录证据链
    ↓
输出: 评分调整报告
```

---

## 📁 知识库结构

```
.knowledge_base/
├── INDEX.md                    # 总索引(评分排序)
├── 📖 1_regime_patterns/      # Regime形态库
├── 📗 2_classic_strategies/   # 经典策略库 (含评分)
├── 🔧 3_trading_tools/        # 交易工具库 (含评分)
└── 👥 4_master_profiles/      # 大师资料库

# 评分索引
├── scores/
│   ├── S_rank.json           # S级知识索引
│   ├── A_rank.json           # A级知识索引
│   ├── B_rank.json           # B级知识索引
│   └── pending.json         # 待评估队列
└── history/
    └── YYYY-MM-DD.json      # 每日变动记录
```

---

## 🛠️ 使用方法

### 1. 知识沉淀

```yaml
# 当你需要将新策略入库时
invoke_skill:
  command: "dream-knowledge"
  action: "knowledge_save"
  
  input:
    name: "网格策略"
    type: "strategy"
    regime: ["RANGE_BOUND"]
    tool: "grid"
    source: "联网搜索"
    content: "策略详细内容..."
    
  output:
    score_report: "评分详情"
    tier: "A级"
    action: "已入库 / 需补充证据"
```

### 2. 知识检索

```yaml
# 当你需要查找策略时
invoke_skill:
  command: "dream-knowledge"
  action: "knowledge_search"
  
  input:
    regime: "TREND_BULL"
    tool: "futures"
    min_score: 60
    
  output:
    results: [
      {
        name: "趋势追踪策略",
        score: 85,
        tier: "S级",
        evidence: ["EP001", "EP002"]
      }
    ]
```

### 3. 知识进化

```yaml
# 当实践结束后
invoke_skill:
  command: "dream-knowledge"
  action: "knowledge_evolve"
  
  input:
    knowledge_id: "strategy_trend_001"
    result: "success"  # success / partial / failure
    episode_id: "EP003"
    notes: "复盘备注"
    
  output:
    score_adjustment: "+5"
    new_tier: "A级→A级(稳定)"
```

---

## 📋 文档模板

```markdown
---
name: 策略/工具名称
type: strategy | tool
id: auto_generated_uuid
regime: [适用Regime]
tool_type: 工具类型
score: 75
tier: A级
source: 联网搜索 | 实践复盘 | 蒸馏产物
created: 2026-04-27
updated: 2026-04-27
verifications: 1
status: active

scoring:
  logic_completeness: 8/10
  parameter_clarity: 7/10
  executability: 8/10
  historical_win_rate: 15/20
  risk_reward_ratio: 7/10
  practice_count: 5/10
  regime_coverage: 6/10
  tool_compatibility: 4/5
  optimization_space: 6/10
  extensibility: 4/5
  total: 70/100

evidence_chain:
  - type: practice
    episode_id: EP001
    result: success
    date: 2026-04-27
    notes: "验证通过"
---

## 策略概述

## 评分详情
| 维度 | 得分 | 说明 |
|:---|:---:|:---|
| 逻辑完整性 | 8/10 | ... |
| ... | ... | ... |

## 适用条件

## 入场规则

## 出场规则

## 风险管理

## 实践记录

## 优化历史
```

---

## 🔗 关联系统

| 系统 | 关系 |
|:---|:---|
| dream-tactical-validator | A4实践 → 知识进化 |
| dream-posttrade-mrm-audit | 盘后复盘 → 评分更新 |
| master-distillation-orchestrator | 蒸馏产物 → 直接入库 |
| Regime检测系统 | Regime变化 → 检索触发 |
| artifact-alignment-manager | **前后端产物对齐** → 知识库规范化 |

---

## 🔄 前后端产物配套机制 (v1.1)

### 配套原则

> **知识库 = 前端展示层 + 后端存储层 + 检索接口层**

```
前端 FeedClient.tsx
    ↓ 展示分类 (KNOWLEDGE_CATS)
    ↓ 标签过滤
    ↓
artifacts/  (后端存储)
    ├── masters/      ← 蒸馏大师库
    ├── tools/       ← OKX工具库
    ├── macro/       ← 宏观资产库
    ├── risk/        ← 风险库
    ├── exit/        ← 离场规则库
    ├── practice/     ← 实践教训库
    └── web_strategy/ ← 联网策略库
    ↓ 检索
dream-knowledge (检索接口)
    ↓ 评分/推荐
A1/A2/A3 链路调用
```

### 配套规则

| 规则 | 说明 |
|------|------|
| R1 | 知识入库必须同时写入 `artifacts/{category}/` |
| R2 | 每个产物必须有 frontmatter（含 tags 标签） |
| R3 | tags 必须与前端 KNOWLEDGE_CATS 定义一致 |
| R4 | 知识检索优先从 artifacts/ 读取 |
| R5 | 每日与 artifact-alignment-manager 同步检查 |

### 工具库配套

```
dream-knowledge 检索 "工具" → 
    ↓ 调用 artifacts/tools/
    ↓ 读取 index.json + *.md
    ↓ 按标签匹配 (okx_tools, commands)
    ↓ 返回 OKX CLI 命令参考
```

### 风险库配套

```
dream-knowledge 检索 "风险" → 
    ↓ 调用 artifacts/risk/
    ↓ 读取 stop_loss.md, thresholds.md
    ↓ 按标签匹配 (risk, thresholds)
    ↓ 返回风险参数
```

### 触发词（新增）

- 知识配套检查、前后端同步
- 工具库检索、风险库检索
- 知识标签修复、产物标签规范化

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|:---|:---|:---|
| v1.0 | 2026-04-27 | 初版，评估体系+沉淀检索+进化流程 |
| v1.1 | 2026-05-05 | 新增前后端产物配套机制，与 artifact-alignment-manager 对齐 |
