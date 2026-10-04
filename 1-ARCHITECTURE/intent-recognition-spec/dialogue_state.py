#!/usr/bin/env python3
"""
交易系统对话状态管理器

Phase 2: 对话状态管理（Dialogue State Management, DSM）

功能：
1. 对话上下文跟踪 — 维护多轮对话历史和槽位
2. 槽位继承 — 从上一轮意图继承未覆盖的槽位
3. 指代消解 — 解析"它"、"那个"、"刚才"等指代词
4. 修正回滚 — 处理"不是X是Y"类型的修正指令
5. 确认流程 — 高风险交易的二次确认状态机

用法:
    dsm = DialogueStateManager()

    # 第一轮
    result1 = dsm.process("茅台走势怎么样？")
    # result1 包含完整意图 + 更新后的对话状态

    # 第二轮（指代消解 + 槽位继承）
    result2 = dsm.process("那它呢")  # "它" -> 茅台
"""

import json
import copy
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum


# ── 状态枚举 ────────────────────────────────────────────────────────────────

class DialoguePhase(str, Enum):
    """对话阶段"""
    INITIAL = "initial"           # 初始状态，无上下文
    ACTIVE = "active"             # 活跃对话中
    AWAITING_CONFIRM = "awaiting_confirm"  # 等待确认（高风险交易）
    AWAITING_CLARIFY = "awaiting_clarify"  # 等待澄清
    COMPLETED = "completed"       # 单轮完成
    CANCELLED = "cancelled"       # 用户取消


class ModificationType(str, Enum):
    """修正类型"""
    ACTION_CORRECTION = "action_correction"      # "不是买，是卖"
    PARAMETER_MODIFICATION = "parameter_modification"  # "改成200股"
    TARGET_CORRECTION = "target_correction"      # "不是茅台，是五粮液"
    QUANTITY_MODIFICATION = "quantity_modification"  # "改100股"
    CANCEL = "cancel"                              # "算了"


# ── 指代消解规则 ────────────────────────────────────────────────────────────

# 指代词 → 解析策略
REFERENCE_PATTERNS = {
    # 标的指代
    "它": "resolve_stock",
    "它呢": "resolve_stock",
    "那只": "resolve_stock",
    "那个": "resolve_stock_or_target",
    "那只股票": "resolve_stock",
    "刚才那只": "resolve_stock",
    "刚刚说的": "resolve_stock_or_topic",
    # 订单指代
    "刚才那单": "resolve_order_last",
    "上一单": "resolve_order_last",
    "最后那单": "resolve_order_last",
    "刚刚那个": "resolve_order_last",
    # 操作指代
    "再来一次": "repeat_last_action",
    "再买": "repeat_buy",
    "再卖": "repeat_sell",
}

# 修正触发词
MODIFICATION_TRIGGERS = {
    "不是": ModificationType.ACTION_CORRECTION.value,      # "不是买，是卖"
    "改成": ModificationType.PARAMETER_MODIFICATION.value,   # "改成200股"
    "换成": ModificationType.TARGET_CORRECTION.value,       # "换成五粮液"
    "不对": ModificationType.ACTION_CORRECTION.value,       # "不对，是卖"
    "错了": ModificationType.ACTION_CORRECTION.value,       # "错了，应该是200股"
    "修改": ModificationType.PARAMETER_MODIFICATION.value,  # "修改数量为200"
    "改": ModificationType.PARAMETER_MODIFICATION.value,    # "改200股"
}

# 确认触发词
CONFIRM_TRIGGERS = {
    "好的": True,
    "确认": True,
    "没问题": True,
    "对": True,
    "是的": True,
    "执行": True,
    "可以": True,
    "好": True,
    "嗯": True,
}

# 取消触发词
CANCEL_TRIGGERS = {
    "算了": True,
    "取消": True,
    "不要了": True,
    "算了算了": True,
    "放弃": True,
    "算了把": True,
}


# ── 对话状态数据结构 ────────────────────────────────────────────────────────

@dataclass
class TurnRecord:
    """单轮对话记录"""
    user_input: str
    intent_result: Dict[str, Any]
    timestamp: str = ""
    phase: str = DialoguePhase.ACTIVE.value


