#!/usr/bin/env python3
"""mcp_shells/_shared/agent_mail_shadow.py — AgentMail 影子观察器（COMM-SHADOW Phase 0 + P2）

SPEC-L0-AGENT-COMM-SHADOW-v0.1 §2.1 + SPEC-L0-L1-DOMAIN-DISCOVERY-v0.1 §4.1

职责：
  - 旁路观察 L0 壳信封，归一化为 trajectory 条目并落本地 JSONL
  - 若存在 L1 域传播先验（domain_transmission_static.json），追加 l1_insights
  - P2 增强: 识别 Phase A (source=static) vs Phase B (source=neural_sde_head_infer)
    coupling 来源; 可选 DomainCouplingHead 推理, ckpt 缺失时 FAIL-OPEN 回退静态值.

硬约束（COMM-SHADOW §5.2 S1-S3）：
  S1 不触发：只写本地 JSONL，不 import / 调用任何域 agent
  S2 独立 trace：落盘 trace_id 统一 shadow- 前缀
  S3 零资源占用：无 DB / 无网络 / 无子进程，内存仅保留 max_entries 条

FAIL-OPEN：静态先验缺失或损坏、Head ckpt 缺失/推理失败、落盘失败均不影响主链路.
"""

from __future__ import annotations

import itertools
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

STATIC_TRANSMISSION_PATH = (
    Path(__file__).resolve().parent / "assets" / "domain_transmission_static.json"
)
# NeuralSDE checkpoint (Phase B Head 推理依赖; 缺失则 FAIL-OPEN)
_NEURAL_SDE_CKPT = (
    Path(__file__).resolve().parents[2]
    / "23-四层闭环自进化交易架构"
    / "data"
    / "neural_sde_v1_dim64.pt"
)
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE_PATH = _REPO_ROOT / ".workbuddy" / "agent_mail" / "trajectories.jsonl"

SHADOW_PREFIX = "shadow-"
# 一致性判定三带：≥ strong 视为应耦合已耦合；≤ weak 视为不应耦合却耦合（drift）；
# 中间带不参与判定，避免把中等先验当噪声。
STRONG_COUPLING = 0.5
WEAK_COUPLING = 0.3

# S0 观测层时序缓冲（SPEC-L0-L1-DOMAIN-DISCOVERY §4.6.4 / §4.6.7）
# 同批去重：一次 observe() 的多条目折叠为每域 1 步（路径步），避免重复时间戳污染签名。
DEFAULT_WINDOW_MINUTES = 60
DEFAULT_MAX_STEPS = 128

# 壳 source → L0 域名（SPEC-L0-MCP-PACKAGING registry 的 source 字段）
_SOURCE_TO_DOMAIN = {
    "l0.cognition.mcp": "cognition",
    "l0.semantic-39.mcp": "semantic",
    "l0.search.mcp": "search",
    "l0.rea.mcp": "rea",
    "l0.data.mcp": "data",
    "l0.eval.mcp": "eval",
    "l0.store-admin.mcp": "store-admin",
}


def _shadow_trace(trace_id: Any) -> str:
    """S2：落盘 trace_id 统一 shadow- 前缀，与主链路 trace 解耦。"""
    tid = str(trace_id or "").strip()
    if tid.startswith(SHADOW_PREFIX):
        return tid
    if tid:
        return SHADOW_PREFIX + tid
    return SHADOW_PREFIX + uuid.uuid4().hex[:16]


