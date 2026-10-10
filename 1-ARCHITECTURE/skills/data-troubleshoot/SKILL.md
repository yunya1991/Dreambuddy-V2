---
name: "data-troubleshoot"
description: "排查基本面数据链路问题：前端显示异常值（0.000、错误标签、量级不对、字段缺失）时，系统化追踪 18-DB→backfill→19-DAL→快照→API→前端 全链路，含字段契约验证、数据质量检查、云端一致性核对。Invoke when frontend shows suspicious values (0.000, wrong labels, missing fields, magnitude errors) or user reports incorrect fundamental data."
---

# Data Troubleshoot (基本面数据排查)

## 触发条件

当出现以下症状时调用本 SKILL：
- 前端显示 `0.000%`、`0.0`、空值、`--`
- 信号标签与数据矛盾（如"维持利率"标为"利多"）
- 数值量级明显错误（如 CPI 同比显示 334 而非 3.4）
- 数据来源为 legacy/fallback 而非真实 DAL 数据
- **字段缺失**：前端期望 `valuation_zone` 但 API 返回 `valuation_range`
- **多个模块同时异常**：如估值 + onchain 都显示 0 或空值（可能是 DAL DB 整体未同步）

## 排查流程（6 步法）

### Step 1: 确认前端显示值

```bash
curl -s http://localhost:9094/fundamental/snapshot | python -c "
import sys, json
data = json.load(sys.stdin)
for mod_name in sorted(data.get('modules',{}).keys()):
    core = data['modules'][mod_name].get('metrics',{}).get('core',{})
    for k, v in sorted(core.items()):
        marker = ' ⚠️' if (isinstance(v,(int,float)) and v == 0.0) else ''
        print(f'{mod_name}.{k}: {v}{marker}')
"
```

标记规则：
- `0.0` → 可能缺失数据
- 极小值（<0.001）→ 可能量级错误
- 极大值（>1e10）→ 可能单位错误
- `source` 含 Tavily/Mock → legacy 假数据

### Step 2: 检查 DAL 是否有该数据

```bash
python -c "
import sqlite3
conn = sqlite3.connect('19-数据访问层/data/dreambuddy_core.db')
# 按 sub_category 搜索
rows = conn.execute(\"SELECT sub_category, metric_name, metric_value FROM mm_metrics WHERE sub_category LIKE '%KEYWORD%' ORDER BY timestamp DESC LIMIT 10\").fetchall()
for r in rows: print(f'{r[0]}.{r[1]}={r[2]}')
"
```

常见 sub_category：
- 宏观：`CPIAUCSL`, `FEDFUNDS`, `fedwatch`, `fomc_decision`, `cpi`
- 链上：`btc_basics`, `glassnode`, `coinglass`
- 资金流：`etf_flow`, `binance_funding_rate`, `long_short_ratio`
- 跨市场：`^TNX`, `^VIX`, `DX-Y.NYB`, `SPY`, `GC=F`, `gold`, `BTC-USD`
- 社交：`social_volume`, `newsflash_*`

### Step 3: 检查 18-DB 原始数据

```bash
python -c "
import sqlite3, json
conn = sqlite3.connect('18-数据获取中心/data_center.db')
rows = conn.execute(\"SELECT * FROM records WHERE sub_category='SUB_CAT' ORDER BY timestamp DESC LIMIT 5\").fetchall()
for r in rows:
    # records 表结构: id, hash, source, category, sub_category, timestamp, metrics, events, timeseries, extra, version
    metrics = json.loads(r[6]) if r[6] else {}
    timeseries = json.loads(r[8]) if r[8] else []
    print(f'metrics={metrics}')
    if timeseries: print(f'timeseries latest={timeseries[-1]}')
"
```

### Step 4: 定位 bug 类型（9 大模式）

