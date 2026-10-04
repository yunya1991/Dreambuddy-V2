# SPEC — 事件驱动策略 P0 盲区修复（非农/CPI 加息预期）

> **版本**：v1.0 (2026-10-02)
> **状态**：待实施
> **优先级**：P0
> **作者**：调研沉淀（记忆 VM-1790952663890-dca3391e 落地）
> **关系**：本文件是 [`SPEC-美国宏观事件驱动交易策略.md`](./SPEC-美国宏观事件驱动交易策略.md) v2.0 (2026-09-17) 的**增量补丁**，不替代原 SPEC。原 SPEC 覆盖 FOMC 议息周期 6 阶段、利空出尽 4 维定义、不确定性消除三层权衡；本补丁仅修复原 SPEC **未覆盖的盲区**：非农/CPI 等非 FOMC 周期事件实质影响加息预期时，`EventDrivenStrategy` 与 `PrimaryContradictionDetector` 直接返回中性，导致 BCRM2.0 收不到宏观反向风险注入。

---

## 一、问题陈述

### 1.1 触发事件（2026-10-02）

今日美国非农数据大幅降低美联储加息预期，BTC/ETH 大涨。BCRM2.0 在 HYPE/MSTR/MU/COIN/ARB/SKHYNIX 等币种上反复开空单，宏观反向风险无法被识别，导致逆势持仓。

### 1.2 直接根因

