"""
ESSDirectionProvider — 加载策略基因库，计算 ESS 排序，输出 top1 方向
SPEC §2.4

激活 RippleEngine 的关键：ess_top_direction 为空导致龙头检测和涟漪扩散全部失效

缓存：每 6h 刷新一次基因库，不每轮重载
Phase 0 降级：min_sample=0 (允许样本不足的组合参与排序)
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL = 6 * 3600  # 6 小时


class ESSDirectionProvider:
    """策略基因 ESS 方向提供器"""

    def __init__(self, gene_data_root: str, min_sample: int = 0) -> None:
        """
        Args:
            gene_data_root: gene_data 目录路径
            min_sample: 最小样本数阈值
                       Phase 0: min_sample=0 (降级，允许样本不足)
                       Phase 1+: min_sample=30 (蓝图硬约束)
        """
        self._root = gene_data_root
        self._min_sample = min_sample
        self._cache_ts: float = 0.0
        self._cached_direction: str = ""
        self._cached_combo_id: str = ""
        self._cached_score: float = 0.0

    def get_top_direction(self) -> dict[str, Any]:
        """
        获取 ESS top1 方向。

        Returns:
            {ess_top_direction: str, ess_top1_id: str, ess_top1_score: float}
        """
        now = time.time()
        if now - self._cache_ts < _CACHE_TTL:
            return {
                "ess_top_direction": self._cached_direction,
                "ess_top1_id": self._cached_combo_id,
                "ess_top1_score": self._cached_score,
            }

        result = self._compute_top_direction()
        self._cached_direction = result["ess_top_direction"]
        self._cached_combo_id = result["ess_top1_id"]
        self._cached_score = result["ess_top1_score"]
        self._cache_ts = now
        return result

    def _compute_top_direction(self) -> dict[str, Any]:
        """从基因库计算 ESS top1 方向"""
        try:
            import sys as _sys
            # 确保 dreambuddy_evolution 在 path 中
            _evo_root = None
            for p in _sys.path:
                if "dreambuddy_evolution" in p or "23-四层闭环" in p:
                    _evo_root = p
                    break

            if _evo_root is None:
                from pathlib import Path
                _evo_root = str(Path(self._root).parent)
                if _evo_root not in _sys.path:
                    _sys.path.insert(0, _evo_root)

            from dreambuddy_evolution.core.strategy_gene import (  # type: ignore
                load_gene_library,
                top_combinations_by_ess,
            )

            library = load_gene_library(self._root)
            # load_gene_library 返回 dict: {root, conditions, actions, combinations, counts, bad_genes_log}
            actions = library.get("actions", []) if isinstance(library, dict) else []

            top_combos = top_combinations_by_ess(
                library, min_sample=self._min_sample
            )

            if not top_combos:
                logger.info("[FO] ESS: no combos above min_sample=%d", self._min_sample)
                return {"ess_top_direction": "", "ess_top1_id": "", "ess_top1_score": 0.0}

            top1 = top_combos[0]
            combo_id = top1.get("combo_id", "")
            ess_score = float(top1.get("ess", 0.0))

            # 从 action_ids 查找 action gene → 读取 direction
            action_ids = top1.get("action_ids", [])
            direction = ""
            # actions 是 list[dict]
            for aid in action_ids:
                for a in actions:
                    if isinstance(a, dict) and a.get("gene_id") == aid:
                        d = a.get("direction", "")
                        if d in ("long", "short"):
                            direction = d
                        break
                if direction:
                    break

            logger.info("[ESS] top1=%s ess=%.4f dir=%s", combo_id, ess_score, direction)
            return {
                "ess_top_direction": direction,
                "ess_top1_id": combo_id,
                "ess_top1_score": ess_score,
            }

        except Exception as e:
            logger.warning("[FO] ESSDirectionProvider compute crash: %s", e)
            return {"ess_top_direction": "", "ess_top1_id": "", "ess_top1_score": 0.0}

    def invalidate_cache(self) -> None:
        """手动失效缓存（测试用）"""
        self._cache_ts = 0.0

    def update_ess(self, ess_delta: float, symbol: str = "") -> bool:
        """
        P0 闭环修复：将平仓反思得到的 ess_delta 写回基因库。

        策略: 更新 ESS 最高的组合（决策主导者），clamp 到 [0,1]，
              n_samples+1，记录 last_updated 时间戳。
        FAIL-OPEN: 任何异常返回 False，不阻断交易。
        """
        import json
        import time
        from pathlib import Path
        try:
            lib_path = Path(self._root) / "strategy_combinations" / "library.json"
            if not lib_path.exists():
                return False
            data = json.loads(lib_path.read_text(encoding="utf-8"))
            if not data:
                return False
            # 找 ESS 最高的组合（决策主导者）
            top_idx = max(range(len(data)), key=lambda i: float(data[i].get("ess", 0)))
            combo = data[top_idx]
            old_ess = float(combo.get("ess", 0.5))
            new_ess = max(0.0, min(1.0, old_ess + ess_delta))
            combo["ess"] = round(new_ess, 6)
            combo["n_samples"] = int(combo.get("n_samples", 0)) + 1
            combo["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if symbol:
                combo.setdefault("trade_history", []).append({
                    "symbol": symbol,
                    "ess_delta": round(ess_delta, 6),
                    "ts": combo["last_updated"],
                })
            lib_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            self.invalidate_cache()  # 下次读取重新计算
            return True
        except Exception as e:
            logger.warning("[FO] update_ess crash: %s", e)
            return False
