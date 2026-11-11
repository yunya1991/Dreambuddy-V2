#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 4.5 — 双链提案方（side A / side B，各发散 N 张）。

  - SideAProposer：POST 3.1 协议层 `/api/agent/plan` N 次，variant.focus 轮转
  - SideBProposer：POST DreamOS `/api/v1/intent` 一次，再按 variant 派生 N 张 PlanCard

每个 proposer 声明 `{proposer_id, model, evidence_path, model_kind}`
（铁律⑤多样性校验输入）。HTTP 失败一律记入 `last_errors` 并跳过该变体，
绝不抛出（编排器降级不中断）。
仅标准库（urllib.request）。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from plancard import describe_variant, from_dreamos_intent

DEFAULT_SIDE_A_URL = "http://127.0.0.1:3001"
DEFAULT_SIDE_B_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SEC = float(os.environ.get("PROPOSER_TIMEOUT_SEC", "60"))

# 取证路径声明（铁律⑤：双方证据路径必须差异化）
SIDE_A_EVIDENCE_PATH = "unified_search+recall"
SIDE_B_EVIDENCE_PATH = "dreamos.intent+registry"

# side-A 变体聚焦轮转（SPEC §7.7.1）
FOCUS_ROTATION = ("risk-first", "cost-first", "speed-first")


def http_post_json(
    url: str, payload: dict[str, Any], timeout: float = DEFAULT_TIMEOUT_SEC
) -> dict[str, Any]:
    """POST JSON → 解析 JSON 响应。网络/解析错误向上抛，由调用方降级。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — 内网固定 URL
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("response_not_object")
    return parsed


class Proposer:
    """提案方基类：声明身份 + 统一 propose 接口（返回 0-N 张卡）。"""

    proposer_id = "base"
    evidence_path = ""
    model = "unknown"
    model_kind = "unknown"

    def __init__(self, url: str | None = None, poster: Callable[..., dict] | None = None):
        self.url = (url or "").rstrip("/")
        self._post = poster or http_post_json
        self.last_error: str | None = None
        self.last_errors: list[str] = []

    def propose(
        self, intent: str, context_refs: list[str] | None = None, n: int = 1
    ) -> list[dict[str, Any]]:
        """返回 [{"card", "variant", "selection_basis"}]；失败项为空列表。"""
        raise NotImplementedError


class SideAProposer(Proposer):
    """3.1 协议层侧：模型 + 独立取证（unified_search + recall），N 次变体调用。"""

    proposer_id = "side_a"
    evidence_path = SIDE_A_EVIDENCE_PATH
    model_kind = "llm"

    def __init__(
        self,
        url: str | None = None,
        poster: Callable[..., dict] | None = None,
        model_hint: str | None = None,
    ):
        super().__init__(url or os.environ.get("SIDE_A_URL", DEFAULT_SIDE_A_URL), poster)
        self.model = model_hint or os.environ.get("SIDE_A_MODEL", "unknown")

    def propose(
        self, intent: str, context_refs: list[str] | None = None, n: int = 1
    ) -> list[dict[str, Any]]:
        """调用 `/api/agent/plan` N 次；单次失败仅记 error，不整体失败。"""
        self.last_errors = []
        results: list[dict[str, Any]] = []
        for index in range(max(1, n)):
            focus = FOCUS_ROTATION[index % len(FOCUS_ROTATION)]
            payload: dict[str, Any] = {
                "intent": intent,
                "variant": {"focus": focus, "seed": index},
            }
            if context_refs:
                payload["context_refs"] = list(context_refs)
            try:
                response = self._post(f"{self.url}/api/agent/plan", payload)
            except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
                self.last_errors.append(f"variant_{index}:{type(exc).__name__}: {exc}")
                continue

            if not response.get("ok"):
                self.last_errors.append(
                    f"variant_{index}:side_a_degraded:{response.get('error') or 'unknown'}"
                )
                continue
            data = response.get("data") or {}
            card = data.get("plancard") if isinstance(data, dict) else None
            if not isinstance(card, dict):
                self.last_errors.append(f"variant_{index}:side_a_plancard_missing")
                continue
            self.model = str(data.get("model") or self.model)
            self.evidence_path = str(data.get("evidence_path") or self.evidence_path)
            results.append(
                {
                    "card": card,
                    "variant": index,
                    "selection_basis": f"focus={focus}, seed={index}",
                }
            )
        self.last_error = self.last_errors[-1] if self.last_errors else None
        return results


class SideBProposer(Proposer):
    """DreamOS 侧：意图识别结果 → N 张变体 PlanCard（registry 映射）。"""

    proposer_id = "side_b"
    evidence_path = SIDE_B_EVIDENCE_PATH
    model_kind = "deterministic_planner"

    def __init__(
        self,
        url: str | None = None,
        poster: Callable[..., dict] | None = None,
        allowed_tools: set[str] | None = None,
        model_hint: str | None = None,
    ):
        super().__init__(url or os.environ.get("SIDE_B_URL", DEFAULT_SIDE_B_URL), poster)
        self.allowed_tools = set(allowed_tools or ())
        self.model = model_hint or os.environ.get("SIDE_B_MODEL", "dreamos-intent-engine")

    def propose(
        self, intent: str, context_refs: list[str] | None = None, n: int = 1
    ) -> list[dict[str, Any]]:
        """只调 DreamOS 一次，再按 variant 派生（0=完整链 / 1=base / ≥2=反转 extend）。"""
        self.last_errors = []
        try:
            response = self._post(f"{self.url}/api/v1/intent", {"user_input": intent})
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_errors.append(f"{type(exc).__name__}: {exc}")
            self.last_error = self.last_errors[-1]
            return []

        if response.get("error"):
            self.last_errors.append(f"side_b_error:{response.get('error')}")
            self.last_error = self.last_errors[-1]
            return []

        results: list[dict[str, Any]] = []
        for index in range(max(1, n)):
            try:
                card = from_dreamos_intent(
                    intent,
                    response,
                    allowed_tools=self.allowed_tools,
                    context_refs=context_refs,
                    variant=index,
                )
            except (KeyError, TypeError, ValueError) as exc:
                self.last_errors.append(
                    f"variant_{index}:side_b_plancard_failed:{type(exc).__name__}: {exc}"
                )
                continue
            results.append(
                {
                    "card": card,
                    "variant": index,
                    "selection_basis": describe_variant(response, index),
                }
            )
        self.last_error = self.last_errors[-1] if self.last_errors else None
        return results


def build_proposers(allowed_tools: set[str]) -> list[Proposer]:
    """按 env 构造默认双提案方（离线测试可用 side-a-plancard 跳过 A 侧 HTTP）。"""
    return [
        SideAProposer(),
        SideBProposer(allowed_tools=allowed_tools),
    ]
