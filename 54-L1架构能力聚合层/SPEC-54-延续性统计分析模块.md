# SPEC-54 — 趋势延续性统计分析模块（T0）

- **版本**: v1.6 ｜ **日期**: 2026-11-15 ｜ **状态**: ✅ T0 已实现（方法层 + 测试 + 报告脚本 + 机器契约）；✅ T0.5/A8 首版经 D-E02 出口交付（v1.5）；🟡 T2/D-E14 一维 h=1/2 首版经独立能力出口交付（v1.6），二维仍受样本与状态特征约束；v1.1 关闭评审 B1/B2/B3，v1.2 修订后续排期，v1.3 明确 T0.5=S3→S4 与 PIT 口径，v1.4 更正 R02 `pit=true` 已实现
- **归属**: 54-L1 架构能力聚合层 ｜ **层级**: L1（确定性统计，非预测）
- **调研来源**: [RESEARCH-TREND-PERSISTENCE-MODELS.md](./docs/RESEARCH-TREND-PERSISTENCE-MODELS.md)
- **母 SPEC**: [SPEC-54-L1架构能力聚合层.md](./SPEC-54-L1架构能力聚合层.md)
- **代码**: [l1agg/persistence/](./l1agg/persistence/) ｜ **测试**: [tests/test_persistence.py](./tests/test_persistence.py) ｜ **脚本**: [scripts/persistence_report.py](./scripts/persistence_report.py) ｜ **契约**: [contracts/persistence.schema.json](./contracts/persistence.schema.json)
- **评审**: [SPEC评审报告-延续性统计分析模块-v0.1.md](./SPEC评审报告-延续性统计分析模块-v0.1.md)（v1.0 有条件通过 4.10/5 → v1.1 复审通过）

---

## §1 定位与目标

### 1.1 解决什么

回答一个问题：**某个价格序列本身有没有「记忆」？记忆有多强、持续多久？**

这是调研中的 **P1 层（延续性度量）**，不是 P3（预测）。它把"趋势是否延续"从主观判断变成一组可复现、可带样本量披露的统计量。

### 1.2 目标

| # | 目标 |
|---|---|
| G1 | 输出 7 个确定性延续性指标（A1–A7），全部可反查 METHOD_LIBRARY 方法 ID |
| G2 | 每个指标必带 `n`；所有输出必带 `span / caveat`；样本不足必须降级而非静默给数 |
| G3 | 纯 stdlib 实现，与 `l1agg.align` 同纪律：同输入同输出，不引入 numpy/scipy |
| G4 | 一条命令生成四资产画像报告，落 `reports/persistence/` |

### 1.3 非目标（硬边界）

| 不做 | 原因 |
|---|---|
| ❌ 预测未来收益 / 点估计 | 属 L2（P3），本模块只描述历史 |
| ❌ 输出"将会上涨/预计延续" | 违反 SPEC-54 ADR-3（不做因果与点预测） |
| ❌ 综合评分（persistence_score） | 权重无客观依据，属伪精确；只给分项指标 |
| ❌ 用相关矩阵做方向推断 | 相关是同期联动，不含时间方向（调研 §5） |
| ❌ 引入 FinBERT / 机器学习 | 不属 T0 范围（调研 §2、§4 Tier B/C） |
| ❌ 写入或修改生产数据 | 只读 DB |

### 1.4 层级归属

```
L1（本模块）          L2（后续）              L3+（后续）
A1–A7 确定性度量  →   B1/B2/B3/B4 可解释基线  →  Tier C 深度模型
P1 延续性度量         P3 延续性预测             （样本 ≥3000 日才启动）
```

---

## §2 方法定义（A1–A7）

