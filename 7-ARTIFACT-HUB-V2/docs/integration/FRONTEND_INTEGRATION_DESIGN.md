# 7-ARTIFACT-HUB-V2 与 3-FRONTEND 互联架构设计

> 版本：v2.0
> 更新日期：2026-05-19
> 状态：已确认
> 作用：明确 7-ARTIFACT-HUB-V2 与 3-FRONTEND 的定位区分、端口分配和互联互通方式。

---

## 一、架构定位确认

### 1.1 两大前端系统定位

| 系统 | 技术栈 | 端口 | 面向用户 | 核心职责 |
|------|--------|------|----------|----------|
| **3-FRONTEND** | Next.js (React) | `:3000` | 交易员/用户 | 用户认证、配置管理、任务调度、产物查看、积分管理 |
| **7-ARTIFACT-HUB-V2** | Node.js + Express | `:3456` | AI Agent 管理员 | AI 治理、产物生命周期、Trace追踪、审计回放 |

### 1.2 路由归属确认

**3-FRONTEND 已实现的页面**：
```
/dashboard    - 用户仪表盘
/feed         - 研究中台（产物列表）
/chain        - 交易链路监控
/market       - 市场化中台
/board        - 董事会总览台
/login        - 用户登录
/register     - 用户注册
```

**7-ARTIFACT-HUB-V2 的 ops-ui**：
```
/             - 治理控制台首页 (ops-ui)
/api/*        - Hub REST API
```

### 1.3 无冲突确认

- ✅ 端口独立（3000 vs 3456）
- ✅ 技术栈独立（Next.js vs Node.js）
- ✅ 用户群体不同（用户 vs AI管理员）
- ✅ 功能边界清晰（业务操作 vs 治理监控）

---

## 二、互联互通方案

### 2.1 数据层共享（单一真相源）

```
┌─────────────────────────────────────────────────────────┐
│                   共享数据层                             │
│  MetaStore: dreambuddy/meta/artifact_hub.sqlite        │
│  Artifacts: dreambuddy/artifacts/                       │
│  Config:    dreambuddy/config/                          │
└─────────────────────────────────────────────────────────┘
              ▲                              ▲
              │ 读/写                         │ 读/写
    ┌─────────┴─────────┐        ┌──────────┴──────────┐
    │   3-FRONTEND      │        │ 7-ARTIFACT-HUB-V2  │
    │   (localhost:3000) │        │   (localhost:3456) │
    └───────────────────┘        └───────────────────┘
```

### 2.2 API调用关系

```
3-FRONTEND (用户端)
    │
    ├─→ WorkBuddy API (创建任务)
    │       │
    │       └─→ A0-A9 交易流水线
    │               │
    │               └─→ Artifacts Hub (产物产出)
    │
    └─→ 7-ARTIFACT-HUB-V2 API (治理数据查询)
            │
            ├─ GET /traces/:id      (Trace追踪)
            ├─ GET /api/artifacts   (产物列表)
            └─ GET /api/board/*     (董事会数据)
```

### 2.3 Hub API 契约

| API | 方法 | 用途 | 调用方 |
|-----|------|------|--------|
| `/health` | GET | Hub健康检查 | 3-FRONTEND |
| `/traces/:traceId` | GET | Trace详情回放 | 3-FRONTEND |
| `/events/stream` | GET | SSE事件流 | 3-FRONTEND |
| `/api/artifacts` | GET | 产物列表查询 | 3-FRONTEND |
| `/api/artifacts/:id` | GET | 产物详情 | 3-FRONTEND |
| `/api/board/departments` | GET | 部门状态 | 3-FRONTEND |
| `/api/ops/queues` | GET | 队列监控 | 3-FRONTEND |
| `POST /route/decide` | POST | 路由决策沙盒 | 管理员 |

---

## 三、3-FRONTEND → Hub API 集成方案

### 3.1 前端代理配置

在 3-FRONTEND 的 `next.config.ts` 或 API Routes 中添加代理：

