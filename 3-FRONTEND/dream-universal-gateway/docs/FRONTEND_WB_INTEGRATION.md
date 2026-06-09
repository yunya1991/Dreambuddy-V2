# Frontend-WorkBuddy Integration Design

> Version: 1.1 | Date: 2026-05-22 | Status: Core Bridge Implemented, Follow-up Integration Pending

## 0. Implementation Status (2026-05-22 / Task 6)

- Implemented: `src/app/api/task/route.ts` already exposes task create/query/list/feed logic and merges `collectStrategyTaskOrderFeedItems()` into the Product Hub compatible feed.
- Implemented: strategy apply/create flow now writes `StrategyTaskOrder` artifacts into `artifacts/trading/` via `createStrategyTaskOrderArtifactWriter`, so frontend strategy state and Product Hub feed use the same artifact contract.
- Implemented: `GET /api/config/strategies` now returns `taskOrders.strategyTasks.executionRuns`, and Dashboard consumes the unified task-order chain through `buildStrategyPanelViewModel()`.
- Verified in this task: `node --import tsx --test tests/strategy-task-order.test.ts tests/strategy-lifecycle-service.test.ts tests/strategy-artifacts.test.ts tests/strategy-view-model.test.ts tests/trading-panel-data.test.ts` passes with 14/14 tests, and `pnpm build` passes.
- Not yet closed in this document's original scope: WorkBuddy automation poller / manual trigger / optional SSE stream remain design items here, and `pnpm lint` still fails because of pre-existing repository-wide issues outside the Task 6 touch area.

### Development Demo User Fallback

- Local development fallback consistently uses `DEMO_UID`.
- When the demo user does not exist, the route helper automatically ensures a minimal `User` record.
- After `prisma migrate reset`, local strategy and feed verification can continue without manually inserting the demo user.

## 1. Overview

### 1.1 Goal

Connect Dream Universal Gateway frontend Dashboard with WorkBuddy, enabling users to send messages in the frontend that trigger WorkBuddy execution and return real results.

### 1.2 Core Principle

**Product Hub (artifact center) as the information bridge and artifact relay hub** - all communication between frontend and WorkBuddy flows through the Product Hub's file system.

### 1.3 Key Constraint

WorkBuddy has no public HTTP API. Available integration mechanisms:
- Gateway/Tunnel: only for WeChat/QQ/Enterprise WeChat messaging platforms
- MCP Protocol: call-direction-reversed (WorkBuddy calls MCP, not vice versa)
- Automation: cron-based polling, minimum ~1 minute interval
- **File-system bridge**: the only viable approach for custom frontend integration

## 2. Architecture Design

### 2.1 System Architecture Overview

```
+------------------+     +------------------+     +------------------+
|   Frontend       |     |  Product Hub     |     |   WorkBuddy      |
|   Dashboard      |     |  (Bridge)        |     |   (Executor)     |
+------------------+     +------------------+     +------------------+
        |                        |                        |
        |  1. POST /api/task     |                        |
        |----------------------->|                        |
        |  (write task file)     |                        |
        |                        |                        |
        |  2. Task file created  |                        |
        |     artifacts/tasks/   |                        |
        |                        |   3. Automation/Chat   |
        |                        |<-------poll/read-------|
        |                        |                        |
        |                        |   4. Execute task      |
        |                        |--------SKILL/A1-A5---->|
        |                        |                        |
        |                        |   5. Write result      |
        |                        |<---result file---------|
        |     artifacts/results/ |                        |
        |                        |                        |
        |  6. GET /api/task?id=  |                        |
        |------poll result------>|                        |
        |                        |                        |
        |  7. Display result     |                        |
        |<------JSON response----|                        |
        +------------------+     +------------------+     +------------------+
```

### 2.2 Five-Step Data Flow

| Step | Actor | Action | Location |
|------|-------|--------|----------|
| 1 | Frontend | User sends message, API writes task file | `artifacts/tasks/task_{id}.json` |
| 2 | WorkBuddy | Automation polls or manual `/chat` reads task | reads `artifacts/tasks/` |
| 3 | Product Hub | Syncs task artifacts, provides UI visibility | `localhost:3456` Feed |
| 4 | WorkBuddy | Executes task via SKILL chain, writes result | `artifacts/results/result_{id}.json` |
| 5 | Frontend | Polls result API, displays to user | Dashboard chat |

### 2.3 Component Responsibilities

| Component | Role | Key Tech |
|-----------|------|----------|
| Frontend Dashboard | User interface, async polling | Next.js, React |
| API Route `/api/task` | Task CRUD, file I/O | Next.js Route Handler |
| Product Hub | Artifact relay, visibility bridge | content.server.ts |
| WorkBuddy Automation | Task polling, execution trigger | cron/Automation |
| WorkBuddy Agent | Actual task execution | SKILL chains (A1-A5) |

## 3. Data Format Design

### 3.1 Task File Format

Path: `artifacts/tasks/task_{timestamp}_{random}.json`