class AgentMailShadow:
    """壳信封旁路观察器：只读消费 + 本地落盘 + L1 静态先验一致性比对。"""

    def __init__(
        self,
        l1_transmission_path: Optional[str] = None,
        trajectory_store_path: Optional[str] = None,
        max_entries: int = 1000,
        head_infer: bool = True,
        window_minutes: int = DEFAULT_WINDOW_MINUTES,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        self._head_infer_enabled = bool(head_infer)
        self._l1_path = (
            Path(l1_transmission_path) if l1_transmission_path else STATIC_TRANSMISSION_PATH
        )
        self._store_path = (
            Path(trajectory_store_path) if trajectory_store_path else DEFAULT_STORE_PATH
        )
        self._max_entries = max(1, int(max_entries))
        self._recent: List[Dict[str, Any]] = []
        # S0：每域滑窗（内存 only，不落盘、不新增 DB/网络，仍满足 S3）
        self._window_minutes = max(1, int(window_minutes))
        self._max_steps = max(1, int(max_steps))
        self._windows: Dict[str, List[Dict[str, Any]]] = {}

    # ---------- L1 静态先验（FAIL-OPEN） ----------
    def load_transmission(self) -> Optional[Dict[str, Any]]:
        """加载静态域传播先验；缺失 / 损坏 / 结构不符一律返回 None。"""
        try:
            if not self._l1_path.exists():
                return None
            data = json.loads(self._l1_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return None
            if not isinstance(data.get("domain_transmission"), dict):
                return None
            return data
        except Exception:  # noqa: BLE001 — FAIL-OPEN 契约
            return None

    # ---------- 观察入口 ----------
    def observe(self, envelope_trajectory: Any) -> Dict[str, Any]:
        """观察一批壳信封（单条 dict 或 list），落盘并返回观察摘要。

        返回：{observed, domains, store}，若静态先验可用则追加 l1_insights。
        """
        items = (
            envelope_trajectory if isinstance(envelope_trajectory, list) else [envelope_trajectory]
        )
        batch_id = uuid.uuid4().hex[:12]
        entries = [
            self._to_entry(item, seq, batch_id)
            for seq, item in enumerate(items)
            if isinstance(item, dict)
        ]
        self._append(entries)

        result: Dict[str, Any] = {
            "observed": len(entries),
            "domains": sorted({e["agent_domain"] for e in entries}),
            "store": str(self._store_path),
        }
        summary = self.get_window_summary()
        if summary:
            result["windows"] = summary

        transmission = self.load_transmission()
        if transmission:
            block = transmission["domain_transmission"]
            l1_meta = {
                "transmission_source": transmission.get("source", "static"),
                "model_version": transmission.get("model_version", "l1-domain-coupling-v0.0"),
                "trace_id": transmission.get("trace_id", ""),
                "generated_at": transmission.get("generated_at", ""),
            }
            coupling = self._resolve_couplings(block.get("drift_coupling") or {})
            result["l1_insights"] = {
                **l1_meta,
                "coupling_consistency": self._check_coupling_consistency(entries, coupling),
                "l1_regime_match": block.get("regime"),
                "l1_state": block.get("state"),
            }
        return result

    # ---------- P2: Head 推理（FAIL-OPEN） ----------
    def _resolve_couplings(self, static_coupling: Dict[str, Any]) -> Dict[str, Any]:
        """Phase B: 尝试用 DomainCouplingHead 推理替换静态先验.

        条件: NeuralSDE ckpt 存在 + Head 可导入 + 推理无异常.
        否则 FAIL-OPEN 直接返回 static_coupling.
        """
        if not self._head_infer_enabled:
            return static_coupling
        head_result = self.head_infer_couplings()
        if head_result is None:
            return static_coupling
        # 用 Head 推理值替换 coupling (lags_min 保留静态先验)

        from dreambuddy_evolution.core.domain_coupling_head import PAIRS

        merged: Dict[str, Any] = dict(static_coupling)
        for i, (a, b) in enumerate(PAIRS):
            key = f"{a}↔{b}"
            val = float(head_result[i])
            existing = merged.get(key)
            lags = existing.get("lags_min", 30) if existing else 30
            merged[key] = {"coupling": val, "lags_min": lags}
        return merged

    def head_infer_couplings(self) -> Optional[List[float]]:
        """尝试用 NeuralSDE + DomainCouplingHead 推理 15 维 coupling.

        Returns 15 维 coupling list ∈ [0,1] 或 None (FAIL-OPEN).
        S1 硬约束: 不触发域 agent / 不在初始化时 import torch — 懒加载.
        """
        if not _NEURAL_SDE_CKPT.exists():
            return None
        try:
            import torch  # noqa: F401 — 懒加载, 避免无 GPU 环境 import 阻塞
            from dreambuddy_evolution.core.domain_coupling_head import (
                DomainCouplingHead,
                NeuralSDEHiddenExtractor,
                freeze_backbone,
                load_neural_sde_v1_dim64,
            )

            dev = "mps" if torch.backends.mps.is_available() else "cpu"
            drift_net, _ck = load_neural_sde_v1_dim64(str(_NEURAL_SDE_CKPT), device=dev)
            freeze_backbone(drift_net)
            head = DomainCouplingHead().to(dev)
            head.eval()
            # 推理 8 个点取 mean (B=16)
            extractor = NeuralSDEHiddenExtractor(drift_net, device=dev)
            sig_dim = 15
            with extractor.capture():
                _ = drift_net(
                    0.5,
                    torch.randn(16, 1, device=dev),
                    torch.randn(16, sig_dim, device=dev),
                )
            hidden = extractor.last_hidden
            coupling = head(hidden).detach().mean(dim=0).cpu().tolist()
            extractor.remove()
            return coupling
        except Exception:  # noqa: BLE001 — FAIL-OPEN
            return None

    # ---------- 查询 ----------
    def get_recent_trajectories(
        self, domain: Optional[str] = None, limit: int = 10
    ) -> List[Dict[str, Any]]:
        items = [e for e in self._recent if domain is None or e["agent_domain"] == domain]
        return items[-max(1, int(limit)) :]

    # ---------- S0 观测层：每域时序步窗口 ----------
    def get_domain_window(
        self, domain: str, window_minutes: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """取某域滑窗内的时序步（按 ts 升序，ts 严格大于窗口下界）。

        每个步 = 同一次 observe() 中该域所有条目的聚合（同批去重）。
        供 S1 的 TemporalSignatureExtractor 消费；S0 阶段不消费。
        """
        steps = self._windows.get(domain) or []
        if window_minutes is None or not steps:
            return list(steps)
        cutoff = float(steps[-1]["ts"]) - max(1, int(window_minutes)) * 60.0
        return [s for s in steps if float(s["ts"]) > cutoff]

    def get_window_summary(self) -> Dict[str, Dict[str, float]]:
        """各域窗口摘要（steps / span_sec），用于 §4.6.7 数据门禁观测。"""
        return {
            domain: {
                "steps": len(steps),
                "span_sec": round(float(steps[-1]["ts"]) - float(steps[0]["ts"]), 1),
            }
            for domain, steps in sorted(self._windows.items())
            if steps
        }

    # ---------- 策略评估（SPEC §2.1 evaluate_policy） ----------
    def evaluate_policy(
        self, policy: str, trajectories: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """V = quality / max(cost, 1)；quality 取 poe_score 均值，cost 取 messages_sent 总和。"""
        items = self._recent if trajectories is None else trajectories
        if not items:
            return {"policy": policy, "V": 0.0, "quality": 0.0, "cost": 0.0, "n": 0}
        quality = sum(float(e.get("poe_score", 0.0) or 0.0) for e in items) / len(items)
        cost = sum(float((e.get("cost") or {}).get("messages_sent", 1) or 0) for e in items)
        return {
            "policy": policy,
            "V": round(quality / max(cost, 1.0), 4),
            "quality": round(quality, 4),
            "cost": cost,
            "n": len(items),
        }

    # ---------- 报告 ----------
    def generate_report(self, days: int = 7) -> str:
        """生成影子观察周报（Markdown）。窗口按条目 ts 过滤。"""
        cutoff = time.time() - max(1, int(days)) * 86400
        items = [e for e in self._recent if float(e.get("ts", 0.0)) >= cutoff]
        lines = [f"# AgentMail Shadow Report ({days}d)", "", f"- observations: {len(items)}"]
        if not items:
            return "\n".join(lines) + "\n- (no data)\n"

        counts: Dict[str, int] = {}
        for e in items:
            counts[e["agent_domain"]] = counts.get(e["agent_domain"], 0) + 1
        lines.append("- domains: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

        ev = self.evaluate_policy("observed", items)
        lines.append(f"- V: {ev['V']} (quality={ev['quality']}, cost={ev['cost']})")

        transmission = self.load_transmission()
        if transmission:
            block = transmission["domain_transmission"]
            cc = self._check_coupling_consistency(items, block.get("drift_coupling") or {})
            lines.append(f"- l1_state: {block.get('state')} / regime: {block.get('regime')}")
            lines.append(
                f"- coupling_consistency: {cc['verdict']} (ratio={cc['consistency_ratio']})"
            )
        return "\n".join(lines) + "\n"

    # ---------- 内部 ----------
    def _to_entry(self, item: Dict[str, Any], seq: int, batch_id: str = "") -> Dict[str, Any]:
        meta = item.get("meta") or {}
        source = str(item.get("source", ""))
        domain = meta.get("domain") or _SOURCE_TO_DOMAIN.get(
            source, source.split(".")[-2] if source.count(".") >= 2 else "unknown"
        )
        return {
            "seq": seq,
            "ts": time.time(),
            "batch_id": batch_id,
            "agent_domain": domain,
            "agent_id": meta.get("agent_id", ""),
            "action": meta.get("event_type") or meta.get("action") or "",
            "cost": {
                "messages_sent": int(meta.get("messages_sent", 1) or 1),
                "latency_ms": float(meta.get("latency_ms", 0.0) or 0.0),
            },
            "cross_domain_refs": meta.get("cross_domain_refs", 0) or 0,
            "poe_score": float(meta.get("poe_score", 0.0) or 0.0),
            # 真实信封质量信号（合成轨迹无此字段时保持缺省，不影响旧数据）
            "ok": bool(item.get("ok", True)),
            "degraded": bool(item.get("degraded", False)),
            "error_code": str(item.get("error_code", "") or ""),
            "trace_id": _shadow_trace(item.get("trace_id")),
        }

    def _append(self, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            return
        self._recent.extend(entries)
        self._recent = self._recent[-self._max_entries :]
        self._ingest_windows(entries)
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            with self._store_path.open("a", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 — S3 零干扰，落盘失败不阻断主链路
            pass

    # ---------- S0 观测层：同批去重 → 每域一步 → 时间窗裁剪 ----------
    def _ingest_windows(self, entries: List[Dict[str, Any]]) -> None:
        """把本批条目折叠为每域 1 个时序步，并做时间窗 + 步数裁剪。

        硬约束：纯内存结构，不落盘 / 不新增 DB/网络（S3）；任何异常静默降级。
        """
        try:
            grouped: Dict[tuple, List[Dict[str, Any]]] = {}
            for entry in entries:
                key = (entry["agent_domain"], entry.get("batch_id", ""))
                grouped.setdefault(key, []).append(entry)

            touched = set()
            for (domain, _batch), bucket in grouped.items():
                self._windows.setdefault(domain, []).append(self._aggregate_step(bucket))
                touched.add(domain)

            for domain in touched:
                steps = sorted(self._windows[domain], key=lambda s: float(s["ts"]))
                newest = float(steps[-1]["ts"])
                cutoff = newest - self._window_minutes * 60.0
                self._windows[domain] = [s for s in steps if float(s["ts"]) > cutoff][
                    -self._max_steps :
                ]
        except Exception:  # noqa: BLE001 — S3 零干扰，观测层失败不阻断主链路
            pass

    @staticmethod
    def _aggregate_step(bucket: List[Dict[str, Any]]) -> Dict[str, Any]:
        """同批同域条目 → 1 个路径步（质量取均值，消息量取总和）。"""
        n = len(bucket)
        return {
            "ts": max(float(e.get("ts", 0.0)) for e in bucket),
            "poe_score": sum(float(e.get("poe_score", 0.0) or 0.0) for e in bucket) / n,
            "cross_domain_refs": sum(float(e.get("cross_domain_refs", 0) or 0) for e in bucket) / n,
            "messages_sent": sum(
                float((e.get("cost") or {}).get("messages_sent", 1) or 0) for e in bucket
            ),
            "latency_ms": sum(
                float((e.get("cost") or {}).get("latency_ms", 0.0) or 0.0) for e in bucket
            )
            / n,
            "n": n,
        }

    def _check_coupling_consistency(
        self, entries: List[Dict[str, Any]], drift_coupling: Dict[str, Any]
    ) -> Dict[str, Any]:
        """观察窗口内共现的域对，与静态先验三带比对（SPEC §4.1 一致性旁路）。"""
        observed = sorted({e["agent_domain"] for e in entries})
        checked: List[Dict[str, Any]] = []
        for left, right in itertools.combinations(observed, 2):
            meta = self._pair_entry(drift_coupling, left, right)
            if meta is None:
                continue
            try:
                coupling = float(meta.get("coupling", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if coupling >= STRONG_COUPLING:
                band = "strong"
            elif coupling <= WEAK_COUPLING:
                band = "weak"
            else:
                continue  # 中等先验不参与判定
            checked.append(
                {
                    "pair": f"{left}↔{right}",
                    "static_coupling": coupling,
                    "lags_min": meta.get("lags_min"),
                    "band": band,
                    "consistent": band == "strong",
                }
            )
        if not checked:
            return {
                "checked_pairs": [],
                "consistency_ratio": None,
                "verdict": "insufficient_data",
                "strong_threshold": STRONG_COUPLING,
                "weak_threshold": WEAK_COUPLING,
            }
        ratio = sum(1 for c in checked if c["consistent"]) / len(checked)
        return {
            "checked_pairs": checked,
            "consistency_ratio": round(ratio, 4),
            "verdict": "consistent" if ratio >= STRONG_COUPLING else "drift",
            "strong_threshold": STRONG_COUPLING,
            "weak_threshold": WEAK_COUPLING,
        }

    @staticmethod
    def _pair_entry(
        drift_coupling: Dict[str, Any], left: str, right: str
    ) -> Optional[Dict[str, Any]]:
        """静态先验键序不固定，双向查找。"""
        for key in (f"{left}↔{right}", f"{right}↔{left}"):
            meta = drift_coupling.get(key)
            if isinstance(meta, dict):
                return meta
        return None


__all__ = ["AgentMailShadow", "STATIC_TRANSMISSION_PATH", "DEFAULT_STORE_PATH", "SHADOW_PREFIX"]
