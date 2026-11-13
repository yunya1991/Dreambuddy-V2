# 十大交易机会 · 子系统交叉验证榜单与决策卡升级 SPEC

- 版本：v1.0（评审稿）
- 日期：2026-11-13
- 关联文档：`1-ARCHITECTURE/TOP10_RANKING_RECOMMENDATION_SPEC.md`（产品定位与决策卡七模块，本 SPEC 是其工程落地续篇）
- 现状代码：`3.1-FRONTEND/scripts/trading_ranking.py`、`1-ARCHITECTURE/dreamos/cli/ranking_asset_pool.py`

---

## 1. 背景与问题

线上榜单（commit `f948d6694d`）已具备多资产候选、6+2+2 品类配额、OKX 可交易 + 成交额 + 市值过滤、真实最新价与空值安全决策卡。但评分仍是"静态研究分排序"：

| 候选来源 | 分数语义 | 局限 |
|---|---|---|
| `coin_pool.json`（hermes-weekly） | 周度研究推荐度，orchestrator 透传 | 无入场/止损语义；仅最新快照，历史不可复现 |
| 影子信号补位 | `_SHADOW_SIGNAL_BASE` 硬编码 0.43~0.55 | 尾部排名无信号内容 |
| `ranking_asset_pool.json` | 动量 + MA 技术分 0.65 + 40 周期 0.35 | 无风险调整，无交易计划 |

决策卡缺入场区间、止损止盈、风险分级、历史类比；且当前评分**无法做真实历史回测**，无法回答"榜单是否有效"。

## 2. 已确认决策（用户拍板，不再变更）

1. **资产范围**：B 组（子系统推理）限定「加密 + OKX 合成品种」（XAU/XAG/XPT/NG/USO/US500/AMD 等经 51 OKX CLI 可取 K 线的标的）；非 OKX 美股个股暂沿用 A 组动量逻辑。
2. **回测口径**：固定持有 N 日（N=1/3/5/10）与按 SL/TP 出场两者都测，**主指标采用 SL/TP 口径**。
3. **P0 先行**：决策卡维度补齐（BCRM2 SL/TP/风险分级 + CBR 历史类比）先于回测单独落地。
4. **子系统分榜**：23 自进化、12 三屏趋势、17 V4 波浪、29 事件驱动、11 BCRM2.0、11 BDSM 各自输出最优推荐 Top1~2，**全部打子系统标签**；回测按标签分组评估各子系统选币能力。
5. 综合榜与各子系统分榜并行，回测达标前不替换现有默认榜单。

## 3. 总体架构

```
候选池（沿用现有：流动性/市值门槛 + 品类配额）
        │
        ▼  42 信号总线（已有，复用，不另建适配层）
┌──────────────────────────────────────────────┐
│ 42 SignalBus：schema 校验 / F1 新鲜度 /       │
│ F2 置信度降 neutral / F3 多源方向冲突标记 /   │
│ 按 (source,symbol) 去重 + 持久化 + metrics    │
│                                              │
│ 已接入：11-bcrm、11-bcrm-tactical(28币)、     │
│        bdsm(10币)、29-event、washout、40、23  │
│ 待新增 publisher：12 三屏、17 V4 波浪（仅2个）│
└──────────────────────────────────────────────┘
        │  runtime/bus_state.json snapshot
        ▼  榜单侧读取融合器（唯一新建组件）
   symbol 归一化（BTC/USDT→BTC；MACRO/板块信号仅用于推演）
   → 映射 SubsystemPick → 共识融合（复用 F3 conflict_flags）
        │
        ▼
┌──────────────────────┐   ┌─────────────────────────┐
│ 综合榜：共识分融合    │   │ 子系统分榜：各系统 Top1~2 │
└──────────────────────┘   └─────────────────────────┘
        │  decision_card 维度由 BCRM2/CBR 填充（P0 不变）
        ▼
/api/trading-ranking/today（只读预计算文件，FAIL-OPEN 降级现有逻辑）

离线：历史重放器复用 42 signal schema 重算子系统信号 → 分组指标报告
      + bus_history.jsonl 持续落库做前向跟踪（双轨验证）
```

**关键工程约束**：
1. 子系统推理重，禁止在 API 请求内实时调用；榜单只读 42 持久化状态与每日预计算文件，缺失/过期回退现有榜单。
2. **不在榜单侧分别对接子系统**：信号一律经 42 总线进入，新子系统按 `registry.yaml` 声明式接入，避免重复造轮子。
3. 线上与回测共用 42 signal schema，保证口径一致。