| ID | 方法 | 方法库 ID | 数学口径 | 输出字段 | 判读 |
|---|---|---|---|---|---|
| A1 | Hurst R/S | T13 | 输入为**收益序列**（价格上直算会得 H≈1.5）；分块 k=8,16,…,min(n/2, **256**)；每块 R/S 取均值；简化 Anis-Lloyd 修正 `(k-0.5)/k`（不含 k>340 长段修正）；`log(R/S) ~ log(k)` 的 OLS 斜率 | `h, chunks, max_chunk, loglog_r2, corrected, n, confidence, regime, regime_displayable` | H>0.55 持续；0.45–0.55 随机；<0.45 反持续。`regime_displayable=false`（n<2000）时**禁止展示 regime** |
| A2 | 方差比 VR(q) | T14 | `VR = Var(q期收益和)/q / Var(1期)`；同方差 z；正态近似 p | `q, vr, z, p, n, interpretation` | >1 趋势；≈1 随机；<1 均值回复 |
| A3 | AR(1)/半衰期 | T20/T21 | `φ = corr(r_t, r_{t+1})`；`half = ln0.5/ln|φ|` | `phi, halflife_days, n` | φ>0 延续；φ<0 反转；\|φ\|≥1 无半衰期（返回 null） |
| A4 | 连胜/连败 | F18 | 按收益符号切 run，统计长度分布；`r==0` 跳过并计入 `n_zero` | `n_runs, max_run, mean_run, max_up, max_down, n, n_zero` | 对比几何分布期望（p=0.5 时均值≈2） |
| A5 | 状态转移 | B07/B08/T24 | 2×2 计数矩阵 → 行归一；**仅方向态（涨/跌）**，波动 regime 归 T0.5/T1a；**零收益跳过**（与 A4 一致）并计入 `n_zero`；稳态 `π_up = p_du/(p_ud+p_du)`；停留期 `1/p_switch` | `p_up_up, p_up_down, p_down_up, p_down_down, steady_up, dwell_up_days, dwell_down_days, n, n_zero` | p_up_up>0.5 延续；<0.5 反转 |
| A6 | 趋势斜率 | T08/T09 | `ln(price) ~ t` 的 OLS；t 值、R²；**未做 HAC/Newey-West 修正** | `slope_per_day, annualized_log, se, t, p, r2, n, hac_corrected, note` | `hac_corrected=false` 时 `t` **仅作同一资产跨期相对比较，不得作显著性结论** |
| A7 | IC 衰减 | B13/B14/B15 | 因子=过去 `lookback` 期收益，目标=未来 h 期收益；Spearman IC；非重叠口径**遍历 h 个相位取均值与极差** | `lookback, items[{h, ric, n, ric_nonoverlap, ric_nonoverlap_min, ric_nonoverlap_max, n_phases, n_nonoverlap}], n` | IC 随 h 衰减越快，信号有效期越短 |

**A7 的双口径**：重叠样本 n 大但 t 虚高；非重叠样本更保守。两者都输出，禁止只报重叠口径。

**已知取舍**：
- p 值用正态近似（纯 stdlib 无 t 分布 CDF）。n≥30 时误差可接受，`n<30` 时方法直接拒绝。下溢时截断到 `1e-12`，**禁止输出 0**（0 会被读成"确定性"）。
- Hurst 用 R/S 而非 DFA。R/S 对短样本更敏感，但实现简单、可审计；已用 `confidence` + `regime_displayable` 双重兜底。
- Hurst 块上限固定 256（B3）：若不固定，n 增长时最大块会从 256 跳到 512/1024，同一资产滚动窗口的 H 会因窗口长度而非行情本身跳变，跨期不可比。
- A6 的 `t` 未做 HAC（B1）：对数价格 OLS 残差强自相关，名义 t 被放大（XAU 实测 t=101）。已通过 `hac_corrected=false` + `note` + 文本声明强制降级，HAC 实现留 T1a。
- A7 非重叠口径遍历 h 个相位（B2）：只取 `i%h==0` 会发生相位选择偏差（h=20 时换相位 IC 可差 0.1 量级），因此输出相位均值 + 极差。

---

## §3 数据契约

### 3.1 输入

| 项 | 规格 |
|---|---|
| 表 | `mm_metrics` |
| 过滤 | `sub_category = <symbol>` AND `metric_name = 'close_usd'` |
| 时间 | UTC 日频，按 `timestamp` 升序；同秒去重保留最新 |
| 取值 | `metric_value > 0`（对数收益前提）；非正值在 `trend_slope` 拒绝 |
| 入口 | `l1agg.align.load_price(db_path, symbol, days)`（只读，`mode=ro`） |

### 3.2 样本门禁

