# 经典指标系统 — 技术设计文档

> **版本**: v2.0 | **更新日期**: 2026-07-31
> **定位**: 经典指标系统技术架构设计，面向开发者理解系统内部实现
> **关联**: [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) v1.1 · [API_SPEC.md](./API_SPEC.md) v1.1 · [CHANGELOG.md](./CHANGELOG.md) v1.1
> **历史**: 由根目录 `技术文档2.0.md`（2026-02-07 维护版）于 2026-07-31 迁入 docs/，原内容保留，逐步按 DOC_STANDARD 规范重构

## 0. 使用规则（强制）

### 0.1 变更流程

任何功能修改/扩展遵循以下流程：

1. 先阅读 [技术文档规范.md](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/技术文档规范.md)（尤其是：主章节入口索引、开关矩阵、Runbook、变更日志）。
2. 再出方案（包含：影响范围、接口/配置变更、验收标准、回滚策略）。
3. 再改代码（小步提交，保持可回退）。
4. 验收合格后，必须在“变更日志”追加记录（包含：原因、改动点、验证方式、风险）。

强制约束（与 AI Agent/沙箱协作时必须遵守）：

- 变更前必须通过本文件“工程索引（0.3）”与“FAQ 快速定位（0.3）”先定位入口与既有排障口径，优先复用已有经验，以最小化方式修改。
- 任何会改变交易系统运行行为的修复/优化，必须在本文件（交易系统）补齐或更新对应的排障口径/FAQ；任何会改变 AI Agent 行为边界、门禁、审计、沙箱闭环的修复/优化，必须同步更新 [交易AI Agent 技术文档2.0.md](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/交易AI%20Agent%20技术文档2.0.md)。
- 禁止绕过文档直接改动高风险能力：生产侧写入接口（例如 `/config/set`、`/evaluation/rollback/restore`）只能按文档约束执行，并具备可审计、可回滚的变更单/变更包依据。

### 0.2 文档维护原则

- 每个模块章节都包含“入口索引”：关键文件、关键函数/路由、关键配置项。
- 每个关键开关/风控拦截点都必须在文档中可被定位。
- 文档优先服务“快速定位与修改”。

### 0.3 工程索引（必读入口）

- 运行入口
  - 后端服务（Flask）：[ml_trade_service.py](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py)
  - 前端 Dashboard（Vite + React）：[frontend/](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend)
- 核心链路入口（Strategy 信号 → 决策 Gate/Arena → 执行 → 结算）
  - 信号接收（通用）：[/signals](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L30775-L30775)
  - v1 信号接收（统一 schema）：[/signals/v1](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L11815-L11815)
  - v1 信号落库与触发决策：[_emit_signal_v1](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L11438-L11438)
  - 决策与下单主入口：[_decision_entry_impl](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L33710-L33710) / [/decision/entry](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L34952-L34952)
  - 成交/出场回传（结算触发）：[/tracker/update](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L36269-L36269)
- 执行交易所路由（现状口径）
  - Strategy：由 `execution_venue` 决定（当前默认 aster）
  - Quant（pairs/btceth、pairs/btcalt）：固定走 Aster（后端禁止 `venue=hyperliquid`）
  - CarryTrade：由 `carry_trade_venue` 决定（当前默认 hyperliquid）
  - Freqtrade Webhook（`POST /webhook/freqtrade`）：按 `strategy_id → system_id` 路由（Carry 强制 HL，Quant 强制 Aster，Strategy 走 `execution_venue` 或 payload.venue）
