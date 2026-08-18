# 前端架构详细设计

> **版本**: v2.0
> **更新日期**: 2026-05-14

---

## 🏗️ 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Dream Universal Gateway                   │
│                      (Next.js 14 App Router)                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────────────────────────────────────────────┐   │
│  │                    用户界面层                           │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │   │
│  │  │Dashboard│  │Settings │  │Reports  │  │Chat     │  │   │
│  │  │首页仪表盘│  │配置中心 │  │报告中心 │  │对话界面 │  │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  │   │
│  └───────────────────────────────────────────────────────┘   │
│                             │                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │                    组件库层                             │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │   │
│  │  │Button   │  │Card     │  │Modal    │  │Table    │  │   │
│  │  │表单组件 │  │卡片组件 │  │弹窗组件 │  │表格组件 │  │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  │   │
│  └───────────────────────────────────────────────────────┘   │
│                             │                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │                    状态管理层                           │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │   │
│  │  │auth     │  │chat     │  │config   │  │credit   │  │   │
│  │  │store    │  │store    │  │store    │  │store    │  │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐               │   │
│  │  │ui       │  │session  │  │task     │               │   │
│  │  │store    │  │store    │  │store    │               │   │
│  │  └─────────┘  └─────────┘  └─────────┘               │   │
│  └───────────────────────────────────────────────────────┘   │
│                             │                               │
│  ┌───────────────────────────────────────────────────────┐   │
│  │                    核心库层                             │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │   │
│  │  │auth.ts  │  │task-    │  │prisma.ts│  │uid.ts   │  │   │
│  │  │认证管理 │  │manager  │  │数据库   │  │ID生成   │  │   │
│  │  │         │  │任务调度 │  │客户端   │  │         │  │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  │   │
│  └───────────────────────────────────────────────────────┘   │
│                             │                               │
└─────────────────────────────┼───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                      API路由层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │/api/auth/*  │  │/api/task/*  │  │/api/chat/*  │         │
│  │认证接口     │  │任务接口     │  │对话接口     │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 目录结构

```
3-FRONTEND/dream-universal-gateway/
├── src/
│   ├── app/                      # Next.js App Router
│   │   ├── layout.tsx           # 根布局
│   │   ├── page.tsx             # 首页
│   │   ├── providers.tsx        # 全局Provider
│   │   ├── globals.css          # 全局样式
│   │   │
│   │   ├── (auth)/             # 认证路由组
│   │   │   ├── login/
│   │   │   └── register/
│   │   │
│   │   ├── (dashboard)/        # Dashboard路由组
│   │   │   ├── page.tsx        # Dashboard首页
│   │   │   ├── settings/
│   │   │   │   ├── api-config/
│   │   │   │   ├── trading/
│   │   │   │   ├── strategy/
│   │   │   │   └── channels/
│   │   │   ├── reports/
│   │   │   └── chat/
│   │   │
│   │   └── api/                 # API路由
│   │       ├── auth/[...nextauth]/
│   │       ├── task/
│   │       └── chat/
│   │
│   ├── components/              # 组件库
│   │   ├── ui/                 # 基础UI组件
│   │   │   ├── button.tsx
│   │   │   ├── card.tsx
│   │   │   ├── modal.tsx
│   │   │   └── input.tsx
│   │   │
│   │   ├── layout/             # 布局组件
│   │   │   ├── sidebar.tsx
│   │   │   ├── header.tsx
│   │   │   └── footer.tsx
│   │   │
│   │   ├── dashboard/          # Dashboard组件
│   │   │   ├── stats-card.tsx
│   │   │   ├── chart-card.tsx
│   │   │   └── position-table.tsx
│   │   │
│   │   └── settings/           # 设置组件
│   │       ├── api-config-form.tsx
│   │       ├── trading-form.tsx
│   │       └── strategy-selector.tsx
│   │
│   ├── stores/                  # 状态管理
│   │   ├── auth-store.ts        # 认证状态
│   │   ├── chat-store.ts       # 对话状态
│   │   ├── config-store.ts     # 配置状态
│   │   ├── credits-store.ts    # 积分状态
│   │   ├── ui-store.ts          # UI状态
│   │   ├── session-store.ts     # Session状态
│   │   └── index.ts             # 导出
│   │
│   ├── lib/                     # 核心库
│   │   ├── auth.ts              # 认证工具
│   │   ├── prisma.ts            # Prisma客户端
│   │   ├── task-manager.ts      # 任务管理
│   │   ├── uid.ts               # UID生成
│   │   └── api.ts               # API客户端
│   │
│   ├── hooks/                   # 自定义Hooks
│   │   ├── useAuth.ts
│   │   ├── useCredits.ts
│   │   └── useTask.ts
│   │
│   └── types/                   # 类型定义
│       ├── index.ts             # 通用类型
│       ├── auth.ts              # 认证类型
│       ├── config.ts            # 配置类型
│       └── task.ts              # 任务类型
│
├── prisma/
│   ├── schema.prisma           # 数据模型
│   └── migrations/             # 迁移文件
│
├── public/                     # 静态资源
│   ├── images/
│   └── icons/
│
├── docs/                       # 设计文档
│   ├── ARCHITECTURE.md
│   ├── USER_SYSTEM_DESIGN.md
│   └── ...
│
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── next.config.ts
└── pnpm-workspace.yaml
```

---

## 🔧 核心模块

### 1. 用户系统 (User System)

**功能**:
- 邮箱注册/登录
- JWT Token认证
- 个人资料管理
- API Key管理

**数据结构**:
```typescript
// prisma/schema.prisma
model User {
  id        String   @id @default(cuid())
  email     String   @unique
  password  String   // bcrypt hashed
  name      String?
  avatar    String?
  credits   Int      @default(0)
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt

  apiConfigs   ApiConfig[]
  tradingConfigs TradingConfig[]
  strategies    Strategy[]
}
```

### 2. 状态管理 (Stores)

**auth-store.ts**:
```typescript
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  register: (email: string, password: string) => Promise<void>;
}
```

**config-store.ts**:
```typescript
interface ConfigState {
  apiConfigs: ApiConfig[];
  tradingConfigs: TradingConfig[];
  strategies: Strategy[];
  currentProfile: string;
  updateApiConfig: (config: ApiConfig) => Promise<void>;
  updateTradingConfig: (config: TradingConfig) => Promise<void>;
}
```

**chat-store.ts**:
```typescript
interface ChatState {
  messages: Message[];
  isLoading: boolean;
  sendMessage: (content: string) => Promise<void>;
  clearMessages: () => void;
}
```

### 3. 任务管理 (Task Manager)

**task-manager.ts**:
```typescript
interface TaskRequest {
  uid: string;
  prompt: string;
  intentType?: string;
  scheduleType?: 'once' | 'recurring';
  scheduledAt?: string;
  rrule?: string;
}

interface TaskResponse {
  taskId: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

// API调用
POST /api/task → task-manager.ts → WorkBuddy中台
```

---

## 🎨 UI设计规范

### 主题配置

```typescript
// tailwind.config.ts
export default {
  content: ['./src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#3B82F6',    // 蓝色
        secondary: '#10B981',  // 绿色
        danger: '#EF4444',     // 红色
        warning: '#F59E0B',    // 黄色
      },
    },
  },
}
```

### 组件规范

| 组件 | 用途 | 状态 |
|------|------|------|
| Button | 操作按钮 | default/hover/active/disabled/loading |
| Card | 卡片容器 | default/hover/selected |
| Input | 输入框 | default/focus/error/disabled |
| Modal | 弹窗 | open/closing |
| Toast | 提示 | success/error/warning/info |

---

## 🔐 安全设计

### 认证流程

```
1. 用户登录 → /api/auth/signin
        ↓
2. 验证邮箱密码 → bcrypt.compare
        ↓
3. 生成JWT Token → jose.sign
        ↓
4. 返回Token → httpOnly Cookie
        ↓
5. 后续请求 → Authorization: Bearer {token}
```

### 数据加密

- 密码: bcrypt (saltRounds: 12)
- API Key: AES-256-GCM
- Token: RS256

---

## 🚀 部署方案

### 开发环境

```bash
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

## 📊 性能优化

### 策略

1. **首屏优化**: SSR + Streaming
2. **静态资源**: CDN + 缓存
3. **图片优化**: Next/Image
4. **代码分割**: 路由级懒加载
5. **状态管理**: Zustand (轻量)

### 指标目标

| 指标 | 目标值 |
|------|--------|
| LCP | <2.5s |
| FID | <100ms |
| CLS | <0.1 |
| TTFB | <200ms |
