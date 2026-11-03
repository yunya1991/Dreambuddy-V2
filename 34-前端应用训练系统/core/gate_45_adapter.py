# -*- coding: utf-8 -*-
"""45 业务门禁适配器(T-DSH-P2 P2-1)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 P2·验收(45 业务门禁接为硬门,先 shadow 转正)
+ DD4(45 先 shadow,误拦率 <5% 转硬门) + ADR-6(验收外置,Worker 不自证)
+ ADR-8/H2(开关默认关,关断字节等价) + 45-评测系统/api/routes.py 契约
(异步两段式: POST submit 202 → GET poll verdict PASS/BLOCK/INCONCLUSIVE)。

定位: 产出 l0_foundation.settle 的 gate callable。适配器只做「提交→轮询→
裁决结构化」,不做业务判定;submit_fn/poll_fn 由调用侧注入(生产接 45 HTTP
:8790,测试注入 in-process fake),本模块不持网络与存储。

裁决语义:
  shadow: 评测执行、裁决记录,一律放行(P0 语义延续,供误拦率统计)
  hard:   PASS 放行;BLOCK/INCONCLUSIVE/TIMEOUT/ERROR 拦截(fail-closed,
          与 settle「门禁异常按 fail-closed」一致,避免无凭证沉淀)
  开关 enable_gate_45_hard 默认关: 关断时 config.mode=hard 也按 shadow 放行
  FAIL-OPEN: config 非法 → build 返回 None(调用侧退回无门禁,等价升级不存在)
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple

# 模块化开关(H2,默认 False)
GATE_45_HARD_SWITCH = "enable_gate_45_hard"

_MODES = ("shadow", "hard")
_DECIDED_VERDICTS = ("PASS", "BLOCK", "INCONCLUSIVE")

GateFn = Callable[[Dict[str, Any]], Tuple[bool, Dict[str, Any]]]


def is_gate_45_hard_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(H2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(GATE_45_HARD_SWITCH, False))
    except Exception:
        return False


def build_gate_45(
    config: Any,
    flags: Optional[Dict[str, Any]] = None,
) -> Optional[GateFn]:
    """构建 45 门禁 gate callable。非法配置 → None(FAIL-OPEN,退回无门禁)。

    config 必填:
      mode: "shadow" | "hard"
      submit_fn: callable(context) -> eval_id(str)
      poll_fn:   callable(eval_id) -> dict(含 verdict 或 status)
    可选:
      timeout_s(默认 30) / poll_interval_s(默认 0.5)
    flags: 模块化开关;enable_gate_45_hard 关断时 hard 退化为 shadow(H2)。
    """
    try:
        if not isinstance(config, dict):
            return None
        mode = config.get("mode")
        if mode not in _MODES:
            return None
        submit_fn = config.get("submit_fn")
        poll_fn = config.get("poll_fn")
        if not callable(submit_fn) or not callable(poll_fn):
            return None
        timeout_s = float(config.get("timeout_s", 30.0))
        poll_interval_s = float(config.get("poll_interval_s", 0.5))
    except Exception:
        return None

    # H2: 开关关断 → hard 退化为 shadow(字节等价现有 shadow 行为)
    effective_mode = mode
    if mode == "hard" and not is_gate_45_hard_enabled(flags):
        effective_mode = "shadow"

    def gate(context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        ctx = context if isinstance(context, dict) else {}
        verdict: Dict[str, Any] = {
            "verdict": None,
            "eval_id": None,
            "evidence_uri": None,
            "trace_id": ctx.get("trace_id"),
            "mode": effective_mode,
        }
        try:
            verdict["eval_id"] = submit_fn(ctx)
        except Exception:
            verdict["verdict"] = "ERROR"
            return _decide(effective_mode, verdict)

        deadline = time.monotonic() + timeout_s
        while True:
            try:
                report = poll_fn(verdict["eval_id"]) or {}
            except Exception:
                verdict["verdict"] = "ERROR"
                return _decide(effective_mode, verdict)
            if not isinstance(report, dict):
                report = {}
            v = report.get("verdict")
            if v in _DECIDED_VERDICTS:
                verdict["verdict"] = v
                verdict["evidence_uri"] = report.get("evidence_uri")
                return _decide(effective_mode, verdict)
            if time.monotonic() >= deadline:
                verdict["verdict"] = "TIMEOUT"
                return _decide(effective_mode, verdict)
            if poll_interval_s > 0:
                time.sleep(poll_interval_s)

    return gate


def _decide(mode: str, verdict: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """shadow 一律放行;hard 仅 PASS 放行(其余 fail-closed 拦截)。"""
    if mode == "shadow":
        return True, verdict
    return verdict.get("verdict") == "PASS", verdict
