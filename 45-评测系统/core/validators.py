# -*- coding: utf-8 -*-
"""
validators.py — env_manifest 语义校验（P1-1）
==============================================
职责（PLAN P1-1 / SPEC §13.1「受理即拒」/ §15）：
- 结构语义：endpoints 必须可解析为 http/https URL、非空、去重
- 可达性：注入探针（默认不探测）；不可达在实盘模式即拒、影子模式只告警
- 密钥安全：secret_refs 只允许引用名，禁止明文密钥值（§15）

模式语义（P1-3「只受理不拦截」）：
- strict=True（gate.shadow=false，实盘）→ 有 finding 即抛 EnvManifestError
- strict=False（gate.shadow=true，影子）→ 仅逐条告警，照常受理
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# secret_ref 允许的引用名形态：字母数字与 _ . : / -（如 OBJ_READ_KEY / aws.prod.readonly）
_SECRET_REF_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,64}$")
# 已知密钥前缀（OpenAI / GitHub / AWS / Slack / Google）
_SECRET_PREFIXES = ("sk-", "ghp_", "gho_", "ghs_", "AKIA", "xoxb-", "xoxp-", "AIza")
# 裸令牌：20 位以上字母数字（含数字），无分隔符 —— 高概率是密钥值
_BARE_TOKEN_RE = re.compile(r"^[A-Za-z0-9+/=]{20,}$")


class EnvManifestError(Exception):
    """env_manifest 校验失败（实盘模式下拒绝受理，API 映射 400）。"""


def looks_like_plaintext_secret(value: Any) -> bool:
    """粗判明文密钥值：命中已知前缀，或无分隔符的长裸令牌（§15）。"""
    if not isinstance(value, str):
        return True
    if any(value.startswith(prefix) for prefix in _SECRET_PREFIXES):
        return True
    return bool(_BARE_TOKEN_RE.match(value)) and any(ch.isdigit() for ch in value)


class HttpProber:
    """端点可达性探针：HEAD 短超时；4xx 视为可达（服务已应答），5xx/连接失败视为不可达。"""

    def __init__(self, timeout: float = 1.0) -> None:
        self._timeout = timeout

    def __call__(self, url: str) -> bool:
        request = urllib.request.Request(url, method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return 200 <= int(getattr(response, "status", 0)) < 400
        except urllib.error.HTTPError as exc:
            return int(exc.code) < 500
        except Exception:  # noqa: BLE001 — 探针失败一律视为不可达（fail-closed）
            return False


class EnvManifestValidator:
    """env_manifest 校验器；findings 采用 `code:detail` 字符串便于观测与断言。"""

    def __init__(
        self,
        strict: bool = True,
        prober: Callable[[str], bool] | None = None,
        warn: Callable[[str], None] | None = None,
    ) -> None:
        self._strict = strict
        self._prober = prober
        self._warn = warn or (lambda finding: logger.warning("env_manifest: %s", finding))

    @property
    def strict(self) -> bool:
        return self._strict

    def check(self, manifest: Any) -> list[str]:
        """返回全部 findings（不抛异常，供指标/告警观测）。"""
        if not isinstance(manifest, dict):
            return ["env_manifest_not_object"]

        findings: list[str] = []
        findings.extend(self._check_endpoints(manifest.get("endpoints")))
        findings.extend(self._check_secret_refs(manifest.get("secret_refs")))
        return findings

    def enforce(self, manifest: Any) -> list[str]:
        """实盘模式有 finding 即拒；影子模式只告警（P1-3）。"""
        findings = self.check(manifest)
        if findings:
            if self._strict:
                raise EnvManifestError("env_manifest 校验失败: " + "; ".join(findings))
            for finding in findings:
                self._warn(finding)
        return findings

    # ---------- 内部校验 ----------

    def _check_endpoints(self, endpoints: Any) -> list[str]:
        if not isinstance(endpoints, list) or not endpoints:
            return ["endpoints_missing"]

        findings: list[str] = []
        seen: set[str] = set()
        probeable: list[str] = []
        for endpoint in endpoints:
            if not isinstance(endpoint, str) or not _is_http_url(endpoint):
                findings.append(f"endpoint_invalid:{endpoint}")
                continue
            if endpoint in seen:
                findings.append(f"endpoint_duplicate:{endpoint}")
                continue
            seen.add(endpoint)
            probeable.append(endpoint)

        if self._prober is not None:
            for endpoint in probeable:
                try:
                    reachable = bool(self._prober(endpoint))
                except Exception:  # noqa: BLE001 — 探针自身异常按不可达处理
                    reachable = False
                if not reachable:
                    findings.append(f"endpoint_unreachable:{endpoint}")
        return findings

    @staticmethod
    def _check_secret_refs(secret_refs: Any) -> list[str]:
        if secret_refs is None:
            return []
        if not isinstance(secret_refs, list):
            return ["secret_refs_not_list"]

        findings: list[str] = []
        for ref in secret_refs:
            if looks_like_plaintext_secret(ref):
                findings.append(f"secret_ref_plaintext:{ref}")
            elif not _SECRET_REF_RE.match(ref):
                findings.append(f"secret_ref_invalid:{ref}")
        return findings


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)
