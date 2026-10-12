"""
辩论引擎深度集成 — P3
====================
复杂案例调用辩论引擎产生 debate 元数据（bull/bear confidence），
注入 case.metadata['debate']，供 P2 C-Drive 反思逻辑使用。

集成链路：
  收尾案例 → should_run_debate() 判断 → run_debate_for_case() 调用
  → 注入 debate 元数据 → derive_expected_decision_with_cdrive() 使用

设计原则：
  - FAIL-OPEN：辩论引擎不可用时降级为 P2/P1 逻辑
  - 延迟控制：低价值案例走 run_fast（~10s），高价值走 run_deep（~20-40s）
  - 无 LLM 时：降级为纯规则辩论（debate_engine 内部 FAIL-OPEN）

关联：
  - 辩论引擎: 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/debate_engine.py
  - C-Drive Agent: 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py
  - 决策推导器: 34-前端应用训练系统/core/decision_deriver.py
"""
import asyncio
import os
import sys
from typing import Any, Dict, Optional

# sys.path 注入 python-server 路径
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_PYTHON_SERVER_DIR = os.path.join(
    _PROJECT_ROOT, "1-ARCHITECTURE",
    "dream-harness-bridge", "packages", "python-server",
)

for _p in [_THIS_DIR, _34_DIR, _PYTHON_SERVER_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ============================================================
# 辩论触发阈值
# ============================================================

# confidence 低于此值时考虑触发辩论
DEBATE_CONFIDENCE_THRESHOLD = 0.5

# outcome 为 failure/partial 时考虑触发辩论
DEBATE_OUTCOMES = {"failure", "partial"}

# 高价值案例关键词（触发 run_deep 而非 run_fast）
HIGH_VALUE_KEYWORDS = [
    "架构", "重写", "迁移", "核心", "关键", "重要",
    "architecture", "rewrite", "migration", "critical", "core",
]


# ============================================================
# 辩论引擎加载（FAIL-OPEN）
# ============================================================

_debate_engine = None
_debate_engine_loaded = False


def _load_debate_engine():
    """延迟加载辩论引擎实例（FAIL-OPEN）。

    尝试导入 DebateEngine 并创建实例。
    需要 llm_fn 注入，无 LLM 时使用规则提取模式。

    Returns:
        DebateEngine 实例，或 None（不可用时降级）
    """
    global _debate_engine, _debate_engine_loaded
    if _debate_engine_loaded:
        return _debate_engine
    _debate_engine_loaded = True

    try:
        from debate_engine import DebateEngine  # noqa: F401

        # 无 LLM 时使用 None（debate_engine 内部降级为规则提取）
        _debate_engine = DebateEngine(
            llm_fn=None,  # 规则模式，无 LLM 调用
            config={"mode": "rule"},  # 纯规则模式
            cognitive_adapter=None,  # 无认知闭环（FAIL-OPEN）
        )
        return _debate_engine
    except ImportError:
        return None
    except Exception:
        return None


# ============================================================
# 辩论触发判断
# ============================================================

def should_run_debate(
    confidence: float,
    outcome: str,
    intent: str = "",
    domain_tag: str = "",
) -> bool:
    """判断案例是否需要触发辩论。

    触发条件（任一满足）：
      1. confidence < DEBATE_CONFIDENCE_THRESHOLD（低置信度）
      2. outcome in DEBATE_OUTCOMES（失败/部分成功）
      3. intent 含高价值关键词

    参数:
        confidence: 案例置信度
        outcome: 案例结果状态
        intent: 任务描述
        domain_tag: 领域标签

    Returns:
        True 表示应该触发辩论
    """
    # 低置信度
    if confidence < DEBATE_CONFIDENCE_THRESHOLD:
        return True

    # 失败/部分成功
    if outcome in DEBATE_OUTCOMES:
        return True

    # 高价值关键词
    intent_lower = (intent or "").lower()
    if any(kw in intent_lower for kw in HIGH_VALUE_KEYWORDS):
        return True

    return False


def is_high_value(intent: str, learned: list = None) -> bool:
    """判断案例是否为高价值（走 run_deep 而非 run_fast）。

    参数:
        intent: 任务描述
        learned: 经验教训列表

    Returns:
        True 表示高价值案例
    """
    text = (intent or "").lower()
    learned_text = " ".join(learned or []).lower()
    combined = f"{text} {learned_text}"

    return any(kw in combined for kw in HIGH_VALUE_KEYWORDS)


# ============================================================
# 辩论执行
# ============================================================

def run_debate_for_case(
    case: Any,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """为案例执行辩论，返回 debate 元数据。

    集成链路：
      1. should_run_debate() 判断是否需要辩论
      2. _load_debate_engine() 加载辩论引擎
      3. is_high_value() 决定走 run_fast 还是 run_deep
      4. 执行辩论，返回 {bull_confidence, bear_confidence, ...}

    参数:
        case: TrainingCase 对象
        force: 强制执行辩论（跳过 should_run_debate 判断）

    Returns:
        debate 元数据 dict，或 None（不可用/不需要时降级）
    """
    confidence = getattr(case, "confidence", 0.4)
    metadata = getattr(case, "metadata", None) or {}
    outcome = metadata.get("outcome", "unknown")
    intent = getattr(case, "intent", "")
    learned = getattr(case, "learned", [])

    # 判断是否需要辩论
    if not force and not should_run_debate(confidence, outcome, intent):
        return None

    # 加载辩论引擎
    engine = _load_debate_engine()
    if engine is None:
        # FAIL-OPEN: 辩论引擎不可用
        return None

    try:
        # 构建辩论 topic
        topic = intent or "未知决策"
        background = " ".join(case.actions) if hasattr(case, "actions") else ""

        # 决定走 fast 还是 deep
        high_value = is_high_value(intent, learned)

        # 执行辩论（异步转同步）
        if high_value:
            result = asyncio.run(
                engine.run_fast(topic, background)  # 先走 fast，deep 需 LLM
            )
        else:
            result = asyncio.run(
                engine.run_fast(topic, background)
            )

        # 提取 debate 元数据
        return {
            "bull_confidence": result.get("bull_confidence", 0.5),
            "bear_confidence": result.get("bear_confidence", 0.5),
            "bull_thesis": result.get("bull_thesis", ""),
            "bear_thesis": result.get("bear_thesis", ""),
            "mode": "fast" if not high_value else "fast-for-high-value",
        }

    except Exception:
        # FAIL-OPEN: 辩论执行失败
        return None


def enrich_case_with_debate(case: Any) -> Any:
    """为案例注入 debate 元数据（原地修改）。

    参数:
        case: TrainingCase 对象

    Returns:
        修改后的 case（原地修改，返回方便链式调用）
    """
    debate_meta = run_debate_for_case(case)
    if debate_meta is not None:
        if case.metadata is None:
            case.metadata = {}
        case.metadata["debate"] = debate_meta
    return case
