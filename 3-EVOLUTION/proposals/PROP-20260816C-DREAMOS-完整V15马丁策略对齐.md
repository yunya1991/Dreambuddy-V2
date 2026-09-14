# PROP-20260816C — DreamOS 对齐完整 V15 马丁策略（适配器接入，Paper 先行）

- **提案日期**: 2026-08-16
- **提案人**: 云涯 Hermes（D 链调研）
- **状态**: ⏳ 待用户明确批准
- **前置**: PROP-20260816（双腿对冲，已实施）、PROP-20260816B（对冲择股引擎驱动排名，已批准实施中）
- **飞书审批实例**: `93C88F1F-C481-4503-B45F-7DED62BCECD7`（模板 096DC318 交易进化审批；注意 AUTO_PASS 仅存档，以用户对话中明确批准为准）

---

## 1. 背景与问题（D1/D2 调研结论）

### 1.1 现状核查（2026-08-16 实证）

系统中存在**两个 V15 实现**，且权威完整版从未在本机运行：

| 维度 | DreamOS 简化版（在用） | 14-V15 权威完整版（未运行） |
|---|---|---|
| 文件 | `1-ARCHITECTURE/dreamos/capabilities/trading/v15_executor.py`（506 行） | `14-V15经典马丁策略/core/v15_trader.py`（3142 行） |
| 入场决策 | 无（由易经信号直接触发） | **16 层入场决策 + 16 项技术指标**（斐波那契回调区 + 布林带均值回归 + RSI/MACD/ADX 多指标共振，`v15_signal.py`） |
| 方向控制 | 仅 long_only 门禁 | **DirectionGate**：BTC 日线 MA128 + BTC风向标三状态模型（LONG_PREFERRED / SHORT_ALLOWED / LONG_ONLY_FORCE，3 日确认，Phase2 力学化力场） |
| 加仓结构 | MAX_ADDONS=3 等额 | **4 档金字塔加仓 = 总 5 单**（底仓 22% + 5/10/20/35%，黑天鹅档） |
| AI 闸门 | 无 | **Phase D gate**（G-D1 跳过开仓 / G-D2 动态缩减加仓档 / G-D3 时机评分，当前影子模式；模型 8/16 已训练） |
| 其他 | 仅超时离场 | 反弹潜力监控、TimingGate、移动止盈、冷却期、月度资金重建、L4 TradeEvent 注册 |

### 1.2 为什么完整版从未运行（根因）

1. **数据依赖 OKX**：`market_data.py` 仅支持 OKX API / OKX CLI 双路。本机（腾讯云大陆）实测 **okx.com 直连与硬编码 IP（47.52.118.149）均 100% 不可达**。
2. **执行依赖 OKX**：`okx_client.py` OKXSimulatedClient，且 `.env.common` 配置为 `OKX_SIMULATED=false / OKX_DRY_RUN=false`（实盘模式）——即使网络通也是向 OKX 下单，与本机 Hyperliquid 实盘账户体系不符。
3. `install_launchd.py` 为 macOS 遗留调度，Linux crontab 无 V15 条目；`data/v15_state.json` 为 0 字节。

### 1.3 可行性确认

- ✅ Hyperliquid `candleSnapshot` K 线 API 可用（`aster_spot.get_candles` 已在用，仅需补 1d 周期支持）
- ✅ v15_trader 实际调用的 client 接口仅 **9 个方法**（place_order×9、cancel_algo_orders×5、place_stop_loss_take_profit×2、cancel_order×2、get_pending_orders、get_order、get_all_positions）+ get_kline/get_ticker —— 适配器工作量可控
- ✅ 配置已就绪：TOTAL_BUDGET=260、LEVERAGE=5.0、MAX_ADDONS_PER_POSITION=4、BASE_TP_PCT=0.04（V9 红线）、Phase D 影子模式开启
- ✅ 币种池 8 币中 7 个有 HL perp（OKB 无，需剔除）

### 1.4 ⚠️ 安全发现（随本提案处理）

`14-V15经典马丁策略/config/.env.common` 含**明文 OKX API 凭据且被 git 追踪**（git status 显示已修改）。值已按 `[REDACTED]` 处理不落任何报告。本提案包含凭据隔离步骤，并**强烈建议批准后立即在 OKX 侧轮换该 API key**（已进 git 历史）。

---

## 2. 方案（D3 设计）

**核心原则：适配器模式，权威 V15 引擎零分叉（SSoT），Paper 先行。**

不重写、不搬运 3142 行引擎进 DreamOS；只在数据层与执行层各加一个适配器，让权威引擎在本机跑起来。

### 模块 1 — HL 数据适配器（新文件 `14-V15/lib/hl_data_adapter.py`）

- `fetch_candles(inst_id, bar, limit)`：OKX inst_id（`BTC-USDT`）→ HL coin（`BTC`）映射，bar（`1H/4H/1D/1W`）→ HL interval（`1h/4h/1d/1w`），底层走 `aster_spot.get_candles`
- `get_ticker(inst_id)`：HL 现价（复用 aster_spot 价格通道）
- 注入点：`market_data._get_okx_client()` / `fetch_candles()` 增加环境开关 `V15_DATA_SOURCE=hyperliquid`（默认值保持 OKX，可移植性不变）
- 配套：`aster_spot.get_candles` intervals 字典补 `1d`（3d/1w 顺带）
- 数据深度护栏：日线不足（如 <128 根）时 MA 计算返回 None → DirectionGate/信号层现有 None 处理路径自然降级为 WAIT，不新增逻辑

### 模块 2 — Paper 执行客户端（新文件 `14-V15/lib/v15_paper_client.py`）

