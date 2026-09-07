# 自进化架构可视化 Tab 设计 Spec

> **日期**: 2026-09-05
> **状态**: 已确认 — 待转入实施计划
> **作者**: brainstorming 流程产出
> **关联**: 取代隐藏的"☁️ 云端调度"Tab · 落地"自进化可视化要以交易数据来评估"用户决策

---

## 1. 背景与目标

### 1.1 背景
- 8765 监控页 [monitor.html](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/monitor.html) 现有 12 个 Tab，其中"☁️ 云端调度"价值有限（运维兜底监控，非研究/叙事维度）。
- 用户决策：隐藏云端调度（不删除，可恢复），新增"🧬 自进化架构"Tab 取代其位置。
- **核心要求**："自进化可视化还是要以交易数据来评估"——不是纯静态架构图，而是用真实交易/进化数据回答"系统是否真的在自我进化、效果如何"。
- AGI 时代叙事：自我进化系统是 AGI 主路径之一，对外可视化叙事价值显著高于运维监控。

### 1.2 核心评估问题
**25U 演化子池（source_tag="evolution"）vs 非evolution主池（其他 source_tag 合并），谁表现更好？系统是否在真实进化？**

### 1.3 范围
- **MVP（本 Spec）**: 4 区块可视化 + ECharts 交互下钻 + 4 后端 API + 时间窗口切换
- **不在 MVP（Phase 2）**: 实时 WebSocket 推送、策略维度下钻（evolution 内部按策略拆分）、回测对比基准

---

## 2. 现有资产盘点

