"""
跨资产验证器（P1-5 改进）

P1-5: 影子验证不只在 BTC，扩展到 ETH/SOL 等

流程:
  1. 接受 {symbol: samples} 字典
  2. 对每个资产生成 check_promotion_with_stats 结果
  3. 统计通过 promote 的资产数
  4. cross_asset_pass = n_assets_pass >= min_assets_pass（默认 2）

鲁棒性: 基因在多个资产上均通过统计检验才算鲁棒，避免单标的过拟合。
参考: architecture-evaluation-23.md P1 改进建议 #5
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _import_check():
    from dreambuddy_evolution.core.gene_promotion_stats import check_promotion_with_stats
    return check_promotion_with_stats


class CrossAssetValidator:
    """跨资产验证器.

    用法:
        v = CrossAssetValidator()
        result = v.validate({"BTC": btc_samples, "ETH": eth_samples, "SOL": sol_samples})
        if result["cross_asset_pass"]:
            print("基因跨资产鲁棒")
    """

    DEFAULT_MIN_ASSETS_PASS = 2

    def __init__(self) -> None:
        try:
            self._check = _import_check()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[P1-5] 导入 gene_promotion_stats 失败: {exc}")
            self._check = None

    def validate(self, asset_samples: dict[str, list[dict[str, Any]]],
                 min_assets_pass: int = 2) -> dict[str, Any]:
        """执行跨资产验证.

        Args:
            asset_samples: {symbol: [{"pnl_pct": float, ...}, ...]}
            min_assets_pass: 通过 promote 的最少资产数（默认 2）

        Returns:
            {
              "per_asset": {symbol: check_promotion_with_stats 结果},
              "n_assets_evaluated": int,
              "n_assets_pass": int,
              "n_assets_skipped": int,
              "min_assets_pass": int,
              "cross_asset_pass": bool,
            }
        """
        # FAIL-OPEN: 空字典
        if not asset_samples:
            return {
                "per_asset": {},
                "n_assets_evaluated": 0,
                "n_assets_pass": 0,
                "n_assets_skipped": 0,
                "min_assets_pass": min_assets_pass,
                "cross_asset_pass": False,
            }

        if self._check is None:
            # FAIL-OPEN: 模块不可用，全部标记不通过
            per_asset = {sym: {"promote": False, "reason": "stats module unavailable"}
                         for sym in asset_samples}
            return {
                "per_asset": per_asset,
                "n_assets_evaluated": len(asset_samples),
                "n_assets_pass": 0,
                "n_assets_skipped": 0,
                "min_assets_pass": min_assets_pass,
                "cross_asset_pass": False,
            }

        per_asset: dict[str, dict[str, Any]] = {}
        n_pass = 0
        n_skipped = 0

        for symbol, samples in asset_samples.items():
            if not samples or len(samples) < 1:
                per_asset[symbol] = {"promote": False, "reason": "empty samples"}
                n_skipped += 1
                continue

            decision = self._check(samples)
            per_asset[symbol] = decision
            if decision.get("promote"):
                n_pass += 1

        cross_pass = n_pass >= min_assets_pass

        return {
            "per_asset": per_asset,
            "n_assets_evaluated": len(asset_samples),
            "n_assets_pass": n_pass,
            "n_assets_skipped": n_skipped,
            "min_assets_pass": min_assets_pass,
            "cross_asset_pass": cross_pass,
        }