## 4. 统一契约：复用 42 signal schema

线上信号直接使用 42 总线字段，不再自定义第二套契约：

```json
{
  "signal_id": "sig_11-bcrm-tactical_HYPE_...",
  "source": "11-bcrm-tactical",
  "symbol": "HYPE",
  "direction": "long | short | neutral",
  "confidence": 0.0,
  "ts": "ISO8601",
  "expires_at": "ISO8601",
  "risk_exposure_hint": 0.0,
  "conflict_flags": [],
  "payload": {}
}
```

榜单侧在此基础上派生 `SubsystemPick` 展示字段：
- `subsystem`：由 `source` 映射（`11-bcrm/11-bcrm-tactical→bcrm2`、`bdsm/11-bdsm→bdsm`、`29-event→event`、`washout→evolution`、`12-three-screen→three_screen`、`17-v4-wave→v4_wave`）。
- `symbol` 归一化：`BTC/USDT→BTC`；`MACRO`、`precious_metal`、`us_stock` 等板块/宏观信号不进入选币，仅用于逻辑推演。
- `direction=neutral` 不进入推荐，仅留档供回测对照。
- `score`：综合榜由融合层计算；分榜直接用 `confidence` 排序，不假设跨系统原始分同量纲。
- `stop_loss/take_profit/rr/risk_level`：总线暂无标准字段，P0 由 BCRM2 推理或 ATR 兜底补齐；同步推动子系统在 `payload` 扩展 `sl/tp`，到位后优先采用。

## 5. 子系统接入清单（经 42 总线）

| 子系统 | 标签 | 42 接入现状（已核实） | 剩余工作量 |
|---|---|---|---|
| BCRM2.0 | `bcrm2` | 已接入：`adapters/bcrm_state_adapter.py`（3 币）+ `bcrm_tactical_state_adapter.py`（28 币，含 direction/confidence） | 无；SL/TP 由 P0 决策卡链路补齐 |
| BDSM | `bdsm` | 已接入：`adapters/bdsm_state_adapter.py`（10 币） | 无 |
| 事件驱动 | `event` | 已接入：`adapters/event_driven_adapter.py`（当前 snapshot 无活跃信号，可能过期或数据源缺席） | 小：确认发布频率与数据源 |
| 自进化（washout 系） | `evolution` | 已接入：`adapters/washout_state_adapter.py` | 无 |
| 三屏趋势 | `three_screen` | **未接入**；源入口 `12-三屏趋势系统/engine.py`：`calc_take_profit_stop_loss()`、`five_algo_decision()` | 新增 1 个 publisher（多标的扫描封装） |
| V4 波浪 | `v4_wave` | **未接入**；源入口 `17-v4-wave-strategy/v4_wave_engine.py`：`compute_v4_wave_signal()` | 新增 1 个 publisher（多标的扫描封装） |

> 新增 publisher 只读子系统公开入口并发布到总线，不改子系统内部逻辑；子系统不可用时该标签当日缺席，不阻塞其他系统。榜单侧唯一新建组件是"总线读取 + symbol 归一化 + 共识融合"读取器。

## 6. 榜单组成与融合

### 6.1 综合榜（B 组）
```
方向共识 = 同标的非 neutral 子系统中方向一致数 / 有效子系统数
score = 0.5 × 方向共识 + 0.3 × 置信度加权均值 + 0.2 × RR 归一化
```
- 方向冲突（多空并存且共识 < 0.6）的标的降出综合榜。
- `risk_level=expert` 降权 20%。
- 保留 6+2+2 品类配额与现有流动性/市值门槛；非 OKX 美股个股仍以 A 组分数补足配额，`rationale` 标注 `source=momentum_proxy`。

### 6.2 子系统分榜
每子系统按自身 `score` 取 Top2（不足则 Top1 或空缺），原样携带 `subsystem` 标签，前端新增"按子系统查看"筛选，用于观察各系统选币风格。

### 6.3 A 组保留
现有榜单逻辑整体保留为 A 组，双榜并行，供回测对照与线上对比。

## 7. 决策卡维度映射（P0 范围）

| 模块 | 数据源 | 降级 |
|---|---|---|
| 入场策略 | 最新价 + ATR 入场区间（±0.5 ATR），`inferred=true` 标注 | 现价单点 + "待定"区间 |
| 止损止盈 | BCRM2 `stop_loss_px/take_profit_px`（P0 起） | ATR 兜底；再缺则"待定" |
| 风险分级 | BCRM2 `risk_level` | `intermediate` + 标注 |
| 历史类比 | CBR `CBRQuery` Top1 案例：市态/入场/离场/盈亏/回撤 | 隐藏模块，不报错 |
| 事件日历 | 暂无可靠数据源，维持"待定" | — |
| 逻辑推演 | 共识方向 + 各子系统 rationale 摘要 | 现有规则文案 |

