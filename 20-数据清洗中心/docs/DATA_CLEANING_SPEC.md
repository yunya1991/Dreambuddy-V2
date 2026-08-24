# 20-数据清洗中心 专项 Spec v1.0（摘自全局 Spec v1.0 frozen 对应章节归档）

```
文档状态：归档版（设计冻结，与全局 specs 一致）
来源文档：docs/superpowers/specs/2026-08-24-data-cleaning-and-feature-hub-spec.md
归档范围：本目录 20-数据清洗中心 专项内容（Silver层 / H1集成 / M1阶段 / T1~T12 / 本模块监控指标）
```

---

## 一、定位（奖章三层中 Silver L2）

Bronze（18-采集，原响应不改）→ **Silver = 20-数据清洗中心**（强制链路·入库必先清洗）→ Gold（写19-DAL就绪）

- 核心目标：**脏数据拦截率 ≥ 99.5%**
- 0 新增依赖：仅依赖已有 pandas / numpy / 18-data_center.monitoring 三件套
- fail-open 兜底对齐 project_memory 与 FiveDomainFeatureComputer：热路径不抛异常，兜底中性 50

---

## 二、目录结构

```
20-数据清洗中心/
├── data_cleaning/                  # 主包
│   ├── __init__.py                 # 导出 CleaningPipeline / SilverLayer
│   ├── contract.py                 # SilverRecord / CleanedDF / CleaningTrace 契约
│   ├── errors.py                   # CleaningError / QualityGateFailed
│   ├── cleaners/                   # 算子（责任链节点）
│   │   ├── dedup_align.py          # 去重+时间对齐+重采样ffill(limit=5)
│   │   ├── outlier_filter.py       # 🔴 三级异常过滤（核心）
│   │   ├── missing_imputer.py      # 缺失值插补（时序/宏观/事件三级兜底→50）
│   │   └── unit_normalizer.py      # 币种→USD / %归一 / 换手率ratio
│   ├── gate/
│   │   └── quality_gate.py         # 🟠 复用 18-quality.py，enforce_hard_block=True
│   ├── adapters/
│   │   ├── record_to_df.py         # DataRecord(metrics/timeseries/events) → DF
│   │   └── df_to_record.py         # DF → SilverRecord / DAL 写回格式
│   ├── pipeline/
│   │   └── cleaning_pipeline.py    # Chain of Responsibility：.add(...).run(record)
│   └── cli/
│       └── app.py                  # dc-clean status / health --source / verify
├── tests/                          # T1~T12 单测 + 集成
├── config/
│   └── cleaning_rules.yaml         # category × sub_category × asset 参数走查表
├── requirements.txt                # 0 新增依赖
├── docs/
│   └── DATA_CLEANING_SPEC.md       # 本文件（归档）
└── README.md
```

---

## 三、流水线编排（不可颠倒）

```
DataRecord → ① DedupAlign
              │  drop_duplicates([timestamp,asset,key]) + resample→ffill(limit=5)
              ▼
          ② Outlier3LFilter（🔴 核心）
              │  ① |Z|>3.0 标记到trace不裁剪 （极端行情4.5，走查）
              │  ② IQR×1.5 (宏观收严 1.3) clip 到边界 / 事件期保留
              │  ③ |Δprice|>3.0×14-ATR (黄金2.5 / 股票2.8，走查) → 匹配事件命中保留/否则 clip+ffill(1)
              ▼
          ③ MissingImputer（B5 fail-open=50）
              │  时序: ffill(5) → linear → 50/median；宏观: linear → 拖尾 → 50；事件: 1/0/0.5
              ▼
          ④ UnitNormalizer（非USD×汇率；百分比/100；换手率→ratio）
              ▼
          [Cleaned DF + CleaningTrace] → QualityGate(enforce_hard_block=True)
              │   EMPTY_RESULT / CONTRACT_INVALID / DUPLICATE / STALE
              ├─ PASS → SilverRecord → 写入 19-DAL (Gold)
              └─ FAIL → 仅写 Bronze 审计 + log ERROR(6层栈) + Lark/File 告警
```

