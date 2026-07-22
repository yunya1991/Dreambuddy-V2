# /feed 增强设计文档

> 版本: v1.0 | 日期: 2026-05-18 | 任务: feed-design-7b

## 1. 路由策略

### 1.1 路由层级
```
3-FRONTEND/dream-universal-gateway/src/app/feed/page.tsx   # Client page
3-FRONTEND/dream-universal-gateway/src/app/api/feed/route.ts  # Server proxy
```

### 1.2 数据流
```
Client (feed/page.tsx)
  ↓ fetch("/api/feed?workflow_type=...")
Next.js API Route (/api/feed)
  ↓ fetch HUB_BASE_URL/chain/artifacts
Artifact Hub V2 (/chain/artifacts)
  ↓ groupByWorkflowType(store.getArtifactsIndex())
SQLite artifact store
```

### 1.3 过滤参数
| 参数 | 值 | 说明 |
|------|-----|------|
| `workflow_type` | `legacy_chain` | 只显示 legacy_chain 产物 |
| `workflow_type` | `trading_v2` | 只显示 trading_v2 产物 |
| (空) | — | 全量产物 (两个工作流合并) |

## 2. 组件边界

### 2.1 /feed 页面组件
- `FeedPage` (Client Component) — 主页面，状态管理、过滤、刷新
- 工作流徽章过滤: `all | legacy_chain | trading_v2`
- FeedItem 卡片: 标题、部门、chain_phase、状态、时间
- 错误/加载/空状态三态处理

### 2.2 API 代理
- 纯服务端 Route Handler，不包含业务逻辑
- Hub 不可用时返回 503 + `hub_unavailable` 错误码
- ISR revalidate: 15s (比 /chain 更频繁，feed 是实时流)

## 3. 数据源规范

### 3.1 FeedItem 数据结构
```typescript
interface FeedItem {
  id: string;              // artifact_id
  title: string;           // artifact title
  department: string;      // originating department
  type: ArtifactType;      // knowledge | trading | dashboard_*
  chain_phase: string;     // A1-A9 phase label
  workflow_type: WorkflowType;  // legacy_chain | trading_v2
  status: ArtifactStatus;  // completed | processing | failed | unknown
  date: ISODateString;     // creation date
  excerpt?: string;        // optional summary
  url: string;             // relative path in artifact store
}
```

### 3.2 Hub 端点
- `GET /chain/artifacts` — returns `{ legacy_chain, trading_v2, total }`
- `GET /chain/artifacts?workflow_type=legacy_chain` — returns `{ workflow_type, items, total }`
- Hub env: `HUB_BASE_URL` (default: http://127.0.0.1:3000)

## 4. 增强规划 (v1.1+)

| 特性 | 优先级 | 说明 |
|------|--------|------|
| 实时 SSE 订阅 | P1 | 通过 /chain/events 端点推送新产物 |
| 分页加载 | P2 | cursor-based pagination for large datasets |
| 全文搜索 | P2 | Client-side fuzzy search on title/department |
| 产物预览 | P3 | Inline markdown preview for knowledge artifacts |

## 5. 依赖关系

- `chain-card-comp-3c` (PR #53): WorkflowCard components (可复用 FeedItem 卡片样式)
- `chain-fe-route-3b` (PR #54): /api/chain/artifacts proxy (与 /api/feed 共享模式)
- Hub V2 /chain/artifacts endpoint (已在 7-ARTIFACT-HUB-V2/src/index.ts 实现)