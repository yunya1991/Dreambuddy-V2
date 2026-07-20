#!/usr/bin/env python3
"""
易经推理轮询交易器（P2 完整版）

集成功能：
- P2-1a: 平仓后自动生成 case 存入 L4
- P2-1b: 定期重训 LiangyiEngine + QMM
- P2-2a: 动态仓位（置信度 + 波动率）
- P2-2b: 日最大亏损限制 + 连续亏损熔断
- P2-3: 交易绩效统计 + PnL 持久化
- P2-4: BCRM 矛盾格式修复
- P2-5: 进程守护 + 异常告警 + 日志持久化

用法:
  python -m scripts.memory_l4.polling_trader --once
  python -m scripts.memory_l4.polling_trader --interval 300 --coins BTC,ETH
"""
import argparse
import json
import time
import signal as signal_module
import os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

from scripts.memory_l4.yijing_trainer import (
    _kline_to_snapshot,
    _build_contradiction_list,
    _build_research_contradictions,
    _contradictions_to_bcrm_format,
    _load_kline_from_okx,
    _detect_ranging_market,
)
from scripts.memory_l4.bcrm.engine import BCRMEngine
from scripts.memory_l4.bcrm.bagua_engine import BaguaEngine
from scripts.memory_l4.okx_simulated import OKXSimulatedClient
from scripts.memory_l4.trading_utils import (
    PerformanceTracker,
    RiskManager,
    PositionTracker,
    generate_case_from_trade,
    save_case_to_l4,
)
from scripts.memory_l4.learning_scheduler import LearningScheduler
from scripts.memory_l4.process_guardian import ProcessGuardian
from scripts.memory_l4.knowledge_bridge import KnowledgeBridge
from scripts.memory_l4.classic_exit_system import (
    ClassicExitSystem,
    PositionState as ExitPositionState,
    ExitAction,
    ExitConfig,
)
from scripts.memory_l4.yijing_exit_system import (
    YijingExitSystem, YijingExitConfig, YijingExitAction,
)
from scripts.memory_l4.bcrm2.incremental_learner import IncrementalLearner
from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter
from scripts.memory_l4.yijing_feishu_alert import notify_model_error, notify_system_error
from scripts.memory_l4.ranging_market_enhancer import (
    RangingMarketEnhancer,
    MarketRegime,
    BollingerSignal,
    HexagramDataDrivenCalibrator,
)


