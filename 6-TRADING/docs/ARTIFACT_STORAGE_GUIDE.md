# 6-TRADING 产物存储规范 v1.0

> **版本**: v1.0
> **创建日期**: 2026-05-27
> **状态**: 正式
> **替代**: 旧邮箱方案 `~/.workbuddy/skills/boss-secretary/reports/trading/6-trading/`

---

## 一、设计原则

| 原则 | 说明 |
|------|------|
| **会话隔离** | 每次研究独立一个 session 文件夹，互不干扰 |
| **团队归属** | 产物按团队分类（Team A 研究 / Team B 执行 / Gate C 门禁 / Process D 复盘） |
| **可追溯** | 每个产物有时间戳和关联 session_id，可全链路回溯 |
| **统一入口** | 通过 `sessions/ACTIVE_SESSION.json` 定位当前活跃 session |
| **版本化** | session 文件夹名包含日期，历史产物永久保留 |

---

## 二、目录结构

### 2.1 顶层结构

```
6-TRADING/sessions/
├── ACTIVE_SESSION.json          # ★ 当前活跃 session 指针（必读）
├── SESSION_INDEX.json           # 所有历史 session 索引
├── README.md                    # 命名规范说明
├── _template/                   # 会话目录模板
│   ├── meta.json
│   ├── team-a/
│   ├── team-b/
│   ├── gate-c/
│   └── review/
│
├── 20260527-BTC-SCREEN1/        # 示例 Screen 1 会话
├── 20260527-BTC-SCREEN2/        # 示例 Screen 2 会话
└── 20260528-BTC-ENTRY/          # 示例入场会话
```

### 2.2 单个 Session 完整结构

```
sessions/{YYYYMMDD}-{SYMBOL}-{TRIGGER}/
│
├── meta.json                    # 会话元数据（状态机）
├── session-summary.md           # ★ 会话最终摘要（关闭时写入）
│
├── team-a/                      # Team A 研究产物
│   ├── screen1/                 # 第一屏（周线分析）
│   │   ├── raw/
│   │   │   ├── a0-contradiction.md    # A0 矛盾分析
│   │   │   ├── a1-research.md         # A1 调研报告
│   │   │   ├── a2-principles.md       # A2 第一性原理
│   │   │   └── a3-seminar.md          # A3 大师研讨
│   │   ├── strategy-type.json         # 方向+策略类型（可直接读取）
│   │   └── weekly-direction.md        # 综合周线方向报告
│   │
│   └── screen2/                 # 第二屏（日线预设）
│       ├── raw/
│       │   ├── a1-daily.md            # A1 日线调研
│       │   ├── a2-daily.md            # A2 日线第一性原理
│       │   └── a3-daily.md            # A3 日线沙盘推演
│       ├── daily-presets.json         # ★ 三大预设（入场/加仓/TP-SL）
│       ├── martingale-grid.json       # 马丁阶梯参数
│       └── order-plan.md              # 挂单执行方案
│
├── team-b/                      # Team B 执行产物
│   ├── a7-gate.json             # A7 门禁结果（PASS / SKIP）
│   ├── a4-validation.json       # A4 实时验证结果
│   ├── execution-log.md         # ★ A5 下单完整记录
│   ├── position-state.json      # 当前仓位状态快照
│   ├── a6-events.jsonl          # A6 监控事件流（append）
│   └── a9-exit.json             # A9 离场决策结果
│
├── gate-c/                      # Gate C 门禁产物
│   └── pretrade-check.json      # 代码门禁检查结果（PASS / BLOCK）
│
└── review/                      # Process D 复盘产物
    └── a8-reflection.md         # A8 理论实践验证报告
```

---

## 三、产物分类索引

### 3.1 研究类产物（Team A）

| 产物 | 路径 | 产生时机 | 消费者 |
|------|------|---------|--------|
| 矛盾分析 | `team-a/screen1/raw/a0-contradiction.md` | Screen 1 | A1/A2 |
| 调研报告 | `team-a/screen1/raw/a1-research.md` | Screen 1 | A2/A3 |
| 第一性原理 | `team-a/screen1/raw/a2-principles.md` | Screen 1 | A3/A4 |
| 大师研讨 | `team-a/screen1/raw/a3-seminar.md` | Screen 1 | Screen 2 |
| 方向输出 | `team-a/screen1/strategy-type.json` | Screen 1 完成 | Screen 2, Team B |
| 日线调研 | `team-a/screen2/raw/a1-daily.md` | Screen 2 | A2 daily |
| 日线推演 | `team-a/screen2/raw/a3-daily.md` | Screen 2 | A4 validation |
| **三大预设** | `team-a/screen2/daily-presets.json` | Screen 2 完成 | **Team B 入场** |
| 马丁阶梯 | `team-a/screen2/martingale-grid.json` | Screen 2 完成 | A5 下单 |

### 3.2 执行类产物（Team B）

| 产物 | 路径 | 产生时机 | 关键字段 |
|------|------|---------|---------|
| A7 门禁 | `team-b/a7-gate.json` | Phase 1 | `result: PASS/SKIP` |
| A4 验证 | `team-b/a4-validation.json` | Phase 2 | `result`, `confidence` |
| 下单日志 | `team-b/execution-log.md` | Phase 3.5 | 价格/数量/止损 |
| 仓位状态 | `team-b/position-state.json` | 每次状态变化 | `status`, `martingale_level` |
| 监控事件 | `team-b/a6-events.jsonl` | Phase 4 持续 | 加仓/风险告警 |
| 离场决策 | `team-b/a9-exit.json` | Phase 5 | `layer`, `pnl` |

