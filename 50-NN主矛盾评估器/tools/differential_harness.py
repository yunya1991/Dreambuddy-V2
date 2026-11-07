"""R0-04 differential harness：同输入 23(control) vs 50(treatment) 逐字段 diff，产出分歧率基线。

R2 的 A/B 只解释相对此基线的增量，不解释绝对值。
"""

from __future__ import annotations

DIFF_FIELDS = ("direction", "confidence", "dimension", "horizon", "intent", "continuation_score")


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
