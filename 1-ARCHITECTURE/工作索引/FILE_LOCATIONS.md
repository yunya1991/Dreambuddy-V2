# 核心文件位置索引

> **版本**: v1.0  
> **更新日期**: 2026-05-14

---

## 📂 用户前端 (Dream Universal Gateway)

```
/Users/zhangjiangtao/WorkBuddy/dreambuddy-v1/3-FRONTEND/dream-universal-gateway/
├── src/
│   ├── app/
│   │   ├── api/auth/[...nextauth]/
│   │   ├── api/chat/
│   │   ├── api/task/
│   │   ├── login/
│   │   ├── register/
│   │   └── dashboard/
│   ├── stores/
│   │   ├── auth-store.ts
│   │   ├── chat-store.ts
│   │   └── config-store.ts
│   └── lib/
│       ├── auth.ts
│       └── task-manager.ts
├── docs/                          # 18个设计文档
└── prisma/
```

---

## 📂 SKILL存储

```
~/.workbuddy/skills/               # 用户级SKILL (全局)
├── dream-governance-manager/
├── dream-exit-skill-v2/
├── dream-intelligence-monitor/
├── memory-manager/
├── learning-episode-writer/
├── dream-hr-recruitment/
├── boss-secretary/
└── ... (80+ SKILL)
```

---

## 📂 工作区SKILL

```
/Users/zhangjiangtao/WorkBuddy/20260415144304/.workbuddy/skills/
├── boss-secretary/
├── dream-bailian-integration/
└── dream-exit-skill-v2/
```

---

## 📂 交易核心系统

```
/Users/zhangjiangtao/WorkBuddy/20260415144304/
├── 1-TRADE/                       # 交易研究
│   ├── A7-practice-theory/
│   ├── A8-theory-practice-verification/
│   ├── dream-exit-skill-v2/
│   ├── dream-pretrade-gatekeeper/
│   └── dream-strategy-designer/
├── 2-INTELLIGENCE/               # 情报监控
│   ├── dream-bailian-integration/
│   ├── dream-data-analysis/
│   ├── dream-knowledge/
│   └── master-seminar/
└── 3-SUPPORT/                    # 支持系统
    ├── ai-trading-compliance/
    └── boss-secretary/
```

---

## 📂 记忆系统

```
~/.workbuddy/
├── memory/
│   ├── MEMORY.md                 # 长期记忆
│   ├── YYYY-MM-DD.md             # 每日日志
│   └── distillation/             # 蒸馏状态
└── .workbuddy/
    └── memory/                   # 工作区记忆
```

---

## 📂 产物中台

```
/Users/zhangjiangtao/WorkBuddy/20260415144304/.workbuddy/
├── mailbox/
│   ├── secretary/                # 秘书邮箱
│   └── inbox/                    # 待处理
├── skills/boss-secretary/
│   ├── reports/                  # 报告归档
│   ├── knowledge/                # 知识库
│   └── scripts/
└── automations/                  # 自动化任务
```

---

## 📂 核心配置文件

```
~/.workbuddy/
├── SOUL.md                       # 系统灵魂
├── IDENTITY.md                   # 身份定义
├── USER.md                       # 用户信息
└── MCP.json                      # MCP配置

/Users/zhangjiangtao/WorkBuddy/20260415144304/
├── WORKSPACE/
│   └── MEMORY.md                 # 工作区记忆
└── .workbuddy/
    └── memory/
        └── MEMORY.md             # 长期记忆
```

---

## 📂 OKX交易工具

```
~/.workbuddy/
└── bin/
    └── okx-trade-cli             # OKX交易CLI v1.3.1

/Users/zhangjiangtao/WorkBuddy/20260415144304/
├── scripts/
│   ├── okx_unified_toolkit.py    # 统一工具包
│   └── task_poller.py            # 任务轮询
└── knowledge_base/
    ├── exit/                      # 离场策略库
    └── regime_patterns/           # Regime知识库
```

---

## 📂 架构输出

```
/Users/zhangjiangtao/WorkBuddy/20260415144304/dream-multiSkill-architecture/
├── README.md                     # 总览
├── 1-ARCHITECTURE/               # 架构设计
│   ├── 中台设计/
│   ├── 前端设计/
│   ├── 工作索引/
│   └── FAQ/
├── 2-GOVERNANCE/                 # 治理系统
├── 3-FRONTEND/                   # 前端系统
├── 4-MEMORY/                     # 记忆系统
├── 5-BUSINESS/                   # 业务管理
└── 6-TRADING/                    # 交易系统
```
