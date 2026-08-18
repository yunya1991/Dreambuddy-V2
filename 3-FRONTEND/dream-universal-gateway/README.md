# Dream Universal Gateway

> Dream-MultiSkill 系统的用户端前端

[![Next.js](https://img.shields.io/badge/Next.js-14-black)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-blue)](https://www.typescriptlang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🏛️ 项目定位

Dream Universal Gateway 是 Dream-MultiSkill 系统的用户端前端，提供：

- **用户认证**: 邮箱注册/登录/JWT Token
- **配置管理**: API配置/交易参数/策略设置
- **任务调度**: 定时任务/即时任务
- **产物查看**: 报告/图表/统计数据
- **积分管理**: 积分余额/消耗记录

---

## 📁 项目结构

```
dream-universal-gateway/
├── src/
│   ├── app/                      # Next.js App Router
│   │   ├── page.tsx             # 首页
│   │   ├── layout.tsx           # 根布局
│   │   ├── login/               # 登录页
│   │   ├── register/            # 注册页
│   │   ├── dashboard/           # Dashboard
│   │   └── api/                 # API路由
│   │       ├── auth/            # 认证API
│   │       ├── task/            # 任务API
│   │       ├── chat/            # 聊天API
│   │       └── market/          # 市场数据API
│   │
│   ├── components/              # UI组件库
│   │   ├── ui/                 # 基础组件
│   │   ├── layout/             # 布局组件
│   │   ├── auth/               # 认证组件
│   │   └── dashboard/          # Dashboard组件
│   │
│   ├── stores/                  # 状态管理 (Zustand)
│   │   ├── auth-store.ts       # 认证状态
│   │   ├── chat-store.ts       # 聊天状态
│   │   ├── config-store.ts     # 配置状态
│   │   ├── credits-store.ts    # 积分状态
│   │   └── ui-store.ts         # UI状态
│   │
│   ├── lib/                     # 核心库
│   │   ├── auth.ts             # 认证工具
│   │   ├── prisma.ts           # Prisma客户端
│   │   ├── task-manager.ts     # 任务管理
│   │   └── encryption.ts       # 加密工具
│   │
│   ├── types/                   # 类型定义
│   └── middleware.ts            # 中间件
│
├── prisma/
│   └── schema.prisma           # 数据库模型
│
├── public/                     # 静态资源
│
├── docs/                       # 设计文档
│
├── package.json
├── tsconfig.json
├── next.config.ts
└── .env.example                # 环境变量模板
```

---

## 🚀 快速开始

### 环境要求

- Node.js >= 18
- pnpm >= 8
- PostgreSQL >= 14 (可选，用于生产环境)

### 1. 安装依赖

```bash
pnpm install
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

**必需的环境变量**:

```env
# 数据库
DATABASE_URL="file:./dev.db"

# NextAuth
NEXTAUTH_URL="http://localhost:3456"
NEXTAUTH_SECRET="your-secret-key-min-32-chars"

# 加密
ENCRYPTION_KEY="your-32-char-encryption-key"

# WorkBuddy集成
WORKBUDDY_WS_URL="ws://localhost:8080"
WORKBUDDY_API_URL="http://localhost:8080"
```

### 3. 初始化数据库

```bash
# 开发环境 (SQLite)
pnpm db:push

# 或使用 PostgreSQL
DATABASE_URL="postgresql://user:pass@localhost:5432/gateway" pnpm db:push
```

### 4. 启动开发服务器

```bash
pnpm dev
# 访问 http://localhost:3456
```

### 5. 构建生产版本

```bash
pnpm build
pnpm start
```

---

## 🎯 核心功能

### 用户认证

- 邮箱注册/登录
- JWT Token 认证
- 密码加密 (bcrypt)
- 会话管理

### 配置管理

- OKX API Key 管理
- API 状态检测
- 密钥加密存储

### 交易参数

- 交易对选择
- 仓位管理
- 杠杆配置
- 止损止盈

### 策略设置

- 策略模板选择
- 参数自定义
- 定时任务调度

### 积分系统

- 积分余额查询
- 积分消耗记录
- 档位管理

---

## 🔧 技术栈

| 技术 | 用途 |
|------|------|
| Next.js 14 | 框架 |
| TypeScript | 类型系统 |
| Zustand | 状态管理 |
| Prisma | ORM |
| Tailwind CSS | 样式 |
| jose | JWT |
| bcrypt | 密码加密 |

---

## 🔗 相关文档

- [前端系统设计](../3-FRONTEND/FRONTEND_SYSTEM.md)
- [网关中台设计](../1-ARCHITECTURE/中台设计/GATEWAY_HUB.md)
- [产物中台设计](../7-ARTIFACT_HUB/ARTIFACT_HUB.md)
- [项目总览](../README.md)

---

## 📄 许可证

MIT License - 详见项目根目录 LICENSE 文件
