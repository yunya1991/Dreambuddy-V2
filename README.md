# Dream-MultiSkill

> AI驱动的加密货币交易决策系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-2.0-blue.svg)](./VERSION)

---

## 🏛️ 项目概述

Dream-MultiSkill 是一个基于 AI Agent 的加密货币交易决策系统，采用多智能体架构，包含：

- **交易研究系统**: A0-A9 九步决策流水线
- **产物中台**: 统一产物管理与投递
- **治理合规系统**: 合规审查、门禁、审计
- **记忆学习系统**: 跨session记忆、进化
- **业务管理系统**: HR、运营、成本控制

---

## 📁 目录结构

```
dream-multiSkill-architecture/
│
├── 1-ARCHITECTURE/           # 架构设计文档
│   ├── 中台设计/             # 产物中台、网关中台
│   ├── 前端设计/             # 用户前端系统
│   ├── 工作索引/             # SKILL索引、工具映射
│   └── FAQ/                 # 常见问题
│
├── 2-GOVERNANCE/            # 中台治理系统
│   ├── GOVERNANCE_CHARTER.md
│   ├── GOVERNANCE_SYSTEM.md
│   ├── COMPLIANCE_RULES.md
│   └── AUDIT_LOGS.md
│
├── 3-FRONTEND/              # 用户前端（文档 + 工程）
│   ├── dream-universal-gateway/    # 🌐 用户前端 (Next.js + TypeScript)
│   │   ├── src/                   # 源码
│   │   ├── prisma/                # 数据库模型
│   │   ├── docs/                  # 设计文档
│   │   ├── package.json           # 依赖配置
│   │   └── .env.example           # 环境变量模板
│   ├── FRONTEND_SYSTEM.md
│   └── README.md
│
├── 4-MEMORY/                # 底层记忆系统
│   └── MEMORY_SYSTEM.md
│
├── 5-BUSINESS/              # 业务管理系统
│   └── BUSINESS_SYSTEM.md
│
├── 6-TRADING/               # 交易研究系统(A0-A9)
│   ├── TRADING_SYSTEM.md
│   └── A_SERIES_DETAIL.md
│
└── 7-ARTIFACT_HUB/         # 产物中台
    ├── ARTIFACT_HUB.md
    └── README.md
```

---

## 🔑 核心系统

### 1. 交易研究系统 (A0-A9)

```
用户输入 → A0矛盾分析 → A1深度调研 → A2第一性原理 → A3沙盘推演
    → A4战术验证 → A5决策执行 → A6情报监控 → A7实践门禁 → A9离场
```

**核心SKILL**: `dream-contradiction-theory`, `dream-strategy-research`, `dream-first-principles`, `master-seminar`, `dream-tactical-validator`, `dream-tactical-executor`, `dream-intelligence-monitor`, `A7-practice-theory`, `A8-theory-practice-verification`, `dream-exit-skill-v2`

### 2. 产物中台 (Artifact Hub)

统一管理所有AI执行产物，支持邮件路由、产物投递、归档管理。

## 🤝 AGENT 协作（入口）

仓库内的 AGENT 协作规则、流程与协议主入口位于：

- `AGENT协作工具/docs/README.md`

广播（作为各 AGENT 记忆固定引用）：

- 协作宪法（允许/禁止/裁决，fail-closed）：`AGENT协作工具/docs/00-AGENT-CONSTITUTION.md`
- 协作协议（PR 评论锚点 + 门禁）：`AGENT协作工具/docs/01-COLLABORATION-PROTOCOL.md`
- 工程索引（改哪里/查哪里）：`AGENT协作工具/docs/04-ENGINEERING-INDEX.md`
- FAQ（常见阻塞与修复）：`AGENT协作工具/docs/05-FAQ.md`
- SKILL 清单（什么时候调用什么）：`AGENT协作工具/docs/06-SKILLS-INVENTORY.md`

当前默认协作方式：