| 指标 | 最小 n | 不足时行为 |
|---|---|---|
| A1 Hurst | 64 | 抛 `PersistenceError` → 该项 null + reason |
| A2 VR(q) | max(30, 3q) | 同上 |
| A3 AR(1) | 30 | 同上 |
| A4 连胜 | 10 | 同上 |
| A5 转移 | 30 | 同上 |
| A6 斜率 | 30 | 同上 |
| A7 IC | lookback+max(h)+30 | 同上 |
| 整体画像 | 250（可配 `min_n`） | `quality.status ∈ {good, partial, degraded}`：样本不足 → `partial`；样本够但方法失败 → `degraded`；全通过 → `good` |

### 3.3 Hurst 特殊门禁

`n < 2000` 时 `confidence=low` 且 `regime_displayable=false`。理由：R/S 估计对样本长度极敏感，实测同一序列三种修正口径可给出 0.19 / 0.61 / 0.62。**低于门槛只作参考，不得进结论**；`regime` 字段仅供内部调试，文本层禁止展示「持续/反持续/随机」标签。

### 3.4 零收益口径

A4 与 A5 统一**跳过** `r == 0` 的观测（加密日频零收益极少，但契约必须一致），并把跳过个数写入 `n_zero`，使 `n + n_zero` 可对账。

---

## §4 输出契约

### 4.1 JSON 结构

机器可校验版本见 [contracts/persistence.schema.json](./contracts/persistence.schema.json)（JSON Schema draft-07，`oneOf: profile | errorProfile`）。

```json
{
  "kind": "persistence",
  "symbol": "BTC",
  "span": "2023-11-15~2026-11-12",
  "sample_n": 1093,
  "metrics": {
    "hurst": {"h": 0.647, "chunks": [8,16,32,64,128,256], "max_chunk": 256,
              "loglog_r2": 0.9995, "corrected": true, "n": 1093,
              "confidence": "low", "regime": "persistent", "regime_displayable": false},
    "variance_ratio": [{"q":2,"vr":1.0017,"z":0.057,"p":0.9549,"n":1093,"interpretation":"trend"}],
    "ar1": {"phi": 0.0033, "halflife_days": 0.12, "n": 1092},
    "runs": {"n_runs": 555, "max_run": 11, "mean_run": 1.97, "max_up": 9, "max_down": 11,
             "n": 1093, "n_zero": 0},
    "transition": {"p_up_up":0.5273,"p_up_down":0.4727,"p_down_up":0.5474,"p_down_down":0.4526,
                   "steady_up":0.5366,"dwell_up_days":2.12,"dwell_down_days":1.83,
                   "n":1092,"n_zero":0},
    "trend": {"slope_per_day":0.0004,"annualized_log":0.15,"se":0.00002,"t":16.367,"p":1e-12,
              "r2":0.197,"n":1093,"hac_corrected":false,
              "note":"t 未做 HAC 修正，仅作相对比较，不作显著性结论"},
    "ic_decay": {"lookback":20,"items":[{"h":20,"ric":0.0436,"n":1054,
                 "ric_nonoverlap":0.0513,"ric_nonoverlap_min":-0.1025,
                 "ric_nonoverlap_max":0.2251,"n_phases":20,"n_nonoverlap":53}],"n":1094}
  },
  "quality": {
    "status": "good", "sample_n": 1093, "span": "...",
    "align_method": "daily_last+ffill", "timezone": "UTC", "min_n": 250,
    "lookback_days": 1200, "degraded_reason": null, "failed_methods": {},
    "hurst_confident_n": 2000, "hurst_max_chunk": 256,
    "notes": ["trend_t_no_hac: ...", "hurst_low_confidence: ...", "ic_phase: ..."]
  },
  "caveat": "历史统计，不代表未来",
  "text": "..."
}
```

### 4.2 文本模板（固定，禁止自由发挥）

```
{资产} 近 {N} 个交易日延续性画像（{start}~{end}）；
Hurst={h}（{持续/随机/反持续}，置信度 {low|high}）        ← regime_displayable=true
Hurst={h}（口径敏感，仅参考，不作结论）                    ← regime_displayable=false（默认路径）
VR(2)={..}、VR(5)={..}、VR(10)={..}、VR(20)={..}；AR(1) φ={phi}，半衰期={half} 日；
最长连涨/连跌={up}/{down} 日；P(涨|涨)={..}，P(跌|跌)={..}；
趋势斜率 t={t}（R²={r2}，t 未做自相关修正）；
动量 IC：h=1 IC={..}、h=5 IC={..}、h=20 IC={..}；[降级：{reason}]；历史统计，不代表未来。
```

