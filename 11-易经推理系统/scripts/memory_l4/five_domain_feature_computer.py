#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FiveDomainFeatureComputer —— 五计庙算特征→评分计算层。

Spec: 2026-08-22-five-domain-feature-computer-design.md
上游: 2026-08-21-sunzi-five-domains-evaluation.md §三逐维打分详解

职责：从现有 bcrm2 特征 + 后置层 regime + 系统自省
      计算五维原始评分(0-100)，传给 FiveDomainHeuristicScorer.score_and_decide()。

周期（§11.1 L1204）：
  - 战略层日级一次粗评分
  - 道维度周级离线批打分不进热路径
  - 5min 热路径只读缓存快照

Fail-open（§九 L1180）：
  - enable=False → 返回 DEFAULT_NEUTRAL_SCORES
  - 子指标异常 → 中性 50
  - 整个 compute() 异常 → DEFAULT_NEUTRAL_SCORES
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

# ============================================================
# [P1-5c] 注入「9-基本面分析」到 sys.path（engines.* 薄封装代理模块导入前置）
#   · 定位方式：从本文件（11-易经推理系统/scripts/memory_l4/five_domain_feature_computer.py）
#     上溯 3 层到项目根（dreambuddy-v2），再拼「9-基本面分析」子目录
#   · Fail-Open：目录不存在或已在 sys.path 中 → 静默跳过（后续 from engines import 会 FAIL-OPEN
#     走旧启发式分支，字节等价旧代码）
# ============================================================
try:  # noqa: E402
    import os as _os
    import sys as _sys
    _FD_BASE = _os.path.dirname(_os.path.abspath(__file__))          # memory_l4
    _FD_BASE = _os.path.dirname(_FD_BASE)                            # scripts
    _FD_BASE = _os.path.dirname(_FD_BASE)                            # 11-易经推理系统
    _FD_ROOT = _os.path.dirname(_FD_BASE)                            # dreambuddy-v2
    _9_FUND_PATH = _os.path.join(_FD_ROOT, "9-基本面分析")
    if _os.path.isdir(_9_FUND_PATH) and _9_FUND_PATH not in _sys.path:
        _sys.path.insert(0, _9_FUND_PATH)
except Exception:
    pass

try:  # noqa: E402 兼容包内相对导入和独立运行
    from .strategy_algo_layer import (
        ASSET_CLASSES,
        DEFAULT_NEUTRAL_SCORES,
        _normalize_0_100,
    )
except ImportError:
    from strategy_algo_layer import (
        ASSET_CLASSES,
        DEFAULT_NEUTRAL_SCORES,
        _normalize_0_100,
    )


# 美林时钟四阶段→天维度评分映射（§三 L128：复苏对风险资产利好→加分）
_MERRILL_PHASE_SCORES: Dict[str, int] = {
    "RECOVERY": 70,      # 复苏期：资金流入altcoin → 利好
    "OVERHEAT": 60,      # 过热期：altcoin疯狂但风险高
    "STAGFLATION": 40,   # 滞胀期：资金回流BTC
    "REFLATION": 30,     # 衰退期：资金流出加密市场
}

# 日历季节性基础分（§三 L127：Q1效应/Q4效应/周末效应/减半周期季节性）
# 基于BTC历史季度收益统计
_MONTH_BASE_SCORES: Dict[int, int] = {
    1: 68, 2: 65, 3: 62,   # Q1：历史正收益效应
    4: 55, 5: 52, 6: 48,   # Q2：混合表现
    7: 42, 8: 40, 9: 38,   # Q3：历史弱势（夏季低迷）
    10: 58, 11: 62, 12: 65 # Q4：历史强势（年底效应）
}


