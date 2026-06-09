# 底层记忆系统

> **版本**: v1.0  
> **创建日期**: 2026-05-14

---

## 🧠 系统概述

底层记忆系统用于存储记忆、复盘、自我学习与进化，核心针对**用户意图分析**和**交易路由**，以便根据用户需求快速调度交易A系SKILL，形成针对性输出。

---

## 📁 记忆类型

### 1️⃣ 长期记忆 (MEMORY.md)
- 用户偏好和背景
- 项目配置和约定
- 核心教训和经验
- 战略决策历史

### 2️⃣ 每日记忆 (YYYY-MM-DD.md)
- 当日工作日志
- 任务执行记录
- 决策快照
- 临时信息

### 3️⃣ Episode记忆
- 交易决策记录
- 执行结果归因
- 评分和门禁日志

### 4️⃣ Lesson记忆
- 蒸馏的经验规则
- 禁令清单
- 偏好设置

---

## 📁 SKILL清单

### 记忆管理

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `memory-manager` | 压缩检测/快照 | 记忆管理 |
| `memory-distiller` | 蒸馏瘦身 | 记忆蒸馏 |
| `memory-setup` | 初始化配置 | 记忆设置 |
| `memory-session-index` | 索引召回 | 索引检索 |
| `memory-budget-policy` | 配额策略 | 配额管理 |
| `memory-context-fencing` | 围栏防护 | 围栏注入 |

### 学习进化

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `learning-episode-writer` | 决策固化 | Episode记录 |
| `learning-lesson-distiller` | 经验蒸馏 | Lesson蒸馏 |
| `learning-proposal-generator` | 变更提案 | 提案生成 |
| `learning-recall-pack` | 经验召回 | 上下文包 |
| `self-improving` | 自我改进 | 持续学习 |
| `capability-evolver` | 能力进化 | 协议进化 |

### 知识管理

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `dream-knowledge` | 知识库 | 策略库 |
| `ontology` | 知识图谱 | 实体关联 |
| `dream-data-analysis` | 数据分析 | 趋势分析 |

---

## 🔄 用户意图分析流程

```
用户输入 → 意图识别 → SKILL路由 → 执行调度 → 结果输出
              ↓
        memory-context-fencing
              ↓
        learning-recall-pack
              ↓
        A0-A9流水线
```

---

## 📂 存储结构

```
~/.workbuddy/
├── memory/
│   ├── MEMORY.md              # 长期记忆
│   ├── YYYY-MM-DD.md          # 每日日志
│   └── distillation/          # 蒸馏状态
├── skills/                    # SKILL定义
│   ├── memory-*/
│   ├── learning-*/
│   └── dream-knowledge/
└── .workbuddy/
    └── memory/                # 工作区记忆
```

---

## 🎯 核心目标

1. **快速意图识别**: 用户一句话 → 精准调度SKILL
2. **上下文连贯**: 跨session记忆用户偏好
3. **自我进化**: 从错误中学习，避免重复
4. **噪声控制**: 防止记忆膨胀和污染
