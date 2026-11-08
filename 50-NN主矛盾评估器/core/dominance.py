# R2-03: Dominance（50 SPEC §4.5，成对支配 + Copeland 矩阵，独立实现）。
#
# Dominance 只在同 horizon 的 path 集合内两两比较；跨 horizon 不做 dominance。
# 输出可解释 dominance 矩阵与主导者；argmax 仅作 shadow 回退（fallback=argmax 标注）。
# 纯函数：不读文件、不写状态。
from __future__ import annotations

from typing import Any

from core.path_synthesis import Path


def _strength(path: Path) -> float:
    # 路径力量：置信度 x 证据权重（外部证据权重来自 SOURCE_WEIGHT_MAP）。
    weight = float(path.metadata.get("weight") or 0.0)
    return path.confidence * weight


def _pairwise(a: Path, b: Path) -> int:
    # 成对支配：a 支配 b 返回 1，b 支配 a 返回 -1，平局 0。
    # 比较口径：力量对比为主；力量相等时 continuation_score 破平。
    sa, sb = _strength(a), _strength(b)
    if sa > sb:
        return 1
    if sa < sb:
        return -1
    if a.continuation_score > b.continuation_score:
        return 1
    if a.continuation_score < b.continuation_score:
        return -1
    return 0


def resolve_dominance(paths: list[Path]) -> dict[str, Any]:
    # Dominance 主入口：同 horizon 分组内成对支配 + Copeland 矩阵。
    # 返回：per-horizon 的 dominance 矩阵、Copeland 得分、主导者与回退标注。
    by_horizon: dict[str, list[Path]] = {}
    for p in paths:
        if isinstance(p, Path):
            by_horizon.setdefault(p.horizon, []).append(p)
    result: dict[str, Any] = {"horizons": {}}
    overall_leader = None
    overall_fallback = False
    for horizon in sorted(by_horizon):
        group = by_horizon[horizon]
        ids = [p.path_id for p in group]
        n = len(group)
        # dominance 矩阵：matrix[i][j] = 1 表示 i 支配 j，-1 表示被支配，0 平局
        matrix = [[0] * n for _ in range(n)]
        copeland = [0] * n
        for i in range(n):
            for j in range(i + 1, n):
                outcome = _pairwise(group[i], group[j])
                matrix[i][j] = outcome
                matrix[j][i] = -outcome
                if outcome > 0:
                    copeland[i] += 1
                    copeland[j] -= 1
                elif outcome < 0:
                    copeland[j] += 1
                    copeland[i] -= 1
        best = max(copeland) if n else 0
        leaders = [ids[i] for i in range(n) if copeland[i] == best]
        fallback = False
        leader = None
        if n == 0:
            leader = None
        elif len(leaders) == 1:
            leader = leaders[0]
        else:
            # 无唯一支配者：argmax 仅作 shadow 回退
            fallback = True
            strongest = max(group, key=_strength)
            leader = strongest.path_id
        entry: dict[str, Any] = {
            "path_ids": ids,
            "matrix": matrix,
            "copeland": {ids[i]: copeland[i] for i in range(n)},
            "leader": leader,
            "fallback_argmax": fallback,
            "tied_leaders": leaders if fallback else [],
        }
        result["horizons"][horizon] = entry
        if leader is not None and not fallback and overall_leader is None:
            overall_leader = leader
        if fallback:
            overall_fallback = True
    result["overall_leader"] = overall_leader
    result["overall_fallback_argmax"] = overall_fallback and overall_leader is None
    return result
