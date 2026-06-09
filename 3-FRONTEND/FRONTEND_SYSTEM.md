# 用户前端系统完整设计

> **版本**: v2.0
> **更新日期**: 2026-05-14

---

## 🏛️ 系统定位

Dream Universal Gateway 是 Dream-MultiSkill 的用户端前端系统，提供：
- **用户认证**: 邮箱注册/登录/JWT Token
- **配置管理**: API配置/交易参数/策略设置
- **任务调度**: 定时任务/即时任务
- **产物查看**: 报告/图表/统计数据
- **积分管理**: 积分余额/消耗记录

---

## 📐 架构设计

### 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Dream Universal Gateway                   │
│                      Next.js 14 + TypeScript                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    UI层 (React)                       │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐            │   │
│  │  │Dashboard│  │Settings │  │Reports  │            │   │
│  │  │ 仪表盘  │  │ 设置页  │  │ 报告页  │            │   │
│  │  └─────────┘  └─────────┘  └─────────┘            │   │
│  └─────────────────────────────────────────────────────┘   │
│                             │                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  状态管理层 (Zustand)                  │   │
│  │  ┌────────────────────────────────────────────┐    │   │
│  │  │ auth │ chat │ config │ credits │ ui │session │    │   │
│  │  └────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────┘   │
│                             │                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  API层 (Next.js API Routes)           │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐            │   │
│  │  │ /auth   │  │ /task   │  │ /chat   │            │   │
│  │  └─────────┘  └─────────┘  └─────────┘            │   │
│  └─────────────────────────────────────────────────────┘   │
│                             │                               │
└─────────────────────────────┼───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                      外部服务层                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ WorkBuddy   │  │ 产物中台     │  │ 百炼API     │       │
│  │ 任务调度     │  │ Artifact Hub │  │ LLM服务     │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 目录结构

```
dream-universal-gateway/
├── src/
│   ├── app/                      # Next.js App Router
│   │   ├── layout.tsx           # 根布局
│   │   ├── page.tsx             # 首页
│   │   ├── globals.css          # 全局样式
│   │   │
│   │   ├── (auth)/             # 认证路由组
│   │   │   ├── login/
│   │   │   │   └── page.tsx
│   │   │   └── register/
│   │   │       └── page.tsx
│   │   │
│   │   ├── (dashboard)/        # Dashboard路由组
│   │   │   ├── page.tsx        # Dashboard首页
│   │   │   │
│   │   │   ├── settings/       # 设置模块
│   │   │   │   ├── page.tsx
│   │   │   │   ├── api-config/
│   │   │   │   ├── trading/
│   │   │   │   ├── strategy/
│   │   │   │   └── channels/
│   │   │   │
│   │   │   ├── reports/         # 报告模块
│   │   │   │   └── page.tsx
│   │   │   │
│   │   │   └── chat/           # 聊天模块
│   │   │       └── page.tsx
│   │   │
│   │   └── api/                 # API路由
│   │       ├── auth/
│   │       │   └── [...nextauth]/
│   │       │       └── route.ts
│   │       ├── task/
│   │       │   ├── route.ts
│   │       │   └── [taskId]/
│   │       │       └── route.ts
│   │       ├── chat/
│   │       │   └── route.ts
│   │       └── user/
│   │           └── me/
│   │               └── route.ts
│   │
│   ├── components/              # 组件库
│   │   ├── ui/                 # 基础UI组件
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── input.tsx
│   │   │   ├── modal.tsx
│   │   │   ├── table.tsx
│   │   │   ├── badge.tsx
│   │   │   └── tooltip.tsx
│   │   │
│   │   ├── layout/             # 布局组件
│   │   │   ├── sidebar.tsx
│   │   │   ├── header.tsx
│   │   │   ├── footer.tsx
│   │   │   └── container.tsx
│   │   │
│   │   ├── auth/               # 认证组件
│   │   │   ├── login-form.tsx
│   │   │   └── register-form.tsx
│   │   │
│   │   ├── dashboard/          # Dashboard组件
│   │   │   ├── stats-card.tsx
│   │   │   ├── position-table.tsx
│   │   │   └── chart-widget.tsx
│   │   │
│   │   └── settings/           # 设置组件
│   │       ├── api-config-form.tsx
│   │       ├── trading-form.tsx
│   │       └── strategy-selector.tsx
│   │
│   ├── stores/                  # 状态管理
│   │   ├── auth-store.ts       # 认证状态
│   │   ├── chat-store.ts       # 聊天状态
│   │   ├── config-store.ts     # 配置状态
│   │   ├── credits-store.ts    # 积分状态
│   │   ├── ui-store.ts         # UI状态
│   │   ├── session-store.ts     # Session状态
│   │   └── index.ts            # 导出
│   │
│   ├── lib/                     # 核心库
│   │   ├── auth.ts             # 认证工具
│   │   ├── prisma.ts           # Prisma客户端
│   │   ├── task-manager.ts     # 任务管理
│   │   ├── uid.ts              # UID生成
│   │   └── api.ts              # API客户端
│   │
│   ├── hooks/                   # 自定义Hooks
│   │   ├── useAuth.ts
│   │   ├── useCredits.ts
│   │   ├── useTask.ts
│   │   └── useChat.ts
│   │
│   ├── types/                   # 类型定义
│   │   ├── index.ts
│   │   ├── auth.ts
│   │   ├── config.ts
│   │   └── task.ts
│   │
│   └── middleware.ts            # 中间件
│
├── prisma/
│   ├── schema.prisma           # 数据库模型
│   └── migrations/             # 迁移文件
│
├── public/                     # 静态资源
│   ├── images/
│   └── icons/
│
├── docs/                       # 设计文档
│
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── next.config.ts
└── pnpm-workspace.yaml
```