---

## 四、设计模式表

| 组件 | 模式 | 集成点 |
|---|---|---|
| CleaningPipeline | Chain of Responsibility | 18-dispatcher._fetch_monitored 写入 DAL 前调用 |
| QualityGate | Facade（18-quality） | 直接 import；新增 enforce_hard_block |
| Record↔DF Adapter | 双向适配器 | 按 category(metrics/timeseries/events) 展开列 |
| CleaningRule YAML | Strategy 查表 | category×sub_category×asset 覆盖默认参数 |
| fail-open 兜底 | Circuit Breaker 降级 | 任一环节异常→中性值；不抛到交易热路径 |

---

## 五、集成点 H1（最小侵入 ~10 行）

改文件：`18-数据获取中心/data_center/core/dispatcher.py` 的 `_fetch_monitored()` 方法

```python
from data_cleaning import CleaningPipeline
_pipe = CleaningPipeline.default_with_gate(enforce_hard_block=True)

async def _fetch_monitored(...):
    record = await collector.fetch(...)
    silver_result = _pipe.run_or_fallback(record)
    if silver_result.gate_passed:
        await sink.write_silver(silver_result.silver_record)
    else:
        await sink.write_bronze_only(silver_result.bronze_record)
        await alerting.dispatch(silver_result.quality_report)
    return record  # ⭐ 对外契约字节等价不变
```

灰度 Flag：`EN_SILVER=False（默认旁路）`，按 collector×category 粒度开启；秒级回滚=设 False

---

## 六、M1 阶段交付与验收

| M1 项 | 内容 |
|---|---|
| **工期** | 2 天（含评审） |
| **交付物** | 20-完整骨架代码 + yfinance_collector 单源接入 + 双写 + H1集成点 + dc-clean CLI |
| **灰度范围** | 默认 EN_SILVER=False 旁路；试运行仅 category=finance, source=yfinance |
| **测试组** | T1 Contract/Errors → T2 DedupAlign → T3 Outlier3L边例 → T4 Imputer边例 → T5 Normalizer → T6 Gate脏数据注入 → T7/T8 Adapter双向 → T9 Pipeline全链+fail-open → T10 H1旁路等价 → T11全局回归（铁门槛：18-M1~M5 164项0回归）→ T12 yfinance BTC E2E |
| **回滚方式** | EN_SILVER=False；删除 20 目录；dispatcher.py 回退到 M5 原版 |

---

## 七、监控指标（Silver 专项）

| 指标 | 计算方式 | 告警阈值 |
|---|---|---|
| silver_gate_pass_rate | PASS / total | < 98% 连续3批次 → Lark红警 |
| silver_outlier_clip_count | ①3σ / ②IQR / ③ATR 分档统计 | ③ ATR档 > 2×7日均 → 调查 |
| silver_missing_impute_rate | 插补cell占比 | > 10% → 告警（源头故障） |
| silver_failopen_count | L1 兜底次数 | 同模块 5min ≥ 3 → Lark告警 |
| silver_ohlcv_stale_sec | now() − latest(timestamp) | ≥ 15min → 触发离场缓存时效性旁路直接重取（project_memory红线） |
| silver_macro_stale_hour | now() − latest(timestamp) | FRED ≥ 48h 橙；CPI/PCE ≥ 5天 红 |

---

## 八、日常运维 CLI 快捷入口

| 命令 | 场景 |
|---|---|
| `dc-clean status` | PASS率 / 拦截率 / fail-open次数 / 各源stale 日常巡检 |
| `dc-clean health --source yfinance --asset BTC` | 近N条清洗 trace + 脏数据样本样例（实盘复盘排查） |

---

## 九、关联回写入口（全局完整版 Spec）

本归档文件为 20 号专项摘录，完整章节含 21-FeatureHub、集成 H2/H3、M2/M3、错误处理三层全图、新鲜度红线关联易经离场缓存等内容：

👉 完整 Spec：[2026-08-24-data-cleaning-and-feature-hub-spec.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/docs/superpowers/specs/2026-08-24-data-cleaning-and-feature-hub-spec.md)