**文本禁忌**：不得出现「将会 / 预计 / 有望 / 建议买入」等预测或建议措辞；`regime_displayable=false` 时不得出现「持续/反持续/随机」标签。

### 4.3 字段命名纪律

- 时间单位一律写进字段名（`halflife_days`、`dwell_up_days`、`slope_per_day`），禁止裸 `halflife`。
- 概率保留 4 位，t/z 保留 3 位，p 保留 4 位；禁止用 0 表示"无 p 值"，用 `null`。
- 缺失一律 `null` + `quality.failed_methods` 记录原因，禁止填 0。

---

## §5 模块结构与 API

```
54-L1架构能力聚合层/
├── l1agg/
│   ├── align.py                     # 既有：对齐层（输入来源）
│   └── persistence/                 # 新增：延续性统计分析模块（包）
│       ├── __init__.py              # 对外 API 收口
│       ├── constants.py             # 阈值/异常/CAVEAT
│       ├── _stats.py                # 纯 stdlib 统计原语
│       ├── metrics.py               # A1–A7 单指标
│       ├── profile.py               # 聚合画像 + 质量门禁 + 文本模板
│       └── report.py                # 报告入口
├── tests/
│   └── test_persistence.py          # 新增：27 个用例
├── scripts/
│   └── persistence_report.py        # 新增：薄封装，调用 persistence.report
├── contracts/
│   └── persistence.schema.json      # 新增：JSON Schema 契约（profile | errorProfile）
├── reports/persistence/             # 产物：<YYYYmmdd-HHMM>.json
└── SPEC-54-延续性统计分析模块.md      # 本文件
```

### 5.1 公开函数

| 函数 | 签名 | 说明 |
|---|---|---|
| `hurst_rs(values, *, min_chunk=8, max_chunk=256, corrected=True)` | → dict | A1 |
| `variance_ratio(returns, q)` | → dict | A2 |
| `ar1_halflife(returns)` | → dict | A3 |
| `run_length_stats(returns)` | → dict | A4 |
| `transition_matrix(returns)` | → dict | A5 |
| `trend_slope(prices)` | → dict | A6 |
| `ic_decay(prices, *, lookback=20, horizons=(1,5,20))` | → dict | A7 |
| `build_profile(db_path, symbol="BTC", *, days=1200, min_n=250, vr_qs=(2,5,10,20), ic_horizons=(1,5,20))` | → dict | 聚合 A1–A7 |

- 异常统一为 `PersistenceError(ValueError)`；`build_profile` 内部逐项捕获，不因单项失败中断。
- 无全局状态、无随机数、无时间依赖（除 `load_price` 的 now 窗口）。

### 5.2 报告脚本

```bash
python3 scripts/persistence_report.py                          # 四资产，days=1200，落盘
python3 scripts/persistence_report.py --symbols BTC XAU        # 指定资产
python3 scripts/persistence_report.py --days 365 --out /tmp/p  # 自定义窗口与产物目录
python3 scripts/persistence_report.py --symbols BTC --json     # 单资产 JSON 到 stdout（不落盘）
```

`--days` 为**自然日**回看窗口（非交易日数），画像内以 `quality.lookback_days` 回显。单资产失败写入 `error` 字段，不阻塞其它资产。退出码：0 成功 / 2 DB 不存在。

---

## §6 验收标准

### 6.1 已通过的测试（27 项）