---

## 🔧 核心模块

### 1. 用户认证模块

**功能**:
- 邮箱注册/登录
- JWT Token认证
- 会话管理
- 权限控制

**认证流程**:
```
用户输入邮箱密码
        ↓
提交 /api/auth/register 或 /api/auth/login
        ↓
验证凭证 (bcrypt)
        ↓
生成 JWT Token (jose)
        ↓
返回 Token (httpOnly Cookie)
        ↓
后续请求携带 Token
```

**状态管理 (auth-store.ts)**:
```typescript
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  
  // 方法
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
  checkAuth: () => Promise<void>;
}
```

### 2. API配置模块

**功能**:
- OKX API Key管理
- API状态检测
- 密钥加密存储

**配置表单**:
```typescript
interface APIConfig {
  exchange: 'okx';              // 交易所
  apiKey: string;              // API Key (加密)
  secretKey: string;           // Secret Key (加密)
  passphrase: string;           // Passphrase (OKX)
  mode: 'demo' | 'live';       // 模式
  profile: string;             // 账户配置名
}
```

### 3. 交易参数模块

**功能**:
- 交易对选择
- 仓位管理
- 杠杆配置
- 止损止盈

**参数表单**:
```typescript
interface TradingConfig {
  symbol: string;              // 交易对
  leverage: number;           // 杠杆倍数
  maxPosition: number;        // 最大仓位
  stopLoss: number;           // 止损比例
  takeProfit: number;         // 止盈比例
  slippage: number;           // 滑点容忍
}
```

### 4. 策略设置模块

**功能**:
- 策略模板选择
- 参数自定义
- 定时任务调度

**支持的Regime**:
- TRENDING_UP - 上涨趋势
- TRENDING_DOWN - 下跌趋势
- RANGE_BOUND - 区间震荡
- VOLATILE - 高波动
- BREAKOUT - 突破

### 5. 积分系统模块

**功能**:
- 积分余额查询
- 积分消耗记录
- 档位管理

**积分档位**:
| 档位 | 价格 | 积分 |
|------|------|------|
| L1 | ¥9.9 | 1000 |
| L2 | ¥29.9 | 5000 |
| L3 | ¥99 | 20000 |
| L4 | ¥268 | 60000 |

### 6. 任务管理模块

**功能**:
- 创建即时任务
- 创建定时任务
- 任务状态跟踪
- 结果查看

**任务API**:
```typescript
// 创建任务
POST /api/task
{
  "prompt": "执行A1深度调研",
  "intentType": "research",
  "scheduleType": "once" | "recurring",
  "scheduledAt"?: string,
  "rrule"?: string
}

// 响应
{
  "taskId": "task_xxx",
  "status": "pending"
}
```

---

## 🎨 UI设计

### 页面结构

```
┌─────────────────────────────────────────────────────────────┐
│ Header: Logo | 用户名 | 积分余额 | 设置 | 登出              │
├──────────┬──────────────────────────────────────────────────┤
│          │                                                   │
│ Sidebar  │              Main Content                         │
│          │                                                   │
│ • 首页   │  ┌─────────────────────────────────────────┐    │
│ • 设置   │  │                                         │    │
│   - API  │  │                                         │    │
│   - 交易  │  │           动态内容区域                   │    │
│   - 策略 │  │                                         │    │
│   - 通道 │  │                                         │    │
│ • 报告   │  │                                         │    │
│ • 聊天   │  └─────────────────────────────────────────┘    │
│          │                                                   │
└──────────┴──────────────────────────────────────────────────┘
```

### 主题配置

```typescript
// tailwind.config.ts
export default {
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          500: '#3b82f6',    // 主色
          600: '#2563eb',
          700: '#1d4ed8',
        },
        success: '#10b981',
        danger: '#ef4444',
        warning: '#f59e0b',
      },
    },
  },
}
```

---

## 🔐 安全设计

### 认证安全

- 密码: bcrypt (saltRounds: 12)
- Token: JWT (RS256, 24h过期)
- API Key: AES-256-GCM加密

### 传输安全

- HTTPS强制
- httpOnly Cookie
- CSRF保护

---

## 🚀 部署方案

### 开发环境

```bash
cd 3-FRONTEND/dream-universal-gateway
pnpm install
pnpm dev
# http://localhost:3456
```

### Docker部署

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN corepack enable && pnpm install
COPY . .
RUN pnpm build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
```

---

## 📊 性能指标

| 指标 | 目标 | 当前 |
|------|------|------|
| LCP | <2.5s | 1.8s |
| FID | <100ms | 50ms |
| CLS | <0.1 | 0.05 |
| TTFB | <200ms | 150ms |

---

## 🔗 相关文档

- [前端设计文档索引](../1-ARCHITECTURE/前端设计/README.md)
- [网关中台设计](../1-ARCHITECTURE/中台设计/GATEWAY_HUB.md)
- [WorkBuddy集成](./FRONTEND_WB_INTEGRATION.md)
