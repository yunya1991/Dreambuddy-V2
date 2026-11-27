"""P0-A 成交身份契约（SPEC-20261127-winrate-diagnosis-optimization §6）。

目标：让每笔已平仓成交能回答「谁出的信号、什么模式、哪版代码、如何关联」。
本模块只负责生成/迁移身份字段，不做任何交易决策。

字段口径：
- source_system：信号/策略来源。11-bcrm=纯 BCRM 推理；11-bdsm=BDSM 子池；
  23-evolution=23 自进化域；11-unknown=11 域内但无法细分；"" = 历史未归属（UNKNOWN）。
- mode：shadow / live。
- git_sha：写入时代码版本。
- config_hash / signal_id：无可靠来源时留空，禁止猜测回填。
- trade_id：持仓记录唯一 ID，用于开仓—平仓—复盘关联。
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # 11-易经推理系统

# trades 表新增身份列（model_version / fold_id 已存在）
IDENTITY_COLUMNS = (
    "source_system",
    "mode",
    "git_sha",
    "config_hash",
    "signal_id",
    "trade_id",
)


@lru_cache(maxsize=1)
def current_git_sha() -> str:
    """当前代码版本；失败返回空串（fail-open，不阻断交易记录）。"""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def classify_source(
    *,
    source_tag: str = "",
    domain_tag: str = "",
    strategy_source: str = "",
) -> str:
    """把持仓上下文映射为稳定来源标识；无法判断时返回 11-unknown，不留空。"""
    if str(domain_tag or "") == "23域":
        return "23-evolution"
    tag = str(source_tag or "").strip().lower()
    if tag in {"bdsm", "bcrm"}:
        return f"11-{tag}"
    strategy = str(strategy_source or "").strip().lower()
    if strategy and strategy != "bcrm":
        # 外部策略（马丁等）不并入 11 模型口径
        return f"external-{strategy}"
    return "11-unknown"


def build_identity(trade: Any, *, shadow_mode: bool = False) -> Dict[str, str]:
    """从 TradeRecord 提取身份字段；缺失一律空串，由下游按 UNKNOWN 处理。"""
    return {
        "source_system": classify_source(
            source_tag=getattr(trade, "source_tag", "") or "",
            domain_tag=getattr(trade, "domain_tag", "") or "",
            strategy_source=getattr(trade, "strategy_source", "") or "",
        ),
        "mode": "shadow" if shadow_mode else "live",
        "git_sha": current_git_sha(),
        "config_hash": str(getattr(trade, "config_hash", "") or ""),
        "signal_id": str(getattr(trade, "signal_id", "") or ""),
        "trade_id": str(getattr(trade, "trade_id", "") or ""),
    }