| 类别 | 用例 | 断言要点 |
|---|---|---|
| A1 | 随机游走 | 0.35 ≤ H ≤ 0.68，confidence=high（n=3000） |
| A1 | AR(1) φ=0.6 | H>0.55，regime=persistent |
| A1 | 短样本 n=500 | confidence=low，regime_displayable=false |
| A1 | 长样本 n=3000（B3） | chunks 最大 ≤ 256，`max_chunk=256` |
| A1 | n=20 | 抛 PersistenceError |
| A2 | iid n=4000 | 0.8≤VR≤1.2，\|z\|<2.5 |
| A2 | AR(1) | VR>1 |
| A2 | 强均值回复 | p 下溢截断，p>0（禁止输出 0） |
| A3 | AR(1) φ=0.6 | φ∈0.6±0.08，半衰期∈(1,2) |
| A3 | iid | \|φ\|<0.08 |
| A4 | 已知序列 | n_runs=7、max_up=4、max_down=2（跨块合并口径） |
| A4/A5 | 含 20 个零收益（I1） | 零收益跳过，`n_zero=20`，n 分别为 30 / 29 |
| A5 | 20涨+20跌+20涨 | p_up_up=38/39、p_down_down=0.95、n=59、n_zero=0 |
| A6 | 精确指数 | slope=0.01、R²≈1、\|t\|>100、p=1e-12 |
| A6 | 含非正价 | 抛 PersistenceError |
| A6 | HAC 声明（B1） | `hac_corrected=false` 且 `note` 含 "HAC" |
| A7 | 100日分段单边 | h=1 IC>0.5，全部 IC∈[−1,1] |
| A7 | 多相位（B2） | `n_phases=h`，min ≤ 均值 ≤ max |
| 聚合 | 合成库 n=500 | status=good，7 项全非空，text 含 Hurst 与 caveat |
| 聚合 | 合成库 n=120 | status=partial，reason=insufficient_samples，text 含"降级" |
| 聚合 | 常数价格 | status=degraded，variance_ratio=null，reason=partial_methods_failed，text 含"降级" |
| 聚合 | 文本降噪（反对 2） | 低置信度 text 含"口径敏感"、不含"持续"；含"未做自相关修正" |
| 聚合 | 可比性声明（I2/I6） | quality 含 `lookback_days=800`、`hurst_max_chunk=256`、`trend_t_no_hac` 说明 |
| CLI | `--json` 单资产（I4） | stdout 为单个 profile，且不落盘 |
| 契约 | schema 校验（I3） | profile 与 errorProfile 均通过 JSON Schema |
| 冒烟 | 真实库 BTC | status=good，n≥1000，hurst.confidence=low |

执行：`python3 -m pytest tests/ -q` → **146 passed**（persistence 27 + 既有 align/catalog/leader_registry 119，零回归）。

### 6.2 真实数据验收（2026-11-14，四资产 n=1093，max_chunk=256 口径）

| 资产 | Hurst | VR(5) | AR(1) φ | P(涨\|涨) | 斜率 t | R² | IC(h=20) / 相位极差 |
|---|---|---|---|---|---|---|---|
| BTC | 0.6470 (low) | 1.0376 | 0.0033 | 0.5273 | 16.37 | 0.197 | 0.0436 / −0.1025~0.2251 |
| ETH | 0.6341 (low) | 1.1183 | 0.0721 | 0.5229 | −9.61 | 0.078 | 0.1549 / 0.0442~0.2608 |
| SOL | 0.6342 (low) | 1.0115 | 0.0206 | 0.5152 | −10.66 | 0.094 | 0.0060 / −0.1925~0.1853 |
| XAU | 0.6094 (low) | 0.9712 | −0.0054 | 0.5500 | 101.00 | 0.903 | 0.0678 / −0.0968~0.2557 |

**结论**：四资产日频方向延续性极弱（φ≈0、VR≈0.97–1.12、P(涨|涨)≈0.52–0.55）；延续性主要体现在**趋势斜率（XAU 最强，R²=0.90，但 t 未做 HAC，不得作显著性结论）**。IC 在 h=20 的相位极差远大于均值本身（如 BTC 均值 0.0436、极差 −0.10~0.23），证明单相位口径不可用（B2）。

> 上表是 golden 参考，非硬断言（数据窗口前移会变）。硬断言只保留结构性约束：Hurst confidence 必为 low、7 项非空、n≥1000。

---

## §7 风险与限制

| 风险 | 现状 | 处置 |
|---|---|---|
| Hurst 口径敏感 | 三种修正口径实测 0.19/0.61/0.62 | 冻结实现 + `corrected` 字段 + 单测锁定 + `confidence=low` + `regime_displayable=false` 时禁止展示 regime |
| Hurst 跨期不可比 | v1.0 的 chunk 随 n 增长（512/1024） | 已固定 `max_chunk=256`，`quality.hurst_max_chunk` 可反查 |
| 样本偏短 | 1,093 < 2,000 | 全量标 low；不作为任何结论依据 |
| p 值为正态近似 | 纯 stdlib 无 t 分布 | n≥30 才计算；文档披露 |
| 趋势 t 被自相关放大 | 残差 ACF 显著非零，XAU 名义 t=101 | `hac_corrected=false` + `note` + 文本声明；HAC 实现留 T1a |
| 非平稳 | 全窗口一个数 | 本模块只给全窗口；分段（高/低波动）留 T1a |
| 未做多重比较校正 | 单资产 7 指标 | 本模块不做跨资产推断；进入 MERS 时由 H14 BH-FDR 处理 |
| 重叠样本 | A7 已双口径 | 同时输出 `ric`、`ric_nonoverlap` 与相位极差 |

