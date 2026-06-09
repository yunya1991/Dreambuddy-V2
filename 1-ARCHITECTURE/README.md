# 架构设计总览

> **版本**: v2.0
> **更新日期**: 2026-05-16

---

## 🏛️ 六大核心系统

Dream-MultiSkill架构由六大核心系统组成：

| 系统 | 目录 | 描述 |
|------|------|------|
| 架构设计 | `1-ARCHITECTURE/` | 架构文档+设计文档+索引 |
| 治理系统 | `2-GOVERNANCE/` | 合规+门禁+审计 |
| 前端系统 | `3-FRONTEND/` | 用户界面 |
| 记忆系统 | `4-MEMORY/` | 记忆+学习+进化 |
| 业务管理 | `5-BUSINESS/` | HR+运营+成本 |
| 交易系统 | `6-TRADING/` | A0-A9交易流水线 |

---

## 🧠 公司中枢方向

自 `2026-05-16` 起，`7-ARTIFACT-HUB-V2` 的定位从“产物中台 + 路由服务”升级为“公司治理架构驱动的 AI 中枢”。

它不再只服务产物索引和路由，而是开始统一承接：

- 研究中台；
- 市场化中台；
- 交易链路监控；
- 治理控制台；
- HR 绩效与组织优化；
- 市场情报与外部竞争；
- 六人董事会（治理委员会）与人工审批。

相关文档：

- [公司中枢设计](./中台设计/COMPANY_CENTRAL_HUB.md)
- [治理中枢化设计](../docs/superpowers/specs/2026-05-16-artifact-hub-v2-governance-central-design.md)

---

## 📐 架构层次

```
┌─────────────────────────────────────────────────────────────┐
│                    用户交互层                                 │
│  Gateway / Feed / Chain / Ops / 市场化中台 / 董事会台         │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                 公司中枢 / 中台治理层                           │
│  Artifact Hub V2 / Query / Route / Trace / Audit / Approval  │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    决策执行层                                 │
│  研究链路 / 双交易工作流 / 分发执行 / 审计回放                 │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    支撑服务层                                 │
│  治理部 / HR / 市场部 / 记忆系统 / 业务管理 / 外部集成          │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    基础设施层                                 │
│  dreambuddy artifacts/meta/config / OKX / LLM / DB / 外部渠道 │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔗 四大协作闭环

### 闭环1: 交易决策闭环

```
A1调研 → A2分析 → A3推演 → A4验证 → A5执行 → A6监控 → A7门禁 → A1迭代
```

### 闭环2: 学习进化闭环

```
Episode记录 → Lesson蒸馏 → Proposal生成 → 验证门禁 → 实施执行 → A8复盘
```

### 闭环3: 治理合规闭环

```
合规审查 → 影子验证 → 执行监控 → 审计归因 → 持续改进
```

### 闭环4: 组织进化闭环

```
市场部发现机会/威胁 → 研究部调研 → 交易部执行验证 → 运营部分发 →
治理部审计/解释 → HR 绩效评估/招聘/优化 → 董事会治理 → 人工审批
```

---

## 📊 SKILL分类

| 类别 | 数量 | 核心SKILL |
|------|------|-----------|
| 交易研究(A0-A9) | 15+ | dream-strategy-research, dream-first-principles... |
| 治理合规 | 12+ | dream-governance-manager, ai-trading-compliance... |
| 记忆学习 | 12+ | memory-manager, learning-episode-writer... |
| 业务管理 | 8+ | dream-hr-recruitment, dream-operation-director... |
| 外部集成 | 15+ | tavily, telegram, 腾讯文档... |
| 前端工具 | 5+ | gateway, bailian-integration... |

---

## 📁 文档分类索引

### 1-ARCHITECTURE/ 架构设计

```
1-ARCHITECTURE/
├── 中台设计/                    # 产物中台、网关中台
│   ├── README.md
│   ├── PRODUCT_HUB.md          # 基础设计
│   ├── PRODUCT_HUB_FULL.md      # 完整设计
│   └── GATEWAY_HUB.md           # 网关设计
├── 前端设计/                    # 用户前端系统
│   ├── README.md
│   ├── ARCHITECTURE.md
│   ├── FRONTEND_ARCHITECTURE.md
│   ├── USER_SYSTEM_DESIGN.md
│   ├── API_CONFIG_DESIGN.md
│   ├── TRADING_CONFIG_DESIGN.md
│   ├── STRATEGY_CONFIG_DESIGN.md
│   ├── CHANNEL_DESIGN.md
│   ├── INTENT_ROUTER.md
│   ├── UI_SPEC.md
│   ├── UI_ROADMAP.md
│   ├── FRONTEND_WB_INTEGRATION.md
│   ├── CHAIN_ORCHESTRATOR.md
│   └── TECH_STACK_EVALUATION.md
├── 工作索引/                    # SKILL索引、工具映射
│   ├── README.md
│   ├── SKILL_INDEX.md          # 完整SKILL索引
│   ├── DEPARTMENT_MATRIX.md     # 部门矩阵
│   ├── FILE_LOCATIONS.md        # 文件位置
│   └── TOOL_MAPPING.md          # 工具映射
└── FAQ/                        # 常见问题
    ├── README.md
    ├── FAQ.md                   # 基础FAQ
    └── FAQ_FULL.md              # 完整FAQ