@dataclass
class DialogueState:
    """对话状态"""
    turns: List[TurnRecord] = field(default_factory=list)
    current_phase: DialoguePhase = DialoguePhase.INITIAL

    # 最近一次有效意图的槽位（用于继承）
    last_intent_slots: Dict[str, Any] = field(default_factory=dict)

    # 最近一次涉及的标的
    last_stock: Optional[str] = None
    last_sector: Optional[str] = None

    # 最近一次操作类型
    last_action: Optional[str] = None

    # 待确认的意图（高风险交易等）
    pending_confirm_intent: Optional[Dict[str, Any]] = None

    # 对话ID（同一会话内递增）
    turn_count: int = 0

    def get_context(self) -> Dict[str, Any]:
        """生成供意图识别器使用的上下文"""
        context = {
            "turn_count": self.turn_count,
            "phase": self.current_phase.value,
        }

        if self.last_stock:
            context["last_stock"] = self.last_stock
        if self.last_sector:
            context["last_sector"] = self.last_sector
        if self.last_action:
            context["last_action"] = self.last_action
        if self.last_intent_slots:
            context["last_slots"] = self.last_intent_slots

        # 最近 3 轮对话历史
        recent_turns = self.turns[-3:] if len(self.turns) > 3 else self.turns
        if recent_turns:
            context["recent_history"] = [
                {
                    "input": t.user_input,
                    "intent": t.intent_result.get("intent_primary", ""),
                    "secondary": t.intent_result.get("intent_secondary", ""),
                    "slots": t.intent_result.get("slots", {}),
                }
                for t in recent_turns
            ]

        if self.pending_confirm_intent:
            context["pending_confirm"] = self.pending_confirm_intent

        return context

    def get_last_turn(self) -> Optional[TurnRecord]:
        """获取最近一轮对话"""
        if self.turns:
            return self.turns[-1]
        return None


# ── 对话状态管理器 ──────────────────────────────────────────────────────────