- 以 `7-ARTIFACT-HUB-V2/**` 为核心工作区
- 每个 AGENT 自建 `agent/*` 分支并提交独立 PR
- 协作职责拆分为“账本协议AGENT（维护任务清单与协议文档）”与“治理AGENT（合并门禁与冲突收口）”

**依赖**:
- `~/.workbuddy/artifacts/` - 产物存储目录
- `~/.workbuddy/scripts/sync_artifact.py` - 同步脚本
- `~/.workbuddy/skills/artifact-alignment-manager/` - AAM SKILL

### 3. Dream Universal Gateway

用户端前端系统，提供：
- 用户认证 (邮箱注册/登录)
- API配置管理
- 交易参数设置
- 任务调度
- 产物查看
- 积分管理

---

## 🚀 快速开始

### 环境要求

- Node.js >= 18
- Python >= 3.10
- PostgreSQL >= 14
- pnpm >= 8

### 1. 克隆项目

```bash
git clone https://github.com/your-org/dream-multiSkill.git
cd dream-multiSkill
```

### 2. 安装前端依赖

```bash
cd 3-FRONTEND/dream-universal-gateway
pnpm install
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填写配置
```

**必需的环境变量**:
```env
DATABASE_URL="file:./dev.db"
NEXTAUTH_URL="http://localhost:3456"
NEXTAUTH_SECRET="your-secret-key"
ENCRYPTION_KEY="your-32-char-key"
WORKBUDDY_WS_URL="ws://localhost:8080"
WORKBUDDY_API_URL="http://localhost:8080"
```

### 4. 初始化数据库

```bash
pnpm db:push    # 创建/更新数据库表
pnpm db:studio  # 可选：查看数据库
```

### 5. 启动开发服务器

```bash
pnpm dev
# 访问 http://localhost:3456
```

### 6. 配置产物中台

```bash
# 创建产物存储目录
mkdir -p ~/.workbuddy/artifacts/{trading,memory,governance,knowledge,evolution}

# 初始化索引文件
echo '{"last_updated":"","count":0,"items":[]}' > ~/.workbuddy/artifacts/trading/index.json

# 复制 AAM SKILL (如需要)
cp -r skills/artifact-alignment-manager ~/.workbuddy/skills/
```

---

## 📚 文档

| 模块 | 文档 | 描述 |
|------|------|------|
| 用户前端 | [dream-universal-gateway/README.md](./3-FRONTEND/dream-universal-gateway/README.md) | Next.js项目说明 |
| 用户前端 | [3-FRONTEND/FRONTEND_SYSTEM.md](./3-FRONTEND/FRONTEND_SYSTEM.md) | 前端系统设计 |
| 产物中台 | [7-ARTIFACT_HUB/ARTIFACT_HUB.md](./7-ARTIFACT_HUB/ARTIFACT_HUB.md) | 产物中台设计 |
| 架构设计 | [1-ARCHITECTURE/README.md](./1-ARCHITECTURE/README.md) | 整体架构 |
| 治理系统 | [2-GOVERNANCE/README.md](./2-GOVERNANCE/README.md) | 治理合规 |
| 记忆系统 | [4-MEMORY/README.md](./4-MEMORY/README.md) | 记忆学习 |
| 业务管理 | [5-BUSINESS/README.md](./5-BUSINESS/README.md) | 业务运营 |
| 交易系统 | [6-TRADING/README.md](./6-TRADING/README.md) | 交易研究 |
| FAQ | [1-ARCHITECTURE/FAQ/README.md](./1-ARCHITECTURE/FAQ/README.md) | 常见问题 |

---

## 🤝 贡献

请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md) 了解贡献流程。

### 贡献流程

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'feat: Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

### 代码规范

- 使用 TypeScript 严格模式
- 遵循 ESLint 配置
- 使用 Conventional Commits 提交规范
- 确保 `pnpm lint` 和 `pnpm type-check` 通过

---

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](./LICENSE) 文件了解详情。

---

## 🙏 致谢

- [WorkBuddy](https://www.codebuddy.cn/) - AI协作平台
- [OKX](https://www.okx.com/) - 交易所API
- [Tavily](https://tavily.com/) - AI搜索服务