```

### 2-GOVERNANCE/ 治理系统

```
2-GOVERNANCE/
├── README.md
├── GOVERNANCE_CHARTER.md       # 治理章程
├── 核心SKILL/
│   ├── dream-governance-manager/
│   ├── ai-trading-compliance/
│   ├── hermes-shadow-verification-gate/
│   ├── hermes-skill-governance/
│   └── hermes-rollback-actuator/
└── 文档/
    └── compliance_checklist.md
```

### 3-FRONTEND/ 前端系统

```
3-FRONTEND/
├── README.md
└── dream-universal-gateway/
    ├── src/
    ├── docs/
    └── 配置/
```

### 4-MEMORY/ 记忆系统

```
4-MEMORY/
├── README.md
└── 核心SKILL/
    ├── memory-manager/
    ├── memory-distiller/
    ├── memory-session-index/
    ├── learning-episode-writer/
    ├── learning-lesson-distiller/
    └── learning-proposal-generator/
```

### 5-BUSINESS/ 业务管理

```
5-BUSINESS/
├── README.md
└── 核心SKILL/
    ├── dream-hr-recruitment/
    ├── dream-performance-review/
    ├── dream-operation-director/
    ├── dream-cost-control/
    └── auto-repair/
```

### 6-TRADING/ 交易系统

```
6-TRADING/
├── README.md
├── A_SERIES_DETAIL.md          # A0-A9详解
└── 核心SKILL/
    ├── dream-contradiction-theory/  (A0)
    ├── dream-strategy-research/     (A1)
    ├── dream-first-principles/      (A2)
    ├── master-seminar/              (A3)
    ├── dream-tactical-validator/    (A4)
    ├── dream-tactical-executor/     (A5)
    ├── dream-intelligence-monitor/  (A6)
    ├── A7-practice-theory/
    ├── A8-theory-practice-verification/
    └── dream-exit-skill-v2/         (A9)
```

---

## 🚀 快速导航

### 按需求导航

| 需求 | 文档 |
|------|------|
| 系统概览 | [README.md](./README.md) |
| SKILL索引 | [SKILL_INDEX.md](./工作索引/SKILL_INDEX.md) |
| 部门职责 | [DEPARTMENT_MATRIX.md](./工作索引/DEPARTMENT_MATRIX.md) |
| 产物中台 | [PRODUCT_HUB_FULL.md](./中台设计/PRODUCT_HUB_FULL.md) |
| 网关设计 | [GATEWAY_HUB.md](./中台设计/GATEWAY_HUB.md) |
| 前端架构 | [FRONTEND_ARCHITECTURE.md](./前端设计/FRONTEND_ARCHITECTURE.md) |
| A系流程 | [A_SERIES_DETAIL.md](../6-TRADING/A_SERIES_DETAIL.md) |
| 治理章程 | [GOVERNANCE_CHARTER.md](../2-GOVERNANCE/GOVERNANCE_CHARTER.md) |
| 常见问题 | [FAQ_FULL.md](./FAQ/FAQ_FULL.md) |
