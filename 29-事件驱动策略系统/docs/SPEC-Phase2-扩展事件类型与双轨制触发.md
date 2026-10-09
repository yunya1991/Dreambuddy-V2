# SPEC-Phase2 — 扩展事件类型与双轨制触发

> **版本**：v1.1 draft（同行评审修订版） | **日期**：2026-10-09
> **关联文档**：TECHNICAL_DESIGN.md v1.0 | SPEC-事件驱动策略独立化 v1.2
> **前置调研**：Phase 1 可行性调研（SEC RSS / CoinMarketCal / federalreserve.gov）
> **v1.1 修订记录**（基于同行评审 4 Major + 3 Minor）：
> - M1: fed_speech 统一走轨道 B（EventTriggerSink），固定周期用 scheduled 队列预注入，消除双轨路由歧义
> - M2: SEC RSS 去重从仅 dc:creator 升级为三层（dc:creator + 标题 Jaccard + 24h 窗口 + 实体名匹配）
> - M3: tech_upgrade direction 从 neutral 改为动态判定（升级前价格趋势 + 社区情绪）
> - M4: 半衰期参数全部标注为「经验假设 v0，待回测验证后校准」
> - m1: GeneralEventWindowTracker 从 3 阶段升级为 5 阶段
> - m2: congressional_hearing 增加数据源快速验证项
> - m3: CoinMarketCal 增加 rate limit 标注

## 1. 背景与目标

### 1.1 现状

当前事件驱动策略仅支持 4 种 event_type：`fomc / nfp / cpi / ppi`，全部是「窗口预演型」——事件日期已知，EventWindowTracker 提前 N 天进入 pre_event 阶段。遗漏了四类对加密/黄金市场影响显著的事件：

| 新 event_type | 场景 | 影响标的 | 数据源 |
|---|---|---|---|
| `tech_upgrade` | 硬分叉 / 协议升级 / 主网上线 | BTC/ETH/SOL 等 | CoinMarketCal API |
| `fed_speech` | 主席讲话 / 半年度证词 / Jackson Hole | 黄金/加密 | federalreserve.gov HTML |
| `sec_deadline` | SEC 执法行动 / 加密政策提案 | 加密板块 | SEC RSS |
| `congressional_hearing` | 国会听证会 / 加密监管听证 | 加密/金融 | senate.gov / house.gov |

### 1.2 核心设计挑战

四类新事件存在**两种根本不同的触发语义**：

- **窗口预演型**（tech_upgrade / congressional_hearing）：事件日期提前已知，市场提前 N 天消化 → 适用 EventWindowTracker 的 5 阶段模型
- **突发触发型**（sec_deadline / fed_speech）：发布即推送，无 pre_event 阶段 → 走 EventTriggerSink

> **v1.1 修订（M1）**：fed_speech 统一走轨道 B（EventTriggerSink）。固定周期讲话（半年度 MPR 证词、Jackson Hole）通过 collector 提前注入 EventTriggerSink 的 **scheduled 队列**预触发，临时讲话发布即触发。消除 v1.0 中 fed_speech 跨双轨的路由歧义。

### 1.3 设计目标

1. 引入**双轨制架构**：轨道 A 扩展 EventWindowTracker 支持窗口预演型新事件；轨道 B 新建 EventTriggerSink 处理突发触发型事件
2. 扩展 `VALID_EVENT_TYPES` 枚举至 8 种（+none）
3. 新增 3 个 Collector 接入 data_pipeline
4. 保持 FAIL-OPEN：新数据源故障不影响现有策略链路
5. 落地优先级：`tech_upgrade`（数据最成熟）→ `fed_speech` → `sec_deadline` → `congressional_hearing`

---

## 2. 双轨制架构总览

```
                    ┌─────────────────────────────────────┐
                    │        data_pipeline.assemble()       │
                    │   注入 event_context 到 kline_data    │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
              ┌─────▼─────┐                ┌──────▼──────┐
              │  轨道 A   │                │   轨道 B    │
              │ EventWindow │                │EventTrigger │
              │  Tracker    │                │   Sink      │
              │ (窗口预演)  │                │ (突发触发)  │
              └─────┬─────┘                └──────┬──────┘
                    │                             │
     event_type:                                  │
     fomc/nfp/cpi/ppi                             │
     tech_upgrade                                │
     congressional_hearing                       │
                    │                             │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │ EventDrivenStrategy  │
                    │    .evaluate()       │
                    └─────────────────────┘
```

### 2.1 轨道划分

