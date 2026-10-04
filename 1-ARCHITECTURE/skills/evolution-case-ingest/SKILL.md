---
name: "evolution-case-ingest"
description: "为自进化系统案例库（washout/washout_reversal/pump_dump_reversal）新增闭环训练案例。Invoke when 用户要求为自进化系统增加训练案例、入库市场行情样本、或补充 CBR/KNN 案例库。"
---

# 自进化训练案例入库

为自进化系统的 CBR/KNN 案例库新增闭环训练案例。案例库存储于 `4-MEMORY/data/evolution_cases/{library_name}.json`，供 WashoutClassifier 等模块做 KNN 检索 + 贝叶斯后验推理。

## 触发条件

用户要求：
- 为自进化系统增加训练案例
- 将某段行情样本入库到案例库
- 补充 washout / reversal 案例库
- 标记「假突破」「宏观顶」「杠杆出清」等典型场景

## 步骤

### 1. 确定案例库归属

| 案例库 | library_name | actual_label 取值 | 适用场景 |
|--------|-------------|-------------------|---------|
| WashoutCaseLibrary | `washout` | `washout` / `weakness` | 价格破位后判定是洗盘（会反弹）还是真弱势（继续跌） |
| WashoutReversalCaseLibrary | `washout_reversal` | `reversal_long_success` / `reversal_long_fail` | 洗盘结束后反转做多的成败 |
| PumpDumpReversalCaseLibrary | `pump_dump_reversal` | `reversal_short_success` / `reversal_short_fail` | 拉高出货后反转做空的成败 |

判断要点：
- 宏观驱动破位 + 多头清算 + OI 下降 → `washout` 库，label=`weakness`
- 缩量破位 + 支撑守住 + 快速反弹 → `washout` 库，label=`washout`
- 洗盘结束后抄底做多 → `washout_reversal` 库
- 拉高诱多后做空 → `pump_dump_reversal` 库

### 2. 构造 13 维特征快照（F1-F13）

特征定义见 `11-易经推理系统/scripts/memory_l4/bcrm2/washout_features.py`。缺数据维度用 NEUTRAL_DEFAULTS 中性值。

| 维度 | key | 洗盘(washout)倾向 | 真弱势(weakness)倾向 | 中性默认 |
|------|-----|-------------------|---------------------|---------|
| F1 | volume_ratio_20d | <0.8 缩量 | >1.5 放量 | 1.0 |
| F2 | support_holds_count | ≥3 守住 | 0 破位 | 0.0 |
| F3 | atr_compress_ratio | <1 收窄 | >1 扩大 | 1.0 |
| F4 | oi_change_rate_7d | >0 增仓 | <-0.10 投降 | 0.0 |
| F5 | cycle_position_365d | <0.3 低位 | >0.7 高位 | 0.5 |
| F6 | rebound_ratio_5d | >0.5 反弹强 | <0.3 反弹弱 | 0.5 |
| F7 | news_negative_score | 低 | 高 | 0.0 |
| F8 | btc_correlation_30d | <0.5 独立 | >0.7 跟随 | 0.5 |
| F9 | oi_price_quadrant | 1 (OI↑P↓空头建仓) | 3 (OI↓P↓多头投降) | -1.0 |
| F10 | funding_rate_zscore | 持续负 | 突然转正 | 0.0 |
| F11 | cvd_price_divergence | 负(trapped) | 正(同步下行) | 0.0 |
| F12 | ofi_std_20d | 低方差+高量 | 高方差 | 0.0 |
| F13 | wyckoff_climax_stage | 3 Exhaustion | 1/2 Panic/Sustained | 0.0 |

### 3. 计算 pnl_pct 与 reward

- `pnl_pct`：闭环盈亏百分比（如 0.02 = +2%，做空破位获利为正）
- `reward = tanh(pnl_pct / 0.02)`，裁剪到 [-1, 1]
  - pnl_pct=0.02 → reward=tanh(1.0)=0.7616
  - pnl_pct=-0.02 → reward=tanh(-1.0)=-0.7616

### 4. 写入 JSON 文件

文件路径：`4-MEMORY/data/evolution_cases/{library_name}.json`

格式为 JSON 数组，每个元素是 WashoutCase 字典：

```json
[
  {
    "case_id": "<唯一ID，如 btc_20260923_macro_liquidation_weakness>",
    "coin": "BTC",
    "entry_time": "2026-09-23T20:00:00+00:00",
    "exit_time": "2026-09-24T02:00:00+00:00",
    "features_snapshot": { ... F1-F13 ... },
    "actual_label": "weakness",
    "pnl_pct": 0.02,
    "reward": 0.7615941559557649,
    "timestamp": "2026-09-24T05:00:00+00:00"
  }
]
```

注意：若文件已存在，将新案例追加到数组中（case_id 重复则覆盖）。

### 5. 验证

```python
import sys
sys.path.insert(0, '<project_root>/1-ARCHITECTURE')
from dreamos.evolution.washout_case_library import WashoutCaseLibrary

lib = WashoutCaseLibrary(persist_path='<project_root>/4-MEMORY/data/evolution_cases/washout.json')
assert len(lib) >= 1
case = lib.get('<case_id>')
assert case.actual_label in ('washout', 'weakness')
assert abs(case.reward - __import__('math').tanh(case.pnl_pct / 0.02)) < 1e-9
neighbors = lib.knn_search(case.features_snapshot, k=1)
assert neighbors[0][0] == 0.0  # 自身检索距离为0
```

运行回归测试：`pytest tests/test_washout_w4.py`

## 硬约束

- reward 必须用 `tanh(pnl_pct / 0.02)` 公式，不可手填
- actual_label 必须小写
- features_snapshot 缺失维度用 NEUTRAL_DEFAULTS，不可省略导致 KNN 距离偏差
- 案例库 < 30 例时分类器走降级规则，新案例仍需入库等待积累
- 不修改案例库 Python 代码，仅追加 JSON 数据

## 参考文件

- 数据结构：`1-ARCHITECTURE/dreamos/evolution/washout_case_library.py`
- 特征定义：`11-易经推理系统/scripts/memory_l4/bcrm2/washout_features.py`
- 分类器：`1-ARCHITECTURE/dreamos/evolution/washout_classifier.py`
- 反转库：`washout_reversal_case_library.py` / `pump_dump_reversal_case_library.py`
