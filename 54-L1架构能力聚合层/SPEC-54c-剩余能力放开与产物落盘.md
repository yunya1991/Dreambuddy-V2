# SPEC-54c 剩余 7 项能力放开与产物落盘

- 版本：v0.1（2026-11-17）
- 上游：SPEC-54 / SPEC-54b（卡片动态参数表单）
- 范围：D-E14 / D-G21 / D-G23 / D-A14 / D-A16 / D-E19 / D-K02 共 7 项
- 纪律：只放开「有真实数据、口径可披露」的能力；不伪造数据、不静默降级；
  任何门槛放宽必须在返回值中显式携带阈值与降级原因。

## 1. 现状与根因（云端 2026-11-17 实测）

| 能力 | 现状 code | 真实原因 |
| --- | --- | --- |
| D-E14 | `sample_insufficient` | 每桶非重叠门槛 250 + PIT 滚动窗口 250，454 个对齐点经 250 日预热只剩 204 个，连下游 B05/B10/R08/R01（min_n=250）都进不去 |
| D-G21 | `sample_insufficient` | `_panel_lists` 对 14 资产取**全量日期交集**，被历史最短资产（XCU 255 行、XAG 290 行）截断至 170 天 → 169 期横截面 < 250 |
| D-G23 | `unsupported` | `param_schema.UNSUPPORTED` 静态禁用；实际 `mm_events` 有 548 条（US500/TLT/XAU/BTC），事件窗能力已实现 |
| D-A14 | `unsupported` | 五张 `mm_*` 明细表为空；但 `mm_metrics` 已有三条日频长序列（funding / OI / long_short），可直接装配 |
| D-A16 | `unsupported` | `stablecoins_top_10.total_circulating_usd_bln` 仅 283 行（2026-09-28 起），且无长历史采集 |
| D-E19 | `product_missing` | lights 只在请求内现算，`artifacts/visual/lights_history.json` 的缓存签名不含数据水位 → 从不落盘累积 |
| D-K02 | `product_missing` | `reports/discovery/<期>/` 无任何生产者 |

## 2. 改造方案（6 个工作组）

### W1 D-E14：E14 专用门槛（卡口头放宽，能力层默认值不动）

- 装配器对 D-E14 显式传 `window=120`、`min_bucket_n=100`；
- 能力层函数默认值保持 250（既有单测与二维档位契约不变）；
- 输出 `params.min_bucket_nonoverlap_n=100`、`params.window=120`，答案句披露
  「4 桶 → 2 桶」或「h=2 每桶不足」，`quality.degraded_reason` 保留。

### W2 D-G21：面板按覆盖率收口

- `_panel_lists` 先按最长序列长度做覆盖率过滤（`len ≥ 0.6 × 最长`），
  再取公共日期轴；若仍 < 250 天，按覆盖率从低到高逐个剔除直到 ≥250 或只剩 2 资产；
- 12 资产实测公共轴 494 天（2024-10-29 ~ 2026-11-11），Fama-MacBeth 期数
  493 ≥ 250；`n_assets` 在答案句与 `params` 中披露。

### W3 D-G23：事件窗 CAR 接线

- 从 `UNSUPPORTED` 移除；
- 装配器把 D-G23 并入 `PRICE_CAPS`，复用 D-E04 的 `_load_events(symbol, days)`
  装配 `events` + `dates` + `symbol`；事件为空返回 `product_missing`（不伪造）。

### W4 D-A14 / D-A16：数据装配 + 采集补齐

- D-A14 三指标固定口径（与 `data_query_executor._CROWDING_SERIES` 一致）：
  `funding_rate.funding_rate_pct`、`open_interest.open_interest_value_binance`、
  `long_short_ratio.long_short_ratio`，按 UTC 日期交集对齐后传 `series`；