```typescript
// src/app/api/hub/[...path]/route.ts
import { NextRequest, NextResponse } from 'next/server';

const HUB_BASE_URL = process.env.HUB_API_URL || 'http://127.0.0.1:3456';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  const { path } = await params;
  const targetUrl = `${HUB_BASE_URL}/${path.join('/')}`;
  const response = await fetch(targetUrl, {
    headers: { ...Object.fromEntries(request.headers) }
  });
  return NextResponse.json(await response.json());
}

export async function POST(
  request: NextRequest,
  { params }: { params: { path: string[] } }
) {
  const { path } = params;
  const body = await request.json();
  const targetUrl = `${HUB_BASE_URL}/${path.join('/')}`;
  const response = await fetch(targetUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  return NextResponse.json(await response.json());
}
```

### 3.2 Hub API 客户端封装

```typescript
// src/lib/hub-api.ts
const HUB_BASE = process.env.NEXT_PUBLIC_HUB_API_URL || 'http://localhost:3456';

export const HubApi = {
  async getTrace(traceId: string) {
    const res = await fetch(`${HUB_BASE}/traces/${traceId}`);
    return res.json();
  },

  async getArtifacts(params?: { category?: string; limit?: number }) {
    const qs = new URLSearchParams(params as Record<string, string>);
    const res = await fetch(`${HUB_BASE}/api/artifacts?${qs}`);
    return res.json();
  },

  async getBoardOverview() {
    const res = await fetch(`${HUB_BASE}/api/board/departments`);
    return res.json();
  },

  async getOpsHealth() {
    const res = await fetch(`${HUB_BASE}/api/ops/health`);
    return res.json();
  }
};
```

---

## 四、运行方式

### 4.1 独立运行（开发环境）

```bash
# 终端1：启动用户前端 (3-FRONTEND)
cd 3-FRONTEND/dream-universal-gateway
npm run dev  # http://localhost:3000

# 终端2：启动治理后台 (7-ARTIFACT-HUB-V2)
cd 7-ARTIFACT-HUB-V2
npm run build
node dist/index.js  # http://localhost:3456
```

### 4.2 统一代理（生产环境）

```nginx
# nginx.conf
server {
    listen 80;
    server_name your-domain.com;

    # 用户前端
    location / {
        proxy_pass http://localhost:3000;
    }

    # Hub API (治理后台)
    location /hub/ {
        rewrite ^/hub/(.*) /$1 break;
        proxy_pass http://localhost:3456;
    }
}
```

---

## 五、数据流全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                        用户视角                                    │
│  ┌──────────────┐                                                │
│  │ 3-FRONTEND   │  http://localhost:3000                         │
│  │ (Next.js)    │                                                │
│  └──────┬───────┘                                                │
│         │                                                        │
│         ├─→ 配置 → 任务 → WorkBuddy                              │
│         │                                                        │
│         └─→ 查询 → Hub API (localhost:3456)                      │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                     AI 治理视角                                  │
│  ┌──────────────────────────┐    ┌────────────────────────────┐ │
│  │ 7-ARTIFACT-HUB-V2        │    │ 共享数据层                  │ │
│  │ (Node.js + Express)      │───→│ • MetaStore (SQLite)       │ │
│  │ http://localhost:3456    │    │ • Artifacts (文件存储)     │ │
│  │                          │    │ • Config (策略/路由)       │ │
│  │ • ops-ui (治理控制台)     │    └────────────────────────────┘ │
│  │ • Hub Core (核心服务)     │                                      │
│  │ • REST API               │                                      │
│  └──────────────────────────┘                                      │
│           ▲                                                        │
│           │ 产物产出                                               │
│  ┌────────┴────────┐                                              │
│  │  WorkBuddy       │                                              │
│  │  (A0-A9流水线)    │                                              │
│  └──────────────────┘                                              │
└──────────────────────────────────────────────────────────────────┘
```

---

## 六、结论

1. **无冲突**：两大前端独立运行在不同端口，技术栈和用户群体完全不同
2. **互联互通**：通过共享数据层（MetaStore + Artifacts）和标准 API 契约实现
3. **职责清晰**：
   - 3-FRONTEND = 用户操作界面
   - 7-ARTIFACT-HUB-V2 = AI 治理后台
4. **扩展灵活**：未来可通过反向代理统一入口，实现单域名多服务路由