| 模式 | 症状 | 根因 | 修复方法 |
|------|------|------|----------|
| **P1: 小数未×100** | 0.4% 实际应为 44.9% | 后端存 0-1 小数，前端直接拼 `%` | 前端加 `percent: true`，fmt 中 ×100 |
| **P2: 信号阈值错配** | 值域 -1~1 但阈值 >=50 | 后端值域与前端阈值不匹配 | 查 API 返回值，按实际值域选阈值 |
| **P3: timeseries 漏同步** | 18-DB 有数据但 DAL 为空 | backfill 只读 metrics 列，漏 timeseries 列 | backfill 增加 timeseries fallback |
| **P4: sub_category 不匹配** | 后端查 `GC=F` 但 DAL 存 `gold` | 命名不一致 | 后端添加 fallback 映射 |
| **P5: 字段语义错误** | cpi_yoy=334（指数值非同比） | 变量名与实际数据语义不符 | 改用正确数据源或修正变量名 |
| **P6: legacy 假数据** | source=Tavily/Mock，值为合成 | API key 过期或未接入 DAL | 新增 collect_XXX 接入 DAL 真实数据 |
| **P7: DAL 关键字段=0 触发静默回退** | 估值返回 `valuation_range` 而非 `valuation_zone`，onchain 多个 0 | `collect_XXX` 在关键字段=0 时 return None → `_make_collector` 静默回退 legacy → 字段集不匹配 | **不**在 collect_XXX 中因单字段=0 就 return None；用合理默认值继续；或在回退时打 ERROR 日志+告警 |
| **P8: 快照文件脏数据持久化** | 服务重启前数据正常，重启后变 legacy | 服务启动时 DAL 数据不完整 → 快照含 legacy 字段 → 快照不自动刷新 | 重启前先验证 DAL 关键字段非 0；或定时刷新快照；或 API 实时调用 collector 而非读快照 |
| **P9: 云端 DAL DB 未同步** | 本地正常但云端异常（market_cap=0） | 本地 DAL 有数据但云端 DAL 无数据/0 值 | SCP 同步 `dreambuddy_core.db` 到云端 → 重启 fundamental.service |

#### P7 深度诊断：判断是否发生了 legacy 回退

```python
# 检查 API 返回的字段集是否与 DalSnapshotProvider 一致
# 如果包含 valuation_range/ahr999_index/mayer_multiple → 说明回退到了 legacy
# 如果包含 valuation_zone/nvt_ratio/nvt_z_score → 说明是 DalSnapshotProvider

legacy_fields = {'valuation_range', 'ahr999_index', 'mayer_multiple', 'pi_cycle_top', 'therm_index', 'sopr', 'valuation_heat_level'}
dal_fields = {'valuation_zone', 'nvt_ratio', 'nvt_z_score', 'market_cap_usd', 'realized_price'}

core = api_response['modules']['valuation']['metrics']['core']
has_legacy = any(f in core for f in legacy_fields)
has_dal = any(f in core for f in dal_fields)
if has_legacy and not has_dal:
    print("⚠️  估值模块回退到了 legacy DataCollector！根因：DAL 中 btc_basics.market_cap_usd = 0.0")
```

### Step 5: 修复

**后端修复**（`dal_snapshot_provider.py`）：
- P3: 在 `backfill_18_records.py` 的 `_iter_metric_rows` 增加 timeseries fallback
- P4: `self._metric("GC=F", "value", 0.0) or self._metric("gold", "value", 0.0)`
- P5: `cpi_yoy = self._metric("cpi", "actual", 0.0)` 而非 `CPIAUCSL`
- P6: 新增 `collect_news()` 等方法，注册到 `DAL_COLLECTORS`
- **P7**: 移除 `if market_cap == 0.0: return None`，改为用默认值继续计算；在 `_make_collector` 回退 legacy 时打 `[DAL][FALLBACK]` ERROR 日志
- **P8**: 重启服务前先 `CHECKPOINT WAL` + 验证 DAL 关键字段；或在 `build_module_snapshot` 中检测到 legacy 字段时拒绝写入快照

**前端修复**（`*.tsx`）：
- P1: 在 metric config 中加 `percent: true`，fmt 函数中 ×100
- P2: `signalOf` 阈值改为匹配实际值域（如 `>= 0` 而非 `>= 50`）
- 固定情绪标签：`fixedSignal: 'neutral'` 覆盖自动判断