| event_type | 轨道 | 触发语义 | 窗口模型 |
|---|---|---|---|
| `fomc` | A | 窗口预演 | 6 阶段（现有，概率模型） |
| `nfp` / `cpi` / `ppi` | A | 窗口预演 | 简化 3 阶段（现有） |
| `tech_upgrade` | A | 窗口预演 | 5 阶段（短窗口，±3 天） |
| `congressional_hearing` | A | 窗口预演 | 5 阶段（中窗口，±7 天） |
| `sec_deadline` | B | 突发触发 | 无 pre_event，直接 event → post_event |
| `fed_speech` | B | 突发触发（含 scheduled 队列预注入） | 无 pre_event，event → post_event |

> **v1.1 修订（M1）**：fed_speech 不再区分 is_scheduled 走双轨。所有 fed_speech 统一走轨道 B（EventTriggerSink）：固定周期讲话由 collector 提前 N 天写入 scheduled 队列，到达 event_date 时进入 event 阶段；临时讲话发布即触发进入 event 阶段。data_pipeline 路由无需判断 is_scheduled。

---

## 3. 轨道 A：EventWindowTracker 扩展

### 3.1 设计方案：GeneralEventWindowTracker

新建抽象基类 `BaseEventWindowTracker`，现有 FOMC 逻辑保留为子类 `FOMCEventWindowTracker`，新增 `GeneralEventWindowTracker` 处理日程型事件。

```
BaseEventWindowTracker (抽象基类)
├── FOMCEventWindowTracker (现有 EventWindowTracker 逻辑，改名保留)
│   └── 6 阶段 + 概率模型（hike_prob/cut_prob/dominant_direction）
└── GeneralEventWindowTracker (新)
    ├── 参数: event_date, event_type, half_life_days
    ├── 窗口: pre_event(half_life×3) / event(当天) / post_event(half_life×3)
    └── 不依赖 hike_prob；direction 由事件语义映射
```

### 3.2 GeneralEventWindowTracker 接口契约

```python
class GeneralEventWindowTracker(BaseEventWindowTracker):
    """通用日程型事件窗口追踪器（不依赖概率模型）。"""

    # 按 event_type 的半衰期（天）—— 决定窗口大小
    # ⚠️ v1.1 修订（M4）：以下参数均为经验假设 v0，待回测验证后校准
    HALF_LIFE = {
        "tech_upgrade": 1.0,           # 经验假设：硬分叉影响较短（窗口±3天）
        "congressional_hearing": 2.5,  # 经验假设：听证会影响中等（窗口±7天）
    }

    # 事件方向语义映射
    # ⚠️ v1.1 修订（M3）：tech_upgrade 不再固定 neutral，改为动态判定
    # 判定逻辑见 §6.1 CoinMarketCalCollector direction 计算
    DIRECTION_MAP = {
        "congressional_hearing": "neutral",  # 听证会本身中性，方向由内容决定
    }

    def get_context(
        self,
        event_date: datetime | None = None,
        event_type: str = "none",
        now: datetime | None = None,
        event_direction: str = "neutral",  # v1.1 新增：collector 预计算的方向
    ) -> dict[str, Any]:
        """
        通用事件窗口判定。

        Args:
            event_date: 下次事件时间
            event_type: tech_upgrade / congressional_hearing
            now: 锚定时间
            event_direction: collector 预计算的方向（long/short/neutral），写入 dominant_direction

        Returns event_context dict（与 FOMCEventWindowTracker 输出 schema 一致）:
            cycle_phase, event_window, in_event_cycle,
            days_to_event, days_since_event,
            dominant_direction, half_life, raw
        """
```

### 3.3 阶段判定逻辑（v1.1 m1：5 阶段）

> **v1.1 修订（m1）**：从 3 阶段升级为 5 阶段，保留预期递进信息（类比 FOMC 的 build→rise→jump→digest），但缩短尺度以适配短窗口事件。

| 条件 | cycle_phase | event_window | 说明 |
|---|---|---|---|
| days_to ≤ 0 且 days_since ≤ half_life×3 | event | event | 事件当天 |
| 0 < days_since ≤ half_life×3 | post_event | post_event | 消化阶段 |
| 0 < days_to ≤ half_life | expectation_digest | pre_event | 预期消化（前 1×τ） |
| half_life < days_to ≤ half_life×2 | expectation_rise | pre_event | 预期升温（前 2×τ） |
| half_life×2 < days_to ≤ half_life×3 | expectation_build | pre_event | 预期构建（前 3×τ） |
| 其他 | neutral | none | 窗口外 |

