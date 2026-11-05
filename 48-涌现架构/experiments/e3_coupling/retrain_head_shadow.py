"""retrain_head_shadow.py — E3 前置：DomainCouplingHead shadow 重训（SPEC v0.5 §4 E3 P0#1）。

为什么重训：生产 ckpt neural_sde_v1_dim64.pt mtime 早于 regime artifact
（btc_1h_ts.json，fetched 2026-11-04），head 是用修复前数据训的。
本脚本用最新 JSONL 标注 + 真实市场特征重训 head，产物一律落 48 域 shadow 目录。

硬约束：
  - 不调用 export_coupling_json —— 生产 static JSON 一字节不动
  - 不碰 ckpt（冻结 backbone，H2）
  - n_steps 默认 120（认知 VM-1793699143718：80-120 步收敛最佳，更多步反弹）

FAIL-OPEN：训练异常 → status=error + reason，不抛出。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
# 认知 VM-1793699143718：sys.path 必须加 dreambuddy_evolution 的父目录（23 域根）
_23_ROOT = _REPO_ROOT / "23-四层闭环自进化交易架构"
if str(_23_ROOT) not in sys.path:
    sys.path.insert(0, str(_23_ROOT))

DEFAULT_JSONL = _REPO_ROOT / ".workbuddy" / "l1_training" / "domain_discovery_training.jsonl"
STATIC_JSON = _REPO_ROOT / "mcp_shells" / "_shared" / "assets" / "domain_transmission_static.json"
DEFAULT_ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
DEFAULT_STEPS = 120


def _train_and_infer(
    n_steps: int, seed: int, jsonl_path: Path, n_windows: int
) -> Tuple[Dict[str, Any], Any]:
    """调用 23 域训练管线，返回 (result_dict, head)。隔离 import 便于测试 mock。"""

    from dreambuddy_evolution.core import train_and_export_coupling as tec  # noqa: PLC0415

    result = tec.train_head_and_infer(
        n_steps=n_steps,
        seed=seed,
        jsonl_path=Path(jsonl_path) if jsonl_path else None,
        n_windows=n_windows,
        use_real_market=True,
    )
    # train_head_and_infer 内部创建 head 但不返回——按同 seed 重建一次并载入同权重不可行，
    # 因此改为直接复跑其训练循环太重；这里用其二阶段：重新构造 head 并用 result 元信息
    # 标注。若需保存权重，优先使用 tec 内部返回的 head（新版本支持）。
    head = getattr(tec, "last_trained_head", None)
    if head is None:
        # 兼容路径：tec 未暴露 head 时，保存 result 中的 coupling 向量作为轻量产物
        return result, None
    return result, head


def retrain_shadow(
    artifacts_dir: Optional[Path] = None,
    jsonl_path: Optional[Path] = None,
    n_steps: int = DEFAULT_STEPS,
    n_windows: int = 96,
    seed: int = 42,
) -> Dict[str, Any]:
    """shadow 重训主入口。产物：coupling_head_e3_shadow.pt（可选）+ retrain_meta.json。"""
    art = Path(artifacts_dir) if artifacts_dir else DEFAULT_ARTIFACTS
    try:
        result, head = _train_and_infer(
            n_steps=n_steps,
            seed=seed,
            jsonl_path=Path(jsonl_path) if jsonl_path else DEFAULT_JSONL,
            n_windows=n_windows,
        )
        art.mkdir(parents=True, exist_ok=True)

        head_path = art / "coupling_head_e3_shadow.pt"
        head_saved = False
        if head is not None:
            import torch  # noqa: PLC0415

            torch.save(head.state_dict(), str(head_path))
            head_saved = True
        else:
            # 轻量产物：15 维 coupling 向量（评测器可直接消费）
            head_path = art / "coupling_head_e3_shadow.json"
            head_path.write_text(
                json.dumps({"coupling_15d": result.get("coupling_15d")}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        meta = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "shadow": True,
            "spec": "SPEC-EMERGENCE-EVOLUTION v0.5 §4 E3 前置重训",
            "n_steps": n_steps,
            "seed": seed,
            "n_windows": n_windows,
            "jsonl_path": str(jsonl_path or DEFAULT_JSONL),
            "final_loss": result.get("final_loss"),
            "loss_curve_tail": result.get("loss_curve", [])[-5:],
            "target_source": result.get("target_source"),
            "input_source": result.get("input_source"),
            "pseudo_target_loaded": result.get("pseudo_target_loaded"),
            "inferred": result.get("inferred"),
            "regime_counts": (result.get("input_meta") or {}).get("regime_counts"),
            "coupling_15d": result.get("coupling_15d"),
            "head_artifact": head_path.name,
            "head_state_dict_saved": head_saved,
            "production_static_json_untouched": True,
        }
        (art / "retrain_meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {"status": "ok", "artifacts": str(art), "meta": meta}
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("retrain_shadow 失败: %s", exc)
        return {"status": "error", "reason": str(exc)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="E3 DomainCouplingHead shadow 重训")
    parser.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    parser.add_argument("--n-windows", type=int, default=96)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--jsonl", type=str, default=None)
    args = parser.parse_args()
    out = retrain_shadow(
        jsonl_path=Path(args.jsonl) if args.jsonl else None,
        n_steps=args.steps,
        n_windows=args.n_windows,
        seed=args.seed,
    )
    print(json.dumps(out.get("meta", out), ensure_ascii=False, indent=2))