- 面板数据接口：[/signals/recent](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L59900-L59900) / [/orders/recent](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L59596-L59796)（支持按 `strategy_id/group_id/ab_owner` 过滤）/ [/quant/pairs/btceth/orders/recent](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L70194-L70194) / [/carry/status](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L49625-L49625) / [/carry/candidates](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L49780-L49780)
- 风控/实盘关键入口（常见“为什么没下单/被拒绝”都从这里切）
  - 总开关矩阵与错误码：见 3.2
  - 风控 Gate：[_risk_check](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L28988-L29097)
  - 实盘开关/鉴权（排查 403 / config_forbidden）：[_config_auth_ok](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L32306-L32335) / [_governance_write_auth_ok](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L32534-L32548)
  - 配置读写与热加载：[/config/get](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L44049-L44050) / [/config/set](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L50409-L50410) / [/config/reload_env](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L50385-L50386)
  - Carry 解对冲 Gate（仅影响 UNHEDGE）：[_carry_unhedge_gate](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L44859-L45100)
  - 交易对→币种归一（canary 白名单、Universe 拦截等依赖）：[_hl_coin_from_pair](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L6640-L6654)
  - 下单前 Notional/Trading 状态预检（用于排障与“SETTLING”类报错）：[_aster_preflight_notional](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L4435-L4435) / [_aster_mid](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L4176-L4176)
  - Aster 执行入口（Open/Close）：[/execution/aster/market_open](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L16588-L16588) / [/execution/aster/market_close](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L16946-L16946)
  - 宏观 Gate 刷新（解决 macro_gate_stale）：[/macro/gate/eval](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L80103-L80104)
