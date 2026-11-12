"""E 层金融事件存储（SPEC-EMERGENCE-FINANCIAL-ENV §3.1）。

canonical EventRecord 唯一落盘位置：data_center/events/events.jsonl（append-only）。
正文（point-in-time 快照）落盘位置：data_center/events/bodies.jsonl（事件只存 body_ref）。
"""

from data_center.events.body_store import (
    BODIES_PATH,
    BodyContractError,
    append_bodies,
    body_ref,
    load_bodies,
    make_body_id,
    normalize_body,
    resolve_body_ref,
)
from data_center.events.store import (
    EVENTS_PATH,
    EventContractError,
    append_events,
    audit_events,
    load_events,
    make_event_id,
    normalize_event,
)

__all__ = [
    "BODIES_PATH",
    "EVENTS_PATH",
    "BodyContractError",
    "EventContractError",
    "append_bodies",
    "append_events",
    "audit_events",
    "body_ref",
    "load_bodies",
    "load_events",
    "make_body_id",
    "make_event_id",
    "normalize_body",
    "normalize_event",
    "resolve_body_ref",
]