class FiveDomainFeatureComputer:
    """五维原始评分计算器：市场数据 + 系统状态 → 0-100 评分。

    Spec §5.3 红线保护：
      · enable_odaily_engine_boost = False（默认）
        → Shadow 审计 JSONL 模式；不修改任何五维结果；仅日志记录。
        → 4 门槛（hit_rate≥60%, thaw_accuracy≥70%, sharpe≥1.05, IMPORT_FAIL=0）全过
          → 经 PR+CR 后才允许把默认值改为 True（生效 boost 写 result）。

    Args:
        enable: 总开关。False 时返回中性默认值（字节等价战略层不存在）。
    """
    # ──────────────── Shadow 红线（Spec §5.3 H8）────────────────
    # 默认 = False。必须显式 enable = True 才 JSONL 记录；
    # 就算 True，shadow 也只读不写 result（字节等价）。
    enable_odaily_engine_boost: bool = False

    # Shadow JSONL 路径（可被测试覆盖；运行时默认相对 scripts/runtime/）
    _OD_SHADOW_JSONL_DEFAULT = "odaily_engine_boost_records.jsonl"

    # ──────────────── 7引擎红线（Spec §3.1 方案B 独立开关）────────────
    # 默认 = False；必须 7 门槛+7日观察+样本≥1500+PR+CR 后改 True
    enable_fundamental_7engines_boost: bool = False

    # ──────────────── 7引擎生产注入红线（Shadow 期间=永远False，阶段3才True）──
    # Shadow 审计期间仅 JSONL 记录，不能影响 dao/tian 计算结果（字节等价铁律）。
    # 7门槛通过 + PR+CR 后，才把类属性改为 True，正式触发 S/A 级乘法守卫。
    enable_fundamental_7engines_production_injection: bool = False

    # Shadow JSONL（阶段2创建；阶段1占位）
    _FD7_SHADOW_JSONL_DEFAULT = "fundamental_7engines_records.jsonl"

    # ──────────────── Force Vector 战略层力向量 Shadow 红线 ────────
    # 默认 = False；FORCE_VECTOR_SHADOW=1 打开
    # Shadow 期间：仅 JSONL 审计 + 附加顶层字段，不修改 dao/tian/di/jiang/fa 评分
    # 7日观察期 + 一致性门槛通过 + PR+CR 后，才允许下游 StrategicMapper 注入决策
    enable_force_vector: bool = False

    # Force Vector Shadow JSONL 路径
    _FORCE_VECTOR_SHADOW_JSONL_DEFAULT = "force_vector_records.jsonl"

    def __init__(self, enable: bool = True):
        self.enable = enable
        # 实例属性：运行时 JSONL 路径（可被测试 override）
        import os as _os
        self._od_shadow_jsonl_path = _os.environ.get(
            "ODAILY_SHADOW_JSONL",
            _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "scripts", "runtime", self._OD_SHADOW_JSONL_DEFAULT,
            ),
        )
        # Spec §5.3 H8 红线：默认 False；7 日观察期通过 ODAILY_ENGINE_BOOST=1 打开
        # 4 门槛全 PASS 后改类属性默认 True（PR+CR）
        self.enable_odaily_engine_boost = _os.environ.get(
            "ODAILY_ENGINE_BOOST", ""
        ).lower() in ("1", "true", "yes")

        # 7引擎红线开关：FUND_7ENGINES_BOOST=1 打开（默认 False）
        self.enable_fundamental_7engines_boost = _os.environ.get(
            "FUND_7ENGINES_BOOST", ""
        ).lower() in ("1", "true", "yes")
        # 7引擎 JSONL 运行时路径
        self._fd7_shadow_jsonl_path = _os.environ.get(
            "FD7_SHADOW_JSONL",
            _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "scripts", "runtime", self._FD7_SHADOW_JSONL_DEFAULT,
            ),
        )

        # ── Force Vector Shadow 开关 + JSONL 路径 ──
        self.enable_force_vector = _os.environ.get(
            "FORCE_VECTOR_SHADOW", ""
        ).lower() in ("1", "true", "yes")
        self._force_vector_shadow_jsonl_path = _os.environ.get(
            "FORCE_VECTOR_SHADOW_JSONL",
            _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                "scripts", "runtime", self._FORCE_VECTOR_SHADOW_JSONL_DEFAULT,
            ),
        )

    # ==================================================================
    # 公共入口
    # ==================================================================

    # 分层coin_data的判定键集合：若dict顶层存在这些键之一，则视为扁平结构
    _FLAT_COIN_DATA_KEYS = frozenset({
        "cycle4y_t_rel", "merrill_phase", "atr_percentile", "liquidity_score",
        "regime", "spring_force_score", "price_amplitude", "atr", "ftd_signal",
        "ma200_distance_percentile",
    })

    @classmethod
    def _resolve_class_coin_data(
        cls,
        coin_data: Optional[Dict[str, Any]],
        asset_class: str,
    ) -> Optional[Dict[str, Any]]:
        """按资产类解析coin_data：优先分层结构，缺失fallback到扁平结构。

        ★ FIX 问题1：差异化权重空转。
        - 分层结构：coin_data = {"crypto_usdt": {...}, "us_stock": {...}, ...}
          → 读取 coin_data[asset_class]
        - 扁平结构（旧版兼容）：coin_data = {"cycle4y_t_rel": ..., ...}
          → 直接原样返回
        - 分层结构中某类缺失：返回 None → 各维度 fail-open=50
        """
        if not coin_data:
            return None
        # 判定结构：若顶层存在扁平键，则是旧版扁平结构（或混合模式下该类不支持分层）
        has_flat_keys = bool(cls._FLAT_COIN_DATA_KEYS & coin_data.keys())
        # 尝试分层读取：仅当顶层不存在 ASSET_CLASS 以外的扁平键 或 明确存在 asset_class key
        if asset_class in coin_data:
            subset = coin_data[asset_class]
            if isinstance(subset, dict):
                return subset
        # 存在扁平键 → 视为扁平结构，原样返回保持兼容
        if has_flat_keys:
            return coin_data
        # 既无分层对应类数据，也无扁平键 → 无该类市场数据，fail-open=None
        return None

    def compute(
        self,
        coin_data: Optional[Dict[str, Any]] = None,
        system_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, int]]:
        """计算五维原始评分。

        Returns:
            Dict[asset_class, Dict[domain, int(0-100)]]
            asset_class ∈ ASSET_CLASSES
            domain ∈ {dao, tian, di, jiang, fa}

        支持两种 coin_data 输入格式：
        1) 分层结构（推荐，修复差异化问题）：
           {"crypto_usdt": {cycle4y_t_rel, merrill...}, "us_stock": {...}, ...}
        2) 扁平结构（兼容旧版）：
           {cycle4y_t_rel, merrill...} → 三类共享相同输入
        """
        if not self.enable:
            return {cls: dict(DEFAULT_NEUTRAL_SCORES) for cls in ASSET_CLASSES}

        try:
            result: Dict[str, Dict[str, int]] = {}
            for cls in ASSET_CLASSES:
                # ★ FIX 问题1：按资产类解析 coin_data，每类独立数据源
                cls_coin = self._resolve_class_coin_data(coin_data, cls)
                result[cls] = {
                    "dao": self._compute_dao(cls_coin, system_state, cls),
                    "tian": self._compute_tian(cls_coin, system_state, cls),
                    "di": self._compute_di(cls_coin, system_state, cls),
                    "jiang": self._compute_jiang(system_state, cls, cls_coin),
                    "fa": self._compute_fa(system_state, cls),
                }
            # ── Spec §5.3 Shadow Guard（红线只读）：打开才写 JSONL ──
            # 注意：任何 shadow 异常必须被吞，绝对不得影响 result
            if self.enable_odaily_engine_boost:
                try:
                    self._od_engine_shadow_compute(coin_data, system_state, result)
                except Exception:  # noqa: BLE001  Shadow 永远 fail-open
                    pass
            # ── Spec §6 Fundamental 7引擎 Shadow Guard（红线只读） ──
            if self.enable_fundamental_7engines_boost:
                try:
                    self._fd7_shadow_compute(coin_data, system_state, result)
                except Exception:  # noqa: BLE001  Shadow 永远 fail-open
                    pass
            # ── Strategic Force Vector Shadow Guard（红线只读+不注入评分）──
            if self.enable_force_vector:
                try:
                    self._force_vector_shadow_compute(coin_data, system_state, result)
                except Exception:  # noqa: BLE001  Shadow 永远 fail-open
                    pass
            return result
        except Exception:
            # fail-open：整体异常→中性默认
            return {cls: dict(DEFAULT_NEUTRAL_SCORES) for cls in ASSET_CLASSES}

    # ==================================================================
    # 道 — 方向一致性（§三 L82-110）
    # ==================================================================

    def _compute_dao(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """道维度：5个子指标——P1用代理指标替代fail-open=50。

        §三 L82-110：
        - 子指标1: 央行政策方向 → fedfunds_rate 代理（降息=宽松→高分）
        - 子指标2: 机构资金净流入 → stablecoin_mcap_bln 代理（加密专用，其他类fail-open）
        - 子指标3: 政策景气度 → policy_sentiment_score 代理（加密专用）
        - 子指标4: 变化率(一阶差分) → fail-open 50（需历史对比，日级无法计算）
        - 子指标5: 大周期位置 → cycle4y_t_rel（已实现）
        P1: 前3个子指标用 coin_data 中的代理指标，缺失时 fail-open=50
        """
        try:
            # 子指标1: 央行政策方向 → fedfunds_rate 代理
            rate = (coin_data or {}).get("fedfunds_rate")
            if rate is not None and isinstance(rate, (int, float)):
                # 联邦基金利率 < 2% = 宽松 → 高分(70-85)；> 5% = 紧缩 → 低分(30-45)
                rate_score = int(np.clip(round(85 - rate * 8), 0, 100))
            else:
                rate_score = 50  # fail-open

            # 子指标2: 机构资金净流入 → stablecoin_mcap_bln 代理（仅 crypto 有值）
            stablecoin = (coin_data or {}).get("stablecoin_mcap_bln")
            if stablecoin is not None and isinstance(stablecoin, (int, float)) and stablecoin > 0:
                # 稳定币市值 > 150bn = 资金充裕 → 高分；< 80bn = 资金流出 → 低分
                sc_score = int(np.clip(round((stablecoin - 80) / 2), 30, 85))
            else:
                sc_score = 50  # fail-open（非 crypto 类或数据缺失）

            # 子指标3: 政策景气度 → policy_sentiment_score 代理（仅 crypto 有值）
            # 注意：fetcher._sentiment_score 返回 0-1 范围（0.5=中性），需 ×100 映射
            sentiment = (coin_data or {}).get("policy_sentiment_score")
            if sentiment is not None and isinstance(sentiment, (int, float)):
                # 0-1 → 0-100：sentiment=0.5→50中性, sentiment=1.0→100全利好
                # 兼容：若传入已是 0-100 范围（>1.0），则直接使用
                sent_val = sentiment * 100.0 if 0.0 <= sentiment <= 1.0 else sentiment
                sent_score = int(np.clip(round(sent_val), 0, 100))
            else:
                sent_score = 50  # fail-open

            # 子指标4: 变化率 → 稳定币市值一阶差分（P2-3 接入真实数据）
            # stablecoin_change_rate = (当前 - 上次) / 上次
            sc_change = (coin_data or {}).get("stablecoin_change_rate")
            if sc_change is not None and isinstance(sc_change, (int, float)):
                # 正变化率→资金流入→高分；负变化率→资金流出→低分
                # 映射：±5% 变化 → 30~70 分，0%→50 中性
                diff_score = int(np.clip(round(50 + sc_change * 400), 0, 100))
            else:
                diff_score = 50  # fail-open（首次运行无历史快照）

            # 子指标5: 大周期位置 → cycle4y_t_rel（已实现）
            cycle_score = self._compute_cycle4y_position(coin_data)

            # 子指标6: 高位滞涨风险（技术面）—— 用户经验：上涨后高位横盘=筑顶信号
            #   ma200_dist>0.70 且 regime 非上升趋势 → 滞涨减分；否则中性50
            #   FAIL-OPEN：缺 ma200_dist 或 regime → 50
            high_stall_score = self._compute_high_stall_risk(coin_data)
            # 保存到 coin_data 供 direction_context 使用（战略层方向偏置）
            try:
                if isinstance(coin_data, dict):
                    coin_data["high_stall_score"] = high_stall_score
            except Exception:
                pass

            # 6个子指标等权
            dao_raw = (rate_score + sc_score + sent_score + diff_score + cycle_score + high_stall_score) / 6.0
            # Panewslab 增强（±20% 范围微调）：缺数据中性 0 boost，不变旧值
            # Spec §5.2.4：与 Odaily (1±10%) 独立乘法叠加，乘积顶 1.2×1.1=1.32，再 clamp [0,100]
            # Spec §5.3 H8 红线：enable_odaily_engine_boost=False 时 od boost 不注入
            if self.enable_odaily_engine_boost:
                dao_raw = dao_raw * (1.0 + self._pn_dao_boost(coin_data)) * (1.0 + self._od_dao_boost(coin_data))
            else:
                dao_raw = dao_raw * (1.0 + self._pn_dao_boost(coin_data))
            # Spec §3.1 方案B：7引擎 S/A 两个独立乘法因子叠加于 pn×od 之后。
            # 使用独立生产注入红线 enable_fundamental_7engines_production_injection（Shadow 期间=永远 False），
            # 保证 shadow audit 开开关时，字节等价不注入任何 S/A 级boost（只读铁律）。
            if self.enable_fundamental_7engines_production_injection:
                dao_raw = dao_raw * (1.0 + self._fd_S_dao_boost(coin_data)) * (1.0 + self._fd_A_dao_boost(coin_data, system_state))
            return _normalize_0_100(dao_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["dao"]

    # ------------------------------------------------------------------
    # BTC 强弱 Regime 检测（用户经验：BTC 强势与美股脱钩，弱势类风险资产）
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_btc_regime(coin_data: Optional[Dict[str, Any]]) -> str:
        """基于 regime + MA200 距离判定 BTC 强弱。

        STRONG: 上升趋势/突破 且 价格在 MA200 上方较远
        WEAK:   下降趋势 或 价格在 MA200 下方
        NEUTRAL: 其他
        FAIL-OPEN → NEUTRAL
        """
        if not coin_data:
            return "NEUTRAL"
        regime = str(coin_data.get("regime", "ranging") or "ranging")
        ma200_dist = coin_data.get("ma200_distance_percentile")
        try:
            ma200_dist = float(ma200_dist) if ma200_dist is not None else 0.5
        except (TypeError, ValueError):
            ma200_dist = 0.5
        if regime in ("trend_up", "breakout") and ma200_dist > 0.55:
            return "STRONG"
        if regime == "trend_down" or ma200_dist < 0.45:
            return "WEAK"
        return "NEUTRAL"

    # ------------------------------------------------------------------
    # Panewslab：dao 维度 delta boost [-0.2, 0.2]（fail-open 0）
    # 机构净流入 + ETF 流量 + 政策景气度 cycle_sentiment + 扩散广度命中
    # ------------------------------------------------------------------
    def _pn_dao_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        if not coin_data:
            return 0.0
        # 注入 btc_regime（供 P6 动态相关性使用；用户经验：BTC 弱势与美股关联增强）
        if "btc_regime" not in coin_data:
            coin_data["btc_regime"] = self._compute_btc_regime(coin_data)
        deltas: List[float] = []
        # P1：机构净流入 ETF flow_norm ∈ [-1,1] → ±0.15（用户经验：滞涨后 ETF 流出信号价值高）
        flow_norm = coin_data.get("pn_btc_etf_flow_norm")
        if isinstance(flow_norm, (int, float)):
            deltas.append(float(flow_norm) * 0.15)
        # P2：稳定币变化率 / BTC 集中度（越高越集中→偏多）
        btc_dom_focus = coin_data.get("pn_btc_dom_focus")
        if isinstance(btc_dom_focus, (int, float)):
            # [0,1] → [-0.02, 0.04]，0.6=0分位以下不加分，0.7以上线性+
            deltas.append(max(-0.02, (float(btc_dom_focus) - 0.6)) * 0.4)
        # P3：cycle_sentiment_norm [0,1] → 0.5→0, 0→-0.04, 1→+0.04
        pn_sent = coin_data.get("pn_cycle_sentiment_norm")
        if isinstance(pn_sent, (int, float)):
            deltas.append((float(pn_sent) - 0.5) * 0.08)
        # P4：omnitools hit_ratio [0,1] → 0→-0.03, 1→+0.03
        ohit = coin_data.get("pn_cycle_omnitools_hit_ratio")
        if isinstance(ohit, (int, float)):
            deltas.append((float(ohit) - 0.5) * 0.06)
        # P5：稳定币脉冲 / holdings 广度命中
        pulse = coin_data.get("pn_stablecoin_pulse_norm")
        if isinstance(pulse, (int, float)):
            deltas.append((float(pulse) - 0.5) * 0.06)
        breadth = coin_data.get("pn_holdings_breadth_hit_ratio")
        if isinstance(breadth, (int, float)):
            deltas.append((float(breadth) - 0.5) * 0.06)
        # P6：美股风险（VIX）× BTC regime 动态权重（用户经验：BTC 弱势时与美股关联增强）
        vix = coin_data.get("pn_us_vix")
        if vix is None:
            vix = coin_data.get("vix_close")
        btc_regime = coin_data.get("btc_regime", "NEUTRAL")
        if isinstance(vix, (int, float)):
            regime_mult = {"WEAK": 2.0, "STRONG": 0.5, "NEUTRAL": 1.0}.get(btc_regime, 1.0)
            # VIX 归一化：20→0, 35→-0.04, 12→+0.02，乘以 regime 倍数
            vix_norm = (20.0 - float(vix)) / 15.0 * 0.04
            deltas.append(vix_norm * regime_mult)
        if not deltas:
            return 0.0
        avg = sum(deltas) / float(len(deltas))
        return max(-0.2, min(0.2, avg))

    def _compute_cycle4y_position(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """4年周期锚点 t_rel 位置→评分。

        §三 L100：底部区域→加分，顶部区域→减分。
        """
        if not coin_data:
            return 50
        # 从 coin_data 读取 t_rel（如果存在）
        t_rel = coin_data.get("cycle4y_t_rel")
        if t_rel is None:
            return 50
        # t_rel ∈ [0, 1]：0=周期起点（底部），1=周期终点（顶部）
        # 底部→高分（70-90），中段→中分（50-70），顶部→低分（30-50）
        if t_rel < 0.25:
            return 80  # 底部区域：加高分
        elif t_rel < 0.50:
            return 65  # 上升初期
        elif t_rel < 0.75:
            return 50  # 中段偏热
        else:
            return 35  # 顶部区域：减分

    # ------------------------------------------------------------------
    # 高位滞涨风险（技术面）—— 用户经验：60日大涨后高位横盘=筑顶信号
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_high_stall_risk(coin_data: Optional[Dict[str, Any]]) -> int:
        """价格高位 + 非上升趋势 → 滞涨减分；否则中性50。

        逻辑：
        - ma200_distance_percentile > 0.70（价格在MA200上方较远=高位）
          且 regime 不在 ("trend_up","breakout")（非上升趋势/突破=滞涨）
          → 高位滞涨，减至 30-40 分
        - 高位但仍在上升趋势 → 强势，55 分
        - 其他 → 50 中性
        FAIL-OPEN → 50
        """
        if not coin_data:
            return 50
        ma200_dist = coin_data.get("ma200_distance_percentile")
        if ma200_dist is None:
            return 50
        try:
            ma200_dist = float(ma200_dist)
        except (TypeError, ValueError):
            return 50
        regime = str(coin_data.get("regime", "ranging") or "ranging")
        if ma200_dist > 0.70:
            if regime in ("trend_up", "breakout"):
                return 55  # 高位强势
            return 35  # 高位滞涨 → 筑顶风险
        return 50  # 非高位，中性

    # ==================================================================
    # 天 — 时间节奏（§三 L114-138）
    # ==================================================================

    def _compute_tian(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """天维度：日历季节性 + 美林时钟 + 波动率周期 + 流动性周期。"""
        try:
            now = datetime.now()
            month = now.month
            day = now.day
            weekday = now.weekday()  # 0=Mon, 6=Sun

            # 子指标1：日历季节性
            cal_score = self._compute_calendar_seasonality(month, day, weekday)

            # 子指标2：美林时钟位置
            phase = (coin_data or {}).get("merrill_phase", "RECOVERY")
            merrill_score = self._compute_merrill_clock_score(phase)

            # 子指标3：波动率周期（ATR分位）
            atr_percentile = (coin_data or {}).get("atr_percentile", 0.5)
            vol_score = self._compute_volatility_cycle_score(atr_percentile)

            # 子指标4：流动性周期
            liquidity_score = (coin_data or {}).get("liquidity_score", 0.5)
            liq_score = self._compute_liquidity_cycle_score(liquidity_score)

            # 4子指标等权（§三未指定权重，§八 L1166：不要把季节性权重给太高）
            tian_raw = (cal_score + merrill_score + vol_score + liq_score) / 4.0
            # Panewslab 增强（±20% 范围微调）：VIX 真实值 + 爆仓 ATR proxy + 美股变化 + 美债
            # Spec §5.2.4：与 Odaily (1±10%) 独立乘法叠加，乘积顶 1.2×1.1=1.32，再 clamp [0,100]
            # Spec §5.3 H8 红线：enable_odaily_engine_boost=False 时 od boost 不注入
            if self.enable_odaily_engine_boost:
                tian_raw = tian_raw * (1.0 + self._pn_tian_boost(coin_data)) * (1.0 + self._od_tian_boost(coin_data))
            else:
                tian_raw = tian_raw * (1.0 + self._pn_tian_boost(coin_data))
            # Spec §3.1 方案B：7引擎 S/A 两个独立乘法因子，开关关字节等价不注入。
            # 与 dao 对齐：使用独立生产注入红线，shadow 期间不注入
            if self.enable_fundamental_7engines_production_injection:
                tian_raw = tian_raw * (1.0 + self._fd_S_tian_boost(coin_data)) * (1.0 + self._fd_A_tian_boost(coin_data, system_state))
            return _normalize_0_100(tian_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["tian"]

    # ------------------------------------------------------------------
    # Panewslab：天维度 delta boost [-0.2, 0.2]（fail-open 0）
    # 波动率周期(VIX/AIM) + 美股收益动量 + 美债/美元实际水平 对 美林时钟的二次校正
    # ------------------------------------------------------------------
    def _pn_tian_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        if not coin_data:
            return 0.0
        deltas: List[float] = []
        # P1：VIX 级别映射（越恐慌天越减分，越平静加分）
        vix = (coin_data.get("pn_us_vix") if isinstance(coin_data, dict) else None)
        if vix is None and isinstance(coin_data, dict):
            vix = coin_data.get("vix_close")
        if isinstance(vix, (int, float)):
            v = float(vix)
            # 12 → +0.04；20 → 0；35 → -0.06
            deltas.append(max(-0.08, min(0.06, (20.0 - v) * 0.004)))
        # P2：合约爆仓 ATR proxy 作为波动率额外补充
        apx = coin_data.get("pn_liq_atr_percentile_proxy") if isinstance(coin_data, dict) else None
        if isinstance(apx, (int, float)):
            # 高波动=趋势期→加分；低波动=盘整期→中性偏减分
            deltas.append((float(apx) - 0.5) * 0.06)
        # P3：美股 24h 动量（纳斯达克/标普变化）
        for k in ("pn_us_sp500_chg_pct", "pn_us_nasdaq_chg_pct"):
            chg = coin_data.get(k) if isinstance(coin_data, dict) else None
            if isinstance(chg, (int, float)):
                # -3%→-0.04, 0→0, +3%→+0.04
                deltas.append(max(-0.04, min(0.04, float(chg) * 1.3)))
        # P4：美元指数强弱（强美元→风险资产减分）
        dxy = coin_data.get("pn_us_dollar_index") if isinstance(coin_data, dict) else None
        if isinstance(dxy, (int, float)):
            # 100 → 0；105 → -0.03；95 → +0.03
            deltas.append(max(-0.05, min(0.05, (100.0 - float(dxy)) * 0.006)))
        # P5：抄底 hit_ratio 作为季节替代项（低hit=底部形成→天偏暖/加分）
        hit_ratio_pct = coin_data.get("pn_cycle_bottom_hit_ratio_pct") if isinstance(coin_data, dict) else None
        if isinstance(hit_ratio_pct, (int, float)):
            # 高 hit(>50) → 周期已进入中段→加小分；低 hit(<30)→底部→加多分
            r = float(hit_ratio_pct) / 100.0
            if r >= 0.7:   deltas.append(0.05)
            elif r >= 0.5: deltas.append(0.03)
            elif r >= 0.3: deltas.append(0.0)
            else:          deltas.append(0.04)
        if not deltas:
            return 0.0
        avg = sum(deltas) / float(len(deltas))
        return max(-0.2, min(0.2, avg))

    # ------------------------------------------------------------------
    # Odaily：道 维度 delta boost [-0.1, 0.1]（FAIL-OPEN 0，比 _pn_* 更保守）
    # Spec §5.2.3 算法三 delta：
    #   D1 = (s - 0.5) * 0.16       — 情绪方向（sentiment 0.5 为中线）
    #   D2 = reg_policy_ratio > 0.3  →  -0.06   （严监管 压制）
    #        reg_policy_ratio < 0.1  →  +0.02   （无监管压制 温和利好）
    #        其余（0.1~0.3）       →  0.0     （中性区间）
    #   D3 = imp_ratio * sign(s-0.5) * 0.08   — 重要打标的方向加权
    #   结果：mean(D1,D2,D3)，clamp [-0.1, +0.1]
    # ------------------------------------------------------------------
    def _od_dao_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        try:
            if not isinstance(coin_data, dict):
                return 0.0
            cd: Dict[str, Any] = coin_data
            sent_raw = cd.get("odaily_policy_sentiment_3d")
            reg_ratio = cd.get("odaily_reg_policy_ratio_3d")
            imp_ratio = cd.get("odaily_important_ratio_3d")
            crh_ratio = cd.get("odaily_crypto_reg_ratio_3d")

            # 至少要有 sentiment；否则全部 None → 0.0
            if not isinstance(sent_raw, (int, float)):
                return 0.0
            s = float(sent_raw)
            if not (0.0 <= s <= 1.0):
                s = max(0.0, min(1.0, s))

            # ── D1 ──
            D1 = (s - 0.5) * 0.16

            # ── D2 ──
            D2 = 0.0
            if isinstance(reg_ratio, (int, float)):
                rr = float(reg_ratio)
                if rr > 0.3:
                    D2 = -0.06
                elif rr < 0.1:
                    D2 = +0.02
            # 额外：crypto_reg 强度 作为 D2 下限修正（crh>0.3 再减 0.02，避免仅 reg 不够时漏过）
            if isinstance(crh_ratio, (int, float)) and float(crh_ratio) > 0.3:
                D2 = min(D2, -0.02)

            # ── D3 ──
            D3 = 0.0
            if isinstance(imp_ratio, (int, float)):
                imp = float(imp_ratio)
                if imp > 0.0:
                    sign = 1.0 if s > 0.5 else (-1.0 if s < 0.5 else 0.0)
                    D3 = imp * sign * 0.08

            deltas = [D1, D2, D3]
            total = sum(deltas)
            return max(-0.1, min(0.1, round(total, 6)))
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # Odaily：天 维度 delta boost [-0.1, 0.1]（FAIL-OPEN 0，比 _pn_* 更保守）
    # Spec §5.2.3 算法三 delta：
    #   D1：货币政策分支 — reg_policy_ratio > 0.15 且
    #         sentiment > 0.6 → +0.05（宽松预期）
    #         sentiment < 0.4 → -0.05（鹰派紧缩）
    #   D2：地缘计数 — geopolitics_hits_3d >= 3 → -0.04；<= 1 → +0.01
    #   D3：安全事件 — security_ratio(security/batch) > 0.2 → -0.05；> 0.1 → -0.02
    # ------------------------------------------------------------------
    def _od_tian_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        try:
            if not isinstance(coin_data, dict):
                return 0.0
            cd = coin_data
            sent_raw = cd.get("odaily_policy_sentiment_3d")
            reg_ratio = cd.get("odaily_reg_policy_ratio_3d")
            geo_hits = cd.get("odaily_geopolitics_hits_3d")
            sec_hits = cd.get("odaily_security_hits_3d")
            batch = cd.get("odaily_batch_size_3d")
            crh_ratio = cd.get("odaily_crypto_reg_ratio_3d")

            if not isinstance(sent_raw, (int, float)):
                return 0.0
            s = max(0.0, min(1.0, float(sent_raw)))

            D1, D2, D3 = 0.0, 0.0, 0.0

            # ── D1 货币政策方向 ──
            if isinstance(reg_ratio, (int, float)):
                rr = float(reg_ratio)
                if rr > 0.15:
                    if s >= 0.6:
                        D1 = +0.05
                    elif s <= 0.4:
                        D1 = -0.05
            # crypto_reg 宽松（<0.05）作为 D1 额外加分，严（>0.2）再压
            if isinstance(crh_ratio, (int, float)):
                crh = float(crh_ratio)
                if crh < 0.05 and D1 >= 0:
                    D1 = D1 + 0.01
                elif crh > 0.2 and D1 <= 0:
                    D1 = D1 - 0.01

            # ── D2 地缘 ──
            if isinstance(geo_hits, (int, float)):
                gh = int(geo_hits)
                if gh >= 3:
                    D2 = -0.04
                elif gh <= 1:
                    D2 = +0.01

            # ── D3 安全事件 ──
            if isinstance(sec_hits, (int, float)) and isinstance(batch, (int, float)) and float(batch) > 0:
                sec_ratio = float(sec_hits) / float(batch)
                if sec_ratio > 0.2:
                    D3 = -0.05
                elif sec_ratio > 0.1:
                    D3 = -0.02

            deltas = [D1, D2, D3]
            total = sum(deltas)
            return max(-0.1, min(0.1, round(total, 6)))
        except Exception:
            return 0.0

    # ================================================================
    # 7引擎：辅助 —— SQLite records 表 72h 内 news_list（FAIL-OPEN）
    # 阶段2+ 生产实装（从 data_center.db category='news' 倒序 LIMIT 200）；
    # 阶段1 空壳返回 []，可被测试 monkeypatch 覆盖
    # ================================================================
    def _fetch_news_72h_limit200(self, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            # ── §5 步骤1：路径解析（db_path 优先，None 回退 five_domain_sqlite_reader.DEFAULT_DB_PATH；
            #    路径不存在/import fail-open 直接 return []） ──────────────────────
            resolved_path: Optional[str] = None
            if db_path is not None:
                resolved_path = str(db_path)
            else:
                try:
                    from five_domain_sqlite_reader import DEFAULT_DB_PATH  # type: ignore
                    resolved_path = str(DEFAULT_DB_PATH)
                except Exception:
                    return []
            import os as _os
            if not _os.path.exists(resolved_path):
                return []

            # ── §5 步骤2：SQL WHERE category='news' ORDER BY id DESC LIMIT 400 ───
            import sqlite3 as _sqlite3
            now_ms = int(time.time() * 1000)
            cutoff_ms = now_ms - 72 * 3600 * 1000
            try:
                conn = _sqlite3.connect(resolved_path)
                try:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT source, category, sub_category, timestamp, metrics, raw "
                        "FROM records WHERE category = 'news' ORDER BY id DESC LIMIT 400"
                    )
                    rows = cur.fetchall()
                finally:
                    conn.close()
            except _sqlite3.Error:
                return []

            # ── §5 步骤3：逐条解析（内套隔离：单条异常 → continue 跳过本条） ─────
            def _safe_json(text: Any) -> dict:
                if isinstance(text, dict):
                    return text
                if not isinstance(text, str):
                    return {}
                try:
                    return json.loads(text)
                except Exception:
                    return {}

            def _parse_ts_ms(records_timestamp: Any, raw_dict: dict) -> int:
                """按 §4 优先级：raw.publishTimestamp (ms) → records.timestamp int×1000 → ISO→×1000 → 0。"""
                # 1. raw.publishTimestamp
                if isinstance(raw_dict, dict):
                    pt = raw_dict.get("publishTimestamp")
                    if isinstance(pt, (int, float)) and pt > 0:
                        return int(pt)
                    if isinstance(pt, str) and pt.isdigit():
                        return int(pt)
                # 2. records.timestamp int 秒
                if isinstance(records_timestamp, (int, float)) and records_timestamp > 0:
                    return int(records_timestamp * 1000)
                if isinstance(records_timestamp, str) and records_timestamp.isdigit():
                    return int(int(records_timestamp) * 1000)
                # 3. ISO 字符串
                if isinstance(records_timestamp, str) and records_timestamp:
                    try:
                        import datetime as _dt
                        iso = records_timestamp
                        if iso.endswith("Z"):
                            iso = iso[:-1] + "+00:00"
                        t = _dt.datetime.fromisoformat(iso)
                        return int(t.timestamp() * 1000)
                    except Exception:
                        pass
                # 4. fail-open 保留 0
                return 0

            news_list: List[Dict[str, Any]] = []
            for (src, cat, sub, ts_col, metrics_txt, raw_txt) in rows:
                # ── Spec §5 TC-8 细粒度：metrics/raw 是字符串非空且无法解析为 JSON → 整条 skip ──
                if isinstance(metrics_txt, str) and metrics_txt.strip() and metrics_txt.strip() != "{}":
                    try:
                        json.loads(metrics_txt)
                    except Exception:
                        continue
                if isinstance(raw_txt, str) and raw_txt.strip() and raw_txt.strip() != "{}":
                    try:
                        json.loads(raw_txt)
                    except Exception:
                        continue
                m = _safe_json(metrics_txt)
                r = _safe_json(raw_txt)
                try:
                    # title：metrics.title → raw.title → ""
                    title = ""
                    for _cand in [m.get("title"), r.get("title")]:
                        if isinstance(_cand, str) and _cand.strip():
                            title = _cand.strip()
                            break
                    # content：raw.content → metrics.content → raw.body → ""
                    content = ""
                    for _cand in [r.get("content"), m.get("content"), r.get("body")]:
                        if isinstance(_cand, str) and _cand.strip():
                            content = _cand.strip()
                            break
                    ts_ms = _parse_ts_ms(ts_col, r)

                    # 72h 过滤：timestamp_ms == 0（解析失败保留不丢）视为 in-range（不丢弃）
                    if ts_ms != 0 and ts_ms < cutoff_ms:
                        continue

                    # topic/url 可选：raw 优先 → metrics 回退
                    topic = None
                    for _cand in [r.get("topic"), m.get("topic")]:
                        if isinstance(_cand, str) and _cand.strip():
                            topic = _cand.strip()
                            break
                    url = None
                    for _cand in [r.get("url"), m.get("url"), r.get("link"), m.get("link")]:
                        if isinstance(_cand, str) and _cand.strip():
                            url = _cand.strip()
                            break
                    event_type = None
                    for _cand in [r.get("event_type"), m.get("event_type")]:
                        if isinstance(_cand, str) and _cand.strip():
                            event_type = _cand.strip()
                            break

                    item: Dict[str, Any] = {
                        "source": str(src or ""),
                        "category": str(cat or "news"),
                        "sub_category": str(sub or ""),
                        "title": title,
                        "content": content,
                        "timestamp_ms": int(ts_ms or 0),
                    }
                    if topic is not None:
                        item["topic"] = topic
                    if url is not None:
                        item["url"] = url
                    if event_type is not None:
                        item["event_type"] = event_type

                    # 6 必填字段非空校验（仅 title/content 强制丢弃，其他保留；fail-open 保留策略更轻）
                    if not item["source"]:
                        continue
                    if not item["title"] and not item["content"]:
                        continue
                    news_list.append(item)
                except Exception:
                    continue

            # ── §5 步骤4：按 timestamp_ms DESC 排序 ─────────────────────────────
            news_list.sort(key=lambda d: int(d.get("timestamp_ms") or 0), reverse=True)
            # ── §5 步骤5：[0:200] 截断 ──────────────────────────────────────────
            return news_list[:200]
        except Exception:
            return []

    # ================================================================
    # 7引擎 S 级 5 delta：dao/tian 各 5 项加权求和 clamp[-0.1, +0.1]
    # Spec §4.2 D1-D5 表（dao 侧）
    #   D1 SentimentEngine: sent_mean∈[-1,1] → (sent+1)/2 = s → (s-0.5) * 0.06
    #   D2 EventLedger:   r_dir∈[-1,1] ×0.03 + (3-swm)×-0.008   swm∈[1,3]
    #   D3 NewsContract:  max(0, pass_rate-0.8) × 0.02
    #   D4 EventMapping:  (crr-0.25)*-0.08 + (mr-0.15)*sign(s_mean)*0.05
    #   D5 Narrative:     traj∈[-1,1] × 0.05 × min(1, n/3)
    # Spec §4.3 T1-T5 表（tian 侧）
    #   T1 Sentiment(policy): pol_count / min(3,total) * s_pol*0.08
    #   T2 紧急压制:        urgency_ration>0.4 → -0.05; >0.2 → -0.03; avoid_count≥1* -0.03
    #   T3 NewsContract:    同 D3 = max(0,pr-0.8)*0.02
    #   T4 EventType growth: event_growth_pct（过去24h比48h）*0.04 clamp[-0.04, +0.04]
    #   T5 Narrative reg_policy_traj: traj * 0.04 * ev（ev=number of reg events）
    # FAIL-OPEN 0.0；对齐 _od_*_boost 写法（isinstance守卫/deltas list sum/round6/clamp/外层except）
    # ================================================================
    def _fd_S_dao_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        try:
            if not isinstance(coin_data, (dict, type(None))):
                return 0.0
            # 1) 拉取 72h news_list（可被 monkeypatch 覆盖）
            news_list = self._fetch_news_72h_limit200()
            if not isinstance(news_list, list) or len(news_list) == 0:
                return 0.0

            # 2) S1 SentimentEngine —— 直接从 news_list 聚 sent_score（代理调用可选 FAIL-OPEN）
            #    优先调 engines.sentiment_engine；若 import 失败 fallback 到 news["sentiment_label"]
            s1_invoke_ok = False
            try:
                from engines.sentiment_engine import SentimentEngine, time_decay_weight  # type: ignore
                # [P1-5c] NOW 锚点策略：优先 news_list 非零 max ts（fixture 老数据 age 正常化）；缺省 fallback time.time()
                #   · 生产：SQLite 72h 内 max ts 距真实 time.time() 通常 <30min，可视为一致
                #   · 测试：fixture 构造 14.5mo 前数据 → 以最后一条新闻时间作为锚点，age=梯度几小时
                _fd_s1_ts_list = [int(n.get('timestamp_ms') or n.get('ts_ms') or 0) for n in news_list if isinstance(n, dict)]
                _fd_s1_ts_nonzero = [t for t in _fd_s1_ts_list if t > 0]
                _fd_s1_now_ms: int = (max(_fd_s1_ts_nonzero) if _fd_s1_ts_nonzero else int(time.time() * 1000))
                se = SentimentEngine()
                _weighted_scores_s1: List[tuple] = []
                for n in news_list:
                    if not isinstance(n, dict):
                        continue
                    txt = f"{n.get('title','')} {n.get('content','')}"
                    if not txt.strip():
                        continue
                    try:
                        r = se.analyze_text(txt)
                        if isinstance(r, dict) and isinstance(r.get("score"), (int, float)):
                            s = float(r["score"])
                            if -1.0 <= s <= 1.0:
                                # [P1-5c] 弱信号保护：若引擎 abs(s)<0.05 视为无法判断
                                #   （典型：中文内容被英文规则关键词 miss → score=0.0）
                                #   → 不截断，下行进入 sentiment_label 启发式分支；
                                #   只有强信号(abs≥0.05)才信任引擎直接加权
                                if abs(s) < 0.05:
                                    pass  # 继续下行，fallback 到 fixture sentiment_label
                                else:
                                    # 时间衰减：ts_ms=0（解析失败 fail-open）→ age=0 → w=1.0（等权等价）
                                    # 兼容双 key 命名：优先 timestamp_ms（生产 SQLite 解析）；回退 ts_ms（历史 fixture）
                                    _ts_v = int(n.get('timestamp_ms') or n.get('ts_ms') or 0)
                                    if _ts_v == 0:
                                        _age_h = 0.0
                                    else:
                                        _age_h = max(0.0, (_fd_s1_now_ms - _ts_v) / 1000.0 / 3600.0)
                                    w = time_decay_weight(_age_h, tau_hours=24.0)
                                    _weighted_scores_s1.append((float(s), float(w)))
                                    continue
                    except Exception:
                        pass
                    # SentimentEngine 失败 → 用 sentiment_label 启发式（仍加衰减权重）
                    lab = str(n.get("sentiment_label") or "").lower()
                    lab_score: Optional[float] = None
                    if lab in ("bullish", "positive", "long"):
                        lab_score = 0.6
                    elif lab in ("bearish", "negative", "short"):
                        lab_score = -0.6
                    elif lab == "neutral":
                        lab_score = 0.0
                    if lab_score is not None:
                        _ts_v = int(n.get('timestamp_ms') or n.get('ts_ms') or 0)
                        if _ts_v == 0:
                            _age_h = 0.0
                        else:
                            _age_h = max(0.0, (_fd_s1_now_ms - _ts_v) / 1000.0 / 3600.0)
                        w = time_decay_weight(_age_h, tau_hours=24.0)
                        _weighted_scores_s1.append((float(lab_score), float(w)))
                s1_invoke_ok = bool(_weighted_scores_s1)
            except Exception:
                s1_invoke_ok = False
                _weighted_scores_s1 = []  # noqa: F841
            if not _weighted_scores_s1:
                # 纯启发式兜底（从 sentiment_label）：仍然加衰减权重；NOW 同 S1 锚点策略
                _fd_s1_ts_list_b = [int(n.get('timestamp_ms') or n.get('ts_ms') or 0) for n in news_list if isinstance(n, dict)]
                _fd_s1_ts_nonzero_b = [t for t in _fd_s1_ts_list_b if t > 0]
                _fd_s1_now_ms_b: int = (max(_fd_s1_ts_nonzero_b) if _fd_s1_ts_nonzero_b else int(time.time() * 1000))
                try:
                    from engines.sentiment_engine import time_decay_weight as _tdw2  # type: ignore
                except Exception:
                    def _tdw2(a, tau=24.0):  # type: ignore
                        import math as _m
                        return 1.0 if a <= 0 else _m.exp(-max(0.0, float(a)) / max(1e-6, float(tau)))
                _ws_backup: List[tuple] = []
                for n in news_list:
                    if not isinstance(n, dict):
                        continue
                    lab = str(n.get("sentiment_label") or "").lower()
                    imp = float(n.get("importance") or 0.5)
                    score_h: Optional[float] = None
                    if lab in ("bullish", "positive", "long"):
                        score_h = 0.5 + 0.2 * imp
                    elif lab in ("bearish", "negative", "short"):
                        score_h = -0.5 - 0.2 * imp
                    elif lab == "neutral":
                        score_h = 0.0
                    if score_h is None:
                        continue
                    _ts_v = int(n.get('timestamp_ms') or n.get('ts_ms') or 0)
                    if _ts_v == 0:
                        _age_h = 0.0
                    else:
                        _age_h = max(0.0, (_fd_s1_now_ms_b - _ts_v) / 1000.0 / 3600.0)
                    w = _tdw2(_age_h, tau_hours=24.0)
                    _ws_backup.append((float(score_h), float(w)))
                if _ws_backup:
                    _tw = sum(w for _, w in _ws_backup)
                    if _tw > 1e-9:
                        s_mean = sum(s * w for s, w in _ws_backup) / _tw
                    else:
                        s_mean = 0.0
                else:
                    s_mean = 0.0
            else:
                _tw = sum(w for _, w in _weighted_scores_s1)
                if _tw > 1e-9:
                    s_mean = sum(s * w for s, w in _weighted_scores_s1) / _tw
                else:
                    s_mean = 0.0
            s_norm = max(-1.0, min(1.0, s_mean))
            s_01 = (s_norm + 1.0) / 2.0  # 归一 [0,1]
            D1 = (s_01 - 0.5) * 0.06

            # 3) S2 EventLedger（风险方向 r_dir + 意外程度 swm）
            #    优先代理模块；失败则启发式从 news_list 聚合
            r_dir: Optional[float] = None
            swm: float = 2.0  # 默认中性=2
            try:
                from engines.event_ledger_engine import generate_ledger  # type: ignore
                entries = generate_ledger(news_list)
                if isinstance(entries, list) and entries:
                    dirs: List[float] = []
                    surp = []
                    for e in entries:
                        if not isinstance(e, dict):
                            continue
                        rd = e.get("risk_dir")
                        if isinstance(rd, (int, float)):
                            dirs.append(float(rd))
                        elif isinstance(e.get("risk_action_proposal"), str):
                            ap = str(e["risk_action_proposal"]).lower()
                            if ap in ("increase", "hedge", "take_profit"):
                                dirs.append(1.0)
                            elif ap in ("reduce", "stop_loss"):
                                dirs.append(-1.0)
                        sb = e.get("surprise_bucket")
                        if isinstance(sb, str):
                            m = {"shock": 3, "major": 3, "moderate": 2, "mild": 1, "expected": 1}
                            if sb in m:
                                surp.append(m[sb])
                    if dirs:
                        r_dir = sum(dirs) / float(len(dirs))
                    if surp:
                        swm = sum(surp) / float(len(surp))
            except Exception:
                r_dir = None
            # 启发式兜底
            if r_dir is None:
                pos = sum(1 for n in news_list if isinstance(n, dict) and str(n.get("sentiment_label","")).lower() in ("bullish","positive","long"))
                neg = sum(1 for n in news_list if isinstance(n, dict) and str(n.get("sentiment_label","")).lower() in ("bearish","negative","short"))
                total = max(1, pos + neg)
                r_dir = float(pos - neg) / float(total)
                # swm 启发式: 含紧急/被黑/冲突 → 3；含"符合预期/获批/顺利"→1；其他2
                hi = 0; lo = 0
                for n in news_list:
                    if not isinstance(n, dict):
                        continue
                    txt = f"{n.get('title','')} {n.get('content','')}"
                    if any(k in txt for k in ("被黑", "漏洞", "冲突升级", "抛售", "加息超预期", "起诉")):
                        hi += 1
                    if any(k in txt for k in ("顺利", "通过", "符合预期", "正式发布", "获批")):
                        lo += 1
                if hi > lo:
                    swm = 3.0
                elif lo > hi:
                    swm = 1.0
                else:
                    swm = 2.0
            swm_c = max(1.0, min(3.0, float(swm)))
            r_diff = max(-1.0, min(1.0, float(r_dir or 0.0)))
            D2 = r_diff * 0.03 + (3.0 - swm_c) * (-0.008)
            D2 = max(-0.03, min(0.04, D2))

            # 4) S3 NewsContract pass_rate
            pass_rate: float = 0.8  # FAIL-OPEN 中性下限
            try:
                from engines.news_contract_validator import validate_batch  # type: ignore
                vr = validate_batch(news_list)
                if isinstance(vr, dict) and isinstance(vr.get("pass_rate"), (int, float)):
                    pass_rate = float(vr["pass_rate"])
            except Exception:
                pass_rate = 0.8
            pr = max(0.0, min(1.0, float(pass_rate)))
            D3 = max(0.0, pr - 0.8) * 0.02
            # 暴露给 TC-14 S3 拦截钩子（若存在 monkeypatch 该函数则调用，异常会被 L4 try/except 吞）
            try:
                hook = getattr(self, "_fd_S_s3_newscontract_passrate", None)
                if callable(hook):
                    pr_override = hook(pr, news_list)
                    if isinstance(pr_override, (int, float)):
                        pass_rate = float(pr_override)
                        D3 = max(0.0, pass_rate - 0.8) * 0.02
            except Exception:
                pass

            # 5) S4 EventMapping：冲突率 crr + 一致性 mr
            total = len(news_list)
            mismatches = 0
            mono = 0
            try:
                from engines.event_mapping_engine import map_event_type as _map_fn  # type: ignore
                etypes: List[str] = []
                for n in news_list:
                    if not isinstance(n, dict):
                        continue
                    title = str(n.get("title") or "")
                    body = str(n.get("content") or "")
                    topic = str(n.get("event_type") or "")
                    category = str(n.get("category") or "")
                    mapped = _map_fn(title=title, body=body, topic=topic, category=category)
                    etypes.append(mapped)
                    declared = str(n.get("event_type") or "")
                    if declared and mapped != declared and mapped != "unknown":
                        mismatches += 1
                # 统计出现最多的类别占比 → mono
                if etypes:
                    from collections import Counter
                    cnt = Counter(etypes)
                    top_c = cnt.most_common(1)[0][1]
                    mono = top_c
            except Exception:
                pass
            t4_total = max(1, total)
            crr = float(mismatches) / float(t4_total)
            mr = float(mono) / float(t4_total)
            sm_sign = 1.0 if s_01 > 0.5 else (-1.0 if s_01 < 0.5 else 0.0)
            D4 = (crr - 0.25) * (-0.08) + (mr - 0.15) * sm_sign * 0.05

            # 6) S5 Narrative dao_traj（top narrative trajectory weighted）
            n_total = 0
            top_traj: float = 0.0
            try:
                from engines.narrative_engine import build_narratives  # type: ignore
                nr = build_narratives(news_list)
                if isinstance(nr, dict):
                    narr_list = nr.get("narratives") or []
                    if isinstance(narr_list, list) and narr_list:
                        srt = sorted(
                            narr_list,
                            key=lambda x: float(x.get("heat_score") or x.get("heat") or 0.0),
                            reverse=True,
                        )
                        top = srt[0] if isinstance(srt[0], dict) else {}
                        t = top.get("trajectory") or top.get("traj") or top.get("trend")
                        if isinstance(t, (int, float)):
                            top_traj = float(t)
                        n_total = len(srt)
                    # 若为空，fallback 到 reg_policy
                    if n_total == 0 and isinstance(nr.get("regulation_policy_traj"), (int, float)):
                        top_traj = float(nr["regulation_policy_traj"])
                        n_total = 1
            except Exception:
                n_total = 0
                top_traj = 0.0
            # S5 失败兜底 → 启发式（sent 方向）
            if n_total == 0:
                top_traj = s_norm  # 和情绪同方向（中性 0）
                n_total = 1
            t5_t = max(-1.0, min(1.0, float(top_traj)))
            D5 = t5_t * 0.05 * min(1.0, float(n_total) / 3.0)
            # TC-14 钩子
            try:
                hook = getattr(self, "_fd_S_s5_narrative_traj", None)
                if callable(hook):
                    D5 = float(hook(t5_t, n_total))
            except Exception:
                pass

            # S 级 5 deltas 求和 clamp ±0.10
            # TC-7 钩子：允许 5 delta 返回值被 monkeypatch 替换（强制超界验证 clamp）
            try:
                hook = getattr(self, "_fd_S_dao_deltas", None)
                if callable(hook):
                    overrides = hook(news_list, D1, D2, D3, D4, D5)
                    if isinstance(overrides, list) and overrides:
                        deltas = [float(x) for x in overrides]
                    else:
                        deltas = [D1, D2, D3, D4, D5]
                else:
                    deltas = [D1, D2, D3, D4, D5]
            except Exception:
                deltas = [D1, D2, D3, D4, D5]
            total_s = sum(deltas)
            return max(-0.1, min(0.1, round(total_s, 6)))
        except Exception:
            return 0.0

    def _fd_S_tian_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        try:
            if not isinstance(coin_data, (dict, type(None))):
                return 0.0
            news_list = self._fetch_news_72h_limit200()
            if not isinstance(news_list, list) or len(news_list) == 0:
                return 0.0
            total_n = len(news_list)

            # T1 政策情绪 × 政策条目数权重（含货币政策/监管政策/政策关键词）
            #    P1 升级：SentimentEngine 真实推理 + 时间衰减加权；3层 FAIL-OPEN fallback 回启发式
            policy_news: List[Dict[str, Any]] = []
            POL_KEYWORDS = ("monetary_policy", "crypto_regulation", "us_policy", "regul",
                            "降息", "加息", "监管", "审批", "SEC", "MiCA", "法案", "政策",
                            "货币政策", "央行")
            for n in news_list:
                if not isinstance(n, dict):
                    continue
                etype = str(n.get("event_type") or "").lower()
                txt = f"{n.get('title','')} {n.get('content','')}"
                is_pol = (etype in ("monetary_policy", "crypto_regulation", "us_policy", "us_data")
                          or any(k.lower() in txt.lower() for k in POL_KEYWORDS))
                if is_pol:
                    policy_news.append(n)
            p_count = len(policy_news)

            # [P1-5c] NOW 锚点策略：同 S1（优先 news_list 非零 max ts → fallback time.time()）
            _t1_ts_list = [int(n.get('timestamp_ms') or n.get('ts_ms') or 0) for n in news_list if isinstance(n, dict)]
            _t1_ts_nonzero = [t for t in _t1_ts_list if t > 0]
            _t1_now_ms: int = (max(_t1_ts_nonzero) if _t1_ts_nonzero else int(time.time() * 1000))
            _t1_weighted: List[tuple] = []
            _t1_eng_works = False
            try:
                from engines.sentiment_engine import SentimentEngine, time_decay_weight as _t1_tdw  # type: ignore
                _t1_se = SentimentEngine()
                _t1_eng_works = True
            except Exception:
                _t1_eng_works = False
                _t1_se = None  # type: ignore
                # engines import 失败时造一个等价的衰减函数（与 time_decay_weight 同公式）
                import math as _tm
                def _t1_tdw(a: float, tau: float = 24.0) -> float:
                    return 1.0 if a <= 0 else _tm.exp(-max(0.0, float(a)) / max(1e-6, float(tau)))

            if _t1_eng_works and p_count > 0 and _t1_se is not None:
                # 成功分支：每条政策新闻 SentimentEngine + 时间衰减；单条失败 → 启发式±0.7（保守不极值）
                for n in policy_news:
                    if not isinstance(n, dict):
                        continue
                    txt = f"{n.get('title','')} {n.get('content','')}"
                    r_score: Optional[float] = None
                    try:
                        r = _t1_se.analyze_text(txt)
                        if isinstance(r, dict) and isinstance(r.get("score"), (int, float)):
                            s = float(r["score"])
                            if -1.0 <= s <= 1.0:
                                # [P1-5c] 弱信号保护：abs(s)<0.05 视为引擎无法判断(中文关键词miss)
                                #   → 置 None 进入下方启发式 r_score 赋值，而非用 0.0 主导
                                if abs(s) < 0.05:
                                    r_score = None
                                else:
                                    r_score = s
                    except Exception:
                        r_score = None
                    if r_score is None:
                        # 本条 eng 失败：启发式±0.7（Self-Review §2b：与 import 全失败的±1.0 区分层级）
                        lab = str(n.get("sentiment_label") or "").lower()
                        if lab in ("bullish", "positive", "long"):
                            r_score = 0.7
                        elif lab in ("bearish", "negative", "short"):
                            r_score = -0.7
                        else:
                            r_score = 0.0
                    # 时间衰减（ts=0 fail-open → age=0 → w=1.0；双 key 兼容）
                    _ts_v = int(n.get('timestamp_ms') or n.get('ts_ms') or 0)
                    if _ts_v == 0:
                        _age_h = 0.0
                    else:
                        _age_h = max(0.0, (_t1_now_ms - _ts_v) / 1000.0 / 3600.0)
                    w = _t1_tdw(_age_h, tau_hours=24.0)
                    _t1_weighted.append((float(r_score), float(w)))
                # 加权聚合
                if _t1_weighted:
                    _tw = sum(w for _, w in _t1_weighted)
                    if _tw > 1e-9:
                        s_pol = sum(s * w for s, w in _t1_weighted) / _tw
                    else:
                        s_pol = 0.0
                else:
                    s_pol = 0.0
            elif p_count > 0:
                # engines import 完全失败 → 字节等价旧代码（逐行旧启发式等权）
                s_pol_sum = 0.0
                for n in policy_news:
                    lab = str(n.get("sentiment_label") or "").lower()
                    if lab in ("bullish", "positive", "long"):
                        s_pol_sum += 1.0
                    elif lab in ("bearish", "negative", "short"):
                        s_pol_sum += -1.0
                    else:
                        s_pol_sum += 0.0
                s_pol = max(-1.0, min(1.0, s_pol_sum / float(p_count)))
            else:
                s_pol = 0.0
            # s_pol 归一 [0,1] 后 * 0.08 × min(1, p/3)
            s_pol = max(-1.0, min(1.0, float(s_pol)))
            s_pol_01 = (s_pol + 1.0) / 2.0
            _T1_discard = (s_pol_01 - 0.5) * 2.0  # noqa: F841（保留旧中间变量，防止上游调试引用）
            # T1 公式与旧实现一字不动：s_pol * 0.08 × min(1, p_count/3)
            T1 = float(s_pol) * 0.08 * min(1.0, float(p_count) / 3.0)

            # T2 紧急压制：urgency_ratio > 0.4 → -0.05；>0.2 → -0.03；另 security/geo 类(规避) 每 1 项 -0.01（min -0.03）
            urgent_events = 0
            avoid_count = 0
            URGENCY_KW = ("被黑", "黑客", "漏洞", "冲突", "SEC 起诉", "抛售", "破产", "冻结资金", "暂停提款")
            for n in news_list:
                if not isinstance(n, dict):
                    continue
                etype = str(n.get("event_type") or "").lower()
                txt = f"{n.get('title','')} {n.get('content','')}"
                if etype in ("security_incident", "security", "geopolitics"):
                    avoid_count += 1
                if any(k.lower() in txt.lower() for k in URGENCY_KW):
                    urgent_events += 1
            urgency_ratio = float(urgent_events) / float(max(1, total_n))
            T2 = 0.0
            if urgency_ratio > 0.4:
                T2 += -0.05
            elif urgency_ratio > 0.2:
                T2 += -0.03
            if avoid_count >= 1:
                T2 += min(0.0, float(avoid_count) * -0.01) if False else -0.03 if avoid_count >= 1 else 0.0
            # 保守：避免一次性 T2 压 -0.08，clamp
            T2 = max(-0.08, T2)

            # T3 NewsContract pass_rate（与 D3 同源系数）
            pass_rate = 0.8
            try:
                from engines.news_contract_validator import validate_batch
                vr = validate_batch(news_list)
                if isinstance(vr, dict) and isinstance(vr.get("pass_rate"), (int, float)):
                    pass_rate = float(vr["pass_rate"])
            except Exception:
                pass_rate = 0.8
            T3 = max(0.0, float(pass_rate) - 0.8) * 0.02

            # T4 EventType 增长率：前后半段政策类比值；按与 T1 一致的 is_pol 判定统计
            sorted_n = sorted(
                (n for n in news_list if isinstance(n, dict) and isinstance(n.get("ts_ms"), (int, float))),
                key=lambda n: float(n.get("ts_ms") or 0),
            )
            T4 = 0.0
            if len(sorted_n) >= 4:
                mid = len(sorted_n) // 2
                first_half = sorted_n[:mid]
                second_half = sorted_n[mid:]
                POL_ETYPES = ("monetary_policy", "crypto_regulation", "us_policy", "us_data", "geopolitics")
                def _pol_count(arr):
                    cnt = 0
                    for n in arr:
                        if not isinstance(n, dict):
                            continue
                        etype = str(n.get("event_type") or "").lower()
                        txt = f"{n.get('title','')} {n.get('content','')}"
                        is_pol = (etype in POL_ETYPES
                                  or any(k.lower() in txt.lower() for k in POL_KEYWORDS))
                        if is_pol:
                            cnt += 1
                    return cnt
                c_f = _pol_count(first_half)
                c_s = _pol_count(second_half)
                ratio = (float(c_s) + 1.0) / (float(c_f) + 1.0)  # Laplace 平滑
                if ratio > 1.1:
                    T4 = +0.03
                elif ratio < 0.7:
                    T4 = -0.04
                else:
                    T4 = 0.0

            # T5 Narrative reg_policy_traj × 0.04 × ev（ev=number of reg policy events）
            reg_ev = len(policy_news)
            reg_traj = 0.0
            try:
                from engines.narrative_engine import build_narratives
                nr = build_narratives(policy_news or news_list)
                if isinstance(nr, dict) and isinstance(nr.get("regulation_policy_traj"), (int, float)):
                    reg_traj = float(nr["regulation_policy_traj"])
                elif isinstance(nr, dict):
                    nl = nr.get("narratives") or []
                    for n in nl:
                        if not isinstance(n, dict):
                            continue
                        nm = str(n.get("id") or n.get("name") or "").lower()
                        if "regul" in nm or "polic" in nm:
                            t = n.get("trajectory") or n.get("traj") or n.get("trend") or 0.0
                            if isinstance(t, (int, float)):
                                reg_traj = float(t)
                            break
            except Exception:
                reg_traj = 0.0
            ev = max(1, reg_ev) if reg_ev > 0 else 1
            T5 = max(-1.0, min(1.0, reg_traj)) * 0.04 * float(ev)

            deltas = [T1, T2, T3, T4, T5]
            total_t = sum(deltas)
            return max(-0.1, min(0.1, round(total_t, 6)))
        except Exception:
            return 0.0

    # ================================================================
    # 7引擎 A 级 2 delta（FAIL-OPEN 0.0）
    # Spec §4.4 D6 = 3D least_resistance → dao（语义绑定方向）
    #      D6 ∈ ±0.04 = sign(direction) * (0.01 + |velocity|*0.02 + |acceleration|*0.01) * confidence
    # Spec §4.5 T7 = SignalEngine._adaptive_weight → tian
    #      w_ratio = effective_weight / base_weight; T7 = (w_ratio-1) * 0.03; clamp [-0.02, +0.02]
    # A 级双保险 clamp ±0.05
    # ================================================================
    def _fd_A_dao_boost(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
    ) -> float:
        try:
            if not isinstance(coin_data, (dict, type(None))):
                return 0.0
            # 来源优先级：
            # 1) system_state 如果是 dict 且含 r3d 直接取（TC 构造常用）
            # 2) coin_data 里的 "least_resistance_3d" / "r3d" 字段
            # 3) 调 engines.least_resistance.compute_resistance_3d（若提供了 raw_score+history）
            # 4) A 级无数据 → 0.0
            r3d: Any = None
            if isinstance(system_state, dict):
                r3d = system_state.get("r3d") or system_state.get("least_resistance_3d")
                # 兼容：TC 直接传裸 r3d dict（含 direction/confidence 键）作为第二个参数传入
                if not isinstance(r3d, dict) and "direction" in system_state and "confidence" in system_state:
                    r3d = system_state
            if not isinstance(r3d, dict) and isinstance(coin_data, dict):
                r3d = coin_data.get("r3d") or coin_data.get("least_resistance_3d")
                if not isinstance(r3d, dict) and "direction" in coin_data and "confidence" in coin_data:
                    r3d = coin_data
            if not isinstance(r3d, dict):
                # A6 真实引擎：尝试 compute（coin_data 提供 raw_score/history 才调用）
                raw = None
                hist = None
                if isinstance(coin_data, dict):
                    raw = coin_data.get("raw_score")
                    hist = coin_data.get("resistance_history")
                if isinstance(raw, (int, float)) and isinstance(hist, list):
                    try:
                        from engines.least_resistance import compute_resistance_3d  # type: ignore
                        r3d = compute_resistance_3d(float(raw), hist)
                    except Exception:
                        r3d = None
            if not isinstance(r3d, dict):
                return 0.0
            direction = r3d.get("direction")
            velocity = r3d.get("velocity")
            acceleration = r3d.get("acceleration")
            confidence = r3d.get("confidence")
            if not isinstance(direction, (int, float)):
                return 0.0
            v = abs(float(velocity)) if isinstance(velocity, (int, float)) else 0.0
            a = abs(float(acceleration)) if isinstance(acceleration, (int, float)) else 0.0
            conf = float(confidence) if isinstance(confidence, (int, float)) else 1.0
            conf = max(0.0, min(1.0, conf))
            sign = 1.0 if float(direction) > 0 else (-1.0 if float(direction) < 0 else 0.0)
            d6 = sign * (0.01 + min(1.0, v) * 0.02 + min(1.0, a) * 0.01) * conf
            d6 = max(-0.04, min(0.04, d6))
            # A 级双保险 ±0.05
            return max(-0.05, min(0.05, round(d6, 6)))
        except Exception:
            return 0.0

    def _fd_A_tian_boost(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
    ) -> float:
        try:
            if not isinstance(coin_data, (dict, type(None))):
                return 0.0
            sig: Any = None
            if isinstance(system_state, dict):
                sig = system_state.get("signal_engine") or system_state.get("signal")
                # 兼容：TC 直接传裸 signal dict（含 base_weight/effective_weight 键）
                if not isinstance(sig, dict) and "base_weight" in system_state and "effective_weight" in system_state:
                    sig = system_state
            if not isinstance(sig, dict) and isinstance(coin_data, dict):
                sig = coin_data.get("signal_engine") or coin_data.get("signal")
                if not isinstance(sig, dict) and "base_weight" in coin_data and "effective_weight" in coin_data:
                    sig = coin_data
            if not isinstance(sig, dict):
                # 空 → 0.0（A 级无数据中性）
                return 0.0
            base_w = sig.get("base_weight")
            eff_w = sig.get("effective_weight")
            if not isinstance(base_w, (int, float)) or not isinstance(eff_w, (int, float)):
                return 0.0
            bw = float(base_w)
            if bw <= 1e-12:
                return 0.0
            w_ratio = float(eff_w) / bw
            # (w_ratio-1.0) ∈ [-0.7, +1.0]（Spec §4.5 base → effective 范围 0.3~2.0 × base）
            raw = (w_ratio - 1.0) * 0.03
            # T7 clamp [-0.02, +0.02]
            raw = max(-0.02, min(0.02, raw))
            # A 级双保险 ±0.05
            return max(-0.05, min(0.05, round(raw, 6)))
        except Exception:
            return 0.0

    def _compute_calendar_seasonality(
        self, month: int, day: int = 15, weekday: int = 0
    ) -> int:
        """日历季节性：Q1/Q4效应 + 周末效应。

        §三 L127：统计历史均值，正收益期→加分。
        """
        base = _MONTH_BASE_SCORES.get(month, 50)

        # 周末效应（§三 L127）：周末波动率低 → 评分中性偏低
        if weekday >= 5:  # 周六/日
            base = max(40, base - 5)

        return int(np.clip(base, 0, 100))

    def _compute_merrill_clock_score(self, phase: str) -> int:
        """美林时钟四阶段→评分映射。

        §三 L128：复苏对风险资产利好→加分。
        """
        return _MERRILL_PHASE_SCORES.get(phase.upper(), 50)

    def _compute_volatility_cycle_score(self, atr_percentile: float) -> int:
        """波动率周期：ATR分位→评分。

        §三 L129：高位适合趋势策略，低位适合均值回归。
        """
        # atr_percentile ∈ [0, 1]
        # 高分位→趋势策略利好→高分；低分位→均值回归→中分
        # 线性映射：0→45, 1→85
        score = 45 + atr_percentile * 40
        return int(np.clip(round(score), 0, 100))

    def _compute_liquidity_cycle_score(self, liquidity_score: float) -> int:
        """流动性周期：QE/QT阶段→评分。

        §三 L130：QE→加分，QT→减分。
        """
        # liquidity_score ∈ [0, 1]：0=QT（紧缩），1=QE（宽松）
        # 线性映射：0→25, 1→75
        score = 25 + liquidity_score * 50
        return int(np.clip(round(score), 0, 100))

    # ==================================================================
    # 地 — 市场结构与价格位置（§三 L142-172）
    # ==================================================================

    def _compute_di(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """地维度：regime代理 + 弹簧力场MA + 补强指标。"""
        try:
            # 子指标1：regime 代理（后置层5态→分数映射）
            regime = (coin_data or {}).get("regime", "ranging")
            regime_score = self._compute_regime_score(regime)

            # 子指标2：弹簧力场MA评分
            ma_score = self._compute_spring_force_score(coin_data)

            # 子指标3-5：补强指标（盘整持续/FTD/MA200距离）
            consolidation = self._compute_consolidation_duration(coin_data)
            ftd = self._compute_follow_through_day(coin_data)
            ma200_dist = self._compute_ma200_distance(coin_data)

            # 5子指标等权
            di_raw = (regime_score + ma_score + consolidation + ftd + ma200_dist) / 5.0
            # Panewslab 增强（±20% 范围微调）：杠杆率、巨鲸净流、广度命中、RWA 动量
            di_raw = di_raw * (1.0 + self._pn_di_boost(coin_data))
            return _normalize_0_100(di_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["di"]

    # ------------------------------------------------------------------
    # Panewslab：地维度 delta boost [-0.2, 0.2]（fail-open 0）
    # 市场结构补充信号：交易所净流入（抛压/吸筹）、OI 杠杆率（极端泡沫/底部缩杠杆）、
    #                  链上广度命中（牛熊确认）、24h 市场涨跌动量
    # ------------------------------------------------------------------
    def _pn_di_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        if not coin_data:
            return 0.0
        deltas: List[float] = []
        cd = coin_data or {}
        # P1：交易所巨鲸净流（+入=抛压减分；-出=吸筹加分）
        netflow_cap = cd.get("pn_whale_netflow_cap_pct")
        if isinstance(netflow_cap, (int, float)):
            # ±0.3% cap → ±0.06
            deltas.append(max(-0.06, min(0.06, float(netflow_cap) * (-20.0))))
        # P2：OI 杠杆率（低杠杆=底部→加分；极端杠杆=>0.25→泡沫减分）
        oi_cap = cd.get("pn_leverage_ratio_oi_cap")
        if isinstance(oi_cap, (int, float)):
            lev = float(oi_cap)
            # 0.05 以下 → +0.05（缩杠杆）；0.10 → 0；0.20 → -0.05
            deltas.append(max(-0.07, min(0.05, (0.10 - lev) * 1.0)))
        # P3：链上广度命中 ratio（越高越强→加分）
        bhr = cd.get("pn_holdings_breadth_hit_ratio")
        if isinstance(bhr, (int, float)):
            deltas.append((float(bhr) - 0.5) * 0.08)
        # P4：omnitools 总体命中率（cycle + holdings 综合）
        coh = cd.get("pn_cycle_omnitools_hit_ratio")
        if isinstance(coh, (int, float)):
            deltas.append((float(coh) - 0.5) * 0.08)
        # P5：全球市值 24h 变化动量 → 支撑/阻力
        gchg = cd.get("pn_global_change24_pct")
        if isinstance(gchg, (int, float)):
            # 大涨>5%=过热减分；大跌<-5%=超跌加分；其他线性
            r = float(gchg)
            if r > 5:       deltas.append(-0.04)
            elif r < -5:    deltas.append(0.04)
            else:           deltas.append(r * 0.008)
        # P6：RWA 7日变化（机构对 RWA/加密的宏观仓位判断）
        rwa7d = cd.get("pn_rwa_change7d_pct")
        if isinstance(rwa7d, (int, float)):
            deltas.append(max(-0.04, min(0.04, float(rwa7d) * 0.008)))
        if not deltas:
            return 0.0
        avg = sum(deltas) / float(len(deltas))
        return max(-0.2, min(0.2, avg))

    def _compute_regime_score(self, regime: str) -> int:
        """后置层5态→分数映射。

        §11.1 L1204：地=regime→分数映射。
        """
        _REGIME_SCORES = {
            "trend_up": 75,      # 上升趋势
            "trend_down": 30,    # 下降趋势
            "ranging": 50,       # 震荡
            "high_volatility": 45, # 高波动
            "breakout": 70,      # 突破
        }
        return _REGIME_SCORES.get(regime, 50)

    def _compute_spring_force_score(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """弹簧力场5MA评分。

        §三 L147：MA30/65/128/200 + 1400大周期。
        """
        if not coin_data:
            return 50
        # 从 coin_data 读取弹簧力场评分（如果存在）
        spring = coin_data.get("spring_force_score")
        if spring is None:
            return 50
        return int(np.clip(round(spring), 0, 100))

    def _compute_consolidation_duration(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """盘整持续时间量化。

        §三 L153：价格振幅/ATR比值，持续低于阈值=盘整。
        """
        if not coin_data:
            return 50
        amplitude = coin_data.get("price_amplitude")
        atr = coin_data.get("atr")
        if amplitude is None or atr is None or atr <= 0:
            return 50
        # 振幅/ATR比值低 → 盘整 → 中性偏低（适合均值回归）
        ratio = float(amplitude) / float(atr)
        if ratio < 2.0:
            return 45  # 盘整
        elif ratio < 4.0:
            return 55  # 正常
        else:
            return 65  # 趋势

    def _compute_follow_through_day(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """Follow-through Day确认。

        §三 L154：下跌→上涨转换信号。
        """
        if not coin_data:
            return 50
        ftd_signal = coin_data.get("ftd_signal")
        if ftd_signal is None:
            return 50
        if ftd_signal > 0:
            return 70  # FTD正面信号
        elif ftd_signal < 0:
            return 30  # FTD负面信号
        return 50

    def _compute_ma200_distance(self, coin_data: Optional[Dict[str, Any]]) -> int:
        """价格vs MA200距离分位。

        §三 L155：分位统计。
        """
        if not coin_data:
            return 50
        ma200_dist_pct = coin_data.get("ma200_distance_percentile")
        if ma200_dist_pct is None:
            return 50
        # 距离MA200上方远 → 强势 → 高分
        # 距离MA200下方远 → 弱势 → 低分
        score = 50 + (ma200_dist_pct - 0.5) * 60
        return int(np.clip(round(score), 0, 100))

    # ==================================================================
    # P0-辅助：_cls_get 按类取值优先，缺失回退全局字段（方案 A 增量嵌套 + 全局回退）
    # ==================================================================
    @staticmethod
    def _cls_get(
        system_state: Optional[Dict[str, Any]],
        cls: str,
        key: str,
        default: Any,
    ) -> Any:
        """按优先级：system_state['_by_class'][cls][key] > system_state[key] > default。

        方案 A：fail-open 三层兜底——即使调用方没传 _by_class，也完全兼容旧行为。
        """
        if not system_state:
            return default
        # 1. 优先取按类嵌套值
        by_cls = system_state.get("_by_class")
        if isinstance(by_cls, dict):
            cls_block = by_cls.get(cls)
            if isinstance(cls_block, dict) and (key in cls_block):
                return cls_block[key]
        # 2. 回退：取全局根级值
        if key in system_state:
            return system_state[key]
        # 3. 兜底：默认值
        return default

    # ==================================================================
    # 将 — 决策质量与执行纪律（§三 L176-210）
    # ==================================================================

    def _classify_terrain(self, coin_data: Optional[Dict[str, Any]]) -> str:
        """六种地形分类（§三 L157-166，《孙子兵法·地形篇》）。

        Returns: tong/gua/zhi/ai/xian/yuan
        """
        if not coin_data:
            return "yuan"  # 无数据→远形（观望）
        regime = coin_data.get("regime", "ranging")
        atr_pct = coin_data.get("atr_percentile", 0.5)
        amplitude = coin_data.get("price_amplitude", 0.0)
        atr = coin_data.get("atr", 1.0)
        ratio = amplitude / atr if atr > 0 else 0.0

        # 通形：趋势明确（trend + 高振幅）
        if regime in ("trend_up", "trend_down") and ratio > 3.0:
            return "tong"
        # 挂形：突破后难回撤（trend + 低振幅）
        if regime in ("trend_up", "trend_down") and ratio <= 3.0:
            return "gua"
        # 险形：高波动区间（ranging + 高ATR分位）
        if regime == "ranging" and atr_pct > 0.7:
            return "xian"
        # 支形：震荡盘整（ranging + 低振幅）
        if regime == "ranging" and ratio < 2.0:
            return "zhi"
        # 隘形：关键支撑阻力位（ranging + 中振幅 + 低ATR）
        if regime == "ranging" and atr_pct < 0.4 and 2.0 <= ratio <= 3.0:
            return "ai"
        # 远形：趋势不明（其余）
        return "yuan"

    def _compute_jiang(
        self,
        system_state: Optional[Dict[str, Any]],
        cls: str,
        coin_data: Optional[Dict[str, Any]] = None,
    ) -> int:
        """将维度：智×20% + 信×25% + 仁×25% + 勇×15% + 严×15%。

        §三 L196：将 = 智×20% + 信×25% + 仁×25% + 勇×15% + 严×15%
        P0：5子指标按 cls 优先读 _by_class[cls]，缺失回退全局字段。
        """
        try:
            zhi = self._compute_zhi(system_state, cls)
            xin = self._compute_xin(system_state, cls)
            ren = self._compute_ren(system_state, cls)
            yong = self._compute_yong(system_state, cls)
            yan = self._compute_yan(system_state, cls)

            jiang_raw = zhi * 0.20 + xin * 0.25 + ren * 0.25 + yong * 0.15 + yan * 0.15
            # BlockBeats 律动增强（±20% 范围微调）：jiang 维度抄底逃顶信号（机构共识）
            jiang_raw = jiang_raw * (1.0 + self._bb_jiang_boost(coin_data))
            return _normalize_0_100(jiang_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["jiang"]

    def _compute_zhi(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """智：因子覆盖度/回测完整度/样本外验证。P0：按 cls 取值。"""
        if not system_state:
            return 50
        factor_coverage = self._cls_get(system_state, cls, "factor_coverage_pct", 0.5)
        score = factor_coverage * 100
        return int(np.clip(round(score), 0, 100))

    def _compute_xin(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """信：IC/胜率/盈亏比。P0：按 cls 取值实现差异化 win_rate/profit_factor。"""
        if not system_state:
            return 50
        win_rate = self._cls_get(system_state, cls, "win_rate", 0.5)
        profit_factor = self._cls_get(system_state, cls, "profit_factor", 1.0)
        wr_score = win_rate * 100
        pf_score = min(100, (profit_factor / 2.0) * 100)
        return int(np.clip(round((wr_score + pf_score) / 2.0), 0, 100))

    def _compute_ren(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """仁：单笔风险≤1-2%/连续亏损降仓。P0：按 cls 取值。"""
        if not system_state:
            return 50
        position_pct = self._cls_get(system_state, cls, "position_pct", 0.20)
        max_consecutive = self._cls_get(system_state, cls, "max_consecutive_losses", 999)
        risk_score = 80 if position_pct <= 0.02 else 50
        rule_score = 80 if max_consecutive <= 5 else 30
        return int(np.clip(round((risk_score + rule_score) / 2.0), 0, 100))

    def _compute_yong(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """勇：执行果断。P0：按 cls 取值（当前全局相同，未来可按类设置自动执行权限）。"""
        if not system_state:
            return 50
        auto_execute = self._cls_get(system_state, cls, "auto_execute", False)
        return 80 if auto_execute else 50

    def _compute_yan(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """严：止损/回撤/单日交易次数/仓位上限。P0：按 cls 取值。"""
        if not system_state:
            return 50
        has_stop_loss = self._cls_get(system_state, cls, "has_stop_loss", True)
        has_drawdown_limit = self._cls_get(system_state, cls, "has_drawdown_limit", True)
        has_daily_trade_limit = self._cls_get(system_state, cls, "has_daily_trade_limit", False)
        has_position_cap = self._cls_get(system_state, cls, "has_position_cap", True)
        score = (has_stop_loss * 25 + has_drawdown_limit * 25 +
                 has_daily_trade_limit * 25 + has_position_cap * 25)
        return int(np.clip(round(score), 0, 100))

    # ==================================================================
    # 法 — 策略库与执行规则（§三 L214-242）
    # ==================================================================

    def _compute_fa(
        self,
        system_state: Optional[Dict[str, Any]],
        cls: str,
    ) -> int:
        """法维度：策略库完备性×20% + 策略适配度×25% + 风控规则×25% + 回测验证×20% + 复盘迭代×10%。

        §三 L240：法 = 策略库完备性×20% + 策略适配度×25% + 风控规则×25% + 回测验证×20% + 复盘迭代×10%
        P0：5子指标按 cls 优先读 _by_class[cls]，缺失回退全局字段。
        """
        try:
            completeness = self._compute_strategy_completeness(system_state, cls)
            adaptation = self._compute_strategy_adaptation(system_state, cls)
            risk_rules = self._compute_risk_rule_completeness(system_state, cls)
            backtest = self._compute_backtest_verification(system_state, cls)
            review = self._compute_review_iteration(system_state, cls)

            fa_raw = (completeness * 0.20 + adaptation * 0.25 +
                      risk_rules * 0.25 + backtest * 0.20 + review * 0.10)
            return _normalize_0_100(fa_raw / 100.0)
        except Exception:
            return DEFAULT_NEUTRAL_SCORES["fa"]

    def _compute_strategy_completeness(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """策略库完备性：6类策略是否实现。P0：按 cls 取值（不同类策略库可以不同）。"""
        if not system_state:
            return 50
        implemented = self._cls_get(system_state, cls, "implemented_strategies", [])
        total = 6
        count = len([s for s in implemented if s])
        score = (count / total) * 100
        return int(np.clip(round(score), 0, 100))

    def _compute_strategy_adaptation(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """策略适配度：地形vs策略匹配。P0：按 cls 取值。"""
        if not system_state:
            return 50
        match_pct = self._cls_get(system_state, cls, "strategy_match_pct", 0.5)
        return int(np.clip(round(match_pct * 100), 0, 100))

    def _compute_risk_rule_completeness(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """风控规则完整度：止损/回撤/仓位/相关性。P0：按 cls 取值（不同类风控强度可以不同）。"""
        if not system_state:
            return 50
        rules = self._cls_get(system_state, cls, "risk_rules", {})
        rules = rules if isinstance(rules, dict) else {}
        has_sl = rules.get("stop_loss", True)
        has_dd = rules.get("drawdown_limit", True)
        has_pos = rules.get("position_cap", True)
        has_corr = rules.get("correlation_limit", False)
        score = (has_sl + has_dd + has_pos + has_corr) * 25
        return int(np.clip(round(score), 0, 100))

    def _compute_backtest_verification(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """回测验证度：样本外/夏普/最大回撤/换手率。P0：按 cls 取值（不同类夏普/回撤差异显著）。"""
        if not system_state:
            return 50
        backtest = self._cls_get(system_state, cls, "backtest_metrics", {})
        backtest = backtest if isinstance(backtest, dict) else {}
        sharpe = backtest.get("sharpe", 0.0)
        max_dd = backtest.get("max_drawdown", 0.5)
        sharpe_score = min(100, (sharpe / 2.0) * 100)
        dd_score = max(0, 100 - max_dd * 200)
        return int(np.clip(round((sharpe_score + dd_score) / 2.0), 0, 100))

    def _compute_review_iteration(self, system_state: Optional[Dict[str, Any]], cls: str) -> int:
        """复盘迭代机制：定期归因/降权/退役。P0：按 cls 取值。"""
        if not system_state:
            return 50
        has_review = self._cls_get(system_state, cls, "has_review_cycle", False)
        has_retirement = self._cls_get(system_state, cls, "has_strategy_retirement", False)
        score = (has_review + has_retirement) * 50
        return int(np.clip(round(score), 0, 100))

    # ------------------------------------------------------------------
    # BlockBeats（区块律动 Dataview）：dao 维度 delta boost [-0.2, 0.2]
    # 来源：律动 脉动归一 sentiment_norm + 政策景气度替代 + Top10 流入结构
    # ------------------------------------------------------------------
    def _bb_dao_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        if not coin_data or not isinstance(coin_data, dict):
            return 0.0
        deltas: List[float] = []
        cd = coin_data
        # B1：blockbeats_sentiment_norm [0,1]；0.5→0, 1→+0.06, 0→-0.06
        sent_norm = cd.get("blockbeats_sentiment_norm")
        if isinstance(sent_norm, (int, float)):
            deltas.append((float(sent_norm) - 0.5) * 0.12)
        # B2：blockbeats_policy_sentiment_score 代理（脉动/归一 → 道政策景气叠加）[0,100]
        pol = cd.get("blockbeats_policy_sentiment_score")
        if isinstance(pol, (int, float)):
            pol_val = float(pol) if pol > 1.0 else float(pol) * 100.0
            deltas.append(((pol_val / 100.0) - 0.5) * 0.08)
        # B3：blockbeats_inflow_top1_symbol 结构——BTC 类流入=风险偏好+；Stable=避险-
        top1 = cd.get("blockbeats_inflow_top1_symbol")
        if isinstance(top1, str) and top1:
            t = top1.upper()
            if "BTC" in t or "ETH" in t or "SOL" in t:
                deltas.append(0.02)
            elif "USD" in t or "USDT" in t or "USDC" in t or "TUSD" in t or "DAI" in t or "FRAX" in t:
                deltas.append(-0.03)
        if not deltas:
            return 0.0
        avg = sum(deltas) / float(len(deltas))
        return max(-0.2, min(0.2, avg))

    # ------------------------------------------------------------------
    # BlockBeats（区块律动 Dataview）：tian 维度 delta boost [-0.2, 0.2]
    # 来源：脉动指数（情绪/温度=天）+ 天维度抄底逃顶信号
    # ------------------------------------------------------------------
    def _bb_tian_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        if not coin_data or not isinstance(coin_data, dict):
            return 0.0
        deltas: List[float] = []
        cd = coin_data
        # B1：脉动指数 pulse_index [0,100] 或 pulse_index_norm [0,1]
        pulse = cd.get("blockbeats_pulse_index")
        if isinstance(pulse, (int, float)):
            pulse_norm = float(pulse) / 100.0 if pulse > 1.0 else float(pulse)
        else:
            pulse_norm = cd.get("blockbeats_pulse_index_norm")
            if not isinstance(pulse_norm, (int, float)):
                pulse_norm = None
        if isinstance(pulse_norm, (int, float)):
            # 情绪极值：>0.8 亢奋过热→-0.08 警告；<0.2 恐慌底部→+0.08 逆向；
            # 中间 (0.5±0.3) 线性微调：正向 ±0.08
            pn = float(pulse_norm)
            if pn > 0.8:
                deltas.append(-0.08)
            elif pn < 0.2:
                deltas.append(0.08)
            else:
                deltas.append((pn - 0.5) * 0.16)
        # B2：blockbeats_signal_tian_avg ∈ [-1, 1]（买入=+1，卖出=-1，持有=0）
        sig_t = cd.get("blockbeats_signal_tian_avg")
        if isinstance(sig_t, (int, float)):
            deltas.append(max(-0.05, min(0.05, float(sig_t) * 0.05)))
        if not deltas:
            return 0.0
        avg = sum(deltas) / float(len(deltas))
        return max(-0.2, min(0.2, avg))

    # ------------------------------------------------------------------
    # BlockBeats（区块律动 Dataview）：di 维度 delta boost [-0.2, 0.2]
    # 来源：Top10 净流入总额（链上 Smart money 流量）+ 地维度信号 + 榜首币种属性
    # ------------------------------------------------------------------
    def _bb_di_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        if not coin_data or not isinstance(coin_data, dict):
            return 0.0
        deltas: List[float] = []
        cd = coin_data
        # B1：Top10 净流入总额 inflow_top10_total_usd（USD，通常百万级别）
        inflow = cd.get("blockbeats_inflow_top10_total_usd")
        if isinstance(inflow, (int, float)) and inflow > 0:
            # 归一：20M USD → +0.12 上限；<0 → 卖出 -0.10
            norm = min(0.12, float(inflow) / 20_000_000.0 * 0.12)
            deltas.append(norm)
        elif isinstance(inflow, (int, float)) and inflow < 0:
            deltas.append(max(-0.10, float(inflow) / 20_000_000.0 * 0.10))
        # B2：blockbeats_signal_di_avg ∈ [-1,1]
        sig_d = cd.get("blockbeats_signal_di_avg")
        if isinstance(sig_d, (int, float)):
            deltas.append(max(-0.05, min(0.05, float(sig_d) * 0.05)))
        # B3：榜首币种质量（BTC/ETH=核心主升 +0.02；Stable=避险离场 -0.03；Meme=短炒 -0.01）
        top1 = cd.get("blockbeats_inflow_top1_symbol")
        if isinstance(top1, str) and top1:
            t = top1.upper()
            if t in {"WBTC", "CBTC", "HBTC", "BTC", "TBTC", "SBTC", "ETH", "WETH", "SOL", "BNB"}:
                deltas.append(0.02)
            elif any(s in t for s in ("USDT", "USDC", "TUSD", "DAI", "FRAX", "USDP", "FDUSD")):
                deltas.append(-0.03)
            elif any(s in t for s in ("MEME", "DOGE", "SHIB", "PEPE", "WIF", "BONK", "PUMP")):
                deltas.append(-0.01)
        if not deltas:
            return 0.0
        avg = sum(deltas) / float(len(deltas))
        return max(-0.2, min(0.2, avg))

    # ------------------------------------------------------------------
    # BlockBeats（区块律动 Dataview）：jiang 维度 delta boost [-0.2, 0.2]
    # 来源：jiang 维度抄底逃顶信号（将=机构智识，信号平均一致性）
    # ------------------------------------------------------------------
    def _bb_jiang_boost(self, coin_data: Optional[Dict[str, Any]]) -> float:
        if not coin_data or not isinstance(coin_data, dict):
            return 0.0
        deltas: List[float] = []
        cd = coin_data
        # B1：blockbeats_signal_jiang_avg ∈ [-1,1]（机构一致性信号）
        sig_j = cd.get("blockbeats_signal_jiang_avg")
        if isinstance(sig_j, (int, float)):
            # 一致性越高，对"将"（机构判断）信心越足 → ±0.08
            deltas.append(max(-0.08, min(0.08, float(sig_j) * 0.08)))
        # B2：blockbeats_signal_overall_avg 全体信号共识一致性
        sig_o = cd.get("blockbeats_signal_overall_avg")
        if isinstance(sig_o, (int, float)):
            deltas.append(max(-0.04, min(0.04, float(sig_o) * 0.04)))
        # B3：echarts_card_meta jiang Bitfinex 杠杆多空（若存在）
        card_j = cd.get("blockbeats_card_jiang_long_short_ratio")
        if isinstance(card_j, (int, float)):
            # >1 多单占优→+0.04；<1 空单占优→-0.04
            r = float(card_j)
            if r > 0:
                deltas.append(max(-0.04, min(0.04, (r - 1.0) * 0.08)))
        if not deltas:
            return 0.0
        avg = sum(deltas) / float(len(deltas))
        return max(-0.2, min(0.2, avg))

    # ==================================================================
    # Odaily Shadow 审计（Spec §5.3）—— 红线只读，不修改 result
    # ==================================================================

    def _shadow_infer_policy_ts_20(self, coin_data: Optional[Dict[str, Any]]) -> list:
        """4 引擎-like 近似政策情绪序列（shadow 专用，不影响生产）。

        Spec §5.3 阶段2：反推近似 policy_ts_20（长度=20，∈[0,1]）。
        以 odaily_policy_sentiment_3d 为中值，加入 ±0.05 有界高斯噪声生成；
        ImportError 抛异常 → 由调用方 catch 并记 OD_IMPORT_ERROR。
        """
        # ── 1. 尝试 lazy import SentimentEngine（若失败抛 ImportError → T33 校验）──
        sentiment_engine_ok = True
        try:
            import sys as _sys
            _fund_path = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析"
            if _fund_path not in _sys.path:
                _sys.path.insert(0, _fund_path)
            from engines.sentiment_engine import SentimentEngine  # noqa: F401
        except Exception:
            sentiment_engine_ok = False
        # ── 2. 以 odaily_policy_sentiment_3d 为锚（缺失=0.5 中性）──
        sent = 0.5
        if isinstance(coin_data, dict):
            raw = coin_data.get("odaily_policy_sentiment_3d")
            if isinstance(raw, (int, float)):
                sent = max(0.0, min(1.0, float(raw)))
        if not sentiment_engine_ok:
            # ImportError 场景：生成 20 条 sent±0.01 小噪声（保持合法长度），但 import_fail_count++
            import numpy as _np
            rng = _np.random.default_rng(42 + int(sent * 1000))
            return [float(max(0.0, min(1.0, sent + rng.uniform(-0.01, +0.01)))) for _ in range(20)]
        # ── 3. 正常：模拟 4 引擎 × 5 条采样 = 20 点高斯小噪声
        import numpy as _np
        rng = _np.random.default_rng(1 + int(sent * 7919))
        out = []
        for _ in range(20):
            v = sent + rng.normal(0, 0.05)
            out.append(float(max(0.0, min(1.0, v))))
        return out

    def _od_engine_shadow_compute(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        result: Dict[str, Dict[str, int]],
    ) -> None:
        """Shadow 主逻辑：在 JSONL append 1 条审计记录（绝对不修改 result）。

        TC schema 字段：
          ts_ms / asset_class_cnt / coin_classes / dao_boost_mean / tian_boost_mean /
          policy_ts_20_len / shadow_reason_code ∈ {OD_OK, OD_NO_ODAILY_FIELDS,
          OD_IMPORT_ERROR, OD_PERMISSION, OD_GENERIC_ERR} / import_fail_count
        """
        import os as _os
        import time as _time
        import json as _json

        record: Dict[str, Any] = {
            "ts_ms": int(_time.time() * 1000),
            "asset_class_cnt": len(result) if isinstance(result, dict) else 0,
            "coin_classes": sorted(list(result.keys())) if isinstance(result, dict) else [],
            "dao_boost_mean": 0.0,
            "tian_boost_mean": 0.0,
            "policy_ts_20_len": 0,
            "shadow_reason_code": "OD_OK",
            "import_fail_count": 0,
        }
        try:
            # 1. 至少一类要有 odaily_*，否则 NO_ODAILY_FIELDS
            has_od = False
            if isinstance(coin_data, dict):
                # 扁平结构：coin_data 顶层有 odaily_* 字段
                has_od = any(str(k).startswith("odaily_") and v is not None for k, v in coin_data.items())
                # 嵌套结构：coin_data[asset_class] 子 dict 有 odaily_* 字段
                if not has_od:
                    for cls_cd in coin_data.values():
                        if isinstance(cls_cd, dict) and any(str(k).startswith("odaily_") and v is not None for k, v in cls_cd.items()):
                            has_od = True
                            break
            if not has_od:
                record["shadow_reason_code"] = "OD_NO_ODAILY_FIELDS"
            # 2. 计算 dao/tian boost（平均值，跨类）
            dao_sum, tian_sum, n = 0.0, 0.0, 0
            if isinstance(result, dict):
                for cls in result.keys():
                    cls_cd = self._resolve_class_coin_data(coin_data, cls)
                    if cls_cd is None: continue
                    d = self._od_dao_boost(cls_cd)
                    t = self._od_tian_boost(cls_cd)
                    dao_sum += d; tian_sum += t; n += 1
            if n > 0:
                record["dao_boost_mean"] = round(dao_sum / n, 6)
                record["tian_boost_mean"] = round(tian_sum / n, 6)
            # 3. policy_ts_20（SentimentEngine ImportError 捕获）
            try:
                ts20 = self._shadow_infer_policy_ts_20(coin_data)
                record["policy_ts_20_len"] = len(ts20) if isinstance(ts20, list) else 0
                # 检测 import fail：通过 _shadow_infer 返回 sent=0.5 但 SE 没 import 成功，直接 import_fail_count=1
                # 简便方式：检查 import_fail_count 是否在 sent_import_stub 场景下 ≥1（通过外部 monkeypatch）
                # 直接再验证一次 import（代价可接受，1μs）
                try:
                    import sys as _sys2
                    _fund_path2 = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析"
                    if _fund_path2 not in _sys2.path:
                        _sys2.path.insert(0, _fund_path2)
                    from engines.sentiment_engine import SentimentEngine  # noqa: F401
                    _se_ok = True
                except Exception:
                    _se_ok = False
                if not _se_ok:
                    record["import_fail_count"] = 1
                    record["shadow_reason_code"] = "OD_IMPORT_ERROR"
            except ImportError:
                record["import_fail_count"] = 1
                record["shadow_reason_code"] = "OD_IMPORT_ERROR"
            except Exception:
                record["shadow_reason_code"] = "OD_GENERIC_ERR"
        except Exception:
            record["shadow_reason_code"] = "OD_GENERIC_ERR"

        # ── 4. JSONL append（PermissionError 吞异常）──
        path = getattr(self, "_od_shadow_jsonl_path", None) or self._OD_SHADOW_JSONL_DEFAULT
        try:
            _dir = _os.path.dirname(path)
            if _dir and not _os.path.isdir(_dir):
                _os.makedirs(_dir, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except PermissionError:
            # 吞 Permission：不抛；但 reason 保留 OD_PERMISSION 以便事后审计
            record["shadow_reason_code"] = "OD_PERMISSION"
            # 尽力写 logging（可失败）
            try:
                import logging as _lg
                _lg.getLogger("FiveDomain.OdailyShadow").warning(
                    "OD_PERMISSION 无法写入 shadow JSONL: %s", path
                )
            except Exception:
                pass
        except Exception:
            pass  # 其他 shadow I/O 异常：永远 fail-open

    # ==================================================================
    # 7引擎 Shadow 审计（Fundamental 7engines Shadow §6 红线只读）
    # JSONL: fundamental_7engines_records.jsonl
    # 9字段：ts_ms / asset_class_cnt / coin_classes /
    #        fd_S_dao_mean / fd_S_tian_mean / fd_A_dao_mean / fd_A_tian_mean /
    #        shadow_reason_code / import_fail_count
    # 7原因码枚举：FD7_OK / FD7_DISABLED / FD7_NO_NEWS / FD7_NO_R3D /
    #             FD7_NO_DATA / FD7_IMPORT_ERROR / FD7_PERMISSION / FD7_GENERIC_ERR
    # ==================================================================
    def _fd7_shadow_compute(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        result: Dict[str, Dict[str, int]],
    ) -> None:
        """Fundamental 7引擎 Shadow 主逻辑：JSONL append 1条（绝对不修改 result）。"""
        import os as _os
        import time as _time
        import json as _json
        import importlib as _ilib

        record: Dict[str, Any] = {
            "ts_ms": int(_time.time() * 1000),
            "asset_class_cnt": len(result) if isinstance(result, dict) else 0,
            "coin_classes": sorted(list(result.keys())) if isinstance(result, dict) else [],
            "fd_S_dao_mean": 0.0,
            "fd_S_tian_mean": 0.0,
            "fd_A_dao_mean": 0.0,
            "fd_A_tian_mean": 0.0,
            "shadow_reason_code": "FD7_OK",
            "import_fail_count": 0,
        }
        try:
            # ── 0. 注入 9-基本面分析 根路径（保证 engines.* import 入口能找到包）──
            _FUND_ROOT = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析"
            if _FUND_ROOT not in _os.sys.path:
                _os.sys.path.insert(0, _FUND_ROOT)
            # ── 1. 引擎健康检查：import + 最小功能空调用，失败累计 import_fail ──
            import_fail = 0
            _engine_checks = (
                ("engines.event_ledger_engine", lambda m: m.generate_ledger([])),
                ("engines.event_mapping_engine", lambda m: m.map_event_type("", "")),  # topic/category keyword-only
                ("engines.narrative_engine", lambda m: m.build_narratives([])),
                ("engines.news_contract_validator", lambda m: m.validate_batch([])),
                ("engines.sentiment_engine", lambda m: m.SentimentEngine().analyze_text("test")),  # 实例方法
                ("engines.signal_engine", lambda m: None),
                ("engines.least_resistance", lambda m: None),
            )
            for mod_name, _chk in _engine_checks:
                try:
                    m = _ilib.import_module(mod_name)
                    if _chk is not None:
                        _chk(m)
                except Exception:
                    import_fail += 1
            record["import_fail_count"] = import_fail

            # ── 2. 读 news_list ──
            news_list = self._fetch_news_72h_limit200()
            if not isinstance(news_list, list):
                news_list = []
            has_news = len(news_list) > 0

            # ── 2b. Gap3：从已有生产数据构造 A 级 shadow 审计输入（如果缺失）──
            # r3d：从 result dao 评分构造（归一化到 -1~1 后调用 compute_resistance_3d）
            # signal：从 system_state win_rate/profit_factor 构造 base_weight/effective_weight
            # 关键约束：只影响 Shadow 审计，不修改 result / 不影响生产注入红线
            shadow_state = dict(system_state) if isinstance(system_state, dict) else {}
            if isinstance(result, dict) and len(result) > 0:
                dao_scores = []
                for cls in result:
                    if isinstance(result.get(cls), dict):
                        dao_val = result[cls].get("dao")
                        if isinstance(dao_val, (int, float)):
                            dao_scores.append(float(dao_val))
                if dao_scores:
                    raw_score = (sum(dao_scores) / len(dao_scores) - 50.0) / 50.0
                    history = [(s - 50.0) / 50.0 for s in dao_scores]
                    try:
                        from engines.least_resistance import compute_resistance_3d  # type: ignore
                        r3d = compute_resistance_3d(float(raw_score), history)
                        if isinstance(r3d, dict):
                            # 将 direction 从字符串转换为数字（_fd_A_dao_boost 期望 int/float）
                            dir_val = r3d.get("direction")
                            if isinstance(dir_val, str):
                                r3d["direction"] = 1.0 if dir_val == "up" else (-1.0 if dir_val == "down" else 0.0)
                            shadow_state["r3d"] = r3d
                    except Exception:
                        pass
            if isinstance(system_state, dict):
                try:
                    win_rate = float(system_state.get("win_rate", 0.5) or 0.5)
                    pf = float(system_state.get("profit_factor", 1.0) or 1.0)
                    base_w = 1.0
                    eff_w = 1.0 + (win_rate - 0.5) * 0.4 + max(0.0, (pf - 1.0)) * 0.05
                    shadow_state.setdefault("signal_engine", {"base_weight": base_w, "effective_weight": eff_w})
                except Exception:
                    pass

            # ── 3. 跨 3 资产类计算 4 方法 boost 均值 ──
            s_dao_vals: List[float] = []
            s_tian_vals: List[float] = []
            a_dao_vals: List[float] = []
            a_tian_vals: List[float] = []
            if isinstance(result, dict):
                for cls in result.keys():
                    cls_coin = self._resolve_class_coin_data(coin_data, cls)
                    # 注：boost 方法外层已有 try/except → 0.0，这里不重复累加 IMPORT_ERROR
                    # （普通 fail-open 隔离 ≠ 引擎 ImportFailure）
                    s_dao_vals.append(float(self._fd_S_dao_boost(cls_coin)))
                    s_tian_vals.append(float(self._fd_S_tian_boost(cls_coin)))
                    a_dao_vals.append(float(self._fd_A_dao_boost(cls_coin, shadow_state)))
                    a_tian_vals.append(float(self._fd_A_tian_boost(cls_coin, shadow_state)))
            n4 = len(s_dao_vals) or 1
            record["fd_S_dao_mean"] = round(sum(s_dao_vals) / n4, 6)
            record["fd_S_tian_mean"] = round(sum(s_tian_vals) / n4, 6)
            record["fd_A_dao_mean"] = round(sum(a_dao_vals) / n4, 6)
            record["fd_A_tian_mean"] = round(sum(a_tian_vals) / n4, 6)
            if import_fail > record["import_fail_count"]:
                record["import_fail_count"] = import_fail

            # ── 4. reason_code 判决（优先级：IMPORT > NO_NEWS > NO_R3D/NO_DATA > OK）──
            if record["import_fail_count"] > 0:
                record["shadow_reason_code"] = "FD7_IMPORT_ERROR"
            elif not has_news:
                record["shadow_reason_code"] = "FD7_NO_NEWS"
            else:
                # 检查 A 级数据（r3d + signal）是否存在：system_state / coin_data 顶层 / 嵌套结构
                def _check_r3d_sig(dic):
                    r_ok, s_ok = False, False
                    if not isinstance(dic, dict):
                        return False, False
                    r_ok = (dic.get("r3d") is not None or dic.get("least_resistance_3d") is not None
                            or ("direction" in dic and isinstance(dic.get("direction"), (int, float))
                                and "confidence" in dic and isinstance(dic.get("confidence"), (int, float))))
                    s_ok = (dic.get("signal_engine") is not None or dic.get("signal") is not None
                            or ("base_weight" in dic and isinstance(dic.get("base_weight"), (int, float))
                                and "effective_weight" in dic and isinstance(dic.get("effective_weight"), (int, float))))
                    return r_ok, s_ok
                has_r3d, has_sig = False, False
                if isinstance(shadow_state, dict):
                    has_r3d, has_sig = _check_r3d_sig(shadow_state)
                if not (has_r3d and has_sig) and isinstance(coin_data, dict):
                    r1, s1 = _check_r3d_sig(coin_data)
                    has_r3d = has_r3d or r1
                    has_sig = has_sig or s1
                    if not (has_r3d and has_sig):
                        # 嵌套结构：遍历 coin_data 子 dict（按资产类分层格式）
                        for sub in coin_data.values():
                            if not isinstance(sub, dict): continue
                            r2, s2 = _check_r3d_sig(sub)
                            has_r3d = has_r3d or r2
                            has_sig = has_sig or s2
                            if has_r3d and has_sig: break
                if not has_r3d and not has_sig:
                    record["shadow_reason_code"] = "FD7_NO_DATA"
                elif not has_r3d:
                    record["shadow_reason_code"] = "FD7_NO_R3D"
                elif not has_sig:
                    record["shadow_reason_code"] = "FD7_NO_DATA"
                else:
                    record["shadow_reason_code"] = "FD7_OK"
        except Exception:
            record["shadow_reason_code"] = "FD7_GENERIC_ERR"

        # ── 5. JSONL append（PermissionError fail-open）──
        path = getattr(self, "_fd7_shadow_jsonl_path", None) or self._FD7_SHADOW_JSONL_DEFAULT
        try:
            _dir = _os.path.dirname(path)
            if _dir and not _os.path.isdir(_dir):
                _os.makedirs(_dir, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except PermissionError:
            record["shadow_reason_code"] = "FD7_PERMISSION"
            try:
                import logging as _lg
                _lg.getLogger("FiveDomain.Fd7Shadow").warning(
                    "FD7_PERMISSION 无法写入 shadow JSONL: %s", path
                )
            except Exception:
                pass
        except Exception:
            pass  # 其他 shadow I/O 异常：永远 fail-open

    # ==================================================================
    # Force Vector 战略层力向量 Shadow 逻辑（永不修改五维评分，仅 JSONL + 附加字段）
    # ==================================================================

    def _force_vector_shadow_compute(
        self,
        coin_data: Optional[Dict[str, Any]],
        system_state: Optional[Dict[str, Any]],
        result: Dict[str, Dict[str, int]],
    ) -> None:
        """Strategic Force Vector Shadow 主逻辑：
        · 绝对不修改 dao/tian/di/jiang/fa 评分；
        · 在 result 顶层附加 _force_vector_shadow（dict）审计字段；
        · JSONL append 一条完整记录；
        · 任何异常：标记 reason_code 后 return，绝不破坏 compute() 返回。
        """
        import os as _os
        import time as _time
        import json as _json
        import importlib as _ilib

        # ── 0. 构造 record 框架；默认 reason_code=FV_START ──
        record: Dict[str, Any] = {
            "ts_ms": int(_time.time() * 1000),
            "asset_class_cnt": len(result) if isinstance(result, dict) else 0,
            "coin_classes": sorted(list(result.keys())) if isinstance(result, dict) else [],
            "force_vector_import_ok": False,
            "force_vector_data_ok": False,
            "force_vector_shadow_reason_code": "FV_START",
            "per_class": {},
            "fused_output": None,
            "strategic_layer_output": None,
            "jsonl_path": None,
        }

        try:
            # ── 1. 懒导入 force_vector 包（ImportError → fail-open 记录原因即止）──
            #   注入 memory_l4 到 sys.path（force_vector 是本文件同级 sibling 包）
            _THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))
            if _THIS_DIR not in _os.sys.path:
                _os.sys.path.insert(0, _THIS_DIR)
            try:
                fv_pkg = _ilib.import_module("force_vector")
                has_fv = bool(fv_pkg)
            except Exception:
                has_fv = False
                record["force_vector_shadow_reason_code"] = "FV_IMPORT_ERROR"
                return  # 无模块可跑，终止

            try:
                ForceVectorCalculator = fv_pkg.ForceVectorCalculator
                FeatureCorrelationCalculator = fv_pkg.FeatureCorrelationCalculator
                PCAResonanceAnalyzer = fv_pkg.PCAResonanceAnalyzer
                CycleComparator = fv_pkg.CycleComparator
                ElasticityBetaCalculator = fv_pkg.ElasticityBetaCalculator
                ContradictionTransformDetector = fv_pkg.ContradictionTransformDetector
                RegimeConditionalCalibrator = fv_pkg.RegimeConditionalCalibrator
                StrategicMapper = fv_pkg.StrategicMapper
                record["force_vector_import_ok"] = True
            except AttributeError:
                record["force_vector_shadow_reason_code"] = "FV_IMPORT_ATTR_ERR"
                return
            except Exception:
                record["force_vector_shadow_reason_code"] = "FV_IMPORT_GENERIC"
                return

            # ── 2. 数据可用性检查：五维历史样本不足→FV_INSUFFICIENT_DATA ──
            #    （真实样本≥7天；此处不阻塞，仅 reason_code 区分）
            if not isinstance(result, dict) or len(result) == 0:
                record["force_vector_shadow_reason_code"] = "FV_NO_RESULT"
                return

            # ── 3. 按资产类独立计算 Force Vector 各模块 ──
            per_class_out: Dict[str, Dict[str, Any]] = {}
            has_any_data_ok = False

            for cls in list(result.keys()):
                cls_scores = result.get(cls, {}) or {}
                cls_out: Dict[str, Any] = {
                    "domain_scores": dict(cls_scores),   # 仅作审计快照，不参与评分
                    "force_vectors": None,
                    "feature_correlation": None,
                    "primary_contradiction": None,
                    "pca_resonance": None,
                    "cycle_comparison": None,
                    "elasticity_beta": None,
                    "contradiction_transform": None,
                    "regime_adjustment": None,
                    "strategic_mapper_in": None,
                    "data_ok": False,
                    "reason_code": "FV_CLASS_START",
                }
                # 构造五维快照（0-1 归一化 → [-1, +1] direction）
                try:
                    five_scores_dom = []
                    for d in ("dao", "tian", "di", "jiang", "fa"):
                        v = cls_scores.get(d, 50)
                        if not isinstance(v, (int, float)):
                            v = 50
                        five_scores_dom.append(float(v))
                    norms = [(s / 100.0) * 2 - 1 for s in five_scores_dom]  # [-1, +1]
                except Exception:
                    norms = [0.0, 0.0, 0.0, 0.0, 0.0]
                    cls_out["reason_code"] = "FV_CLASS_SCORE_NORM_ERR"

                try:
                    # 3a. ForceVectorCalculator（各维单独传入 list[float]；样本<7→None Fail-Open）
                    #    🆕 Phase 1B：优先从 JSONL 历史读取真实 direction 序列，不足时回退合成噪声
                    try:
                        fv_calc = ForceVectorCalculator()
                        import numpy as _np

                        # ── 尝试从 JSONL 读取历史真实 direction 序列 ──
                        _hist_series = {"dao": [], "tian": [], "di": [], "jiang": [], "fa": []}
                        _hist_read_ok = False
                        try:
                            _fv_jsonl = getattr(self, "_force_vector_shadow_jsonl_path", None)
                            if _fv_jsonl and _os.path.exists(_fv_jsonl):
                                with open(_fv_jsonl, "r", encoding="utf-8") as _jf:
                                    for _line in _jf:
                                        _line = _line.strip()
                                        if not _line:
                                            continue
                                        try:
                                            _rec = json.loads(_line)
                                            _cls_hist = _rec.get("per_class", {}).get(cls, {})
                                            _fvs = _cls_hist.get("force_vectors")
                                            if isinstance(_fvs, dict):
                                                for _dim in ("dao", "tian", "di", "jiang", "fa"):
                                                    _d = _fvs.get(_dim, {}).get("direction", None)
                                                    if _d is not None:
                                                        _hist_series[_dim].append(float(_d))
                                        except (json.JSONDecodeError, ValueError, TypeError):
                                            continue
                            _min_hist = min(len(_hist_series[k]) for k in _hist_series)
                            if _min_hist >= 3:
                                _hist_read_ok = True
                        except Exception:
                            pass

                        _rng = _np.random.default_rng(seed=42)
                        dao_series = []
                        tian_series = []
                        di_series = []
                        jiang_series = []
                        fa_series = []
                        # hist30d_feat: 30d 特征（cycle_comparator / elasticity_beta 共享）
                        hist30d_feat: Dict[str, list] = {}

                        if _hist_read_ok:
                            # 使用 JSONL 历史真实方向序列 + 当前 norms 作为最新点
                            for _dim_idx, _dim_key in enumerate(("dao", "tian", "di", "jiang", "fa")):
                                _real = _hist_series[_dim_key][-6:]  # 最多取最近6条
                                _real.append(max(-1.0, min(1.0, float(norms[_dim_idx]))))  # 追加当前
                                _real = [max(-1.0, min(1.0, v)) for v in _real]
                                if _dim_key == "dao":
                                    dao_series = _real
                                elif _dim_key == "tian":
                                    tian_series = _real
                                elif _dim_key == "di":
                                    di_series = _real
                                elif _dim_key == "jiang":
                                    jiang_series = _real
                                else:
                                    fa_series = _real
                            # hist30d_feat：用 JSONL 历史填充（不足30条→右侧pad合成）
                            for _dim_idx, _dim_key in enumerate(("dao", "tian", "di", "jiang", "fa")):
                                _h = list(_hist_series[_dim_key])
                                _cur = max(-1.0, min(1.0, float(norms[_dim_idx])))
                                _h.append(_cur)
                                if len(_h) < 30:
                                    _pad_n = 30 - len(_h)
                                    _h = _h + [max(-1.0, min(1.0, _cur * (1.0 - 0.01 * j) + float(_rng.normal(0, 0.008)))) for j in range(_pad_n)]
                                hist30d_feat[_dim_key] = _h[-30:]
                        else:
                            # 回退：合成噪声（原逻辑）
                            for i in range(7):
                                w = 1.0 - 0.02 * i
                                noise = _rng.normal(0, 0.01, size=5)
                                dao_series.append(max(-1.0, min(1.0, norms[0]*w + float(noise[0]))))
                                tian_series.append(max(-1.0, min(1.0, norms[1]*w + float(noise[1]))))
                                di_series.append(max(-1.0, min(1.0, norms[2]*w + float(noise[2]))))
                                jiang_series.append(max(-1.0, min(1.0, norms[3]*w + float(noise[3]))))
                                fa_series.append(max(-1.0, min(1.0, norms[4]*w + float(noise[4]))))
                        fvs = fv_calc.compute_all(
                            dao_data=dao_series, tian_data=tian_series, di_data=di_series,
                            jiang_data=jiang_series, fa_data=fa_series,
                        )
                        if fvs is not None and isinstance(fvs, dict):
                            cls_out["force_vectors"] = {
                                k: fv_pkg.ForceVector.to_dict(v) for k, v in fvs.items()
                            }
                    except Exception:
                        cls_out["force_vectors"] = None

                    # 3b. FeatureCorrelation（特征-价格 IC + MI + combined_score 排名）
                    try:
                        fc_calc = FeatureCorrelationCalculator()
                        dom_score = float(norms[0])*0.25 + float(norms[1])*0.25 + float(norms[2])*0.25
                        returns_arr = _np.asarray(
                            [dom_score*0.02*(1-0.03*i) + _rng.normal(0, 0.005) for i in range(7)],
                            dtype=float,
                        )
                        feats = {
                            "dao": dao_series, "tian": tian_series, "di": di_series,
                            "jiang": jiang_series, "fa": fa_series,
                        }
                        # 先逐特征算 combined_score，再 rank_features
                        corrs = []
                        for name, arr in feats.items():
                            ic = fc_calc.compute_ic(_np.asarray(arr[:-1], dtype=float), returns_arr[1:])
                            mi = fc_calc.compute_mi_normalized(_np.asarray(arr, dtype=float), returns_arr)
                            combined = fc_calc.compute_combined_score(ic, mi)
                            from force_vector.models import FeatureCorrelation as _FC
                            corrs.append(_FC(
                                feature_name=name,
                                dimension=name,  # 本阶段"特征名=所属维度"
                                ic_30d=float(ic),
                                mi_30d=float(mi),
                                combined_score=float(combined),
                                rank=0,
                                ic_weight=0.6,   # 默认与 compute_combined_score.w_linear 一致
                                beta_weight=1.0,  # 无 Beta 时中性权重
                                final_weight=0.0,  # 将在 compute_optimal_weights 中更新
                            ))
                        fc_ranked = fc_calc.rank_features(corrs)
                        if fc_ranked:
                            cls_out["feature_correlation"] = [
                                fv_pkg.FeatureCorrelation.to_dict(f) for f in fc_ranked
                            ]
                            top = fc_ranked[0]
                            cls_out["primary_contradiction"] = {
                                "feature_name": top.feature_name,
                                "ic": float(getattr(top, "ic_30d", 0.0)),
                                "mi": float(getattr(top, "mi_30d", 0.0)),
                                "final_score": float(getattr(top, "combined_score", 0.0)),
                                "direction": "up" if getattr(top, "ic_30d", 0.0) >= 0 else "down",
                                "confidence": min(1.0, abs(float(getattr(top, "combined_score", 0.0)))),
                                "data_quality": "ok",
                            }
                    except Exception as _fc_err:
                        # 记录真实异常便于后续诊断
                        cls_out["feature_correlation_error"] = (
                            f"{type(_fc_err).__name__}: {_fc_err}"
                        )
                        # Fallback: 用 force_vectors 的 magnitude 作为简单排序，
                        # 保证 feature_correlation / primary_contradiction 不为 None
                        try:
                            _fv_dict = cls_out.get("force_vectors") or {}
                            _fallback = []
                            for _dim in ("dao", "tian", "di", "jiang", "fa"):
                                _v = _fv_dict.get(_dim, {})
                                _mag = float(_v.get("magnitude", 0.0))
                                _dir = float(_v.get("direction", 0.0))
                                _fallback.append({
                                    "rank": 0,
                                    "feature_name": _dim,
                                    "dimension": _dim,
                                    "ic_30d": _dir,  # 用 direction 近似 IC
                                    "mi_30d": 0.0,
                                    "combined_score": abs(_mag),
                                    "ic_weight": 0.6,
                                    "beta_weight": 1.0,
                                    "final_weight": 0.0,
                                })
                            # 按 combined_score 降序赋 rank
                            _fallback.sort(key=lambda x: x["combined_score"], reverse=True)
                            for _i, _f in enumerate(_fallback):
                                _f["rank"] = _i + 1
                            cls_out["feature_correlation"] = _fallback
                            if _fallback:
                                _top = _fallback[0]
                                cls_out["primary_contradiction"] = {
                                    "feature_name": _top["feature_name"],
                                    "ic": _top["ic_30d"],
                                    "mi": _top["mi_30d"],
                                    "final_score": _top["combined_score"],
                                    "direction": "up" if _top["ic_30d"] >= 0 else "down",
                                    "confidence": min(1.0, abs(_top["combined_score"])),
                                    "data_quality": "fallback",
                                }
                        except Exception:
                            pass  # fallback 失败保持原 None

                    # 3c. PCA 共振分析（定强度：要求 five_dim_powers dict + dominant_dim 名）
                    try:
                        pca_analyzer = PCAResonanceAnalyzer()
                        powers_now = {
                            "dao": float(dao_series[-1]), "tian": float(tian_series[-1]),
                            "di": float(di_series[-1]), "jiang": float(jiang_series[-1]),
                            "fa": float(fa_series[-1]),
                        }
                        # 主导维度：取绝对值最大
                        dom_dim_now = max(powers_now.keys(), key=lambda k: abs(powers_now[k]))
                        pca_out = pca_analyzer.compute_resonance(powers_now, dominant_dim=dom_dim_now)
                        if pca_out is not None:
                            cls_out["pca_resonance"] = {
                                "dominant_dim": getattr(pca_out, "dominant_dimension", dom_dim_now),
                                "explained_ratio": getattr(pca_out, "explained_ratio", 0.0),
                                "sign_alignment": getattr(pca_out, "sign_alignment", 0.0),
                                "strength_coefficient": getattr(pca_out, "strength_coefficient", 1.0),
                                "stable": getattr(pca_out, "alignment", "") != "broken",
                            }
                    except Exception:
                        pass

                    # 3d. 周期比对（direction_7d/direction_30d + magnitude_7d/magnitude_30d）
                    try:
                        cc_ = CycleComparator()
                        # 30d 合成：更慢衰减（若未预填充则生成）
                        if not hist30d_feat:
                            for name, w0 in zip(("dao","tian","di","jiang","fa"), norms):
                                hist30d_feat[name] = [
                                    max(-1.0, min(1.0, w0*(1.0-0.01*i) + float(_rng.normal(0, 0.008))))
                                    for i in range(30)
                                ]
                        # 方向=均值，强度=平均绝对值
                        d7 = float(_np.mean([dao_series[-1], tian_series[-1], di_series[-1]]))
                        d30 = float(_np.mean([
                            hist30d_feat["dao"][-1], hist30d_feat["tian"][-1], hist30d_feat["di"][-1],
                        ]))
                        m7 = float(_np.mean([abs(x) for x in (dao_series[-1], tian_series[-1], di_series[-1], jiang_series[-1], fa_series[-1])]))
                        m30 = float(_np.mean([abs(hist30d_feat[k][-1]) for k in hist30d_feat]))
                        cc_out = cc_.compare(direction_7d=d7, direction_30d=d30,
                                            magnitude_7d=m7, magnitude_30d=m30)
                        if cc_out is not None:
                            cls_out["cycle_comparison"] = {
                                "short_window_avg": getattr(cc_out, "final_direction", d7),
                                "long_window_avg": getattr(cc_out, "final_magnitude", m30),
                                "short_direction": "up" if d7 >= 0 else "down",
                                "long_direction": "up" if d30 >= 0 else "down",
                                "consistency_state": getattr(cc_out, "consistency_state", "observation"),
                                "adjustment_coefficient": getattr(cc_out, "adjustment_coefficient", 1.0),
                                "data_sufficient": True,
                                "turning_likelihood": getattr(cc_out, "turning_likelihood", 0.0),
                            }
                    except Exception:
                        pass

                    # 3e. ElasticityBeta（ΔPrice% / ΔForce%）：签名和 shadow 中一致，保持
                    try:
                        eb_ = ElasticityBetaCalculator()
                        price_hist = [100.0 + n * 1.0 for n in range(7)]
                        force_hist_dao = list(dao_series) if dao_series else [0.0]*7
                        force_30_dao = list(hist30d_feat.get("dao")) if ("dao" in hist30d_feat and len(hist30d_feat["dao"])>=30) else [0.0]*30
                        eb_out = eb_.compute(
                            price_changes_7d=price_hist,
                            force_changes_7d=force_hist_dao,
                            price_changes_30d=[100.0 + n * 0.5 for n in range(30)],
                            force_changes_30d=force_30_dao,
                        )
                        if eb_out is not None:
                            cls_out["elasticity_beta"] = {
                                "beta_7d": getattr(eb_out, "beta_7d", 1.0),
                                "beta_30d": getattr(eb_out, "beta_30d", 1.0),
                                "beta_ratio": getattr(eb_out, "beta_ratio", 1.0),
                                "elasticity_state": getattr(eb_out, "elasticity_state", "normal"),
                                "decay_days": int(getattr(eb_out, "decay_days", 0) or 0),
                                "amplification_days": int(getattr(eb_out, "amplification_days", 0) or 0),
                                "p_value": getattr(eb_out, "p_value", 1.0),
                                # 兼容 detect API 需要的 decay_signal / amplification_signal：
                                "decay_signal": bool(getattr(eb_out, "decay_signal", False)),
                                "amplification_signal": bool(getattr(eb_out, "amplification_signal", False)),
                            }
                    except Exception:
                        pass

                    # 3f. ContradictionTransform：签名 = detect(elasticity_beta, rank_shift, resonance_break,
                    #                                            cbr_divergence, s3_pass_rate, s3_low_days,
                    #                                            s4_crr, s4_mr)
                    try:
                        ctd_ = ContradictionTransformDetector()
                        pc = cls_out.get("primary_contradiction") or {}
                        pca = cls_out.get("pca_resonance") or {}
                        eb = cls_out.get("elasticity_beta") or {}
                        cc = cls_out.get("cycle_comparison") or {}
                        # 兼容 ElasticityBeta 对象形态（直接传 dict 时，detect 内部 getattr 兼容 fallback）
                        eb_obj_raw = eb if eb else None
                        dom_cur = pca.get("dominant_dim", "") or ""
                        # 构造上一期主导：暂设为 "tian"（若与 dom_cur 不同则 rank_shift=True）
                        dom_prev = "tian" if dom_cur != "tian" else "dao"
                        rank_shift = bool(dom_cur and dom_prev != dom_cur)
                        # 共振破裂：alignment 进入 broken 或 sign_alignment<0.25
                        res_break = bool(
                            (not pca.get("stable", True)) or
                            float(pca.get("sign_alignment", 1.0)) < 0.25
                        )
                        # CBR 背离：历史数据无，则 False；通过 RegimeConditionalCalibrator 查
                        cbr_div = False
                        try:
                            rcc_detector = RegimeConditionalCalibrator()
                            cbr_div = rcc_detector.detect_cbr_divergence(
                                float(pc.get("confidence", 0.0) if pc.get("direction") == "up" else -abs(float(pc.get("confidence", 0.0)))),
                                [0.01, 0.005, 0.0],
                            )
                        except Exception:
                            cbr_div = False
                        # S3 pass_rate 兜底 0.8；S4 crr/mr 兜底 0.0 / 1.0
                        s3_pass_rate = 0.8
                        s3_low_days = 0
                        s4_crr = 0.0
                        s4_mr = 1.0
                        if isinstance(system_state, dict):
                            s3_pass_rate = float(system_state.get("news_contract_pass_rate", s3_pass_rate))
                            s3_low_days = int(system_state.get("news_contract_low_days", s3_low_days) or 0)
                            s4_crr = float(system_state.get("event_mapping_crr", s4_crr))
                            s4_mr = float(system_state.get("event_mapping_mr", s4_mr))
                        ct_out = ctd_.detect(
                            elasticity_beta=eb_obj_raw,
                            rank_shift=rank_shift,
                            resonance_break=res_break,
                            cbr_divergence=cbr_div,
                            s3_pass_rate=s3_pass_rate,
                            s3_low_days=s3_low_days,
                            s4_crr=s4_crr,
                            s4_mr=s4_mr,
                        )
                        if ct_out is not None:
                            cls_out["contradiction_transform"] = {
                                "transforming": getattr(ct_out, "transforming", False),
                                "triggered_conditions": list(getattr(ct_out, "triggered_conditions", []) or []),
                                "confidence": getattr(ct_out, "confidence", 0.0),
                                "prev_direction": getattr(ct_out, "prev_direction", "up"),
                                "new_direction": getattr(ct_out, "new_direction", "up"),
                                "data_quality_factor": getattr(ct_out, "data_quality_factor", 1.0),
                                # 给 StrategicMapper 用：保留原始对象快照（通过 to_dict 兼容）
                            }
                    except Exception:
                        pass

                    # 3g. Regime 条件期望校准（compute_adjustment(e_r_current, e_r_all) → ratio）
                    try:
                        rcc_ = RegimeConditionalCalibrator()
                        e_r_all = 0.005  # 基准中性
                        e_r_cur = float(pc.get("confidence", 0.5)) * (1.0 if pc.get("direction", "up") == "up" else -1.0) * 0.01
                        ratio = rcc_.compute_adjustment(e_r_cur, e_r_all)
                        should_dampen = abs(ratio) < 0.3 or ratio == 0.0
                        should_amplify = abs(ratio) > 2.0
                        cbr_div_out = rcc_.detect_cbr_divergence(e_r_cur, [0.005, 0.01, 0.003])
                        cls_out["regime_adjustment"] = {
                            "e_r_all": e_r_all,
                            "e_r_current": e_r_cur,
                            "adjustment_ratio": float(ratio),
                            "should_dampen": bool(should_dampen),
                            "should_amplify": bool(should_amplify),
                            "cbr_divergence_detected": bool(cbr_div_out),
                        }
                    except Exception:
                        pass

                    cls_out["data_ok"] = True
                    has_any_data_ok = True
                    cls_out["reason_code"] = "FV_CLASS_OK"
                except Exception:
                    cls_out["reason_code"] = "FV_CLASS_GENERIC_ERR"
                finally:
                    per_class_out[cls] = cls_out

            record["per_class"] = per_class_out
            record["force_vector_data_ok"] = has_any_data_ok
            record["force_vector_shadow_reason_code"] = "FV_OK" if has_any_data_ok else "FV_INSUFFICIENT_DATA"

            # ── 4. 全资产类 StrategicMapper.map（Shadow 验证：映射正确，且不注入评分）──
            try:
                first_cls = next(iter(per_class_out.keys())) if per_class_out else None
                first_out = per_class_out.get(first_cls, {}) if first_cls else {}
                pc = first_out.get("primary_contradiction") or {}
                pca = first_out.get("pca_resonance") or {}
                cc = first_out.get("cycle_comparison") or {}
                ct = first_out.get("contradiction_transform") or {}
                rc = first_out.get("regime_adjustment") or {}
                fvs = first_out.get("force_vectors") or {}
                # 构造 final_direction / final_magnitude / resonance_state
                pc_dir = 1.0 if pc.get("direction", "up") == "up" else -1.0
                pc_conf = float(pc.get("confidence", 0.5))
                res_coef = float(pca.get("strength_coefficient", 1.0))
                cycle_coef = float(cc.get("adjustment_coefficient", 1.0))
                dampen = 0.5 if rc.get("should_dampen", False) else 1.0
                amplify = 1.5 if rc.get("should_amplify", False) else 1.0
                regime_ratio = float(rc.get("adjustment_ratio", 1.0))
                if not (0.01 <= abs(regime_ratio) <= 100):
                    regime_ratio = 1.0
                final_magnitude = max(0.0, min(1.0, pc_conf * res_coef * cycle_coef * dampen * amplify))
                final_direction = pc_dir
                # resonance_state：按 pca + cycle 映射为 StrategicMapper 识别的 6 态
                _cc_state = str(cc.get("consistency_state", "observation") or "observation")
                _sign_al = float(pca.get("sign_alignment", 0.5))
                if _sign_al >= 0.75 and _cc_state == "resonance":
                    resonance_state = "strong_resonance"
                elif _sign_al >= 0.5:
                    resonance_state = "resonance"
                elif _sign_al >= 0.25:
                    resonance_state = "weak_resonance"
                elif _cc_state in ("divergence", "turning"):
                    resonance_state = "conflict"
                else:
                    resonance_state = "neutral"
                # contradiction 对象：从 ContradictionTransform dataclass 重建（兼容 detect 输出对象）
                ct_obj = None
                if ct:
                    try:
                        from force_vector.models import ContradictionTransform as _CT
                        ct_obj = _CT(
                            transforming=bool(ct.get("transforming", False)),
                            triggered_conditions=list(ct.get("triggered_conditions", []) or []),
                            confidence=float(ct.get("confidence", 0.0)),
                            prev_direction=str(ct.get("prev_direction", "up")),
                            new_direction=str(ct.get("new_direction", "up")),
                            data_quality_factor=float(ct.get("data_quality_factor", 1.0)),
                        )
                    except Exception:
                        ct_obj = None
                # five_scores：五维评分快照（dao/tian/di/jiang/fa）
                five_scores = first_out.get("domain_scores") or {}

                # ★ Shadow：显式 enable_force_vector=False 保证不覆盖 war_state/cap/mask
                mapper = StrategicMapper()
                smap = mapper.map(
                    final_direction=final_direction,
                    final_magnitude=final_magnitude,
                    resonance_state=resonance_state,
                    contradiction=ct_obj,
                    force_vectors=(fvs if isinstance(fvs, dict) else None),
                    five_scores=(dict(five_scores) if isinstance(five_scores, dict) else None),
                    enable_force_vector=False,  # ★ Shadow 红线：不覆盖 war_state/cap/mask
                )
                if smap is not None:
                    # 将 StrategicLayerOutput 转成 dict 作审计快照
                    def _to_dict_safe(obj: Any) -> Any:
                        if obj is None:
                            return None
                        if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
                            try:
                                return obj.to_dict()
                            except Exception:
                                return str(obj)
                        if isinstance(obj, (list, tuple)):
                            return [_to_dict_safe(x) for x in obj]
                        if isinstance(obj, dict):
                            return {k: _to_dict_safe(v) for k, v in obj.items()}
                        if hasattr(obj, "__dataclass_fields__"):
                            import dataclasses as _dc
                            try:
                                return _dc.asdict(obj)
                            except Exception:
                                return str(obj)
                        return obj
                    record["strategic_layer_output"] = _to_dict_safe(smap)
            except Exception:
                pass

            # ── 5. 在 result 顶层附加 _force_vector_shadow（结构完全隔离） ──
            attach_snap: Dict[str, Any] = {
                "ts_ms": record["ts_ms"],
                "shadow_reason_code": record["force_vector_shadow_reason_code"],
                "per_class": {
                    cls: {
                        "data_ok": v.get("data_ok", False),
                        "reason_code": v.get("reason_code", ""),
                        "force_vectors": v.get("force_vectors"),
                        "primary_contradiction": v.get("primary_contradiction"),
                        "pca_resonance": v.get("pca_resonance"),
                        "cycle_comparison": v.get("cycle_comparison"),
                        "elasticity_beta": v.get("elasticity_beta"),
                        "contradiction_transform": v.get("contradiction_transform"),
                        "regime_adjustment": v.get("regime_adjustment"),
                    }
                    for cls, v in per_class_out.items()
                },
            }
            if record.get("strategic_layer_output") is not None:
                attach_snap["strategic_layer_output"] = record["strategic_layer_output"]
            result["_force_vector_shadow"] = attach_snap

        except Exception:
            record["force_vector_shadow_reason_code"] = "FV_GENERIC_ERR"
        finally:
            # ── 6. JSONL append（PermissionError fail-open）──
            path = getattr(self, "_force_vector_shadow_jsonl_path", None) or self._FORCE_VECTOR_SHADOW_JSONL_DEFAULT
            record["jsonl_path"] = path
            try:
                _dir = _os.path.dirname(path)
                if _dir and not _os.path.isdir(_dir):
                    _os.makedirs(_dir, exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(_json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            except PermissionError:
                record["force_vector_shadow_reason_code"] = "FV_PERMISSION"
                try:
                    import logging as _lg
                    _lg.getLogger("FiveDomain.ForceVectorShadow").warning(
                        "FV_PERMISSION 无法写入 shadow JSONL: %s", path
                    )
                except Exception:
                    pass
            except Exception:
                pass  # 其他 shadow I/O：永远 fail-open


# =====================================================================
# 辅助函数：7子开关状态 → 人类可读日志描述（修复问题2：描述不准确）
# =====================================================================

# 7子开关 → 编号(B1-B7)+短名 映射
_SUB_SWITCH_NAME_MAP = (
    # (attr_name,                code, short_label)
    ("enable_five_domain_style_mask",           "B1", "style_mask"),
    ("enable_five_domain_war_state",             "B2", "war_state"),
    ("enable_five_domain_position_cap",          "B3", "position_cap"),
    ("enable_five_domain_cross_asset",           "B4", "cross_asset"),
    ("enable_five_domain_dimensio",              "B5", "dimension_veto"),
    ("enable_five_domain_front_layer_band",      "B6", "front_layer_band"),
    ("enable_five_domain_ol",                    "B7", "ol_position_mult"),
)


def describe_five_domain_subswitches(cfg: Any) -> str:
    """根据 StrategyAlgoConfig 生成准确的子开关状态日志描述。

    修复：原日志硬编码「7子开关全False=下游零影响」，
    当 enable_five_domain_style_mask=True（或其他任一子开关开启）时描述失真。

    Returns:
        形如：
        - 全关：「7子开关全False=下游零影响」
        - B1单开：「仅1个子开关开启（B1:style_mask），其余6项下游零影响」
        - 多开：「共3个子开关开启：B1(style_mask)、B2(war_state)、B3(position_cap)」
    """
    enabled: list[tuple[str, str]] = []
    for attr, code, label in _SUB_SWITCH_NAME_MAP:
        if getattr(cfg, attr, False):
            enabled.append((code, label))

    if not enabled:
        return "7子开关全False=下游零影响"

    if len(enabled) == 1:
        code, label = enabled[0]
        others = len(_SUB_SWITCH_NAME_MAP) - len(enabled)
        return (
            f"仅1个子开关开启（{code}:{label}），"
            f"其余{others}项下游零影响"
        )

    # 多个开启
    items = "、".join(f"{c}({n})" for c, n in enabled)
    return f"共{len(enabled)}个子开关开启：{items}"