- 配置与状态落地点（排障先看这几类文件）
  - 运行时配置（Dashboard Configuration 写入）：[user_data/ml_config.json](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/ml_config.json)
  - 名义资金/开仓 size 配置：[`entry_*_notional_usdc` / `aster_*_notional_usdc` / `hl_*_notional_usdc`](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/ml_config.json#L695-L711)
  - Freqtrade 配置（策略/回测/实盘不同 profile）：[user_data/](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data)
  - Arena/Tracker 状态（用于解释投票与结算）：[user_data/arena_state.json](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/arena_state.json) / [user_data/tracker_state.json](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/user_data/tracker_state.json)
  - 仓位状态（三层隔离：Strategy/Quant/Carry）：
    - 数据结构：`TRACKER_STATE.open_positions` / `TRACKER_STATE.quant_open_positions` / `TRACKER_STATE.carry_open_positions`
    - 统一访问入口：[_tracker_open_positions_get](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L1765-L1790)
    - 清理入口：[/tracker/open_positions/clear](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L58681-L58681)
- 维护自检（改动后最少跑一遍）
  - 语法自检：`python -m py_compile ml_trade_service.py`
  - 后端单测（按需挑选关键用例）：`python -m pytest -q <test_file>::<TestClass>::<test_case>`
  - 前端 lint：`cd frontend && npm run lint`
- 前端页面入口（查 UI 展示/字段解析/排序抽样）
  - 路由入口：[App.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/App.tsx)
  - Recent Signals 表格：[SignalsTable.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/SignalsTable.tsx)
  - Recent Orders 表格：[OrdersTable.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/OrdersTable.tsx)
  - Quant 页面（/quant）：[QuantStrategiesPage.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/QuantStrategiesPage.tsx)
  - Quant Recent Orders 数据源：[fetchQuantPairBtcEthOrdersRecent](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/lib/api.ts#L3665-L3666)（页面 useQuery：[QuantStrategiesPage.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/QuantStrategiesPage.tsx#L653-L659)）
  - Carry 页面（/carry）：[CarryTradePage.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/CarryTradePage.tsx)
  - Carry Recent Orders 数据源：[fetchCarryOrdersRecent](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/lib/api.ts#L748-L748)（页面 useQuery：[CarryTradePage.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/CarryTradePage.tsx#L189-L190)）
  - 配置面板：[ConfigCard.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/ConfigCard.tsx)
  - Arena 面板：[ArenaPage.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/ArenaPage.tsx)

### 0.4 Continue 工程级集成与新人一页式手册

集成目标：

- 在不改变交易运行时逻辑的前提下，统一 IDE 助手行为边界与安全口径。
- 通过工程级忽略规则减少敏感数据进入 AI 上下文的概率。

当前落地（本工程）：

- 已通过 `.gitignore` 增加 Continue 可继承的索引安全边界（`useGitIgnore` 场景）。
- 推荐 Level 2 目标态：补齐 `.continue/rules/` 与 `.continue/agents/` 两层资产（在磁盘/权限允许时落地）。

新人首次使用步骤：

1. 打开工程目录：`/Users/zhangjiangtao/ft_userdata/经典指标机器学习系统`
2. 打开 Continue 面板（`Cmd/Ctrl + L`），确认默认模型可用。
3. 执行 `Developer: Reload Window`，必要时执行 `Continue: Rebuild codebase index`。
4. 首次提问使用“只分析不改动”模式，确认上下文是否包含敏感路径。

日常操作清单：

1. 选上下文：优先 `@Diff` + `@File`，最后才用 `@Codebase`。
2. 先分析：先让模型给出风险点和最小改动计划。
3. 再改动：采用小步改动，避免跨模块大面积修改。
4. 再验证：至少执行语法检查或单测；涉及前端时执行 lint。
5. 再回执：记录“改动点 + 验证结果 + 风险与回滚口径”。

敏感任务红线：

- 不向云端模型提交：`.env*`、`user_data/datasets/`、`user_data/agent_outbox/`、交易账户配置、地址白名单。
- 涉及执行门禁与风控参数时，先用本地模型进行只读审计，再实施代码改动。

链路检查（每周最少一次）：

- `@Codebase` 检索样本中不出现敏感路径内容。
- 工程目录中无明文 `apiKey/token/private key`。
- 关键变更均有验证命令与结果记录。
FAQ 快速定位（高频问题入口）：
  - Canary/白名单/预检报错：见 技术文档规范.md 13.1
  - Recent Signals 时间线/去重/PC&Thr：见 技术文档规范.md 13.2
  - Dashboard /ml 页面数据不显示（/api/health 500 或接口超时）：见 技术文档规范.md 13.3（本文件 14.1.1 为兼容入口）
    - 若前端控制台出现 `http proxy error ... ECONNREFUSED 127.0.0.1:8093`：
      - 后端是否存活：`GET http://127.0.0.1:8093/health`
      - 后端端口是否一致：前端 Vite proxy 需指向正确后端（必要时用 `VITE_PROXY_TARGET=http://127.0.0.1:<PORT>` 启动前端）
      - 前端端口冲突：默认 3001，若被占用可换 3002/3003
  - Quant 页面 /quant 的 Recent Orders 不显示（接口返回 []）：
    - 入口定位：前端 [QuantStrategiesPage.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/QuantStrategiesPage.tsx) → 后端 [/quant/pairs/btceth/orders/recent](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L70194-L70200)
    - 常见原因
      - 订单只落盘在 `user_data/datasets/*_orders.jsonl`，但进程内存 `ORDERS` 为空（重启/冷启动/未回灌）导致 recent 接口返回空
      - 订单在归档侧缺失 `ab_owner/system_id`（例如早期/外部导入/冷启动写入不全），当读取侧按 `ab_owner=quant` 过滤时被误归一到 `strategy`，从而 Quant 侧看起来“无 recent orders”
    - 快速自检：
      - 先看通用 recent：`GET /orders/recent?limit=20`
      - 再看 owner 过滤：`GET /orders/recent?limit=200&include_shadow=1&sort=ingest&ab_owner=quant`（确认是否能看到 `quant_auto_btcalts/quant_pairs_*`）
      - 再看 Quant recent：`GET /quant/pairs/btceth/orders/recent?limit=20`
      - 确认落盘是否存在：`user_data/datasets/*_orders.jsonl`
    - 修复口径
      - recent 读取侧需要合并“内存 ORDERS + datasets 归档”，参考实现：[_orders_recent_candidates](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L59525-L59609)
      - 当 `ab_owner` 缺失时，读取侧 owner 推断必须至少基于 `system_id/strategy_id/tag` 做兼容归一（避免把 Quant/Cary 历史折叠到 strategy），并在 `GET /orders/recent` 的过滤与回填阶段保持一致
  - Quant BTC-ETH 调低 `entry_z` 仍然“信号不触发”（WFO 阈值未同步）：
    - 典型现象：`base_params.entry_z` 已更新，但 `params/selected_params.entry_z_long/entry_z_short` 仍偏大，导致 `thresholds.entry_z_eff` 仍很高（看起来“怎么调都不触发”）。
    - 快速自检：
      - `GET /quant/pairs/btceth/status?timeframe=1h&limit=800`，对比 `base_params` 与 `wfo.selected_params` / `params`，并关注 `thresholds.entry_z_eff`。
      - 若需要立即刷新 WFO：`GET /quant/pairs/btceth/status?timeframe=1h&limit=800&wfo_run=1`（强制重算，绕过缓存）。
    - 根因：启用 WFO 且 `apply=true` 时，实盘/建议动作以 WFO 的 `selected_params` 为准；当 WFO 网格仅包含 `entry_z` 时，历史实现会保留旧的 `entry_z_long/entry_z_short`，导致实际判定阈值仍按 `entry_z_long/entry_z_short` 生效。
    - 修复口径：
      - 代码侧已修复：当 WFO 组合里出现 `entry_z` 且未显式优化 `entry_z_long/entry_z_short` 时，自动同步 `entry_z_long=entry_z_short=entry_z`，避免阈值“看起来不跟随”。
      - 默认 WFO 网格已下探：`entry_z` 从 `[1.5, 2.0, 2.5]` 调整为 `[1.2, 1.4, 1.6, 1.8, 2.0]`（仍保持 WFO 自适应）。
      - 规避/回滚：可在配置中显式设置 `quant_pairs_btceth_wfo_grid`（加入 `entry_z_long/entry_z_short`），或临时关闭 `quant_pairs_btceth_wfo_apply` 让 `base_params` 直接生效。
  - Carry 页面 /carry 的 Recent Orders 不显示（或 owner 显示为 strategy）：
    - 入口定位：前端 [CarryTradePage.tsx](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/CarryTradePage.tsx)（Orders Tab）→ 前端数据源 [fetchCarryOrdersRecent](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/lib/api.ts#L748-L748) → 后端 `GET /orders/recent?strategy_id=CarryTrade&ab_owner=carry`
    - 常见原因：历史 Carry 订单的 `ab_owner` 被错误归一为 `strategy`（早期 [_ab_norm_owner](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L9055-L9055) 只支持 strategy/quant），导致按 owner 过滤或 UI 分组时“看不到/看错归属”。
    - 快速自检：
      - 只按策略查：`GET /orders/recent?limit=200&include_shadow=1&sort=ingest&strategy_id=CarryTrade`
      - 按 owner 查：`GET /orders/recent?limit=200&include_shadow=1&sort=ingest&strategy_id=CarryTrade&ab_owner=carry`
      - 核对 tag：Carry 典型 tag 前缀如 `carry_open|...` / `carry_*`
    - 修复口径：
      - 下单写入侧：Carry 下单内部调用必须显式传 `ab_owner="carry"`（否则会默认落入 strategy；见 [ml_trade_service.py:L49551-L49553](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L49551-L49553)）。
      - 过滤读取侧：[/orders/recent](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L59596-L59796) 增加 `ab_owner` 参数，并对历史 Carry 订单做兼容推断（基于 `strategy_id/tag/system_id`）。
      - 归一化：[_ab_norm_owner](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L9055-L9055) 必须支持 `carry`（否则 owner 相关统计/过滤会被折叠到 strategy）。
  - CarryTrade 下单跑到 Aster（隔离失效）：
    - 现象：`POST /webhook/freqtrade` 返回的 `order.exchange/exec.venue` 为 `aster`，或 Aster 成交里出现 `strategy_id=CarryTrade`。
    - 快速自检：
      - `GET /config/get` 核对 `execution_venue` 与 `carry_trade_venue`。
      - `POST /webhook/freqtrade`（execute=false）核对返回体 `order.exchange` 是否为 `hyperliquid`。
    - 修复口径：Webhook 路由必须对 CarryTrade 使用 `carry_trade_venue`，并在 Aster 执行入口拒绝 `system_id=carry/ab_owner=carry`。
  - /exit 页面 Quant（期望 exchange=aster）出现“模拟/dry-run”（或真实单存在但页面只显示模拟）：
    - 现象：
      - Quant Recent Orders 表格看到 `mode=dry-run` 或 `exec.execute=false`。
      - /orders/recent 已有 `mode=real` 的 Quant 订单，但 /exit 看起来“只有模拟”。
    - 常见原因：
      - Freqtrade Webhook 未显式传入 `execute=true`，后端会默认 `execute=false`，因此落单口径为 `dry-run`（路由到 Aster 与是否实盘是两件事）。入口见 [/webhook/freqtrade](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L12902-L13047)
      - `execute=true` 但被执行门禁拦截（例如缺 `confirm_execute=true`，或 token 不满足），请求会被拒绝而不是生成实盘单。
      - UI/接口口径：`GET /quant/pairs/btceth/orders/recent` 默认 `live_only=1` 仅展示实盘（`exec.execute=true` / `mode=real`）。如需排查模拟链路，用 `live_only=0` 查看模拟单。
    - 快速自检：
      - 先看订单事实：`GET /orders/recent?limit=200&include_shadow=1&sort=ingest&ab_owner=quant`，核对 `mode` 与 `exec.execute`。
      - 若来源是 Freqtrade：回看发到 `POST /webhook/freqtrade` 的 payload 是否包含 `execute=true`（以及 `confirm_execute=true`）。
      - 若来源是 Quant Auto：`POST /quant/auto/btceth/tick` / `POST /quant/auto/btcalts/tick`，看返回体 `execute/enabled/live_blocked_reason/mode`。
    - 修复口径：
      - 需要实盘：Freqtrade webhook 模板必须同时满足 `execute=true` + `confirm_execute=true`；并确保全局开关（例如 `dry_run=false`、Quant/Aster 允许实盘）未关闭。
      - 仅做仿真：显式 `execute=false`，并用 `GET /quant/pairs/btceth/orders/recent?live_only=0` 核对模拟链路即可。

  - Quant（Aster）出场/减仓报 `size_underflow`（数量被 round 到 0）：
    - 典型现象：
      - Recent Orders 或 datasets 里看到 `status=failed` 且 `exec.error=size_underflow`。
      - 常见发生在“减仓 reduce”场景（例如 `reason=exit_exit_feeder:l1_take_profit_reduce:reduce`，reduce_qty 类似 0.73）。
    - 根因：Aster 下单数量会按合约 `stepSize` 做向下取整；当 `raw_qty < stepSize` 时会被 round 为 0，触发 `size_underflow`。
      - 代码入口：[_aster_round_qty](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L6305-L6334)
    - 快速自检：
      - 看订单事实：`GET /orders/recent?limit=200&include_shadow=1&sort=ingest&ab_owner=quant`，定位该笔订单的 `exec.error` 与 `tag/reason`。
      - 看交易对最小步进：确认 `stepSize` 是否过大（例如 DOGE-PERP 的 `stepSize=1`，则 `0.73` 无法下单）。
    - 修复口径（按优先级）：
      - 若仓位已很小：从“reduce”改为直接 `close`（避免落到小于 step 的减仓量）。
      - 若需要保留部分仓位：提高 notional 或调整 `reduce_frac`，确保 `reduce_qty >= stepSize`。
      - 若是系统性频发：检查 Quant 的目标下单/减仓尺寸是否可能落入 `< stepSize` 区间（优先从 sizing/最小名义资金修复，而不是靠重试）。

  - /exit 页面 Quant 被 Strategy 出场判定/执行（跨系统调用）：
    - 现象：
      - Timeline 里出现 `reason=exit_*`（Exit Feeder / L0/L1/L2）但对应仓位 `system_id=quant`。
      - 或 Recent Orders 里出现 `tag=exit_*` 且 `ab_owner/system_id` 指向 quant。
    - 原则口径：/exit 可展示 Quant 用于监控，但 Strategy 出场系统（L0/L1/L2 + Exit Feeder）只允许处理 `system_id=strategy`。
    - 快速自检：
      - `GET /tracker/stats?view=exit`，核对 `open_positions[pair].system_id/strategy_id/exit_owner`。
      - `GET /orders/recent?limit=200&include_shadow=1&sort=ingest&tag=exit`，核对相关订单的 `ab_owner/system_id`。
    - 修复口径：
      - 后端已硬隔离：Exit pipeline 会跳过 `system_id=quant`：[_exit_pipeline_tick](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L43990-L44110)
      - 后端已硬隔离：`GET /tracker/stats?view=exit` 只会对 Strategy 仓位刷新 `exit_l1_last_decision`：[/tracker/stats(view=exit)](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L68727-L69127)
      - 若仍出现混淆：优先修正“仓位快照写入侧”的 `system_id` 标注（确保 Quant 仓位永远带 `system_id=quant`）。
  - /exit 页面 Recent Orders（BTC-ETH）只看到一条腿（例如只有 ETH failed，看不到 BTC 订单）：
    - 现象：
      - `tag=quant_pairs_btceth|pair_<ts>_<k>` 下，面板里只看到 `ETH-PERP` 或只看到 `BTC-PERP`。
      - 交易所侧可能只看到撤单（CANCELED），看不到成交。
    - 常见原因：
      - 订单事实里两条腿都存在，但 UI 只展示“最近 N 条”，另一条腿 `ts` 稍早，被其它 Quant 订单挤出当前窗口。
      - 配对腿的一条发生 `maker_timeout`：post-only maker 下单后等待成交超时并撤单（因此不会产生成交）。
      - 调用 `/quant/pairs/btceth/orders/recent` 时 `limit` 太小，只截取到一条腿。
    - 快速自检：
      - 拉取订单事实（推荐）：`GET /orders/recent?limit=200&include_shadow=1&sort=ingest&ab_owner=quant`，再按 `tag` 精确过滤，看同一 `tag` 是否同时存在 BTC/ETH 两条腿。
      - 查 BTC-ETH 专用 recent：`GET /quant/pairs/btceth/orders/recent?limit=50&live_only=0`（必要时关闭 live_only 以包含模拟）。
      - 若订单显示 `status=failed` 但存在 `exchange_oid`，优先看 `exec.error`：
        - `maker_timeout`：等待成交超时 → 撤单 → 交易所侧通常只能在撤单/历史委托里看到记录，不会有成交。
    - 修复口径：
      - 面板展示按 `tag` 聚合/对齐两条腿（保证一个 `tag` 下 BTC/ETH 同屏）。
      - 排障优先看 `OID(exchange_oid)` 与 `Error(exec.error)`，不要仅靠交易所“成交列表”判断是否下单。
  - Quant（pairs/btcalt）双腿平仓异常：返回 502 / BTC 腿未被自动平仓：
    - 现象：
      - 调用 `POST /execution/pairs/btcalt/market_close` 返回 502，但返回体里两条腿的 close order 实际都已 `status=filled`。
      - 或 ALT 腿已平、BTC 腿仍有持仓（面板或交易所侧 BTC-PERP 仍 open）。
    - 常见原因：
      - BTC 腿平仓请求被 Aster 执行层按“系统归属”忽略：当前持仓 `system_id=strategy`，但平仓请求预期 `system_id=quant`，触发 `ignored_wrong_system`，从而 BTC 腿不执行。
      - 平仓后持仓状态同步滞后：两腿订单都成交，但 tracker 仍未刷新到最新持仓，导致“双腿准原子验证”把已平误判为未平并返回 502。
      - 被 `exit_inflight` 冷却拦截：短时间内连续 close/reduce 导致 429（常见于双腿 close+rollback 组合或快速重试）。
    - 快速自检（按顺序）：
      - 先看持仓事实：`GET /exit/open_positions`，确认 `BTC-PERP/ZEC-PERP`（或对应 ALT）是否仍在 positions。
      - 再看订单事实：`GET /orders/recent?limit=200&include_shadow=1&sort=ingest&ab_owner=quant`，按 `tag=quant_pairs_btcalt|...` 过滤，核对 BTC/ALT 两条腿是否都存在，且 `order.status=filled`。
      - 若 BTC 腿“没单”或 `status=ignored_wrong_system`：核对该 BTC 腿持仓快照的 `system_id`，以及 Aster 平仓是否按 quant owner 执行。
    - 修复口径：
      - 平仓执行必须把 `system_id` 与 owner 对齐：对 `quant_pairs_* / quant_auto_* / rollback|*` 的平仓，Aster 平仓内部应按 `system_id=quant` 处理，并用其作为 `owner_close` 执行下单：
        - Aster 平仓入口：[aster_market_close_internal](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L15609-L15683)
      - 双腿 close 成功时，至少做一次 tracker 同步刷新后再判定是否已平，避免“已平但 502”的误报：
        - 双腿准原子 close：[_pairs_two_legs_quasi_atomic_close](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L84169-L84430)
      - 若出现 429（exit_inflight）：对 Quant 双腿 close/rollback 的 tag（`quant_pairs_*/quant_auto_*/rollback|*`）允许绕开 inflight 冷却拦截，避免双腿链路被卡住：
        - Aster 平仓 inflight：[aster_market_close_internal](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L15623-L15676)
      - 兜底清仓（排障用）：对 BTC/ALT 分别调用强制平仓并强制同步：
        - `POST /execution/aster/market_close {coin:"BTC", force:true, system_id:"quant"}`
        - `POST /execution/aster/market_close {coin:"<ALT>", force:true, system_id:"quant"}`
        - `GET /tracker/stats?view=ui&sync=1&force=1`
  - /exit 页面 `Exit Decisions Timeline` 显示 close/reduce 但没有真实平仓单：
    - 现象
      - Timeline 看到 `action=close|reduce`、`reason` 包含 exit/market_close，但 Recent Orders 或交易所侧没有对应的平仓订单。
    - 口径
      - Timeline 数据源是 `GET /tracker/gate_history`，用于回溯“平仓决策/门禁判定/执行尝试”，不是订单事实列表。
      - 判断是否真实执行以字段为准：
        - `executed=true`：真实执行（已进入交易所执行链路并落地为执行事件/订单）。
        - `shadow=true`：影子/仿真（SIM），不会产生真实订单。
        - `ok=false` 或 `error=ignored_*`：未执行或被忽略（例如无持仓、非 owner、exit 开关关闭）。
        - `ok!=false` 且无 `executed/shadow`：仅记录“决策/判定”（DEC），不代表已下单。
    - 快速自检（按顺序）
      - 先看 Timeline 事件本身：是否有 `executed/shadow/ok/error/order_id/exchange_oid`（前端已在 Timeline 展示这些字段）。
      - 再核对订单事实：`GET /orders/recent?limit=200&include_shadow=1&sort=ingest&ab_owner=<strategy|quant|carry>`。
      - 若 `error=ignored_strategy_exit_disabled`：检查 `/config/get` → `strategy_exit_enabled`（false 时会直接忽略 strategy owner 的平仓）。
      - 若 Timeline/仓位“看起来不一致”：核对 `system_id/exit_owner` 是否正确，避免用 strategy 维度去解释 quant/carry 的仓位事件。
    - 代码入口
      - 前端 Timeline：[/exit](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/frontend/src/components/ExitSystemPage.tsx#L1468-L1536)
      - 后端平仓执行与忽略口径（`ignored_*` 视为未执行并写入 `error`）：[_exit_execute_action](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py#L42819-L42930)
  - 三层仓位隔离（already_open/页面不一致/清理无效）：见本文件 14.4.1
  - 实盘开关/鉴权与 confirm_live：见本文件 14.17
  - Aster 预检报 macro_gate_stale：见本文件 14.18
  - 最小实盘试单（reduce-only 减仓）：见本文件 14.19
