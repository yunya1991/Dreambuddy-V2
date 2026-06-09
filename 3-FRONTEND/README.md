# 用户前端系统 - Dream Universal Gateway

> **版本**: v1.0  
> **创建日期**: 2026-05-14

---

## 📁 源码目录

```
dream-universal-gateway/
├── src/
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth/[...nextauth]/   # NextAuth认证
│   │   │   ├── chat/                 # 聊天API
│   │   │   ├── task/                 # 任务API
│   │   │   ├── register/             # 注册API
│   │   │   └── user/me/              # 用户信息API
│   │   ├── login/                    # 登录页
│   │   ├── register/                # 注册页
│   │   ├── dashboard/                # 仪表盘
│   │   ├── layout.tsx                # 根布局
│   │   └── page.tsx                  # 首页
│   ├── components/                    # UI组件
│   ├── stores/                        # Zustand状态
│   │   ├── auth-store.ts             # 认证状态
│   │   ├── chat-store.ts             # 聊天状态
│   │   ├── config-store.ts           # 配置状态
│   │   ├── credits-store.ts          # 积分状态
│   │   ├── session-store.ts          # 会话状态
│   │   └── ui-store.ts               # UI状态
│   ├── lib/
│   │   ├── auth.ts                   # 认证工具
│   │   ├── prisma.ts                 # 数据库
│   │   ├── task-manager.ts           # 任务管理
│   │   └── uid.ts                    # UID生成
│   ├── types/index.ts                # 类型定义
│   └── middleware.ts                  # 中间件
├── docs/                             # 设计文档(18个)
├── prisma/                           # 数据库Schema
└── package.json
```

---

## 🎯 四大功能模块

### 1️⃣ API配置模块
- OKX API密钥管理
- 多交易所支持
- 连接状态检测

### 2️⃣ 交易参数模块
- 交易对选择(BTC/USDT等)
- 仓位管理
- 杠杆配置
- 风险参数

### 3️⃣ 策略设置模块
- 策略模板库
- 自定义策略
- 定时任务调度
- 信号类型选择

### 4️⃣ 通信通道模块
- WebSocket实时
- Telegram通知
- 状态指示灯

---

## 📊 已有设计文档

| 文档 | 说明 |
|------|------|
| `ARCHITECTURE.md` | 整体架构 |
| `USER_SYSTEM_DESIGN.md` | 用户系统 |
| `API_CONFIG_DESIGN.md` | API配置 |
| `TRADING_CONFIG_DESIGN.md` | 交易参数 |
| `STRATEGY_CONFIG_DESIGN.md` | 策略设置 |
| `CHANNEL_DESIGN.md` | 通信通道 |
| `INTENT_ROUTER.md` | 意图路由 |
| `UI_SPEC.md` | UI规范 |
| `TECH_STACK_EVALUATION.md` | 技术评估 |

---

## 🔗 后端联动

```
Gateway前端 → POST /api/task → WorkBuddy中台
                           ↓
                    task-manager.ts
                           ↓
                    scripts/task_poller.py
                           ↓
                    A1-A5交易流水线
```
