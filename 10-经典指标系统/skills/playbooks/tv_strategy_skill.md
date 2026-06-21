# TV 策略 SKILL（外联导入 → 策略资产入库 → 沙箱验证 → 审批上线）

更新时间：2026-03-15

## 1. 定位与边界

本 SKILL 用于把 TradingView 的策略脚本（Pine Script）导入为“策略资产库”中的可治理资产，并完成最小验证闭环：

- 导出 Pine：从你本机已登录的 TradingView 中检索（按社区热度/策略名）并导出源码
- 转化策略：将 Pine 规则转为符合 Freqtrade 规范且符合本仓库 SimpleStrategy 规范的策略文件
- 沙箱回测：验证策略可运行且可产出信号（或明确标注无交易原因）
- 入库治理：进入 Research 资产池后，再按既有流程晋升为 Model/Deployment 并上线

本 SKILL 不直接影响生产交易执行面：

- 默认只写入 `user_data/strategies/tradingview/` 资产目录
- 默认不把策略文件放入运行目录，也不修改全局配置
- 晋升到可运行目录必须走审批与变更包（changeset/pipeline）流程

## 2. 运行域与分级（R0/R1/R2/R3）

该链路被拆分为四段能力，按“外联/写入/回测/修复”分域治理：

1) `tradingview.strategy.export.request`（R2 / outbox_channel / push）
- 只入队导出请求，不执行浏览器自动化

2) `tradingview.strategy.exporter`（R2 / host_script / push）
- 宿主侧执行：使用本机浏览器 profile 执行搜索与复制源码并落盘

3) `strategy_import.tv_pine_to_freqtrade.simple`（R2 / sandbox_script / governance）
- 外联模型执行（建议由 NanoClaw 执行）：把 Pine 转为策略资产（Research 目录）

4) `sandbox.backtest`（R1 / inproc / sandbox）
- 系统内回测能力，绑定产物落盘与证据链

失败修复：
- 默认不使用本地“FAQ 级”修复去强行 patch 复杂策略
- 统一通过 NanoClaw 的大模型能力做修复与迭代，并把修复链路写入 outbox/receipt

### 2.1 路径 A/B 决策树（源码可得 vs 黑盒资产）

决策输入：

- `visibility_type`：`open` / `protected` / `invite_only` / `built_in`
- `is_author`：当前账号是否脚本作者
- `source_visible`：在 Pine Editor 中是否可见源码

决策规则：

1) 路径 A（源码资产）
- 条件：`source_visible=true`
- 典型：Open 脚本、作者本人脚本、可见源码的 built-in
- 产物：`original.pine` + 转化策略 `.py` + backtest 产物 + checksums

2) 路径 B（黑盒资产）
- 条件：`source_visible=false`
- 典型：Protected / Invite-only 且非作者
- 产物：不生成 `original.pine`，转为黑盒资产包（alerts/strategy report/参数快照）

约束：

- 路径 B 严禁声明“已获取源码”
- 路径 B 不做源码级转化，不产出可执行策略代码

## 3. 策略开发规范（强制对齐 SimpleStrategy）

转化输出必须满足本仓库规范：

- 目录固定：`经典指标机器学习系统/user_data/strategies` 的子资产域（见下文目录形态）
- 禁止项：策略文件内禁止 `sys.path` 注入，禁止跨工程依赖
- 三段式：`populate_indicators` / `populate_entry_trend` / `populate_exit_trend`
- 字段初始化：enter/exit 字段必须初始化；必须处理同 bar 多空冲突
- 指标库优先：TA-Lib（`talib.abstract as ta`）与 qtpylib
- 参数化：关键阈值/窗口使用 `IntParameter/DecimalParameter`
- 可解释性：必须提供 `plot_config`

规范原文：`经典指标机器学习系统/策略开发规范（基于SimpleStrategy）.md`

## 4. 策略资产库目录形态（TradingView 独立域）

目标：把 GitHub 策略资产与 TV 策略资产物理隔离、索引可并行、治理口径一致。

建议目录：

```
user_data/strategies/
  tradingview/
    research/
      <strategy_key>/
        source/
          pine/
            original.pine
          meta.json
        strategy/
          <StrategyClassName>.py
        backtest/
          config.snapshot.json
          report.md
          metadata.json
          stdout.log
          stderr.log
        checksums/
          sha256.json
    model/
      <strategy_key>/
        ...
    deployment/
      <strategy_key>/
        ...
    _by_family/
    _by_stage/
    _by_tier/
    _by_market/
    _by_timeframe/
    _by_tag/
    _reports/
```

路径 B（黑盒资产）建议目录：

```
user_data/strategies/
  tradingview/
    research/
      <strategy_key>/
        source/
          meta.json
        blackbox/
          alerts.json
          strategy_report.md
          params_snapshot.json
          execution_notes.md
        checksums/
          sha256.json
```

关键约束：

- `tradingview/research` 允许快速迭代与失败，但必须可追溯（来源、时间窗、导出链接、回测口径）
- `tradingview/model` 与 `tradingview/deployment` 目录中的 bundle 必须不可变（immutable），且必须绑定审批信息
- `user_data/strategies/` 顶层运行目录只允许放“已审核可运行策略”；TV 导入默认不进入该目录