- 实现 v15_trader 调用的全部 9+2 个方法，底层为纸面账本 `data/v15_paper_ledger.json`
- place_order → 按 HL 现价模拟成交（含 0.05% 滑点模型）；place_stop_loss_take_profit → 记录条件单；cancel_* / get_* → 账本读写
- 注入点：`v15_trader._get_okx_client()` 增加环境开关 `V15_EXECUTION=paper` 时返回 paper client
- **硬安全闸**：`V15_EXECUTION=paper` 时构造 OKX 实盘 client 的路径直接 raise——双保险（本机 OKX 本就不通）
- 审计：沿用 `sim_trades_audit.jsonl` + 既有 L4 TradeEvent 注册钩子

### 模块 3 — 调度与配置

- DreamOS scheduler 新增任务 `v15_full_cycle`：**每小时 :45** 调用 `v15_trader.run_poll_cycle()`（paper 环境注入）；与 scan_main(:00)/orchestration(:30)/exit_check(:00,:30) 错峰
- 币池：`V15_COINS=BTC,ETH,SOL,ARB,OP,UNI,HYPE`（剔除 OKB），`V15_ASSET_TYPES` 同步（全 crypto → BTC风向标智能模式）
- 其余配置**原样保留**：4 档加仓、Phase D 影子模式、`V15_ALLOW_SHORT=true`（完整版 V15 的空头由 DirectionGate 三状态模型控制，paper 期完整观察其行为；实盘期方向策略在 Phase 2 提案中另行决策）
- `data/v15_state.json` 0 字节 → 首轮自然初始化

### 模块 4 — 安全与治理

- 凭据隔离：OKX key 从 `.env.common` 移入未追踪的 `config/.env.local` + `.gitignore`；git 索引中移除（历史已泄露 → 建议轮换）
- 实盘（Hyperliquid 钱包 c 执行）= **Phase 2 独立提案**，需另行审批 + 风险评估，不在本提案范围
- 观测：v15-daily-monitor cron（e38bb157）与 DreamOS 每日监控覆盖 paper 账本 + 审计日志

---

## 3. 变更清单

| 文件 | 类型 | 说明 |
|---|---|---|
| `14-V15/lib/hl_data_adapter.py` | 新增 | HL K线/现价适配器 |
| `14-V15/lib/v15_paper_client.py` | 新增 | Paper 执行客户端（9+2 方法） |
| `14-V15/lib/market_data.py` | 小改 | `V15_DATA_SOURCE` 环境开关 |
| `14-V15/core/v15_trader.py` | 小改 | `_get_okx_client()` 增加 paper 注入 + 硬安全闸 |
| `experiments/ab-trading/execution/aster_spot.py` | 微改 | get_candles 补 1d 周期 |
| `14-V15/config/.env.v15` | 改 | 币池 7 币 + 两个环境开关 |
| `14-V15/config/.env.common` → `.env.local` | 安全迁移 | 凭据隔离 + gitignore |
| `dreamos/cli/scheduler.py` + jobs.json | 改 | 新增 v15_full_cycle 任务（:45） |
| 测试 | 新增 | 适配器单测 + 离线集成冒烟（mock K线跑通 1 轮 poll cycle） |

### 不动项（硬约束）

- ❌ 不改 `v15_trader.py` 决策逻辑本体（3142 行引擎逐字节不动，仅 client 工厂注入）
- ❌ 不改 V9 红线参数（8%/4%/无固定止损，4 档加仓为既有配置非本提案新增）
- ❌ 不动 DreamOS 简化 V15 路径（orchestration_cycle paper 流水线 + PROP-20260816/B 对冲依赖它）
- ❌ 不动生产三空单路径（scan_main → A链 auto_trader）
- ❌ 不引入任何实盘下单能力（paper 硬闸）

---

## 4. 验收标准

1. 适配器单测全绿：K线映射（inst_id/bar→coin/interval）、paper 成交/条件单/撤单全方法覆盖、硬安全闸触发
2. 离线集成：mock K线下 `run_poll_cycle()` 完整跑通 1 轮——16 层信号 → DirectionGate → Phase D 影子日志 → paper 账本落盘 → 审计日志写入
3. 生产 :45 周期：完整决策栈在 HL 真实行情上运行，日志可见 16 层信号评分 / DirectionGate 状态 / Phase D G-D1/G-D2/G-D3 影子决策
4. 实盘零风险验证：OKX 不可达 + paper 注入 + 断言检查三重确认无真实下单路径
5. 存量不漂移：orchestration_cycle / 对冲 / scan_main 行为与账本 md5 对照无变化

## 5. 风险与回滚

| 风险 | 缓解 |
|---|---|
| HL 日线历史深度不足（新币 <128/200 日） | MA 返回 None → 现有降级路径 WAIT，不开仓 |
| paper 行为与未来实盘偏差 | paper 期 ≥72h 观察 + Phase 2 独立审批 |
| 引擎隐式依赖未覆盖的 client 方法 | 集成冒烟 + AttributeError 即时暴露（首轮即发现） |
| v15_trader 与 DreamOS 调度竞争资源 | :45 错峰 + 单进程 scheduler 内串行 |

**回滚**：删除 scheduler 任务 + 关闭两个环境开关即回到原状（完整版 V15 本来就没在跑，零副作用）；新增适配器文件独立，可整体移除。

## 6. 成本

- E 链实施：约 2.5~3.5 小时（含测试）
- Token/运行成本：每小时 1 轮轻量 poll（纯本地计算 + HL 公共 API，无 LLM 消耗）

## 7. 审批

- 飞书审批模板：096DC318（交易进化审批）
- **AUTO_PASS ≠ 用户批准**：需用户在对话中明确回复批准后方可进入 E 链实施