**云端修复**（P9）：
```bash
# 1. 本地 checkpoint WAL（确保数据落盘）
python3 -c "
import sqlite3
conn = sqlite3.connect('19-数据访问层/data/dreambuddy_core.db')
conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
conn.close()
"

# 2. SCP 同步到云端
scp 19-数据访问层/data/dreambuddy_core.db luke@<云端IP>:/tmp/dreambuddy_core.db

# 3. 云端替换 DB 并重启服务
ssh luke@<云端IP> "
cp /tmp/dreambuddy_core.db /home/luke/dreambuddy/19-数据访问层/data/dreambuddy_core.db
sudo systemctl restart fundamental.service
sleep 10
curl -s http://localhost:9094/fundamental/snapshot | python3 -c \"
import sys, json
data = json.load(sys.stdin)
core = data['modules']['valuation']['metrics']['core']
print('valuation_zone:', core.get('valuation_zone'))
print('nvt_ratio:', core.get('nvt_ratio'))
\"
"
```

### Step 6: 重启 + 验证

```bash
# 重启后端
kill $(ps aux | grep "[m]l_trade_service_v2" | grep ".venv" | awk '{print $2}')
cd 9-基本面分析 && DAL_DB_PATH=19-数据访问层/data/dreambuddy_core.db python ml_trade_service_v2.py --no-collect &

# 验证
sleep 6 && curl -s http://localhost:9094/fundamental/snapshot | python -c "
import sys, json; data = json.load(sys.stdin)
# 检查修复后的值
"
```

## 管理缺陷与预防措施

数据层反复出问题的根因是**6 类管理缺陷**，按优先级排列：

### P0：静默降级无告警
- **问题**：`_make_collector` 在 DAL 返回 None 时静默回退 legacy，仅 print 一行日志，无人监控
- **预防**：
  - 回退时打 `[DAL][FALLBACK]` ERROR 级别日志，接入监控告警
  - 健康检查接口返回 `data_quality` 字段，标记哪些模块在用 legacy
  - 前端检测到 legacy 字段时显示"数据降级"红色标识

### P0：关键字段=0 过早 return None
- **问题**：`collect_valuation()` 中 `if market_cap == 0.0: return None` 导致整个模块回退
- **预防**：
  - collect_XXX 中不因单字段=0 就 return None，用合理默认值继续
  - 0 值在返回结果中用 `None` 而非 `0.0`，让前端显示 `--` 而非误导性的 0
  - 区分"数据缺失"（None）和"真实值为 0"（0.0）

### P1：快照脏数据持久化
- **问题**：服务启动时 DAL 不完整 → 快照含 legacy → 不自动刷新
- **预防**：
  - 重启前先验证 DAL 关键字段（market_cap, active_addresses 等）非 0
  - 或 API 实时调用 collector，不读快照文件（牺牲性能换正确性）
  - 或定时（每 5 分钟）刷新快照

### P1：字段契约三方不一致
- **问题**：DalSnapshotProvider vs DataCollector vs 前端期望字段集不统一
- **预防**：
  - 维护一份 `valuation_contract.json` 定义前端期望的字段
  - DalSnapshotProvider 和 DataCollector 都必须满足该契约
  - CI 中加字段契约测试：API 返回的字段 ⊇ 契约字段

### P1：数据质量监控缺失
- **问题**：健康检查只查进程，不查数据有效性
- **预防**：
  - 健康检查增加数据质量检查：关键指标非 0、数据新鲜度 < 24h
  - 关键指标阈值告警（如 market_cap < 1e12 → 告警）
  - 数据新鲜度监控：mm_metrics 最新 timestamp 与当前时间差

### P2：云端 DB 同步无自动化
- **问题**：18→19 层 backfill 是手动脚本，本地→云端无同步
- **预防**：
  - backfill 加入 cron 定时执行（每小时）
  - 本地→云端 DB 同步脚本（scp + restart），或云端直接运行 backfill
  - 部署脚本 `update.sh` 中加入"DB 同步 + 数据验证"步骤

