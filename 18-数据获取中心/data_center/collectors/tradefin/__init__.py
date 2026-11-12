"""tradefin（传统金融）事件采集器 — SPEC §3.2（P0-C 官方源 + P1-A 中文财经源）。

P0-C 三个官方源：sec_edgar / fed_calendar / macro_calendar，`fetch()` 返回 `list[dict]`。
P1-A 四个中文源：sina_finance / wallstreetcn / cls / jin10，`fetch()` 返回
`CollectResult(events, bodies)`（正文走 bodies.jsonl，事件只存 `body_ref`）。

两类都产出 canonical EventRecord（§3.1），不是行情 DataRecord，
因此不走 BaseCollector.fetch() → DataRecord 通路，统一由
`data_center.cli.collect_events` 写入 `data_center/events/events.jsonl`。
"""

from data_center.collectors.tradefin._result import CollectResult

__all__ = ["CollectResult"]
