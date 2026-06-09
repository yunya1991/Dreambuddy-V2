# 业务管理系统

> **版本**: v1.0  
> **创建日期**: 2026-05-14

---

## 🏢 系统概述

业务管理系统涵盖公司除核心交易系统外的其他部门，包括HR/招聘、绩效考核、运营管理、成本控制、文档协作等。

---

## 📊 部门分类

### 1️⃣ 人力资源部 (HR)

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `dream-hr-recruitment` | 技能搜索/招聘/入职 | 招聘、技能市场 |
| `dream-performance-review` | KPI评分/PIP计划 | 绩效考核、评分 |

### 2️⃣ 运营管理部 (COO)

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `dream-operation-director` | 流程优化/跨部门协调 | 协调、流程 |
| `dream-task-creator` | 任务创建/调度 | 定时任务、自动化 |
| `auto-repair` | 系统健康检查 | 自动修复 |

### 3️⃣ 成本控制部 (CFO)

| SKILL | 功能 | 触发词 |
|-------|------|--------|
| `dream-cost-control` | 预算控制/ROI评估 | 成本、预算、收益 |
| `dream-execution-cost-model` | 交易成本分析 | 手续费、滑点 |

### 4️⃣ 文档协作部

| SKILL | 功能 |
|-------|------|
| `boss-secretary` | 老板秘书/邮件路由/日报 |
| `腾讯文档` | 腾讯文档协作 |
| `notion` | Notion笔记 |

### 5️⃣ 会议管理部

| SKILL | 功能 |
|-------|------|
| `腾讯会议` | 预约/录制/纪要 |

---

## 📂 目录结构

```
5-BUSINESS/
├── HR/
│   ├── RECRUITMENT.md         # 招聘流程
│   └── PERFORMANCE.md         # 绩效考核
├── OPERATIONS/
│   ├── TASK_MANAGEMENT.md     # 任务管理
│   └── PROCESS_OPTIMIZATION.md # 流程优化
├── FINANCE/
│   └── COST_CONTROL.md        # 成本控制
└── ADMIN/
    ├── SECRETARY.md           # 秘书系统
    └── DOCUMENTATION.md      # 文档协作
```

---

## 🔄 部门协作流程

```
用户请求
    ↓
dream-operation-director (协调)
    ↓
    ├── dream-hr-recruitment (人力)
    ├── dream-cost-control (财务)
    └── boss-secretary (行政)
```

---

## 📋 绩效考核矩阵

| 维度 | 权重 | SKILL覆盖 |
|------|------|-----------|
| 执行效率 | 30% | dream-task-creator |
| 质量评分 | 30% | dream-performance-review |
| 成本控制 | 20% | dream-cost-control |
| 团队协作 | 20% | dream-operation-director |

---

## 🎯 核心目标

1. **高效协作**: 跨部门流程自动化
2. **成本可控**: 预算执行监控
3. **人才发展**: 技能升级和招聘
4. **持续优化**: 流程改进和迭代