```json
{
  "task_id": "task_20260514_100600_a3f2",
  "status": "pending",
  "created_at": "2026-05-14T10:06:00+08:00",
  "updated_at": "2026-05-14T10:06:00+08:00",
  "source": "dashboard",
  "message": "分析BTC行情",
  "intent": {
    "type": "deep_analysis",
    "confidence": 0.85,
    "entities": {
      "symbol": "BTC",
      "timeframe": "4h"
    }
  },
  "thinking_mode": "deep",
  "session_id": "sess_abc123",
  "priority": "high",
  "metadata": {
    "user_agent": "DreamGateway/1.0",
    "llm_model": "qwen3-30b-a3b",
    "intent_method": "llm"
  }
}
```

### 3.2 Task Status Lifecycle

```
pending -> processing -> completed
                     -> failed
                     -> timeout
```

| Status | Description |
|--------|-------------|
| `pending` | Task created, waiting for WorkBuddy to pick up |
| `processing` | WorkBuddy has started execution |
| `completed` | Execution finished, result available |
| `failed` | Execution failed with error |
| `timeout` | Task expired (default 30 min) |

### 3.3 Result File Format

Path: `artifacts/results/result_{task_id}.json`

```json
{
  "task_id": "task_20260514_100600_a3f2",
  "status": "completed",
  "created_at": "2026-05-14T10:08:30+08:00",
  "execution_time_ms": 150000,
  "content": "## A1-A5 Analysis Results\n\n...",
  "content_type": "markdown",
  "artifacts_produced": [
    {
      "file": "a1_research_20260514_1006.md",
      "type": "research",
      "chain_phase": "A1"
    },
    {
      "file": "a2_analysis_20260514_1008.md",
      "type": "analysis",
      "chain_phase": "A2"
    }
  ],
  "execution_summary": {
    "chain_executed": ["A1_research", "A2_analysis", "A3_simulation"],
    "total_steps": 3,
    "skipped_steps": [],
    "regime": "RANGE_BOUND",
    "confidence": 0.65
  },
  "metadata": {
    "executor": "workbuddy-agent",
    "model": "qwen3-30b-a3b",
    "cost_credits": 200
  }
}
```

## 4. API Design

### 4.1 POST /api/task - Create Task

**Request:**
```json
{
  "message": "分析BTC行情",
  "thinking_mode": "deep",
  "session_id": "sess_abc123"
}
```

**Response (immediate):**
```json
{
  "success": true,
  "data": {
    "task_id": "task_20260514_100600_a3f2",
    "status": "pending",
    "poll_url": "/api/task?id=task_20260514_100600_a3f2",
    "estimated_time_ms": 60000
  }
}
```

### 4.2 GET /api/task - Poll Result

**Request:** `GET /api/task?id=task_20260514_100600_a3f2`

**Response (pending):**
```json
{
  "success": true,
  "data": {
    "task_id": "task_20260514_100600_a3f2",
    "status": "pending",
    "message": "Waiting for WorkBuddy to process..."
  }
}
```

**Response (completed):**
```json
{
  "success": true,
  "data": {
    "task_id": "task_20260514_100600_a3f2",
    "status": "completed",
    "content": "## Analysis Results\n...",
    "artifacts_produced": [...],
    "execution_summary": {...},
    "execution_time_ms": 150000
  }
}
```

### 4.3 GET /api/task?action=list - List Tasks

**Request:** `GET /api/task?action=list&limit=10`

**Response:**
```json
{
  "success": true,
  "data": {
    "tasks": [
      {
        "task_id": "task_20260514_100600_a3f2",
        "status": "completed",
        "message": "分析BTC行情",
        "created_at": "2026-05-14T10:06:00+08:00"
      }
    ],
    "total": 1
  }
}
```

### 4.4 SSE Support (Optional Enhancement)

For real-time updates without polling:

**Endpoint:** `GET /api/task/stream?id=task_xxx`

```
event: status
data: {"status":"processing","message":"WorkBuddy is executing..."}

event: progress
data: {"step":"A1_research","progress":0.33}

event: result
data: {"status":"completed","content":"...","artifacts_produced":[...]}
```

## 5. Frontend Adaptation

### 5.1 Message Flow Change

**Before (synchronous mock):**
```
User sends message -> POST /api/chat -> mock response -> display
```

**After (asynchronous real):**
```
User sends message -> POST /api/task -> task_id returned
-> show "thinking" animation
-> poll GET /api/task?id=xxx (every 3s)
-> result received -> display
```

### 5.2 UI States

| State | Display |
|-------|---------|
| Task created | "Waiting for WorkBuddy..." with spinner |
| Processing | "WorkBuddy is executing [chain step]..." with progress |
| Completed | Full result with artifact links |
| Failed | Error message with retry option |
| Timeout | "Response timeout" with manual retry |

### 5.3 Hybrid Mode