## 字段契约验证

修复后必须验证 API 返回字段与前端期望一致：

```bash
# 验证估值模块字段契约
curl -s http://localhost:9094/fundamental/snapshot | python3 -c "
import sys, json
data = json.load(sys.stdin)
core = data['modules']['valuation']['metrics']['core']

# 前端 ValuationPanel 期望的字段
expected = ['mvrv_ratio', 'nvt_ratio', 'nvt_z_score', 'market_cap_usd', 'valuation_zone', 'nupl', 'puell_multiple']

missing = [f for f in expected if f not in core]
if missing:
    print(f'❌ 缺失字段: {missing}')
    print(f'   当前字段: {sorted(core.keys())}')
    # 判断是否回退到 legacy
    legacy = {'valuation_range', 'ahr999_index', 'mayer_multiple'}
    if legacy & set(core.keys()):
        print('   → 回退到了 legacy DataCollector！需检查 DAL 数据')
else:
    print('✅ 估值字段契约验证通过')

# 验证总览字段
overview_checks = {
    'flow': ['etf_total_flow', 'fund_flow_score', 'stablecoin_dominance_usdt', 'flow_regime'],
    'sentiment': ['sentiment_index', 'sentiment_classification', 'sentiment_regime', 'social_volume'],
    'onchain': ['onchain_trend', 'accumulation_signal', 'exchange_net_flow', 'network_health'],
    'macro': ['policy_score', 'cpi_yoy', 'rate_cycle', 'fed_funds_rate'],
    'breadth': ['btc_dominance', 'breadth_confirmation', 'global_change_24h', 'market_participation_index'],
}
for mod, fields in overview_checks.items():
    mod_core = data['modules'][mod]['metrics']['core']
    mod_missing = [f for f in fields if f not in mod_core]
    status = '❌' if mod_missing else '✅'
    print(f'{status} {mod}: {\"缺失 \"+str(mod_missing) if mod_missing else \"OK\"}')
"
```

## 关键文件

| 文件 | 作用 |
|------|------|
| `9-基本面分析/dal_snapshot_provider.py` | DAL 数据提供者，collect_XXX 方法 |
| `9-基本面分析/ml_trade_service_v2.py` | 后端服务入口 |
| `19-数据访问层/scripts/backfill_18_records.py` | 18→19 DAL 同步脚本 |
| `3.1-FRONTEND/src/components/features/fundamental/*.tsx` | 前端面板组件 |
| `18-数据获取中心/data_center.db` | 原始采集数据库 |
| `19-数据访问层/data/dreambuddy_core.db` | DAL 数据库（mm_metrics 表） |

## 常见 bug 速查表

| 字段 | 常见 bug | 正确值域 |
|------|----------|----------|
| probability (cut/hold/hike) | 小数未×100 | 0-1 小数，显示需×100 |
| fund_flow_score | 阈值 >=50 错配 | -1~1 |
| policy_score | 阈值 >=50 错配 | -1~1 |
| funding_rate | 显示丢精度 | -0.1~0.1，×100 显示 |
| cpi_yoy | 读指数绝对值 | 0-10 (%) |
| dxy_correlation | 阶梯阈值太粗 | -1~1 线性插值 |
| rate_cycle | 基于历史决议 | 按当前概率判断 |
| dot_plot_median | 采集器未提取 | fallback 用 fomc rate |
| news negative_count | legacy 假数据全正面 | 接入 DAL newsflash |
| us10y_yield | backfill 漏 timeseries | 增加 timeseries fallback |
| gold_price | sub_category 不匹配 | GC=F → gold fallback |
| valuation_zone | 返回 valuation_range | DAL market_cap=0 → 回退 legacy → 字段名不一致 |
| nvt_ratio/nvt_z_score | 字段缺失 | 同上，legacy 不返回这些字段 |
| market_cap_usd | 0.0 或缺失 | DAL 中 btc_basics.market_cap_usd=0 → 整个模块回退 |
| active_addresses/hash_rate | 0.0 | onchain 模块同样因关键字段=0 回退 legacy |
