# 中台治理系统

> **版本**: v1.0  
> **创建日期**: 2026-05-14

---

## 🏛️ 系统概述

中台治理系统负责整个Dream-MultiSkill的合规审查、门禁管理、违规处理和流程规范化。

---

## 📁 核心SKILL

### 治理管理
| SKILL | 路径 | 描述 |
|-------|------|------|
| `dream-governance-manager` | `~/.workbuddy/skills/dream-governance-manager/` | 治理管理部，四步法 |
| `ai-trading-compliance` | `~/.workbuddy/skills/ai-trading-compliance/` | AI交易合规审查v2.0 |

### 门禁/验证
| SKILL | 路径 | 描述 |
|-------|------|------|
| `hermes-shadow-verification-gate` | `~/.workbuddy/skills/hermes-shadow-verification-gate/` | 影子验证门 |
| `hermes-skill-governance` | `~/.workbuddy/skills/hermes-skill-governance/` | SKILL治理门 |

### 回滚/审计
| SKILL | 路径 | 描述 |
|-------|------|------|
| `hermes-rollback-actuator` | `~/.workbuddy/skills/hermes-rollback-actuator/` | 回滚执行器 |
| `dream-posttrade-mrm-audit` | `~/.workbuddy/skills/dream-posttrade-mrm-audit/` | 盘后MRM审计 |

### 秘书系统
| SKILL | 路径 | 描述 |
|-------|------|------|
| `boss-secretary` | `~/.workbuddy/skills/boss-secretary/` | 老板秘书 |
| `artifact-alignment-manager` | `~/.workbuddy/skills/artifact-alignment-manager/` | 产物管理 |

---

## 🔧 四步法流程

```
Step1: FAQ自愈
   ↓
Step2: 治理文档检索
   ↓
Step3: 联网搜索
   ↓
Step4: 自主分析
```

---

## ⚖️ 违规处理矩阵

| 违规类型 | 级别 | 处罚 |
|----------|------|------|
| V001 | 警告 | 口头警告 |
| V002 | 记过 | 书面记录 |
| V003 | 绩效影响 | 扣分处理 |
| V004 | 审计标记 | 重点监控 |
| V005 | 暂停权限 | 临时冻结 |
| V006 | 开除 | 终止服务 |

---

## 📂 文档结构

```
2-GOVERNANCE/
├── SKILL.md                  # 治理SKILL说明
├── GOVERNANCE_CHARTER.md     # 治理章程
├── COMPLIANCE_RULES.md       # 合规规则
├── AUDIT_LOGS.md             # 审计日志
└── VIOLATION_RECORDS.md      # 违规记录
```

---

## 🔗 联动系统

- **交易系统** ← 合规审查前门
- **产物中台** ← 产物投递验证
- **记忆系统** ← 记忆围栏防护
