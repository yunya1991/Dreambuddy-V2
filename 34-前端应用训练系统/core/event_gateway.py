# -*- coding: utf-8 -*-
"""事件驱动 L1 网关(T-DSH-P0 C1)。

依据: SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2(46-DSH架构/docs/tech)§二/§四。
定位: 外部异步事件的零 token 第一道门——规则过滤 → 事件意图匹配 → 三分流:
  命中事件意图   → l1_close(L1 确定性闭环)
  未命中+高价值  → escalate_l2(升级 L2,C3 负责组六维上下文信封)
  未命中+低价值  → silent(注意力预算,记录后静默)

硬约束:
  HC-1 FAIL-OPEN: 任何异常 → action=fallback,事件直落现有入口,不抛错
  HC-2 开关 enable_event_l1_gateway 默认 False,关断时调用方不得加载本模块
  HC-4 零 token: 纯函数+注入依赖,生成式 LLM 禁止进入 L1
  HC-5 可审计: 每个决策携带 reason/value_score;shadow 模式经 recorder 留痕

shadow 模式(P0 默认): 决策照算、recorder 记录,但 effective_action=passthrough,
不拦截事件流(§六 风险缓解: 先旁路观察)。
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

# 模块化开关(HC-2,默认 False)
GATEWAY_SWITCH = "enable_event_l1_gateway"

# 三分流动作 + FAIL-OPEN 兜底动作
ACTION_L1_CLOSE = "l1_close"
ACTION_ESCALATE_L2 = "escalate_l2"
ACTION_SILENT = "silent"
ACTION_FALLBACK = "fallback"

# shadow 模式下不论决策为何,对外一律放行(只记录不拦截)
EFFECTIVE_PASSTHROUGH = "passthrough"

# 默认值(§七 评审清单: 未知 kind 默认升级,保证不漏事件)
_DEFAULT_VALUE = 0.5
_DEFAULT_THRESHOLD = 0.5
_DEFAULT_DEDUP_WINDOW_SEC = 300.0
_DEFAULT_BATCH_WINDOW_MS = 2000.0  # 批合并窗口初值 2s,对齐 Super-agent passes 周期

# Trigger 契约必填字段(SPEC §二)
_REQUIRED_FIELDS = ("trigger_id", "source", "kind")

# 事件意图契约文件默认路径(C2,与本模块同目录;两侧消费端只读对齐)
_DEFAULT_INTENTS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "event_intents.yaml"
)


def load_event_intents(path: Optional[str] = None) -> Dict[str, str]:
    """加载事件意图契约文件 → {kind: intent_id}(route_trigger 的 intents 入参)。

    契约文件是事件类意图唯一事实源(§七 独立事件注册表),34-core 与前端 TS
    两侧只读对齐。文件缺失/坏 YAML/结构非法 → {}(FAIL-OPEN,全部走价值分流)。
    """
    try:
        import yaml  # 延迟导入: 无 pyyaml 环境下网关本体仍可用

        with open(path or _DEFAULT_INTENTS_PATH, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        if not isinstance(doc, dict):
            return {}
        mapping: Dict[str, str] = {}
        for item in doc.get("intents") or []:
            if not isinstance(item, dict):
                continue
            intent_id = item.get("intent_id")
            if not intent_id:
                continue
            for kind in item.get("kinds") or []:
                if kind:
                    mapping[str(kind)] = str(intent_id)
        return mapping
    except Exception:
        return {}


def is_gateway_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(HC-2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(GATEWAY_SWITCH, False))
    except Exception:
        return False


class GatewayState:
    """去重/冷却状态(注入依赖,调用方持有)。

    网关本体纯函数;可变状态收敛到本对象,便于测试隔离与运行期重置。
    """

    def __init__(self) -> None:
        self._seen: Dict[str, float] = {}  # trigger_id → 最近通过时刻
        self._last_pass: Dict[tuple, float] = {}  # (source, kind) → 最近通过时刻

    def seen_recently(self, trigger_id: str, now: float, window_sec: float) -> bool:
        """trigger_id 在去重窗口内是否已出现过(出现过则不再重复通过)。"""
        last = self._seen.get(trigger_id)
        if last is not None and (now - last) < window_sec:
            return True
        self._seen[trigger_id] = now
        return False

    def in_cooldown(self, source: str, kind: str, now: float, cooldown_sec: float) -> bool:
        """(source, kind) 在冷却窗口内是否已有同类事件通过。"""
        key = (source, kind)
        last = self._last_pass.get(key)
        if last is not None and (now - last) < cooldown_sec:
            return True
        self._last_pass[key] = now
        return False


def normalize_trigger(raw: Any) -> Optional[Dict[str, Any]]:
    """Trigger 契约规整:{trigger_id, source, kind, payload_ref, thread_id?, ts}。

    缺必填字段 / 非 dict → None(FAIL-OPEN,由 route_trigger 转 fallback)。
    ts 缺省补当前时间(便于无 ts 的适配器)。
    """
    try:
        if not isinstance(raw, dict):
            return None
        for field in _REQUIRED_FIELDS:
            if not raw.get(field):
                return None
        ts = raw.get("ts")
        try:
            ts = float(ts) if ts is not None else time.time()
        except (TypeError, ValueError):
            ts = time.time()
        return {
            "trigger_id": str(raw["trigger_id"]),
            "source": str(raw["source"]),
            "kind": str(raw["kind"]),
            "payload_ref": raw.get("payload_ref"),
            "thread_id": raw.get("thread_id"),
            "ts": ts,
        }
    except Exception:
        return None


def _fallback(reason: str, raw: Any = None) -> Dict[str, Any]:
    """FAIL-OPEN 决策(HC-1): 行为等价网关不存在,事件直落现有入口。"""
    return {
        "trigger_id": raw.get("trigger_id") if isinstance(raw, dict) else None,
        "action": ACTION_FALLBACK,
        "effective_action": ACTION_FALLBACK,
        "reason": reason,
        "intent_id": None,
        "value_score": None,
        "shadow": False,
    }


def _silent(trigger: Dict[str, Any], reason: str, value_score: Optional[float]) -> Dict[str, Any]:
    return {
        "trigger_id": trigger.get("trigger_id"),
        "action": ACTION_SILENT,
        "effective_action": ACTION_SILENT,
        "reason": reason,
        "intent_id": None,
        "value_score": value_score,
        "shadow": False,
    }


def route_trigger(
    raw_trigger: Any,
    rules: Optional[Dict[str, Any]] = None,
    intents: Optional[Dict[str, str]] = None,
    state: Optional[Any] = None,
    now: Optional[float] = None,
    shadow: bool = False,
    recorder: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """单事件分流: 规则过滤 → 事件意图匹配 → 三分流。

    参数(全部注入,纯函数):
      rules   规则配置 {whitelist:{sources,kinds}, dedup_window_sec,
              cooldown_sec:{kind:秒}, value_threshold, kind_value:{kind:分}}
      intents 事件意图契约(kind → intent_id,C2 契约文件由调用方加载)
      state   GatewayState(去重/冷却);None 则本轮无状态
      now     当前时刻(可注入便于测试);缺省 time.time()
      shadow  True=旁路观察: 决策照算+recorder 记录,effective_action=passthrough
      recorder 决策记录回调(HC-5 审计);回调异常静默吞掉

    任何异常 → fallback(HC-1),绝不抛错。
    """
    try:
        trigger = normalize_trigger(raw_trigger)
        if trigger is None:
            return _fallback("invalid_trigger", raw_trigger)
        if rules is not None and not isinstance(rules, dict):
            return _fallback("invalid_rules", trigger)
        if intents is not None and not isinstance(intents, dict):
            return _fallback("invalid_intents", trigger)

        rules = rules or {}
        intents = intents or {}
        ts_now = float(now) if now is not None else time.time()
        kind = trigger["kind"]
        source = trigger["source"]

        # ① 程序规则过滤(白名单/去重/冷却)
        whitelist = rules.get("whitelist") or {}
        sources = whitelist.get("sources") or []
        kinds = whitelist.get("kinds") or []
        if (sources and source not in sources) or (kinds and kind not in kinds):
            decision = _silent(trigger, "whitelist", None)
            return _finalize(decision, shadow, recorder)

        if state is not None:
            dedup_window = float(rules.get("dedup_window_sec", _DEFAULT_DEDUP_WINDOW_SEC))
            if state.seen_recently(trigger["trigger_id"], ts_now, dedup_window):
                decision = _silent(trigger, "dedup", None)
                return _finalize(decision, shadow, recorder)
            cooldown_map = rules.get("cooldown_sec") or {}
            cooldown_sec = cooldown_map.get(kind)
            if cooldown_sec and state.in_cooldown(source, kind, ts_now, float(cooldown_sec)):
                decision = _silent(trigger, "cooldown", None)
                return _finalize(decision, shadow, recorder)

        # ② 事件类意图匹配(命中 → L1 确定性闭环)
        intent_id = intents.get(kind)
        if intent_id:
            decision = {
                "trigger_id": trigger["trigger_id"],
                "action": ACTION_L1_CLOSE,
                "effective_action": ACTION_L1_CLOSE,
                "reason": "intent_hit",
                "intent_id": intent_id,
                "value_score": None,
                "shadow": False,
            }
            return _finalize(decision, shadow, recorder)

        # ③ 未命中: 价值分 ≥ 阈值升级 L2,否则静默(注意力预算)
        value = float((rules.get("kind_value") or {}).get(kind, _DEFAULT_VALUE))
        threshold = float(rules.get("value_threshold", _DEFAULT_THRESHOLD))
        if value >= threshold:
            decision = {
                "trigger_id": trigger["trigger_id"],
                "action": ACTION_ESCALATE_L2,
                "effective_action": ACTION_ESCALATE_L2,
                "reason": "value_above_threshold",
                "intent_id": None,
                "value_score": value,
                "shadow": False,
            }
        else:
            decision = _silent(trigger, "low_value", value)
        return _finalize(decision, shadow, recorder)
    except Exception as exc:
        return _fallback("fail_open:%s" % type(exc).__name__, raw_trigger)


def _finalize(
    decision: Dict[str, Any],
    shadow: bool,
    recorder: Optional[Callable[[Dict[str, Any]], None]],
) -> Dict[str, Any]:
    """shadow 标记 + 审计记录(HC-5)。recorder 异常静默吞掉(FAIL-OPEN)。"""
    try:
        if shadow:
            decision["shadow"] = True
            decision["effective_action"] = EFFECTIVE_PASSTHROUGH
        if recorder is not None:
            try:
                recorder(decision)
            except Exception:
                pass
        return decision
    except Exception:
        return _fallback("fail_open:finalize")


def merge_batch(
    raw_triggers: Any,
    window_ms: float = _DEFAULT_BATCH_WINDOW_MS,
) -> List[Dict[str, Any]]:
    """批合并: 事件突发时按 (thread_id, kind) 在窗口内合并(§三.1 任务 5)。

    无 thread_id 的事件按 kind 合并。同组内按 ts 排序,超过窗口即切新批。
    返回合并批列表:[{trigger_ids, kind, thread_id, count, payload_refs,
    payload_ref(首个为代表), first_ts, last_ts}]。坏输入 → [](FAIL-OPEN)。
    """
    try:
        if not isinstance(raw_triggers, (list, tuple)) or not raw_triggers:
            return []
        groups: Dict[tuple, List[Dict[str, Any]]] = {}
        for raw in raw_triggers:
            trigger = normalize_trigger(raw)
            if trigger is None:
                continue
            key = (trigger["thread_id"], trigger["kind"])
            groups.setdefault(key, []).append(trigger)

        batches: List[Dict[str, Any]] = []
        for (thread_id, kind), items in groups.items():
            items.sort(key=lambda t: t["ts"])
            current: Optional[Dict[str, Any]] = None
            for trigger in items:
                in_window = (
                    current is not None
                    and (trigger["ts"] - current["first_ts"]) * 1000.0 <= window_ms
                )
                if not in_window:
                    if current is not None:
                        batches.append(current)
                    current = {
                        "trigger_ids": [],
                        "kind": kind,
                        "thread_id": thread_id,
                        "count": 0,
                        "payload_refs": [],
                        "payload_ref": None,
                        "first_ts": trigger["ts"],
                        "last_ts": trigger["ts"],
                    }
                current["trigger_ids"].append(trigger["trigger_id"])
                current["count"] += 1
                current["payload_refs"].append(trigger["payload_ref"])
                if current["payload_ref"] is None:
                    current["payload_ref"] = trigger["payload_ref"]
                current["last_ts"] = trigger["ts"]
            if current is not None:
                batches.append(current)

        batches.sort(key=lambda b: b["first_ts"])
        return batches
    except Exception:
        return []
