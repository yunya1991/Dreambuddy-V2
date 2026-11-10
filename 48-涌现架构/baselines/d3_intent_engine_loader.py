"""D3-A 基线 B1/B2：DreamOS IntentEngine 轻量导入器（P1-3）。

用途：
  D3-A 实验需要把 DreamOS IntentEngine 作为基线 B1（规则层）/ B2（全链路）。
  IntentEngine 位于 `1-ARCHITECTURE/dreamos/core/sense/intent_engine.py`，
  但 `dreamos/__init__.py` 在包初始化时导入 `apps`（依赖 Flask），
  因此导入前需把 `1-ARCHITECTURE` 加入 sys.path 并确保 flask 已装。

本模块不改 DreamOS 包结构，仅提供轻量导入路径：

    from baselines.d3_intent_engine_loader import load_intent_engine

    engine = load_intent_engine(use_llm_based=False)  # B1 规则层，无需 LLM
    result = engine.recognize(user_message="分析BTC趋势")

退出条件（P1-3）：IntentEngine 可导入 + smoke 可跑（见本文件 `smoke()`）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 1-ARCHITECTURE 是 dreamos 包的父目录
REPO_ROOT = Path(__file__).resolve().parents[2]
ARCH_DIR = REPO_ROOT / "1-ARCHITECTURE"
if str(ARCH_DIR) not in sys.path:
    sys.path.insert(0, str(ARCH_DIR))


def _check_flask() -> None:
    try:
        import flask  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "IntentEngine 导入需要 flask（dreamos 包初始化时导入 apps.api_server）。\n"
            "  安装：pip install -r 48-涌现架构/baselines/requirements-d3.txt"
        ) from exc


def load_intent_engine(use_llm_based: bool = False, **kwargs):
    """导入并实例化 IntentEngine。

    默认 `use_llm_based=False`（B1 规则基线，零 Token、无需 API key）。
    如需 B2 全链路（含 LLM 识别器），传 `use_llm_based=True` 并配置 DEEPSEEK_API_KEY。
    """
    _check_flask()
    from dreamos.core.sense.intent_engine import IntentEngine

    return IntentEngine(use_llm_based=use_llm_based, **kwargs)


def smoke() -> bool:
    """P1-3 退出条件验证：IntentEngine 可导入 + recognize 可调用。"""
    engine = load_intent_engine(use_llm_based=False)
    result = engine.recognize(
        user_message="分析BTC趋势",
        market={"price": 50000, "rsi14": 45, "change_24h": 2.5},
    )
    ok = bool(getattr(result, "intent_type", None))
    print(
        f"[d3-loader] smoke intent_type={result.intent_type} "
        f"confidence={result.confidence} ok={ok}"
    )
    return ok


if __name__ == "__main__":
    sys.exit(0 if smoke() else 1)
