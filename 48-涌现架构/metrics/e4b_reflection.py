"""e4b_reflection.py — E4b 埋点③：自指纠错率（SPEC v0.5 §4 E4b / P1 M4）。

口径：反思 → 实际修复动作 的 join 比例。
数据源（零侵入起步，2026-11-05 实证）：
  - 反思代理：`.cognitive/sessions/*/suggestions.md` 的「生成时间」+「reflection_id」
  - 修复动作：同 session `action_chain.jsonl` 中的 git_commit / file_change

**2026-11-10 升级**：`active_reflection_id` 已在动作侧补记（cognitive_session.add_action），
可做 reflection_id 精确 join；旧会话（无 rid）仍用时序代理（72h 窗口）。
evidence_grade 随精确 join 覆盖率自动提升：pipeline_only → proxy → real。

FAIL-OPEN：异常 → no_data。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SESSIONS = _REPO_ROOT / ".cognitive" / "sessions"
ACTION_TYPES = ("git_commit", "file_change")
FIX_WINDOW_HOURS = 72
MIN_REFLECTIONS = 30

_TIME_RE = re.compile(r"生成时间:\s*([0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2})")
_RID_RE = re.compile(r"reflection_id:\s*(RF-[0-9]+-[0-9a-f]+)")


def _parse_gen_time(md_path: Path) -> Optional[float]:
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")[:400]
    except Exception:  # noqa: BLE001 — FAIL-OPEN
        return None
    m = _TIME_RE.search(text)
    if m:
        try:
            raw = m.group(1).replace("T", " ")
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            pass
    try:
        return md_path.stat().st_mtime
    except Exception:  # noqa: BLE001
        return None


def compute_self_correction_rate(
    sessions_root: Optional[Path] = None,
    min_reflections: int = MIN_REFLECTIONS,
    fix_window_hours: float = FIX_WINDOW_HOURS,
) -> Dict[str, Any]:
    """反思批次 → 后续修复动作 的 join 比例。"""
    root = Path(sessions_root) if sessions_root else DEFAULT_SESSIONS
    if not root.exists():
        return {
            "value": None,
            "status": "no_data",
            "n_reflections": 0,
            "n_fixed": 0,
            "note": "sessions 目录不存在",
        }
    n_ref = 0
    n_fixed = 0
    n_with_rid = 0
    n_actions = 0
    n_precise = 0  # 有 reflection_id 且可做精确 join 的会话数
    n_precise_fixed = 0  # 精确 join 命中的会话数
    window = fix_window_hours * 3600
    try:
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            md = d / "suggestions.md"
            if not md.exists():
                continue
            gen_ts = _parse_gen_time(md)
            if gen_ts is None:
                continue
            n_ref += 1
            md_text = md.read_text(encoding="utf-8", errors="ignore")[:600]
            rid_m = _RID_RE.search(md_text)
            rid = rid_m.group(1) if rid_m else None
            if rid:
                n_with_rid += 1
            chain = d / "action_chain.jsonl"
            if not chain.exists():
                continue
            try:
                lines = chain.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:  # noqa: BLE001
                continue
            fixed = False
            precise_match = False
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    a = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if a.get("action_type") not in ACTION_TYPES:
                    continue
                ts = a.get("timestamp")
                if not isinstance(ts, (int, float)):
                    continue
                n_actions += 1
                # 精确 join：action.active_reflection_id == suggestions.md reflection_id
                if rid and a.get("active_reflection_id") == rid:
                    precise_match = True
                    fixed = True
                # 时序代理（仅在无 rid 或精确未命中时作为降级）
                elif not rid and 0 < float(ts) - gen_ts <= window:
                    fixed = True
            if rid:
                n_precise += 1
                if precise_match:
                    n_precise_fixed += 1
            if fixed:
                n_fixed += 1
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("reflection join FAIL-OPEN: %s", exc)
        return {
            "value": None,
            "status": "no_data",
            "n_reflections": 0,
            "n_fixed": 0,
            "note": str(exc),
        }

    if n_ref == 0:
        return {
            "value": None,
            "status": "no_data",
            "n_reflections": 0,
            "n_fixed": 0,
            "note": "无反思产物（suggestions.md 不存在）",
        }
    rate = n_fixed / n_ref
    # evidence_grade 自动升级：
    #   - pipeline_only：无 reflection_id，纯时序代理（会话域退化率趋近 1）
    #   - proxy：有 reflection_id 但精确 join 覆盖率不足（新旧混合）
    #   - real：精确 join 已命中（reflection_id → action 精确 mapping）
    if n_precise_fixed > 0:
        grade = "real"
    elif n_with_rid > 0:
        grade = "proxy"
    else:
        grade = "pipeline_only"
    degenerate = grade == "pipeline_only"
    return {
        "value": rate,
        "status": "ok" if n_ref >= min_reflections else "insufficient_data",
        "evidence_grade": grade,
        "n_reflections": n_ref,
        "n_fixed": n_fixed,
        "n_actions": n_actions,
        "fix_window_hours": fix_window_hours,
        "n_with_reflection_id": n_with_rid,
        "reflection_id_coverage": round(n_with_rid / n_ref, 4) if n_ref else 0.0,
        "n_precise_join": n_precise,
        "n_precise_fixed": n_precise_fixed,
        "precise_fix_rate": round(n_precise_fixed / n_precise, 4) if n_precise else 0.0,
        "note": (
            "精确 join（active_reflection_id == reflection_id）已启用；"
            f"精确命中 {n_precise_fixed}/{n_precise}，时序代理覆盖旧会话"
            if n_precise
            else "时序 join 代理：反思生成后 72h 内同 session 有修复动作即计；reflection_id 未覆盖，待新会话积累"
        ),
        "caveat": (
            "会话域建议批次在会话早期、动作必然随后 → 率退化接近 1，仅验证管道，"
            "不构成「反思驱动修复」证据；需 reflection_id 覆盖率提升后精确 join"
            if degenerate
            else None
        ),
    }


def _emit_reflection_gap() -> bool:
    """reflection_id 未落盘 → E6 需求单（同类型 open 单不重复发）。"""
    try:
        _reg = str(_REPO_ROOT / "48-涌现架构" / "registry")
        if _reg not in sys.path:
            sys.path.insert(0, _reg)
        import capability_gaps as cg

        for g in cg.load_gaps(cg.DEFAULT_GAPS_PATH):
            if (
                g.get("gap_type") == "reflection_log_missing"
                and g.get("created_by") == "e4b_reflection"
                and g.get("status") in ("open", "claimed")
            ):
                return False
        gap = cg.new_gap(
            gap_type="reflection_log_missing",
            evidence={
                "source": "e4b_reflection",
                "reason": "HermesReflector 未落盘 reflection_id + 修复动作映射；"
                "当前只能用 sessions/suggestions.md 时序代理（率退化接近 1）",
            },
            expected_value="e4_self_correction_rate 可从时序代理升级为 reflection→fix 精确 join",
            target_domain_hint="35-广义认知",
            created_by="e4b_reflection",
        )
        return cg.append_gap(gap)
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("发 E6 需求单失败（降级）: %s", exc)
        return False


def main() -> int:
    res = compute_self_correction_rate()
    if res.get("caveat"):
        _emit_reflection_gap()
    print(
        f"E4b self-correction: value={res.get('value')} status={res.get('status')} "
        f"grade={res.get('evidence_grade')} "
        f"n_reflections={res.get('n_reflections')} n_fixed={res.get('n_fixed')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
