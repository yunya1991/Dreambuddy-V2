"""因子敏感度契约 — SPEC-D1-MULTIDIM-STATE §2.9.2 / §2.9.7。

本模块只固化「规则」，不跑事件研究（数据侧由 P3-c1 脚本调用）：

  补丁① 双窗口同号
    pre / post 两个窗口的超额收益必须同号且都过阈值，才可进入正向因子池；
    反向记 reversal —— 只保留「反转敏感」标签，不进正向池（P3-b2 已见 24h fade）。

  补丁② 禁止自证
    walk-forward 切分带 embargo，train 严格早于 test，禁止训练集内验证。
    主/次矛盾的 bull_S/bear_S 必须用这套切分做样本外检验。

  补丁③ 涌现三要素
    变异算子 / 适应度 / 选择压力未定义前不得启用反思层（见 SPEC §2.9.8），
    本模块不提供实现，只提供 REQUIRED_EMERGENCE_KEYS 供门禁检查。

FAIL-OPEN：异常返回保守结果（weak / 空切分），不抛。
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger("data_center.processing.factor_sensitivity")

# 单日超额收益阈值：低于该幅度视为无信号（约 5bp）
SENSITIVITY_THRESHOLD = 0.0005

# 补丁③：反思层启用前必须齐备的三要素
REQUIRED_EMERGENCE_KEYS = ("variation", "fitness", "selection")

VERDICT_POSITIVE = "positive"
VERDICT_REVERSAL = "reversal"
VERDICT_WEAK = "weak"


def classify_sensitivity(
    pre_excess: Any, post_excess: Any, threshold: float = SENSITIVITY_THRESHOLD
) -> dict:
    """补丁①：pre/post 双窗口同号判定。

    → {verdict, eligible, direction}
      positive : 同号且都过阈值 → 可进正向因子池，direction = ±1
      reversal : 异号 → 只记「反转敏感」，eligible=False
      weak     : 任一不过阈值 / 非法输入 → 无信号
    """
    zero = {"verdict": VERDICT_WEAK, "eligible": False, "direction": 0}
    try:
        pre = float(pre_excess)
        post = float(post_excess)
    except (TypeError, ValueError):
        return zero
    if abs(pre) < threshold or abs(post) < threshold:
        return zero
    if pre > 0 and post > 0:
        return {"verdict": VERDICT_POSITIVE, "eligible": True, "direction": 1}
    if pre < 0 and post < 0:
        return {"verdict": VERDICT_POSITIVE, "eligible": True, "direction": -1}
    return {"verdict": VERDICT_REVERSAL, "eligible": False, "direction": 0}


def walk_forward_split(dates: Iterable[Any], n_folds: int = 4, embargo: int = 1) -> list[dict]:
    """补丁②：时间序列 walk-forward 切分（带 embargo）。

    train 只含 test 起点之前、且中间空出 embargo 个观测日的样本，
    保证 train 严格早于 test，不泄漏未来。FAIL-OPEN → []。
    """
    try:
        ds = sorted({str(d)[:10] for d in dates if str(d)})
        if n_folds < 2 or len(ds) < n_folds * 2:
            return []
        fold = len(ds) // n_folds
        out: list[dict] = []
        for k in range(n_folds):
            lo = k * fold
            hi = len(ds) if k == n_folds - 1 else (k + 1) * fold
            train_end = max(0, lo - embargo)
            out.append({"train": tuple(ds[:train_end]), "test": tuple(ds[lo:hi])})
        return out
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] walk_forward_split %s: %s", type(e).__name__, str(e)[:120])
        return []


def validate_no_leakage(folds: Any) -> bool:
    """补丁②：校验切分无泄漏（train 与 test 无交集，且 train 全早于 test）。"""
    try:
        if not isinstance(folds, list):
            return False
        for f in folds:
            train = tuple(f.get("train") or ())
            test = tuple(f.get("test") or ())
            if not test:
                return False
            if set(train) & set(test):
                return False
            if train and max(train) >= min(test):
                return False
        return True
    except Exception:  # noqa: BLE003  FAIL-OPEN
        return False


def emergence_ready(definition: Any) -> dict:
    """补丁③：反思层启用门禁——三要素是否都已定义。

    → {ready, missing}
    """
    try:
        d = definition if isinstance(definition, dict) else {}
        missing = [k for k in REQUIRED_EMERGENCE_KEYS if not str(d.get(k) or "").strip()]
        return {"ready": not missing, "missing": missing}
    except Exception:  # noqa: BLE003  FAIL-OPEN
        return {"ready": False, "missing": list(REQUIRED_EMERGENCE_KEYS)}
