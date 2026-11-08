# 数据 MCP 整合规划（调研结论存档）

> 创建：2026-11-05 22:00 ｜ 状态：调研完成，待实施
> 背景：主前端 3.1 基本面数据展示异常排查（fundamental_snapshot.py 收口）过程中，对 9-基本面分析模块定位与数据链路完成调研。

## 1. 背景与问题

- 前端 3.1 的 `scripts/fundamental_snapshot.py` 与 9-基本面分析的 `dal_snapshot_provider.py` 存在大量同构的模块构建逻辑（flow/macro/sentiment/onchain/intermarket/valuation/breadth），同一指标修复需要在两处分别接入（例：MVRV 真实值接入）。
- 23-四层闭环自进化交易架构通过 `sys.path.insert` 直接 import 9 层代码（dimension_force_evaluator 懒加载 DalSnapshotProvider 作第二数据源交叉校验），属于跨层硬依赖。
- 底层数据 MCP 现状：桥接层 `data.dal_query` 工具（chain/market/macro/metric 四命令），直接查 SQLite mm_metrics，属于薄查询层，无加工能力。

## 2. 9-基本面分析的实际定位（数据应用层）

- `dal_snapshot_provider.py`（887 行）：完整 19-DAL 数据源，十个 collect_* 方法（flow/macro/calendar/sentiment/onchain/intermarket/valuation/breadth/news/narrative），含 _latest/_history/_metric 通用查询、回退链（market_cap 缺失时 price×supply 估算）、NVT 派生计算。
- `engines/`：事件账本、事件映射、叙事、情绪、信号引擎（业务决策层）。
- `shared/`：OKX/Web3 流量 schema 映射、叙事证据映射（数据规范化资产）。
- `_build_ohlcv_dataframe` / `compute_features`：OHLCV 特征与基本面衍生特征计算。

## 3. 归并方案（分层归并，非整体搬迁）

### 3.1 下沉为数据 MCP 工具（数据加工能力）
- 十个 collect_* 方法 → 注册 `data.fundamental_snapshot` 类工具，提供加工后模块级快照（含回退链与派生计算）。
- OHLCV/特征计算 → `data.features` 工具，供交易架构复用。
- shared/ schema 映射资产随方法下沉，作为数据规范化层。

### 3.2 保留在 9 层（业务应用逻辑）
- engines/ 叙事/信号/事件引擎：策略与决策层职责，不下沉。
- backend/ 与前端路由：消费方，不下沉。

### 3.3 实施步骤
1. 数据加工能力下沉（provider + 特征计算 + schema 映射）
2. 注册为桥接层数据工具（data.fundamental_snapshot / data.features）
3. 保留 9 层为业务引擎层；23 层懒加载引用同步迁移为标准 MCP 调用

## 4. 收益

- 消除前端 3.1 与 9 层的重复模块构建逻辑，一处维护。
- 统一数据出口，消除 23 层跨层硬依赖。
- 9 层成熟回退/估算链（NVT、market_cap 估算）直接被前端复用。

## 5. 风险与前置条件

- 依赖方向：9 层 provider 读取 19-DAL，需保持 18→19 回填链路稳定。
- 数据缺口传导：归并前需先补齐 18 层采集缺口（见 §6），避免把空数据通道搬过去。
- 兼容性：23 层引用需同步迁移，避免归并期间断链。

## 6. 数据采集缺口清单（2026-11-05 核查）

### 6.1 已修复
- bgeometrics 指标名丢失：根因为 18 层调度器加载旧版采集器（14:25 启动 vs 16:32 新代码落盘）。已重启调度器（PID 239489）+ 手动补采 + 回填，19 侧 mm_metrics 已有 btc_metrics/mvrv=1.4461，前端 valuation 模块 data_quality 已从 derived 升级为 good。
- 桥接层 chain 映射已补充 btc_metrics 的 mvrv/sopr/nupl 条目（dsh_frontend_bridge.py L753-756）。注意：该文件曾被外部进程覆盖过一次，修改后需验证持久性。

### 6.2 待解决（按优先级）
1. **cycle_signals 的 bottom_* 系列无真实数据**：bottom_mvrv_value、bottom_nupl_value、bottom_puell-multiple_value、bottom_two-year-ma_value、bottom_reserve-risk_value 在 19 侧全部不存在，该类别近 30 天仅有 us_ 前缀 FRED 占位值（50.0）。预期产出源为 18 层 panewslab 采集器，需排查该链路。
2. **exchanges_whales 的 ex_*/whale* 无真实数据**：ex_bal_BTC_total、ex_summary_inflowUsd24h、whale_netflow_to_ex_usd 等全部不存在，同样被 FRED 占位数据占用类别名。
3. btc_dominance 采集。
4. ETF 分发行商明细（sosovalue 落库 sub_category=etf_dashboard，19 侧该类别为空）。
5. 清算数据（coinglass）。
6. fedwatch 利率概率接入 fundamental_snapshot.py（数据已在库：cut_prob=0.0, hold_prob=0.173, hike_prob=0.827, effr=3.88）。
7. btc_basics 采集质量：active_addresses/hashrate/tx_count_24h 落库为 0.0。
8. sopr/nupl：bgeometrics 免费额度限流（8次/小时）导致本轮仅采到 mvrv，调度器 4h 周期自动补齐，回填脚本可按需重跑。

## 7. 关键路径备忘

- 前端链路：3.1 路由 `src/app/api/fundamental/[...path]/route.ts`（60s 缓存）→ fundamental_snapshot.py → dsh_frontend_bridge（data.dal_query handler）→ 19-DAL SQLite mm_metrics
- 18 层 PG：127.0.0.1:5432, user dreambuddy, db data_center；密码在 18 层 .env（postgresql 连接串）或 3.1 前端 .env.production 的 DATABASE_URL
- 回填：19 层 scripts/backfill_18_records.py（PG records → mm_metrics，幂等，主键 source+sub_category+metric_name+timestamp）
- 18 层调度器：start_scheduler.sh（从 .env 注入 PG 凭据），日志 logs/scheduler.log
