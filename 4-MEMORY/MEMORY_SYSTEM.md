# 底层记忆系统完整设计

> **版本**: v2.0
> **更新日期**: 2026-05-14

---

## 🏛️ 系统定位

底层记忆系统是Dream-MultiSkill的智能记忆中枢，核心功能：
- **记忆存储**: 长期记忆、每日日志、Episode、Lesson
- **意图识别**: 用户输入 → 精准SKILL路由
- **交易路由**: 根据上下文快速调度A系SKILL
- **自我进化**: 从错误中学习，持续优化

---

## 📐 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    记忆系统架构                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    记忆输入层                          │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │ 用户输入 │  │ 执行结果 │  │ 外部数据 │          │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘          │   │
│  └───────┼─────────────┼─────────────┼────────────────────┘   │
│          │             │             │                        │
│  ┌───────▼─────────────▼─────────────▼────────────────────┐   │
│  │                    意图分析层                          │   │
│  │  ┌─────────────────────────────────────────────┐    │   │
│  │  │ memory-context-fencing (围栏防护)           │    │   │
│  │  │   - 污染检测                                  │    │   │
│  │  │   - 上下文注入                               │    │   │
│  │  │   - 意图分类                                 │    │   │
│  │  └─────────────────────────────────────────────┘    │   │
│  └───────────────────────────┬─────────────────────────────┘   │
│                              │                                │
│  ┌───────────────────────────▼─────────────────────────────┐   │
│  │                    SKILL路由层                           │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │   │
│  │  │ learning-    │  │ dream-       │  │ memory-    │  │   │
│  │  │ recall-pack  │  │ strategy-    │  │ budget-    │  │   │
│  │  │              │  │ parser       │  │ policy     │  │   │
│  │  └──────────────┘  └──────────────┘  └────────────┘  │   │
│  └───────────────────────────┬─────────────────────────────┘   │
│                              │                                │
│  ┌───────────────────────────▼─────────────────────────────┐   │
│  │                    记忆存储层                             │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │   │
│  │  │ MEMORY   │  │ DAILY    │  │ EPISODE  │  │ LESSON │  │   │
│  │  │ .md      │  │ .md      │  │          │  │        │  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └────────┘  │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 记忆类型

### 1. 长期记忆 (MEMORY.md)

**定位**: 跨session持久化的核心事实

**内容**:
- 用户偏好和背景
- 项目配置和约定
- 核心教训和经验
- 战略决策历史
- 系统架构说明

**存储位置**:
```
~/.workbuddy/memory/MEMORY.md
/Users/zhangjiangtao/WorkBuddy/{workspace}/.workbuddy/memory/MEMORY.md
```

**格式**:
```markdown
# MEMORY.md

## 用户信息
- 姓名: 张江涛
- 职业: 产品经理
- 偏好: 结构化输出、表格展示

## 项目配置
- 工作目录: /WorkBuddy/20260415144304
- 核心系统: Dream-MultiSkill

## 核心教训
- OKX API踩坑: CLI用okx非okx-trade
- SHORT委托: SL=tpTriggerPx, TP=slTriggerPx
```

### 2. 每日记忆 (YYYY-MM-DD.md)

**定位**: 当日工作记录

**内容**:
- 任务执行记录
- 决策快照
- 临时信息
- 产物路径

**存储位置**:
```
~/.workbuddy/memory/2026-05-14.md
```

**格式**:
```markdown
# 2026-05-14

## 任务记录
- 14:00 A8理论实践验证
- 17:00 做梦洞察

## 决策快照
- 14:30 BUY信号触发，执行建仓
- 15:00 A4验证通过

## 产物
- a4_validation_20260514_1400.md
- a5_execution_20260514_1500.md
```

### 3. Episode记忆

**定位**: 交易决策闭环的事实底座

**内容**:
- 决策输入快照
- 执行链路
- 评分和门禁
- 结果归因

**存储位置**:
```
/Users/zhangjiangtao/WorkBuddy/{workspace}/episodes/
episode_{timestamp}.json
```

**格式**:
```json
{
  "episode_id": "ep_20260514_143000",
  "timestamp": "2026-05-14T14:30:00Z",
  "user_input": "BTC/USDT做多信号",
  "decision_chain": {
    "a0": "矛盾已识别",
    "a1": "调研完成",
    "a2": "阻力分析通过",
    "a3": "大师评审通过",
    "a4": "验证通过",
    "a5": "执行完成"
  },
  "scores": {
    "macro": 75,
    "technical": 68,
    "sentiment": 72
  },
  "gatekeepers": {
    "pretrade": "PASS",
    "a7": "PASS"
  },
  "result": {
    "outcome": "PROFIT",
    "pnl": 150.5,
    "exit_reason": "TAKE_PROFIT"
  },
  "lessons": ["lesson_001", "lesson_002"]
}
```

### 4. Lesson记忆

**定位**: 从Episode蒸馏的规则