> 5 阶段的 days_to 阈值按 half_life 动态伸缩：tech_upgrade（τ=1）→ 窗口 ±3 天；congressional_hearing（τ=2.5）→ 窗口 ±7.5 天。

### 3.4 向后兼容

- `EventWindowTracker` 类名保留为 `FOMCEventWindowTracker` 的别名（避免现有 import 断裂）
- data_pipeline.assemble() 优先检测 event_type：FOMC 系列走 `FOMCEventWindowTracker`，其余走 `GeneralEventWindowTracker`
- 现有 get_context() 签名不变

---

## 4. 轨道 B：EventTriggerSink 新建

### 4.1 设计定位

EventTriggerSink 处理「发布即触发」的突发型事件（sec_deadline / fed_speech）。不预演窗口，在事件发布当天直接标记 event 阶段，后续进入 post_event 衰减。

**v1.1 修订（M1）**：增加 **scheduled 队列**——固定周期事件（如 Fed 半年度证词、Jackson Hole）由 collector 提前 N 天写入 scheduled 队列，到达 event_date 时自动激活进入 event 阶段。这样 fed_speech 统一走轨道 B，消除跨双轨路由歧义。

### 4.2 接口契约

```python
class EventTriggerSink:
    """突发型事件触发器（sec_deadline / fed_speech）。

    监听 collector 推送的事件，在发布当天标记 event 阶段，
    后续按半衰期衰减进入 post_event。
    支持 scheduled 队列：固定周期事件提前写入，到达 event_date 自动激活。
    """

    # 半衰期（天）—— 经验假设 v0，待回测验证后校准（M4）
    HALF_LIFE = {
        "sec_deadline": 1.5,   # 经验假设：SEC 执法影响中等
        "fed_speech": 2.0,     # 经验假设：Fed 讲话影响中等
    }

    def consume(self, event: EventRecord) -> None:
        """接收突发事件，写入触发记录。

        event 字段:
            event_type, title, direction, trigger_time,
            is_scheduled, event_date（scheduled 事件用）
        """

    def consume_scheduled(self, event: EventRecord) -> None:
        """v1.1 新增（M1）：写入 scheduled 队列，到达 event_date 时自动激活。"""

    def get_context(
        self,
        event_type: str = "none",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """
        获取最近触发的突发事件上下文。

        优先级:
            1. scheduled 队列中 event_date == now 的事件 → event 阶段
            2. 已触发且在半衰期窗口内的事件 → event/post_event 阶段
            3. 无 → neutral

        Returns:
            cycle_phase: "event" / "post_event" / "neutral"
            event_window: "event" / "post_event" / "none"
            in_event_cycle: bool
            days_since_event: int | None
            dominant_direction: str
            half_life: float
            raw: dict
        """

    def cleanup(self) -> None:
        """清理过期触发记录（半衰期窗口外的记录）。由 scheduler 每小时调用。"""
```

### 4.3 触发记录存储

- 使用内存 ring buffer（最近 100 条触发记录）+ SQLite 持久化
- 表名：`event_trigger_log`（symbol, event_type, trigger_time, event_date, direction, strength, expired_at, is_scheduled）
- 查询：按 event_type 取最近一条，判断是否在半衰期窗口内
- **清理策略**：`cleanup()` 删除 `expired_at < now` 的记录，由 scheduler 每小时调用，防止堆积

### 4.4 事件方向映射

突发事件的方向由事件内容语义决定，collector 采集时标注：

| 事件 | direction 判定逻辑 |
|---|---|
| SEC 执法（针对某项目） | short（该项目利空） |
| SEC 加密政策提案（利好） | long（行业利好） |
| Fed 鹰派讲话 | short |
| Fed 鸽派讲话 | long |

> direction 由 collector 的 NLP / 关键词匹配初步标注，EventDrivenStrategy 最终由市场反应（resilience_score）修正。

### 4.5 fed_speech scheduled 队列机制（M1）

```
FedSpeechCollector.fetch()
    → 识别固定周期讲话（MPR 证词 / Jackson Hole）
    → 调用 EventTriggerSink.consume_scheduled(event)
    → event_date 到达时自动激活进入 event 阶段

FedSpeechCollector.fetch()
    → 识别临时讲话（speeches.htm 新发布）
    → 调用 EventTriggerSink.consume(event)
    → 立即进入 event 阶段
```

> 同一天多个 fed_speech（固定+临时）按 trigger_time 取最近一条，direction 取最新。

---

## 5. event_type 枚举扩展

### 5.1 VALID_EVENT_TYPES 扩展

