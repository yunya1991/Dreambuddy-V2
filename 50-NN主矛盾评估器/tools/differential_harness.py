"""R0-04 differential harness：同输入 23(control) vs 50(treatment) 逐字段 diff，产出分歧率基线。
R2 的 A/B 只解释相对此基线的增量，不解释绝对值。
R0-04 扩展：23 层冻结快照固化（fixtures/control_snapshots/，上限 20 组）与 path 集合转换。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

DIFF_FIELDS = ("direction", "confidence", "dimension", "horizon", "intent", "continuation_score")

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTROL_SNAPSHOT_DIR = REPO_ROOT / "fixtures" / "control_snapshots"
MAX_CONTROL_SNAPSHOTS = 20

# 23 层快照源路径（只读，不侵入 23 系统）
_23_SNAPSHOT_PATH = (
    REPO_ROOT.parent / "23-四层闭环自进化交易架构" / "dreambuddy_evolution" / "gene_data" / "evolution_snapshots.json"
)


def diff_path_sets(control: list[dict], treatment: list[dict]) -> dict:
    c_map = {p["path_id"]: p for p in control}
    t_map = {p["path_id"]: p for p in treatment}
    only_control = sorted(set(c_map) - set(t_map))
    only_treatment = sorted(set(t_map) - set(c_map))
    field_diffs = []
    for path_id in sorted(set(c_map) & set(t_map)):
        for field in DIFF_FIELDS:
            c_val = c_map[path_id].get(field)
            t_val = t_map[path_id].get(field)
            if c_val != t_val:
                field_diffs.append(
                    {
                        "path_id": path_id,
                        "field": field,
                        "control": c_val,
                        "treatment": t_val,
                    }
                )
    total = len(set(c_map) | set(t_map))
    diff_count = len(only_control) + len(only_treatment) + len(field_diffs)
    divergence_rate = round(diff_count / total, 6) if total else 0.0
    return {
        "only_control": only_control,
        "only_treatment": only_treatment,
        "field_diffs": field_diffs,
        "divergence_rate": divergence_rate,
    }


def load_23_snapshot(path: str | Path | None = None) -> dict:
    """只读加载 23 层 evolution_snapshots.json（fail-open，异常返回空 dict）。"""
    target = Path(path) if path else _23_SNAPSHOT_PATH
    try:
        if not target.exists():
            return {}
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def freeze_control_snapshot(snapshot: dict, label: str | None = None) -> str:
    """将 23 层快照固化为 control 基线（时间戳命名，上限 20 组，超出删最旧）。"""
    if not isinstance(snapshot, dict) or not snapshot:
        raise ValueError("snapshot 为空，拒绝固化")
    CONTROL_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    tag = re.sub(r"[^A-Za-z0-9_-]+", "_", str(label)) if label else now.strftime("%Y%m%dT%H%M%SZ")
    out = CONTROL_SNAPSHOT_DIR / ("control_{}.json".format(tag))
    payload = {
        "_meta": {
            "frozen_at": now.isoformat(),
            "coin_count": len(snapshot),
            "schema_version": "1",
        },
        "coins": snapshot,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_old_snapshots()
    return str(out)


def _prune_old_snapshots() -> None:
    files = sorted(f for f in CONTROL_SNAPSHOT_DIR.glob("control_*.json"))
    while len(files) > MAX_CONTROL_SNAPSHOTS:
        files.pop(0).unlink()


def load_control_snapshot(name: str) -> dict:
    """按文件名（不含扩展名）加载已冻结的 control 快照。"""
    target = CONTROL_SNAPSHOT_DIR / ("{}.json".format(name))
    if not target.exists():
        raise FileNotFoundError("control 快照不存在: {}".format(target))
    return json.loads(target.read_text(encoding="utf-8"))


def to_path_set(snapshot: dict) -> list[dict]:
    """将 23 层快照（币 → 状态）转换为与 50 层 path_synthesis 输出同构的 path 集合。

    字段映射：action→direction；u_open→confidence/continuation_score；
    dimension=D3（23 技术层）；horizon=hours；intent=trend。
    """
    paths = []
    for coin, state in (snapshot or {}).items():
        if not isinstance(state, dict):
            continue
        action = str(state.get("action") or "neutral").strip().lower()
        direction = "long" if action == "long" else ("short" if action == "short" else "flat")
        try:
            u_open = float(state.get("u_open", 0.0) or 0.0)
        except (TypeError, ValueError):
            u_open = 0.0
        confidence = max(0.0, min(1.0, u_open))
        paths.append(
            {
                "path_id": "23-{}".format(coin),
                "direction": direction,
                "confidence": round(confidence, 4),
                "continuation_score": round(confidence, 4),
                "dimension": "D3",
                "horizon": "hours",
                "intent": "trend",
            }
        )
    return paths
