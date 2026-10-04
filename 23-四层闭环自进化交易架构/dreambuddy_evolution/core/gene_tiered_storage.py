"""
D1: GeneTieredStorage — 策略基因分级存储（借鉴 ds4 非对称量化）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 1
哲学: ds4 非对称量化——关键组件高精度，非关键激进压缩。
映射: 策略基因分级存储——核心基因完整精度，候选/淘汰基因简化表示。

分级规则:
  L0 核心 (core):      ess >= 0.7 且 n_samples >= 100（充分验证·实盘候选）
  L1 候选 (candidate): ess >= 0.5 或 n_samples >= 30（部分验证·影子模式）
  L2 淘汰 (retired):   ess < 0.5 且 n_samples < 30（验证不足·低优先级）

硬约束:
  HC-DS4-02: 分级失败 → 降级为全量加载（返回原 library）
  HC-DS4-10: L0 核心基因保持完整精度，不得有损压缩
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GeneTieredStorage:
    """策略基因分级存储管理器."""

    # 分级常量
    TIER_CORE = "core"           # L0: 实盘验证 Sharpe 正向 → 完整数据
    TIER_CANDIDATE = "candidate" # L1: 影子验证中 → 仅元数据
    TIER_RETIRED = "retired"     # L2: 已淘汰 → 仅 ID + 评分

    # 分级阈值
    CORE_ESS_THRESHOLD = 0.7
    CORE_SAMPLE_THRESHOLD = 100
    CANDIDATE_ESS_THRESHOLD = 0.5
    CANDIDATE_SAMPLE_THRESHOLD = 30

    @staticmethod
    def classify(combo: dict[str, Any]) -> str:
        """根据验证状态对组合分级.

        分级规则:
          L0 核心:      ess >= 0.7 且 n_samples >= 100
          L1 候选:      ess >= 0.5 或 n_samples >= 30
          L2 淘汰:      ess < 0.5 且 n_samples < 30

        Args:
            combo: 策略组合 dict（含 ess/n_samples 或 meta.H/S/N）

        Returns:
            str: TIER_CORE / TIER_CANDIDATE / TIER_RETIRED
        """
        try:
            # 获取 ess（优先顶层，其次计算）
            ess = combo.get("ess")
            if not isinstance(ess, (int, float)):
                # 从 meta 计算 ESS
                from dreambuddy_evolution.core.strategy_gene import calculate_ess
                ess = calculate_ess(combo)
            ess = float(ess)

            # 获取 n_samples
            n_samples = combo.get("n_samples")
            if not isinstance(n_samples, int):
                n_samples = int(combo.get("meta", {}).get("N", 0) or 0)

            # 分级判定
            if ess >= GeneTieredStorage.CORE_ESS_THRESHOLD and n_samples >= GeneTieredStorage.CORE_SAMPLE_THRESHOLD:
                return GeneTieredStorage.TIER_CORE
            elif ess >= GeneTieredStorage.CANDIDATE_ESS_THRESHOLD or n_samples >= GeneTieredStorage.CANDIDATE_SAMPLE_THRESHOLD:
                return GeneTieredStorage.TIER_CANDIDATE
            else:
                return GeneTieredStorage.TIER_RETIRED
        except Exception:  # noqa: BLE001 — 分级失败保守归为 L2
            return GeneTieredStorage.TIER_RETIRED

    @staticmethod
    def load_tiered(library: dict[str, Any]) -> dict[str, Any]:
        """分级加载基因库.

        对外接口不变: 返回的 library 包含完整 combinations 列表.
        新增 tier_info 字段记录分级信息（可选使用）.

        tier_info 结构:
          core:      {combo_id: 完整组合 dict}
          candidate: {combo_id: {combo_id, ess, n_samples, action_ids}}
          retired:   {combo_id: {combo_id, ess}}

        HC-DS4-02: 分级失败 → 返回原 library（不附加 tier_info）.
        HC-DS4-10: L0 核心基因完整保留，不得有损压缩.

        Args:
            library: load_gene_library() 返回值

        Returns:
            dict: 原 library + tier_info（分级失败时仅原 library）
        """
        try:
            combinations = library.get("combinations", []) or []
            if not isinstance(combinations, list):
                return library

            tier_info: dict[str, dict[str, Any]] = {
                GeneTieredStorage.TIER_CORE: {},
                GeneTieredStorage.TIER_CANDIDATE: {},
                GeneTieredStorage.TIER_RETIRED: {},
            }

            for combo in combinations:
                if not isinstance(combo, dict):
                    continue
                combo_id = str(combo.get("combo_id", ""))
                if not combo_id:
                    continue

                tier = GeneTieredStorage.classify(combo)

                if tier == GeneTieredStorage.TIER_CORE:
                    # L0: 完整保留（HC-DS4-10）
                    tier_info[tier][combo_id] = dict(combo)
                elif tier == GeneTieredStorage.TIER_CANDIDATE:
                    # L1: 仅元数据
                    ess = combo.get("ess")
                    n_samples = combo.get("n_samples")
                    tier_info[tier][combo_id] = {
                        "combo_id": combo_id,
                        "ess": ess if isinstance(ess, (int, float)) else None,
                        "n_samples": n_samples if isinstance(n_samples, int) else None,
                        "action_ids": list(combo.get("action_ids", []) or []),
                    }
                else:
                    # L2: 仅 ID + 评分
                    ess = combo.get("ess")
                    tier_info[tier][combo_id] = {
                        "combo_id": combo_id,
                        "ess": ess if isinstance(ess, (int, float)) else None,
                    }

            # 返回原 library + tier_info（不修改 combinations）
            result = dict(library)
            result["tier_info"] = tier_info
            return result

        except Exception as e:  # noqa: BLE001 — HC-DS4-02 FAIL-OPEN
            logger.debug("[FO-DS4-D1] GeneTieredStorage.load_tiered fail: %s", e)
            return library

    @staticmethod
    def get_core_ids(library: dict[str, Any]) -> list[str]:
        """获取 L0 核心基因 ID 列表."""
        tier_info = library.get("tier_info") or {}
        core = tier_info.get(GeneTieredStorage.TIER_CORE, {}) or {}
        return list(core.keys())

    @staticmethod
    def get_tier_distribution(library: dict[str, Any]) -> dict[str, int]:
        """获取各级别基因数量分布."""
        tier_info = library.get("tier_info") or {}
        return {
            GeneTieredStorage.TIER_CORE: len(tier_info.get(GeneTieredStorage.TIER_CORE, {}) or {}),
            GeneTieredStorage.TIER_CANDIDATE: len(tier_info.get(GeneTieredStorage.TIER_CANDIDATE, {}) or {}),
            GeneTieredStorage.TIER_RETIRED: len(tier_info.get(GeneTieredStorage.TIER_RETIRED, {}) or {}),
        }