```python
# event_driven_strategy.py
VALID_EVENT_TYPES = (
    "fomc", "nfp", "cpi", "ppi",                          # 现有
    "tech_upgrade", "fed_speech",                          # 新增 Phase 2
    "sec_deadline", "congressional_hearing",               # 新增 Phase 2
    "none",
)
```

### 5.2 EVENT_HALF_LIFE 扩展

```python
# ⚠️ v1.1 修订（M4）：新增 4 个半衰期均为经验假设 v0，待回测验证后校准
# 参考：FOMC=3.0 / CPI=2.0 有 Smales 黄金 VAR-GARCH 论文支撑
EVENT_HALF_LIFE = {
    "fomc": 3.0,
    "cpi": 2.0,
    "nfp": 1.5,
    "ppi": 1.0,
    "tech_upgrade": 1.0,          # 经验假设 v0
    "fed_speech": 2.0,            # 经验假设 v0
    "sec_deadline": 1.5,          # 经验假设 v0
    "congressional_hearing": 2.5, # 经验假设 v0
    "none": 0.0,
}
```

### 5.3 MACRO_EVENT_TYPES 扩展

```python
MACRO_EVENT_TYPES = ("nfp", "cpi", "ppi", "fed_speech")
# fed_speech 实质影响加息预期，加入强制激活列表
```

### 5.4 PHASE_THRESHOLDS 扩展

现有阶段阈值表（pre_event/event/repricing/neutral）对全部 event_type 通用，无需新增。但新增 tech_upgrade 的保守性调整：

```python
# tech_upgrade 窗口短、波动大，pre_event 更保守
PHASE_THRESHOLDS_BY_EVENT = {
    "tech_upgrade": {
        "pre_event": {"long": 0.75, "short": 0.25},  # 比通用更保守
        "event": {"long": 0.60, "short": 0.40},
        "post_event": {"long": 0.65, "short": 0.35},
    }
}
# 默认回退 PHASE_THRESHOLDS（现有）
```

### 5.5 PHASE_POSITION_MULT 扩展

```python
PHASE_POSITION_MULT = {
    # ... 现有 ...
    "post_event": 1.0,  # 新增：GeneralEventWindowTracker 的 post_event 阶段
}
```

---

## 6. Collector 设计

### 6.1 CoinMarketCalCollector（tech_upgrade）

```
路径: 18-数据获取中心/data_center/collectors/macro/coinmarketcal_collector.py
source: "coinmarketcal"
category: "protocol"  # DataRecord 契约合法值，sub_category=tech_upgrade
```

