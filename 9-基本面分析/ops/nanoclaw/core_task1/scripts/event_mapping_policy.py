import json
import re
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).parent.parent
POLICY_PATH = BASE_DIR / "schema" / "event_mapping.policy.json"


def load_policy() -> Dict[str, Any]:
    try:
        with open(POLICY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


POLICY = load_policy()


def map_event_type(topic: str, category: str, title: str, body: str) -> str:
    t = str(topic or "").strip()
    c = str(category or "").strip()
    text = f"{title or ''} {body or ''}"

    for rule in POLICY.get("keyword_rules", []):
        event_type = str(rule.get("event_type") or "unknown")
        patterns = rule.get("patterns") or []
        for p in patterns:
            if re.search(str(p), text, re.IGNORECASE):
                return event_type

    topic_map = POLICY.get("topic_to_event_type") or {}
    if t in topic_map:
        return str(topic_map[t])

    category_map = POLICY.get("category_to_event_type") or {}
    if c in category_map:
        return str(category_map[c])

    return "unknown"


def is_macro_topic(topic: str) -> bool:
    t = str(topic or "").strip()
    macro_topics = POLICY.get("macro_topics_for_expectation") or []
    return t in macro_topics


def is_high_grade_event(event_type: str, event_window_range: str) -> bool:
    et = str(event_type or "").strip()
    wr = str(event_window_range or "").strip()
    high_grades = POLICY.get("high_grade_event_types") or []
    near_windows = POLICY.get("near_window_ranges") or []
    return et in high_grades and wr in near_windows
