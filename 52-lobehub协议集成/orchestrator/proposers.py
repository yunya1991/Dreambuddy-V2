#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 4 — 双链提案方（side A / side B）。

  - SideAProposer：POST 3.1 协议层 `/api/agent/plan`（Vercel AI SDK loop 侧）
  - SideBProposer：POST DreamOS `/api/v1/intent` → plancard.from_dreamos_intent

每个 proposer 声明 `{proposer_id, model, evidence_path}`（铁律⑤多样性校验输入）。
HTTP 失败一律返回 None 并记 error，绝不抛出（编排器降级不中断）。
仅标准库（urllib.request）。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Callable

from plancard import from_dreamos_intent

DEFAULT_SIDE_A_URL = "http://127.0.0.1:3001"
DEFAULT_SIDE_B_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SEC = float(os.environ.get("PROPOSER_TIMEOUT_SEC", "15"))

# 取证路径声明（铁律⑤：双方证据路径必须差异化）
SIDE_A_EVIDENCE_PATH = "unified_search+recall"
SIDE_B_EVIDENCE_PATH = "dreamos.intent+registry"


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
    """提案方基类：声明身份 + 统一 propose 接口。"""

    proposer_id = "base"
    evidence_path = ""
    model = "unknown"

    def __init__(self, url: str | None = None, poster: Callable[..., dict] | None = None):
        self.url = (url or "").rstrip("/")
        self._post = poster or http_post_json
        self.last_error: str | None = None

    def propose(self, intent: str, context_refs: list[str] | None = None) -> dict[str, Any] | None:
        raise NotImplementedError


class SideAProposer(Proposer):
    """3.1 协议层侧：模型 + 独立取证（unified_search + recall）。"""

    proposer_id = "side_a"
    evidence_path = SIDE_A_EVIDENCE_PATH

    def __init__(
        self,
        url: str | None = None,
        poster: Callable[..., dict] | None = None,
        model_hint: str | None = None,
    ):
        super().__init__(url or os.environ.get("SIDE_A_URL", DEFAULT_SIDE_A_URL), poster)
        self.model = model_hint or os.environ.get("SIDE_A_MODEL", "unknown")

    def propose(self, intent: str, context_refs: list[str] | None = None) -> dict[str, Any] | None:
        payload: dict[str, Any] = {"intent": intent}
        if context_refs:
            payload["context_refs"] = list(context_refs)
        try:
            response = self._post(f"{self.url}/api/agent/plan", payload)
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

        if not response.get("ok"):
            self.last_error = f"side_a_degraded:{response.get('error') or 'unknown'}"
            return None
        data = response.get("data") or {}
        card = data.get("plancard") if isinstance(data, dict) else None
        if not isinstance(card, dict):
            self.last_error = "side_a_plancard_missing"
            return None
        self.model = str(data.get("model") or self.model)
        self.evidence_path = str(data.get("evidence_path") or self.evidence_path)
        self.last_error = None
        return card


class SideBProposer(Proposer):
    """DreamOS 侧：意图识别结果 → PlanCard（registry 映射）。"""

    proposer_id = "side_b"
    evidence_path = SIDE_B_EVIDENCE_PATH

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

    def propose(self, intent: str, context_refs: list[str] | None = None) -> dict[str, Any] | None:
        try:
            response = self._post(f"{self.url}/api/v1/intent", {"user_input": intent})
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

        if response.get("error"):
            self.last_error = f"side_b_error:{response.get('error')}"
            return None
        try:
            card = from_dreamos_intent(
                intent, response, allowed_tools=self.allowed_tools, context_refs=context_refs
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.last_error = f"side_b_plancard_failed:{type(exc).__name__}: {exc}"
            return None
        self.last_error = None
        return card


def build_proposers(allowed_tools: set[str]) -> list[Proposer]:
    """按 env 构造默认双提案方（离线测试可用 side-a-plancard 跳过 A 侧 HTTP）。"""
    return [
        SideAProposer(),
        SideBProposer(allowed_tools=allowed_tools),
    ]