**数据源**：CoinMarketCal RESTful API（[coinmarketcal.com/en/api](https://coinmarketcal.com/en/api)）
- 免费档：7 天前瞻 + 基础数据
- 请求头需 API Key（`x-api-key` 或 query param `api_key`）
- **v1.1 修订（m3）Rate Limit**：免费档约 10-30 calls/min，6 小时调度（单次批量拉取 7 天）远低于限流，安全。如出现 429 需等 60s 重试。

**接口**：

```python
class CoinMarketCalCollector(BaseCollector):
    source = "coinmarketcal"
    category = "event"

    def fetch(self, params: dict) -> list[DataRecord]:
        """
        采集未来 N 天的加密技术升级事件。

        params:
            days_ahead: int = 7  # 前瞻天数
            coins: list[str] | None = None  # 筛选币种

        返回 DataRecord 列表，每条含:
            events: [{title, coin, date_event, category, percentage, source, proof}
            metrics: {event_type: "tech_upgrade",
                      direction: "long"/"short"/"neutral",  # v1.1 M3：动态判定
                      impact_level: float, is_scheduled: True}
        """
```

**事件类型映射**（CoinMarketCal category → event_type）：

| CoinMarketCal category | event_type |
|---|---|
| Hard Fork, Soft Fork, Mainnet Launch, Protocol Upgrade | `tech_upgrade` |
| Exchange Listing, Delisting | `tech_upgrade`（子类型标注） |
| 其他 | 暂不采集 |

**v1.1 修订（M3）：direction 动态判定逻辑**

tech_upgrade direction 不再固定 neutral，由以下因子加权决定（初版简单加权）：

| 因子 | 数据源 | long 偏置 | short 偏置 |
|---|---|---|---|
| 升级前价格趋势 | close 序列 20 周期斜率 | 斜率 > 0 → +0.4 | 斜率 < 0 → -0.4 |
| 社区情绪（CoinMarketCal percentage/votes） | API `percentage` 字段 | > 60% → +0.3 | < 40% → -0.3 |
| 子类型语义 | 事件子类型 | listing/mainnet → +0.3 | delisting → -0.3 |

判定规则：加权和 ≥ 0.3 → long，≤ -0.3 → short，否则 neutral。direction 写入 metrics，由 GeneralEventWindowTracker 透传到 dominant_direction。

> 此方向为 pre_event 阶段的初始偏置，EventDrivenStrategy 的 resilience_score 和实际 market reaction 会在 event/post_event 阶段修正。

**调度**：每 6 小时一次（事件日期稳定，无需高频）

### 6.2 FedSpeechCollector（fed_speech）

```
路径: 18-数据获取中心/data_center/collectors/macro/fed_speech_collector.py
source: "federalreserve"
category: "speech"
```

**数据源**：
1. federalreserve.gov/newsevents/speeches.htm（HTML 爬取，ScraplingEngine）
2. 硬编码固定周期：半年度 MPR 证词（2月/6-7月）+ Jackson Hole（8月下旬）

**v1.1 修订（M1）**：所有 fed_speech 统一走轨道 B（EventTriggerSink）。collector 不再标注 is_scheduled 用于路由，而是区分两类事件走不同 sink 接口：
- 固定周期讲话 → `consume_scheduled(event)`（提前写入 scheduled 队列）
- 临时讲话 → `consume(event)`（发布即触发）

**接口**：

```python
class FedSpeechCollector(BaseCollector):
    source = "federalreserve"
    category = "speech"

    def fetch(self, params: dict) -> list[DataRecord]:
        """
        采集 Fed 讲话事件，区分固定周期与临时讲话。

        返回 DataRecord 列表，每条含:
            events: [{title, speaker, date, url, type}]
            metrics: {event_type: "fed_speech",
                      trigger_mode: "scheduled"/"immediate",  # v1.1 替代 is_scheduled
                      direction: "long"/"short"/"neutral",
                      event_date: datetime}  # scheduled 事件的预期日期
        """
```

**固定周期硬编码**：

```python
SCHEDULED_SPEECHES = [
    # 半年度 MPR 证词（2月、6/7月，具体日期由日历页确认）
    {"name": "Semiannual MPR Testimony (Feb)", "month": 2, "type": "mpr"},
    {"name": "Semiannual MPR Testimony (Jun/Jul)", "month": 7, "type": "mpr"},
    # Jackson Hole（8月最后一个周五）
    {"name": "Jackson Hole Symposium", "month": 8, "week": -1, "weekday": 4, "type": "jackson_hole"},
]
```

**trigger_mode 判定**：
- 匹配 SCHEDULED_SPEECHES → `trigger_mode="scheduled"` → `EventTriggerSink.consume_scheduled(event)`
- speeches.htm 新发现的讲话 → `trigger_mode="immediate"` → `EventTriggerSink.consume(event)`

**direction 判定**（关键词匹配，初版）：

```python
HAWKISH_KEYWORDS = ["tight", "restrictive", "higher for longer", "inflation risk", "hike"]
DOVISH_KEYWORDS = ["dovish", "cut", "ease", "patient", "accommodative"]
```

**调度**：每 1 小时一次（讲话日期可能临时公布）

### 6.3 SecRssCollector（sec_deadline）

```
路径: 18-数据获取中心/data_center/collectors/macro/sec_rss_collector.py
source: "sec"
category: "enforcement"
```

**数据源**：SEC RSS 三个 feed
1. `sec.gov/enforcement-litigation/administrative-proceedings/rss`
2. `sec.gov/enforcement-litigation/litigation-releases/rss`
3. `sec.gov/xml/investor/pressreleases`（含加密政策提案）

**接口**：

```python
class SecRssCollector(BaseCollector):
    source = "sec"
    category = "enforcement"

    def fetch(self, params: dict) -> list[DataRecord]:
        """
        采集 SEC RSS 事件（发布即推送）。

        返回 DataRecord 列表，每条含:
            events: [{title, link, pub_date, creator}]
            metrics: {event_type: "sec_deadline",
                      direction: "short"/"long"/"neutral",  # 关键词匹配
                      is_scheduled: False,  # 突发触发
                      crypto_related: bool}  # 是否加密相关
        """
```

**方向判定**（关键词匹配）：

```python
BEARISH_KEYWORDS = ["charge", "sue", "fraud", "enforcement", "delist", "ban", "penalty"]
BULLISH_KEYWORDS = ["approve", "exempt", "innovation", "relief", "proposal", "modernize"]
CRYPTO_KEYWORDS = ["crypto", "bitcoin", "ethereum", "token", "digital asset", "blockchain", "exchange-traded"]
```

**v1.1 修订（M2）：三层去重逻辑**

> v1.0 仅按 `dc:creator` 去重，但 SEC 三个 feed（administrative proceedings / litigation releases / press releases）可能对同一行动发布多条 item，dc:creator 编号不同（LR-26520 vs 34-105415），会漏去重导致重复触发。v1.1 升级为三层去重：

```python
def is_duplicate(new_item, recent_items, window_hours=24) -> bool:
    """三层去重判定。

    1. dc:creator 完全匹配 → 重复
    2. 标题 Jaccard 相似度 > 0.7 且 24h 时间窗口内 → 重复
    3. 实体名匹配（从标题提取的人名/公司名交集 > 0）且 24h 窗口内 → 重复
    任一命中即视为重复。
    """
    # 第 1 层：dc:creator 精确匹配
    if new_item.creator in {item.creator for item in recent_items}:
        return True

    # 第 2 层：标题 Jaccard 相似度
    new_tokens = set(new_item.title.lower().split())
    for item in recent_items:
        if abs((new_item.pub_date - item.pub_date).total_seconds()) > window_hours * 3600:
            continue
        old_tokens = set(item.title.lower().split())
        jaccard = len(new_tokens & old_tokens) / max(1, len(new_tokens | old_tokens))
        if jaccard > 0.7:
            return True

    # 第 3 层：实体名匹配
    new_entities = _extract_entities(new_item.title)  # 提取大写词/公司名
    for item in recent_items:
        if abs((new_item.pub_date - item.pub_date).total_seconds()) > window_hours * 3600:
            continue
        old_entities = _extract_entities(item.title)
        if new_entities & old_entities:  # 有交集
            return True

    return False
```

> 已处理的事件 dc:creator 列表持久化到 SQLite `sec_rss_processed` 表，重启不丢失。

**调度**：每 15 分钟一次（RSS 是突发型，需近实时监听）

### 6.4 CongressionalHearingCollector（congressional_hearing）

```
路径: 18-数据获取中心/data_center/collectors/macro/congressional_hearing_collector.py
source: "congress"
category: "hearing"
```

**数据源**（v1.1 m2：落地前需快速验证可行性）：
1. senate.gov 信贷委员会日历页（HTML）
2. house.gov 金融服务委员会日历页（HTML）

> **v1.1 修订（m2）**：落地前必须完成数据源快速验证：
> - 确认 senate.gov/house.gov 有公开可爬的听证会日程页（非 PDF/JS 渲染）
> - 确认能提取到「日期 + 主题 + 是否加密相关」三要素
> - 如验证失败，congressional_hearing 降级为暂不实现（P4 跳过）

**快速验证脚本**（P4 落地前执行）：

```bash
# 验证 senate.gov 信贷委员会听证会日历页是否可爬
curl -s "https://www.banking.senate.gov/hearings" | grep -o "hearing" | head
```

> **优先级最低**（P4），落地时再确认具体 URL 和格式。

---

## 7. EventDrivenStrategy 扩展点

### 7.1 evaluate() 触发逻辑扩展

[event_driven_strategy.py L287-297](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/29-事件驱动策略系统/event_driven/event_driven_strategy.py#L287-297) 现有三选一触发：

```python
# 扩展后：四选一触发
is_macro_event_active = (
    in_fomc
    or (cesi is not None and abs(cesi) >= self.CESI_TRIGGER_THRESHOLD)
    or event_type in self.MACRO_EVENT_TYPES
    or event_type in ("tech_upgrade", "sec_deadline", "congressional_hearing")  # 新增
)
```

### 7.2 突发型事件特殊处理

检测到轨道 B（sec_deadline / fed_speech）时，跳过 pre_event 阶段逻辑：

```python
# v1.1 修订（M1）：fed_speech 统一走轨道 B，不再判断 is_scheduled
is_trigger_type = event_type in ("sec_deadline", "fed_speech")

if is_trigger_type:
    # 突发型：直接 event/post_event 逻辑，跳过 pre_event 偏移
    cycle_phase = event_ctx.get("cycle_phase", "event")
    # 不应用 pre_event 的 hike_prob 偏移
else:
    # 窗口预演型：现有逻辑（pre_event 偏移 + 三阶段权衡）
```

### 7.3 direction 来源扩展

现有 `dominant_direction` 来自 hike_prob/cut_prob。新事件类型无概率模型，direction 来源：

| event_type | direction 来源 |
|---|---|
| tech_upgrade | collector 动态判定（价格趋势 + 社区情绪 + 子类型语义，见 §6.1） |
| congressional_hearing | neutral（由内容决定，初版默认 neutral） |
| sec_deadline | collector 关键词匹配（short/long） |
| fed_speech | collector 关键词匹配（hawkish→short / dovish→long） |

### 7.4 compute_impulse 兼容

`compute_impulse(event_type, days_since, strength)` 已按 event_type 查 EVENT_HALF_LIFE，扩展后自动兼容新类型，无需改动。

---

## 8. 数据流

### 8.1 窗口预演型（轨道 A）

```
CoinMarketCalCollector.fetch()
    → DataRecord (event_type="tech_upgrade", event_date=...)
    → data_pipeline.assemble() 检测 event_type
    → GeneralEventWindowTracker.get_context(event_date, event_type)
    → event_context 注入 kline_data
    → EventDrivenStrategy.evaluate(kline_data)
```

### 8.2 突发触发型（轨道 B）

```
SecRssCollector.fetch()
    → DataRecord (event_type="sec_deadline", direction="short", crypto_related=True)
    → EventTriggerSink.consume(event)
    → data_pipeline.assemble() 查询 EventTriggerSink.get_context()
    → event_context 注入 kline_data
    → EventDrivenStrategy.evaluate(kline_data)
```

### 8.3 data_pipeline.assemble() 路由逻辑

```python
# data_pipeline.assemble() 新增事件上下文路由
event_type = upcoming_events.get("event_type", "none")

if event_type in ("fomc", "nfp", "cpi", "ppi"):
    # 轨道 A: FOMC 系列走 FOMCEventWindowTracker（现有逻辑）
    event_context = fomc_tracker.get_context(next_fomc, last_fomc, hike_prob, ...)
elif event_type in ("tech_upgrade", "congressional_hearing"):
    # 轨道 A: 通用日程型走 GeneralEventWindowTracker
    event_direction = upcoming_events.get("direction", "neutral")
    event_context = general_tracker.get_context(event_date, event_type, event_direction=event_direction)
elif event_type in ("sec_deadline", "fed_speech"):
    # 轨道 B: 突发型走 EventTriggerSink（v1.1 M1：fed_speech 统一走 B）
    event_context = trigger_sink.get_context(event_type)
else:
    event_context = {}  # FAIL-OPEN
```

---

## 9. 落地步骤（TDD，按优先级）

### P1: tech_upgrade（数据最成熟）

| 步骤 | 内容 | 产出 |
|---|---|---|
| 1. RED | test_general_event_window_tracker.py — 测 GeneralEventWindowTracker 3 阶段判定 | 失败测试 |
| 2. GREEN | general_event_window_tracker.py — 实现 BaseEventWindowTracker + GeneralEventWindowTracker | 通过测试 |
| 3. RED | test_coinmarketcal_collector.py — 测 API 响应解析 + 事件类型映射 | 失败测试 |
| 4. GREEN | coinmarketcal_collector.py — 实现 CoinMarketCalCollector | 通过测试 |
| 5. WIRE | data_pipeline.assemble() 接入 GeneralEventWindowTracker 路由 | 集成 |
| 6. EXTEND | event_driven_strategy.py 扩展 VALID_EVENT_TYPES + EVENT_HALF_LIFE + 触发逻辑 | 扩展 |
| 7. VERIFY | curl /api/event-driven 验证 tech_upgrade event_context 注入 | 端到端 |

### P2: fed_speech

| 步骤 | 内容 |
|---|---|
| 1. RED | test_event_trigger_sink.py — 测突发触发 + scheduled 队列预激活 + 衰减 + cleanup |
| 2. GREEN | event_trigger_sink.py — 实现 EventTriggerSink（含 consume_scheduled / cleanup） |
| 3. RED | test_fed_speech_collector.py — 测 HTML 解析 + 固定周期识别 + trigger_mode 判定 |
| 4. GREEN | fed_speech_collector.py — 实现 FedSpeechCollector（scheduled→consume_scheduled, immediate→consume） |
| 5. WIRE | data_pipeline.assemble() 接入轨道 B 路由（fed_speech 统一走 B） |
| 6. VERIFY | 端到端验证 scheduled 队列激活 + 临时讲话触发 |

### P3: sec_deadline

| 步骤 | 内容 |
|---|---|
| 1. RED | test_sec_rss_collector.py — 测 RSS 三 feed 解析 + 关键词方向匹配 + 三层去重（dc:creator/Jaccard/实体名） |
| 2. GREEN | sec_rss_collector.py — 实现 SecRssCollector + is_duplicate() 三层去重 |
| 3. WIRE | scheduler 注册 15 分钟调度 + sec_rss_processed 持久化表 |
| 4. VERIFY | 端到端验证同一 SEC 行动三 feed 仅触发一次 |

### P4: congressional_hearing

| 步骤 | 内容 |
|---|---|
| 1. RED | test_congressional_hearing_collector.py |
| 2. GREEN | congressional_hearing_collector.py |
| 3. WIRE + VERIFY |

---

## 10. 验收标准

### 10.1 功能验收

- [ ] `VALID_EVENT_TYPES` 包含 9 种（8+none）
- [ ] `GeneralEventWindowTracker.get_context()` 返回与 FOMCEventWindowTracker schema 一致的 dict，支持 5 阶段判定
- [ ] `EventTriggerSink.get_context()` 返回 event/post_event/neutral 三阶段
- [ ] **v1.1 M1**：`EventTriggerSink.consume_scheduled()` 能写入 scheduled 队列，event_date 到达时自动激活 event 阶段
- [ ] **v1.1 M1**：fed_speech 统一走轨道 B，data_pipeline 路由不判断 is_scheduled
- [ ] **v1.1 M2**：SecRssCollector 三层去重（dc:creator + Jaccard + 实体名），同一 SEC 行动三 feed 仅触发一次
- [ ] **v1.1 M3**：tech_upgrade direction 由 collector 动态判定（非固定 neutral），透传到 dominant_direction
- [ ] CoinMarketCalCollector 能采集 7 天前瞻的 tech_upgrade 事件
- [ ] SecRssCollector 能解析 SEC RSS 三个 feed + 关键词方向匹配
- [ ] FedSpeechCollector 能识别固定周期 + 临时讲话，分别走 consume_scheduled/consume
- [ ] data_pipeline.assemble() 正确路由双轨制
- [ ] EventDrivenStrategy.evaluate() 对 4 个新 event_type 产生非 neutral 信号（当条件满足时）

### 10.2 FAIL-OPEN 验收

- [ ] CoinMarketCal API Key 缺失 → 返回空列表，不抛异常
- [ ] SEC RSS 不可达 → 返回空列表
- [ ] federalreserve.gov HTML 结构变更 → 返回空列表
- [ ] EventTriggerSink 无触发记录 → 返回 neutral context
- [ ] 新 collector 故障不影响现有 fomc/nfp/cpi/ppi 链路

### 10.3 回归验收

- [ ] 现有 EventWindowTracker 测试全通过（别名兼容）
- [ ] 现有 EventDrivenStrategy 测试全通过
- [ ] 现有 fed_event_collector 测试全通过
- [ ] data_pipeline 集成测试全通过

---

## 11. 前置依赖与风险

### 11.1 前置依赖

| 依赖 | 状态 | 备注 |
|---|---|---|
| CoinMarketCal API Key | ⚠️ 需注册 | 免费档够用，注册地址 coinmarketcal.com/en/api |
| ScraplingEngine | ✅ 已有 | fed_event_collector 已使用 |
| BeautifulSoup | ✅ 已有 | fed_event_collector 已使用 |
| feedparser（RSS 解析） | ⚠️ 需确认 | 可用 BeautifulSoup 解析 XML，或新增 feedparser 依赖 |

### 11.2 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| CoinMarketCal 免费档仅 7 天前瞻 | tech_upgrade 窗口预演受限 | 7 天对 1 天半衰期足够；如需更长可升级付费档 |
| federalreserve.gov HTML 结构变更 | fed_speech 采集中断 | FAIL-OPEN 返回空；定期检查结构 |
| SEC RSS 是突发型，无窗口预演 | sec_deadline 无法提前布局 | 双轨制设计已解决：走 EventTriggerSink |
| 关键词方向匹配准确率 | sec_deadline direction 误判 | 初版容忍误判，由 resilience_score 市场反应修正 |
| EventTriggerSink 持久化 | 重启后丢失触发记录 | SQLite 持久化（event_trigger_log 表） |

### 11.3 不做的事（Out of Scope）

- 不修改 FOMC 的 6 阶段模型和概率模型
- 不修改 EventDrivenStrategy 的 5 维评分权重
- 不修改 BCRM2.0 / BDSM / 自进化子系统的接口
- 不接入 congressional_hearing 的具体 URL（P4 落地前快速验证，失败则跳过）
- 不做 CoinMarketCal 付费档集成（免费档够用）
- **v1.1 补充**：半衰期参数（tech_upgrade=1.0 等）标注为经验假设 v0，本阶段不做事件研究法回测校准，留待 Phase 3 回测验证后用贝叶斯优化校准