**内容**:
- 规则 (Rule)
- 禁令 (Forbidden)
- 偏好 (Preference)
- 阈值 (Threshold)

**存储位置**:
```
~/.workbuddy/memory/lessons/
lesson_{category}_{id}.md
```

**格式**:
```markdown
# Lesson: OKX_API_001

## 类型
- category: technical_learning
- severity: HIGH
- frequency: 5

## 规则内容
OKX CLI命令使用`okx`而非`okx-trade`

## 来源Episode
- ep_20260510_090000
- ep_20260512_143000

## 验证状态
- validated: true
- validated_at: 2026-05-14
```

---

## 🔧 核心SKILL

### 记忆管理SKILL

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `memory-manager` | 压缩检测/快照 | 记忆管理 |
| `memory-distiller` | 蒸馏瘦身 | 记忆蒸馏 |
| `memory-setup` | 初始化配置 | 记忆设置 |
| `memory-session-index` | 索引召回 | 索引检索 |
| `memory-budget-policy` | 配额策略 | 配额管理 |
| `memory-context-fencing` | 围栏防护 | 围栏注入 |

### 学习进化SKILL

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `learning-episode-writer` | 决策固化 | Episode记录 |
| `learning-lesson-distiller` | 经验蒸馏 | Lesson蒸馏 |
| `learning-proposal-generator` | 变更提案 | 提案生成 |
| `learning-recall-pack` | 经验召回 | 上下文包 |
| `self-improving` | 自我改进 | 持续学习 |
| `capability-evolver` | 能力进化 | 协议进化 |

### 知识管理SKILL

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `dream-knowledge` | 知识库 | 策略库 |
| `ontology` | 知识图谱 | 实体关联 |
| `dream-data-analysis` | 数据分析 | 趋势分析 |

---

## 🔄 用户意图分析流程

```
用户输入
        ↓
┌───────────────────────────┐
│ memory-context-fencing    │  ← 围栏防护
│ 1. 污染检测               │
│ 2. 上下文注入              │
│ 3. 意图分类               │
└───────────┬───────────────┘
            ↓
┌───────────────────────────┐
│ learning-recall-pack      │  ← 经验召回
│ 1. 检索相关Lesson         │
│ 2. 构建上下文包           │
│ 3. 注入证据引用           │
└───────────┬───────────────┘
            ↓
┌───────────────────────────┐
│ dream-strategy-parser    │  ← 策略解析
│ 1. Regime检测             │
│ 2. 工具映射               │
│ 3. 指令生成               │
└───────────┬───────────────┘
            ↓
┌───────────────────────────┐
│ SKILL Router             │  ← SKILL路由
│ A0-A9 / 治理 / 记忆      │
└───────────┬───────────────┘
            ↓
        执行输出
```

---

## 📊 存储结构

### 用户级记忆

```
~/.workbuddy/
├── memory/
│   ├── MEMORY.md              # 长期记忆
│   ├── 2026-05-14.md          # 每日日志
│   ├── distillation/          # 蒸馏状态
│   └── lessons/               # Lesson库
│       ├── technical_*.md
│       ├── strategic_*.md
│       └── ...
├── skills/
│   ├── memory-manager/
│   ├── memory-distiller/
│   ├── learning-episode-writer/
│   └── ...
└── artifacts/                 # 产物中台
```

### 工作区记忆

```
/Users/zhangjiangtao/WorkBuddy/{workspace}/
├── .workbuddy/
│   ├── memory/
│   │   ├── MEMORY.md         # 工作区长期记忆
│   │   ├── 2026-05-14.md     # 工作区每日日志
│   │   └── ...
│   └── skills/               # 项目级SKILL
└── episodes/                 # Episode存储
```

---

## 🎯 核心目标

1. **快速意图识别**: 用户一句话 → 精准调度SKILL
2. **上下文连贯**: 跨session记忆用户偏好
3. **自我进化**: 从错误中学习，避免重复
4. **噪声控制**: 防止记忆膨胀和污染
5. **证据追溯**: 每条结论有据可查

---

## 🔧 维护机制

### 记忆蒸馏

```
触发条件:
- 每日17:00自动
- Episode数量 > 50
- 手动触发 "蒸馏记忆"

蒸馏流程:
1. 扫描Episode
2. 识别模式
3. 蒸馏Lesson
4. 清理过期Episode
5. 更新MEMORY.md
```

### 配额管理

| 记忆类型 | 配额 | 淘汰策略 |
|----------|------|----------|
| MEMORY.md | 无限制 | 手动清理 |
| 每日日志 | 30天 | LRU淘汰 |
| Episode | 100个 | 时间+重要性 |
| Lesson | 50个 | 频次+验证 |

---

## 🚀 快速链接

- [SKILL完整索引](../1-ARCHITECTURE/工作索引/SKILL_INDEX.md)
- [部门矩阵](../1-ARCHITECTURE/工作索引/DEPARTMENT_MATRIX.md)
- [工具映射](../1-ARCHITECTURE/工作索引/TOOL_MAPPING.md)
