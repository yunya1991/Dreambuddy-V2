"""
DataPipelineAdapter — 统一数据管线装配器
SPEC §3

将所有数据源组装为 KlineEventHandler.on_kline_close() 所需的 kline_data dict
FAIL-OPEN: 任一适配器异常 → 该字段缺失 → R 向量该维度走 0.5 兜底
性能预算: <1s
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .cognitive_bridge import CognitiveBridge
from .capital_rotation import CapitalRotationAdapter
from .data_center import DataCenterAdapter
from .ess_provider import ESSDirectionProvider
from .narrative_adapter import NarrativeAdapter
from .okx_market import OKXMarketAdapter
from .ripple_provider import RippleDataProvider
from .sentiment_bridge import SentimentBridge
from .subsystem_bridge import SubSystemBridge
from .traditional_finance import TraditionalFinanceBridge
from .path_library import PathLibrary
from .coin_scanner import CoinScanner
from .ftc_orchestrator import FTCOrchestrator
from .ftc_executor import evaluate_ftc

logger = logging.getLogger(__name__)


class DataPipelineAdapter:
    """统一数据管线装配器"""

    def __init__(
        self,
        okx_client: Any,
        trader: Any = None,
        data_center_db: str | None = None,
        gene_data_root: str | None = None,
        sentiment_engine: Any = None,
        min_sample: int = 0,  # Phase 0 降级
        cognitive_db: str | None = None,
        cognitive_enabled: bool = False,  # Phase 3 解冻前默认关闭
    ) -> None:
        self._okx = OKXMarketAdapter(okx_client)
        self._data_center = DataCenterAdapter(data_center_db) if data_center_db else None
        self._sentiment = SentimentBridge(
            data_center_db=data_center_db,
            sentiment_engine=sentiment_engine,
        )
        self._ess = ESSDirectionProvider(gene_data_root, min_sample=min_sample) if gene_data_root else None
        self._subsystem = SubSystemBridge(trader) if trader else None
        self._cognitive = CognitiveBridge(db_path=cognitive_db, enabled=cognitive_enabled)
        # Phase 2: odaily 叙事标签库（data_center_db 存在时启用）
        self._narrative = NarrativeAdapter(db_path=data_center_db) if data_center_db else None
        # Phase 4: 涟漪关联币数据提供器
        self._ripple = RippleDataProvider(okx_client)
        # Phase 5: 资金轮动检测器（UNI/PUMP 案例抽象）
        self._rotation = CapitalRotationAdapter(okx_client)
        # Phase 6: 传统金融桥接器（Regime/Kelly/Vol缩放/Sharpe）
        self._trad_fin = TraditionalFinanceBridge()
        # Phase 7: 最优路径库（传统/加密成熟经验参考，盈亏评分验证）
        self._path_lib = PathLibrary()
        # Phase 8: 全市场币种扫描器（50+ OKX 币种，信号发现）
        self._coin_scanner = CoinScanner(okx_client)
        # Phase 4(FTC): 金融思维链编排器 — 自进化最优路径
        try:
            self._ftc_orch = FTCOrchestrator(path_library=self._path_lib)
            self._ftc_orch.initialize_seeds()
            # 运行一次回测，为所有 FTC 计算 ESS 并分配轨道
            self._ftc_orch.run_backtest_all(symbol="BTC")
        except Exception as _e:
            logger.warning("[FO] FTCOrchestrator init failed: %s", _e)
            self._ftc_orch = None

    def assemble(self, symbol: str, inst_id: str) -> dict[str, Any]:
        """
        组装完整 kline_data dict。

        Returns dict with all fields KlineEventHandler expects (失败的 key 缺失)。
        """
        t0 = time.time()
        kline_data: dict[str, Any] = {"symbol": symbol}

        # 1. OKX 行情 (kline + ticker + positions)
        try:
            okx_data = self._okx.fetch(symbol, inst_id, limit=200)
            kline_data.update(okx_data)
        except Exception as e:
            logger.warning("[FO] OKXMarketAdapter crash: %s", e)

        # 2. data_center.db 衍生品数据
        if self._data_center is not None:
            try:
                dc_data = self._data_center.query_latest_derivatives(symbol)
                kline_data.update(dc_data)
            except Exception as e:
                logger.warning("[FO] DataCenterAdapter crash: %s", e)

        # 2b. 🆕 P1: 扩展数据源 — ETF/情绪/链上/期权/COT/Coinglass
        #     字段名对齐下游消费方（ExogenousStrengthEvaluator / ThreeFactorShort 等）
        if self._data_center is not None:
            try:
                # ETF 资金流 → etf_net_flow (float, 下游 ESE._eval_fundamental 期望)
                etf_data = self._data_center.query_etf_flow()
                if etf_data:
                    # 提取总净流入数值
                    etf_net = (
                        etf_data.get("total_net_flow")
                        or etf_data.get("net_flow")
                        or etf_data.get("total_inflow")
                        or 0.0
                    )
                    kline_data["etf_net_flow"] = float(etf_net)
                    kline_data["etf_flow_detail"] = etf_data
            except Exception as e:
                logger.debug("[FO] query_etf_flow fail: %s", e)
            try:
                # F&G 情绪指数 → fear_greed_value (float, 0-100)
                fg_data = self._data_center.query_fear_greed()
                if fg_data:
                    kline_data["fear_greed_value"] = float(fg_data.get("fear_greed", 0))
            except Exception as e:
                logger.debug("[FO] query_fear_greed fail: %s", e)
            try:
                # BTC 链上深度 → 展平为 ESE 期望的独立字段
                onchain = self._data_center.query_btc_onchain()
                if onchain:
                    kline_data["btc_onchain"] = onchain
                    # 展平到 ESE _eval_fundamental 期望的字段名
                    if "active_addresses" in onchain:
                        kline_data["active_addresses_now"] = float(onchain["active_addresses"])
                    if "exchange_netflow" in onchain:
                        kline_data["exchange_net_flow"] = float(onchain["exchange_netflow"])
                    # NVT ratio + 历史中位数（bgeometrics 有 nvt 字段时写入）
                    if "nvt" in onchain:
                        kline_data["nvt_ratio"] = float(onchain["nvt"])
                    elif "mvrv" in onchain:
                        # MVRV 作为 NVT 代理
                        kline_data["nvt_ratio"] = float(onchain["mvrv"])
                    # SOPR 映射到 utxo_turnover_rate（ESE 可能消费）
                    if "sopr" in onchain:
                        kline_data["utxo_turnover_rate"] = float(onchain["sopr"])
            except Exception as e:
                logger.debug("[FO] query_btc_onchain fail: %s", e)
            try:
                # Deribit 期权 → max_pain / put_call_ratio
                opt_data = self._data_center.query_options()
                if opt_data:
                    kline_data["options_data"] = opt_data
                    if "max_pain" in opt_data:
                        kline_data["options_max_pain"] = float(opt_data["max_pain"])
                    if "put_call_ratio" in opt_data or "pc_ratio" in opt_data:
                        kline_data["put_call_ratio"] = float(
                            opt_data.get("put_call_ratio") or opt_data.get("pc_ratio", 0)
                        )
            except Exception as e:
                logger.debug("[FO] query_options fail: %s", e)
            try:
                # CFTC COT → 机构净持仓
                cot_data = self._data_center.query_cot()
                if cot_data:
                    kline_data["cot_data"] = cot_data
                    if "non_comm_net" in cot_data:
                        kline_data["cot_net_position"] = float(cot_data["non_comm_net"])
            except Exception as e:
                logger.debug("[FO] query_cot fail: %s", e)
            try:
                # Coinglass 衍生品 → 补充 funding_rate / open_interest 交叉验证
                cg_data = self._data_center.query_coinglass_derivatives()
                if cg_data:
                    kline_data["coinglass"] = cg_data
                    # 如果 panewslab 没提供 funding_rate，用 coinglass 补充
                    if "funding_rate" not in kline_data:
                        for k, v in cg_data.items():
                            if "funding" in k.lower() and isinstance(v, (int, float)):
                                kline_data["funding_rate"] = float(v)
                                break
            except Exception as e:
                logger.debug("[FO] query_coinglass_derivatives fail: %s", e)

        # 3. Sentiment (映射到 kline_event_handler 期望的 sentiment key)
        try:
            sent_score = self._sentiment.get_sentiment_score(symbol)
            kline_data["news_sentiment_score"] = sent_score
            kline_data["sentiment"] = sent_score  # apply_sentiment_modifier 用此字段
        except Exception as e:
            logger.warning("[FO] SentimentBridge crash: %s", e)

        # 4. ESS top direction
        if self._ess is not None:
            try:
                ess_data = self._ess.get_top_direction()
                kline_data["ess_top_direction"] = ess_data["ess_top_direction"]
                kline_data["ess_top1_id"] = ess_data["ess_top1_id"]
                kline_data["ess_top1_score"] = ess_data["ess_top1_score"]
            except Exception as e:
                logger.warning("[FO] ESSDirectionProvider crash: %s", e)
                kline_data["ess_top_direction"] = ""

        # 5. SubSystem bridge (scale_class 是静态方法，不需要 trader)
        try:
            kline_data["scale_class"] = SubSystemBridge.get_scale_class(symbol)
        except Exception:
            pass

        if self._subsystem is not None:
            try:
                kline_data["bcrm_direction"] = self._subsystem.get_bcrm_direction()
                kline_data["bcrm_confidence"] = self._subsystem.get_bcrm_confidence()
                kline_data["bcrm_pattern"] = self._subsystem.get_bcrm_pattern()
                kline_data["war_state"] = self._subsystem.get_war_state()
                kline_data["ess_temperature"] = self._subsystem.get_ess_temperature()
                kline_data["five_scores"] = self._subsystem.get_five_scores()
                kline_data["position_cap"] = self._subsystem.get_position_cap()
                kline_data["btc_regime"] = self._subsystem.get_btc_regime()
                kline_data["bdsm_valuation"] = self._subsystem.get_bdsm_valuation()
                kline_data["direction_state"] = self._subsystem.get_direction_state()
                kline_data["direction_bias"] = self._subsystem.get_direction_bias()
            except Exception as e:
                logger.warning("[FO] SubSystemBridge crash: %s", e)

        # 5b. Capital flow (from OKX OI change) → apply_capital_modifier 用此字段
        capital_flow = self._compute_capital_flow(kline_data)
        if capital_flow is not None:
            kline_data["capital_flow"] = capital_flow

        # 5b-2. Capital rotation (Phase 5: 资金轮动检测，UNI/PUMP 案例抽象)
        #        从竞品组相对资金流推导本币强度，增强 capital_flow 信号
        try:
            rot_result = self._rotation.detect_rotation(symbol)
            kline_data["capital_rotation"] = rot_result["capital_rotation"]
            kline_data["capital_rotation_detail"] = rot_result
            # 轮动信号增强 capital_flow: 正轮动→流入，负轮动→流出
            if capital_flow is not None:
                kline_data["capital_flow"] = max(
                    -1.0, min(1.0, capital_flow + 0.5 * rot_result["capital_rotation"])
                )
        except Exception as e:
            logger.warning("[FO] CapitalRotationAdapter crash: %s", e)
            kline_data["capital_rotation"] = 0.0

        # 5b-3. 传统金融信号 (Phase 6: Regime/Kelly/Vol缩放/Sharpe)
        #        regime → 状态感知（趋势用动量、震荡用均值回归、危机降杠杆）
        #        kelly_fraction → 理论最优仓位
        #        vol_scalar → 波动率缩放（风险平价）
        try:
            tf_result = self._trad_fin.analyze(kline_data)
            kline_data["regime"] = tf_result["regime"]
            kline_data["trend_strength"] = tf_result["trend_strength"]
            kline_data["volatility_ratio"] = tf_result["volatility_ratio"]
            kline_data["adx"] = tf_result["adx"]
            kline_data["vol_scalar"] = tf_result["vol_scalar"]
            kline_data["kelly_fraction"] = tf_result["kelly_fraction"]
            kline_data["performance"] = tf_result["performance"]

            # Regime-aware capital_flow 调整:
            #   trend_up/down → 放大资金流信号（动量有效）
            #   ranging       → 衰减资金流信号（均值回归主导）
            #   crisis        → 抑制信号（降杠杆）
            regime = tf_result["regime"]
            regime_mult = {"trend_up": 1.3, "trend_down": 1.3,
                           "ranging": 0.7, "crisis": 0.3}.get(regime, 1.0)
            if "capital_flow" in kline_data:
                kline_data["capital_flow"] = max(
                    -1.0, min(1.0, kline_data["capital_flow"] * regime_mult)
                )
        except Exception as e:
            logger.warning("[FO] TraditionalFinanceBridge crash: %s", e)
            kline_data["regime"] = "ranging"
            kline_data["vol_scalar"] = 1.0
            kline_data["kelly_fraction"] = 0.10

        # 5b-4. 最优路径评估 (Phase 7: 传统/加密成熟路径库)
        #        系统参考成熟路径，但必须用当前数据验证，盈亏作为评分标准
        try:
            triggered_paths = self._path_lib.evaluate_all(kline_data)
            kline_data["triggered_paths"] = triggered_paths
            # 取最强路径方向作为参考（不直接执行，供 d* 参考）
            if triggered_paths:
                top_path = triggered_paths[0]
                kline_data["top_path"] = top_path["path"]
                kline_data["top_path_direction"] = top_path["direction"]
                kline_data["top_path_confidence"] = top_path["confidence"]
            else:
                kline_data["top_path"] = ""
                kline_data["top_path_direction"] = "neutral"
                kline_data["top_path_confidence"] = 0.0
        except Exception as e:
            logger.warning("[FO] PathLibrary evaluate crash: %s", e)
            kline_data["triggered_paths"] = []
            kline_data["top_path"] = ""

        # 5b-5. FTC 金融思维链评估 (Phase 4)
        #        自进化最优路径：经验路径拆解→基因组合→回测ESS→盈亏验证
        try:
            if self._ftc_orch is not None:
                top_ftcs = self._ftc_orch.get_top_ftcs(n=3)
                kline_data["top_ftcs"] = [f.ftc_id for f in top_ftcs]
                # 对 top FTC 执行条件检查
                best_signal = None
                best_ftc = None
                for ftc in top_ftcs:
                    sig = evaluate_ftc(ftc, kline_data)
                    if sig["signal"] != "WAIT" and (best_signal is None or sig["confidence"] > best_signal["confidence"]):
                        best_signal = sig
                        best_ftc = ftc
                if best_ftc and best_signal:
                    kline_data["top_ftc"] = best_ftc.ftc_id
                    kline_data["top_ftc_direction"] = best_signal["signal"]
                    kline_data["top_ftc_ess"] = best_ftc.ess or 0.0
                    kline_data["top_ftc_track"] = best_ftc.track
                    kline_data["top_ftc_confidence"] = best_signal["confidence"]
                else:
                    kline_data["top_ftc"] = ""
                    kline_data["top_ftc_direction"] = "neutral"
                    kline_data["top_ftc_ess"] = 0.0
                    kline_data["top_ftc_track"] = "exploit"
                    kline_data["top_ftc_confidence"] = 0.0
            else:
                kline_data["top_ftc"] = ""
                kline_data["top_ftc_direction"] = "neutral"
                kline_data["top_ftc_ess"] = 0.0
                kline_data["top_ftc_track"] = "exploit"
                kline_data["top_ftc_confidence"] = 0.0
        except Exception as e:
            logger.warning("[FO] FTC evaluate crash: %s", e)
            kline_data["top_ftc"] = ""
            kline_data["top_ftc_direction"] = "neutral"
            kline_data["top_ftc_track"] = "exploit"

        # 5c. Narrative (Phase 2: odaily 叙事标签库 → R_narrative)
        if self._narrative is not None:
            try:
                narrative_score = self._narrative.get_narrative_score(symbol)
                kline_data["narrative"] = narrative_score
            except Exception as e:
                logger.warning("[FO] NarrativeAdapter crash: %s", e)
                kline_data["narrative"] = None
        else:
            kline_data["narrative"] = None

        # 5d. liq_index_change 代理：panewslab 清算数据缺失时，用量比作为清算指数变化代理
        #     detect_ripple_source 要求 liq_index_change >= 0.30
        #     量比 vol_5/vol_20 >= 1.3 → liq_index_change >= 0.30（放量伴随清算放大）
        if "liq_index_change" not in kline_data:
            vol_5 = float(kline_data.get("vol_5", 0) or 0)
            vol_20 = float(kline_data.get("vol_20", 1e-9) or 1e-9)
            if vol_20 > 0:
                vol_ratio = vol_5 / vol_20
                # vol_ratio=1.0 → 0.0, vol_ratio=1.3 → 0.30, vol_ratio=2.0 → 1.0, cap at 2.0
                kline_data["liq_index_change"] = max(0.0, min(2.0, vol_ratio - 1.0))
                kline_data["vol_ratio"] = round(vol_ratio, 4)  # 供 PathLibrary 使用

        # 6. ripples (Phase 2: R1 hit 基于 ESS 方向 vs K线方向一致性)
        kline_data["ripples"] = self._build_ripples(kline_data)

        elapsed = time.time() - t0
        if elapsed > 1.0:
            logger.warning("[PERF] assemble took %.3fs (>1s budget)", elapsed)

        kline_data["_assemble_ms"] = round(elapsed * 1000, 1)
        return kline_data

    @staticmethod
    def _compute_capital_flow(kline_data: dict) -> float | None:
        """
        从 OKX OI 变化计算 capital_flow ∈ [-1, +1]。
        正值=净流入(看多)，负值=净流出(看空)。
        """
        try:
            oi_change = kline_data.get("oi_change_pct")
            if oi_change is not None:
                return float(oi_change)
            # 降级：从 data_center open_interest 推断
            oi = kline_data.get("open_interest")
            if oi is not None and oi > 0:
                import math
                oi_log = math.log10(max(oi, 1))
                return max(-1.0, min(1.0, (oi_log - 6.0) / 2.0))
            return None
        except Exception:
            return None

    def _build_ripples(self, kline_data: dict) -> dict:
        """
        Phase 4 涟漪构造（R1/R2/R3 全激活）：
        - R1 hit: 当前 K线方向 与 ess_top_direction 一致 → hits=1
        - R2 hit: 核心关联币（BTC↔ETH↔SOL）4H 方向一致数
        - R3 hit: 板块大盘币 4H 方向一致数（板块扩散）
        """
        symbol = kline_data.get("symbol", "")
        ess_dir = kline_data.get("ess_top_direction", "")

        # --- R1: 同币方向一致性 ---
        r1_hits = 0
        try:
            close = kline_data.get("close")
            if close is not None and len(close) >= 2 and ess_dir:
                is_up = float(close[-1]) > float(close[-2])
                kline_dir = "long" if is_up else "short"
                if kline_dir == ess_dir.lower():
                    r1_hits = 1
        except Exception:
            r1_hits = 0

        # --- R2 / R3: 关联币方向一致性 ---
        r2_hits, r2_cands = 0, 1
        r3_hits, r3_cands = 0, 1
        try:
            ripple_hits = self._ripple.get_ripple_hits(symbol, ess_dir)
            r2 = ripple_hits.get("R2", {})
            r3 = ripple_hits.get("R3", {})
            r2_hits = int(r2.get("hits", 0))
            r2_cands = int(r2.get("candidates", 1))
            r3_hits = int(r3.get("hits", 0))
            r3_cands = int(r3.get("candidates", 1))
        except Exception as e:
            logger.debug("[FO] ripple R2/R3 compute fail: %s", e)

        return {
            "R1": {"hits": r1_hits, "candidates": 1, "delta_t_hours": 1, "tau": 1.0},
            "R2": {"hits": r2_hits, "candidates": r2_cands, "delta_t_hours": 4, "tau": 4.0},
            "R3": {"hits": r3_hits, "candidates": r3_cands, "delta_t_hours": 12, "tau": 12.0},
        }

    # ---------------------------------------------------------- 认知系统
    def get_cognitive_bridge(self) -> CognitiveBridge:
        """获取认知桥接器实例（供外部调用 record/verify）"""
        return self._cognitive

    # ---------------------------------------------------------- 叙事
    def get_narrative_adapter(self) -> NarrativeAdapter | None:
        """获取叙事适配器实例"""
        return self._narrative

    # ---------------------------------------------------------- 传统金融
    def get_traditional_finance_bridge(self) -> TraditionalFinanceBridge:
        """获取传统金融桥接器实例"""
        return self._trad_fin

    def record_trade_result(self, pnl_pct: float) -> None:
        """记录交易结果到绩效跟踪器（供 Sharpe/Sortino/Kelly 计算）"""
        self._trad_fin.record_trade(pnl_pct)

    # ---------------------------------------------------------- 最优路径库
    def get_path_library(self) -> PathLibrary:
        """获取最优路径库实例"""
        return self._path_lib

    def record_path_trade(self, path_name: str, pnl_pct: float) -> None:
        """记录路径交易盈亏，更新路径评分"""
        self._path_lib.record_trade(path_name, pnl_pct)

    # ---------------------------------------------------------- 币种扫描器
    def get_coin_scanner(self) -> CoinScanner:
        """获取币种扫描器实例"""
        return self._coin_scanner

    def scan_market(self, top_n: int = 20) -> list[dict[str, Any]]:
        """扫描全市场，返回信号最强的 top_n 币种"""
        return self._coin_scanner.scan(top_n=top_n)

    # ---------------------------------------------------------- FTC 金融思维链
    def get_ftc_orchestrator(self):
        """获取 FTC 编排器实例（可能为 None）"""
        return self._ftc_orch

    def get_ftc_track_multiplier(self, track: str) -> float:
        """
        根据 FTC 轨道返回仓位乘数（Phase 4 实盘分档）:
          exploit → 1.0 (25U 满仓)
          mixed   → 0.5 (12.5U 半仓)
          explore → 0.2 (5U 探索仓)
          discard → 0.0 (不开仓)
        """
        return {
            "exploit": 1.0,
            "mixed": 0.5,
            "explore": 0.2,
            "discard": 0.0,
        }.get(track, 1.0)