前端已完成空值安全（commit `f948d6694d`），P0 不需要再改渲染健壮性，仅新增 `inferred` 标注展示。

## 8. 回测 SPEC（P2）

### 8.1 方法
- **历史重放**：每个交易日 t，用**截至 t** 的数据运行各子系统推理，产出与 42 总线完全同 schema 的信号，再生成 A 榜、B 综合榜、各子系统分榜（Top2）。重放器离线运行，不写入实盘总线。
- **前向跟踪（双轨）**：`runtime/bus_history.jsonl` 目前仅 21 行，历史不足以回测；自 P1 起每日追加落库真实总线信号与后续收益，逐步形成可验证的前向样本。
- 成交价：t+1 开盘价等权买入；加密 + OKX 合成品种 1D K 线（OKX `history-candles`）。
- 两种出场口径都测：
  - 固定持有 N=1/3/5/10 日；
  - **主口径：SL/TP 出场**（同日触及 SL 与 TP 时按 SL 优先的保守口径），最长持有 10 日强制平仓。

### 8.2 A 组前视偏差处理
`coin_pool.json` 无历史快照，A 组采用**可复现代理**：用同一套动量 + MA 公式在历史重算评分，报告显著标注「A 组为代理实现，非线上原始分数」。

### 8.3 分组与指标
- 分组：`overall_A` / `overall_B` / `subsystem=bcrm2|bdsm|event|three_screen|v4_wave|evolution`，再按品类分层。
- 指标：胜率、平均单笔收益、盈亏比、夏普、最大回撤、SL/TP 命中率（SL 先触/TP 先触/超时比例）、换手率、平均持有天数。
- 成本：手续费 + 滑点（加密 0.05% 起，合成品种按点差），做空同样计费。
- 统计：walk-forward 滚动（≥180 天样本），配对日收益差检验 + bootstrap 95% 置信区间，多窗口稳健性。

### 8.4 通过门槛
B 综合榜在主口径下样本外夏普与平均日收益显著优于 A 组、且最大回撤不劣化，才切换为默认榜单；子系统分榜只做能力画像，不设单独切换门槛，但连续两窗口显著为负的标签降权或暂停。

## 9. 分期与验收

| 阶段 | 交付物 | 验收 |
|---|---|---|
| P0 | `ranking_decision_card.py` 预计算（BCRM2 SL/TP/风险 + CBR 类比 + ATR 入场区间）+ API 合并 | 线上卡片五模块有值且标 `inferred`；无卡片崩溃；pytest 通过 |
| P1 | 42 新增 2 个 publisher（三屏/V4）+ 榜单侧总线读取融合器 + 综合榜/分榜 API 与前端筛选 + bus_history 每日落库 | 每系统 Top1~2 带标签可见；单系统故障不影响整榜 |
| P2 | `ranking_backtest.py` + 对照报告（A/B + 标签分组） | 报告含两种口径、成本、置信区间；无前视（数据截止断言） |
| P3 | 达标后默认切换 + 监控 | 线上双榜指标看板 |

## 10. 风险与开放问题

1. 子系统对 OKX 合成品种（美股个股/大宗）推理有效性未验证，P2 需单独分层看表现。
2. CBR 案例库目前以加密实盘案例为主，对合成品种类比可能稀疏 → 允许模块空缺。
3. 各子系统打分频率与 K 线周期不一致，统一以 1D 为基准，盘中不刷新。
4. 事件驱动依赖事件数据源可用性，缺数据时按契约返回 neutral 低置信。
5. 开放问题：综合榜是否保留 6+2+2 硬配额（可能挤掉高共识标的）——评审时确认。

## 11. 测试要求

- 总线读取测试：42 schema 解析、过期信号剔除、neutral 过滤、symbol 归一化（`BTC/USDT→BTC`，MACRO/板块信号不进选币）、source→subsystem 标签映射。
- 融合测试：共识计算、复用 F3 `conflict_flags` 的冲突剔除、专家降权、配额兜底。
- 回测测试：数据截止无前视、SL/TP 同日冲突按 SL、成本计入、分组标签齐全。
- 端到端：预计算文件缺失/过期时 API 降级现有榜单且 HTTP 200。