### 2.1 前端
- 入口：[monitor.html](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/monitor.html)（单页 12 Tab 内联）
- CSS 既有类：`.card` / `.tab-grid` / `.stats-grid` / `.stat` / `.schedule-grid-3`
- 已有 CDN 先例：可复用 CDN 引入 ECharts
- 云端调度 Tab 涉及行：
  - Tab 按钮 [L194](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/monitor.html#L194)
  - Tab 内容 [L409-L455](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/monitor.html#L409-L455)
  - 数据加载逻辑 L2809-L2910

### 2.2 后端
- 服务入口：[data_server_fixed.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/data_server_fixed.py)（端口 8765，`ThreadedHTTPServer` + `BaseHTTPRequestHandler`）
- 现有路由分发：[L3403-L3458](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/data_server_fixed.py#L3403-L3458)
- `/api/state` 入口：[L3410-L3413](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/data_server_fixed.py#L3410-L3413)
- `get_full_state()` 聚合：[L352-L365](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/data_server_fixed.py#L352-L365)
- 数据目录：`open_positions/` / `risk/risk_state.json` / `guardian/heartbeat.json` / `stats/performance.json`

### 2.3 进化系统资产与数据源现状

**已确认可用的数据源**:

- **平仓历史 JSONL**: `11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl`
  - `PerformanceTracker._save_trade()` 以 append 写入（[trading_utils.py L118-L180](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/trading_utils.py#L118-L180)）
  - 字段: `trade_id` / `coin` / `inst_id` / `direction` / `entry_price` / `exit_price` / `pnl` / `exit_reason` / `confidence` / `hexagram` / `strategy_source` / `entry_time` / `exit_time`
  - **关键**: 区分 evolution vs main_pool 用 `strategy_source == "evolution"`（非 `source_tag`，因 JSONL 字段是 strategy_source）
- **全局汇总**: `11-易经推理系统/.workbuddy/memory_l4/stats/performance.json`
  - 字段: `total_trades` / `win_count` / `loss_count` / `win_rate` / `total_pnl` / `avg_pnl` / `max_win` / `max_loss` / `consecutive_losses` / `last_update`
  - 全局汇总，无 evolution/main_pool 拆分（需从 all_trades.jsonl 聚合）
- **当前持仓**: `position_tracker.all_open_positions()`（[trading_utils.py L1073-L1271](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/trading_utils.py#L1073-L1271)）
  - `TradeRecord` 含 `source_tag` 字段（[L70-L74](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/trading_utils.py#L70-L74)）
  - **注意**: position_tracker 无 `closed_positions()` 方法，平仓历史在 all_trades.jsonl
- **入场快照**: `gene_data/evolution_snapshots.json`（[trade_settlement_bridge.py L20-L76](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/engines/trade_settlement_bridge.py#L20-L76)）
  - 仅 pre_trade_snapshot（d_star / ri / confidence 等）
  - **不含** cs/ess_delta/gmax_mult 等后验数据

**已确认缺失的数据源（降级处理）**:

- **ReflectionEngine 历史未持久化**: [reflection_engine.py L42-L121](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/dreambuddy_core/reflection_engine.py#L42-L121) `calculate_cs()` / `apply_reward()` 仅内存计算，返回值未落盘
- **ESS/gmax/cluster 历史轨迹未持久化**: tight_coupling_orchestrator 7步闭环的 reflect/learn/feedback 产出未写入文件
- **降级方案**: 区块4"进化证据"显示"进化引擎数据接入中"占位，不阻塞 MVP 1-3 区块。后续单独排期实现 ReflectionEngine 持久化（新增 `reflection_history.jsonl`，Phase 2 范围）

**进化系统代码资产（参考）**:

- **演化子池建仓**: [polling_trader.py L7448-L7515](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/polling_trader.py#L7448-L7515) — `source_tag="evolution"` / `strategy_source="evolution"`、25U 硬上限、5x isolated
- **闭环 7 步产出**: [tight_coupling_orchestrator.py L37-L60](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/dreambuddy_core/tight_coupling_orchestrator.py#L37-L60)（ri 触发）+ [L150-L182](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/dreambuddy_core/tight_coupling_orchestrator.py#L150-L182)（cs / ess_delta / gmax_mult / cluster_weight_mult / anti_pattern_flag，内存传递未落盘）
- **涟漪引擎**: [ripple_engine.py L58-L87](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/dreambuddy_core/ripple_engine.py#L58-L87) `compute_ri()` + `get_ri_action()`
- **认知记忆**: `mcp_cognitive` MCP server（recall/record/verify/stats/health），数据库 `4-MEMORY/data/cognitive_memory.db`

---

## 3. 设计方案

### 3.1 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  🧬 自进化架构      [7天] [30天] [全部]   最后更新: ...  │
├─────────────────────────────────────────────────────────┤
│ 区块1: 核心盈亏指标卡片                                  │
│  ┌──────────────┬──────────────┐                       │
│  │ 演化子池(25U)│ 主池(非evo)   │                       │
│  │ 总盈亏  +X   │ 总盈亏  +Y    │                       │
│  │ 胜率   65%   │ 胜率   55%    │                       │
│  │ 最大回撤 -3% │ 最大回撤 -8%  │                       │
│  │ 仓位数  2    │ 仓位数  5     │                       │
│  │ 运行天数 14  │ 运行天数 90   │                       │
│  └──────────────┴──────────────┘                       │
├─────────────────────────────────────────────────────────┤
│ 区块2: 累计盈亏曲线对比 (ECharts 折线)                  │
│  ─── 演化子池  ─── 主池                                 │
│  (点击节点 → modal 显示单笔交易详情)                    │
├─────────────────────────────────────────────────────────┤
│ 区块3: 每日盈亏柱状对比 (ECharts 柱状)                  │
│  ▮ 演化子池  ▮ 主池                                     │
│  (点击柱子 → modal 显示当日交易列表)                    │
├─────────────────────────────────────────────────────────┤
│ 区块4: 进化证据                                          │
│  ┌──────────────┬──────────────┐                       │
│  │ ESS评分曲线  │ 反思触发次数  │                       │
│  │ gmax校准轨迹 │ CS一致性分布  │                       │
│  └──────────────┴──────────────┘                       │
│  (点击节点 → modal 显示单次反思记录)                    │
└─────────────────────────────────────────────────────────┘
```

### 3.2 隐藏云端调度（3 处注释，零删除）
1. 注释 [monitor.html L194](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/monitor.html#L194) Tab 按钮（一行）
2. 注释 [monitor.html L409-L455](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/monitor.html#L409-L455) Tab 内容块
3. 注释 L2809-L2910 数据加载逻辑
4. 默认 active 保持 `local`（已是当前状态，无需改）

---

## 4. 后端 API 设计

新增 4 个 API 到 [data_server_fixed.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/data_server_fixed.py) 的路由分发器（L3410-L3458）。

### 4.1 `GET /api/evolution-overview`

**入参**: `range=7d|30d|all`（默认 `all`）

**返回**:
```json
{
  "range": "7d",
  "last_update": "2026-09-05 19:30:00",
  "evolution": {
    "total_pnl": 12.34,
    "win_rate": 0.65,
    "max_drawdown": -0.03,
    "position_count": 2,
    "running_days": 14,
    "closed_count": 8,
    "currency": "USDT"
  },
  "main_pool": {
    "total_pnl": 234.56,
    "win_rate": 0.55,
    "max_drawdown": -0.08,
    "position_count": 5,
    "running_days": 90,
    "closed_count": 120,
    "currency": "USDT"
  }
}
```

**数据源**:
- **当前持仓计数**: `position_tracker.all_open_positions()` 按 `source_tag == "evolution"` 区分（用于 position_count）
- **平仓历史**: `all_trades.jsonl` 按 `strategy_source == "evolution"` 区分（用于 total_pnl/win_rate/max_drawdown/closed_count）
- **运行天数**: 从 all_trades.jsonl 最早一条 trade 的 entry_time 计算
- 时间窗口：基于 all_trades.jsonl 的 `exit_time` 过滤

**降级**: evolution 子池数据不足（<7 天或 closed_count < 1）时，`evolution` 字段各指标返回 `null`，前端显示"数据积累中"。

### 4.2 `GET /api/evolution-timeline`

**入参**: `range=7d|30d|all`（默认 `all`）

**返回**:
```json
{
  "range": "7d",
  "dates": ["2026-08-30", "2026-08-31", ..., "2026-09-05"],
  "cumulative": {
    "evolution": [0.0, 1.2, 2.5, ..., 12.34],
    "main_pool": [100.0, 105.0, 102.0, ..., 234.56]
  },
  "daily": {
    "evolution": [0.0, 1.2, 1.3, -0.5, ..., 0.8],
    "main_pool": [0.0, 5.0, -3.0, 8.0, ..., 2.5]
  },
  "trade_points": {
    "evolution": [
      {"date": "2026-08-31", "trade_id": "tx_001", "pnl": 1.2, "symbol": "BTC", "direction": "long"},
      ...
    ],
    "main_pool": [...]
  }
}
```

**数据源**:
- `all_trades.jsonl` 按 `exit_time` 排序，按 `strategy_source` 区分 evolution vs main_pool
- 累计 = 前一日累计 + 当日盈亏
- daily = 当日所有 closed trades 盈亏之和
- `trade_points` 用于前端点击节点下钻（含 trade_id）

**降级**: 无数据时返回空数组，前端图表显示"暂无数据"。

### 4.3 `GET /api/evolution-evidence`

**入参**: `range=7d|30d|all`（默认 `all`）

**返回**:
```json
{
  "range": "7d",
  "ess_curve": {
    "dates": ["2026-08-30", ..., "2026-09-05"],
    "evolution_avg": [0.62, 0.64, 0.65, ..., 0.71],
    "main_pool_avg": [0.55, 0.55, 0.56, ..., 0.58]
  },
  "reflection_count": {
    "evolution": 5,
    "main_pool": 42,
    "by_date": {"2026-08-30": 1, ..., "2026-09-05": 2}
  },
  "cs_distribution": {
    "evolution": {"min": 0.3, "p25": 0.5, "median": 0.7, "p75": 0.85, "max": 0.95, "samples": [0.3, 0.5, ...]},
    "main_pool": {"min": 0.1, "p25": 0.4, "median": 0.6, "p75": 0.8, "max": 0.95, "samples": [...]}
  },
  "gmax_trajectory": {
    "dates": [...],
    "gmax_mult": [1.0, 1.02, 1.05, ..., 1.15],
    "cluster_weight_mult": [1.0, 0.98, 1.03, ..., 1.08]
  }
}
```

**数据源现状（已确认缺失）**:
- ReflectionEngine 的 cs/ess_delta/gmax_mult/cluster_weight_mult 历史轨迹**未持久化**（仅内存计算，返回值未落盘）
- 4-MEMORY `cognitive_memory.db` 的 stats 可访问，但与交易级 cs/ess 数据无直接关联

**MVP 降级方案**:
- 所有字段返回空数组/0 + `"degraded": true` 标记
- 前端区块4 显示"进化引擎数据接入中（ReflectionEngine 持久化为 Phase 2 范围）"
- 不阻塞 MVP 1-3 区块

**Phase 2 持久化方案（不在本 MVP）**:
- 新增 `reflection_history.jsonl`，在 tight_coupling_orchestrator.py 的 reflect/learn 阶段写入
- 字段: `timestamp` / `trade_id` / `source_tag` / `cs` / `ess_delta` / `gmax_mult` / `cluster_weight_mult` / `anti_pattern_flag`
- 持久化实现后，本 API 自动恢复完整数据返回

### 4.4 `GET /api/evolution-detail`

**入参**: `type=trade|reflection` + `id=<trade_id|reflection_id>`

**返回 (type=trade)**:
```json
{
  "type": "trade",
  "trade_id": "tx_001",
  "symbol": "BTC",
  "direction": "long",
  "source_tag": "evolution",
  "entry_time": "2026-08-31 10:00:00",
  "entry_price": 58000.0,
  "close_time": "2026-08-31 14:00:00",
  "close_price": 58500.0,
  "pnl": 1.2,
  "pnl_pct": 0.04,
  "cs": 0.75,
  "ess_before": 0.62,
  "ess_after": 0.64,
  "gmax_delta": 0.02,
  "reason": "evolution_auto_long conf=0.55 d*=0.62",
  "pre_trade_snapshot": {...}
}
```

**返回 (type=reflection)**:
```json
{
  "type": "reflection",
  "reflection_id": "r_001",
  "trade_id": "tx_001",
  "source_tag": "evolution",
  "cs": 0.75,
  "ess_delta": 0.02,
  "gmax_mult": 1.02,
  "cluster_weight_mult": 1.0,
  "anti_pattern_flag": false,
  "timestamp": "2026-08-31 14:05:00",
  "level0_dstar": 0.62,
  "ess_dir": "long",
  "cbr_top1_outcome": "win",
  "actual_dir": "long",
  "actual_result": "win"
}
```

**数据源**:
- **type=trade**: `all_trades.jsonl` 按 `trade_id` 查找单笔记录 + `evolution_snapshots.json` 按 trade_id 关联 pre_trade_snapshot（若存在）
- **type=reflection**: **MVP 降级** — ReflectionEngine 历史未持久化，返回 `{"degraded": true, "message": "ReflectionEngine 持久化为 Phase 2 范围"}`

**降级**: id 不存在时返回 404 + `{"error": "not found"}`。reflection 类型在 MVP 阶段返回降级提示。

---

## 5. 前端实现

### 5.1 文件组织
- **monitor.html**: 新增 Tab 按钮 + `<div id="tab-evolution">` 容器 + 引入 evolution.js + ECharts CDN
- **新增 evolution.js**（放 `experiments/ab-trading/` 下）: 4 区块渲染逻辑 + 下钻 modal + 时间窗口切换

### 5.2 Tab 按钮（取代 L194）
```html
<div class="tab" onclick="switchTab('evolution', event)">🧬 自进化架构</div>
```

### 5.3 Tab 容器结构
```html
<div id="tab-evolution" class="tab-content">
  <div class="tab-grid">
    <!-- 顶部时间窗口切换 + 最后更新 -->
    <div class="card full-width" style="display:flex;justify-content:space-between;align-items:center">
      <div style="font-size:18px;font-weight:bold">🧬 自进化架构</div>
      <div>
        <button class="evo-range-btn" data-range="7d">7天</button>
        <button class="evo-range-btn" data-range="30d">30天</button>
        <button class="evo-range-btn active" data-range="all">全部</button>
        <span id="evo-last-update" style="margin-left:16px;color:var(--muted)"></span>
      </div>
    </div>

    <!-- 区块1: 核心盈亏指标卡片 -->
    <div class="card full-width">
      <div class="card-title"><div class="dot dot-green"></div>核心盈亏指标</div>
      <div class="schedule-grid-3" style="grid-template-columns:1fr 1fr">
        <div id="evo-overview-evolution" class="schedule-card">...</div>
        <div id="evo-overview-main" class="schedule-card">...</div>
      </div>
    </div>

    <!-- 区块2: 累计盈亏曲线 -->
    <div class="card full-width">
      <div class="card-title"><div class="dot dot-green"></div>累计盈亏曲线对比</div>
      <div id="evo-chart-cumulative" style="height:360px"></div>
    </div>

    <!-- 区块3: 每日盈亏柱状 -->
    <div class="card full-width">
      <div class="card-title"><div class="dot dot-green"></div>每日盈亏柱状对比</div>
      <div id="evo-chart-daily" style="height:300px"></div>
    </div>

    <!-- 区块4: 进化证据 -->
    <div class="card full-width">
      <div class="card-title"><div class="dot dot-green"></div>进化证据</div>
      <div class="schedule-grid-3" style="grid-template-columns:1fr 1fr">
        <div><div style="font-weight:bold;margin-bottom:8px">ESS 评分曲线</div><div id="evo-chart-ess" style="height:240px"></div></div>
        <div><div style="font-weight:bold;margin-bottom:8px">反思触发次数</div><div id="evo-chart-reflection" style="height:240px"></div></div>
        <div><div style="font-weight:bold;margin-bottom:8px">gmax 校准轨迹</div><div id="evo-chart-gmax" style="height:240px"></div></div>
        <div><div style="font-weight:bold;margin-bottom:8px">CS 一致性分布</div><div id="evo-chart-cs" style="height:240px"></div></div>
      </div>
    </div>
  </div>
</div>

<!-- 下钻 modal -->
<div id="evo-detail-modal" style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.5);z-index:9999">
  <div style="background:var(--bg);margin:5% auto;padding:24px;width:80%;max-width:800px;border-radius:8px;max-height:80%;overflow:auto">
    <div id="evo-detail-content"></div>
    <button onclick="document.getElementById('evo-detail-modal').style.display='none'" style="margin-top:16px">关闭</button>
  </div>
</div>
```

### 5.4 ECharts 交互
- **折线/柱状点击**: `chart.on('click', params => showDetail(params.data.tradeId))`
- **modal 内容**: 调用 `/api/evolution-detail?type=trade&id=...` 渲染 JSON 为表格
- **时间窗口切换**: `data-range` 按钮 → 重新调用 4 个 API → 更新所有图表

### 5.5 降级显示
- evolution 数据不足：卡片显示"演化子池数据积累中（运行 X 天）"
- API 异常：区块内显示错误提示，不阻塞其他区块
- 主池无数据：图表仅显示 evolution 单系列

---

## 6. 数据访问层封装

为避免 API 直接操作底层对象，新增 `evolution_data_accessor.py`（放 `11-易经推理系统/scripts/` 下），封装以下函数：

```python
def get_evolution_overview(range_days: int | None) -> dict:
    """返回 evolution + main_pool 各 5 指标"""

def get_evolution_timeline(range_days: int | None) -> dict:
    """返回 cumulative + daily 双系列 + trade_points"""

def get_evolution_evidence(range_days: int | None) -> dict:
    """返回 ess_curve + reflection_count + cs_distribution + gmax_trajectory"""

def get_evolution_detail(detail_type: str, detail_id: str) -> dict | None:
    """返回单笔 trade 或单次 reflection 详情"""
```

**职责**:
- 隔离 `position_tracker` / `ReflectionEngine` / `cognitive_memory.db` 的具体访问细节
- 处理 `source_tag` 区分逻辑
- 处理时间窗口过滤
- 处理降级（数据不足时返回 None / 空结构）

**API 层**（data_server_fixed.py 内）仅做 HTTP 入参解析 + JSON 序列化，不直接访问底层数据。

---

## 7. 错误处理与降级

### 7.1 后端
- API 异常时返回 `{"error": "...", "fallback": true}` + HTTP 200（避免前端 CORS 处理复杂化）
- 单个 API 失败不影响其他 API
- 数据访问层访问 `cognitive_memory.db` 失败时：捕获异常，`cs_distribution` 字段降级为 `null`，其他字段正常返回

### 7.2 前端
- 每个 API 调用独立 try/catch
- 单区块失败：区块内显示"数据加载失败"，不阻塞其他区块
- evolution 数据不足（running_days < 7 或 closed_count < 1）：
  - 区块1 evolution 卡片显示"数据积累中"
  - 区块2/3 图表仅显示 main_pool
  - 区块4 进化证据显示"演化子池反思样本不足"

---

## 8. 测试策略

### 8.1 后端单元测试
新增 `test_evolution_data_accessor.py`（放 `11-易经推理系统/tests/` 下，跟随现有测试约定）：

- `test_get_evolution_overview_distinguishes_source_tag`: 验证 evolution vs main_pool 正确区分
- `test_get_evolution_overview_range_filter`: 验证 7d/30d/all 时间窗口
- `test_get_evolution_overview_empty_evolution`: evolution 无数据时降级
- `test_get_evolution_timeline_cumulative_daily`: 验证累计/daily 计算正确
- `test_get_evolution_timeline_empty`: 无数据时返回空数组
- `test_get_evolution_evidence_cs_distribution`: 验证分位数计算
- `test_get_evolution_evidence_degraded`: cognitive_memory.db 访问失败时降级
- `test_get_evolution_detail_trade`: 验证 trade 详情字段
- `test_get_evolution_detail_reflection`: 验证 reflection 详情字段
- `test_get_evolution_detail_not_found`: id 不存在返回 None

### 8.2 API 层测试
新增 `test_evolution_api.py`：
- 各 API 入参解析（range 默认 all、非法值兜底为 all）
- 异常时返回 fallback 结构
- JSON 序列化正确

### 8.3 前端手动冒烟测试清单
- [ ] Tab 切换正常，4 区块渲染
- [ ] 时间窗口切换（7d/30d/all）数据更新
- [ ] 折线节点点击 → modal 显示 trade 详情
- [ ] 柱状点击 → modal 显示当日交易列表
- [ ] 进化证据 4 子图点击 → modal 显示 reflection 详情
- [ ] evolution 数据不足时降级显示
- [ ] 云端调度 Tab 已隐藏，其他 Tab 不受影响
- [ ] 网络异常时区块内错误提示

---

## 9. 实施步骤（高层）

1. **隐藏云端调度 Tab**（3 处注释，零风险，可一键恢复）
2. **新增 evolution_data_accessor.py** + 单元测试（先 RED 再 GREEN，跟随 TDD 约定）
3. **新增 4 个 API 路由** 到 data_server_fixed.py + API 测试
4. **新增 evolution.js** + monitor.html 接入（Tab 按钮 + 容器 + ECharts CDN）
5. **前端手动冒烟测试**
6. **认知记忆 record**：spec 确认后调用 `record` 写入硬约束（如有）

---

## 10. 不在 MVP 范围（Phase 2 候选）

- 实时 WebSocket 推送（当前用刷新按钮）
- 策略维度下钻（evolution 内部按策略拆分）
- 回测对比基准（evolution vs 历史回测 Sharpe）
- 自定义时间区间选择器
- 数据导出 CSV
- 多账户聚合（当前仅 OKX）

---

## 11. 风险与权衡

| 风险 | 缓解 |
|---|---|
| ReflectionEngine 历史未持久化（已确认） | 区块4 显示"进化引擎数据接入中"占位，不阻塞 MVP 1-3。Phase 2 新增 reflection_history.jsonl |
| position_tracker 无 closed_positions() 方法（已确认） | 平仓历史从 `all_trades.jsonl` 读取，position_tracker 仅用于当前持仓计数 |
| all_trades.jsonl 字段是 strategy_source 不是 source_tag | 数据访问层按 `strategy_source == "evolution"` 区分 evolution vs main_pool |
| ECharts CDN 加载失败 | MVP 接受 CDN 依赖（monitor.html 已有 CDN 先例）；Phase 2 可改本地打包 |
| evolution 子池刚启动数据少 | 降级显示"数据积累中"，不报错 |
| 主池历史持仓无 strategy_source 字段 | 数据访问层将 `strategy_source != "evolution"`（含 None/空字符串）全部归入 main_pool |

---

## 12. 验收标准

- [ ] 云端调度 Tab 已隐藏（注释，可一键恢复）
- [ ] 🧬 自进化架构 Tab 可切换、4 区块渲染
- [ ] 时间窗口 7d/30d/all 切换正常
- [ ] evolution vs main_pool 数据正确区分
- [ ] 折线/柱状/进化证据 4 子图点击下钻正常
- [ ] evolution 数据不足时降级显示
- [ ] 后端单元测试 ≥10 个全 GREEN
- [ ] 前端冒烟测试清单全过

---

## 13. 已解决的开放问题

1. **ReflectionEngine 持久化现状**（已确认）: 未持久化，区块4 降级显示"进化引擎数据接入中"，Phase 2 实现 reflection_history.jsonl
2. **ECharts 引入方式**（已确认）: MVP 用 CDN（monitor.html 已有 CDN 先例），Phase 2 可改本地打包
3. **时间窗口默认值**（已确认）: 默认 `all`（HTML active 类已对齐）
