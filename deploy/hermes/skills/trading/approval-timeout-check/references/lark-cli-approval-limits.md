# lark-cli Approval Capability Limits (2026-06-03 verified)

## What works

| Command | Status | Notes |
|---------|--------|-------|
| `lark-cli approval tasks approve` | ✅ | Works with `--as user` |
| `lark-cli approval tasks reject` | ✅ | Works with `--as user` |
| `lark-cli approval tasks query` | ✅ | List tasks |

## What does NOT work

| Command | Status | Why |
|---------|--------|-----|
| `lark-cli approval instances create` | ❌ | Method doesn't exist in lark-cli. Available: `cancel, cc, get, initiated` |
| `lark-cli approval instances get` | ❌ | Blocked by `strict-mode: bot`. Returns "command_denied — strict mode is bot, only bot-identity commands are available" even with `--as user` |
| `lark-cli event consume approval.*` | ❌ | No approval event keys available. App needs to subscribe to approval events in Feishu Developer Console first |

## Practical consequence

`approval_agent.py` must use **REST API** for:
- `get_approval_status()` → `GET /open-apis/approval/v4/instances/{code}`
- `execute_approval()` → `POST /open-apis/approval/v4/instances/{code}/tasks/{id}/approve`
- `send_msg()` → `POST /open-apis/im/v1/messages`

Token obtained from `~/.hermes/.env` (FEISHU_APP_ID + FEISHU_APP_SECRET).
App ID must be `cli_aa95b2dee3b85bd1` (云涯Hermes), NOT the old `cli_aa9442...`.

## Profile note

The lark-cli profile for the current bot is `cli_aa95b2dee3b85bd1`, not `dream`.
Strict mode is `bot` (source: profile).
User-mode commands for approval require REST API fallback.

## Approval scopes (verified present on cli_aa95b2)

All 15 approval-related scopes confirmed available via REST API at 2026-06-03:
- `approval:instance` — CRUD instances
- `approval:task` — approve/reject tasks
- `approval:approval` — CRUD approval app
- `approval:definition` — CRUD definitions
- `approval:approval.list:readonly` — list approvals
- `approval:instance.comment` — comments
- Plus 9 more HR/attendance-related scopes

## Approval definition codes (verified exist)

- Gate-C: `3901A0B3-5E7F-4A2F-A76E-74A5752BFD1F` — "Gate-C 入场审批"
- A9: `1D4CB111-9E67-4430-AA05-3CD1C262E174` — "A9 离场审批"

## End-to-end test result (2026-06-03)

- Create instance: ✅ 3/3 (user_id, bot open_id, LuckyAI open_id)
- PENDING status confirmed: ✅ (when initiator ≠ approver)
- Query status: ✅ REST API returns correct status
- AI decision: ✅ decide_gate_c runs correctly
- Execute approval: ✅ REST API approve endpoint works
- Auto-approved case: ✅ (when initiator = approver, status immediately APPROVED)
