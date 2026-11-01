# -*- coding: utf-8 -*-
"""
evidence.py — 证据哈希链 / Merkle 根 / 证据包签名（P4-1）
========================================================
职责（PLAN P4-1 / SPEC §12 / §14.4）：
- 哈希链：hash = sha256(prev_hash || sha256 || uri)，首条 prev_hash=None
- Merkle 根：RFC 6962 思路（叶子 H(0x00||hash)、节点 H(0x01||L||R)、
  空树 H("")、奇数叶按最大 2 的幂切分）
- 证据包（bundle）：证据链 + 报告 JSON + Merkle 根 + HMAC-SHA256 签名，
  可离线验证（不依赖 PG / 服务端）
- 签名密钥仅从 secret 注入（`EVAL_EVIDENCE_KEY`），不落盘、不进 bundle

边界：
- 本层不做 WORM 存储（P4-2）；uri 仍为 local:// 占位
- 签名算法取 HMAC-SHA256（§13.3 回调同族，由 `secret_ref` 注入）；
  Sigstore/in-toto 签名属后续升级项
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from storage.repo import EvidenceRow, canonical_json, sha256_hex, zulu

logger = logging.getLogger(__name__)

BUNDLE_VERSION = "evidence_bundle.v1"
DEFAULT_SIGNER = "45-evidence"

_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"


class EvidenceError(Exception):
    """证据包构建失败：未知 eval_id / 无报告等。"""


# ---------- 哈希链 ----------


def chain_hash(prev_hash: str | None, sha256: str, uri: str) -> str:
    """链哈希（与 core/reporter.py 既有公式一致）。"""
    return sha256_hex(f"{prev_hash or 'null'}|{sha256}|{uri}")


def append_entry(
    repo: Any,
    run_id: str,
    payload: Any,
    *,
    uri: str | None = None,
    signed_by: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> EvidenceRow:
    """规范化 payload → 证据链条目并入库（自动链接 prev_hash）。"""
    content_sha = sha256_hex(canonical_json(payload))
    seq = repo.count_evidence(run_id) + 1
    evidence_id = f"EVD-{run_id}-{seq:02d}"
    uri = uri or f"local://evidence/{evidence_id}"
    prev_hash = repo.latest_evidence_hash(run_id)
    entry = EvidenceRow(
        evidence_id=evidence_id,
        run_id=run_id,
        sha256=content_sha,
        uri=uri,
        prev_hash=prev_hash,
        hash=chain_hash(prev_hash, content_sha, uri),
        signed_by=signed_by,
        created_at=(clock or _utcnow)(),
    )
    repo.insert_evidence(entry)
    return entry


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _field(entry: Any, name: str) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(name)
    return getattr(entry, name)


@dataclass(frozen=True)
class ChainVerification:
    """哈希链验证结果。"""

    ok: bool
    reasons: list[str]
    head: str | None
    count: int


def verify_chain(entries: Sequence[Any]) -> ChainVerification:
    """逐条重算链哈希并校验前向链接；返回 fail-closed 结论。"""
    reasons: list[str] = []
    prev: str | None = None
    for index, entry in enumerate(entries):
        evidence_id = _field(entry, "evidence_id")
        prev_hash = _field(entry, "prev_hash")
        sha = _field(entry, "sha256")
        uri = _field(entry, "uri")
        link = _field(entry, "hash")
        if prev_hash != prev:
            reasons.append(f"chain:prev_hash_mismatch@{index}:{evidence_id}")
        if chain_hash(prev_hash, sha, uri) != link:
            reasons.append(f"chain:hash_mismatch@{index}:{evidence_id}")
        prev = link
    return ChainVerification(ok=not reasons, reasons=reasons, head=prev, count=len(entries))


# ---------- Merkle 根（RFC 6962 思路） ----------


def _leaf_digest(hex_digest: str) -> bytes:
    return hashlib.sha256(_LEAF_PREFIX + bytes.fromhex(hex_digest)).digest()


def _node_digest(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(_NODE_PREFIX + left + right).digest()


def _largest_power_of_two_below(n: int) -> int:
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _mth(leaves: list[bytes]) -> bytes:
    n = len(leaves)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return _leaf_digest(leaves[0].hex())
    k = _largest_power_of_two_below(n)
    return _node_digest(_mth(leaves[:k]), _mth(leaves[k:]))


def merkle_root(leaf_hashes: Sequence[str]) -> str:
    """证据链哈希 → Merkle 根（日终归档用，顺序敏感）。"""
    return _mth([bytes.fromhex(h) for h in leaf_hashes]).hex()


# ---------- 证据包与签名 ----------


def _sign_payload(bundle: Mapping[str, Any]) -> str:
    """签名载荷：去除 signature 字段后的规范化 JSON。"""
    return canonical_json({k: v for k, v in bundle.items() if k != "signature"})


def compute_signature(bundle: Mapping[str, Any], key: str) -> str:
    """HMAC-SHA256(sign_payload)。"""
    return hmac.new(
        key.encode("utf-8"), _sign_payload(bundle).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _entry_to_dict(entry: EvidenceRow) -> dict[str, Any]:
    return {
        "evidence_id": entry.evidence_id,
        "run_id": entry.run_id,
        "sha256": entry.sha256,
        "uri": entry.uri,
        "prev_hash": entry.prev_hash,
        "hash": entry.hash,
        "signed_by": entry.signed_by,
        "created_at": zulu(entry.created_at),
    }


def build_bundle(
    repo: Any,
    eval_id: str,
    *,
    key: str | None = None,
    signer: str | None = None,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """从仓内报告 + 证据链构建可离线验证的证据包。

    key 缺省时不签名（P0 兼容语义）；配置 key 后写入 HMAC-SHA256 签名。
    """
    report = repo.get_report(eval_id)
    if report is None:
        raise EvidenceError(f"未知 eval_id 或尚未出分: {eval_id}")

    entries = [_entry_to_dict(e) for e in repo.list_evidence(report["run_id"])]
    chain_head = entries[-1]["hash"] if entries else None
    bundle: dict[str, Any] = {
        "version": BUNDLE_VERSION,
        "eval_id": eval_id,
        "run_id": report["run_id"],
        "chain": entries,
        "chain_head": chain_head,
        "merkle_root": merkle_root([e["hash"] for e in entries]),
        "report_sha256": sha256_hex(canonical_json(report)),
        "report": report,
        "created_at": zulu((clock or _utcnow)()),
        "signature": None,
    }
    if key:
        bundle["signature"] = {
            "alg": "HMAC-SHA256",
            "signed_by": signer or DEFAULT_SIGNER,
            "value": compute_signature(bundle, key),
        }
    return bundle


@dataclass(frozen=True)
class BundleVerification:
    """离线验证结果。"""

    ok: bool
    reasons: list[str]
    signed: bool


def verify_bundle(
    bundle: Mapping[str, Any],
    key: str | None = None,
    *,
    require_signature: bool = False,
) -> BundleVerification:
    """离线验证证据包：版本 → 哈希链 → 链头 → Merkle 根 → 报告 → 签名。"""
    reasons: list[str] = []

    if bundle.get("version") != BUNDLE_VERSION:
        reasons.append(f"version_mismatch:{bundle.get('version')}")

    chain = list(bundle.get("chain") or [])
    chain_result = verify_chain(chain)
    reasons.extend(chain_result.reasons)

    head = chain[-1]["hash"] if chain else None
    if bundle.get("chain_head") != head:
        reasons.append("chain_head_mismatch")
    if bundle.get("merkle_root") != merkle_root([e["hash"] for e in chain]):
        reasons.append("merkle_root_mismatch")

    report = bundle.get("report")
    if report is None:
        reasons.append("report_missing")
    else:
        if bundle.get("report_sha256") != sha256_hex(canonical_json(report)):
            reasons.append("report_sha256_mismatch")

    signature = bundle.get("signature")
    signed = False
    if signature is not None:
        if key is None:
            reasons.append("missing_key:签名存在但未提供密钥")
        elif not _constant_time_equal(signature.get("value", ""), compute_signature(bundle, key)):
            reasons.append("signature_mismatch")
        else:
            signed = True
    elif require_signature:
        reasons.append("unsigned_bundle:证据包缺少签名")

    return BundleVerification(ok=not reasons, reasons=reasons, signed=signed)


def _constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