class DialogueStateManager:
    """对话状态管理器"""

    # 高风险意图需要确认
    HIGH_RISK_INTENTS = {"buy", "sell", "add_position", "close_position", "conditional_order"}

    # 可继承的槽位（如果新轮没提供，从上一轮继承）
    INHERITABLE_SLOTS = {"stock", "sector", "strategy_name", "implied_holding"}

    def __init__(self):
        self.state = DialogueState()

    def process(
        self,
        user_input: str,
        classify_fn=None,
    ) -> Dict[str, Any]:
        """
        处理用户输入，结合对话状态返回增强的意图结果

        Args:
            user_input: 用户自然语言输入
            classify_fn: 意图识别函数（接收 input + context，返回意图结果）

        Returns:
            增强后的意图识别结果（含 dialogue_state 字段）
        """
        self.state.turn_count += 1
        state_context = self.state.get_context()

        # 0. 优先检查修正指令（即使在确认流程中，修正也应优先处理）
        modification = self._detect_modification(user_input)
        if modification:
            result = self._apply_modification(user_input, modification)
            # 修正后退出确认流程
            if self.state.current_phase == DialoguePhase.AWAITING_CONFIRM:
                self.state.pending_confirm_intent = None
                self.state.current_phase = DialoguePhase.ACTIVE
            self._record_turn(user_input, result)
            return result

        # 1. 检查是否在等待确认
        if self.state.current_phase == DialoguePhase.AWAITING_CONFIRM:
            result = self._handle_confirm_flow(user_input)
            if result:
                return result

        # 3. 指代消解 — 将指代词替换为具体实体
        resolved_input, ref_info = self._resolve_references(user_input)

        # 4. 调用意图识别
        if classify_fn:
            result = classify_fn(resolved_input, state_context)
        else:
            result = {
                "intent_primary": "dialog",
                "intent_secondary": "chitchat",
                "risk_level": "low",
                "slots": {},
                "confidence": 0.0,
                "error": "no classify_fn provided",
            }

        # 5. 槽位继承 — 从上一轮继承未提供的槽位
        result = self._inherit_slots(result)

        # 6. 记录指代消解信息
        if ref_info:
            result["reference_resolved"] = ref_info

        # 7. 更新对话状态
        self._update_state(result)

        # 8. 高风险交易 → 进入确认流程
        if self._needs_confirmation(result):
            self.state.current_phase = DialoguePhase.AWAITING_CONFIRM
            self.state.pending_confirm_intent = result
            result["confirmation_required"] = True
            result["confirm_message"] = self._build_confirm_message(result)

        # 9. 记录本轮对话
        self._record_turn(user_input, result)

        return result

    # ── 指代消解 ────────────────────────────────────────────────────────────

    def _resolve_references(self, user_input: str) -> Tuple[str, Dict[str, Any]]:
        """
        解析用户输入中的指代词，替换为具体实体

        Returns:
            (resolved_input, reference_info)
        """
        ref_info = {}
        resolved_input = user_input

        # 检查标的指代
        for pattern, strategy in REFERENCE_PATTERNS.items():
            if pattern in user_input:
                if "stock" in strategy and self.state.last_stock:
                    resolved_input = resolved_input.replace(pattern, self.state.last_stock)
                    ref_info["resolved_target"] = {
                        "reference": pattern,
                        "resolved_to": self.state.last_stock,
                        "strategy": strategy,
                    }
                    break
                elif "order" in strategy:
                    ref_info["resolved_order_ref"] = {
                        "reference": pattern,
                        "resolved_to": "last",
                        "strategy": strategy,
                    }
                    break
                elif "repeat" in strategy and self.state.last_action:
                    ref_info["repeated_action"] = {
                        "reference": pattern,
                        "resolved_to": self.state.last_action,
                        "strategy": strategy,
                    }
                    break

        return resolved_input, ref_info

    # ── 修正检测与回滚 ─────────────────────────────────────────────────────

    def _detect_modification(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        检测用户输入是否为修正指令

        Returns:
            修正信息 dict 或 None
        """
        # 取消指令
        for trigger in CANCEL_TRIGGERS:
            if user_input.strip().startswith(trigger):
                return {"type": ModificationType.CANCEL.value, "trigger": trigger}

        # 否定修正："不是X，是Y"
        if "不是" in user_input and "是" in user_input:
            return {
                "type": ModificationType.ACTION_CORRECTION.value,
                "trigger": "不是...是...",
                "raw": user_input,
            }

        # 参数修改："改成X"、"换X"
        for trigger, mod_type in MODIFICATION_TRIGGERS.items():
            if trigger in user_input:
                return {
                    "type": mod_type,
                    "trigger": trigger,
                    "raw": user_input,
                }

        return None

    def _apply_modification(
        self,
        user_input: str,
        modification: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        应用修正到上一轮意图

        Returns:
            修正后的意图结果
        """
        mod_type = modification["type"]
        last_turn = self.state.get_last_turn()

        if not last_turn:
            return {
                "intent_primary": "dialog",
                "intent_secondary": "chitchat",
                "risk_level": "low",
                "slots": {},
                "confidence": 0.3,
                "error": "no_previous_turn_to_modify",
            }

        last_result = copy.deepcopy(last_turn.intent_result)

        if mod_type == ModificationType.CANCEL.value:
            # 取消操作
            self.state.current_phase = DialoguePhase.CANCELLED
            self.state.pending_confirm_intent = None
            return {
                "intent_primary": "dialog",
                "intent_secondary": "cancel",
                "risk_level": "low",
                "slots": {},
                "confidence": 0.95,
                "cancelled_previous": True,
                "confirmation_flow": "cancelled",
                "dialogue_phase": DialoguePhase.CANCELLED.value,
            }

        elif mod_type == ModificationType.ACTION_CORRECTION.value:
            # "不是买，是卖" — 修正操作方向
            # 从输入中提取新动作
            new_action = self._extract_action_from_correction(user_input)
            if new_action and last_result.get("slots"):
                last_result["slots"]["action"] = new_action

                # 同时修正二级意图
                action_to_secondary = {
                    "buy": "buy",
                    "sell": "sell",
                }
                if new_action in action_to_secondary:
                    last_result["intent_secondary"] = action_to_secondary[new_action]

            last_result["modified_from"] = {
                "type": mod_type,
                "original_action": last_result.get("slots", {}).get("action"),
            }
            last_result["confidence"] = 0.90
            return last_result

        elif mod_type in (
            ModificationType.PARAMETER_MODIFICATION.value,
            ModificationType.QUANTITY_MODIFICATION.value,
        ):
            # "改成200股" — 修改参数
            new_params = self._extract_params_from_modification(user_input)
            if last_result.get("slots"):
                last_result["slots"].update(new_params)

            last_result["intent_primary"] = "dialog"
            last_result["intent_secondary"] = "modify"
            last_result["risk_level"] = "low"
            last_result["modified_from"] = {
                "type": mod_type,
                "modified_params": list(new_params.keys()),
            }
            last_result["confidence"] = 0.88
            return last_result

        elif mod_type == "target_modify":
            # "换成五粮液" — 修改标的
            new_stock = self._extract_stock_from_modification(user_input)
            if new_stock and last_result.get("slots"):
                last_result["slots"]["stock"] = new_stock

            last_result["modified_from"] = {
                "type": mod_type,
                "original_stock": last_result.get("slots", {}).get("stock"),
            }
            last_result["confidence"] = 0.85
            return last_result

        return last_result

    def _extract_action_from_correction(self, input_text: str) -> Optional[str]:
        """从'不是买，是卖'中提取新动作"""
        if "卖" in input_text:
            return "sell"
        if "买" in input_text:
            return "buy"
        if "持有" in input_text or "拿" in input_text:
            return "hold"
        return None

    def _extract_params_from_modification(self, input_text: str) -> Dict[str, Any]:
        """从'改成200股'中提取参数"""
        import re
        params = {}

        # 提取数量
        qty_match = re.search(r'(\d+)\s*(股|手|个|张)', input_text)
        if qty_match:
            params["quantity"] = int(qty_match.group(1))
            unit = qty_match.group(2)
            unit_map = {"股": "share", "手": "lot", "个": "unit", "张": "contract"}
            params["quantity_unit"] = unit_map.get(unit, unit)

        # 提取价格
        price_match = re.search(r'(\d+(?:\.\d+)?)\s*(元|块)', input_text)
        if price_match:
            params["price"] = float(price_match.group(1))

        return params

    def _extract_stock_from_modification(self, input_text: str) -> Optional[str]:
        """从'换成五粮液'中提取新标的"""
        # 简单实现：去掉触发词后的内容
        for trigger in ["换成", "不是", "改", "修改"]:
            if trigger in input_text:
                remaining = input_text.split(trigger)[-1].strip("，。的了")
                if remaining:
                    return remaining
        return None

    # ── 槽位继承 ────────────────────────────────────────────────────────────

    def _inherit_slots(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从上一轮继承未提供的槽位"""
        if not self.state.last_intent_slots:
            return result

        slots = result.get("slots", {})
        if not slots:
            # 如果完全没有槽位但意图需要（如"那它呢"），从上一轮继承
            if result.get("intent_primary") in ("analysis", "query", "trade"):
                inherited = {}
                for slot_name in self.INHERITABLE_SLOTS:
                    if slot_name in self.state.last_intent_slots:
                        inherited[slot_name] = self.state.last_intent_slots[slot_name]
                if inherited:
                    result["slots"] = inherited
                    result["slots_inherited"] = True
            return result

        # 部分继承：只继承新轮未提供的可继承槽位
        inherited_any = False
        for slot_name in self.INHERITABLE_SLOTS:
            if (slot_name not in slots
                    and slot_name in self.state.last_intent_slots
                    and self.state.last_intent_slots[slot_name] is not None):
                slots[slot_name] = self.state.last_intent_slots[slot_name]
                inherited_any = True

        if inherited_any:
            result["slots_inherited"] = True

        result["slots"] = slots
        return result

    # ── 确认流程 ────────────────────────────────────────────────────────────

    def _needs_confirmation(self, result: Dict[str, Any]) -> bool:
        """判断是否需要二次确认"""
        secondary = result.get("intent_secondary", "")
        return secondary in self.HIGH_RISK_INTENTS

    def _handle_confirm_flow(self, user_input: str) -> Optional[Dict[str, Any]]:
        """处理确认流程中的用户输入"""
        stripped = user_input.strip()

        # 检查确认
        for trigger in CONFIRM_TRIGGERS:
            if stripped.startswith(trigger) or stripped == trigger:
                confirmed = copy.deepcopy(self.state.pending_confirm_intent or {})
                confirmed["confirmed"] = True
                confirmed["confirmation_flow"] = "confirmed"
                self.state.pending_confirm_intent = None
                self.state.current_phase = DialoguePhase.COMPLETED
                self._record_turn(user_input, confirmed)
                return confirmed

        # 检查取消
        for trigger in CANCEL_TRIGGERS:
            if stripped.startswith(trigger):
                cancelled = {
                    "intent_primary": "dialog",
                    "intent_secondary": "cancel",
                    "risk_level": "low",
                    "slots": {},
                    "confidence": 0.95,
                    "confirmation_flow": "cancelled",
                    "cancelled_intent": self.state.pending_confirm_intent,
                }
                self.state.pending_confirm_intent = None
                self.state.current_phase = DialoguePhase.CANCELLED
                self._record_turn(user_input, cancelled)
                return cancelled

        # 用户修改了参数 — 退出确认流程，正常处理
        self.state.pending_confirm_intent = None
        self.state.current_phase = DialoguePhase.ACTIVE
        return None  # 返回 None 让正常流程处理

    def _build_confirm_message(self, result: Dict[str, Any]) -> str:
        """构建确认提示消息"""
        slots = result.get("slots", {})
        secondary = result.get("intent_secondary", "")

        action_map = {
            "buy": "买入",
            "sell": "卖出",
            "add_position": "加仓",
            "close_position": "清仓",
            "conditional_order": "设置条件单",
        }

        action = action_map.get(secondary, secondary)
        stock = slots.get("stock", "未知标的")
        quantity = slots.get("quantity", "")

        parts = [f"确认{action} {stock}"]
        if quantity and quantity != "all":
            parts.append(f"{quantity}股")
        elif quantity == "all":
            parts.append("全部")
        elif quantity == "all_in":
            parts.append("全仓")

        msg = "".join(parts) + "？"
        if secondary == "conditional_order":
            price = slots.get("price", "")
            condition = slots.get("condition_type", "")
            if price:
                msg = f"确认设置条件单：{stock} {'跌破' if condition == 'stop_loss' else '涨到'}{price}时{slots.get('action', '卖出')}？"

        return msg

    # ── 状态更新 ────────────────────────────────────────────────────────────

    def _update_state(self, result: Dict[str, Any]):
        """根据意图结果更新对话状态"""
        slots = result.get("slots", {})

        # 更新最近标的
        if slots.get("stock"):
            self.state.last_stock = slots["stock"]
        if slots.get("sector"):
            self.state.last_sector = slots["sector"]

        # 更新最近操作
        secondary = result.get("intent_secondary", "")
        if secondary in ("buy", "sell", "add_position", "close_position"):
            self.state.last_action = secondary

        # 更新可继承槽位
        if slots:
            self.state.last_intent_slots = {
                k: v for k, v in slots.items()
                if k in self.INHERITABLE_SLOTS or k in ("stock", "sector")
            }

        # 更新阶段
        if self.state.current_phase == DialoguePhase.INITIAL:
            self.state.current_phase = DialoguePhase.ACTIVE

    def _record_turn(self, user_input: str, result: Dict[str, Any]):
        """记录一轮对话"""
        turn = TurnRecord(
            user_input=user_input,
            intent_result=copy.deepcopy(result),
            phase=self.state.current_phase.value,
        )
        self.state.turns.append(turn)

    # ── 状态查询 ────────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        """获取当前对话状态（可序列化）"""
        return {
            "turn_count": self.state.turn_count,
            "current_phase": self.state.current_phase.value,
            "last_stock": self.state.last_stock,
            "last_sector": self.state.last_sector,
            "last_action": self.state.last_action,
            "last_intent_slots": self.state.last_intent_slots,
            "has_pending_confirm": self.state.pending_confirm_intent is not None,
            "recent_turns": [
                {
                    "input": t.user_input,
                    "intent": t.intent_result.get("intent_primary", ""),
                    "secondary": t.intent_result.get("intent_secondary", ""),
                }
                for t in self.state.turns[-5:]
            ],
        }

    def reset(self):
        """重置对话状态"""
        self.state = DialogueState()
