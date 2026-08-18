# 治理章程

> **版本**: v2.9  
> **更新日期**: 2026-05-14

---

## 📜 总则

Dream-MultiSkill采用多层治理架构，确保系统运行合规、透明、可审计。

---

## 🏛️ 治理架构

```
┌─────────────────────────────────────────┐
│              宪法层 (Constitution)       │
├─────────────────────────────────────────┤
│  dream-constitution - 系统最高指导文件     │
└─────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────┐
│              治理层 (Governance)          │
├─────────────────────────────────────────┤
│  dream-governance-manager              │
│  ai-trading-compliance                 │
│  hermes-skill-governance               │
└─────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────┐
│              门禁层 (Gatekeepers)         │
├─────────────────────────────────────────┤
│  dream-pretrade-gatekeeper             │
│  hermes-shadow-verification-gate        │
│  A7-practice-theory                    │
└─────────────────────────────────────────┘
```

---

## ⚖️ 违规类型与处罚

| 代码 | 类型 | 描述 | 处罚 |
|------|------|------|------|
| V001 | 轻微 | 首次轻微违规 | 口头警告 |
| V002 | 一般 | 重复轻微违规 | 书面记过 |
| V003 | 较重 | 影响执行效率 | 绩效扣分 |
| V004 | 严重 | 触发风险事件 | 审计标记 |
| V005 | 重大 | 系统性失误 | 暂停权限 |
| V006 | 极重 | 严重违规行为 | 终止服务 |

---

## 🔧 四步法流程

### Step 1: FAQ自愈
检查`FAQ/`目录下是否有相关问题的标准答案。

### Step 2: 治理文档检索
检索`governance_docs/`目录下的治理文档。

### Step 3: 联网搜索
使用`tavily`进行外部信息搜索。

### Step 4: 自主分析
基于已有知识进行推理分析。

---

## 📋 合规审查标准

### AI交易合规
- 策略需通过`ai-trading-compliance`审查
- 输出: PASS / WARN / FAIL

### 提案验证
- 变更前需通过影子验证
- 必须携带`rollback_plan_id`

### 执行监控
- HIGH/CRITICAL风险需人工确认
- LOW/MEDIUM自动执行

---

## 📂 文档结构

```
dream-governance-manager/
├── SKILL.md                    # SKILL定义
├── governance_docs/
│   ├── CHARTER.md              # 治理章程
│   ├── MANUAL.md               # 操作手册
│   ├── DEPARTMENT_RULES.md     # 部门规则
│   ├── SKILL_STANDARDS.md      # SKILL标准
│   └── VIOLATION_TYPES.md      # 违规类型
├── compliance_audit/            # 合规审计
│   ├── audit_checklist.md
│   └── audit_report_*.md
└── penalties/                  # 处罚记录
    └── penalty_records.md
```