---

## §8 后续阶段（不在本 SPEC 范围）

排期经 2026-11-14 复核修正，与 [RESEARCH-TREND-PERSISTENCE-MODELS.md §7](./docs/RESEARCH-TREND-PERSISTENCE-MODELS.md) 保持一致。

| 阶段 | 内容 | 依赖 | 门禁 | 不过怎么办 |
|---|---|---|---|---|
| **T-1**（关键路径） | 日频样本扩充：四资产 ≥3,000 日 | 18/19 回填 | 缺口<5%；PIT 无修订 | 阻塞 T2/T3 结论，不阻塞 T0.5 |
| **T0** ✅ | A1–A7 延续性画像（已交付） | 1,093 日 | 已完成（27 用例） | — |
| **T0.5 ✅** | A8 单资产自身状态 → 前瞻分布（h=1，4 分位桶；PIT 滚动分位分桶） | T0 + R02 `pit=true`（已实现） | **每桶非重叠 n≥250**；输出 `pit/as_of/effective_n/nonoverlap_n`；禁止点预测措辞 | 已实现降级：样本不足自动降为 2 桶并披露有效 n；经 D-E02 出口交付（v1.5），不得以 `pit=false` 冒充交付 |
| **T1a** | 自身状态特征 F11/F12 + 波动 regime PIT 化 | T0 | 缺失率<5%；每特征带 `as_of` | 阻塞 T3a |
| **T1b** | 跨资产相关特征 F1–F10 PIT 化 | T1a + 4 资产对齐 | 窗口不与前瞻窗口重叠；带 `n/window/as_of` | 阻塞 T3b；F6 无稳定 lead-lag 则放弃 T3c |
| **T2** 🟡 | 多维状态 → 前瞻条件分布（P2，A8）；一维 D-E14 h=1/2 已交付 | 一维出口只需已压缩相关状态 + 同步价格；二维仍需 T1b + T-1 | 1–2 维；**每桶非重叠 n≥250**；BH-FDR | 一维主期限降 2 桶、弱后续期限单独降级；二维继续等 T-1，不冒充完成 |
| **T3a** | HAR-RV + 分位数回归（波动腿） | T1a | 打败零参数基线；给区间 | 保留为波动腿基准 |
| **T3b** | Logistic / Ridge / HMM（方向腿） | T2 + MERS | 打败「无条件历史均值」与 `sign(过去20日收益)` 两个基线；跨 ≥2 个年度 regime 样本外同号 | 砍方向腿，只留波动腿 |
| **T3c**（可选） | Kalman / VECM | T1b 的 F6 | 同上 | 默认不做 |
| **T4**（可选） | Tier C（LightGBM → GNN/TFT） | 样本 ≥3,000 日且 T3 已建稳定基准 | 样本外稳定优于 T3 | 不上线 |

**T0.5 交付状态（v1.5）**：已交付。算法 `conditional.py::r02_percentile_forward`（`pit=true`，逐历史时点只用当时可见数据计算分位与桶边界，宏观输入按 `release_ts≤as_of` 过滤）+ 场景编排 `persistence/profile.py::conditional_distribution`（A8，`pit=True`，4→2 桶自动降级）+ 能力出口 D-E02（manifest `I30/R02` + `capabilities/stats.py::percentile_forward` + 前端 `exec_stat_query` 分位 cue 与 `dates` 传参）三层齐备。T0.5 位于 **S3→S4**，算法口径只引用 METHOD_LIBRARY §16.1，本节不重定义。剩余边界：真实数据纵深不足时按契约降级披露，不输出点预测；h>1 的重叠前瞻收益在 Newey-West/HAC 实现前只描述、不作显著性结论。

### 8.1 为什么 T2 门禁按「每桶非重叠」计