Keep the existing mock/LLM response as a fallback:
- If WorkBuddy is not available (no Automation running), use mock/LLM direct response
- If WorkBuddy is connected, use async task mode
- Toggle available in settings: "WorkBuddy Mode" ON/OFF

## 6. WorkBuddy Side Integration

### 6.1 Automation Task Poller

Create an Automation that runs every 1 minute:

```yaml
name: "Frontend Task Poller"
schedule: "*/1 * * * *"
prompt: |
  1. Check artifacts/tasks/ for any task files with status "pending"
  2. If found, update status to "processing"
  3. Execute the task using appropriate SKILL chain based on intent
  4. Write result to artifacts/results/result_{task_id}.json
  5. Update task status to "completed"
  6. If execution fails, update task status to "failed" with error message
```

### 6.2 Intent-to-SKILL Mapping

| Intent | SKILL Chain | Estimated Time |
|--------|-------------|----------------|
| `market_query` | OKX CLI direct | 5-10s |
| `deep_analysis` | A1 -> A2 | 60-120s |
| `scenario_sim` | A1 -> A3 | 90-180s |
| `strategy_verify` | A4 | 60-120s |
| `execute_trade` | A5 (with gate) | 30-60s |
| `simple_qa` | Direct LLM response | 5-15s |

### 6.3 Manual Trigger (Low Latency)

For sub-minute latency, user can trigger WorkBuddy manually:
- Open WorkBuddy chat, type: "执行前端任务"
- Or configure a hotkey/shortcut that sends this command

## 7. Product Hub Integration

### 7.1 Task/Result Visibility

Product Hub should display tasks and results alongside existing artifacts:

```
artifacts/
  trading/        # existing A1-A8 artifacts
  tasks/          # NEW: pending/processing tasks
  results/        # NEW: completed results
  memory/         # existing memory artifacts
  governance/     # existing governance artifacts
```

### 7.2 Feed Integration

- Tasks appear as "in-progress" items in the Product Hub feed
- Results appear as "completed" items with link to full content
- Both show `chain_phase: "dashboard-task"` tag for filtering

### 7.3 Index Registration

Task and result files register in `index.json`:

```json
{
  "file": "results/result_task_20260514_100600_a3f2.json",
  "title": "Dashboard Request: 分析BTC行情",
  "date": "2026-05-14T10:08:30+08:00",
  "type": "dashboard_result",
  "chain_phase": "dashboard",
  "tags": ["dashboard", "deep_analysis", "BTC"],
  "status": "completed",
  "source_task": "task_20260514_100600_a3f2"
}
```

## 8. Latency Analysis

| Trigger Method | Estimated Latency | User Experience |
|---------------|-------------------|-----------------|
| Automation (1min cron) | 60-90s | Acceptable for analysis tasks |
| Manual `/chat` trigger | 5-10s | Good for interactive use |
| SSE streaming result | 2-5s after completion | Best experience |
| Future: WebSocket bridge | <1s | Ideal, requires WB feature |

## 9. Security Considerations

| Concern | Mitigation |
|---------|------------|
| Arbitrary command injection | Task messages sanitized, intent validated |
| Unauthorized task creation | Session-based auth, rate limiting |
| Sensitive data in task files | No API keys/secrets in task JSON |
| Task file cleanup | Auto-delete tasks older than 24h |
| Trade execution safety | A5 gate still applies, no bypass |

## 10. Development Plan

| Phase | Task | Est. Time | Dependencies |
|-------|------|-----------|--------------|
| P1 | Create `artifacts/tasks/` and `artifacts/results/` directories | 5 min | None |
| P2 | Implement `/api/task` route (create + poll + list) | 1.5 h | P1 |
| P3 | Adapt frontend `handleSubmit` for async polling | 1 h | P2 |
| P4 | Create WorkBuddy Automation for task polling | 30 min | P1 |
| P5 | Product Hub integration (scan tasks/results) | 1 h | P1 |
| P6 | SSE streaming support (optional) | 1 h | P2 |
| **Total** | | **~5.5 h** | |

## 11. File Structure After Implementation

```
dream-universal-gateway/
  src/
    app/
      api/
        chat/
          route.ts          # existing, kept as fallback
        task/
          route.ts          # NEW: task create + poll + list
    lib/
      task-manager.ts       # NEW: task file I/O, status management
  docs/
    FRONTEND_WB_INTEGRATION.md  # THIS FILE

artifacts/
  trading/                  # existing
  tasks/                    # NEW
    task_20260514_100600_a3f2.json
  results/                  # NEW
    result_task_20260514_100600_a3f2.json
  index.json                # updated to include tasks/results
```

## 12. Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| WorkBuddy not running | Tasks stuck in pending | Frontend timeout + fallback to mock |
| Task file corruption | Result never written | Auto-timeout after 30 min |
| Concurrent task execution | Resource contention | Max 3 concurrent tasks, queue the rest |
| Product Hub scan lag | Tasks not visible in feed | 5s cache TTL, acceptable delay |
| Large result content | File I/O slowdown | Truncate to 50KB max, link to full artifact |