## 5. Research → Model → Deployment 迁移规则（最小状态机）

状态机：

`research_draft → research_validated → model_candidate → approved → deployed(canary/full) → deprecated/rolled_back`

晋升门槛（建议最小门禁）：

- Research Validated：
  - 通过 SimpleStrategy 规范检查（结构/字段/禁用项）
  - 沙箱回测 returncode=0
  - 交易数/信号密度不为 0；若为 0，必须标注原因并保留为 draft

- Model Candidate：
  - 有明确的回测口径与配置快照
  - 至少一次稳健性检查（可选：分段/滚动）
  - 产物 `checksums/sha256.json` 覆盖 manifest/strategy/config/reports

- Deployment：
  - 审批通过（approved_by/approved_at/approval_id）
  - 灰度与回滚条件写入 bundle 元数据

## 6. outbox/receipt 口径（证据链）

### 6.1 导出 Pine（R2）

request（写入 outbox）：

```json
{
  "event": "tradingview.strategy.export.request",
  "trace_id": "uuid",
  "idempotency_key": "sha256(trace_id+strategy_query+timewindow)",
  "requested_at": "2026-03-15T00:00:00Z",
  "payload": {
    "strategy_query": "string",
    "prefer_sort": "popularity",
    "max_candidates": 10,
    "target": {
      "tv_url": "https://www.tradingview.com/...",
      "script_name": "optional",
      "author": "optional"
    },
    "output_dir": "user_data/strategies/tradingview/research/<strategy_key>/source/pine"
  }
}
```

receipt（写入 delivery_receipts）：

```json
{
  "event": "tradingview.strategy.export.receipt",
  "trace_id": "uuid",
  "idempotency_key": "same_as_request",
  "ok": true,
  "artifacts": {
    "pine_path": "user_data/strategies/tradingview/research/<strategy_key>/source/pine/original.pine",
    "meta_path": "user_data/strategies/tradingview/research/<strategy_key>/source/meta.json"
  },
  "errors": []
}
```

### 6.2 转化与修复（外联模型，R2）

request：

```json
{
  "event": "strategy_import.tv_pine_to_freqtrade.simple.request",
  "trace_id": "uuid",
  "idempotency_key": "sha256(trace_id+pine_sha256+policy_version)",
  "payload": {
    "pine_path": "path",
    "target_strategy_class": "PascalCaseName",
    "timeframe": "1h",
    "policy_ref": "simple_strategy_spec_v1",
    "output_dir": "user_data/strategies/tradingview/research/<strategy_key>/strategy"
  }
}
```

### 6.3 黑盒资产入库（路径 B）

request：

```json
{
  "event": "strategy_import.tv_blackbox_asset.request",
  "trace_id": "uuid",
  "idempotency_key": "sha256(trace_id+tv_url+policy_version)",
  "payload": {
    "strategy_key": "string",
    "tv_url": "https://www.tradingview.com/...",
    "visibility_type": "invite_only",
    "alerts": [],
    "strategy_report_markdown": "string",
    "params_snapshot": {},
    "output_dir": "user_data/strategies/tradingview/research/<strategy_key>/blackbox"
  }
}
```

receipt：

```json
{
  "event": "strategy_import.tv_blackbox_asset.receipt",
  "trace_id": "uuid",
  "idempotency_key": "same_as_request",
  "ok": true,
  "artifacts": {
    "alerts_path": "user_data/strategies/tradingview/research/<strategy_key>/blackbox/alerts.json",
    "strategy_report_path": "user_data/strategies/tradingview/research/<strategy_key>/blackbox/strategy_report.md",
    "params_snapshot_path": "user_data/strategies/tradingview/research/<strategy_key>/blackbox/params_snapshot.json"
  },
  "errors": []
}
```

receipt：

```json
{
  "event": "strategy_import.tv_pine_to_freqtrade.simple.receipt",
  "trace_id": "uuid",
  "idempotency_key": "same_as_request",
  "ok": true,
  "artifacts": {
    "strategy_py_path": "user_data/strategies/tradingview/research/<strategy_key>/strategy/<StrategyClassName>.py"
  },
  "errors": [],
  "notes": {
    "known_deviations": ["list of intentional simplifications, if any"]
  }
}
```

## 7. 最小 tool_plan（Plan-Then-Execute）

执行计划必须先生成不可变 plan，再逐步执行，并在 outbox 中落盘每一步结果：

1) 生成 `strategy_key`（与 TV 脚本/作者/时间戳绑定）
2) 入队导出请求（R2）
3) 等待 receipt，拿到 `original.pine` 与 `meta.json`
4) 入队转化请求（R2），输出策略文件到 Research bundle
5) 调用 `sandbox.backtest`（R1）验证策略
6) 写入 bundle 的 `checksums/sha256.json`
7) 生成“入库摘要”（供策略资产审批流程使用）

路径 B（黑盒）最小流程：

1) 生成 `strategy_key`
2) 入队导出请求（R2）
3) 收到 `source_visible=false` 的 receipt
4) 入队黑盒资产请求（alerts/strategy report/params）
5) 写入 `checksums/sha256.json`
6) 生成黑盒入库摘要（用于审批与后续作者授权补源）