- D-A16 优先读 `stablecoin_supply.total_circulating_usd_bln`，缺失回退
  `stablecoins_top_10.total_circulating_usd_bln`；新增
  `scripts/backfill_stablecoin_supply.py`（DefiLlama `stablecoincharts/all`，
  免 Key）落长历史到 `stablecoin_supply.total_circulating_usd_bln`。

### W5 D-E19：点亮块落盘与日累积

- 主览图每次请求把当期 D-E19 block 写 `artifacts/visual/lights_latest.json`；
- 以 `as_of` 为键追加 `artifacts/visual/lights_daily.jsonl`（同日幂等），形成可验证的累积；
- `_lights_history` 缓存签名加入数据水位（最后交易日），新交易日自动重算；
- 能力卡片未传 `block` 时回退读取 `lights_latest.json`，仍缺失才返回 `product_missing`。

### W6 D-K02：发现报告生产者

- 新增 `scripts/discovery_scan.py`：读 `config/discovery_space.yaml`（预注册冻结项），
  按固定枚举顺序单序列→双序列、序列/变换/期限执行 **B14 RankIC** 筛选，
  70/30 分段（holdout 仅验证符号一致率），BH-FDR α=0.05，|corr|>0.95 去重，
  预算 5,000 单元内确定性截断并在 manifest 记录；
- 产出 `reports/discovery/<YYYYMMDD-HHMM>/manifest.json`、`findings.jsonl`，
  随后调用 `scripts/build_patterns.py` 生成 `patterns.json`；
- 只写报告目录，不写数据库、不改配置；`D-K02` 仍只读最近一期。

## 3. 验收标准（AC）

| AC | 判据 |
| --- | --- |
| AC1 | 云端 `D-E14` code=ok，返回 `min_bucket_nonoverlap_n=100`、`window=120`，答案含降级披露 |
| AC2 | 云端 `D-G21` code=ok，`n_assets≥2` 且 `n_periods≥250` |
| AC3 | 云端 `D-G23` code=ok 或 `sample_insufficient`（事件映射成功），不再返回 `unsupported` |
| AC4 | 云端 `D-A14` code=ok（三指标交集 n≥60）；`D-A16` code=ok（growth_7d 非空） |
| AC5 | 云端存在 `artifacts/visual/lights_latest.json` 与 `lights_daily.jsonl`，且 jsonl 行数随交易日增长 |
| AC6 | 云端存在 `reports/discovery/<期>/manifest.json` + `findings.jsonl` + `patterns.json`，`D-K02` code=ok 或 partial(`no_findings`) |
| AC7 | 94 项能力矩阵 `code=ok` 数 ≥ 88（原 82 + 本次 6 项），无新增 `unsupported` |
| AC8 | 全量 pytest（54 模块）通过，前端 3001/3002 双实例 health 200 |

## 4. 风险与回滚

| 风险 | 处置 |
| --- | --- |
| E14 门槛放宽被误读为「结论变强」 | 阈值、窗口、降级原因全部落字段；答案句保留「历史统计，不代表未来」 |
| G21 剔除资产造成样本选择偏差 | 只剔除覆盖率 <60% 的资产，答案句披露 `n_assets` 与期数 |
| 稳定币长历史与既有短序列口径不一致 | 写入独立 `stablecoin_supply` 子类，不覆盖 `stablecoins_top_10` |
| K02 报告与预注册空间不一致 | manifest 记录 `space_hash`、截断维度与 `evaluated_methods`，仅标 candidate |
| 落盘失败影响主览图 | 全部写盘 FAIL-OPEN（异常吞掉，仅记录），不影响响应 |

## 5. 变更清单

- `l1agg/capabilities/param_schema.py`
- `3.1-FRONTEND/scripts/capability_resolve.py`
- `3.1-FRONTEND/scripts/visual_overview.py`
- `54-L1架构能力聚合层/scripts/backfill_stablecoin_supply.py`（新增）
- `54-L1架构能力聚合层/scripts/discovery_scan.py`（新增）
- 测试：`tests/test_spec54c_open_capabilities.py`（新增）、既有 resolve 测试更新