class PollingTrader:
    """易经推理轮询交易器（P2 完整版）"""

    def __init__(self,
                 interval: int = 3600,
                 coins: list = None,
                 bar: str = "1H",
                 confidence_threshold: float = 0.55,
                 max_positions: int = 3,
                 kline_limit: int = 200,
                 initial_equity: float = 100.0,
                 daily_loss_limit: float = -50.0,
                 max_consecutive_losses: int = 5,
                 default_position_pct: float = 0.10,
                 guardian: ProcessGuardian = None,
                 shared_dir=None,
                 use_bcrm2: bool = True):
        self.interval = interval
        self.coins = coins or ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE"]
        self.bar = bar
        self.confidence_threshold = confidence_threshold
        self.max_positions = max_positions
        self.kline_limit = kline_limit

        self.bcrm_engine = BCRMEngine()
        self.bagua_engine = BaguaEngine()
        self.okx_client = OKXSimulatedClient()
        
        self.use_bcrm2 = use_bcrm2
        self.bcrm2_adapters = {}
        if self.use_bcrm2:
            # 措施1：启动时主动验证 BCRM 2.0 模块导入与核心依赖可用性
            # 避免运行时才发现 "No module named 'bcrm2'" 等导入错误
            healthy, reason = self._health_check_bcrm2()
            if not healthy:
                self._log(f"[BCRM2.0] 启动健康检查失败: {reason}，降级到 BCRM 1.0", "WARN")
                self.use_bcrm2 = False
                try:
                    notify_system_error(
                        f"BCRM2.0 启动健康检查失败，已降级到 BCRM 1.0: {reason}",
                        component="BCRM2.0健康检查",
                    )
                except Exception as e:
                    self._log(f"[BCRM2.0] 飞书告警发送失败: {e}", "WARN")
            else:
                self._log(f"[BCRM2.0] 模式已启用，启动健康检查通过", "INFO")

        self.running = False
        self.cycle_count = 0
        self.last_date = datetime.now().strftime("%Y-%m-%d")

        self.perf_tracker = PerformanceTracker(initial_equity=initial_equity)
        self.risk_manager = RiskManager(
            daily_loss_limit_usdt=daily_loss_limit,
            max_consecutive_losses=max_consecutive_losses,
            default_position_pct=default_position_pct,
            min_position_usdt=20.0,
        )
        self.position_tracker = PositionTracker()
        self.learning_scheduler = LearningScheduler(
            bcrm_engine=self.bcrm_engine,
            retrain_interval_cases=10,
            retrain_interval_hours=4,
            on_retrain_complete=self._on_retrain_complete,
            shared_dir=shared_dir,
        )
        self.guardian = guardian

        self.knowledge_bridge = KnowledgeBridge(shared_dir=shared_dir)
        self.external_knowledge = {}

        # 经典指标离场系统（短期修复：关闭杠杆解耦 + 放宽震荡市止损 + 暂停 Risk Gate 追跌）
        exit_cfg = ExitConfig(
            l0_max_hold_sec=172800,
            l0_max_loss_pct=-0.05,
            tb_enabled=True,
            tb_sl_atr_mult=1.5,
            tb_tp_atr_mult=3.0,
            tb_sl_min_pct=0.045,  # 震荡市从 2% 提到 4.5%（覆盖默认 2%）
            tb_tp_min_pct=0.04,
            trailing_enabled=True,
            trailing_arm_profit_pct=0.04,
            trailing_retrace_pct=0.035,  # 跟踪止损回撤从 2% 放到 3.5%，减少震荡洗盘
            tstp_enabled=True,
            l1_enabled=True,
            l2_close_threshold=0.75,
            l2_reduce_threshold=0.55,
            apply_leverage_to_thresholds=True,  # 关闭杠杆解耦：-5% 真的是 -5%
            inflight_cooldown_sec=180,
            # 暂停 Risk Gate 追跌强制 close：震荡市 hold_risk 持续高位易误伤
            l0_risk_gate_enabled=True,  # 保留 armed + reduce（减仓保护）
            l0_risk_gate_close_enabled=False,  # 关闭强制 close，避免追跌平仓
            l0_risk_gate_cooldown_min=60.0,  # cooldown 从 30min 拉长到 60min
            l0_risk_gate_confirm_n=3,  # 确认次数从 2 提到 3，更保守
        )
        self.exit_system = ClassicExitSystem(config=exit_cfg)
        self._exit_cfg_base = exit_cfg  # 保存基准配置，供动态调整使用

        # 震荡市增强器（优化1-5统一入口）
        # 包含：5种市场状态、布林带双信号确认、MA200方向性偏向、动态止损宽度、置信度校准
        self.ranging_enhancer = RangingMarketEnhancer()
        # 优化5：卦象数据驱动校准器（500+样本后重新校准64卦参数）
        self.ranging_enhancer.hex_calibrator = HexagramDataDrivenCalibrator()

        # 易经专属离场系统：基于卦象风险-价值评估，可否决 classic 的噪音止损
        self.yijing_exit_system = YijingExitSystem(config=YijingExitConfig())
        self.yijing_exit_system.set_log_callback(self._log)

        self.log_dir = Path("data/polling_trader")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"trader_{datetime.now().strftime('%Y%m%d')}.jsonl"

        self.incremental_learner = IncrementalLearner(
            retrain_trade_threshold=100,
            retrain_win_rate_threshold=0.5,
            retrain_sharpe_threshold=1.0,
        )

        # 异常检测引擎 (Phase 2.1)
        from scripts.memory_l4.bcrm2.anomaly_detector import HybridAnomalyDetector
        self.anomaly_detector = HybridAnomalyDetector(
            if_contamination=0.02,
            enable_if=True,
            enable_lgb=True,
            enable_dl=False,
        )
        self._kline_cache = {}  # 缓存K线数据用于异常检测

        self._sync_existing_positions()

    def _sync_existing_positions(self):
        """同步 OKX 已有持仓到本地跟踪器"""
        self._log("[持仓同步] 检查 OKX 已有持仓...", "INFO")
        for coin in self.coins:
            inst_id = f"{coin}-USDT-SWAP"
            pos_result = self.okx_client.get_positions(inst_id)
            if not pos_result.get("ok"):
                continue
            positions = pos_result.get("positions", [])
            for pos in positions:
                if float(pos["pos"]) <= 0:
                    continue
                if self.position_tracker.has_open_position(inst_id):
                    continue
                self.position_tracker.open_position(
                    coin=coin,
                    inst_id=inst_id,
                    direction=pos["pos_side"],
                    entry_price=float(pos["avg_px"]),
                    confidence=0.5,
                    hexagram="已存在持仓",
                    market_snapshot={"price": float(pos.get("mark_px", pos["avg_px"]))},
                    strategy_source="external",
                )
                self._log(f"[持仓同步] 已同步 {coin} {pos['pos_side']} @ {pos['avg_px']} [外部策略]", "INFO")

        # 反向清理：本地有但 OKX 已无持仓的记录（已止损/止盈/手动平仓）
        for p in self.position_tracker.all_open_positions():
            inst_id = p.inst_id
            pos_result = self.okx_client.get_positions(inst_id)
            if not pos_result.get("ok"):
                continue
            okx_positions = [pp for pp in pos_result.get("positions", []) if float(pp["pos"]) > 0]
            if not okx_positions:
                self.position_tracker.close_position(
                    inst_id,
                    exit_price=0.0,
                    exit_reason="OKX持仓已不存在，清理本地残留",
                )
                self._log(f"[持仓同步] 清理本地残留 {inst_id} (OKX已无持仓)", "WARN")

        open_count = len(self.position_tracker.all_open_positions())
        external_count = sum(1 for p in self.position_tracker.all_open_positions()
                             if p.strategy_source == "external")
        self._log(f"[持仓同步] 完成，共 {open_count} 个持仓 (BCRM={open_count-external_count} 外部={external_count})", "INFO")

    def _log(self, msg: str, level: str = "INFO"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": ts, "level": level, "msg": msg},
                                   ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _health_check_bcrm2(self) -> tuple:
        """措施1：BCRM 2.0 启动健康检查

        主动验证 BCRM 2.0 关键模块导入路径与核心依赖可用性，
        避免运行时才发现 "No module named 'bcrm2'" 等问题导致静默回退。

        Returns:
            (healthy: bool, reason: str) — healthy=True 表示检查通过
        """
        checks = []

        # 1. 验证核心模块导入路径
        try:
            from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter  # noqa: F401
            checks.append(("BCRM2Adapter 导入", True, ""))
        except Exception as e:
            checks.append(("BCRM2Adapter 导入", False, str(e)))

        # 2. 验证辩证ML引擎可加载
        try:
            from scripts.memory_l4.bcrm2.dialectical_ml_engine import DialecticalMLEngine
            checks.append(("DialecticalMLEngine 导入", True, ""))
        except Exception as e:
            checks.append(("DialecticalMLEngine 导入", False, str(e)))

        # 3. 验证八卦特征引擎可加载
        try:
            from scripts.memory_l4.bcrm2.bagua_feature_engine import BaguaFeatureEngine
            checks.append(("BaguaFeatureEngine 导入", True, ""))
        except Exception as e:
            checks.append(("BaguaFeatureEngine 导入", False, str(e)))

        # 4. 验证增量学习器可加载
        try:
            from scripts.memory_l4.bcrm2.incremental_learner import IncrementalLearner
            checks.append(("IncrementalLearner 导入", True, ""))
        except Exception as e:
            checks.append(("IncrementalLearner 导入", False, str(e)))

        # 5. 验证关键依赖库 (lightgbm / pandas / numpy)
        try:
            import lightgbm  # noqa: F401
            checks.append(("lightgbm 依赖", True, f"v{lightgbm.__version__}"))
        except Exception as e:
            checks.append(("lightgbm 依赖", False, str(e)))

        # 汇总
        failed = [c for c in checks if not c[1]]
        if failed:
            reason = "; ".join(f"{name}失败: {msg}" for name, _, msg in failed)
            return (False, reason)

        passed_summary = ", ".join(name for name, _, _ in checks)
        self._log(f"[BCRM2.0] 健康检查项: {passed_summary}", "INFO")
        return (True, "all checks passed")

    def _on_retrain_complete(self, result: dict):
        """重训完成回调"""
        self._log(
            f"[学习调度] 重训完成 | case={result.get('case_count')} "
            f"两仪更新={result.get('liangyi_updated')} "
            f"QMM更新={result.get('qmm_updated')} "
            f"第{result.get('retrain_count')}次"
        )

    def _check_date_rollover(self):
        """检查是否跨天，重置每日风控"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.last_date:
            self._log(f"[风控] 新的一天 {today}，重置每日风控统计")
            self.risk_manager.reset_daily()
            self.last_date = today

    def _fetch_and_infer(self, coin: str) -> dict:
        """获取实时行情并执行 BCRM + 八卦双引擎推理"""
        inst_id = f"{coin}-USDT-SWAP"

        kline_data = _load_kline_from_okx(
            inst_id=inst_id, bar=self.bar, limit=self.kline_limit)
        if not kline_data:
            return {"ok": False, "error": f"获取 {inst_id} K线失败"}
        
        # BCRM 2.0 推理路径
        if self.use_bcrm2:
            try:
                return self._infer_bcrm2(coin, inst_id, kline_data)
            except Exception as e:
                # 措施2：BCRM2.0 运行时未预期异常，降级到 BCRM 1.0 并告警
                self._log(f"[{coin}] BCRM2.0 运行异常: {e}，降级到 BCRM 1.0", "ERROR")
                try:
                    notify_model_error(
                        f"BCRM2.0 运行异常降级: {type(e).__name__}: {e}",
                        symbol=coin,
                    )
                except Exception as alert_err:
                    self._log(f"[{coin}] 飞书告警发送失败: {alert_err}", "WARN")
                self.use_bcrm2 = False
                # 降级后继续走 BCRM 1.0 推理路径（不 return，落到下面）

        snapshot = _kline_to_snapshot(kline_data, idx=0)
        if not snapshot:
            return {"ok": False, "error": "构造 snapshot 失败"}
        snapshot["symbol"] = inst_id

        contradictions_raw = _build_contradiction_list(snapshot)
        contradictions_raw.extend(_build_research_contradictions(snapshot))
        contradictions = _contradictions_to_bcrm_format(contradictions_raw, snapshot)

        closes_window = [kline_data[j]["c"]
                         for j in range(min(60, len(kline_data)))]
        volumes_window = [kline_data[j].get("v", 0)
                          for j in range(min(60, len(kline_data)))]
        ranging_info = _detect_ranging_market(snapshot, closes_window)
        snapshot["is_ranging"] = ranging_info.get("is_ranging", False)
        snapshot["ranging_confidence"] = ranging_info.get("confidence", 0)

        # P0修复: 每币种推理前重置 ForceEngine 速度状态，防止跨币种污染
        if hasattr(self.bcrm_engine, 'force_engine') and \
           hasattr(self.bcrm_engine.force_engine, 'reset_velocity'):
            self.bcrm_engine.force_engine.reset_velocity()

        qmm_output = {"uncertainty": 0.3}
        try:
            bcrm_result = self.bcrm_engine.infer(
                market_snapshot=snapshot,
                contradiction_list=contradictions,
                qmm_output=qmm_output,
            )
        except Exception as e:
            if self.guardian:
                self.guardian.record_error(e, context=f"bcrm_infer:{coin}")
            return {"ok": False, "error": f"BCRM 推理失败: {e}"}

        direction = bcrm_result.next_state.direction
        confidence = bcrm_result.next_state.confidence
        hex_cn = (bcrm_result.hexagram.hexagram_name_cn
                  or bcrm_result.hexagram.hexagram_name)
        fail_closed = bcrm_result.is_fail_closed()

        bagua_result = None
        try:
            bagua_result = self.bagua_engine.infer(
                snapshot=snapshot,
                closes=closes_window,
                volumes=volumes_window,
            )
        except Exception:
            pass

        bagua_dir = bagua_result.primary_direction if bagua_result else "neutral"
        bagua_conf = bagua_result.primary_confidence if bagua_result else 0

        bcrm_dir_num = 1 if direction == "UP" else (-1 if direction == "DOWN" else 0)
        bagua_dir_num = 1 if bagua_dir == "long" else (-1 if bagua_dir == "short" else 0)

        if bcrm_dir_num != 0 and bagua_dir_num != 0:
            if bcrm_dir_num == bagua_dir_num:
                confidence = min(0.95, confidence * 0.5 + bagua_conf * 0.5 + 0.1)
            else:
                confidence = confidence * 0.4
                if bagua_conf > confidence + 0.2:
                    direction = "UP" if bagua_dir == "long" else "DOWN"
                    confidence = bagua_conf * 0.7
        elif bcrm_dir_num == 0 and bagua_dir_num != 0:
            direction = "UP" if bagua_dir == "long" else "DOWN"
            confidence = bagua_conf * 0.6
        elif bagua_dir_num == 0 and bcrm_dir_num != 0:
            confidence = confidence * 0.7

        if bagua_result and bagua_result.hexagram_name_cn:
            hex_cn = bagua_result.hexagram_name_cn

        # 卦象名与方向一致性检查 (修复: 2026-07-13)
        hex_consistent = True
        if hex_cn:
            gua_direction = self._get_hexagram_direction(hex_cn)
            actual_direction = "long" if direction == "UP" else "short"
            if gua_direction and gua_direction != "neutral" and gua_direction != actual_direction:
                hex_consistent = False
                # 尝试使用变卦或互卦作为替代卦象
                if bcrm_result and hasattr(bcrm_result, 'hexagram'):
                    bcrm_hex = bcrm_result.hexagram
                    # 使用变卦替代
                    if hasattr(bcrm_hex, 'changed_hexagram_cn') and bcrm_hex.changed_hexagram_cn:
                        hex_cn = bcrm_hex.changed_hexagram_cn
                        self._log(f"[{coin}] 卦象校准 | {hex_cn}(变卦) 替代原卦象", "INFO")
                    else:
                        self._log(
                            f"[{coin}] 卦象警告 | 卦象{hex_cn}({gua_direction})与决策方向({actual_direction})不一致",
                            "WARN"
                        )

        sl_px, tp_px, reduce_ratio = 0, 0, 0
        if bcrm_result.strategy_branches:
            b1 = next((b for b in bcrm_result.strategy_branches
                       if b.branch_id == "B1"), None)
            if b1:
                sl_px = b1.stop_loss_px
                tp_px = b1.take_profit_px
                reduce_ratio = b1.reduce_ratio

        # 经典指标离场回退：BCRM 未产生止盈止损时，用 ATR 计算止损止盈
        if sl_px == 0 or tp_px == 0:
            price = snapshot.get("price", 0)
            volatility = snapshot.get("volatility", 0.03)
            if price > 0:
                # ATR 近似：用波动率 × 价格作为 ATR 估计
                atr = max(price * volatility, price * 0.005)  # 至少 0.5%
                atr_mult_sl = 1.5   # 止损 = 1.5 × ATR
                atr_mult_tp = 3.0   # 止盈 = 3.0 × ATR（盈亏比 2:1）
                if direction == "UP":
                    fallback_sl = round(price - atr * atr_mult_sl, 4)
                    fallback_tp = round(price + atr * atr_mult_tp, 4)
                else:
                    fallback_sl = round(price + atr * atr_mult_sl, 4)
                    fallback_tp = round(price - atr * atr_mult_tp, 4)
                if sl_px == 0:
                    sl_px = fallback_sl
                if tp_px == 0:
                    tp_px = fallback_tp
                self._log(
                    f"[{coin}] 经典指标离场 | ATR={atr:.2f} | "
                    f"SL={sl_px} TP={tp_px} (盈亏比={atr_mult_tp/atr_mult_sl:.1f}:1)",
                    "INFO")

        liangyi_dict = {}
        if hasattr(bcrm_result, 'liangyi_state') and bcrm_result.liangyi_state:
            if hasattr(bcrm_result.liangyi_state, 'to_dict'):
                liangyi_dict = bcrm_result.liangyi_state.to_dict()
            elif isinstance(bcrm_result.liangyi_state, dict):
                liangyi_dict = bcrm_result.liangyi_state

        scale_dict = {}
        if hasattr(bcrm_result, 'scale_params') and bcrm_result.scale_params:
            if hasattr(bcrm_result.scale_params, 'to_dict'):
                scale_dict = bcrm_result.scale_params.to_dict()
            elif isinstance(bcrm_result.scale_params, dict):
                scale_dict = bcrm_result.scale_params

        return {
            "ok": True,
            "coin": coin,
            "inst_id": inst_id,
            "price": snapshot.get("price", 0),
            "direction": direction,
            "confidence": round(confidence, 4),
            "hexagram": hex_cn,
            "hex_consistent": hex_consistent,  # 卦象方向一致性标志
            "fail_closed": fail_closed,
            "is_ranging": snapshot.get("is_ranging", False),
            "bagua_direction": bagua_dir,
            "bagua_confidence": round(bagua_conf, 4),
            "stop_loss_px": sl_px,
            "take_profit_px": tp_px,
            "reduce_ratio": reduce_ratio,
            "liangyi_state": liangyi_dict,
            "scale_params": scale_dict,
            "snapshot": snapshot,
            "contradictions": contradictions,
            "volatility": snapshot.get("volatility", 0.03),
            "kline_data": kline_data,
        }

    def _kline_to_dataframe(self, kline_data: list) -> "pd.DataFrame":
        """将 OKX K线数据转换为 pandas DataFrame"""
        import pandas as pd
        data = []
        for c in kline_data:
            data.append({
                'timestamp': c.get('ts', 0),
                'open': float(c.get('o', 0)),
                'high': float(c.get('h', 0)),
                'low': float(c.get('l', 0)),
                'close': float(c.get('c', 0)),
                'volume': float(c.get('v', 0)),
            })
        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)
        return df

    def _infer_bcrm2(self, coin: str, inst_id: str, kline_data: list) -> dict:
        """使用 BCRM 2.0 (辩证ML) 执行推理"""
        import pandas as pd
        
        if coin not in self.bcrm2_adapters:
            self.bcrm2_adapters[coin] = BCRM2Adapter(
                symbol=coin,
                timeframe=self.bar,
                tp_atr=3.0,
                sl_atr=1.5,
                max_hold_bars=60,
            )
        
        adapter = self.bcrm2_adapters[coin]
        
        try:
            df = self._kline_to_dataframe(kline_data)
        except Exception as e:
            return {"ok": False, "error": f"K线转换失败: {e}"}
        
        # 首次推理时自动训练
        if adapter.engine is None:
            self._log(f"[{coin}] BCRM2.0 首次推理，开始训练模型...", "INFO")
            if not adapter.train(df):
                # 措施2：训练失败回退时立即发送飞书告警
                self._log(f"[{coin}] BCRM2.0 训练失败，回退到 BCRM 1.0", "WARN")
                try:
                    notify_model_error(
                        f"BCRM2.0 训练失败，已降级回退到 BCRM 1.0",
                        symbol=coin,
                    )
                except Exception as e:
                    self._log(f"[{coin}] 飞书告警发送失败: {e}", "WARN")
                self.use_bcrm2 = False
                return self._fetch_and_infer(coin)

        # 执行推理
        bcrm_result = adapter.infer(df, idx=-1)

        if not bcrm_result.get('ok'):
            # 措施2：推理失败时立即发送飞书告警（fail_closed 也会走这里）
            fail_reason = bcrm_result.get('fail_closed_reason', '未知')
            self._log(f"[{coin}] BCRM2.0 推理失败: {fail_reason}", "WARN")
            try:
                notify_model_error(
                    f"BCRM2.0 推理失败 (fail_closed): {fail_reason}",
                    symbol=coin,
                )
            except Exception as e:
                self._log(f"[{coin}] 飞书告警发送失败: {e}", "WARN")
            return {"ok": False, "error": "BCRM2.0 推理失败"}
        
        direction = bcrm_result['next_state']['direction']
        confidence = bcrm_result['next_state']['confidence']
        hex_cn = bcrm_result['hexagram']['hexagram_name_cn']
        fail_closed = bcrm_result['is_fail_closed']()
        
        # 计算波动率（用于止盈止损）
        closes = df['close'].values
        atr = 0
        if len(df) >= 14:
            highs = df['high'].values
            lows = df['low'].values
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(
                    np.abs(highs[1:] - closes[:-1]),
                    np.abs(lows[1:] - closes[:-1])
                )
            )
            atr = np.mean(tr[-14:])
        volatility = atr / closes[-1] if closes[-1] > 0 else 0.03
        
        # 检测震荡市
        closes_window = list(closes[-60:])
        snapshot_simple = {"price": closes[-1], "volatility": volatility}
        ranging_info = _detect_ranging_market(snapshot_simple, closes_window)
        is_ranging = ranging_info.get("is_ranging", False)
        
        price = closes[-1]
        
        # 计算 ATR 止盈止损
        sl_px, tp_px = 0, 0
        if atr > 0:
            if direction == "UP":
                sl_px = round(price - atr * 1.5, 4)
                tp_px = round(price + atr * 3.0, 4)
            elif direction == "DOWN":
                sl_px = round(price + atr * 1.5, 4)
                tp_px = round(price - atr * 3.0, 4)
        
        self._log(
            f"[{coin}] BCRM2.0 推理 | 方向={direction} 置信度={confidence:.2f} "
            f"卦象={hex_cn} fail_closed={fail_closed}",
            "INFO"
        )
        
        return {
            "ok": True,
            "coin": coin,
            "inst_id": inst_id,
            "price": price,
            "direction": direction,
            "confidence": round(confidence, 4),
            "hexagram": hex_cn,
            "hex_consistent": True,
            "fail_closed": fail_closed,
            "is_ranging": is_ranging,
            "bagua_direction": "neutral",
            "bagua_confidence": 0,
            "stop_loss_px": sl_px,
            "take_profit_px": tp_px,
            "reduce_ratio": 0,
            "liangyi_state": {},
            "scale_params": {},
            "snapshot": {
                "price": price,
                "volatility": volatility,
                "is_ranging": is_ranging,
            },
            "contradictions": [],
            "volatility": volatility,
            "kline_data": kline_data,
        }

    def _get_hexagram_direction(self, hexagram_name: str) -> str:
        """根据卦象名查询卦象方向

        Args:
            hexagram_name: 卦象中文名 (如 "巽为风")

        Returns:
            卦象方向: "long" / "short" / "neutral" / "" (未知)
        """
        # 卦象名到方向的映射 (基于SIXTY_FOUR_GUAS)
        HEX_TO_DIRECTION = {
            "乾为天": "long",
            "坤为地": "short",
            "水雷屯": "neutral",
            "山水蒙": "neutral",
            "水天需": "long",
            "天水讼": "neutral",
            "地水师": "short",
            "水地比": "long",
            "风雷益": "long",
            "雷风恒": "neutral",
            "离为火": "long",
            "泽火革": "neutral",
            "火风鼎": "long",
            "巽为风": "long",
            "兑为泽": "long",
            "艮为山": "neutral",
            "山地剥": "short",
            "地雷复": "long",
            "坎为水": "short",
            "水火既济": "neutral",
            "火水未济": "neutral",
            "地天泰": "long",
            "天地否": "short",
            "天雷无妄": "neutral",
            "山天大畜": "long",
            "山雷颐": "neutral",
            "泽天夬": "long",
            "天风姤": "short",
            "泽地萃": "long",
            "地泽临": "long",
            "风天小畜": "neutral",
            "风地观": "neutral",
            "风火家人": "long",
            "风山渐": "long",
            "风泽中孚": "long",
            "雷天大壮": "long",
            "雷地豫": "long",
            "震为雷": "long",
            "雷水解": "long",
            "雷火丰": "long",
            "雷山小过": "short",
            "雷泽归妹": "short",
            "水风井": "neutral",
            "火天大有": "long",
            "火地晋": "long",
            "火雷噬嗑": "long",
            "火山旅": "short",
            "火泽睽": "short",
            "山水蒙": "short",
            "山风蛊": "short",
            "山火贲": "long",
            "山泽损": "short",
            "泽水困": "short",
            "泽山咸": "long",
            "泽风大过": "short",
        }
        return HEX_TO_DIRECTION.get(hexagram_name, "")

    def _check_positions(self, coin: str) -> dict:
        """检查指定币种的持仓"""
        inst_id = f"{coin}-USDT-SWAP"
        pos_result = self.okx_client.get_positions(inst_id)
        if not pos_result.get("ok"):
            return {"has_position": False}
        positions = pos_result.get("positions", [])
        if not positions:
            return {"has_position": False}
        pos = positions[0]
        return {
            "has_position": True,
            "pos_side": pos["pos_side"],
            "pos_size": pos["pos"],
            "avg_px": pos["avg_px"],
            "upl": pos["upl"],
            "upl_ratio": pos["upl_ratio"],
            "mark_px": pos["mark_px"],
        }

    def _count_total_positions(self) -> int:
        count = 0
        for coin in self.coins:
            if self._check_positions(coin).get("has_position"):
                count += 1
        return count

    def _get_leverage(self) -> float:
        """获取当前默认杠杆倍数"""
        return float(self.okx_client.cfg.get("default_leverage", 3))

    def _roi_to_price_change(self, roi_pct: float, leverage: float = None) -> float:
        """订单收益率 → 价格涨跌幅（不含杠杆）

        公式：price_change = roi / leverage
        例子：杠杆10x、订单收益率 +5% → 价格涨跌幅 +0.5%
        """
        if leverage is None:
            leverage = self._get_leverage()
        if leverage <= 0:
            leverage = 1.0
        return roi_pct / leverage

    def _price_change_to_roi(self, price_change_pct: float, leverage: float = None) -> float:
        """价格涨跌幅（不含杠杆） → 订单收益率（含杠杆）

        公式：roi = price_change * leverage
        例子：杠杆10x、价格涨 0.5% → 订单收益率 +5%
        """
        if leverage is None:
            leverage = self._get_leverage()
        return price_change_pct * leverage

    def _calc_sl_price(
        self, entry_price: float, pos_side: str, sl_roi_pct: float, leverage: float = None
    ) -> float:
        """根据订单止损收益率计算止损价格

        Args:
            entry_price: 开仓价
            pos_side: long/short
            sl_roi_pct: 订单止损收益率（正数，如 0.03 = -3% 亏损）
            leverage: 杠杆倍数

        Returns:
            止损价格
        """
        if leverage is None:
            leverage = self._get_leverage()
        price_change = self._roi_to_price_change(sl_roi_pct, leverage)
        if pos_side == "long":
            return entry_price * (1 - price_change)
        else:
            return entry_price * (1 + price_change)

    def _calc_tp_price(
        self, entry_price: float, pos_side: str, tp_roi_pct: float, leverage: float = None
    ) -> float:
        """根据订单止盈收益率计算止盈价格

        Args:
            entry_price: 开仓价
            pos_side: long/short
            tp_roi_pct: 订单止盈收益率（正数，如 0.06 = +6% 盈利）
            leverage: 杠杆倍数

        Returns:
            止盈价格
        """
        if leverage is None:
            leverage = self._get_leverage()
        price_change = self._roi_to_price_change(tp_roi_pct, leverage)
        if pos_side == "long":
            return entry_price * (1 + price_change)
        else:
            return entry_price * (1 - price_change)

    def _handle_close_position(self, inst_id: str, coin: str,
                                pos_side: str, exit_price: float,
                                exit_reason: str, pnl: float, pnl_pct: float):
        """处理平仓：生成交易记录、更新绩效、生成 case、更新风控、增量学习

        Returns:
            trade summary dict
        """
        trade_rec = self.position_tracker.close_position(
            inst_id=inst_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )

        if trade_rec:
            perf_summary = self.perf_tracker.record_trade(trade_rec)
            self.risk_manager.update_after_trade(pnl, pnl >= 0)

            case = generate_case_from_trade(trade_rec)
            saved = save_case_to_l4(case)

            self._log(
                f"[{coin}] 平仓记录 | {'盈利' if pnl >= 0 else '亏损'} {pnl:.2f}USDT "
                f"({pnl_pct:.2%}) | case已保存={saved} | "
                f"日盈亏={perf_summary['daily_total_pnl']:.2f} "
                f"连亏={perf_summary['consecutive_losses']}"
            )

            try:
                hold_bars = 0
                if trade_rec.entry_time and trade_rec.exit_time:
                    try:
                        from datetime import datetime
                        entry_dt = datetime.fromisoformat(trade_rec.entry_time.replace('Z', '+00:00'))
                        exit_dt = datetime.fromisoformat(trade_rec.exit_time.replace('Z', '+00:00'))
                        delta = exit_dt - entry_dt
                        hold_bars = int(delta.total_seconds() / 3600)
                    except Exception:
                        pass

                trade_data = {
                    'symbol': coin,
                    'direction': trade_rec.direction,
                    'entry_time': trade_rec.entry_time,
                    'exit_time': trade_rec.exit_time,
                    'entry_price': trade_rec.entry_price,
                    'exit_price': trade_rec.exit_price,
                    'pnl_pct': trade_rec.pnl_pct,
                    'hold_bars': hold_bars,
                    'exit_reason': trade_rec.exit_reason,
                    'confidence': trade_rec.confidence,
                    'hexagram': trade_rec.hexagram,
                    'upper_gua': '',
                    'lower_gua': '',
                    'position_factor': 1.0,
                }
                n_saved = self.incremental_learner.log_trades_batch([trade_data])

                should_retrain, reason = self.incremental_learner.should_retrain(coin)
                if should_retrain:
                    self._log(f"[{coin}] 增量学习触发再训练: {reason}")
            except Exception as e:
                self._log(f"[{coin}] 增量学习记录失败: {e}", "WARN")

            retrain_result = self.learning_scheduler.trigger_retrain()
            if retrain_result.get("retrained"):
                self._log(f"[{coin}] 触发重训: {retrain_result.get('reason')}")

            # 优化4：更新置信度校准表
            # 优化5：更新卦象数据驱动校准统计
            try:
                if hasattr(self, 'ranging_enhancer') and self.ranging_enhancer:
                    enhance_info = tracker_pos.enhance_info if tracker_pos and hasattr(tracker_pos, 'enhance_info') else None
                    regime_val = enhance_info.get('regime', 'sideways') if enhance_info else 'sideways'

                    # 置信度校准
                    trade_for_cal = {
                        'confidence': trade_rec.confidence,
                        'pnl_pct': trade_rec.pnl_pct,
                        'regime': regime_val,
                        'hexagram': trade_rec.hexagram or '',
                        'direction': 'UP' if trade_rec.direction == 'long' else 'DOWN',
                    }
                    self.ranging_enhancer.update_calibration([trade_for_cal])

                    # 卦象数据驱动校准（优化5）
                    if hasattr(self.ranging_enhancer, 'hex_calibrator') and self.ranging_enhancer.hex_calibrator:
                        self.ranging_enhancer.hex_calibrator.record_trade(
                            hexagram=trade_rec.hexagram or '',
                            direction='UP' if trade_rec.direction == 'long' else 'DOWN',
                            pnl_pct=trade_rec.pnl_pct,
                            confidence=trade_rec.confidence,
                        )
            except Exception as e:
                self._log(f"[{coin}] 校准更新失败: {e}", "WARN")

            return perf_summary
        else:
            self._log(f"[{coin}] 警告：平仓但无对应开仓记录 {inst_id}", "WARN")
            return {}

    def _execute_trade(self, inference: dict, confidence_threshold: float = None):
        """根据推理结果执行交易决策（P2 完整版）"""
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        fail_closed = inference["fail_closed"]
        is_ranging = inference["is_ranging"]
        volatility = inference.get("volatility", 0.03)

        effective_threshold = confidence_threshold or self.confidence_threshold

        pos_info = self._check_positions(coin)

        if pos_info.get("has_position"):
            pos_side = pos_info["pos_side"]
            upl = pos_info.get("upl", 0)
            upl_ratio = pos_info.get("upl_ratio", 0)

            tracker_pos = self.position_tracker.get_open_position(inst_id)
            is_external = tracker_pos and tracker_pos.strategy_source == "external"

            if is_external:
                self._log(f"[{coin}] 外部策略持仓，BCRM 不干预", "INFO")
                return

            signal_reverse = (
                (pos_side == "long" and direction == "DOWN"
                 and confidence >= effective_threshold)
                or
                (pos_side == "short" and direction == "UP"
                 and confidence >= effective_threshold)
            )

            if signal_reverse:
                self._log(f"[{coin}] 信号反转 {pos_side}→{direction} | "
                          f"置信度={confidence:.2f} 卦象={inference['hexagram']} "
                          f"浮动盈亏={upl:.2f}({upl_ratio:.2%})")

                exit_price = pos_info.get("mark_px", inference["price"])
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"反转平多 conf={confidence}")
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"反转平空 conf={confidence}")

                if r.get("ok") or r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id,
                        coin=coin,
                        pos_side=pos_side,
                        exit_price=exit_price,
                        exit_reason="signal_reverse",
                        pnl=upl,
                        pnl_pct=upl_ratio,
                    )

                    risk_check = self.risk_manager.can_trade(
                        self.perf_tracker.current_equity
                    )
                    if not risk_check["allowed"]:
                        self._log(f"[{coin}] 风控拦截反手开仓: {risk_check['reason']}", "WARN")
                        return

                    total_pos = self._count_total_positions()
                    if total_pos >= self.max_positions:
                        self._log(f"[{coin}] 已达最大持仓数 {self.max_positions}，跳过反手")
                        return

                    self._open_position(inference, is_reverse=True)
                return

            # 经典指标离场系统评估（完整四大优先级）
            current_price = inference["price"]
            entry_price = pos_info.get("avg_px", 0)
            position_age_sec = 0
            open_time = pos_info.get("open_time", 0)
            if open_time > 0:
                position_age_sec = time.time() - open_time

            kline_data = inference.get("kline_data", [])
            is_ranging = inference.get("is_ranging", False)
            regime = "chop" if is_ranging else "trend"

            exit_pos = ExitPositionState(
                coin=coin,
                side=pos_side,
                entry_price=float(entry_price) if entry_price else 0,
                current_price=float(current_price),
                position_age_sec=position_age_sec,
                unrealized_pnl_pct=float(upl_ratio),
                leverage=float(self.okx_client.cfg.get("default_leverage", 3)),
                atr_pct=float(inference.get("volatility", 0.03)),
                mfe_pnl_pct=max(0.0, float(upl_ratio)),
            )

            candles_1h = None
            if kline_data and len(kline_data) >= 20:
                candles_1h = [
                    {
                        "t": c.get("ts", c.get("t", 0)),
                        "o": c.get("o", 0),
                        "h": c.get("h", 0),
                        "l": c.get("l", 0),
                        "c": c.get("c", 0),
                        "v": c.get("v", 0),
                    }
                    for c in kline_data
                ]

            # ── 主离场层：易经推理专属离场（基于卦象风险-价值评估）──
            # 架构反转：yijing 作为主决策，classic 降为备用（仅在 yijing 不可用或信号中性时调用）
            yijing_hexagram = self._infer_current_hexagram(coin, inference, kline_data)
            yijing_decision = None
            yijing_available = yijing_hexagram is not None

            if yijing_available:
                yijing_decision = self.yijing_exit_system.evaluate(
                    hexagram=yijing_hexagram,
                    pos_side=pos_side,
                    entry_price=float(entry_price) if entry_price else 0,
                    current_price=float(current_price),
                    position_age_sec=position_age_sec,
                    unrealized_pnl_pct=float(upl_ratio),
                    classic_decision=None,  # 主离场模式：不再否决 classic
                    mfe_pnl_pct=max(0.0, float(upl_ratio)),
                )

            # 1) 易经强制平仓：卦象风险极高 + 方向冲突 → 直接 close
            if yijing_decision and yijing_decision.action == YijingExitAction.FORCE_CLOSE:
                self._log(
                    f"[{coin}] 易经主离场 [FORCE_CLOSE] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} "
                    f"风险={yijing_decision.yijing_risk_score:.2f} "
                    f"价值={yijing_decision.yijing_value_score:.2f} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})")
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"易经离场:{yijing_decision.reason}")
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"易经离场:{yijing_decision.reason}")
                if r.get("ok") or r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id, coin=coin, pos_side=pos_side,
                        exit_price=current_price,
                        exit_reason=f"yijing_exit:{yijing_decision.reason}",
                        pnl=upl, pnl_pct=upl_ratio,
                    )
                return

            # 2) 易经提高止盈：价值高 + 成长期 → 上调止盈位
            # 口径：目标用"订单止盈收益率"定义，再通过 leverage 换算成价格
            if yijing_decision and yijing_decision.action == YijingExitAction.RAISE_TP:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                tp_uplift = yijing_decision.tp_adjust_pct
                target_tp_roi_pct = tp_uplift * 0.5  # 订单止盈收益率（30%×0.5=15%）
                new_tp_price = self._calc_tp_price(
                    entry_price, pos_side, target_tp_roi_pct, leverage
                )
                tp_price_change_pct = self._roi_to_price_change(target_tp_roi_pct, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [RAISE_TP] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"目标订单收益率={target_tp_roi_pct:.2%} 需价格涨幅={tp_price_change_pct:.2%} "
                    f"新止盈={new_tp_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})")
                try:
                    tp_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=None,
                        take_profit_px=new_tp_price,
                        reason=f"yijing_raise_tp:{yijing_decision.reason}",
                    )
                    if tp_result.get("ok"):
                        self._log(f"[{coin}] 易经止盈价已上调至 {new_tp_price:.2f}")
                    else:
                        self._log(f"[{coin}] 易经上调止盈失败: {tp_result.get('error', 'unknown')}", "WARN")
                except Exception as e:
                    self._log(f"[{coin}] 易经上调止盈异常: {e}", "WARN")
                return

            # 3) 易经降低止损：风险低 + 趋势初期 → 放宽止损空间，避免被洗出去
            # 口径：基础订单止损收益率 -2%，放宽 50% → 允许订单亏损 -3%
            if yijing_decision and yijing_decision.action == YijingExitAction.LOWER_SL:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                sl_relax_pct = yijing_decision.sl_adjust_pct
                base_sl_roi_pct = 0.02  # 基础订单止损收益率 -2%
                new_sl_roi_pct = base_sl_roi_pct * (1 + sl_relax_pct)  # 放宽 50% → -3%
                new_sl_price = self._calc_sl_price(
                    entry_price, pos_side, new_sl_roi_pct, leverage
                )
                sl_price_change_pct = self._roi_to_price_change(new_sl_roi_pct, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [LOWER_SL] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"新订单止损={new_sl_roi_pct:.2%}(价{sl_price_change_pct:.2%}) "
                    f"新止损={new_sl_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})")
                try:
                    sl_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=new_sl_price,
                        take_profit_px=None,
                        reason=f"yijing_lower_sl:{yijing_decision.reason}",
                    )
                    if sl_result.get("ok"):
                        self._log(f"[{coin}] 易经止损价已放宽至 {new_sl_price:.2f}")
                    else:
                        self._log(f"[{coin}] 易经放宽止损失败: {sl_result.get('error', 'unknown')}", "WARN")
                except Exception as e:
                    self._log(f"[{coin}] 易经放宽止损异常: {e}", "WARN")
                return

            # 4) 易经降低止盈：风险升高 + 已有利润 → 提前锁定利润
            # 口径：用"订单止盈收益率"定义新止盈位（不下调太狠，仍有利润空间）
            if yijing_decision and yijing_decision.action == YijingExitAction.LOWER_TP:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                tp_adjust_pct = abs(yijing_decision.tp_adjust_pct)
                target_tp_roi_pct = tp_adjust_pct * 0.3  # 订单止盈收益率 30%×0.3=9%
                new_tp_price = self._calc_tp_price(
                    entry_price, pos_side, target_tp_roi_pct, leverage
                )
                tp_price_change_pct = self._roi_to_price_change(target_tp_roi_pct, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [LOWER_TP] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"新订单止盈={target_tp_roi_pct:.2%}(价{tp_price_change_pct:.2%}) "
                    f"新止盈={new_tp_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})")
                try:
                    tp_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=None,
                        take_profit_px=new_tp_price,
                        reason=f"yijing_lower_tp:{yijing_decision.reason}",
                    )
                    if tp_result.get("ok"):
                        self._log(f"[{coin}] 易经止盈价已下调至 {new_tp_price:.2f}")
                    else:
                        self._log(f"[{coin}] 易经下调止盈失败: {tp_result.get('error', 'unknown')}", "WARN")
                except Exception as e:
                    self._log(f"[{coin}] 易经下调止盈异常: {e}", "WARN")
                return

            # 5) 易经主决策 HOLD：风险低 + 价值高 + 方向一致 + 未破阈值 → 维持持仓
            #    （卦象信号良好，无需调用 classic 备用层）
            if yijing_decision and yijing_decision.action == YijingExitAction.NO_INTERVENE:
                cfg_yijing = self.yijing_exit_system.config
                risk_low = yijing_decision.yijing_risk_score < cfg_yijing.veto_risk_threshold
                value_high = yijing_decision.yijing_value_score > cfg_yijing.veto_value_threshold
                loss_acceptable = float(upl_ratio) > cfg_yijing.veto_max_loss_pct
                not_expired = position_age_sec < cfg_yijing.veto_max_hold_sec

                if (risk_low and value_high and yijing_decision.direction_consistent
                        and loss_acceptable and not_expired):
                    self._log(
                        f"[{coin}] 易经主离场 [HOLD] 卦象信号良好 | "
                        f"卦象={yijing_decision.hexagram_name} "
                        f"风险={yijing_decision.yijing_risk_score:.2f} "
                        f"价值={yijing_decision.yijing_value_score:.2f} "
                        f"阶段={yijing_decision.current_phase or '-'} "
                        f"方向一致={yijing_decision.direction_consistent} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h "
                        f"行情={regime} | 维持持仓")
                    return
                # 卦象信号中性或风险偏高 → 降级 classic 评估
                self._log(
                    f"[{coin}] 易经信号中性，降级经典备用离场 | "
                    f"卦象={yijing_decision.hexagram_name} "
                    f"风险={yijing_decision.yijing_risk_score:.2f} "
                    f"价值={yijing_decision.yijing_value_score:.2f} "
                    f"方向一致={yijing_decision.direction_consistent} "
                    f"盈亏={upl_ratio:.2%} 持仓={position_age_sec/3600:.1f}h")
            elif not yijing_available:
                self._log(
                    f"[{coin}] 易经卦象不可用，启用经典离场备用层 | "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})", "WARN")

            # ── 备用离场层：经典指标离场（yijing 不可用 或 信号中性时调用）──
            # 短期修复 2：震荡市动态放宽止损（is_ranging / 弱趋势 → 止损更宽）
            # 注意：传入 dict（含 is_ranging/adx/trend_strength），而非字符串 regime
            self._adjust_exit_config_for_regime({
                "is_ranging": is_ranging,
                "adx": float(inference.get("adx", 0) or 0),
                "trend_strength": inference.get("trend_strength", 0.5),
            })

            exit_decision = self.exit_system.evaluate_full(
                pos=exit_pos,
                candles_1h=candles_1h,
                regime=regime,
            )

            # VETO_CLOSE/VETO_REDUCE 检查：classic 决定离场前，易经二次评估可否决
            # （易经主离场已判定为 NO_INTERVENE，但仍可否决 classic 的噪音止损）
            if (yijing_available and yijing_decision
                    and exit_decision.action in (ExitAction.CLOSE, ExitAction.REDUCE)):
                veto_decision = self.yijing_exit_system.evaluate(
                    hexagram=yijing_hexagram,
                    pos_side=pos_side,
                    entry_price=float(entry_price) if entry_price else 0,
                    current_price=float(current_price),
                    position_age_sec=position_age_sec,
                    unrealized_pnl_pct=float(upl_ratio),
                    classic_decision=exit_decision,  # 传入 classic 决策用于否决判断
                    mfe_pnl_pct=max(0.0, float(upl_ratio)),
                )
                if veto_decision.action == YijingExitAction.VETO_CLOSE:
                    self._log(
                        f"[{coin}] 易经否决 [VETO_CLOSE] {veto_decision.reason} | "
                        f"卦象={veto_decision.hexagram_name} "
                        f"风险={veto_decision.yijing_risk_score:.2f} "
                        f"价值={veto_decision.yijing_value_score:.2f} "
                        f"经典离场原因={exit_decision.reason} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h | "
                        f"否决 classic 离场，维持持仓")
                    return
                if veto_decision.action == YijingExitAction.VETO_REDUCE:
                    self._log(
                        f"[{coin}] 易经否决 [VETO_REDUCE] {veto_decision.reason} | "
                        f"卦象={veto_decision.hexagram_name} "
                        f"风险={veto_decision.yijing_risk_score:.2f} "
                        f"价值={veto_decision.yijing_value_score:.2f} "
                        f"经典减仓原因={exit_decision.reason} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) | "
                        f"否决 classic 减仓，维持持仓")
                    return

            # 执行 classic 决策
            if exit_decision.action == ExitAction.CLOSE:
                self._log(
                    f"[{coin}] 经典备用离场 [CLOSE] {exit_decision.reason} | "
                    f"优先级={exit_decision.priority.value} "
                    f"置信度={exit_decision.confidence:.2f} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})")
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"经典备用离场:{exit_decision.reason}")
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"经典备用离场:{exit_decision.reason}")
                if r.get("ok") or r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id, coin=coin, pos_side=pos_side,
                        exit_price=current_price,
                        exit_reason=f"classic_backup:{exit_decision.reason}",
                        pnl=upl, pnl_pct=upl_ratio,
                    )
                return

            if exit_decision.action == ExitAction.REDUCE:
                self._log(
                    f"[{coin}] 经典备用离场 [REDUCE] {exit_decision.reason} | "
                    f"减仓比例={exit_decision.reduce_frac:.0%} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})")
                reduce_result = self.okx_client.reduce_position(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    reduce_ratio=exit_decision.reduce_frac,
                    reason=f"classic_backup:{exit_decision.reason}",
                )
                if reduce_result.get("ok"):
                    self._log(
                        f"[{coin}] 减仓成功 | "
                        f"原持仓={reduce_result.get('original_pos')} "
                        f"减仓量={reduce_result.get('reduce_sz')} "
                        f"剩余={reduce_result.get('remaining_pos')}")
                else:
                    self._log(f"[{coin}] 减仓失败: {reduce_result.get('error', 'unknown')}", "WARN")
                return

            if exit_decision.action == ExitAction.RAISE_TP:
                new_tp_price = exit_decision.new_tp_price
                new_tp_pct = exit_decision.new_tp_pct
                self._log(
                    f"[{coin}] 经典备用离场 [RAISE_TP] {exit_decision.reason} | "
                    f"新止盈={new_tp_price:.2f}({new_tp_pct:.2%}) "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})")
                try:
                    tp_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=None,
                        take_profit_px=new_tp_price,
                        reason=f"raise_tp_backup:{exit_decision.reason}",
                    )
                    if tp_result.get("ok"):
                        self._log(f"[{coin}] 止盈价已上调至 {new_tp_price:.2f}")
                    else:
                        self._log(f"[{coin}] 上调止盈失败: {tp_result.get('error', 'unknown')}", "WARN")
                except Exception as e:
                    self._log(f"[{coin}] 上调止盈异常: {e}", "WARN")
                return

            # 维持持仓日志（含易经风险评估）
            hold_risk = (exit_decision.features.hold_risk if exit_decision and exit_decision.features else 0.5)
            hold_value = (exit_decision.features.hold_value if exit_decision and exit_decision.features else 0.5)
            yijing_risk = yijing_decision.yijing_risk_score if yijing_decision else 0.5
            yijing_value = yijing_decision.yijing_value_score if yijing_decision else 0.5
            hex_display = (yijing_decision.hexagram_name if yijing_decision else "无卦象") or "无卦象"
            yijing_phase = (yijing_decision.current_phase if yijing_decision else "") or "-"
            self._log(
                f"[{coin}] 持仓中 {pos_side} | "
                f"浮动盈亏={upl:.2f}({upl_ratio:.2%}) | "
                f"卦象={hex_display} 易经风险={yijing_risk:.2f} 易经价值={yijing_value:.2f} "
                f"阶段={yijing_phase} "
                f"持有风险={hold_risk:.2f} 持有价值={hold_value:.2f} "
                f"行情={regime} | 维持持仓")
            return

        trend_strength = inference.get("trend_strength", 0.5)
        ranging_confidence = inference.get("ranging_confidence", 0.0)
        is_trial = False

        # ===== 震荡市增强器（优化1-5统一入口）=====
        # 包含：
        #   优化1: MA200方向性偏向 + 阻力支撑确认
        #   优化2: 布林带双信号确认
        #   优化3: 动态止损宽度（震荡市2.5-3×ATR）
        #   优化4: 置信度校准（框架，数据积累后生效）
        #   优化5: 5种市场状态自适应
        enhance_result = None
        kline_data = inference.get("kline_data", [])
        if kline_data and len(kline_data) >= 20:
            try:
                closes = [float(c.get('c', 0)) for c in kline_data if c.get('c')]
                highs = [float(c.get('h', 0)) for c in kline_data if c.get('h')]
                lows = [float(c.get('l', 0)) for c in kline_data if c.get('l')]
                price = float(inference.get("price", 0))
                vol = inference.get("volatility", 0.03)
                atr_val = price * vol if price > 0 else 0

                if len(closes) >= 20 and price > 0:
                    enhance_result = self.ranging_enhancer.enhance(
                        price=price,
                        direction=direction,
                        confidence=confidence,
                        closes=closes,
                        highs=highs if len(highs) == len(closes) else None,
                        lows=lows if len(lows) == len(closes) else None,
                        atr=atr_val,
                        is_ranging=is_ranging,
                        ranging_confidence=ranging_confidence,
                        trend_strength=trend_strength,
                        coin=coin,
                    )
            except Exception as e:
                self._log(f"[{coin}] 增强器调用异常: {e}，回退到P0简单逻辑", "WARN")

        if enhance_result:
            # 记录市场状态
            regime_label = enhance_result.regime.value
            boll_sig = enhance_result.bollinger.signal.value
            self._log(
                f"[{coin}] 增强器 | 状态={regime_label} "
                f"布林信号={boll_sig} "
                f"偏向={enhance_result.directional_bias:+.2f} "
                f"止损={enhance_result.recommended_sl_atr_mult:.1f}×ATR"
            )

            # 保存增强结果到inference，供开仓时使用（动态止损）
            inference["enhance_result"] = {
                "regime": regime_label,
                "sl_atr_mult": enhance_result.recommended_sl_atr_mult,
                "tp_atr_mult": enhance_result.recommended_tp_atr_mult,
                "bollinger_signal": boll_sig,
                "bollinger_confirms": enhance_result.bollinger_confirms,
                "directional_bias": enhance_result.directional_bias,
                "ma200_above": enhance_result.mas.price_above_ma200,
            }

            # 更新有效阈值（增强器推荐的方向差异化阈值）
            if direction == "UP":
                effective_threshold = max(effective_threshold, enhance_result.recommended_long_threshold)
            elif direction == "DOWN":
                effective_threshold = max(effective_threshold, enhance_result.recommended_short_threshold)

            # 综合判断：是否应该开仓
            if not enhance_result.should_trade:
                self._log(
                    f"[{coin}] 增强器过滤 | 原因={enhance_result.reject_reason} "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return
        else:
            # ===== 回退：P0简单逻辑（当增强器不可用时）=====
            if is_ranging and ranging_confidence >= 0.75:
                self._log(
                    f"[{coin}] P0-强震荡市强制空仓 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return
            elif is_ranging and ranging_confidence >= 0.5:
                effective_threshold = max(effective_threshold, 0.7)
                self._log(
                    f"[{coin}] P0-中震荡市 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度要求提高至 {effective_threshold}"
                )
            elif is_ranging:
                effective_threshold = max(effective_threshold, 0.6)
                self._log(
                    f"[{coin}] P0-弱震荡市 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度要求提高至 {effective_threshold}"
                )
            elif trend_strength > 0.6:
                effective_threshold = max(0.3, self.confidence_threshold - 0.1)
                self._log(f"[{coin}] 趋势明确(强度={trend_strength:.2f}) | 置信度要求放宽至 {effective_threshold}")

        if fail_closed:
            # P0修复: fail-closed 硬约束，BCRM判定不交易则直接跳过，不用八卦方向软化
            bagua_dir = inference.get("bagua_direction", "neutral")
            self._log(
                f"[{coin}] fail-closed 跳过 | 卦象={inference['hexagram']} "
                f"BCRM不确定，不开仓 (八卦方向={bagua_dir} 不作为开仓依据)"
            )
            return

        trial_threshold = max(0.25, effective_threshold - 0.15)
        if confidence >= effective_threshold:
            pass
        elif confidence >= trial_threshold:
            is_trial = True
            self._log(f"[{coin}] 轻仓试错模式 | 置信度={confidence:.2f} 在试错区间 [{trial_threshold}, {effective_threshold})")
        else:
            self._log(f"[{coin}] 置信度不足 "
                      f"{confidence:.2f} < {trial_threshold} | "
                      f"方向={direction} 卦象={inference['hexagram']}")
            return

        if direction not in ("UP", "DOWN"):
            self._log(f"[{coin}] 方向不明确 {direction} 跳过")
            return

        risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
        if not risk_check["allowed"]:
            self._log(f"[{coin}] 风控拦截: {risk_check['reason']}", "WARN")
            return

        if self._count_total_positions() >= self.max_positions:
            self._log(f"[{coin}] 已达最大持仓数 {self.max_positions} 跳过")
            return

        self._open_position(inference, is_reverse=False, is_trial=is_trial)

    def _open_position(self, inference: dict, is_reverse: bool = False, is_trial: bool = False):
        """开仓（动态仓位 + 持仓跟踪）"""
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        volatility = inference.get("volatility", 0.03)

        leverage = self.okx_client.cfg.get("default_leverage", 3)
        td_mode = self.okx_client.cfg.get("td_mode", "isolated")
        balance = self.okx_client.get_balance()
        
        available_equity = self.perf_tracker.current_equity
        if balance.get("ok"):
            avail_usdt = balance.get("assets", {}).get("USDT", {}).get("avail", 0)
            if td_mode == "isolated":
                available_equity = avail_usdt
            else:
                total_eq = balance.get("total_eq", 0)
                pos_result = self.okx_client.get_positions()
                total_imr = 0
                if pos_result.get("ok"):
                    for p in pos_result.get("positions", []):
                        if float(p.get("pos", 0)) > 0:
                            total_imr += float(p.get("imr", 0))
                available_equity = total_eq - total_imr

        pos_size_info = self.risk_manager.calc_position_size(
            confidence=confidence,
            volatility=volatility,
            current_equity=available_equity,
        )
        position_usdt = pos_size_info["position_usdt"]
        position_pct = pos_size_info["position_pct"]

        if is_trial:
            position_usdt *= 0.4
            position_pct *= 0.4

        action = "open_long" if direction == "UP" else "open_short"
        pos_side = "long" if direction == "UP" else "short"
        sl_px = inference["stop_loss_px"]
        tp_px = inference["take_profit_px"]
        price = inference["price"]

        # 优化3：动态止损宽度（如果增强器有推荐，覆盖默认值）
        # 关键口径：先按"订单收益率"定义，再通过 leverage 换算成价格
        #   ATR 倍数（市场态）→ 价格波动% → 订单收益率% = 价格波动% × leverage
        enhance_info = inference.get("enhance_result")
        if enhance_info and price > 0 and volatility > 0:
            sl_mult = enhance_info.get("sl_atr_mult", 1.5)
            tp_mult = enhance_info.get("tp_atr_mult", 3.0)
            atr_val = price * volatility
            if sl_mult != 1.5 or tp_mult != 3.0:
                # 1) 先按"订单收益率"定义：1.5×ATR → 价格波动 sl_mult×volatility
                #    对应订单止损收益率 = sl_mult × volatility × leverage
                sl_price_change_pct = sl_mult * volatility
                tp_price_change_pct = tp_mult * volatility
                sl_roi_pct = self._price_change_to_roi(sl_price_change_pct, leverage)
                tp_roi_pct = self._price_change_to_roi(tp_price_change_pct, leverage)
                # 2) 由订单收益率 + 入场价反推止损止盈价
                if direction == "UP":
                    new_sl = self._calc_sl_price(price, "long", sl_roi_pct, leverage)
                    new_tp = self._calc_tp_price(price, "long", tp_roi_pct, leverage)
                else:
                    new_sl = self._calc_sl_price(price, "short", sl_roi_pct, leverage)
                    new_tp = self._calc_tp_price(price, "short", tp_roi_pct, leverage)
                if new_sl > 0 and new_tp > 0:
                    old_sl_pct = abs(sl_px - price) / price * 100 if sl_px else 0
                    new_sl_pct = abs(new_sl - price) / price * 100
                    sl_px = new_sl
                    tp_px = new_tp
                    self._log(
                        f"[{coin}] 动态止损 | {enhance_info.get('regime','')} "
                        f"杠杆={leverage}x "
                        f"SL={sl_mult:.1f}×ATR(订单亏{sl_roi_pct:.2%}/价格{sl_price_change_pct:.2%}) "
                        f"TP={tp_mult:.1f}×ATR(订单盈{tp_roi_pct:.2%}/价格{tp_price_change_pct:.2%}) "
                        f"(原SL={old_sl_pct:.1f}%)"
                    )

        # 输出：换算订单收益率（杠杆×价格波动%）
        if price > 0 and leverage > 0 and sl_px and tp_px:
            sl_pct = abs(sl_px - price) / price
            tp_pct = abs(tp_px - price) / price
            sl_roi = self._price_change_to_roi(sl_pct, leverage)
            tp_roi = self._price_change_to_roi(tp_pct, leverage)
            if pos_side == "long":
                sl_label = f"亏{sl_roi:.2%}(价{sl_pct:.2%})"
                tp_label = f"盈{tp_roi:.2%}(价{tp_pct:.2%})"
            else:
                sl_label = f"亏{sl_roi:.2%}(价{sl_pct:.2%})"
                tp_label = f"盈{tp_roi:.2%}(价{tp_pct:.2%})"
            self._log(
                f"[{coin}] {'反手' if is_reverse else ''}开仓 {'[轻仓试错]' if is_trial else ''} {action} | "
                f"置信度={confidence:.2f} 卦象={inference['hexagram']} 杠杆={leverage}x | "
                f"仓位={position_usdt:.2f}USDT ({position_pct:.1%}) | "
                f"价格={inference['price']} SL={sl_px}({sl_label}) TP={tp_px}({tp_label}) | "
                f"原因={pos_size_info['reason']} | "
                f"可用余额={available_equity:.2f}USDT"
            )
        else:
            self._log(
                f"[{coin}] {'反手' if is_reverse else ''}开仓 {'[轻仓试错]' if is_trial else ''} {action} | "
                f"置信度={confidence:.2f} 卦象={inference['hexagram']} 杠杆={leverage}x | "
                f"仓位={position_usdt:.2f}USDT ({position_pct:.1%}) | "
                f"价格={inference['price']} 止损={sl_px} 止盈={tp_px} | "
                f"原因={pos_size_info['reason']} | "
                f"可用余额={available_equity:.2f}USDT"
            )

        margin_needed = position_usdt / leverage
        
        if balance.get("ok"):
            total_eq = balance.get("total_eq", 0)
            avail_usdt = balance.get("assets", {}).get("USDT", {}).get("avail", 0)
            
            if td_mode == "isolated":
                if margin_needed > avail_usdt:
                    self._log(f"[{coin}] 可用保证金不足（逐仓） | 需要={margin_needed:.2f}USDT 可用={avail_usdt:.2f}USDT 总权益={total_eq:.2f}USDT 杠杆={leverage}x 跳过", "WARN")
                    return
            else:
                pos_result = self.okx_client.get_positions()
                total_imr = 0
                if pos_result.get("ok"):
                    for p in pos_result.get("positions", []):
                        if float(p.get("pos", 0)) > 0:
                            total_imr += float(p.get("imr", 0))
                
                cross_available = total_eq - total_imr
                
                if margin_needed > cross_available:
                    self._log(f"[{coin}] 可用保证金不足（全仓） | 需要={margin_needed:.2f}USDT 可用={cross_available:.2f}USDT 总权益={total_eq:.2f}USDT 已用IMR={total_imr:.2f}USDT 杠杆={leverage}x 跳过", "WARN")
                    return

        # 检查下单量是否满足最小合约单位
        sz = self.okx_client._usdt_to_sz(inst_id, position_usdt)
        if sz <= 0:
            self._log(f"[{coin}] 下单量不足最小合约单位 | 金额={position_usdt:.2f}USDT 跳过", "WARN")
            return

        if direction == "UP":
            order_result = self.okx_client.market_open_long(
                inst_id, usdt_amount=position_usdt,
                reason=f"yijing_open_long conf={confidence:.2f}")
        else:
            order_result = self.okx_client.market_open_short(
                inst_id, usdt_amount=position_usdt,
                reason=f"yijing_open_short conf={confidence:.2f}")

        ok = order_result.get("ok", False)
        ord_id = order_result.get("ord_id", "") or order_result.get("ordId", "")
        entry_price = order_result.get("estimated_price", inference["price"])

        if ok or order_result.get("dry_run"):
            self.position_tracker.open_position(
                coin=coin,
                inst_id=inst_id,
                direction=pos_side,
                entry_price=entry_price,
                confidence=confidence,
                hexagram=inference["hexagram"],
                liangyi_state=inference.get("liangyi_state"),
                scale_params=inference.get("scale_params"),
                market_snapshot=inference.get("snapshot"),
                contradiction_list=inference.get("contradictions"),
                enhance_info=inference.get("enhance_result"),
            )
            self._log(f"[{coin}] 开仓成功 | ordId={ord_id} | "
                      f"入场价≈{entry_price}")

            if sl_px and tp_px:
                sltp_result = self.okx_client.place_stop_loss_take_profit(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    stop_loss_px=sl_px,
                    take_profit_px=tp_px,
                    reason="yijing_risk_management",
                )
                if sltp_result.get("ok"):
                    self._log(f"[{coin}] 止盈止损已设置 | SL={sl_px} TP={tp_px}")
        else:
            err = order_result.get("error", "") or order_result.get("sMsg", "")
            self._log(f"[{coin}] 开仓失败 | {err}", "ERROR")
            if self.guardian:
                self.guardian.record_error(RuntimeError(f"开仓失败: {err}"),
                                           context=f"open_position:{coin}")

    def _load_external_knowledge(self):
        """加载 AB Trading 导出的外部知识"""
        try:
            self.external_knowledge = self.knowledge_bridge.get_knowledge_summary()
            if self.external_knowledge["evolved_params_count"] > 0:
                self._log(
                    f"[外部知识] 已加载 {self.external_knowledge['evolved_params_count']} 个进化参数 | "
                    f"灵敏度={self.external_knowledge['trend_sensitivity']:.2f} | "
                    f"风险厌恶={self.external_knowledge['risk_aversion']:.2f} | "
                    f"市场倾向={self.external_knowledge['market_bias']}"
                )
        except Exception as e:
            self._log(f"[外部知识] 加载失败: {e}", "ERROR")
            self.external_knowledge = {}

    def _infer_current_hexagram(self, coin: str, inference: dict, kline_data: list):
        """离场时推理当前卦象（轻量级，复用 YijingEngine）

        用 inference 中已有的技术指标作为四维评分的简化输入：
        - technical_score = trend_strength（趋势强度）
        - supply_demand_score = 用价格位置近似
        - capital_flow_score = 用成交量比近似
        - sentiment_score = 用 confidence + is_ranging 反向近似

        失败时返回 None（YijingExitSystem 会 fail-open 不干预）
        """
        try:
            from scripts.memory_l4.bcrm.yijing_engine import YijingEngine
            if not hasattr(self, "_yijing_engine_for_exit"):
                self._yijing_engine_for_exit = YijingEngine()

            # 从 inference 提取可用字段
            trend_strength = float(inference.get("trend_strength", 0.5) or 0.5)
            volatility = float(inference.get("volatility", 0.03) or 0.03)
            confidence = float(inference.get("confidence", 0.5) or 0.5)
            is_ranging = bool(inference.get("is_ranging", False))
            current_price = float(inference.get("price", 0) or 0)

            # 简化四维评分
            technical_score = max(0.0, min(1.0, trend_strength))
            supply_demand_score = 0.5  # 中性，离场时不重算供需
            capital_flow_score = 0.5   # 中性
            # 情绪面：confidence 高=乐观；震荡市=情绪混乱
            sentiment_score = max(0.0, min(1.0, confidence * 0.7 + (0.3 if not is_ranging else 0.1)))

            # 波动率归一化（0-1）
            vol_norm = max(0.0, min(1.0, volatility * 20))

            # 价格位置（从 kline_data 简单计算）
            price_position = 0.5
            if kline_data and len(kline_data) >= 20 and current_price > 0:
                try:
                    closes = [float(c.get("c", 0)) for c in kline_data[-20:]]
                    if closes and max(closes) > min(closes):
                        price_position = (current_price - min(closes)) / (max(closes) - min(closes))
                        price_position = max(0.0, min(1.0, price_position))
                except Exception:
                    pass

            result = self._yijing_engine_for_exit.infer(
                supply_demand_score=supply_demand_score,
                technical_score=technical_score,
                capital_flow_score=capital_flow_score,
                sentiment_score=sentiment_score,
                trend_strength=trend_strength,
                volatility=vol_norm,
                volume_ratio=1.0,
                price_position=price_position,
                close_price=current_price,
            )
            return result
        except Exception as e:
            self._log(f"[{coin}] 离场卦象推理失败: {e}", "WARN")
            return None

    def _adjust_exit_config_for_regime(self, regime: dict):
        """短期修复 2：根据市场状态动态调整 ExitConfig

        - 震荡市（is_ranging=true / 弱趋势）：止损放宽到 5%，跟踪回撤 3.5% → 4%
        - 趋势市：恢复基准配置（4.5% / 3.5%）
        """
        if not regime or not hasattr(self, "_exit_cfg_base"):
            return
        try:
            is_ranging = bool(regime.get("is_ranging", False))
            # 弱趋势判定：adx < 20 或 trend_strength 为 weak/range
            adx = float(regime.get("adx", 0) or 0)
            trend_strength = str(regime.get("trend_strength", "")).lower()
            weak_trend = (adx < 20) or (trend_strength in ("weak", "range", "ranging"))

            cfg = self.exit_system.config
            if is_ranging or weak_trend:
                # 震荡市：放宽止损
                if cfg.tb_sl_min_pct != 0.05:
                    cfg.tb_sl_min_pct = 0.05
                    cfg.trailing_retrace_pct = 0.04
                    self._log(
                        f"[离场动态调整] 震荡市(is_ranging={is_ranging},adx={adx:.1f}) "
                        f"→ tb_sl_min=5% trailing_retrace=4%"
                    )
            else:
                # 趋势市：恢复基准
                if cfg.tb_sl_min_pct != self._exit_cfg_base.tb_sl_min_pct:
                    cfg.tb_sl_min_pct = self._exit_cfg_base.tb_sl_min_pct
                    cfg.trailing_retrace_pct = self._exit_cfg_base.trailing_retrace_pct
                    self._log(
                        f"[离场动态调整] 趋势市恢复基准 "
                        f"→ tb_sl_min={cfg.tb_sl_min_pct:.1%} trailing_retrace={cfg.trailing_retrace_pct:.1%}"
                    )
        except Exception as e:
            self._log(f"[离场动态调整失败] {e}")

    def _adjust_confidence_threshold(self) -> float:
        """根据外部知识调整置信度阈值"""
        base_threshold = self.confidence_threshold

        if self.external_knowledge.get("risk_aversion", 0.5) > 0.8:
            adjusted = base_threshold + 0.05
            self._log(f"[外部知识] 风险厌恶高，置信度阈值提高至 {adjusted:.2f}")
            return adjusted

        if self.external_knowledge.get("market_bias") == "bear":
            adjusted = base_threshold + 0.03
            self._log(f"[外部知识] 熊市环境，置信度阈值提高至 {adjusted:.2f}")
            return adjusted

        return base_threshold

    def run_once(self):
        """执行一轮推理 + 交易"""
        self._check_date_rollover()
        self._load_external_knowledge()
        self.cycle_count += 1
        self._log(f"═══ 轮询 #{self.cycle_count} 开始 ═══")

        risk_state = self.risk_manager.get_state()
        perf_stats = self.perf_tracker.get_today_stats()
        self._log(
            f"[状态] 日盈亏={risk_state['daily_pnl']:.2f} | "
            f"连亏={risk_state['consecutive_losses']}/{risk_state['max_consecutive_losses']} | "
            f"交易暂停={risk_state['trading_halted']} | "
            f"今日交易={perf_stats.get('total_trades', 0)}笔"
        )

        effective_threshold = self._adjust_confidence_threshold()

        # 异常检测 (Phase 2.1)
        anomaly_detected = False
        anomaly_coins = []
        try:
            for coin in self.coins:
                kline_data = _load_kline_from_okx(
                    inst_id=f"{coin}-USDT-SWAP", bar=self.bar, limit=self.kline_limit)
                if kline_data and len(kline_data) > 100:
                    import pandas as pd
                    df = pd.DataFrame(kline_data)
                    df['timestamp'] = pd.to_datetime(df['ts'], unit='ms')
                    df.set_index('timestamp', inplace=True)
                    df.rename(columns={'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}, inplace=True)

                    summary = self.anomaly_detector.get_summary(df, symbol=coin)
                    critical_count = summary['by_severity'].get('critical', 0)
                    high_count = summary['by_severity'].get('high', 0)

                    if critical_count > 0 or high_count >= 2:
                        anomaly_detected = True
                        anomaly_coins.append(coin)
                        self._log(f"[异常检测] {coin}: 检测到 {critical_count} 个严重异常, {high_count} 个高等级异常")

            if anomaly_detected:
                self._log(f"[异常检测] 市场环境异常，提高风控等级 | 涉及币种: {anomaly_coins}")
                effective_threshold = min(0.8, effective_threshold + 0.15)
        except Exception as e:
            self._log(f"[异常检测] 检测失败: {e}", "WARN")

        cycle_success = True
        for coin in self.coins:
            try:
                inference = self._fetch_and_infer(coin)
                if not inference.get("ok"):
                    self._log(f"[{coin}] 推理失败: {inference.get('error')}", "ERROR")
                    cycle_success = False
                    continue

                self._log(
                    f"[{coin}] 价格={inference['price']} | "
                    f"卦象={inference['hexagram']} | "
                    f"方向={inference['direction']} | "
                    f"置信度={inference['confidence']:.2f} | "
                    f"八卦={inference['bagua_direction']}({inference['bagua_confidence']:.2f}) | "
                    f"震荡={inference['is_ranging']} | "
                    f"波动率={inference.get('volatility', 0):.4f} | "
                    f"fail={inference['fail_closed']}"
                )

                self._execute_trade(inference, confidence_threshold=effective_threshold)

            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle:{coin}")

        open_pos = self.position_tracker.all_open_positions()
        self._log(f"[持仓跟踪] 记录中持仓数: {len(open_pos)}")
        for pos in open_pos:
            self._log(f"  - {pos.coin}: {pos.direction} @ {pos.entry_price} "
                      f"(conf={pos.confidence:.2f})")

        learn_state = self.learning_scheduler.get_state()
        self._log(f"[学习] 当前案例={learn_state['current_case_count']} | "
                  f"新增自上次重训={learn_state['new_cases_since']} | "
                  f"上次重训={learn_state['last_retrain_time_str']}")

        if self.guardian:
            self.guardian.record_heartbeat(
                status="running",
                cycle_count=self.cycle_count,
            )
            if cycle_success:
                self.guardian.record_success()

        self._log(f"═══ 轮询 #{self.cycle_count} 结束 ═══\n")

    def run_loop(self):
        """主轮询循环"""
        self.running = True
        cfg = self.okx_client.cfg
        self._log(
            f"轮询交易器启动 | "
            f"间隔={self.interval}s 币种={self.coins} 周期={self.bar} | "
            f"置信度阈值={self.confidence_threshold} 最大持仓={self.max_positions} | "
            f"dry_run={cfg.get('dry_run')} simulated={cfg.get('simulated')}"
        )
        self._log(
            f"[风控] 日亏损上限={self.risk_manager.state.daily_loss_limit}USDT | "
            f"最大连续亏损={self.risk_manager.state.max_consecutive_losses} | "
            f"默认仓位={self.risk_manager.state.position_size_pct:.1%}"
        )
        self._log(
            f"[绩效] 初始权益={self.perf_tracker.initial_equity} | "
            f"当前权益={self.perf_tracker.current_equity:.2f} | "
            f"历史交易={self.perf_tracker.get_overall_stats()['total_trades']}笔"
        )

        def _shutdown(signum, frame):
            self._log("收到退出信号，正在停止...", "WARN")
            self.running = False

        signal_module.signal(signal_module.SIGINT, _shutdown)
        signal_module.signal(signal_module.SIGTERM, _shutdown)

        while self.running:
            try:
                self.run_once()
            except Exception as e:
                self._log(f"轮询异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context="main_loop")

            if not self.running:
                break

            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)

        if self.guardian:
            self.guardian.stop()
        self._log("轮询交易器已停止")

    def get_status(self) -> dict:
        """获取完整运行状态（供 API 查询）"""
        return {
            "cycle_count": self.cycle_count,
            "running": self.running,
            "interval": self.interval,
            "coins": self.coins,
            "bar": self.bar,
            "confidence_threshold": self.confidence_threshold,
            "max_positions": self.max_positions,
            "risk": self.risk_manager.get_state(),
            "performance_today": self.perf_tracker.get_today_stats(),
            "performance_overall": self.perf_tracker.get_overall_stats(),
            "open_positions": [
                {
                    "coin": p.coin,
                    "inst_id": p.inst_id,
                    "direction": p.direction,
                    "entry_price": p.entry_price,
                    "confidence": p.confidence,
                    "hexagram": p.hexagram,
                    "entry_time": p.entry_time,
                }
                for p in self.position_tracker.all_open_positions()
            ],
            "learning": self.learning_scheduler.get_state(),
            "guardian": self.guardian.get_status() if self.guardian else {},
        }


def main():
    parser = argparse.ArgumentParser(description="易经推理轮询交易器（P2 完整版）")
    parser.add_argument("--interval", type=int, default=3600,
                        help="轮询间隔（秒），默认 3600(1h)")
    parser.add_argument("--coins", type=str, default="BTC,ETH,SOL,BNB,XRP,DOGE",
                        help="币种列表，逗号分隔，默认 BTC,ETH,SOL,BNB,XRP,DOGE")
    parser.add_argument("--bar", type=str, default="1H",
                        help="K线周期，默认 1H")
    parser.add_argument("--confidence", type=float, default=0.35,
                        help="置信度阈值，默认 0.35")
    parser.add_argument("--max-positions", type=int, default=5,
                        help="最大同时持仓数，默认 5")
    parser.add_argument("--once", action="store_true",
                        help="只执行一次，不循环")
    parser.add_argument("--initial-equity", type=float, default=None,
                        help="初始权益（USDT），不指定则从 OKX 读取实际余额")
    parser.add_argument("--daily-loss-limit", type=float, default=-50.0,
                        help="日最大亏损（USDT），默认 -50")
    parser.add_argument("--max-consecutive-losses", type=int, default=5,
                        help="最大连续亏损次数，默认 5")
    parser.add_argument("--position-pct", type=float, default=0.10,
                        help="默认单笔仓位比例，默认 0.10(10%%)")
    parser.add_argument("--no-guardian", action="store_true",
                        help="不启用进程守护")
    parser.add_argument("--use-bcrm2", action="store_true", default=True,
                        help="使用 BCRM 2.0 (辩证ML引擎)，默认启用")
    parser.add_argument("--use-bcrm1", action="store_true",
                        help="使用 BCRM 1.0 (矛盾力学引擎)")
    args = parser.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",")]

    if args.initial_equity is None:
        print("[初始化] 从 OKX 读取实际余额...")
        try:
            from scripts.memory_l4.okx_simulated import OKXSimulatedClient
            client = OKXSimulatedClient()
            balance = client.get_balance()
            if balance.get("ok"):
                args.initial_equity = balance.get("total_eq", 100.0)
            else:
                args.initial_equity = 100.0
        except Exception as e:
            print(f"[初始化] 读取余额失败，使用默认值: {e}")
            args.initial_equity = 100.0
        print(f"[初始化] 实际余额={args.initial_equity:.2f} USDT")

    guardian = None
    if not args.no_guardian:
        guardian = ProcessGuardian(
            process_name="yijing_polling_trader",
            heartbeat_timeout=max(args.interval * 3, 300),
            max_consecutive_errors=args.max_consecutive_losses,
        )
        existing = guardian.check_existing_heartbeat()
        if existing and existing.get("is_alive"):
            print(f"警告：检测到已有运行中的进程 (PID={existing.get('pid')})")
            print(f"上次心跳: {existing.get('ts_str')}")

    trader = PollingTrader(
        interval=args.interval,
        coins=coins,
        bar=args.bar,
        confidence_threshold=args.confidence,
        max_positions=args.max_positions,
        initial_equity=args.initial_equity,
        daily_loss_limit=args.daily_loss_limit,
        max_consecutive_losses=args.max_consecutive_losses,
        default_position_pct=args.position_pct,
        guardian=guardian,
        use_bcrm2=not args.use_bcrm1,
    )

    if guardian:
        guardian.start()

    if args.once:
        trader.run_once()
        status = trader.get_status()
        print("\n═══ 运行状态 ═══")
        print(json.dumps({k: v for k, v in status.items()
                         if k not in ("open_positions_detail",)},
                        indent=2, ensure_ascii=False, default=str))
    else:
        trader.run_loop()

    if guardian:
        guardian.stop()


if __name__ == "__main__":
    main()
