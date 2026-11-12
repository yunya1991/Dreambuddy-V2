"""采集结果容器：事件 + 待入库正文（P1-A）。

P0-C 的官方源只产出事件，`fetch()` 直接返回 list[dict]；
P1-A 的中文财经源需要"正文入库"（SPEC §3.1 body_ref），因此统一返回
`CollectResult(events, bodies)`，由 `cli/collect_events.py` 先写正文、再写事件。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CollectResult:
    events: list[dict] = field(default_factory=list)
    bodies: list[dict] = field(default_factory=list)