### 3.3 门禁类产物（Gate C）

| 产物 | 路径 | 产生时机 | 关键字段 |
|------|------|---------|---------|
| 预交易门禁 | `gate-c/pretrade-check.json` | Phase 3 | `pass: true/false`, `reason_codes` |

### 3.4 复盘类产物（Process D）

| 产物 | 路径 | 产生时机 |
|------|------|---------|
| A8 复盘报告 | `review/a8-reflection.md` | 每周一 Process D |
| 会话摘要 | `session-summary.md` | 会话关闭时 |

---

## 四、关键索引文件

### 4.1 ACTIVE_SESSION.json（活跃会话指针）

```json
{
  "active_session_id": "20260528-BTC-USDT-SWAP-ENTRY",
  "session_path": "sessions/20260528-BTC-USDT-SWAP-ENTRY/",
  "status": "monitoring",
  "symbol": "BTC-USDT-SWAP",
  "started_at": "2026-05-28T09:00:00Z",
  "latest_screen1": "sessions/20260527-BTC-USDT-SWAP-SCREEN1/",
  "latest_screen2": "sessions/20260528-BTC-USDT-SWAP-SCREEN2/",
  "last_updated": "2026-05-28T09:30:00Z"
}
```

**更新时机**: 每次新 session 创建时写入；A9 离场后 `status` 改为 `closed`。

### 4.2 SESSION_INDEX.json（历史索引）

```json
{
  "sessions": [
    {
      "session_id": "20260527-BTC-USDT-SWAP-SCREEN1",
      "type": "screen1",
      "status": "closed",
      "direction": "LONG",
      "score": 82,
      "closed_at": "2026-05-27T20:30:00Z"
    },
    {
      "session_id": "20260528-BTC-USDT-SWAP-ENTRY",
      "type": "entry",
      "status": "monitoring",
      "entry_price": 79800,
      "martingale_level": 1
    }
  ],
  "last_updated": "2026-05-28T09:30:00Z"
}
```

---

## 五、命名规范

### Session 文件夹命名

```
{YYYYMMDD}-{SYMBOL}-{TRIGGER}

YYYYMMDD  : 创建日期（UTC+8）
SYMBOL    : 交易对（BTC-USDT-SWAP）
TRIGGER   : 触发类型

TRIGGER 枚举:
  SCREEN1   - 第一屏周线分析
  SCREEN2   - 第二屏日线预设
  ENTRY     - 入场执行（Team B）
  REVIEW    - 复盘（Process D）
```

示例：
```
20260527-BTC-USDT-SWAP-SCREEN1/
20260528-BTC-USDT-SWAP-SCREEN2/
20260528-BTC-USDT-SWAP-ENTRY/
20260602-BTC-USDT-SWAP-REVIEW/
```

### 产物文件命名

| 产物类型 | 命名规范 | 示例 |
|---------|---------|------|
| JSON 结果 | `{a系编号}-{描述}.json` | `a4-validation.json` |
| JSONL 事件流 | `{a系编号}-events.jsonl` | `a6-events.jsonl` |
| Markdown 报告 | `{a系编号}-{描述}.md` | `a8-reflection.md` |
| 执行日志 | `execution-log.md` | - |

---

## 六、快速查询

```bash
# 当前活跃 session
cat sessions/ACTIVE_SESSION.json | jq '.active_session_id'

# 最新三大预设
cat sessions/$(cat sessions/ACTIVE_SESSION.json | jq -r '.latest_screen2' | xargs basename)/team-a/screen2/daily-presets.json

# 当前仓位状态
SESS=$(cat sessions/ACTIVE_SESSION.json | jq -r '.session_path')
cat ${SESS}team-b/position-state.json

# 查看 A6 监控事件
tail -20 ${SESS}team-b/a6-events.jsonl
```

---

## 七、与旧邮箱方案的迁移对照

| 旧邮箱路径 | 新 Sessions 路径 |
|-----------|----------------|
| `screen1/screen1_{date}.md` | `sessions/{id}/team-a/screen1/weekly-direction.md` |
| `screen2/screen2_{date}.md` | `sessions/{id}/team-a/screen2/order-plan.md` |
| `signals/a4_signal_{ts}.md` | `sessions/{id}/team-b/a4-validation.json` |
| `signals/a5_signal_{ts}.md` | `sessions/{id}/team-b/execution-log.md` |
| `signals/a6_signal_{ts}.md` | `sessions/{id}/team-b/a6-events.jsonl` |
| `signals/a9_signal_{ts}.md` | `sessions/{id}/team-b/a9-exit.json` |
| `orders/active_orders.json` | `sessions/{id}/team-b/position-state.json` |
| `execution_log/exec_{date}.json` | `sessions/{id}/team-b/execution-log.md` |

> **旧路径已废弃**，新系统不再向 `~/.workbuddy/boss-secretary/` 写入产物。

---

## 八、写入规则（所有 SKILL 和脚本必须遵守）

```yaml
写入规则:
  1. 先读取 ACTIVE_SESSION.json 确认当前 session_id
  2. 所有产物写入 sessions/{session_id}/ 对应子目录
  3. 写入后更新 sessions/{session_id}/meta.json 的 last_updated
  4. A9 离场后同步写入 session-summary.md，并更新 ACTIVE_SESSION.json status = "closed"
  5. 新 session 创建时，同步更新 SESSION_INDEX.json

禁止事项:
  ✗ 向 ~/.workbuddy/boss-secretary/ 写入产物（已废弃）
  ✗ 在 sessions/ 以外的位置存储交易产物
  ✗ 使用绝对本地路径（如 /Users/xxx）
```
