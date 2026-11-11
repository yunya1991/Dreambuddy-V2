"""training_ingest.py — 48 域训练入口（G1：文章/因子样本写入 48）。

职责（SPEC-EMERGENCE-FULL-CHAIN v1.0 §6 G1）：
  1. 读取 18 域因子样本（p3a dominance_agreement / p3b news_agreement）；
  2. 转换为 48 域训练样本（TrainingSample），append-only 写入
     `48-涌现架构/events/training_samples/*.jsonl`；
  3. `sample_id` 幂等（sha256 of source+doc_id+gate），重复导入不产生新行。

纪律：FAIL-OPEN（IO/解析异常降级跳过，不中断主链）；只读 18 域，不回写。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = _REPO_ROOT / "48-涌现架构" / "events" / "training_samples"
SOURCES = {
    "p3a": _REPO_ROOT / "18-数据获取中心" / "backfill" / "p3a" / "dominance_agreement.jsonl",
    "p3b": _REPO_ROOT / "18-数据获取中心" / "backfill" / "p3b" / "news_agreement.jsonl",
}
SCHEMA_VERSION = "training_sample.v0.1"
INGEST_VERSION = "training_ingest.v0.1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sample_id(source: str, row: Dict[str, Any]) -> str:
    seed = "|".join(
        [source, str(row.get("doc_id", "")), str(row.get("as_of", "")), str(row.get("gate", ""))]
    )
    return "TS-" + hashlib.sha256(seed.encode()).hexdigest()[:16]


def normalize_sample(source: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """18 域因子样本行 → 48 域 TrainingSample。"""
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": _sample_id(source, row),
        "ingested_at": _now_iso(),
        "source": source,
        "doc_id": row.get("doc_id"),
        "as_of": row.get("as_of"),
        "title": row.get("title"),
        "dominant_factor": row.get("dominant_factor"),
        "dominant_dimension": row.get("dominant_dimension"),
        "direction": row.get("direction"),
        "horizon": row.get("horizon"),
        "urgency": row.get("urgency"),
        "impact": row.get("impact"),
        "gate": row.get("gate"),
        "weight": row.get("weight"),
        "agreement": row.get("agreement"),
        "measured": {
            "top": row.get("measured_top"),
            "direction": row.get("measured_direction"),
            "z": row.get("measured_z"),
            "strength": row.get("measured_strength"),
        },
    }


def load_source_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        logger.warning("样本源缺失（跳过）: %s", path)
        return rows
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except json.JSONDecodeError:
                    logger.warning("样本行解析失败（跳过）: %s", path)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("样本源读取失败（降级）: %s %s", path, exc)
    return rows


def ingest(
    sources: Optional[Dict[str, Path]] = None, out_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """把 18 域因子样本写入 48 域训练样本目录（幂等 append-only）。"""
    srcs = sources or SOURCES
    target_dir = Path(out_dir) if out_dir else DEFAULT_OUT_DIR
    stats: Dict[str, Any] = {"ingest_version": INGEST_VERSION, "per_source": {}, "total": 0}
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("训练样本目录创建失败: %s", exc)
        return stats

    for name, path in srcs.items():
        rows = load_source_rows(Path(path))
        out_path = target_dir / f"{name}_samples.jsonl"
        existing: set = set()
        if out_path.exists():
            try:
                with out_path.open(encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                existing.add(json.loads(line).get("sample_id"))
                            except json.JSONDecodeError:
                                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("已有样本读取失败: %s %s", out_path, exc)
        appended = 0
        try:
            with out_path.open("a", encoding="utf-8") as f:
                for row in rows:
                    sample = normalize_sample(name, row)
                    if sample["sample_id"] in existing:
                        continue
                    f.write(json.dumps(sample, ensure_ascii=False) + "\n")
                    existing.add(sample["sample_id"])
                    appended += 1
        except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
            logger.warning("训练样本写入失败（降级）: %s %s", out_path, exc)
        stats["per_source"][name] = {
            "source": str(path),
            "n_rows": len(rows),
            "appended": appended,
            "total_in_file": len(existing),
        }
        stats["total"] += appended
    return stats


def main() -> int:
    stats = ingest()
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