`EventDrivenStrategy.evaluate()` 在 [event_driven_strategy.py:89-98](./dreambuddy_evolution/engines/event_driven_strategy.py#L89-L98) 存在硬限制：

```python
# 仅在 FOMC 周期内激活
if not event_ctx.get("in_fomc_cycle", False):
    return EventDrivenSignal(
        signal="neutral",
        confidence=0.0,
        mode="none",
        scores={},
        event_phase=cycle_phase,
        reason="不在 FOMC 周期内",
    )
```

非农/CPI 不在 FOMC 议息周期内（`in_fomc_cycle=False`），但实质影响加息预期。当前实现直接返回中性，**完全错过此类宏观信号**。

### 1.3 次要根因

1. `PrimaryContradictionDetector._classify_primary()` 在 [primary_contradiction_detector.py:149-157](./dreambuddy_evolution/engines/primary_contradiction_detector.py#L149-L157) 同样有 `in_fomc` 硬限制，非 FOMC 周期事件无法被识别为主要矛盾
2. `EventDrivenStrategy._assess_forward_guidance()` 中 hike_prob=0 时兜底返回 1.0（参考记忆 VM-1789631187004），需用真实 CME FedWatch 数据替换
3. `UsEconomicCalendarCollector` surprise 计算为绝对值差（actual-forecast），**不是 CESI 标准化**（Surprise=(Actual-Forecast)/σ），无法跨指标比较
4. `FedEventCollector` 用爬虫爬 investing.com，脆弱且无 EFFR/meeting_date/contract 字段，需用 `cme-fedwatch` PyPI 包替换
5. `FredCollector.SERIES` 缺 EFFR/UNRATE/DGS10 三个关键序列

### 1.4 边界澄清（用户硬约束）

> "BCRM2.0 这个和 V15 没有任何关系，战略层会影响 BCRM2.0，不过现在应该还在独立测试，注意梳理边界"

- **BCRM2.0 与 V15 完全独立**，本 SPEC 不涉及 V15
- **战略层会影响 BCRM2.0**，但战略层当前默认关闭（`enable_strategy_layer=False`、`enable_five_domain=False`），本 SPEC 不修改战略层
- **BCRM2.0 当前独立测试**，本 SPEC 修复 EventDrivenStrategy 盲区后，BCRM2.0 通过 `polling_trader.py:223-260` 的事件桥接（只读 odaily_newsflash 币种快讯情感）**仍读不到宏观事件类型**——这是 P1 范围，本 P0 SPEC 不涉及

---

## 二、与原 SPEC 的关系

| 维度 | 原 SPEC v2.0 (2026-09-17) | 本补丁 v1.0 (2026-10-02) |
|------|---------------------------|--------------------------|
| 覆盖范围 | FOMC 议息周期 6 阶段（expectation_build→rise→jump→digest→event→repricing） | 非 FOMC 周期事件（非农/CPI/PPI）的加息预期影响 |
| 核心机制 | 买预期卖事实 + 实际利率驱动 + 利空出尽 4 维 + 三阶段权衡 | 解除 `in_fomc_cycle=False` 硬限制 + 注入 CESI Surprise 触发 + CME FedWatch 真实概率 |
| 数据源 | 假设 hike_prob 已注入 | 明确 `cme-fedwatch` PyPI 包替换 investing.com 爬虫 |
| 触发条件 | `in_fomc_cycle=True` | `in_fomc_cycle=True` **OR** `cesi_surprise ≥ ±1.5σ` |
| 修改文件 | event_driven_strategy.py / primary_contradiction_detector.py / event_dominance_controller.py | 同上 + fred_collector.py / fed_event_collector.py / us_economic_calendar_collector.py / data_pipeline.py |

**不冲突**：本补丁解除硬限制后，原 SPEC 的 FOMC 周期逻辑（5 维评分、三阶段权衡）**完全保留**，仅在硬限制前增加非农/CPI 事件分支。

---

## 三、P0 三层补丁

### 3.1 P0.1 数据层补丁

#### 3.1.1 FredCollector.SERIES 扩展

**文件**：[18-数据获取中心/data_center/collectors/macro/fred_collector.py](../../18-数据获取中心/data_center/collectors/macro/fred_collector.py#L26-L29)

**变更**：`SERIES` 元组追加三个序列：

```python
SERIES = (
    "FEDFUNDS", "RRPONTSYD", "DFII10", "T10YIE",           # 原有
    "M2NS", "M2SL", "WALCL", "CPIAUCSL", "PPIACO", "INDPRO", # 五维需求新增
    "EFFR",      # Effective Federal Funds Rate — 替代 hike_prob=0 兜底的真实利率
    "UNRATE",    # 失业率 — 非农数据的核心反向指标
    "DGS10",     # 10 年期国债收益率 — 跨资产验证维度
)
```

**理由**：
- `EFFR` 替代当前 `_score_real_rate()` 中 `BASE_RATE_MIDPOINT=3.625` 硬编码（[event_driven_strategy.py:253](./dreambuddy_evolution/engines/event_driven_strategy.py#L253)），用真实有效联邦基金利率
- `UNRATE` 是非农数据的核心反向指标（非农强→失业率降→加息预期升）
- `DGS10` 补全跨资产验证维度（原 SPEC §4.5.1 affected_assets 含 us10y）

#### 3.1.2 FedEventCollector 用 cme-fedwatch PyPI 包替换爬虫

**文件**：[18-数据获取中心/data_center/collectors/macro/fed_event_collector.py](../../18-数据获取中心/data_center/collectors/macro/fed_event_collector.py#L42-L129)

**变更**：`_fetch_fedwatch_from_investing()` 改为 `_fetch_fedwatch_from_cme()`，使用 `cme-fedwatch 0.2.1` PyPI 包：

```python
def _fetch_fedwatch_from_cme() -> dict:
    """从 CME FedWatch 官方数据采集下次会议概率。
    
    PyPI 包：cme-fedwatch 0.2.1
    接口：from cme_fedwatch import get_probabilities
    返回：{effr, current_target, target_source, trade_date, meetings:[{date, contract, probabilities:{...}}]}
    """
    try:
        from cme_fedwatch import get_probabilities
    except ImportError:
        logger.warning("[FedWatch] cme-fedwatch 包未安装，降级到 investing.com 爬虫")
        return _fetch_fedwatch_from_investing()  # 保留原爬虫作为降级路径
    
    try:
        data = get_probabilities("next")
    except Exception as e:
        logger.warning("[FedWatch] cme-fedwatch 调用失败，FAIL-OPEN 降级: %s", e)
        return _fetch_fedwatch_from_investing()
    
    if not data or "meetings" not in data or not data["meetings"]:
        return {}
    
    next_meeting = data["meetings"][0]
    probabilities = next_meeting.get("probabilities", {})
    
    effr = float(data.get("effr", 4.00))  # 当前有效联邦基金利率
    current_target = data.get("current_target", "4.00-4.25")
    
    # 解析 target 区间下限
    import re
    m = re.search(r"([\d.]+)", current_target)
    current_lower = float(m.group(1)) if m else 4.00
    
    hike_prob = 0.0
    cut_prob = 0.0
    hold_prob = 0.0
    
    for rate_range, prob in probabilities.items():
        m = re.search(r"([\d.]+)", rate_range)
        if m:
            rate_lower = float(m.group(1))
            if rate_lower > current_lower:
                hike_prob += float(prob) / 100.0  # probabilities 是百分比值
            elif rate_lower < current_lower:
                cut_prob += float(prob) / 100.0
            else:
                hold_prob += float(prob) / 100.0
    
    return {
        "hike_prob": round(hike_prob, 4),
        "cut_prob": round(cut_prob, 4),
        "hold_prob": round(hold_prob, 4),
        "meeting_date": next_meeting.get("date", ""),
        "target_rate": next_meeting.get("contract", ""),
        "effr": effr,                          # 新增字段
        "current_target": current_target,      # 新增字段
        "trade_date": data.get("trade_date", ""),  # 新增字段
    }
```

**新增字段**：`effr` / `current_target` / `trade_date`，供 `EventDrivenStrategy._score_real_rate()` 替代硬编码 `BASE_RATE_MIDPOINT`。

**降级策略**：cme-fedwatch 包未安装或调用失败时，回退到原 investing.com 爬虫路径（**保留 `_fetch_fedwatch_from_investing()` 不删除**）。

#### 3.1.3 UsEconomicCalendarCollector 追加 CESI 标准化

**文件**：[18-数据获取中心/data_center/collectors/macro/us_economic_calendar_collector.py](../../18-数据获取中心/data_center/collectors/macro/us_economic_calendar_collector.py#L208-L225)

**变更**：`fetch()` 方法在 `surprise = data["actual"] - data["forecast"]` 后追加 CESI 标准化：

```python
# CESI 标准化：Surprise = (Actual - Forecast) / σ_historical
# σ 维护：滚动窗口最近 12 次发布的 surprise 标准差
cesi = None
try:
    from data_center.collectors.macro.cesi_history import get_surprise_history, append_surprise
    history = get_surprise_history(indicator)  # 最近 12 次 surprise
    if len(history) >= 6:  # 至少 6 次才能算 σ
        sigma = float(np.std(history))
        if sigma > 0:
            cesi = round((data["actual"] - data["forecast"]) / sigma, 3)
    # 追加到历史
    append_surprise(indicator, data["actual"] - data["forecast"])
except Exception as e:
    logger.warning("[EconCal] CESI 计算失败，FAIL-OPEN 跳过: %s", e)
    cesi = None
```

**新模块**：`18-数据获取中心/data_center/collectors/macro/cesi_history.py`（轻量级 SQLite/JSON 滚动窗口，维护每个指标的最近 12 次 surprise 值）

**降级策略**：CESI 计算失败时 `cesi=None`，下游用 `surprise` 绝对值差兜底。

### 3.2 P0.2 事件层补丁

#### 3.2.1 解除 EventDrivenStrategy in_fomc_cycle 硬限制

**文件**：[23-四层闭环自进化交易架构/dreambuddy_evolution/engines/event_driven_strategy.py](./dreambuddy_evolution/engines/event_driven_strategy.py#L89-L98)

**变更**：将 L89-98 的硬限制改为分支判断：

```python
# 原：仅在 FOMC 周期内激活
if not event_ctx.get("in_fomc_cycle", False):
    return EventDrivenSignal(signal="neutral", ...)

# 新：FOMC 周期 OR 非农/CPI 事件窗口（CESI 触发）
in_fomc = event_ctx.get("in_fomc_cycle", False)
cesi = kline_data.get("cesi")  # 由 data_pipeline 注入
event_type = event_ctx.get("event_type", "")  # nfp/cpi/ppi/fomc

# CESI 触发阈值 ±1.5σ（参考记忆 VM-1790952663890 调研结论）
CESI_TRIGGER_THRESHOLD = 1.5

is_macro_event_active = (
    in_fomc
    or (cesi is not None and abs(cesi) >= CESI_TRIGGER_THRESHOLD)
    or event_type in ("nfp", "cpi", "ppi")  # 事件窗口内强制激活
)

if not is_macro_event_active:
    return EventDrivenSignal(
        signal="neutral",
        confidence=0.0,
        mode="none",
        scores={},
        event_phase=cycle_phase,
        reason="不在 FOMC 周期且无宏观事件触发",
    )
```

**新增字段**：`event_type`（nfp/cpi/ppi/fomc），由 `data_pipeline` 注入到 `event_context`。

#### 3.2.2 解除 PrimaryContradictionDetector in_fomc 硬限制

**文件**：[23-四层闭环自进化交易架构/dreambuddy_evolution/engines/primary_contradiction_detector.py](./dreambuddy_evolution/engines/primary_contradiction_detector.py#L149-L157)

**变更**：`_classify_primary()` 优先级 1 改为"FOMC 周期 OR CESI 触发"：

```python
def _classify_primary(
    self,
    kline_data: dict,
    event_ctx: dict,
    hike_prob: float | None,
    prob_trend: str,
) -> tuple[str, float]:
    """判定主要矛盾类型 + 强度。"""
    in_fomc = event_ctx.get("in_fomc_cycle", False)
    cesi = kline_data.get("cesi")
    event_type = event_ctx.get("event_type", "")
    
    # 优先级 1: FOMC 周期内 OR CESI 触发的加息预期变化
    macro_rate_triggered = (
        in_fomc
        or (cesi is not None and abs(cesi) >= 1.5 and event_type in ("nfp", "cpi", "ppi"))
    )
    
    if macro_rate_triggered and hike_prob is not None:
        p = float(hike_prob)
        trend_val = _PROB_TREND_VALUE.get(prob_trend, 0.0)
        # CESI 放大 intensity：|cesi| 越大，矛盾强度越高
        cesi_amplifier = min(abs(cesi) / 3.0, 0.3) if cesi is not None else 0.0
        intensity = min(p * 0.6 + abs(trend_val) * 0.4 + cesi_amplifier, 0.95)
        return "fomc_rate_decision", round(intensity, 3)
    
    # 优先级 2-4: 原逻辑保留（inflation_shock / credit_event / ai_capex_cycle）
    # ...
```

#### 3.2.3 注入 cme-fedwatch 真实 hike_prob 替代兜底

**文件**：[23-四层闭环自进化交易架构/dreambuddy_evolution/engines/event_driven_strategy.py](./dreambuddy_evolution/engines/event_driven_strategy.py) `_assess_forward_guidance()` 方法

**变更**：当 `hike_prob=0` 或 `None` 时，从 `kline_data["fedwatch"]` 读取真实概率，替代当前兜底返回 1.0 的逻辑（参考记忆 VM-1789631187004）：

```python
def _assess_forward_guidance(self, data: dict, event_ctx: dict) -> str:
    """评估前瞻指引方向。"""
    hike_prob = event_ctx.get("hike_prob")
    
    # 优先用真实 CME FedWatch 概率
    fedwatch = data.get("fedwatch") or {}
    real_hike_prob = fedwatch.get("hike_prob")
    effr = fedwatch.get("effr")
    
    if real_hike_prob is not None:
        hike_prob = real_hike_prob
    
    if hike_prob is None and effr is None:
        return ""  # 无数据，不评估前瞻指引
    
    # 用 effr 替代硬编码 BASE_RATE_MIDPOINT
    if effr is not None:
        try:
            if float(effr) >= 4.5:  # 高利率环境，加息空间有限
                return "dovish"
            elif float(effr) <= 3.5:  # 低利率环境，加息空间大
                return "hawkish"
        except (TypeError, ValueError):
            pass
    
    # 兜底逻辑（移除原来 hike_prob=0 返回 1.0 的硬编码）
    if hike_prob is None:
        return ""
    
    p = float(hike_prob)
    if p >= 0.7:
        return "hawkish"
    elif p <= 0.3:
        return "dovish"
    return "neutral"
```

### 3.3 P0.3 接线层补丁

#### 3.3.1 DataPipelineAdapter 注入宏观字段

**文件**：`23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/data_pipeline.py`（参考 [SPEC-数据管线打通与能力落地.md](./SPEC-数据管线打通与能力落地.md) §4.4）

**变更**：`assemble()` 方法注入以下字段到 kline_data 顶层：

| 字段 | 来源 | 说明 |
|------|------|------|
| `cpi_actual` | UsEconomicCalendarCollector("cpi") | CPI 实际值 |
| `cpi_expected` | UsEconomicCalendarCollector("cpi") | CPI 预期值 |
| `nfp_actual` | UsEconomicCalendarCollector("nfp") | 非农实际值 |
| `nfp_expected` | UsEconomicCalendarCollector("nfp") | 非农预期值 |
| `cesi` | UsEconomicCalendarCollector 计算 | CESI 标准化 surprise |
| `fedwatch` | FedEventCollector("fedwatch") | CME FedWatch 完整 dict（含 effr/hike_prob/meeting_date） |
| `effr` | FredCollector("EFFR") | 有效联邦基金利率（替代 BASE_RATE_MIDPOINT 硬编码） |
| `unrate` | FredCollector("UNRATE") | 失业率 |
| `dgs10` | FredCollector("DGS10") | 10 年期国债收益率 |
| `event_context.event_type` | 事件窗口计算 | nfp/cpi/ppi/fomc/none |
| `event_context.in_fomc_cycle` | FOMC 日历 | True/False（保留） |
| `event_context.hike_prob` | fedwatch.hike_prob | 真实概率（替代兜底） |

**事件窗口触发逻辑**（`event_context.event_type` 计算）：

```python
def _compute_event_type(self, kline_data: dict) -> str:
    """根据发布日期判断当前是否在事件窗口内（发布后 0-5 天）。"""
    # 从 econ_calendar 拿最近一次 nfp/cpi/ppi 的 release_date
    # 若 release_date 距今 ≤ 5 天，返回对应 event_type
    # FOMC 周期判断保留原逻辑
    today = datetime.now().date()
    for indicator in ("nfp", "cpi", "ppi"):
        rec = kline_data.get(f"{indicator}_release")
        if rec:
            try:
                release_date = datetime.strptime(rec["release_date"], "%Y-%m-%d").date()
                if 0 <= (today - release_date).days <= 5:
                    return indicator
            except (ValueError, KeyError):
                continue
    return "none"
```

---

## 四、任务拆分（TDD：RED-GREEN-REFACTOR）

### 任务 T1：FredCollector.SERIES 扩展（数据层）

**文件**：`18-数据获取中心/data_center/collectors/macro/fred_collector.py`

**RED**：在 `18-数据获取中心/tests/macro/test_fred_collector.py` 追加测试：

```python
def test_series_includes_new_indicators():
    """RED: 验证 FredCollector.SERIES 包含 EFFR/UNRATE/DGS10。"""
    from data_center.collectors.macro.fred_collector import FredCollector
    assert "EFFR" in FredCollector.SERIES
    assert "UNRATE" in FredCollector.SERIES
    assert "DGS10" in FredCollector.SERIES
```

**GREEN**：在 `SERIES` 元组追加 `"EFFR", "UNRATE", "DGS10"`。

**REFACTOR**：无（最小变更）。

**验收**：`pytest test_fred_collector.py::test_series_includes_new_indicators -v` 通过。

---

### 任务 T2：FedEventCollector 接入 cme-fedwatch（数据层）

**文件**：`18-数据获取中心/data_center/collectors/macro/fed_event_collector.py`

**RED**：在 `18-数据获取中心/tests/macro/test_fed_event_collector.py` 追加测试：

```python
def test_fedwatch_from_cme_returns_effr(monkeypatch):
    """RED: 验证 cme-fedwatch 调用返回 effr 字段。"""
    def mock_get_probabilities(meeting):
        return {
            "effr": 4.33,
            "current_target": "4.25-4.50",
            "trade_date": "2026-10-02",
            "meetings": [{"date": "2026-11-07", "contract": "NOV", "probabilities": {"4.25-4.50": 65.0, "4.50-4.75": 35.0}}],
        }
    
    import sys
    import types
    mock_module = types.ModuleType("cme_fedwatch")
    mock_module.get_probabilities = mock_get_probabilities
    monkeypatch.setitem(sys.modules, "cme_fedwatch", mock_module)
    
    from data_center.collectors.macro.fed_event_collector import _fetch_fedwatch_from_cme
    result = _fetch_fedwatch_from_cme()
    
    assert result["hike_prob"] == 0.35
    assert result["hold_prob"] == 0.65
    assert result["effr"] == 4.33
    assert result["current_target"] == "4.25-4.50"


def test_fedwatch_cme_fallback_to_investing(monkeypatch):
    """RED: 验证 cme-fedwatch 未安装时降级到 investing.com 爬虫。"""
    import sys
    # 模拟 cme_fedwatch 不存在
    monkeypatch.setitem(sys.modules, "cme_fedwatch", None)
    
    from data_center.collectors.macro.fed_event_collector import _fetch_fedwatch_from_cme
    # 应该降级到 _fetch_fedwatch_from_investing（可能返回空 dict，但不抛异常）
    result = _fetch_fedwatch_from_cme()
    assert isinstance(result, dict)
```

**GREEN**：实现 `_fetch_fedwatch_from_cme()`，保留 `_fetch_fedwatch_from_investing()` 作为降级路径，`FedEventCollector._fetch_fedwatch()` 改为调用 `_fetch_fedwatch_from_cme()`。

**REFACTOR**：将 hike/cut/hold 分类逻辑抽取为 `_classify_probabilities(probabilities, current_lower)` 私有方法，消除重复。

**验收**：两个测试通过；`cme-fedwatch` 加入 `requirements.txt`（`cme-fedwatch>=0.2.1`）。

---

### 任务 T3：UsEconomicCalendarCollector 追加 CESI 标准化（数据层）

**文件**：`18-数据获取中心/data_center/collectors/macro/us_economic_calendar_collector.py` + 新建 `cesi_history.py`

**RED**：在 `18-数据获取中心/tests/macro/test_us_economic_calendar_collector.py` 追加测试：

```python
def test_cesi_calculation_with_history(monkeypatch):
    """RED: 验证 CESI = (actual - forecast) / σ_history。"""
    # 模拟历史 surprise: [0.1, -0.1, 0.2, -0.2, 0.3, -0.3, 0.4, -0.4, 0.5, -0.5, 0.6, -0.6]
    # σ = std([0.1, -0.1, ...]) ≈ 0.335
    from data_center.collectors.macro import cesi_history
    monkeypatch.setattr(cesi_history, "get_surprise_history", lambda ind: [0.1, -0.1, 0.2, -0.2, 0.3, -0.3, 0.4, -0.4, 0.5, -0.5, 0.6, -0.6])
    
    from data_center.collectors.macro.us_economic_calendar_collector import UsEconomicCalendarCollector
    collector = UsEconomicCalendarCollector()
    # actual=4.0, forecast=3.5 → surprise=0.5 → cesi=0.5/0.335≈1.49
    # mock _fetch_indicator 返回 actual=4.0, forecast=3.5
    monkeypatch.setattr(collector, "_fetch_indicator", lambda ind: {"actual": 4.0, "forecast": 3.5, "previous": 3.4, "release_date": "2026-10-02"})
    
    records = collector.fetch({"indicator": "cpi"})
    assert len(records) == 1
    assert "cesi" in records[0].metrics
    assert abs(records[0].metrics["cesi"] - 1.49) < 0.1


def test_cesi_none_when_history_insufficient(monkeypatch):
    """RED: 历史不足 6 次时 cesi=None。"""
    from data_center.collectors.macro import cesi_history
    monkeypatch.setattr(cesi_history, "get_surprise_history", lambda ind: [0.1, 0.2])
    
    from data_center.collectors.macro.us_economic_calendar_collector import UsEconomicCalendarCollector
    collector = UsEconomicCalendarCollector()
    monkeypatch.setattr(collector, "_fetch_indicator", lambda ind: {"actual": 4.0, "forecast": 3.5, "previous": 3.4, "release_date": "2026-10-02"})
    
    records = collector.fetch({"indicator": "cpi"})
    assert records[0].metrics.get("cesi") is None
```

**GREEN**：
1. 新建 `cesi_history.py`，实现 `get_surprise_history(indicator)` 和 `append_surprise(indicator, value)`（SQLite 滚动窗口，最近 12 次）
2. 在 `UsEconomicCalendarCollector.fetch()` 中追加 CESI 计算逻辑

**REFACTOR**：CESI 计算逻辑抽取为 `_compute_cesi(indicator, actual, forecast)` 私有方法。

**验收**：两个测试通过；CESI 字段出现在 DataRecord.metrics 中。

---

### 任务 T4：解除 EventDrivenStrategy in_fomc_cycle 硬限制（事件层）

**文件**：`23-四层闭环自进化交易架构/dreambuddy_evolution/engines/event_driven_strategy.py`

**RED**：在 `23-四层闭环自进化交易架构/tests/test_event_driven_strategy.py` 追加测试：

```python
def test_evaluate_activates_on_cesi_trigger():
    """RED: CESI ≥ 1.5σ 时即使 in_fomc_cycle=False 也应激活。"""
    from dreambuddy_evolution.engines.event_driven_strategy import EventDrivenStrategy
    
    strategy = EventDrivenStrategy()
    kline_data = {
        "cpi_actual": 4.0,
        "cpi_expected": 3.5,
        "cesi": 2.0,  # 强超预期
        "event_context": {
            "in_fomc_cycle": False,  # 不在 FOMC 周期
            "cycle_phase": "neutral",
            "event_type": "cpi",
            "hike_prob": 0.65,
        },
    }
    signal = strategy.evaluate(kline_data)
    # 不应返回 neutral + "不在 FOMC 周期内"
    assert signal.signal != "neutral" or signal.reason != "不在 FOMC 周期内"
    assert signal.confidence > 0.0


def test_evaluate_neutral_when_no_macro_event():
    """RED: 无 FOMC 周期且无 CESI 触发时返回中性。"""
    from dreambuddy_evolution.engines.event_driven_strategy import EventDrivenStrategy
    
    strategy = EventDrivenStrategy()
    kline_data = {
        "event_context": {
            "in_fomc_cycle": False,
            "cycle_phase": "neutral",
            "event_type": "none",
        },
    }
    signal = strategy.evaluate(kline_data)
    assert signal.signal == "neutral"
    assert "不在 FOMC 周期且无宏观事件触发" in signal.reason
```

**GREEN**：将 L89-98 硬限制替换为 §3.2.1 的分支判断逻辑。

**REFACTOR**：将 `is_macro_event_active` 计算抽取为 `_is_macro_event_active(event_ctx, kline_data)` 私有方法。

**验收**：两个测试通过；原 FOMC 周期测试（`test_evaluate_*_in_fomc_cycle`）全部回归通过。

---

### 任务 T5：解除 PrimaryContradictionDetector in_fomc 硬限制（事件层）

**文件**：`23-四层闭环自进化交易架构/dreambuddy_evolution/engines/primary_contradiction_detector.py`

**RED**：在 `23-四层闭环自进化交易架构/dreambuddy_evolution/tests/test_primary_contradiction_detector.py` 追加测试：

```python
def test_detect_fomc_rate_decision_on_cesi_trigger():
    """RED: CESI 触发的非 FOMC 事件应识别为 fomc_rate_decision 主要矛盾。"""
    from dreambuddy_evolution.engines.primary_contradiction_detector import PrimaryContradictionDetector
    
    detector = PrimaryContradictionDetector()
    kline_data = {
        "cesi": 2.0,  # 强超预期
        "event_context": {
            "in_fomc_cycle": False,  # 不在 FOMC 周期
            "event_type": "cpi",
            "hike_prob": 0.65,
            "probability_trend": "rising",
        },
    }
    info = detector.detect(kline_data)
    assert info.primary == "fomc_rate_decision"
    assert info.intensity > 0.3  # CESI 放大后强度更高


def test_detect_unknown_when_no_macro_trigger():
    """RED: 无 FOMC 周期且无 CESI 触发时 primary=unknown。"""
    from dreambuddy_evolution.engines.primary_contradiction_detector import PrimaryContradictionDetector
    
    detector = PrimaryContradictionDetector()
    kline_data = {
        "event_context": {
            "in_fomc_cycle": False,
            "event_type": "none",
        },
    }
    info = detector.detect(kline_data)
    assert info.primary == "unknown"
    assert info.intensity == 0.0
```

**GREEN**：将 `_classify_primary()` 优先级 1 替换为 §3.2.2 的 `macro_rate_triggered` 逻辑。

**REFACTOR**：CESI 放大因子计算抽取为 `_compute_cesi_amplifier(cesi)` 私有方法。

**验收**：两个测试通过；原 fomc_rate_decision 测试回归通过。

---

### 任务 T6：注入 cme-fedwatch 真实 hike_prob 替代兜底（事件层）

**文件**：`23-四层闭环自进化交易架构/dreambuddy_evolution/engines/event_driven_strategy.py` `_assess_forward_guidance()`

**RED**：在 `tests/test_event_driven_strategy.py` 追加测试：

```python
def test_assess_forward_guidance_uses_real_fedwatch():
    """RED: hike_prob=0 时应从 fedwatch 读取真实概率，不返回兜底 1.0。"""
    from dreambuddy_evolution.engines.event_driven_strategy import EventDrivenStrategy
    
    strategy = EventDrivenStrategy()
    kline_data = {
        "fedwatch": {
            "hike_prob": 0.75,
            "effr": 4.33,
            "current_target": "4.25-4.50",
        },
        "event_context": {
            "in_fomc_cycle": True,
            "cycle_phase": "expectation_build",
            "hike_prob": 0.0,  # event_ctx 兜底 0，应被 fedwatch 真实值替代
        },
    }
    # 调用 _assess_forward_guidance
    fg = strategy._assess_forward_guidance(kline_data, kline_data["event_context"])
    assert fg == "hawkish"  # 0.75 >= 0.7


def test_assess_forward_guidance_dovish_when_low_effr():
    """RED: effr <= 3.5 时应返回 dovish（低利率环境）。"""
    from dreambuddy_evolution.engines.event_driven_strategy import EventDrivenStrategy
    
    strategy = EventDrivenStrategy()
    kline_data = {
        "fedwatch": {"hike_prob": 0.1, "effr": 3.25, "current_target": "3.00-3.25"},
        "event_context": {"in_fomc_cycle": True, "cycle_phase": "expectation_build", "hike_prob": 0.1},
    }
    fg = strategy._assess_forward_guidance(kline_data, kline_data["event_context"])
    assert fg == "dovish"
```

**GREEN**：实现 §3.2.3 的逻辑，移除原来 hike_prob=0 返回 1.0 的硬编码。

**REFACTOR**：前瞻指引判定逻辑抽取为独立的 `_ForwardGuidanceClassifier` 类（可选，若复杂度提升）。

**验收**：两个测试通过；原前瞻指引测试回归通过。

---

### 任务 T7：DataPipelineAdapter 注入宏观字段（接线层）

**文件**：`23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/data_pipeline.py`

**RED**：在 `23-四层闭环自进化交易架构/dreambuddy_evolution/tests/test_data_pipeline.py` 追加测试：

```python
def test_assemble_injects_macro_fields():
    """RED: assemble() 应注入 cpi_actual/cesi/fedwatch/effr 等宏观字段。"""
    from dreambuddy_evolution.adapters.data_pipeline import DataPipelineAdapter
    
    adapter = DataPipelineAdapter.__new__(DataPipelineAdapter)
    # mock 所有 collector
    adapter._fred = MockFred()
    adapter._econ_cal = MockEconCal()
    adapter._fed_event = MockFedEvent()
    
    result = adapter.assemble(symbol="BTC", inst_id="BTC-USDT-SWAP")
    
    assert "cpi_actual" in result
    assert "cpi_expected" in result
    assert "cesi" in result
    assert "fedwatch" in result
    assert "effr" in result
    assert "unrate" in result
    assert "dgs10" in result
    assert "event_type" in result["event_context"]


def test_assemble_event_type_within_5_days():
    """RED: 最近一次 CPI 发布在 5 天内时 event_type=cpi。"""
    # mock econ_cal 返回 release_date=today-2
    ...
```

**GREEN**：实现 §3.3.1 的字段注入 + `_compute_event_type()` 方法。

**REFACTOR**：字段注入逻辑按指标分组（fred/econ_cal/fed_event），每组用独立私有方法。

**验收**：两个测试通过；`assemble()` 性能 < 1s（参考 SPEC-数据管线打通 §4.6）。

---

## 五、FAIL-OPEN 风险评估

| 风险点 | 触发条件 | FAIL-OPEN 策略 | 影响范围 |
|--------|----------|----------------|----------|
| cme-fedwatch 包未安装 | PyPI 包未在 requirements.txt | 降级到 investing.com 爬虫 | hike_prob 仍可获取，但无 effr 字段 |
| cme-fedwatch 调用失败（网络/CME 限流） | 网络异常或 429 | 降级到 investing.com 爬虫 | 同上 |
| CESI 历史不足 6 次 | 冷启动期 | `cesi=None`，下游用 `surprise` 绝对值差兜底 | CESI 触发不生效，但 FOMC 周期逻辑保留 |
| FRED API Key 缺失 | 无 `FRED_API_KEY` 环境变量 | FredCollector 返回空列表 | effr/unrate/dgs10 字段缺失，硬编码兜底 |
| UsEconomicCalendarCollector 爬虫失败 | Trading Economics 反爬 | 返回空列表 | cpi_actual/cpi_expected 缺失，_score_real_rate 返回 0.5 |
| 事件窗口计算失败 | release_date 解析异常 | event_type="none"，降级到 in_fomc_cycle 判断 | 非 FOMC 周期事件仍会被错过（与现状一致，无回退风险） |

**关键原则**：所有 FAIL-OPEN 降级路径**不得比现状更差**——任何数据缺失都返回中性/默认值，不抛异常。

---

## 六、验收标准（量化）

### 6.1 单元测试

- [ ] T1: `test_series_includes_new_indicators` 通过
- [ ] T2: `test_fedwatch_from_cme_returns_effr` + `test_fedwatch_cme_fallback_to_investing` 通过
- [ ] T3: `test_cesi_calculation_with_history` + `test_cesi_none_when_history_insufficient` 通过
- [ ] T4: `test_evaluate_activates_on_cesi_trigger` + `test_evaluate_neutral_when_no_macro_event` 通过
- [ ] T5: `test_detect_fomc_rate_decision_on_cesi_trigger` + `test_detect_unknown_when_no_macro_trigger` 通过
- [ ] T6: `test_assess_forward_guidance_uses_real_fedwatch` + `test_assess_forward_guidance_dovish_when_low_effr` 通过
- [ ] T7: `test_assemble_injects_macro_fields` + `test_assemble_event_type_within_5_days` 通过

### 6.2 回归测试

- [ ] 原有 `test_event_driven_strategy.py` 全部测试通过（FOMC 周期逻辑不破坏）
- [ ] 原有 `test_primary_contradiction_detector.py` 全部测试通过
- [ ] 原有 `test_fed_event_collector.py` 全部测试通过
- [ ] 原有 `test_data_pipeline.py` 全部测试通过
- [ ] `backtest_macro_event.py` 端到端回测脚本可运行（60 天 FOMC 周期数据）

### 6.3 端到端验收

- [ ] 模拟 2026-10-02 场景：注入 cesi=-2.0（非农大幅低于预期，降低加息预期）+ in_fomc_cycle=False，验证 EventDrivenStrategy 返回 `signal="long"`（宏观反向风险被识别）
- [ ] 模拟现状修复后：BCRM2.0 通过 polling_trader 事件桥接（**P1 范围**，本 SPEC 不要求）

### 6.4 性能验收

- [ ] `DataPipelineAdapter.assemble()` 单次调用 < 1s（参考 SPEC-数据管线打通 §4.6）
- [ ] `EventDrivenStrategy.evaluate()` 单次调用 < 50ms

---

## 七、依赖与前置条件

### 7.1 PyPI 依赖

```txt
# requirements.txt 追加
cme-fedwatch>=0.2.1
```

### 7.2 环境变量

- `FRED_API_KEY`（已有，FredCollector 必需）

### 7.3 数据库

- `data_center.db` 已有 `macro_data` 表（FredCollector 写入路径）
- `cesi_history.py` 新建轻量级 SQLite 或 JSON 文件：`4-MEMORY/data/cesi_history.db`（最近 12 次 surprise 滚动窗口）

### 7.4 配置开关

本 SPEC 修改**不引入新的模块化开关**，复用现有：
- `enable_contradiction_driven_layer`（已有）
- `enable_primary_contradiction_detector`（已有）
- `enable_event_dominance`（已有）

---

## 八、回滚方案

### 8.1 单任务回滚

每个任务（T1-T7）独立，可单独回滚（git revert 单个 commit）。

### 8.2 整体回滚

若 P0 整体上线后发现问题：
1. `git revert` 所有 P0 commit
2. `EventDrivenStrategy` 自动恢复 `in_fomc_cycle=False` 硬限制
3. `FedEventCollector` 自动恢复 investing.com 爬虫（cme-fedwatch 调用路径被跳过）
4. `FredCollector.SERIES` 自动恢复原有 10 个序列（EFFR/UNRATE/DGS10 被移除，不影响现有逻辑）

### 8.3 紧急熔断

若 BCRM2.0 在 P0 上线后仍逆势开空单：
- 临时关闭 `enable_contradiction_driven_layer=False` + `enable_event_dominance=False`（已有开关）
- EventDrivenStrategy 与 PrimaryContradictionDetector 自动返回中性默认

---

## 九、后续 P1 范围（不在本 SPEC 内）

1. **BCRM2.0 事件桥接升级**：`polling_trader.py:223-260` 从只读 odaily_newsflash 币种快讯情感，升级为读取 EventDrivenStrategy 输出 + CESI 触发信号
2. **战略层注入 BCRM2.0**：开启 `enable_strategy_layer=True` + `enable_five_domain=True`，将 strategic_mapper war_state 注入 BCRM2.0
3. **Citi ESI 接入**：调研 Citi Economic Surprise Index API，替代自维护 CESI 滚动窗口
4. **gs-quant / NautilusTrader 接入**：原 SPEC v2.0 §7 已调研，待 P0 验证后落地

---

## 十、文档同步硬约束

本 SPEC 涉及新增 1 个文件（`cesi_history.py`）+ 修改 6 个文件，按 CLAUDE.md 硬约束：
- 实施完成后必须调用 `dream-doc-sync-workflow` skill 执行 7 步文档索引同步
- `record` 经验时 `tags` 必须包含 `doc-sync`
- 触发 `cognitive_mcp_server.py` TAG_HOOKS 自动返回 `triggered_skills: ["dream-doc-sync-workflow"]`

---

## 附录 A：调研来源

### A.1 传统金融方法论
1. CME FedWatch 二叉树定价模型 — https://www.cmegroup.com/portals/economic-research/fedwatch.html
2. Taylor Rule — Taylor (1993), "Discretion versus policy rules in practice"
3. 高盛 Mericle 模型 — GS Economics Research
4. Citi ESI — Citi Economic Surprise Index
5. GDPNow — Atlanta Fed https://www.frbatlanta.org/cqer/research/gdpnow
6. Tealbook — FOMC Tealbook forecasts
7. ED 期货 + OIS — Eurodollar futures + Overnight Index Swap

### A.2 GitHub 项目
1. tjdwls101010/CME-FedWatch — PyPI: cme-fedwatch 0.2.1
2. pydata/pandas-datareader — `pdr.get_data_fred("GS10")`
3. joce/fredq — `fredq.Series("DGS10").observations()`

### A.3 本仓库相关文件
- 原 SPEC: [SPEC-美国宏观事件驱动交易策略.md](./SPEC-美国宏观事件驱动交易策略.md) v2.0
- 数据管线 SPEC: [SPEC-数据管线打通与能力落地.md](./SPEC-数据管线打通与能力落地.md)
- EventDrivenStrategy: [event_driven_strategy.py](./dreambuddy_evolution/engines/event_driven_strategy.py)
- PrimaryContradictionDetector: [primary_contradiction_detector.py](./dreambuddy_evolution/engines/primary_contradiction_detector.py)
- FredCollector: [fred_collector.py](../../18-数据获取中心/data_center/collectors/macro/fred_collector.py)
- FedEventCollector: [fed_event_collector.py](../../18-数据获取中心/data_center/collectors/macro/fed_event_collector.py)
- UsEconomicCalendarCollector: [us_economic_calendar_collector.py](../../18-数据获取中心/data_center/collectors/macro/us_economic_calendar_collector.py)
- 认知记忆: VM-1790952663890-dca3391e（调研结论）、VM-1789631187004（hike_prob=0 兜底反模式）