以下样本预算引自 [METHOD_LIBRARY §15](./docs/METHOD_LIBRARY.md) 同日快照，仅作门禁派生，执行时须按最新快照重算。现有 1,093 日，前瞻 h 期的非重叠样本约为 `1093/h`，再按 4 分位桶切分：

| h | 非重叠总数 | 每桶（4 桶） | 过 n≥250 |
|---|---|---|---|
| 1 | 1,093 | ≈273 | ✅ |
| 5 | ≈218 | ≈54 | ❌ |
| 20 | ≈54 | ≈13 | ❌ |

因此 **T0.5 只做 h=1**；h≥5 的分桶条件分布必须等 T-1 扩样本。用重叠样本凑够 250 属自欺——A7 已实测 h=20 非重叠仅 53 点。

### 8.2 状态口径分工

| 状态维度 | 归属 | 说明 |
|---|---|---|
| 涨/跌方向态 | **A5（已冻结）** | 2×2 转移矩阵，本 SPEC 已实现 |
| 波动 regime（高/低） | **T0.5 / T1a** | PIT 滚动分位分桶，算法只引用 METHOD_LIBRARY §16.1，不在本场景包重定义；A5 明确不做 |
| 跨资产相关状态 F1–F10 | **T1b / T2** | 需多资产对齐，非单资产 |

---

## §9 修订记录

| 版本 | 日期 | 内容 |
|---|---|---|
| v1.6 | 2026-11-15 | D-E14/T2 一维首版交付：独立 `conditional_distribution` 出口，R02 PIT 状态轴共享 B05/B10/R01/R08，默认 h=1/2、4 桶；主期限不足降 2 桶、弱后续期限单独降级，h>1 不输出朴素 t/p；54-L1 全量 751 例通过。二维 4×4 仍受样本与 F1–F12 状态特征约束 |
| v1.0 | 2026-11-14 | 首版落地：A1–A7 + 聚合画像 + 16 测试 + 报告脚本；四资产实测基线 |
| v1.1 | 2026-11-14 | 按评审报告 §3/§5 修复：B1 趋势 t 显式声明 `hac_corrected=false` + note + 文本披露；B2 IC 非重叠口径改为 h 相位均值 + 极差；B3 Hurst `max_chunk=256` 固定并写入契约；I1 零收益统一跳过 + `n_zero`；I2 `quality.lookback_days`；I3 新增 `contracts/persistence.schema.json`；I4 CLI `--json`；I6 `hurst.max_chunk`。文本层低置信度不展示 regime（反对 2）。测试 18→27，全量 137→146 passed；四资产基线按 max_chunk=256 重算 |
| v1.2 | 2026-11-14 | 排期复核：§8 重写为 T-1/T0/T0.5/T1a/T1b/T2/T3a-c/T4，新增每阶段门禁与「不过怎么办」；T2 门禁由「≥250 对齐点」改为「每桶非重叠 n≥250」并给出样本预算表；新增 §8.1 样本预算与 §8.2 状态口径分工（A5 只做方向态）；新增 A8 单资产版 T0.5（h=1）。仅文档，代码与测试不变 |
| v1.5 | 2026-11-15 | T0.5/A8 首版交付：D-E02 三层接线（manifest + executor + 前端分位 cue 分派与 `dates` 传参），`conditional_distribution` 以 `pit=True` 输出 h=1 前瞻分布，样本不足自动 4→2 桶并披露 `effective_n/nonoverlap_n`；T0.5 行 ⬜→✅，blocker 段改为交付状态与剩余边界；不改 A1–A7 冻结口径 |
| v1.4 | 2026-11-15 | 状态更正：R02 `pit=true` 已在 `conditional.py` 实现（逐时点滚动分位 + `release_ts≤as_of` 过滤），T0.5 blocker 改为场景编排、每桶非重叠 n≥250 样本纵深与能力出口 `effective_n/nonoverlap_n` 披露；算法口径与门禁不变，仅文档变更 |
| v1.3 | 2026-11-14 | 调研对齐：明确 T0.5=S3→S4，复用 D-E02/D-E13 且不新增能力 ID；明确 R02 双口径与 T0.5 的 PIT 依赖，禁止以全样本分位冒充 PIT；输出补 `pit/as_of/effective_n/nonoverlap_n`，算法只引用 METHOD_LIBRARY §16.1；样本预算标注引自 §15，补 h>1 Newey-West/HAC 前置。A1–A7 冻结口径、代码与测试不变 |
