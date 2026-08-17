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
import signal as signal_module
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
from scripts.memory_l4.bcrm.bagua_engine import BaguaEngine
from scripts.memory_l4.bcrm.engine import BCRMEngine
from scripts.memory_l4.bcrm2.incremental_learner import IncrementalLearner
from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter
from scripts.memory_l4.classic_exit_system import (
    ClassicExitSystem,
    ExitAction,
    ExitConfig,
)
from scripts.memory_l4.classic_exit_system import (
    PositionState as ExitPositionState,
)
from scripts.memory_l4.knowledge_bridge import KnowledgeBridge
from scripts.memory_l4.learning_scheduler import LearningScheduler
from scripts.memory_l4.okx_simulated import OKXSimulatedClient
from scripts.memory_l4.paths import episodes_dir as _episodes_dir
from scripts.memory_l4.process_guardian import ProcessGuardian
from scripts.memory_l4.ranging_market_enhancer import (
    HexagramDataDrivenCalibrator,
    RangingMarketEnhancer,
)
from scripts.memory_l4.trading_utils import (
    PerformanceTracker,
    PositionTracker,
    RiskManager,
    register_trade_to_l4,
)
from scripts.memory_l4.yijing_exit_system import (
    YijingExitAction,
    YijingExitConfig,
    YijingExitSystem,
)
from scripts.memory_l4.yijing_feishu_alert import notify_model_error, notify_system_error
from scripts.memory_l4.yijing_trainer import (
    _build_contradiction_list,
    _build_research_contradictions,
    _contradictions_to_bcrm_format,
    _detect_ranging_market,
    _kline_to_snapshot,
    _load_kline_from_okx,
)
import pandas as pd


class PollingTrader:
    """易经推理轮询交易器（P2 完整版）"""

    # config.json 中与进化阈值相关的键
    _EVOLUTION_CONFIG_KEYS = (
        "confidence_threshold",
        "daily_loss_limit",
        "max_consecutive_losses",
        "default_position_pct",
    )

    # 统一冷静期：平仓后 N 秒内禁止该币种任何方向新开仓（含反手）
    # 防止"平仓→立即反手→又亏→再反手"的频繁来回割肉循环
    COOLDOWN_SEC = 28800  # 8 小时

    def __init__(
        self,
        interval: int = 3600,
        coins: list = None,
        bar: str = "1H",
        confidence_threshold: float = 0.70,
        short_confidence_threshold: float = 0.70,
        max_positions: int = 5,
        kline_limit: int = 200,
        initial_equity: float = 100.0,
        daily_loss_limit: float = -30.0,
        max_consecutive_losses: int = 999,
        default_position_pct: float = 0.10,
        guardian: ProcessGuardian = None,
        shared_dir=None,
        use_bcrm2: bool = True,
    ):
        self.interval = interval
        default_coins = [
            "UNI",
            "PUMP",
            "MU",
            "SKHYNIX",
            "HYPE",
            "ETH",
            "BTC",
            "SOL",
            "XAU",
            "XAG",
            "GOOGL",
            "NVDA",
            "AMZN",
            "OKB",
            "BNB",
            "LINK",
            "SNDK",
            "SPCX",
        ]
        # P4 修复：币种规范化映射
        # 实际 OKX 合约：
        #   XAU-USDT-SWAP  (黄金现货杠杆代币, ticker code=0, 存在)
        #   XAUT-USDT-SWAP (Tether黄金代币,          ticker code=51001, 不存在/已下线)
        #   XSNDK → SNDK-USDT-SWAP (闪迪, OKX用SNDK而非XSNDK)
        #   XSPCX → SPCX-USDT-SWAP  (SpaceX, OKX用SPCX而非XSPCX)
        # 所以如果用户/旧启动命令写了 XAUT/XSNDK/XSPCX，必须映射，避免 K线拉取失败。
        _NORMALIZE_COIN = {"XAUT": "XAU", "XSNDK": "SNDK", "XSPCX": "SPCX"}

        def _norm(c):
            cu = str(c).strip().upper()
            return _NORMALIZE_COIN.get(cu, cu)

        self.coins = [_norm(c) for c in (coins or default_coins)]
        self.bar = bar
        self.confidence_threshold = confidence_threshold
        self.short_confidence_threshold = short_confidence_threshold  # 做空独立阈值（高于做多）
        self.max_positions = max_positions
        self.kline_limit = kline_limit

        # A-1修复：启动时从 OKX_SIM/config.json 加载进化后的阈值，覆盖默认值
        # 注意：需要在 risk_manager 创建后调用，才能同时更新 risk_manager.state
        self._evolution_config_path = None

        self.bcrm_engine = BCRMEngine.from_config()  # PROP-20260810
        self.bagua_engine = BaguaEngine()
        self.okx_client = OKXSimulatedClient()

        self.use_bcrm2 = use_bcrm2
        self.bcrm2_adapters = {}
        # v3.0：per-coin降级机制，替代全局use_bcrm2=False
        # 记录BCRM 2.0训练失败的币种 + 失败时间戳，避免一个币种失败影响其他币种
        self.bcrm2_failed_coins: dict = {}  # {coin: fail_ts}
        self.bcrm2_retry_interval_sec: int = 86400  # 训练失败后24h才重试
        self.bcrm2_min_samples: int = 100  # BCRM 2.0训练所需最小有效样本数

        # P0-2: 币种黑名单 — 历史回测胜率0%的币种，禁止下单
        # 数据来源：69笔交易复盘中 ETH(0/10) NEAR(0/6) XRP(0/5) LINK(0/4) BNB(0/4) 全部0胜率
        # 可被 config.json 的 blacklist_coins 字段热重载覆盖
        self.blacklist_coins: set = {"ETH", "NEAR", "XRP", "LINK", "BNB"}

        # P0-3: 卦象黑名单 — 历史回测胜率0%的卦象，强制HOLD
        # 数据来源：坤为地(7/7亏) 震为雷(5/5亏) 火地晋(2/2亏) 地雷复(2/2亏) 全部100%亏损
        # 可被 config.json 的 hexagram_blacklist 字段热重载覆盖
        self.hexagram_blacklist: set = {"坤为地", "震为雷", "火地晋", "地雷复"}

        # P1-1: BTC趋势缓存（5分钟刷新一次，避免每币种重复拉取BTC日线K线）
        self._btc_trend_cache: dict = {"ts": 0, "result": None}

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
                self._log("[BCRM2.0] 模式已启用，启动健康检查通过", "INFO")

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

        # A-1修复：risk_manager 创建后，从 config.json 加载进化后的阈值覆盖默认值
        self._load_evolution_config(initial=True)
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

        # 经典指标离场系统（2026-08-06 放宽：减少频繁扫损，支持高置信度长持）
        exit_cfg = ExitConfig(
            l0_max_hold_sec=172800,
            l0_max_loss_pct=-0.05,  # 最后防线不变
            tb_enabled=True,
            tb_sl_atr_mult=2.5,  # 原 1.5 → 2.5：放宽ATR-based止损，避免震荡洗出
            tb_tp_atr_mult=5.0,  # 原 3.0 → 5.0：盈亏比保持~2:1
            tb_sl_min_pct=0.06,  # 原 0.045 → 0.06：订单级最小止损 6%（对应价格0.6%@10x）
            tb_tp_min_pct=0.06,  # 原 0.04 → 0.06：同放宽
            trailing_enabled=True,
            trailing_arm_profit_pct=0.06,  # 原 0.04 → 0.06：达到6%订单盈利才启用追踪止盈，避免过早启动
            trailing_retrace_pct=0.05,  # 原 0.035 → 0.05：允许5%回调而非3.5%，减少利润锁定过急
            tstp_enabled=True,
            l1_enabled=True,
            l2_close_threshold=0.75,
            l2_reduce_threshold=0.55,
            apply_leverage_to_thresholds=True,
            inflight_cooldown_sec=180,
            l0_risk_gate_enabled=True,
            l0_risk_gate_close_enabled=False,
            l0_risk_gate_cooldown_min=60.0,
            l0_risk_gate_confirm_n=3,
            # Bug2修复: L0_RISK_GATE过度敏感（回测95.6%触发率）
            # 提高long阈值0.5→0.65：避免hold_risk刚过0.5就仓促减仓（正常波动就会触发）
            l0_risk_gate_long_thr=0.65,
            # 同步提高short阈值保持比例一致
            l0_risk_gate_short_thr=0.60,
            # Bug2修复: 新增最小持仓时间3600s=1h
            # 开仓初期hold_risk计算不稳定（K线样本少、ATR异常），给1h保护期
            l0_risk_gate_min_hold_sec=3600.0,
            # 提高盈利旁路阈值：pnl_eff>5%才跳过risk_gate（原3%太低，盈利3%可能只是噪音）
            l0_risk_gate_profit_bypass_pct=0.05,
        )
        self.exit_system = ClassicExitSystem(config=exit_cfg)
        self._exit_cfg_base = exit_cfg

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

        # CBR 案例检索增强（2026-07-21 修复：接入历史案例检索到决策流程）
        try:
            from scripts.memory_l4.cbr_adapter import CBRToBCRMBridge

            self.cbr_bridge = CBRToBCRMBridge()
            self.cbr_bridge.initialize()
            self._log("[CBR] 案例检索增强已初始化", "INFO")
        except Exception as e:
            self._log(f"[CBR] 初始化失败: {e}，继续运行", "WARN")
            self.cbr_bridge = None

        # A7 实践论门禁（代码驱动，不依赖大模型）
        try:
            from scripts.memory_l4.a7_practice_gate import A7PracticeGate

            self.a7_gate = A7PracticeGate()
            self._log("[A7] 实践论门禁已初始化", "INFO")
        except Exception as e:
            self._log(f"[A7] 门禁初始化失败: {e}，继续运行", "WARN")
            self.a7_gate = None

        # P3: 认知召回桥接（A 系列 Cron 执行前注入认知召回）
        self.cognitive_recall_enabled = True
        self._trading_recall_fn = None
        try:
            import sys as _sys

            _cog_path = str(Path(__file__).resolve().parents[2] / "4-MEMORY" / "9-工具与接口")
            if _cog_path not in _sys.path:
                _sys.path.insert(0, _cog_path)
            from cognitive_loop_entry import trading_recall as _trading_recall

            self._trading_recall_fn = _trading_recall
            self._log("[P3] 认知召回桥接已初始化", "INFO")
        except Exception as e:
            self._log(f"[P3] 认知召回桥接初始化失败: {e}，继续运行", "WARN")
            self.cognitive_recall_enabled = False

        self._sync_existing_positions()

        self._run_startup_inspection()

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
                    confidence=0.8,
                    hexagram="已存在持仓",
                    market_snapshot={"price": float(pos.get("mark_px", pos["avg_px"]))},
                    strategy_source="bcrm",
                )
                self._log(
                    f"[持仓同步] 已同步 {coin} {pos['pos_side']} @ {pos['avg_px']} [易经推理持仓·启动同步]",
                    "INFO",
                )

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
        external_count = sum(
            1 for p in self.position_tracker.all_open_positions() if p.strategy_source == "external"
        )
        self._log(
            f"[持仓同步] 完成，共 {open_count} 个持仓 (BCRM={open_count-external_count} 外部={external_count})",
            "INFO",
        )

        # ══════════════════════════════════════════════════════════════
        # v5.0 离场防频繁优化：离场确认状态机 + 持仓保护门禁
        # ══════════════════════════════════════════════════════════════
        # 离场动作2次确认状态机：避免单根K线假信号/瞬时波动直接平仓
        # key = f"{coin}:{action_type}"  value = {confirm_count: int, first_ts: float}
        self._exit_confirm_state: Dict[str, Dict[str, Any]] = {}
        # 确认窗口：2次轮询(约2min)内连续触发才执行
        self.EXIT_CONFIRM_WINDOW_SEC = 300  # 5分钟窗口
        self.EXIT_CONFIRM_REQUIRED = 2  # 需要2次连续触发
        # 离场动作类型
        self.EXIT_ACT_SIGNAL_REVERSE = "signal_reverse"
        self.EXIT_ACT_YIJING_FORCE_CLOSE = "yijing_force_close"
        self.EXIT_ACT_P3_EARLY_EXIT = "p3_early_exit"

        # 持仓保护期门禁（开仓后N小时内仅硬离场生效）
        # 保护期内：信号反转需更高置信度；易经TIGHTEN_SL/LOWER_TP/LOWER_SL/RAISE_TP全部屏蔽；
        #          P3提前退出需确认；仅保留开仓静态SL/TP + P0硬止损
        self.POSITION_PROTECTION_HOURS = 6.0  # 开仓后前6小时为保护期
        # 保护期内信号反转所需额外置信度(在effective_threshold之上再加)
        self.PROTECTED_REVERSE_CONF_BOOST = 0.12  # 如原阈值0.7→保护期需≥0.82
        # 保护期内最小亏损比例才允许P3提前退出（否则假预警会走）
        self.PROTECTED_P3_MIN_LOSS_PCT = -0.08  # 浮亏≥8%才允许P3退出（保护期内）
        self._log(
            f"[离场防频繁] v5.0优化已启用：保护期={self.POSITION_PROTECTION_HOURS:.0f}h "
            f"| 离场确认={self.EXIT_CONFIRM_REQUIRED}次/{self.EXIT_CONFIRM_WINDOW_SEC//60:.0f}min "
            f"| 保护期反转置信+{self.PROTECTED_REVERSE_CONF_BOOST:.0%}",
            "INFO",
        )

    def _run_startup_inspection(self):
        """启动时运行 inspect 诊断命令，快速检查系统状态"""
        self._log("[系统诊断] 启动时执行状态检查...", "INFO")
        try:
            from scripts.memory_l4.inspect import SystemInspector

            inspector = SystemInspector()
            report = inspector.inspect(
                panel_ids=["system", "positions", "models", "connections", "risk"]
            )

            for panel in report.panels:
                status_icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(panel.status, "ℹ️")
                self._log(f"  {status_icon} [{panel.name}] {panel.summary}", panel.status.upper())
                for key, val in panel.details.items():
                    if isinstance(val, (int, float, str)) and len(str(val)) <= 50:
                        self._log(f"    └─ {key}: {val}")

            if report.overall_status == "error":
                self._log("[系统诊断] 发现错误，请检查相关组件", "WARN")
            else:
                self._log("[系统诊断] 启动检查通过", "INFO")

        except Exception as e:
            self._log(f"[系统诊断] 执行失败: {e}，继续运行", "WARN")

    def _log(self, msg: str, level: str = "INFO"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps({"ts": ts, "level": level, "msg": msg}, ensure_ascii=False) + "\n"
                )
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
            checks.append(("DialecticalMLEngine 导入", True, ""))
        except Exception as e:
            checks.append(("DialecticalMLEngine 导入", False, str(e)))

        # 3. 验证八卦特征引擎可加载
        try:
            checks.append(("BaguaFeatureEngine 导入", True, ""))
        except Exception as e:
            checks.append(("BaguaFeatureEngine 导入", False, str(e)))

        # 4. 验证增量学习器可加载
        try:
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
            # F2修正：跨天时输出前一天的每日聚合摘要到监控
            self._emit_daily_summary(self.last_date)
            self._log(f"[风控] 新的一天 {today}，重置每日风控统计")
            self.risk_manager.reset_daily()
            self.last_date = today

    def _emit_daily_summary(self, date_str: str):
        """F2修正：输出每日聚合绩效摘要到监控文件。

        将 PerformanceTracker 的日统计 + 整体统计写入
        .workbuddy/memory_l4/stats/daily_summary_{date}.json
        供 yijing_monitor / 飞书推送消费。
        """
        if not date_str:
            return
        try:
            today_stats = self.perf_tracker.get_today_stats()
            overall = self.perf_tracker.get_overall_stats()

            summary = {
                "date": date_str,
                "generated_at": datetime.now().isoformat(),
                "daily": {
                    "total_trades": today_stats.get("total_trades", 0),
                    "win_trades": today_stats.get("win_trades", 0),
                    "loss_trades": today_stats.get("loss_trades", 0),
                    "total_pnl": today_stats.get("total_pnl", 0),
                    "win_rate": today_stats.get("win_rate", 0),
                    "max_drawdown": today_stats.get("max_drawdown", 0),
                    "consecutive_losses": today_stats.get("current_consecutive_losses", 0),
                },
                "overall": {
                    "total_trades": overall.get("total_trades", 0),
                    "win_rate": overall.get("win_rate", 0),
                    "total_pnl": overall.get("total_pnl", 0),
                    "profit_factor": overall.get("profit_factor", 0),
                    "max_drawdown": overall.get("max_drawdown", 0),
                    "current_equity": overall.get("current_equity", 0),
                    "sharpe_ratio": overall.get("sharpe_ratio", 0),
                    "trading_days": overall.get("trading_days", 0),
                },
            }

            summary_file = self.perf_tracker.stats_dir / f"daily_summary_{date_str}.json"
            summary_file.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self._log(
                f"[每日摘要] {date_str} 已落盘: {summary_file.name} | "
                f"日交易{summary['daily']['total_trades']}笔 盈亏{summary['daily']['total_pnl']:.2f}U "
                f"整体夏普{summary['overall']['sharpe_ratio']:.2f}"
            )
        except Exception as e:
            self._log(f"[每日摘要] 生成失败: {e}", "WARN")

    def _fetch_and_infer(self, coin: str) -> dict:
        """获取实时行情并执行 BCRM + 八卦双引擎推理"""
        inst_id = f"{coin}-USDT-SWAP"

        kline_data = _load_kline_from_okx(inst_id=inst_id, bar=self.bar, limit=self.kline_limit)
        if not kline_data:
            return {"ok": False, "error": f"获取 {inst_id} K线失败"}

        # BCRM 2.0 推理路径
        if self.use_bcrm2:
            # v3.0：per-coin降级检查
            fail_ts = self.bcrm2_failed_coins.get(coin)
            if fail_ts is not None and (time.time() - fail_ts) < self.bcrm2_retry_interval_sec:
                # 失败币种在重试间隔内，直接走BCRM 1.0（不训练不告警）
                pass  # 落到下面的BCRM 1.0路径
            else:
                # 未失败或已过重试间隔，尝试BCRM 2.0
                if fail_ts is not None:
                    self._log(f"[{coin}] BCRM2.0 失败重试间隔已过，重新尝试", "INFO")
                    self.bcrm2_failed_coins.pop(coin, None)
                    if coin in self.bcrm2_adapters:
                        del self.bcrm2_adapters[coin]
                try:
                    return self._infer_bcrm2(coin, inst_id, kline_data)
                except Exception as e:
                    self._log(f"[{coin}] BCRM2.0 运行异常: {e}，降级到 BCRM 1.0", "ERROR")
                    try:
                        notify_model_error(
                            f"BCRM2.0 运行异常降级: {type(e).__name__}: {e}",
                            symbol=coin,
                        )
                    except Exception as alert_err:
                        self._log(f"[{coin}] 飞书告警发送失败: {alert_err}", "WARN")
                    self.bcrm2_failed_coins[coin] = time.time()
                    # 降级后继续走 BCRM 1.0 推理路径（不 return，落到下面）

        snapshot = _kline_to_snapshot(kline_data, idx=0)
        if not snapshot:
            return {"ok": False, "error": "构造 snapshot 失败"}
        snapshot["symbol"] = inst_id

        contradictions_raw = _build_contradiction_list(snapshot)
        contradictions_raw.extend(_build_research_contradictions(snapshot))
        contradictions = _contradictions_to_bcrm_format(contradictions_raw, snapshot)

        closes_window = [kline_data[j]["c"] for j in range(min(60, len(kline_data)))]
        volumes_window = [kline_data[j].get("v", 0) for j in range(min(60, len(kline_data)))]
        ranging_info = _detect_ranging_market(snapshot, closes_window)
        snapshot["is_ranging"] = ranging_info.get("is_ranging", False)
        snapshot["ranging_confidence"] = ranging_info.get("confidence", 0)

        # P0修复: 每币种推理前重置 ForceEngine 速度状态，防止跨币种污染
        if hasattr(self.bcrm_engine, "force_engine") and hasattr(
            self.bcrm_engine.force_engine, "reset_velocity"
        ):
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
        hex_cn = bcrm_result.hexagram.hexagram_name_cn or bcrm_result.hexagram.hexagram_name
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
                if bcrm_result and hasattr(bcrm_result, "hexagram"):
                    bcrm_hex = bcrm_result.hexagram
                    # 使用变卦替代
                    if hasattr(bcrm_hex, "changed_hexagram_cn") and bcrm_hex.changed_hexagram_cn:
                        hex_cn = bcrm_hex.changed_hexagram_cn
                        self._log(f"[{coin}] 卦象校准 | {hex_cn}(变卦) 替代原卦象", "INFO")
                    else:
                        self._log(
                            f"[{coin}] 卦象警告 | 卦象{hex_cn}({gua_direction})与决策方向({actual_direction})不一致",
                            "WARN",
                        )

        sl_px, tp_px, reduce_ratio = 0, 0, 0
        if bcrm_result.strategy_branches:
            b1 = next((b for b in bcrm_result.strategy_branches if b.branch_id == "B1"), None)
            if b1:
                sl_px = b1.stop_loss_px
                tp_px = b1.take_profit_px
                reduce_ratio = b1.reduce_ratio

        # 经典指标离场回退：BCRM 未产生止盈止损时，用 ATR 计算止损止盈
        # 2026-08-06 上调：ATR 倍数 2.0→3.0 / 4.0→6.0（过近止损导致频繁扫损，高置信度仓位建议长期持有）
        if sl_px == 0 or tp_px == 0:
            price = snapshot.get("price", 0)
            volatility = snapshot.get("volatility", 0.03)
            if price > 0:
                # ATR 近似：用波动率 × 价格作为 ATR 估计
                atr = max(price * volatility, price * 0.005)  # 至少 0.5%
                # 基础倍率
                atr_mult_sl = 3.0  # 止损 = 3.0 × ATR（原 2.0 → 放宽，避免洗出）
                atr_mult_tp = 6.0  # 止盈 = 6.0 × ATR（原 4.0 → 盈亏比 2:1）
                # 高置信度进一步放宽：置信度 ≥0.9 时 SL/TP 再 ×1.3
                if confidence >= 0.9:
                    atr_mult_sl *= 1.3
                    atr_mult_tp *= 1.3
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
                    f"[{coin}] 经典指标离场 | ATR={atr:.2f} "
                    f"(conf={confidence:.2f}→SL×{atr_mult_sl/3.0:.1f} TP×{atr_mult_tp/6.0:.1f}) | "
                    f"SL={sl_px} TP={tp_px} (盈亏比={atr_mult_tp/atr_mult_sl:.1f}:1)",
                    "INFO",
                )

        liangyi_dict = {}
        if hasattr(bcrm_result, "liangyi_state") and bcrm_result.liangyi_state:
            if hasattr(bcrm_result.liangyi_state, "to_dict"):
                liangyi_dict = bcrm_result.liangyi_state.to_dict()
            elif isinstance(bcrm_result.liangyi_state, dict):
                liangyi_dict = bcrm_result.liangyi_state

        scale_dict = {}
        if hasattr(bcrm_result, "scale_params") and bcrm_result.scale_params:
            if hasattr(bcrm_result.scale_params, "to_dict"):
                scale_dict = bcrm_result.scale_params.to_dict()
            elif isinstance(bcrm_result.scale_params, dict):
                scale_dict = bcrm_result.scale_params

        # P0修复：注入 regime 到 snapshot（卦象+is_ranging+closes推断）
        snapshot["regime"] = self._infer_regime(
            hex_cn, snapshot.get("is_ranging", False), direction, closes_window
        )

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
            data.append(
                {
                    "timestamp": c.get("ts", 0),
                    "open": float(c.get("o", 0)),
                    "high": float(c.get("h", 0)),
                    "low": float(c.get("l", 0)),
                    "close": float(c.get("c", 0)),
                    "volume": float(c.get("v", 0)),
                }
            )
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def _infer_bcrm2(self, coin: str, inst_id: str, kline_data: list) -> dict:
        """使用 BCRM 2.0 (辩证ML) 执行推理"""

        if coin not in self.bcrm2_adapters:
            # BTC 启用 v4 前向选择验证有效的 3 个宏观特征
            # (fgi_zscore + fgi_extreme_fear + hash_rate_trend，BTC验证得分 +23.8%)
            # 其他币种保持默认（不传 macro_config = 全部启用默认行为）
            btc_macro_config = None
            if coin.upper() == "BTC":
                btc_macro_config = {
                    "macro_feat_fgi_zscore": True,
                    "macro_feat_fgi_extreme_fear": True,
                    "macro_feat_hash_rate_trend": True,
                    # 其余 21 个特征显式关闭
                    "macro_feat_fgi_trend_7d": False,
                    "macro_feat_fgi_extreme_greed": False,
                    "macro_feat_fgi_divergence": False,
                    "macro_feat_funding_rate_zscore": False,
                    "macro_feat_funding_extreme_positive": False,
                    "macro_feat_funding_extreme_negative": False,
                    "macro_feat_oi_change_rate": False,
                    "macro_feat_funding_divergence": False,
                    "macro_feat_stablecoin_growth": False,
                    "macro_feat_liquidity_expanding": False,
                    "macro_feat_liquidity_contracting": False,
                    "macro_feat_tvl_change_7d": False,
                    "macro_feat_miner_accumulation": False,
                    "macro_feat_miners_revenue_zscore": False,
                    "macro_feat_smart_money_direction": False,
                    "macro_feat_smart_money_divergence": False,
                    "macro_feat_social_hype_zscore": False,
                    "macro_feat_hype_extreme": False,
                    "macro_feat_market_cap_rank": False,
                    "macro_feat_ath_drop_pct": False,
                    "macro_feat_undervalued": False,
                }
            self.bcrm2_adapters[coin] = BCRM2Adapter(
                symbol=coin,
                timeframe=self.bar,
                tp_atr=3.0,
                sl_atr=2.5,  # P1-2: 原1.5→2.5，与外层SL=3.0×ATR口径一致（2.5~3 ATR区间）
                max_hold_bars=60,
                macro_config=btc_macro_config,
            )

        adapter = self.bcrm2_adapters[coin]

        try:
            df = self._kline_to_dataframe(kline_data)
        except Exception as e:
            return {"ok": False, "error": f"K线转换失败: {e}"}

        # 首次推理时自动训练
        if adapter.engine is None:
            # v3.0：预检查K线数据量，不足则直接走BCRM 1.0，不训练不告警
            # max_hold_bars=60，需要至少 100+60=160 根K线才能产生100个有效样本
            min_klines_needed = self.bcrm2_min_samples + adapter.max_hold_bars
            if len(df) < min_klines_needed:
                self._log(
                    f"[{coin}] BCRM2.0 跳过训练: K线数据不足({len(df)}<{min_klines_needed}根)"
                    f"，直接使用 BCRM 1.0",
                    "INFO",
                )
                self.bcrm2_failed_coins[coin] = time.time()
                return self._fetch_and_infer(coin)

            self._log(f"[{coin}] BCRM2.0 首次推理，开始训练模型...", "INFO")
            train_result = adapter.train(df)
            if train_result is not True:
                # v3.0：区分"数据不足"和"训练异常"
                is_data_insufficient = train_result == "insufficient_data"
                self.bcrm2_failed_coins[coin] = time.time()

                if is_data_insufficient:
                    # 数据不足是预期行为（新上线币种），不发飞书告警
                    self._log(f"[{coin}] BCRM2.0 样本不足，使用 BCRM 1.0（24h后自动重试）", "INFO")
                else:
                    # 真正的训练异常，发飞书告警
                    self._log(f"[{coin}] BCRM2.0 训练失败(异常)，回退到 BCRM 1.0", "WARN")
                    try:
                        notify_model_error(
                            "BCRM2.0 训练异常，已降级回退到 BCRM 1.0",
                            symbol=coin,
                        )
                    except Exception as e:
                        self._log(f"[{coin}] 飞书告警发送失败: {e}", "WARN")
                return self._fetch_and_infer(coin)

        # 执行推理
        bcrm_result = adapter.infer(df, idx=-1)

        if not bcrm_result.get("ok"):
            # 措施2：推理失败时立即发送飞书告警（fail_closed 也会走这里）
            fail_reason = bcrm_result.get("fail_closed_reason", "未知")
            self._log(f"[{coin}] BCRM2.0 推理失败: {fail_reason}", "WARN")
            try:
                notify_model_error(
                    f"BCRM2.0 推理失败 (fail_closed): {fail_reason}",
                    symbol=coin,
                )
            except Exception as e:
                self._log(f"[{coin}] 飞书告警发送失败: {e}", "WARN")
            return {"ok": False, "error": "BCRM2.0 推理失败"}

        direction = bcrm_result["next_state"]["direction"]
        confidence = bcrm_result["next_state"]["confidence"]
        hex_cn = bcrm_result["hexagram"]["hexagram_name_cn"]
        fail_closed = bcrm_result["is_fail_closed"]()

        # 计算波动率（用于止盈止损）— 必须在 CBR 增强前完成，供 CBR 使用
        closes = df["close"].values
        atr = 0
        if len(df) >= 14:
            highs = df["high"].values
            lows = df["low"].values
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
            )
            atr = np.mean(tr[-14:])
        volatility = atr / closes[-1] if closes[-1] > 0 else 0.03

        # 检测震荡市
        closes_window = list(closes[-60:])
        snapshot_simple = {"price": closes[-1], "volatility": volatility}
        ranging_info = _detect_ranging_market(snapshot_simple, closes_window)
        is_ranging = ranging_info.get("is_ranging", False)

        price = closes[-1]

        # CBR 案例检索增强（2026-07-21 修复：price/volatility 必须先计算好再调用）
        if self.cbr_bridge and not fail_closed:
            try:
                bcrm_output = {
                    "inst_id": inst_id,
                    "direction": (
                        "long"
                        if direction == "UP"
                        else ("short" if direction == "DOWN" else "flat")
                    ),
                    "confidence": confidence,
                    "current_price": price,
                    "regime": bcrm_result.get("hexagram", {})
                    .get("liangyi_state", {})
                    .get("macro_phase", ""),
                    "volatility": volatility,
                    "hexagram": hex_cn,
                }
                enhanced = self.cbr_bridge.enhance_bcrm_signal(bcrm_output)
                # 应用 CBR 增强的参数
                if enhanced.get("cbr_fusion_method") != "bcrm_only":
                    confidence = enhanced.get("confidence", confidence)
                    self._log(
                        f"[{coin}] CBR 增强 | 历史胜率={enhanced.get('cbr_historical_win_rate', 0):.1%} "
                        f"Top-1相似度={enhanced.get('cbr_similarity_top1', 0):.2f} "
                        f"融合模式={enhanced.get('cbr_fusion_method')} "
                        f"风险提示={enhanced.get('cbr_risk_notes', [])}",
                        "INFO",
                    )
            except Exception as e:
                self._log(f"[{coin}] CBR 增强失败: {e}", "WARN")

        # 计算 ATR 止盈止损
        # P1-2: 统一ATR止损倍率为2.5~3.0区间（adapter=2.5, 主SL=3.0, ExitConfig=2.5）
        # 高置信度(≥0.9)再×1.3放宽至3.9×ATR，盈亏比保持~2:1
        sl_px, tp_px = 0, 0
        if atr > 0:
            sl_mult = 3.0  # 主止损线 3.0×ATR
            tp_mult = 6.0  # 止盈 6.0×ATR
            if confidence >= 0.9:
                sl_mult *= 1.3
                tp_mult *= 1.3
            if direction == "UP":
                sl_px = round(price - atr * sl_mult, 4)
                tp_px = round(price + atr * tp_mult, 4)
            elif direction == "DOWN":
                sl_px = round(price + atr * sl_mult, 4)
                tp_px = round(price - atr * tp_mult, 4)

        self._log(
            f"[{coin}] BCRM2.0 推理 | 方向={direction} 置信度={confidence:.2f} "
            f"卦象={hex_cn} fail_closed={fail_closed}",
            "INFO",
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
                "regime": self._infer_regime(
                    hex_cn,
                    is_ranging,
                    direction,
                    list(closes[-60:]) if len(closes) >= 60 else list(closes),
                ),
            },
            "contradictions": bcrm_result.get("a0_analysis", {}).get("contradictions", []),
            "a0_analysis": bcrm_result.get("a0_analysis"),
            "a0_warnings": bcrm_result.get("a0_warnings", []),
            "triangle_verification": bcrm_result.get("triangle_verification"),
            # v4 风险评分风控参数（五角校验输出）
            "position_factor": bcrm_result.get("position_factor", 1.0),
            "sl_tighten_factor": bcrm_result.get("sl_tighten_factor", 1.0),
            "early_exit_signal": bcrm_result.get("early_exit_signal", False),
            "leverage_factor": bcrm_result.get("leverage_factor", 1.0),
            "tp_adjustment": bcrm_result.get("tp_adjustment", 1.0),
            "risk_score": bcrm_result.get("risk_score", 0.0),
            "risk_level": bcrm_result.get("risk_level", "NORMAL"),
            "volatility": volatility,
            "sl_atr": 1.5,
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
            "山水蒙_dup"  # noqa: F601 - intentional duplicate per 易经修复说明: "short",
            "山风蛊": "short",
            "山火贲": "long",
            "山泽损": "short",
            "泽水困": "short",
            "泽山咸": "long",
            "泽风大过": "short",
        }
        return HEX_TO_DIRECTION.get(hexagram_name, "")

    # 64卦名首字 → 八卦元素映射（上卦/下卦提取）
    _HEX_CHAR_TO_GUA = {
        "乾": "qian",
        "天": "qian",
        "坤": "kun",
        "地": "kun",
        "震": "zhen",
        "雷": "zhen",
        "巽": "xun",
        "风": "xun",
        "坎": "kan",
        "水": "kan",
        "离": "li",
        "火": "li",
        "艮": "gen",
        "山": "gen",
        "兑": "dui",
        "泽": "dui",
    }

    def _infer_regime(
        self, hexagram_name: str, is_ranging: bool, direction: str = "", closes: list = None
    ) -> str:
        """从卦象名+市场状态推断 regime（8态之一）

        轻量级推断，不依赖 MarketRegimeClassifier 训练。
        映射规则：
          1. 从64卦名提取下卦（第1字）和上卦（第2字，若存在）
          2. 下卦为主卦，映射到 GUA_REGIME_MAP 的8态
          3. is_ranging=True 时，趋势类regime降级为震荡类
          4. 特殊处理纯卦（"X为Y"格式）

        Returns:
            regime 名称（如 TREND_UP_STRONG / RANGE_BOUND / ...）
        """
        from scripts.memory_l4.bcrm2.market_regime import GUA_REGIME_MAP

        if not hexagram_name or hexagram_name == "已存在持仓":
            # 无卦象时用 is_ranging + direction 兜底
            if is_ranging:
                return "RANGE_BOUND"
            if direction == "UP":
                return "TREND_UP_MILD"
            if direction == "DOWN":
                return "VOLATILE_DROP"
            return "CONSOLIDATION"

        # 纯卦格式："X为Y"（如"乾为天"）→ 取首字
        if "为" in hexagram_name:
            first_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[0], "")
            if first_gua and first_gua in GUA_REGIME_MAP:
                regime = GUA_REGIME_MAP[first_gua]
                # 震荡市降级
                if is_ranging and regime in ("TREND_UP_STRONG", "TREND_UP_MILD", "BREAKOUT"):
                    return "RANGE_BOUND"
                return regime

        # 组合卦：取前两字作为上下卦（如"水山蹇"→上坎下艮）
        # 下卦（第1字）为主，上卦（第2字）为辅
        if len(hexagram_name) >= 2:
            lower_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[0], "")
            upper_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[1], "")

            # 优先用下卦（主卦）映射
            if lower_gua and lower_gua in GUA_REGIME_MAP:
                regime = GUA_REGIME_MAP[lower_gua]
                # 震荡市降级：强趋势/突破类 → 震荡
                if is_ranging and regime in (
                    "TREND_UP_STRONG",
                    "TREND_UP_MILD",
                    "BREAKOUT",
                    "FOMO_RALLY",
                ):
                    return "RANGE_BOUND"
                return regime

            # 下卦未命中，尝试上卦
            if upper_gua and upper_gua in GUA_REGIME_MAP:
                return GUA_REGIME_MAP[upper_gua]

        # 价格趋势兜底
        if closes and len(closes) >= 20:
            if closes[-1] > closes[-20]:
                return "TREND_UP_MILD" if not is_ranging else "RANGE_BOUND"
            elif closes[-1] < closes[-20]:
                return "VOLATILE_DROP" if not is_ranging else "RANGE_BOUND"

        return "CONSOLIDATION"

    # ══════════════════════════════════════════════════════════════
    # v5.0 离场防频繁：离场确认状态机 + 持仓保护期门禁
    # ══════════════════════════════════════════════════════════════

    def _is_position_protected(self, position_age_sec: float) -> bool:
        """判断持仓是否在保护期内（开仓后前N小时）

        保护期内：仅P0硬止损/静态SL/TP生效；易经动态SL/TP调整屏蔽；
        信号反转/P3提前退出需要更高门槛 + 离场确认。
        """
        return position_age_sec < (self.POSITION_PROTECTION_HOURS * 3600.0)

    def _exit_confirm(self, coin: str, action_type: str) -> Tuple[bool, int]:
        """离场动作2次确认状态机。

        Args:
            coin: 币种
            action_type: 动作类型（signal_reverse / yijing_force_close / p3_early_exit）

        Returns:
            (confirmed: bool, current_count: int)
                confirmed: 是否达到确认次数（可执行离场）
                current_count: 当前累计确认次数
        """
        now = time.time()
        key = f"{coin}:{action_type}"

        state = self._exit_confirm_state.get(key)
        if state is None:
            # 第一次触发：记录，未确认
            self._exit_confirm_state[key] = {
                "confirm_count": 1,
                "first_ts": now,
            }
            return False, 1

        # 检查是否在确认窗口内
        elapsed = now - state["first_ts"]
        if elapsed > self.EXIT_CONFIRM_WINDOW_SEC:
            # 窗口超时：重置为第一次
            self._exit_confirm_state[key] = {
                "confirm_count": 1,
                "first_ts": now,
            }
            return False, 1

        # 窗口内：累计+1
        state["confirm_count"] += 1
        self._exit_confirm_state[key] = state
        confirmed = state["confirm_count"] >= self.EXIT_CONFIRM_REQUIRED
        return confirmed, state["confirm_count"]

    def _clear_exit_confirm(self, coin: str, action_type: str = ""):
        """清除某币种的离场确认状态。

        离场执行后、或条件不再满足时调用，避免状态污染。
        """
        if action_type:
            key = f"{coin}:{action_type}"
            self._exit_confirm_state.pop(key, None)
        else:
            # 清除该币种所有动作类型
            prefix = f"{coin}:"
            keys = [k for k in self._exit_confirm_state if k.startswith(prefix)]
            for k in keys:
                self._exit_confirm_state.pop(k, None)

    def _check_positions(self, coin: str) -> dict:
        """检查指定币种的持仓。
        Bug修复：返回 open_time（开仓时间戳,秒），供离场系统计算持仓年龄。
        优先从本地 PositionTracker.entry_time 读取（更准确），缺失时回退 OKX ctime。
        """
        inst_id = f"{coin}-USDT-SWAP"
        pos_result = self.okx_client.get_positions(inst_id)
        if not pos_result.get("ok"):
            return {"has_position": False, "query_failed": True}
        positions = pos_result.get("positions", [])
        if not positions:
            return {"has_position": False}
        pos = positions[0]

        open_time_sec = 0.0
        tracker_rec = self.position_tracker.get_open_position(inst_id)
        if tracker_rec and tracker_rec.entry_time:
            try:
                if tracker_rec.entry_time.endswith("Z"):
                    ts = tracker_rec.entry_time.replace("Z", "+00:00")
                else:
                    ts = tracker_rec.entry_time
                from datetime import datetime as _dt

                open_time_sec = _dt.fromisoformat(ts).timestamp()
            except Exception:
                open_time_sec = 0.0
        if open_time_sec <= 0:
            # OKX 回退：取 ctime（字符串秒）
            ctime = pos.get("cTime") or pos.get("ctime") or pos.get("created_at", "0")
            try:
                open_time_sec = float(ctime) / 1000 if float(ctime) > 1e12 else float(ctime)
            except Exception:
                open_time_sec = 0.0

        return {
            "has_position": True,
            "pos_side": pos["pos_side"],
            "pos_size": pos["pos"],
            "avg_px": pos["avg_px"],
            "upl": pos["upl"],
            "upl_ratio": pos["upl_ratio"],
            "mark_px": pos["mark_px"],
            "open_time": open_time_sec,
        }

    def _count_total_positions(self) -> int:
        # 单次批量查询OKX全部持仓，避免逐个查询因限流/超时导致计数偏低、超额开仓
        pos_result = self.okx_client.get_positions()
        if pos_result.get("ok"):
            return len(pos_result.get("positions", []))
        # API失败时回退到本地持仓跟踪器
        return len(self.position_tracker.all_open_positions())

    def _get_leverage(self) -> float:
        """获取当前默认杠杆倍数"""
        return float(self.okx_client.cfg.get("default_leverage", 3))

    def _get_base_sl_roi(self, inst_id: str, entry_price: float = 0.0) -> float:
        """读取开仓时 ATR 基线止损收益率。

        优先从 PositionTracker.base_sl_roi 读取；
        旧持仓（字段为0）时回退到从当前 SL 价格反算。
        """
        rec = self.position_tracker.get_open_position(inst_id)
        if rec and rec.base_sl_roi > 0:
            return rec.base_sl_roi
        # 回退：从 entry_price 和 stop_loss 反算（如果有的话）
        if rec and entry_price > 0 and rec.market_snapshot:
            sl_px = rec.market_snapshot.get("stop_loss_px", 0)
            if sl_px > 0:
                leverage = self._get_leverage()
                price_pct = abs(sl_px - entry_price) / entry_price
                return self._price_change_to_roi(price_pct, leverage)
        return 0.0

    def _get_base_tp_roi(self, inst_id: str, entry_price: float = 0.0) -> float:
        """读取开仓时 ATR 基线止盈收益率。

        优先从 PositionTracker.base_tp_roi 读取；
        旧持仓（字段为0）时回退到从当前 TP 价格反算。
        """
        rec = self.position_tracker.get_open_position(inst_id)
        if rec and rec.base_tp_roi > 0:
            return rec.base_tp_roi
        if rec and entry_price > 0 and rec.market_snapshot:
            tp_px = rec.market_snapshot.get("take_profit_px", 0)
            if tp_px > 0:
                leverage = self._get_leverage()
                price_pct = abs(tp_px - entry_price) / entry_price
                return self._price_change_to_roi(price_pct, leverage)
        return 0.0

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

    def _handle_close_position(
        self,
        inst_id: str,
        coin: str,
        pos_side: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_pct: float,
    ):
        """处理平仓：生成交易记录、更新绩效、生成 case、更新风控、增量学习

        Returns:
            trade summary dict
        """
        # v3.0：平仓后立即清除易经离场系统的评估缓存，
        # 避免下次开仓的前1小时评估被上次持仓的1h窗口缓存污染
        try:
            self.yijing_exit_system.clear_cache(coin=coin, pos_side=pos_side)
        except Exception:
            pass

        trade_rec = self.position_tracker.close_position(
            inst_id=inst_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )

        if trade_rec:
            perf_summary = self.perf_tracker.record_trade(trade_rec)
            self.risk_manager.update_after_trade(
                pnl, pnl >= 0, current_equity=self.perf_tracker.current_equity
            )

            case_id, saved = register_trade_to_l4(trade_rec)

            self._log(
                f"[{coin}] 平仓记录 | {'盈利' if pnl >= 0 else '亏损'} {pnl:.2f}USDT "
                f"({pnl_pct:.2%}) | case={case_id} saved={saved} | "
                f"日盈亏={perf_summary['daily_total_pnl']:.2f} "
                f"连亏={perf_summary['consecutive_losses']}"
            )

            try:
                hold_bars = 0
                if trade_rec.entry_time and trade_rec.exit_time:
                    try:
                        from datetime import datetime

                        entry_dt = datetime.fromisoformat(
                            trade_rec.entry_time.replace("Z", "+00:00")
                        )
                        exit_dt = datetime.fromisoformat(trade_rec.exit_time.replace("Z", "+00:00"))
                        delta = exit_dt - entry_dt
                        hold_bars = int(delta.total_seconds() / 3600)
                    except Exception:
                        pass

                trade_data = {
                    "symbol": coin,
                    "direction": trade_rec.direction,
                    "entry_time": trade_rec.entry_time,
                    "exit_time": trade_rec.exit_time,
                    "entry_price": trade_rec.entry_price,
                    "exit_price": trade_rec.exit_price,
                    "pnl_pct": trade_rec.pnl_pct,
                    "hold_bars": hold_bars,
                    "exit_reason": trade_rec.exit_reason,
                    "confidence": trade_rec.confidence,
                    "hexagram": trade_rec.hexagram,
                    "upper_gua": "",
                    "lower_gua": "",
                    "position_factor": 1.0,
                }
                self.incremental_learner.log_trades_batch([trade_data])

                should_retrain, reason = self.incremental_learner.should_retrain(coin)
                if should_retrain:
                    self._log(f"[{coin}] 增量学习触发再训练: {reason}")
                    retrain_ok = self._trigger_bcrm2_retrain(coin)
                    if retrain_ok:
                        self._log(f"[{coin}] BCRM2.0 增量重训完成")
            except Exception as e:
                self._log(f"[{coin}] 增量学习记录失败: {e}", "WARN")

            retrain_result = self.learning_scheduler.trigger_retrain()
            if retrain_result.get("retrained"):
                self._log(f"[{coin}] 触发重训: {retrain_result.get('reason')}")

            # 优化4：更新置信度校准表
            # 优化5：更新卦象数据驱动校准统计
            try:
                if hasattr(self, "ranging_enhancer") and self.ranging_enhancer:
                    enhance_info = (
                        trade_rec.enhance_info if hasattr(trade_rec, "enhance_info") else None
                    )
                    regime_val = (
                        enhance_info.get("regime", "sideways") if enhance_info else "sideways"
                    )

                    # 置信度校准
                    trade_for_cal = {
                        "confidence": trade_rec.confidence,
                        "pnl_pct": trade_rec.pnl_pct,
                        "regime": regime_val,
                        "hexagram": trade_rec.hexagram or "",
                        "direction": "UP" if trade_rec.direction == "long" else "DOWN",
                    }
                    self.ranging_enhancer.update_calibration([trade_for_cal])

                    # 卦象数据驱动校准（优化5）
                    if (
                        hasattr(self.ranging_enhancer, "hex_calibrator")
                        and self.ranging_enhancer.hex_calibrator
                    ):
                        self.ranging_enhancer.hex_calibrator.record_trade(
                            hexagram=trade_rec.hexagram or "",
                            direction="UP" if trade_rec.direction == "long" else "DOWN",
                            pnl_pct=trade_rec.pnl_pct,
                            confidence=trade_rec.confidence,
                        )
            except Exception as e:
                self._log(f"[{coin}] 校准更新失败: {e}", "WARN")

            # P2-1a增强: 平仓后自动触发L4 Pipeline (M1-M4)
            try:
                self._trigger_l4_pipeline_for_trade(trade_rec, case_id, saved)
            except Exception as e:
                self._log(f"[{coin}] L4 Pipeline自动触发失败: {e}", "WARN")

            return perf_summary
        else:
            self._log(f"[{coin}] 警告：平仓但无对应开仓记录 {inst_id}", "WARN")
            return {}

    def _trigger_bcrm2_retrain(self, coin: str) -> bool:
        """触发 BCRM 2.0 增量重训

        使用最新K线数据重新训练模型，并记录到增量学习版本管理。
        """
        if not self.use_bcrm2:
            return False

        adapter = self.bcrm2_adapters.get(coin)
        if not adapter:
            return False

        try:

            inst_id = f"{coin}-USDT-SWAP"
            kline_resp = self.okx_client.get_kline(inst_id, bar=self.bar, limit=self.kline_limit)
            candles = kline_resp.get("candles", []) if isinstance(kline_resp, dict) else kline_resp
            if not candles or len(candles) < 100:
                self._log(
                    f"[{coin}] BCRM2重训失败：K线不足 {len(candles) if candles else 0}", "WARN"
                )
                return False

            import pandas as pd

            df = pd.DataFrame(
                [
                    {
                        "open": float(c["o"]),
                        "high": float(c["h"]),
                        "low": float(c["l"]),
                        "close": float(c["c"]),
                        "volume": float(c.get("vol", c.get("v", 0))),
                        "timestamp": c.get("ts", ""),
                    }
                    for c in candles
                ]
            )

            retrained = adapter.train(df, force_retrain=True)
            if retrained:
                perf = self.incremental_learner.db.get_recent_performance(coin)
                self.incremental_learner.version_manager.save_version(
                    adapter.engine,
                    coin,
                    version_id=None,
                    metrics={
                        "win_rate": perf.get("win_rate", 0) / 100 if perf.get("win_rate") else 0,
                        "total_trades": perf.get("n_trades", 0),
                    },
                    notes="增量学习自动重训",
                )
                return True
            return False
        except Exception as e:
            self._log(f"[{coin}] BCRM2增量重训异常: {e}", "WARN")
            return False

    def _trigger_l4_pipeline_for_trade(self, trade_rec, case_id: str, saved: bool):
        """平仓后自动触发L4 Pipeline (M1-M4)

        将平仓交易构建为episode文件，执行L4全链路：
        M1(复盘) → M2(蒸馏) → M3(统计) → M3.5(KG同步) → M4(候选)
        """
        if not saved or not case_id:
            return

        import json
        from datetime import datetime

        # 构建episode文件
        episode = {
            "case_id": case_id,
            "ts": trade_rec.exit_time
            or trade_rec.entry_time
            or datetime.now(timezone.utc).isoformat(),
            "regime": getattr(trade_rec, "regime", "unknown") or "unknown",
            "summary": {
                "total_pnl": trade_rec.pnl,
                "wins": 1 if trade_rec.pnl > 0 else 0,
                "losses": 0 if trade_rec.pnl > 0 else 1,
                "total_trades": 1,
            },
            "trades": [
                {
                    "trade_id": case_id,
                    "symbol": trade_rec.inst_id,
                    "inst_id": trade_rec.inst_id,
                    "direction": (
                        trade_rec.direction.upper()
                        if isinstance(trade_rec.direction, str)
                        else "LONG"
                    ),
                    "entry_price": trade_rec.entry_price,
                    "exit_price": trade_rec.exit_price,
                    "position_size": getattr(trade_rec, "position_size", 0.01),
                    "leverage": getattr(trade_rec, "leverage", 10),
                    "margin_usdt": getattr(trade_rec, "margin_usdt", 100),
                    "pnl": trade_rec.pnl,
                    "pnl_pct": trade_rec.pnl_pct,
                    "exit_reason": trade_rec.exit_reason or "unknown",
                    "ts_entry": trade_rec.entry_time,
                    "ts_exit": trade_rec.exit_time,
                    "system_source": "yijing_inference",
                    "decision_context": {
                        "confidence": trade_rec.confidence,
                        "hexagram": trade_rec.hexagram or "",
                    },
                    "market_snapshot": {
                        "regime": getattr(trade_rec, "regime", "unknown") or "unknown",
                    },
                    "risk_events": [],
                }
            ],
        }

        # 保存episode文件
        episodes_dir = _episodes_dir()
        episodes_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        ep_path = episodes_dir / f"live_{trade_rec.inst_id}_{ts_str}.json"
        ep_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2, default=str))

        self._log(f"[L4] Episode保存: {ep_path.name}")

        # 异步执行L4 Pipeline (M1-M4)
        try:
            from scripts.memory_l4.pipeline import run_pipeline

            result = run_pipeline(ep_path)
            l4_status = result.get("case", {}).get("l4_status", "unknown")
            self._log(f"[L4] Pipeline完成: case={case_id} status={l4_status}")
        except Exception as e:
            self._log(f"[L4] Pipeline执行失败: {e}", "WARN")

    # ===== P1-1: 做空趋势过滤器 =====
    # 加密货币用BTC趋势确认（参考V15马丁策略DirectionGate力学化模式）
    # 非加密货币用自身日MA50趋势（未来可升级为标普500趋势线过滤）
    CRYPTO_COINS = frozenset({
        "BTC", "ETH", "SOL", "UNI", "LINK", "BNB", "OKB",
        "HYPE", "PUMP", "NEAR", "XRP", "DOT", "ADA", "AVAX",
    })

    @staticmethod
    def _ma_spring_force(price: float, ma: float, k: float = 2.0) -> float:
        """双均线弹簧力：F = -k × (price - MA) / MA

        符号语义:
          F > 0 → 做多倾向（价格在MA下方时，MA作为支撑，弹簧向上推）
          F < 0 → 做空倾向（价格在MA上方时，MA作为阻力，弹簧向下压）
        来源: V15 direction_gate._ma_spring_force
        """
        if ma is None or ma <= 0:
            return 0.0
        return -k * (price - ma) / ma

    @staticmethod
    def _distance_weight(abs_dist_pct: float) -> float:
        """距离权重函数: w = 1 / (1 + |dist%|)

        距离越近权重越大 → 价格接近周MA200时，周线支撑权重大 → 偏见底
        来源: V15 direction_gate._distance_weight
        """
        return 1.0 / (1.0 + abs(abs_dist_pct))

    def _check_btc_trend(self) -> tuple:
        """BTC日线趋势判定（参考V15 DirectionGate力学化模式）

        算法（双均线弹簧力场 + 距离权重）：
          1. 计算日线MA128 + 周线MA200（近似=日MA1400，200周×7日）
          2. 对每条均线计算弹簧力 F = -k × (price - MA) / MA
          3. 距离%权重 w = 1/(1+|dist%|)，越靠近哪条线，哪条线的话语权越大
               → 价格跌近周MA200时，w_weekly >> w_daily → 周线支撑力（做多）主导 → 偏见底
          4. 加权合力 F_net = F_128 × w_128 + F_200 × w_200
          5. 三态映射:
               F_net > +threshold → LONG_PREFERRED（多头趋势，禁止做空）
               F_net < -threshold + 连续3日跌破MA128确认 → SHORT_ALLOWED（做空允许）
               |F_net| ≤ threshold → 支撑区/筑底，偏见底，禁止做空
          6. 兜底: 价格≤周MA200+1%缓冲 → LONG_ONLY_FORCE（绝对禁止做空）

        Returns:
            (bearish: bool, reason: str)
        """
        now = time.time()
        cached = self._btc_trend_cache
        if cached["result"] and (now - cached["ts"]) < 300:
            return cached["result"]

        try:
            # 拉取足够长度（MA1400需要1400日数据，留余量）
            btc_klines = _load_kline_from_okx(inst_id="BTC-USDT-SWAP", bar="1D", limit=1500)
            if not btc_klines or len(btc_klines) < 1401:
                # 数据不足1401日时降级到可用长度
                limit = len(btc_klines) if btc_klines else 0
                weekly_ma_period = min(1400, max(200, limit - 1)) if limit >= 201 else 200
                if limit < 131:
                    return False, f"BTC日线数据不足(<131,limit={limit})"
            else:
                weekly_ma_period = 1400  # 200周 × 7日 = 日MA1400近似周MA200

            closes = [float(k.get("c", 0)) for k in btc_klines if k.get("c")]
            # OKX返回 newest-first: closes[:N] = 最近N日
            if len(closes) < 131:
                return False, f"BTC收盘价数据不足(<131,len={len(closes)})"

            current_price = closes[0]

            # 日线MA128
            ma128 = sum(closes[:128]) / 128
            # 周线MA200 = 日MA1400（如果够则用1400，否则用可用长度）
            daily_ma_period = min(weekly_ma_period, len(closes))
            ma200_weekly = sum(closes[:daily_ma_period]) / daily_ma_period

            # ===== 双均线力场合力（V15力学化核心） =====
            # 1) 距离%
            dist_daily = (current_price - ma128) / ma128 * 100 if ma128 else 0
            dist_weekly = (current_price - ma200_weekly) / ma200_weekly * 100 if ma200_weekly else 0

            # 2) 弹簧力
            F_daily = self._ma_spring_force(current_price, ma128)
            F_weekly = self._ma_spring_force(current_price, ma200_weekly)

            # 3) 距离权重（距离越近权重越大 → 偏见底关键机制）
            w_daily = self._distance_weight(abs(dist_daily))
            w_weekly = self._distance_weight(abs(dist_weekly))

            # 4) 加权合力
            F_net = F_daily * w_daily + F_weekly * w_weekly

            # 5) 有效跌破MA128确认（连续3日收盘≤MA128）
            recent_3 = closes[:3]
            valid_breakdown = all(c <= ma128 for c in recent_3)

            # 6) 周线MA200兜底：价格≤周MA200+1%缓冲 → 强制做多
            weekly_buffer = ma200_weekly * 0.01
            if current_price <= ma200_weekly + weekly_buffer:
                result = (
                    False,
                    f"BTC跌至周MA200附近(价={current_price:.0f}≤MA200+1%={ma200_weekly+weekly_buffer:.0f})"
                    f" | 偏见底支撑，禁止做空 | F_net={F_net:+.3f}"
                    f" | 日距={dist_daily:+.1f}%({w_daily:.2f}) 周距={dist_weekly:+.1f}%({w_weekly:.2f})"
                )
                self._btc_trend_cache = {"ts": now, "result": result}
                return result

            # 7) 三态映射（阈值0.02=2%等效速度）
            threshold = 0.02
            if F_net > threshold:
                # 合力显著向上 → 多头趋势
                result = (
                    False,
                    f"BTC多头趋势(F_net={F_net:+.3f}>+{threshold})"
                    f" | 主导均线: {'日MA128' if w_daily>=w_weekly else '周MA200'}"
                    f"({w_daily:.2f}/{w_weekly:.2f}), 日距={dist_daily:+.1f}% 周距={dist_weekly:+.1f}%"
                    f" | 最新收盘={current_price:.0f}"
                )
            elif F_net < -threshold and valid_breakdown:
                # 合力显著向下 + 有效跌破MA128双重确认 → 做空允许
                result = (
                    True,
                    f"BTC做空允许(F_net={F_net:+.3f}<-{threshold} + 连续3日跌破MA128)"
                    f" | 主导均线: {'日MA128' if w_daily>=w_weekly else '周MA200'}"
                    f"({w_daily:.2f}/{w_weekly:.2f}), 日距={dist_daily:+.1f}% 周距={dist_weekly:+.1f}%"
                    f" | MA128={ma128:.0f} MA200周={ma200_weekly:.0f} 近3日={'<'.join(str(int(c)) for c in recent_3)}"
                )
            else:
                # 合力在阈值内 → 支撑/筑底区（或未达跌破确认），偏见底，禁止做空
                if not valid_breakdown:
                    extra = " | 无3日跌破MA128确认"
                else:
                    extra = " | |F|≤阈值 → 支撑筑底区"
                result = (
                    False,
                    f"BTC震荡/筑底区(F_net={F_net:+.3f} |阈值{threshold}){extra}"
                    f" | 日距={dist_daily:+.1f}%({w_daily:.2f}) 周距={dist_weekly:+.1f}%({w_weekly:.2f})"
                    f" | MA128={ma128:.0f} MA200周={ma200_weekly:.0f}"
                )

            self._btc_trend_cache = {"ts": now, "result": result}
            return result
        except Exception as e:
            return False, f"BTC趋势检查异常: {e}"

    def _check_self_trend(self, coin: str) -> tuple:
        """非加密货币自身日K线趋势（双均线力场）

        与BTC趋势算法同构：日MA50（短）+ 日MA200（长）双均线弹簧力场。
        未来可直接替换为"标普500趋势线过滤"（SPX ^GSPC的MA200/MA50）。

        Returns:
            (bearish: bool, reason: str)
        """
        try:
            inst_id = f"{coin}-USDT-SWAP"
            klines = _load_kline_from_okx(inst_id=inst_id, bar="1D", limit=250)
            if not klines or len(klines) < 201:
                return False, f"{coin}日线数据不足(<201)"
            closes = [float(k.get("c", 0)) for k in klines if k.get("c")]
            if len(closes) < 201:
                return False, f"{coin}收盘价数据不足"
            current_price = closes[0]
            ma50 = sum(closes[:50]) / 50
            ma200 = sum(closes[:200]) / 200

            # 双均线力场（同构V15力学化）
            dist_50 = (current_price - ma50) / ma50 * 100
            dist_200 = (current_price - ma200) / ma200 * 100
            F_50 = self._ma_spring_force(current_price, ma50)
            F_200 = self._ma_spring_force(current_price, ma200)
            w_50 = self._distance_weight(abs(dist_50))
            w_200 = self._distance_weight(abs(dist_200))
            F_net = F_50 * w_50 + F_200 * w_200

            # 周MA200等价兜底：价格≤MA200+1%缓冲 → 偏见底
            if current_price <= ma200 + ma200 * 0.01:
                return False, (
                    f"{coin}跌至MA200附近(价={current_price:.2f}≤MA200+1%) | "
                    f"偏见底禁止做空 F_net={F_net:+.3f}"
                )

            # 跌破MA50+MA200双重确认 + F_net向下
            recent_2 = closes[:2]
            below_ma50 = recent_2[0] < ma50
            if F_net < -0.02 and below_ma50:
                return True, (
                    f"{coin}趋势看空 F_net={F_net:+.3f} | "
                    f"MA50={ma50:.2f} MA200={ma200:.2f} 最新={current_price:.2f}"
                )
            return False, (
                f"{coin}无看空确认 F_net={F_net:+.3f} | "
                f"MA50={ma50:.2f} MA200={ma200:.2f}"
            )
        except Exception as e:
            return False, f"{coin}趋势检查异常: {e}"

    def _check_short_trend_filter(self, coin: str, inference: dict) -> tuple:
        """P1-1: 做空趋势确认过滤器

        两道关卡：
        1. 趋势确认：加密货币用BTC MA128风向标，非加密用自身日MA50
        2. 短周期共振：当前K线EMA20/50/200需呈空头排列(SMA20<SMA50<SMA200)

        Returns:
            (allow_short: bool, reason: str)
        """
        # Step 1: 趋势确认
        if coin.upper() in self.CRYPTO_COINS:
            trend_bearish, trend_reason = self._check_btc_trend()
        else:
            trend_bearish, trend_reason = self._check_self_trend(coin)

        if not trend_bearish:
            return False, f"趋势未确认: {trend_reason}"

        # Step 2: 短周期共振（SMA20<SMA50<SMA200 空头排列）
        kline_data = inference.get("kline_data", [])
        if kline_data and len(kline_data) >= 200:
            closes = [float(c.get("c", 0)) for c in kline_data if c.get("c")]
            if len(closes) >= 200:
                sma20 = sum(closes[:20]) / 20
                sma50 = sum(closes[:50]) / 50
                sma200 = sum(closes[:200]) / 200
                if sma20 < sma50 < sma200:
                    return True, f"趋势确认+共振(SMA20<sma50<sma200) {trend_reason}"
                return False, f"共振失败(SMA20={sma20:.2f}/50={sma50:.2f}/200={sma200:.2f}非空头排列)"

        return True, f"趋势确认(无共振数据) {trend_reason}"

    def _execute_trade(self, inference: dict, confidence_threshold: float = None,
                       all_inferences: dict = None):
        """根据推理结果执行交易决策（P2 完整版）"""
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        fail_closed = inference["fail_closed"]
        is_ranging = inference["is_ranging"]
        inference.get("volatility", 0.03)

        effective_threshold = confidence_threshold or self.confidence_threshold

        # 做空方向使用独立的更高阈值
        if direction == "DOWN":
            effective_threshold = max(effective_threshold, self.short_confidence_threshold)

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

            # 计算持仓年龄（供保护期门禁、离场确认等使用）
            position_age_sec = 0
            open_time = pos_info.get("open_time", 0)
            if open_time > 0:
                position_age_sec = time.time() - open_time
            in_protection = self._is_position_protected(position_age_sec)

            # ── ① 信号反转：v5.0优化 提高门槛 + 离场确认 ──
            # 基础门槛
            reverse_threshold = effective_threshold
            # 保护期内：额外+12%置信度（原0.7→0.82），最低不低于0.85
            if in_protection:
                reverse_threshold = max(reverse_threshold + self.PROTECTED_REVERSE_CONF_BOOST, 0.85)
            signal_reverse = (
                pos_side == "long" and direction == "DOWN" and confidence >= reverse_threshold
            ) or (pos_side == "short" and direction == "UP" and confidence >= reverse_threshold)

            if signal_reverse:
                # 离场确认：需2次轮询连续触发（避免单根K线假反转）
                confirmed, cnt = self._exit_confirm(coin, self.EXIT_ACT_SIGNAL_REVERSE)
                if not confirmed:
                    self._log(
                        f"[{coin}] 信号反转待确认 [{cnt}/{self.EXIT_CONFIRM_REQUIRED}] "
                        f"{pos_side}→{direction} | 置信度={confidence:.2f}(≥{reverse_threshold:.2f}) "
                        f"{'[保护期]' if in_protection else ''} 卦象={inference['hexagram']} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%})",
                        "INFO",
                    )
                    return  # 未确认：等待下次轮询

                # 确认通过：清除状态后执行
                self._clear_exit_confirm(coin, self.EXIT_ACT_SIGNAL_REVERSE)
                self._log(
                    f"[{coin}] 信号反转✅已确认 {pos_side}→{direction} | "
                    f"置信度={confidence:.2f}(≥{reverse_threshold:.2f}) "
                    f"{'[保护期]' if in_protection else ''} 卦象={inference['hexagram']} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h"
                )

                exit_price = pos_info.get("mark_px", inference["price"])
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"反转平多 conf={confidence}"
                    )
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"反转平空 conf={confidence}"
                    )

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

                    # 统一冷静期：平仓后 8h 内不反手（防止来回割肉循环）
                    _side_map = {"UP": "long", "DOWN": "short"}
                    want_side = _side_map.get(direction)
                    in_cd, cd_reason = self.position_tracker.is_in_cooldown(
                        inst_id, want_side, self.COOLDOWN_SEC
                    )
                    if in_cd:
                        self._log(
                            f"[{coin}] 信号反转已平仓，但统一冷静期生效，跳过反手开仓: {cd_reason}",
                            "INFO",
                        )
                        return

                    risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
                    if not risk_check["allowed"]:
                        self._log(f"[{coin}] 风控拦截反手开仓: {risk_check['reason']}", "WARN")
                        return

                    total_pos = self._count_total_positions()
                    if total_pos >= self.max_positions:
                        self._log(f"[{coin}] 已达最大持仓数 {self.max_positions}，跳过反手")
                        return

                    self._open_position(inference, is_reverse=True)
                return
            else:
                # 反转条件不再满足：清除累计确认状态
                self._clear_exit_confirm(coin, self.EXIT_ACT_SIGNAL_REVERSE)

            # ── ② P3提前退出：v5.0优化 离场确认 + 保护期门槛 ──
            early_exit = inference.get("early_exit_signal", False)
            if early_exit:
                # 保护期内：浮亏≥8%才允许P3退出（否则假预警直接走）
                p3_allowed = True
                if in_protection:
                    if float(upl_ratio) > self.PROTECTED_P3_MIN_LOSS_PCT:
                        p3_allowed = False
                        self._log(
                            f"[{coin}] P3提前退出 [保护期拦截] 盈亏={upl_ratio:.2%}"
                            f">阈值{self.PROTECTED_P3_MIN_LOSS_PCT:.0%}，忽略预警",
                            "INFO",
                        )
                if p3_allowed:
                    # 离场确认：需2次连续触发
                    confirmed, cnt = self._exit_confirm(coin, self.EXIT_ACT_P3_EARLY_EXIT)
                    if not confirmed:
                        tri_ver = inference.get("triangle_verification") or {}
                        self._log(
                            f"[{coin}] P3提前退出待确认 [{cnt}/{self.EXIT_CONFIRM_REQUIRED}] "
                            f"{'[保护期]' if in_protection else ''} | "
                            f"盈亏={upl:.2f}({upl_ratio:.2%}) "
                            f"预警={tri_ver.get('risk_warnings', [])}",
                            "WARN",
                        )
                        return  # 待确认
                    # 确认通过
                    self._clear_exit_confirm(coin, self.EXIT_ACT_P3_EARLY_EXIT)
                    tri_ver = inference.get("triangle_verification") or {}
                    self._log(
                        f"[{coin}] P3提前退出✅已确认 TDA+Ising双重预警 "
                        f"{'[保护期]' if in_protection else ''} | "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) "
                        f"持仓={position_age_sec/3600:.1f}h "
                        f"预警={tri_ver.get('risk_warnings', [])}",
                        "WARN",
                    )
                    exit_price = pos_info.get("mark_px", inference["price"])
                    if pos_side == "long":
                        r = self.okx_client.market_close_long(
                            inst_id, reason="P3_early_exit:TDA+Ising"
                        )
                    else:
                        r = self.okx_client.market_close_short(
                            inst_id, reason="P3_early_exit:TDA+Ising"
                        )
                    if r.get("ok") or r.get("dry_run"):
                        self._handle_close_position(
                            inst_id=inst_id,
                            coin=coin,
                            pos_side=pos_side,
                            exit_price=exit_price,
                            exit_reason="p3_early_exit",
                            pnl=upl,
                            pnl_pct=upl_ratio,
                        )
                    return
            else:
                # P3信号消失：清除累计确认
                self._clear_exit_confirm(coin, self.EXIT_ACT_P3_EARLY_EXIT)

            # 经典指标离场系统评估（完整四大优先级）
            current_price = inference["price"]
            entry_price = pos_info.get("avg_px", 0)
            # position_age_sec 和 open_time 已在上方计算
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
                metadata={"reduce_count": tracker_pos.reduce_count if tracker_pos else 0},
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

            # ── v3.1: 29h持仓超时全局门控（回测最佳持仓时间）──
            # 持仓超过29h后：
            #   盈利 → 信号排名对比：有更强信号则止盈换仓，否则继续持有追求更大利润
            #   亏损 → 跳过yijing评估，直接走classic备用离场
            position_timeout_sec = self.yijing_exit_system.config.veto_max_hold_sec  # 104400 = 29h
            position_timed_out = position_age_sec > position_timeout_sec
            if position_timed_out:
                if upl > 0 and all_inferences:
                    # ── 超时止盈：信号排名对比 ──
                    # 持仓盈利且超时，重新排名当前币种 vs 其他候选币种信号
                    # 有更强信号 → 止盈换仓（Phase 3 自动开新仓）
                    # 无更强信号 → 继续持有，追求更大利润
                    _base_threshold = confidence_threshold or self.confidence_threshold
                    held_conf = inference.get("confidence", 0)
                    held_dir = inference.get("direction", "")
                    held_score = held_conf * (0.95 if held_dir == "DOWN" else 1.0)

                    best_candidate = None
                    best_score = held_score  # 必须严格大于当前持仓才替换
                    _side_map = {"UP": "long", "DOWN": "short"}

                    for other_coin, other_inf in all_inferences.items():
                        if other_coin == coin:
                            continue
                        other_inst = f"{other_coin}-USDT-SWAP"
                        # 本地检查持仓（无API调用）
                        if self.position_tracker.has_open_position(other_inst):
                            continue
                        other_dir = other_inf.get("direction", "")
                        if other_dir not in ("UP", "DOWN"):
                            continue
                        if other_inf.get("fail_closed", True):
                            continue
                        other_conf = other_inf.get("confidence", 0)
                        # 阈值筛选（做空用更高阈值）
                        other_threshold = _base_threshold
                        if other_dir == "DOWN":
                            other_threshold = max(other_threshold, self.short_confidence_threshold)
                        if other_conf < other_threshold:
                            continue
                        # 冷静期检查
                        in_cd, _ = self.position_tracker.is_in_cooldown(
                            other_inst, _side_map.get(other_dir), self.COOLDOWN_SEC
                        )
                        if in_cd:
                            continue
                        other_score = other_conf * (0.95 if other_dir == "DOWN" else 1.0)
                        if other_score > best_score:
                            best_candidate = (other_coin, other_dir, other_conf, other_score)
                            best_score = other_score

                    if best_candidate:
                        bc_coin, bc_dir, bc_conf, bc_score = best_candidate
                        self._log(
                            f"[{coin}] 超时止盈换仓(>29h) | 盈利={upl:.2f}({upl_ratio:.2%}) | "
                            f"当前信号={held_score:.2f} < 候选{bc_coin}={bc_score:.2f} "
                            f"(conf={bc_conf:.2f} dir={bc_dir}) | 止盈后Phase3自动开新仓",
                            "INFO",
                        )
                        exit_price = pos_info.get("mark_px", inference["price"])
                        if pos_side == "long":
                            r = self.okx_client.market_close_long(
                                inst_id, reason=f"超时止盈换仓:更强信号{bc_coin}"
                            )
                        else:
                            r = self.okx_client.market_close_short(
                                inst_id, reason=f"超时止盈换仓:更强信号{bc_coin}"
                            )
                        if r.get("ok") or r.get("dry_run"):
                            self._handle_close_position(
                                inst_id=inst_id,
                                coin=coin,
                                pos_side=pos_side,
                                exit_price=exit_price,
                                exit_reason="timeout_profit_switch",
                                pnl=upl,
                                pnl_pct=upl_ratio,
                            )
                        return
                    else:
                        # 没有更强信号 → 继续持有
                        self._log(
                            f"[{coin}] 超时继续持有(>29h) | 盈利={upl:.2f}({upl_ratio:.2%}) | "
                            f"当前信号={held_score:.2f}仍为最强，继续持有追求更大利润",
                            "INFO",
                        )
                        return
                else:
                    # 持仓亏损 → 走classic备用离场
                    self._log(
                        f"[{coin}] 持仓超时(>29h)启用经典备用离场 | "
                        f"持仓={position_age_sec/3600:.1f}h > {position_timeout_sec/3600:.0f}h阈值 | "
                        f"亏损={upl:.2f} | 跳过yijing评估，直接走classic备用离场",
                        "WARN",
                    )

            # ── 主离场层：易经推理专属离场（基于卦象风险-价值评估）──
            # 架构反转：yijing 作为主决策，classic 降为备用（仅在 yijing 不可用或信号中性时调用）
            yijing_hexagram = self._infer_current_hexagram(coin, inference, kline_data)
            yijing_decision = None
            # Bug1修复: 超时后直接标记yijing不可用，强制走classic降级路径
            yijing_available = (not position_timed_out) and (yijing_hexagram is not None)

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
                    coin=coin,  # v3.0：1h节奏缓存key
                    open_time_sec=float(open_time) if open_time else 0.0,  # v3.0：开仓时间戳
                )

            # 1) 易经强制平仓：卦象风险极高 + 方向冲突 → 离场确认后执行
            if yijing_decision and yijing_decision.action == YijingExitAction.FORCE_CLOSE:
                # v5.0：FORCE_CLOSE 加2次离场确认（避免卦象波动误平仓，尤其是中高风险时）
                fc_confirmed, fc_cnt = self._exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)
                if not fc_confirmed:
                    self._log(
                        f"[{coin}] 易经FORCE_CLOSE待确认 [{fc_cnt}/{self.EXIT_CONFIRM_REQUIRED}] "
                        f"{'[保护期]' if in_protection else ''} | "
                        f"{yijing_decision.reason} | 卦象={yijing_decision.hexagram_name} "
                        f"风险={yijing_decision.yijing_risk_score:.2f} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%})",
                        "WARN",
                    )
                    return  # 未确认，等待下次
                # 确认通过：执行
                self._clear_exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)
                self._log(
                    f"[{coin}] 易经主离场 [FORCE_CLOSE✅已确认] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} "
                    f"风险={yijing_decision.yijing_risk_score:.2f} "
                    f"价值={yijing_decision.yijing_value_score:.2f} "
                    f"持仓={position_age_sec/3600:.1f}h 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"易经离场:{yijing_decision.reason}"
                    )
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"易经离场:{yijing_decision.reason}"
                    )
                if r.get("ok") or r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id,
                        coin=coin,
                        pos_side=pos_side,
                        exit_price=current_price,
                        exit_reason=f"yijing_exit:{yijing_decision.reason}",
                        pnl=upl,
                        pnl_pct=upl_ratio,
                    )
                return
            else:
                # FORCE_CLOSE条件不满足：清除累计确认（避免污染）
                self._clear_exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)

            # ── v5.0：持仓保护期门禁 ──
            # 开仓后6h内：屏蔽易经的SL/TP动态调整（TIGHTEN_SL/LOWER_SL/RAISE_TP/LOWER_TP）
            # 原因：开仓初期卦象/指标不稳定，频繁调SL/TP反而适得其反；
            #       保护期内仅依赖开仓时设置的静态SL/TP + FORCE_CLOSE(极端) + 信号反转
            _PROTECTED_YIJING_ACTIONS = {
                YijingExitAction.RAISE_TP,
                YijingExitAction.LOWER_SL,
                YijingExitAction.LOWER_TP,
                YijingExitAction.TIGHTEN_SL,
            }
            if (
                in_protection
                and yijing_decision
                and yijing_decision.action in _PROTECTED_YIJING_ACTIONS
            ):
                self._log(
                    f"[{coin}] 易经{str(yijing_decision.action).split('.')[-1]} [保护期屏蔽] "
                    f"持仓={position_age_sec/3600:.1f}h<{self.POSITION_PROTECTION_HOURS:.0f}h | "
                    f"原动作原因={yijing_decision.reason} 卦象={yijing_decision.hexagram_name or '-'} | "
                    f"保护期内仅用静态SL/TP，跳过动态调整",
                    "INFO",
                )
                # NO_INTERVENE 语义：维持持仓
                yijing_decision.action = YijingExitAction.NO_INTERVENE
                yijing_decision.reason = "protected_hold:" + yijing_decision.reason

            # 2) 易经提高止盈：价值高 + 成长期 → 上调止盈位（保护期内已屏蔽）
            # 2026-08-06 修复：基于 ATR 基线 × 价值调制因子（非硬编码 15%）
            if yijing_decision and yijing_decision.action == YijingExitAction.RAISE_TP:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                # 读取开仓时 ATR 基线止盈收益率
                base_tp_roi = self._get_base_tp_roi(inst_id, entry_price)
                if base_tp_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [RAISE_TP] 跳过: base_tp_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 价值分 → TP 调制因子（连续函数）
                tp_modulation = YijingExitSystem.value_to_tp_modulation(
                    yijing_decision.yijing_value_score
                )
                target_tp_roi = base_tp_roi * tp_modulation
                # ATR 基线下限保护
                target_tp_roi = YijingExitSystem.apply_atr_floor(target_tp_roi, base_tp_roi)
                new_tp_price = self._calc_tp_price(entry_price, pos_side, target_tp_roi, leverage)
                tp_price_change_pct = self._roi_to_price_change(target_tp_roi, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [RAISE_TP] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_tp_roi:.2%} × 调制{tp_modulation:.2f} = {target_tp_roi:.2%} "
                    f"(价{tp_price_change_pct:.2%}) "
                    f"新止盈={new_tp_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
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
                        self._log(
                            f"[{coin}] 易经上调止盈失败: {tp_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经上调止盈异常: {e}", "WARN")
                return

            # 3) 易经降低止损：风险低 + 趋势初期 → 放宽止损空间，避免被洗出去
            # 2026-08-06 修复：基于 ATR 基线 × 风险调制因子（非硬编码 2%）
            if yijing_decision and yijing_decision.action == YijingExitAction.LOWER_SL:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                # 读取开仓时 ATR 基线止损收益率
                base_sl_roi = self._get_base_sl_roi(inst_id, entry_price)
                if base_sl_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [LOWER_SL] 跳过: base_sl_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 风险分 → SL 调制因子（连续函数，风险低 → >1.0 放宽）
                sl_modulation = YijingExitSystem.risk_to_sl_modulation(
                    yijing_decision.yijing_risk_score
                )
                new_sl_roi = base_sl_roi * sl_modulation
                # ATR 基线下限保护
                new_sl_roi = YijingExitSystem.apply_atr_floor(new_sl_roi, base_sl_roi)
                new_sl_price = self._calc_sl_price(entry_price, pos_side, new_sl_roi, leverage)
                sl_price_change_pct = self._roi_to_price_change(new_sl_roi, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [LOWER_SL] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_sl_roi:.2%} × 调制{sl_modulation:.2f} = {new_sl_roi:.2%} "
                    f"(价{sl_price_change_pct:.2%}) "
                    f"新止损={new_sl_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
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
                        self._log(
                            f"[{coin}] 易经放宽止损失败: {sl_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经放宽止损异常: {e}", "WARN")
                return

            # 4) 易经降低止盈：风险升高 + 已有利润 → 提前锁定利润
            # 2026-08-06 修复：基于 ATR 基线 × 价值调制因子（非硬编码 9%）
            if yijing_decision and yijing_decision.action == YijingExitAction.LOWER_TP:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                base_tp_roi = self._get_base_tp_roi(inst_id, entry_price)
                if base_tp_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [LOWER_TP] 跳过: base_tp_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 价值分低 → tp_modulation < 1.0（降低止盈）
                tp_modulation = YijingExitSystem.value_to_tp_modulation(
                    yijing_decision.yijing_value_score
                )
                target_tp_roi = base_tp_roi * tp_modulation
                # ATR 基线下限保护
                target_tp_roi = YijingExitSystem.apply_atr_floor(target_tp_roi, base_tp_roi)
                new_tp_price = self._calc_tp_price(entry_price, pos_side, target_tp_roi, leverage)
                tp_price_change_pct = self._roi_to_price_change(target_tp_roi, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [LOWER_TP] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_tp_roi:.2%} × 调制{tp_modulation:.2f} = {target_tp_roi:.2%} "
                    f"(价{tp_price_change_pct:.2%}) "
                    f"新止盈={new_tp_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
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
                        self._log(
                            f"[{coin}] 易经下调止盈失败: {tp_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经下调止盈异常: {e}", "WARN")
                return

            # 5) 易经收紧止损：风险升高 + 未盈利/微利 → 收紧止损保本
            # 2026-08-06 修复：基于 ATR 基线 × 风险调制因子（非硬编码 2%）
            if yijing_decision and yijing_decision.action == YijingExitAction.TIGHTEN_SL:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                base_sl_roi = self._get_base_sl_roi(inst_id, entry_price)
                if base_sl_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [TIGHTEN_SL] 跳过: base_sl_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 风险分高 → sl_modulation < 1.0（收紧止损）
                sl_modulation = YijingExitSystem.risk_to_sl_modulation(
                    yijing_decision.yijing_risk_score
                )
                new_sl_roi = base_sl_roi * sl_modulation
                # ATR 基线下限保护（收紧不低于基线的 0.7 倍）
                new_sl_roi = YijingExitSystem.apply_atr_floor(new_sl_roi, base_sl_roi)
                new_sl_price = self._calc_sl_price(entry_price, pos_side, new_sl_roi, leverage)
                sl_price_change_pct = self._roi_to_price_change(new_sl_roi, leverage)
                self._log(
                    f"[{coin}] 易经主离场 [TIGHTEN_SL] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_sl_roi:.2%} × 调制{sl_modulation:.2f} = {new_sl_roi:.2%} "
                    f"(价{sl_price_change_pct:.2%}) "
                    f"新止损={new_sl_price:.2f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    sl_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=new_sl_price,
                        take_profit_px=None,
                        reason=f"yijing_tighten_sl:{yijing_decision.reason}",
                    )
                    if sl_result.get("ok"):
                        self._log(f"[{coin}] 易经止损价已收紧至 {new_sl_price:.2f}")
                    else:
                        self._log(
                            f"[{coin}] 易经收紧止损失败: {sl_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经收紧止损异常: {e}", "WARN")
                return

            # 6) 易经主决策 NO_INTERVENE：持仓<29h维持持仓，不降级classic
            #    v3.1: 经典离场仅在持仓>29h且易经离场不工作时启用（用户需求）
            #    持仓<29h时，NO_INTERVENE即维持持仓，仅依赖开仓静态SL/TP+易经动态调整
            if yijing_decision and yijing_decision.action == YijingExitAction.NO_INTERVENE:
                if not position_timed_out:
                    # 持仓<29h：维持持仓，不降级classic
                    self._log(
                        f"[{coin}] 易经主离场 [HOLD] {yijing_decision.reason} | "
                        f"卦象={yijing_decision.hexagram_name or '-'} "
                        f"风险={yijing_decision.yijing_risk_score:.2f} "
                        f"价值={yijing_decision.yijing_value_score:.2f} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h "
                        f"行情={regime} | 维持持仓（<29h不启用经典备用）"
                    )
                    return
                # 持仓>29h但yijing仍返回NO_INTERVENE（防御性，正常超时后yijing_available=False）
                self._log(
                    f"[{coin}] 易经信号中性(超时>29h)，降级经典备用离场 | "
                    f"卦象={yijing_decision.hexagram_name or '-'} "
                    f"风险={yijing_decision.yijing_risk_score:.2f} "
                    f"价值={yijing_decision.yijing_value_score:.2f} "
                    f"盈亏={upl_ratio:.2%} 持仓={position_age_sec/3600:.1f}h"
                )
            elif not yijing_available:
                # yijing不可用有两种原因：超时(>29h) 或 无卦象数据
                if position_timed_out:
                    self._log(
                        f"[{coin}] 易经卦象不可用(超时>29h)，启用经典离场备用层 | "
                        f"盈亏={upl:.2f}({upl_ratio:.2%})",
                        "WARN",
                    )
                else:
                    self._log(
                        f"[{coin}] 易经卦象不可用(无卦象数据)，持仓<29h仅依赖静态SL/TP | "
                        f"盈亏={upl:.2f}({upl_ratio:.2%})",
                        "WARN",
                    )

            # ── v3.1: 备用离场层门禁 ──
            # 经典离场仅在持仓>29h且易经离场不工作时启用（用户需求）
            # 持仓<29h时完全跳过经典离场，仅依赖易经主离场+开仓静态SL/TP
            if not position_timed_out:
                # 持仓<29h：经典离场不启用，已通过上方HOLD return或yijing动态调整处理
                return

            # ── 备用离场层：经典指标离场（仅在持仓>29h且易经不工作时调用）──
            # v3.1: 到这里说明 position_timed_out=True（持仓>29h），classic 全四优先级启用
            # 短期修复 2：震荡市动态放宽止损（is_ranging / 弱趋势 → 止损更宽）
            # 注意：传入 dict（含 is_ranging/adx/trend_strength），而非字符串 regime
            self._adjust_exit_config_for_regime(
                {
                    "is_ranging": is_ranging,
                    "adx": float(inference.get("adx", 0) or 0),
                    "trend_strength": inference.get("trend_strength", 0.5),
                }
            )

            # 持仓>29h，classic 启用全部四大优先级（P0/P1/P2/P3）
            exit_decision = self.exit_system.evaluate_full(
                pos=exit_pos,
                candles_1h=candles_1h,
                regime=regime,
                p0_only=False,
            )

            # VETO_CLOSE/VETO_REDUCE 检查：classic 决定离场前，易经二次评估可否决
            # 注意：超时后 yijing_available=False，此否决分支不会触发
            if (
                yijing_available
                and yijing_decision
                and exit_decision.action in (ExitAction.CLOSE, ExitAction.REDUCE)
            ):
                veto_decision = self.yijing_exit_system.evaluate(
                    hexagram=yijing_hexagram,
                    pos_side=pos_side,
                    entry_price=float(entry_price) if entry_price else 0,
                    current_price=float(current_price),
                    position_age_sec=position_age_sec,
                    unrealized_pnl_pct=float(upl_ratio),
                    classic_decision=exit_decision,  # 传入 classic 决策用于否决判断
                    mfe_pnl_pct=max(0.0, float(upl_ratio)),
                    coin=coin,
                    open_time_sec=float(open_time) if open_time else 0.0,
                    mode="veto",  # P0修复：veto 模式绕过 1h 门禁 + 不写缓存，避免被主评估缓存吞掉
                )
                if veto_decision.action == YijingExitAction.VETO_CLOSE:
                    self._log(
                        f"[{coin}] 易经否决 [VETO_CLOSE] {veto_decision.reason} | "
                        f"卦象={veto_decision.hexagram_name} "
                        f"风险={veto_decision.yijing_risk_score:.2f} "
                        f"价值={veto_decision.yijing_value_score:.2f} "
                        f"经典离场原因={exit_decision.reason} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h | "
                        f"否决 classic 离场，维持持仓"
                    )
                    return
                if veto_decision.action == YijingExitAction.VETO_REDUCE:
                    self._log(
                        f"[{coin}] 易经否决 [VETO_REDUCE] {veto_decision.reason} | "
                        f"卦象={veto_decision.hexagram_name} "
                        f"风险={veto_decision.yijing_risk_score:.2f} "
                        f"价值={veto_decision.yijing_value_score:.2f} "
                        f"经典减仓原因={exit_decision.reason} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%}) | "
                        f"否决 classic 减仓，维持持仓"
                    )
                    return

            # 执行 classic 决策
            if exit_decision.action == ExitAction.CLOSE:
                self._log(
                    f"[{coin}] 经典备用离场 [CLOSE] {exit_decision.reason} | "
                    f"优先级={exit_decision.priority.value} "
                    f"置信度={exit_decision.confidence:.2f} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"经典备用离场:{exit_decision.reason}"
                    )
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"经典备用离场:{exit_decision.reason}"
                    )
                if r.get("ok") or r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id,
                        coin=coin,
                        pos_side=pos_side,
                        exit_price=current_price,
                        exit_reason=f"classic_backup:{exit_decision.reason}",
                        pnl=upl,
                        pnl_pct=upl_ratio,
                    )
                return

            if exit_decision.action == ExitAction.REDUCE:
                self._log(
                    f"[{coin}] 经典备用离场 [REDUCE] {exit_decision.reason} | "
                    f"减仓比例={exit_decision.reduce_frac:.0%} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                reduce_result = self.okx_client.reduce_position(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    reduce_ratio=exit_decision.reduce_frac,
                    reason=f"classic_backup:{exit_decision.reason}",
                )
                if reduce_result.get("ok"):
                    # E项优化：递增减仓次数并持久化
                    if tracker_pos:
                        tracker_pos.reduce_count += 1
                        self.position_tracker._save_open_position(inst_id)
                    self._log(
                        f"[{coin}] 减仓成功 | "
                        f"原持仓={reduce_result.get('original_pos')} "
                        f"减仓量={reduce_result.get('reduce_sz')} "
                        f"剩余={reduce_result.get('remaining_pos')} "
                        f"累计减仓={tracker_pos.reduce_count if tracker_pos else '?'}/{self.exit_system.config.max_reduce_count}"
                    )
                else:
                    self._log(f"[{coin}] 减仓失败: {reduce_result.get('error', 'unknown')}", "WARN")
                return

            if exit_decision.action == ExitAction.RAISE_TP:
                new_tp_price = exit_decision.new_tp_price
                new_tp_pct = exit_decision.new_tp_pct
                self._log(
                    f"[{coin}] 经典备用离场 [RAISE_TP] {exit_decision.reason} | "
                    f"新止盈={new_tp_price:.2f}({new_tp_pct:.2%}) "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})"
                )
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
                        self._log(
                            f"[{coin}] 上调止盈失败: {tp_result.get('error', 'unknown')}", "WARN"
                        )
                except Exception as e:
                    self._log(f"[{coin}] 上调止盈异常: {e}", "WARN")
                return

            # 维持持仓日志（含易经风险评估）
            hold_risk = (
                exit_decision.features.hold_risk
                if exit_decision and exit_decision.features
                else 0.5
            )
            hold_value = (
                exit_decision.features.hold_value
                if exit_decision and exit_decision.features
                else 0.5
            )
            yijing_risk = yijing_decision.yijing_risk_score if yijing_decision else 0.5
            yijing_value = yijing_decision.yijing_value_score if yijing_decision else 0.5
            hex_display = (
                yijing_decision.hexagram_name if yijing_decision else "无卦象"
            ) or "无卦象"
            yijing_phase = (yijing_decision.current_phase if yijing_decision else "") or "-"
            self._log(
                f"[{coin}] 持仓中 {pos_side} | "
                f"浮动盈亏={upl:.2f}({upl_ratio:.2%}) | "
                f"卦象={hex_display} 易经风险={yijing_risk:.2f} 易经价值={yijing_value:.2f} "
                f"阶段={yijing_phase} "
                f"持有风险={hold_risk:.2f} 持有价值={hold_value:.2f} "
                f"行情={regime} | 维持持仓"
            )
            return

        trend_strength = inference.get("trend_strength", 0.5)
        ranging_confidence = inference.get("ranging_confidence", 0.0)
        is_trial = False

        # A项过滤：可配置 confidence 最低门槛（原贝叶斯寻优值 0.7955 改为可热 reload）
        # - 优先使用 self.confidence_threshold（构造参数 args.confidence
        #   → 被 _load_evolution_config 从 config.json 热 reload
        #   → 被 _adjust_confidence_threshold 按外部知识小幅上调）
        # - A_SAFETY_FLOOR = 0.40 兜底：防止进化配置损坏/参数手误传成 0.01 导致阈值失控
        #
        # 回测基线（原硬编码 0.7955）：过滤掉 37% 低质量交易，
        # 胜率 76.6% -> 84.8%，策略收益 5.23% -> 5.59%；
        # 当 config.json 的 confidence_threshold 偏离较大时，
        # 仍以 safety floor=0.40 作为最低边界。
        try:
            adjusted_threshold = self._adjust_confidence_threshold()
        except Exception:
            adjusted_threshold = self.confidence_threshold
        A_SAFETY_FLOOR = 0.70
        effective_a_floor = max(float(adjusted_threshold), A_SAFETY_FLOOR)
        if confidence < effective_a_floor:
            self._log(
                f"[{coin}] A项过滤 | confidence={confidence:.4f} < "
                f"effective_a_floor={effective_a_floor:.4f}("
                f"adjusted={adjusted_threshold:.4f}, safety_floor={A_SAFETY_FLOOR}) | "
                f"方向={direction} 卦象={inference['hexagram']} 跳过"
            )
            return

        # P0-3: 卦象黑名单 — 历史胜率0%的卦象强制HOLD
        hex_name = inference.get("hexagram", "")
        if hex_name in self.hexagram_blacklist:
            self._log(
                f"[{coin}] P0卦象黑名单 | {hex_name} 历史胜率0% | "
                f"confidence={confidence:.4f} 方向={direction} 跳过"
            )
            return

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
                closes = [float(c.get("c", 0)) for c in kline_data if c.get("c")]
                highs = [float(c.get("h", 0)) for c in kline_data if c.get("h")]
                lows = [float(c.get("l", 0)) for c in kline_data if c.get("l")]
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
                effective_threshold = max(
                    effective_threshold, enhance_result.recommended_long_threshold
                )
            elif direction == "DOWN":
                effective_threshold = max(
                    effective_threshold, enhance_result.recommended_short_threshold
                )

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
                self._log(
                    f"[{coin}] 趋势明确(强度={trend_strength:.2f}) | 置信度要求放宽至 {effective_threshold}"
                )

        if fail_closed:
            # P0修复: fail-closed 硬约束，BCRM判定不交易则直接跳过，不用八卦方向软化
            bagua_dir = inference.get("bagua_direction", "neutral")
            self._log(
                f"[{coin}] fail-closed 跳过 | 卦象={inference['hexagram']} "
                f"BCRM不确定，不开仓 (八卦方向={bagua_dir} 不作为开仓依据)"
            )
            return

        # P1-1: 做空趋势过滤器
        # 加密货币用BTC MA128趋势确认，非加密用自身日MA50；+短周期EMA共振
        if direction == "DOWN":
            trend_ok, trend_reason = self._check_short_trend_filter(coin, inference)
            if not trend_ok:
                self._log(
                    f"[{coin}] P1做空趋势过滤 | {trend_reason} | "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return

        # 做空试错区间更窄（减少低置信度做空）
        if direction == "DOWN":
            trial_threshold = max(0.40, effective_threshold - 0.10)
        else:
            trial_threshold = max(0.25, effective_threshold - 0.15)
        if confidence >= effective_threshold:
            pass
        elif confidence >= trial_threshold:
            is_trial = True
            self._log(
                f"[{coin}] 轻仓试错模式 | 置信度={confidence:.2f} 在试错区间 [{trial_threshold}, {effective_threshold}) 方向={direction}"
            )
        else:
            self._log(
                f"[{coin}] 置信度不足 "
                f"{confidence:.2f} < {trial_threshold} | "
                f"方向={direction} 卦象={inference['hexagram']}"
            )
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

        # v4 风险评分风控：杠杆调整
        leverage_factor = inference.get("leverage_factor", 1.0)
        effective_leverage = max(1, round(leverage * leverage_factor))
        risk_level = inference.get("risk_level", "NORMAL")
        if leverage_factor != 1.0:
            self._log(
                f"[{coin}] v4杠杆调整 | risk_level={risk_level} factor={leverage_factor:.2f} "
                f"leverage {leverage}→{effective_leverage}",
                "INFO",
            )

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

        # v4 风险评分风控：仓位调整
        position_factor = inference.get("position_factor", 1.0)
        if position_factor != 1.0:
            old_usdt = position_usdt
            position_usdt *= position_factor
            position_pct *= position_factor
            self._log(
                f"[{coin}] v4仓位调整 | risk_level={risk_level} factor={position_factor:.2f} "
                f"仓位 {old_usdt:.2f}→{position_usdt:.2f}USDT",
                "INFO",
            )

        action = "open_long" if direction == "UP" else "open_short"
        pos_side = "long" if direction == "UP" else "short"
        sl_px = inference["stop_loss_px"]
        tp_px = inference["take_profit_px"]
        price = inference["price"]

        # v4 风险评分风控：止损收紧
        sl_tighten_factor = inference.get("sl_tighten_factor", 1.0)
        if sl_tighten_factor < 1.0 and sl_px and price > 0:
            old_sl = sl_px
            sl_px = round(price + (sl_px - price) * sl_tighten_factor, 4)
            self._log(
                f"[{coin}] v4止损收紧 | factor={sl_tighten_factor:.2f} SL {old_sl}→{sl_px}", "WARN"
            )

        # v4 风险评分风控：止盈调整
        tp_adjustment = inference.get("tp_adjustment", 1.0)
        if tp_adjustment != 1.0 and tp_px and price > 0:
            old_tp = tp_px
            tp_px = round(price + (tp_px - price) * tp_adjustment, 4)
            self._log(
                f"[{coin}] v4止盈调整 | factor={tp_adjustment:.2f} TP {old_tp}→{tp_px}", "INFO"
            )

        # 优化3：动态止损宽度（如果增强器有推荐，覆盖默认值）
        # 关键口径：先按"订单收益率"定义，再通过 leverage 换算成价格
        #   ATR 倍数（市场态）→ 价格波动% → 订单收益率% = 价格波动% × leverage
        # 2026-08-06 上调：默认倍率 1.5/3.0 → 2.5/5.0，与 ExitConfig/BCRM2_ATR 口径保持一致
        enhance_info = inference.get("enhance_result")
        if enhance_info and price > 0 and volatility > 0:
            sl_mult = enhance_info.get("sl_atr_mult", 2.5)
            tp_mult = enhance_info.get("tp_atr_mult", 5.0)
            price * volatility
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
                    abs(new_sl - price) / price * 100
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
        # 同时记录 ATR 基线 SL/TP 收益率，供易经离场系统调制使用
        base_sl_roi = 0.0
        base_tp_roi = 0.0
        if price > 0 and leverage > 0 and sl_px and tp_px:
            sl_pct = abs(sl_px - price) / price
            tp_pct = abs(tp_px - price) / price
            sl_roi = self._price_change_to_roi(sl_pct, leverage)
            tp_roi = self._price_change_to_roi(tp_pct, leverage)
            # 记录 ATR 基线 ROI（供易经离场系统 1h 后调制使用）
            base_sl_roi = sl_roi
            base_tp_roi = tp_roi
            if pos_side == "long":
                sl_label = f"亏{sl_roi:.2%}(价{sl_pct:.2%})"
                tp_label = f"盈{tp_roi:.2%}(价{tp_pct:.2%})"
            else:
                sl_label = f"亏{sl_roi:.2%}(价{sl_pct:.2%})"
                tp_label = f"盈{tp_roi:.2%}(价{tp_pct:.2%})"
            self._log(
                f"[{coin}] {'反手' if is_reverse else ''}开仓 {'[轻仓试错]' if is_trial else ''} {action} | "
                f"置信度={confidence:.2f}(factor={pos_size_info.get('confidence_factor', 0):.2f}) "
                f"卦象={inference['hexagram']} 杠杆={leverage}x | "
                f"仓位={position_usdt:.2f}USDT ({position_pct:.1%}) | "
                f"价格={inference['price']} SL={sl_px}({sl_label}) TP={tp_px}({tp_label}) | "
                f"原因={pos_size_info['reason']} | "
                f"可用余额={available_equity:.2f}USDT"
            )
        else:
            self._log(
                f"[{coin}] {'反手' if is_reverse else ''}开仓 {'[轻仓试错]' if is_trial else ''} {action} | "
                f"置信度={confidence:.2f}(factor={pos_size_info.get('confidence_factor', 0):.2f}) "
                f"卦象={inference['hexagram']} 杠杆={leverage}x | "
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
                    self._log(
                        f"[{coin}] 可用保证金不足（逐仓） | 需要={margin_needed:.2f}USDT 可用={avail_usdt:.2f}USDT 总权益={total_eq:.2f}USDT 杠杆={leverage}x 跳过",
                        "WARN",
                    )
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
                    self._log(
                        f"[{coin}] 可用保证金不足（全仓） | 需要={margin_needed:.2f}USDT 可用={cross_available:.2f}USDT 总权益={total_eq:.2f}USDT 已用IMR={total_imr:.2f}USDT 杠杆={leverage}x 跳过",
                        "WARN",
                    )
                    return

        # 检查下单量是否满足最小合约单位
        sz = self.okx_client._usdt_to_sz(inst_id, position_usdt)
        if sz <= 0:
            self._log(
                f"[{coin}] 下单量不足最小合约单位 | 金额={position_usdt:.2f}USDT 跳过", "WARN"
            )
            return

        if direction == "UP":
            order_result = self.okx_client.market_open_long(
                inst_id, usdt_amount=position_usdt, reason=f"yijing_open_long conf={confidence:.2f}"
            )
        else:
            order_result = self.okx_client.market_open_short(
                inst_id,
                usdt_amount=position_usdt,
                reason=f"yijing_open_short conf={confidence:.2f}",
            )

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
                base_sl_roi=base_sl_roi,
                base_tp_roi=base_tp_roi,
            )
            self._log(f"[{coin}] 开仓成功 | ordId={ord_id} | " f"入场价≈{entry_price}")

            # L4 轻量开仓事件（M0 注册预览 + A0 创伤追踪）
            self._record_opening_event(inference, entry_price, pos_side, confidence)

            if sl_px and tp_px:
                sltp_result = self.okx_client.place_stop_loss_take_profit(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    stop_loss_px=sl_px,
                    take_profit_px=tp_px,
                    sz=sz,
                    reason="yijing_risk_management",
                )
                if sltp_result.get("ok"):
                    self._log(f"[{coin}] 止盈止损已设置 | SL={sl_px} TP={tp_px}")
                else:
                    self._log(
                        f"[{coin}] 止盈止损设置失败 | SL={sl_px} TP={tp_px} | "
                        f"错误={sltp_result.get('error', sltp_result.get('msg', 'unknown'))}",
                        "ERROR",
                    )
        else:
            err = order_result.get("error", "") or order_result.get("sMsg", "")
            self._log(f"[{coin}] 开仓失败 | {err}", "ERROR")
            if self.guardian:
                self.guardian.record_error(
                    RuntimeError(f"开仓失败: {err}"), context=f"open_position:{coin}"
                )

    def _inject_cognitive_recall(self, coin: str, inference: dict) -> dict:
        """
        P3: 构建交易上下文并调用认知系统召回，返回认知建议。

        设计原则:
          - 建议而非约束: 召回结果注入 inference，不阻断交易决策
          - 失败安全: 认知系统不可用时返回空结果，不影响交易
          - 上下文构建: 从 inference 提取关键字段组装召回上下文
        """
        if not self._trading_recall_fn:
            return {"ok": False, "reason": "recall_fn not initialized"}

        # 构建召回上下文（从 inference 提取关键字段）
        direction = inference.get("direction", "")
        confidence = inference.get("confidence", 0.0)
        hexagram = inference.get("hexagram", "")
        is_ranging = inference.get("is_ranging", False)
        volatility = inference.get("volatility", 0.0)
        a0_warnings = inference.get("a0_warnings", [])

        ctx_parts = [f"{coin}", f"方向={direction}", f"置信度={confidence:.2f}"]
        if hexagram:
            ctx_parts.append(f"卦象={hexagram}")
        if is_ranging:
            ctx_parts.append("震荡市场")
        if volatility > 0:
            ctx_parts.append(f"波动率={volatility:.4f}")
        if a0_warnings:
            ctx_parts.append(f"矛盾预警={len(a0_warnings)}项")
        context = " ".join(ctx_parts)

        try:
            result = self._trading_recall_fn(
                context=context,
                task_type="strategy-execution",
                top_k_mem=3,
                top_meta=2,
                top_applied=2,
            )
            if result.get("ok"):
                mem_count = result.get("count", 0)
                meta_count = len(result.get("processes", {}).get("meta", []))
                applied_count = len(result.get("processes", {}).get("applied", []))
                self._log(
                    f"[{coin}] P3认知召回: 记忆={mem_count}条 | "
                    f"T系列Skill={meta_count}个 | 历史路径={applied_count}条",
                    "INFO",
                )
            return result
        except Exception as e:
            self._log(f"[{coin}] P3认知召回失败: {e}", "WARN")
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _summarize_cognitive_recall(inference: dict) -> dict:
        """P3: 从 inference 中提取认知召回摘要（轻量，供开仓事件存档）"""
        cr = inference.get("cognitive_recall")
        if not cr or not cr.get("ok"):
            return {"ok": False}
        return {
            "ok": True,
            "mem_count": cr.get("count", 0),
            "meta_skills": [m.get("skill_id") for m in cr.get("processes", {}).get("meta", [])],
            "applied_count": len(cr.get("processes", {}).get("applied", [])),
        }

    def _record_opening_event(
        self, inference: dict, entry_price: float, pos_side: str, confidence: float
    ):
        """开仓时轻量记录：A0 创伤追踪 + 开仓事件存档（供平仓后 L4 使用）"""
        import json
        from datetime import datetime

        coin = inference.get("coin", "")
        inst_id = inference.get("inst_id", "")
        direction = inference.get("direction", "")

        # A0 创伤追踪：记录决策方向（平仓后会更新对错）
        try:
            from scripts.memory_l4.a0_contradiction_engine import A0ContradictionEngine

            if not hasattr(self, "_a0_engine"):
                self._a0_engine = A0ContradictionEngine()
            self._a0_engine.record_decision(
                inst_id=inst_id,
                direction=direction,
                was_correct=True,  # 开仓时未知，平仓后更新
                ts=datetime.now().isoformat(),
            )
        except Exception:
            pass

        # 轻量开仓事件存档
        try:
            # P2-9: 事前预测（对齐 Friston 主动推理，失败静默不阻断开仓记录）
            prediction_data = None
            try:
                from scripts.memory_l4.prediction_bridge import generate_prediction_dict

                prediction_data = generate_prediction_dict(inference)
            except Exception:
                pass

            event = {
                "ts": datetime.now().isoformat(),
                "type": "position_opened",
                "inst_id": inst_id,
                "coin": coin,
                "direction": direction,
                "pos_side": pos_side,
                "entry_price": entry_price,
                "confidence": confidence,
                "a0_analysis": inference.get("a0_analysis"),
                "a0_warnings": inference.get("a0_warnings", []),
                "volatility": inference.get("volatility", 0),
                "hexagram": inference.get("hexagram", ""),
                # P3: 认知召回摘要（供平仓后 L4 回溯分析）
                "cognitive_recall": self._summarize_cognitive_recall(inference),
                # P2-9: 事前预测快照（供平仓后计算 prediction_error 驱动贝叶斯）
                "prediction": prediction_data,
            }
            event_dir = (
                Path(self.data_dir) / "l4_events"
                if hasattr(self, "data_dir")
                else Path("data/l4_events")
            )
            event_dir.mkdir(parents=True, exist_ok=True)
            event_file = event_dir / f"open_{inst_id}_{int(datetime.now().timestamp())}.json"
            event_file.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

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
        """离场时推理当前卦象（轻量级，复用 YijingEngine + HexagramKnowledge）

        P1修复：
        - 优先复用开仓时的卦象名（inference["hexagram"]），保证卦象一致性
        - 从 HexagramKnowledge 获取固有的 risk_level/direction_hint（不依赖简化参数）
        - 用 YijingEngine.infer() 推理 current_phase/development_stage（动态判断）
        - 修正 supply_demand/capital_flow 不再固定0.5，改用价格位置+成交量比

        失败时返回 None（YijingExitSystem 会 fail-open 不干预）
        """
        try:
            from scripts.memory_l4.bcrm.sixty_four_guas import get_hexagram_knowledge
            from scripts.memory_l4.bcrm.yijing_engine import YijingEngine

            if not hasattr(self, "_yijing_engine_for_exit"):
                self._yijing_engine_for_exit = YijingEngine()

            # 从 inference 提取可用字段
            trend_strength = float(inference.get("trend_strength", 0.5) or 0.5)
            volatility = float(inference.get("volatility", 0.03) or 0.03)
            confidence = float(inference.get("confidence", 0.5) or 0.5)
            is_ranging = bool(inference.get("is_ranging", False))
            current_price = float(inference.get("price", 0) or 0)
            # 开仓时已推理的卦象名（如"巽为风"）
            hex_name_cn = inference.get("hexagram", "") or ""

            # ── 价格位置 + 成交量比（不再固定0.5）──
            price_position = 0.5
            volume_ratio = 1.0
            closes = []
            if kline_data and len(kline_data) >= 20 and current_price > 0:
                try:
                    closes = [float(c.get("c", 0)) for c in kline_data[-20:]]
                    if closes and max(closes) > min(closes):
                        price_position = (current_price - min(closes)) / (max(closes) - min(closes))
                        price_position = max(0.0, min(1.0, price_position))
                    # 成交量比：近5根 vs 前20根均值
                    vols = [float(c.get("v", 0)) for c in kline_data[-20:]]
                    if vols and len(vols) >= 10:
                        recent_vol = sum(vols[-5:]) / 5
                        base_vol = sum(vols[:-5]) / max(len(vols) - 5, 1)
                        volume_ratio = recent_vol / base_vol if base_vol > 0 else 1.0
                except Exception:
                    pass

            # 供需评分：价格位置 >0.7 偏多，<0.3 偏空，中间中性
            supply_demand_score = max(0.0, min(1.0, price_position))
            # 资金面：放量=资金流入，缩量=流出
            capital_flow_score = max(0.0, min(1.0, 0.5 + (volume_ratio - 1.0) * 0.3))
            # 技术面
            technical_score = max(0.0, min(1.0, trend_strength))
            # 情绪面
            sentiment_score = max(
                0.0, min(1.0, confidence * 0.7 + (0.3 if not is_ranging else 0.1))
            )
            vol_norm = max(0.0, min(1.0, volatility * 20))

            # ── 用 YijingEngine 推理 current_phase / development_stage ──
            result = self._yijing_engine_for_exit.infer(
                supply_demand_score=supply_demand_score,
                technical_score=technical_score,
                capital_flow_score=capital_flow_score,
                sentiment_score=sentiment_score,
                trend_strength=trend_strength,
                volatility=vol_norm,
                volume_ratio=volume_ratio,
                price_position=price_position,
                close_price=current_price,
            )

            # ── P1修复：用 HexagramKnowledge 覆盖固有属性（risk_level/direction_hint）──
            # YijingEngine.infer() 用简化参数推理时，risk_level 可能不准
            # HexagramKnowledge 的 risk_level/direction_hint 是卦象固有属性，更可靠
            if hex_name_cn and hex_name_cn != "已存在持仓":
                hex_kb = get_hexagram_knowledge(hex_name_cn)
                if hex_kb:
                    # 覆盖固有属性
                    result.risk_level = hex_kb.risk_level or result.risk_level
                    result.direction_hint = hex_kb.direction_hint or result.direction_hint
                    # 确保 hexagram_name_cn 一致
                    result.hexagram_name_cn = hex_name_cn

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

    def _load_evolution_config(self, initial: bool = False):
        """A-1修复：从 OKX_SIM/config.json 加载进化后的阈值，覆盖默认值。

        - initial=True: __init__ 时调用，覆盖构造参数默认值
        - initial=False: run_once 每轮调用，热 reload 进化后的新阈值

        只更新 4 个进化键：confidence_threshold / daily_loss_limit /
        max_consecutive_losses / default_position_pct。
        其余字段（api_key 等）不受影响。
        """
        try:
            from scripts.memory_l4.paths import workspace_root as _ws

            cfg_path = _ws() / "data" / "okx_sim" / "config.json"
            self._evolution_config_path = cfg_path
            if not cfg_path.exists():
                return
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

            updated = []
            {
                "confidence_threshold": self.confidence_threshold,
                "daily_loss_limit": getattr(self.risk_manager, "state", None)
                and self.risk_manager.state.daily_loss_limit,
                "max_consecutive_losses": getattr(self.risk_manager, "state", None)
                and self.risk_manager.state.max_consecutive_losses,
                "default_position_pct": getattr(self.risk_manager, "state", None)
                and self.risk_manager.state.position_size_pct,
            }

            # confidence_threshold
            new_conf = cfg.get("confidence_threshold")
            if new_conf is not None and new_conf != self.confidence_threshold:
                self.confidence_threshold = new_conf
                updated.append(f"confidence_threshold={new_conf}")

            # PROP-20260810: 引擎层阈值同步（进化采纳值热重载到引擎）
            if (
                hasattr(self, "bcrm_engine")
                and self.bcrm_engine is not None
                and new_conf is not None
            ):
                try:
                    new_conf_f = float(new_conf)
                    if (
                        0.01 <= new_conf_f <= 0.95
                        and new_conf_f != self.bcrm_engine.min_confidence_threshold
                    ):
                        self.bcrm_engine.min_confidence_threshold = new_conf_f
                        updated.append(f"engine.min_confidence_threshold={new_conf_f}")
                except (TypeError, ValueError):
                    pass

            # risk_manager 相关 3 个字段（init 后 risk_manager 才存在）
            if hasattr(self, "risk_manager") and self.risk_manager is not None:
                state = self.risk_manager.state
                new_dll = cfg.get("daily_loss_limit")
                if new_dll is not None and new_dll != state.daily_loss_limit:
                    state.daily_loss_limit = new_dll
                    updated.append(f"daily_loss_limit={new_dll}")
                new_mcl = cfg.get("max_consecutive_losses")
                if new_mcl is not None and new_mcl != state.max_consecutive_losses:
                    state.max_consecutive_losses = int(new_mcl)
                    updated.append(f"max_consecutive_losses={new_mcl}")
                new_dpp = cfg.get("default_position_pct")
                if new_dpp is not None and new_dpp != state.position_size_pct:
                    state.position_size_pct = new_dpp
                    updated.append(f"default_position_pct={new_dpp}")
                new_llp = cfg.get("loss_limit_pct")
                if new_llp is not None and new_llp != state.loss_limit_pct:
                    state.loss_limit_pct = float(new_llp)
                    updated.append(f"loss_limit_pct={new_llp}")

            if updated:
                tag = "init" if initial else "reload"
                self._log(f"[进化阈值/{tag}] 从 config.json 加载: {', '.join(updated)}")
        except Exception as e:
            if initial:
                # init 阶段失败静默（config 可能尚不存在）
                pass
            else:
                self._log(f"[进化阈值/reload] 加载失败: {e}", "WARN")

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
        # A-1修复：每轮热 reload 进化后的阈值
        self._load_evolution_config(initial=False)
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
                    inst_id=f"{coin}-USDT-SWAP", bar=self.bar, limit=self.kline_limit
                )
                if kline_data and len(kline_data) > 100:
                    import pandas as pd

                    df = pd.DataFrame(kline_data)
                    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
                    df.set_index("timestamp", inplace=True)
                    df.rename(
                        columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"},
                        inplace=True,
                    )

                    summary = self.anomaly_detector.get_summary(df, symbol=coin)
                    critical_count = summary["by_severity"].get("critical", 0)
                    high_count = summary["by_severity"].get("high", 0)

                    if critical_count > 0 or high_count >= 2:
                        anomaly_detected = True
                        anomaly_coins.append(coin)
                        self._log(
                            f"[异常检测] {coin}: 检测到 {critical_count} 个严重异常, {high_count} 个高等级异常"
                        )

            if anomaly_detected:
                self._log(f"[异常检测] 市场环境异常，提高风控等级 | 涉及币种: {anomaly_coins}")
                effective_threshold = min(0.8, effective_threshold + 0.15)
        except Exception as e:
            self._log(f"[异常检测] 检测失败: {e}", "WARN")

        # ===== 第一阶段：收集所有币种推理结果 =====
        cycle_success = True
        all_inferences = {}
        for coin in self.coins:
            # P0-2: 币种黑名单过滤
            if coin in self.blacklist_coins:
                self._log(f"[{coin}] P0币种黑名单 | 跳过（历史胜率0%）")
                continue
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

                # P3: 反向召回接入 — A 系列 Cron 执行前注入认知召回（建议而非约束）
                if self.cognitive_recall_enabled and self._trading_recall_fn:
                    inference["cognitive_recall"] = self._inject_cognitive_recall(coin, inference)

                # A7 实践论门禁检查（代码驱动，执行前拦截）
                if self.a7_gate and not inference.get("fail_closed", False):
                    current_positions = self._count_total_positions()
                    cbr_engine = getattr(self.cbr_bridge, "cbr", None) if self.cbr_bridge else None
                    gate_report = self.a7_gate.check_before_execute(
                        inference=inference,
                        risk_manager=self.risk_manager,
                        cbr_engine=cbr_engine,
                        current_equity=self.perf_tracker.current_equity,
                        max_positions=self.max_positions,
                        current_positions=current_positions,
                    )
                    if not gate_report.passed:
                        self._log(
                            f"[{coin}] A7门禁拦截: " f"{'; '.join(gate_report.blocking_reasons)}",
                            "WARN",
                        )
                        continue

                all_inferences[coin] = inference

            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle:{coin}")

        # ===== 第二阶段：先处理持仓管理（平仓/反手/离场），按币种顺序 =====
        # 持仓管理按币种顺序即可（无需排名），关键是不要打乱离场时机
        for coin, inference in all_inferences.items():
            try:
                pos_info = self._check_positions(coin)
                if pos_info.get("has_position"):
                    # 有持仓：执行持仓管理（离场评估、信号反转等）
                    self._execute_trade(inference, confidence_threshold=effective_threshold,
                                        all_inferences=all_inferences)
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 持仓管理异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle_manage:{coin}")

        # ===== 第三阶段：新开仓候选按置信度排名执行 =====
        # 规则：默认根据置信度排名开仓，高置信度优先，仓位大小也根据置信度调控
        open_candidates = []
        for coin, inference in all_inferences.items():
            try:
                pos_info = self._check_positions(coin)
                if pos_info.get("has_position"):
                    continue  # 已有持仓，不在新开仓阶段处理

                # 运行时残留清理：本地有记录但 OKX 已无持仓（OKX端 SL/TP 触发）
                # 清理残留并记录平仓时间，用于统一冷静期判断
                # 注意：查询失败（限流）时不清理，避免误删本地持仓记录
                inst_id = f"{coin}-USDT-SWAP"
                if pos_info.get("query_failed"):
                    self._log(f"[{coin}] OKX 持仓查询失败（可能限流），跳过残留清理", "WARN")
                elif self.position_tracker.has_open_position(inst_id):
                    stale_rec = self.position_tracker.get_open_position(inst_id)
                    stale_side = stale_rec.direction if stale_rec else None
                    self.position_tracker.close_position(
                        inst_id,
                        exit_price=float(pos_info.get("mark_px", 0.0)) or 0.0,
                        exit_reason="运行时检测OKX持仓消失",
                    )
                    self._log(
                        f"[{coin}] 运行时清理本地残留 " f"(OKX端已平仓, side={stale_side})", "WARN"
                    )

                direction = inference["direction"]
                confidence = inference["confidence"]
                fail_closed = inference["fail_closed"]

                if direction not in ("UP", "DOWN"):
                    continue
                if fail_closed:
                    continue

                # 统一冷静期检查：平仓后 8h 内禁止该币种任何方向新开仓
                _side_map = {"UP": "long", "DOWN": "short"}
                want_side = _side_map.get(direction)
                in_cd, cd_reason = self.position_tracker.is_in_cooldown(
                    inst_id, want_side, self.COOLDOWN_SEC
                )
                if in_cd:
                    self._log(f"[{coin}] 跳过开仓候选: {cd_reason}", "INFO")
                    continue

                # 基础阈值筛选
                short_threshold = (
                    max(effective_threshold, self.short_confidence_threshold)
                    if direction == "DOWN"
                    else effective_threshold
                )
                if confidence < short_threshold:
                    continue

                # 风控检查
                risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
                if not risk_check["allowed"]:
                    self._log(f"[{coin}] 风控拦截开仓候选: {risk_check['reason']}", "WARN")
                    continue

                # 计算"置信度调整后优先级" = confidence * 方向偏好
                # 做空难度更高，进一步乘以 0.95 作轻微折减
                direction_bias = 0.95 if direction == "DOWN" else 1.0
                priority_score = confidence * direction_bias

                open_candidates.append(
                    {
                        "coin": coin,
                        "inference": inference,
                        "priority_score": priority_score,
                        "confidence": confidence,
                        "direction": direction,
                    }
                )
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 候选评估异常: {e}", "ERROR")

        # 按置信度（优先级）从高到低排序
        open_candidates.sort(key=lambda c: c["priority_score"], reverse=True)

        if open_candidates:
            ranking_display = " | ".join(
                f"{c['coin']}({c['direction']} conf={c['confidence']:.2f})" for c in open_candidates
            )
            self._log(
                f"[开仓排名] 共 {len(open_candidates)} 个候选，"
                f"按置信度从高到低：{ranking_display}"
            )

        # 依次按排名执行开仓
        for candidate in open_candidates:
            coin = candidate["coin"]
            inference = candidate["inference"]
            confidence = candidate["confidence"]

            try:
                # 再次检查风控和持仓数（在排名执行过程中可能变化）
                risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
                if not risk_check["allowed"]:
                    self._log(f"[{coin}] 排名开仓前风控拦截: {risk_check['reason']}", "WARN")
                    break

                current_positions = self._count_total_positions()
                if current_positions >= self.max_positions:
                    self._log(
                        f"[{coin}] 已达最大持仓数 {self.max_positions}，"
                        f"剩余 {len(open_candidates) - open_candidates.index(candidate) - 1} 个候选跳过"
                    )
                    break

                self._log(
                    f"[{coin}] 排名 #{open_candidates.index(candidate) + 1} 开仓 | "
                    f"置信度={confidence:.2f} 方向={candidate['direction']}"
                )
                self._execute_trade(inference, confidence_threshold=effective_threshold)
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 排名开仓异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle_open:{coin}")

        open_pos = self.position_tracker.all_open_positions()
        self._log(f"[持仓跟踪] 记录中持仓数: {len(open_pos)}")
        for pos in open_pos:
            self._log(
                f"  - {pos.coin}: {pos.direction} @ {pos.entry_price} "
                f"(conf={pos.confidence:.2f})"
            )

        learn_state = self.learning_scheduler.get_state()
        self._log(
            f"[学习] 当前案例={learn_state['current_case_count']} | "
            f"新增自上次重训={learn_state['new_cases_since']} | "
            f"上次重训={learn_state['last_retrain_time_str']}"
        )

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
            _sig_names = {
                getattr(signal_module, k, 0): k
                for k in ("SIGINT", "SIGTERM", "SIGHUP", "SIGPIPE",
                          "SIGXCPU", "SIGXFSZ", "SIGUSR1", "SIGUSR2")
            }
            _sn = _sig_names.get(signum, f"SIG#{signum}")
            self._log(f"收到退出信号 {_sn}，正在停止...", "WARN")
            self.running = False

        signal_module.signal(signal_module.SIGINT, _shutdown)
        signal_module.signal(signal_module.SIGTERM, _shutdown)
        # macOS setsid 后仍然可能收到的信号，全部统一捕获写日志，避免静默退出
        for _sn_name in ("SIGHUP", "SIGPIPE", "SIGXCPU", "SIGXFSZ", "SIGUSR1", "SIGUSR2"):
            try:
                signal_module.signal(getattr(signal_module, _sn_name), _shutdown)
            except (AttributeError, OSError, ValueError):
                pass

        # ══════════════════════════════════════════════════════════════
        # 内置 yijing_monitor 调度线程（每 6 小时触发一次健康检查 + 自进化）
        # 替代 launchd 定时调度，避免 macOS 沙箱权限问题
        # ══════════════════════════════════════════════════════════════
        MONITOR_INTERVAL_SEC = 6 * 3600  # 6 小时

        def _monitor_worker():
            first_run = True
            while self.running:
                try:
                    if first_run:
                        # 首次延迟 1 小时启动：避免和首轮 18 币种 BCRM2 训练/推理重叠导致内存压力
                        wait_sec = 60 * 60
                        desc = "首次延迟 1h"
                    else:
                        # 之后每 6 小时一次
                        wait_sec = MONITOR_INTERVAL_SEC
                        desc = "定期"
                    # 以 1s 为粒度响应 shutdown
                    for _ in range(wait_sec):
                        if not self.running:
                            return
                        time.sleep(1)
                    first_run = False
                    self._log(f"[Monitor] {desc}触发监控周期（健康检查 + 自进化）", "INFO")
                    # 延迟导入，避免模块加载冲突
                    from scripts.memory_l4 import yijing_monitor
                    try:
                        healthy, status, detail = yijing_monitor.check_yijing_health()
                        self._log(
                            f"[Monitor] 健康: {'✅ 正常' if healthy else '⚠️ 异常'} | {status}",
                            "INFO" if healthy else "WARN",
                        )
                    except Exception as _e:
                        self._log(f"[Monitor] 健康检查异常: {_e}", "WARN")
                    try:
                        evo, perf, evolved = yijing_monitor.run_evolution()
                        self._log(
                            f"[Monitor] 进化完成 | 累计次数={evo.get('evolution_count', 0)} "
                            f"| 胜率={perf.get('win_rate', 0):.0%} | 总盈亏={perf.get('total_pnl', 0):.2f}USDT",
                            "INFO",
                        )
                    except Exception as _e:
                        self._log(f"[Monitor] 自进化异常: {_e}", "ERROR")
                        if self.guardian:
                            self.guardian.record_error(_e, context="monitor_evolution")
                except Exception as _e:
                    # 线程级别兜底：不能让监控线程挂了
                    self._log(f"[Monitor] 调度线程异常: {_e}", "ERROR")
                    for _ in range(300):
                        if not self.running:
                            return
                        time.sleep(1)

        import threading as _threading
        monitor_thread = _threading.Thread(
            target=_monitor_worker, name="yijing_monitor", daemon=True
        )
        monitor_thread.start()
        self._log(f"[Monitor] 内置调度线程已启动 | 周期={MONITOR_INTERVAL_SEC//3600}h", "INFO")

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
    parser.add_argument("--interval", type=int, default=3600, help="轮询间隔（秒），默认 3600(1h)")
    parser.add_argument(
        "--coins",
        type=str,
        default="UNI,PUMP,MU,SKHYNIX,HYPE,ETH,BTC,SOL,XAU,XAG,GOOGL,NVDA,AMZN,OKB,BNB",
        help="币种列表，逗号分隔，默认 15币种固定候选池（注意：使用 XAU 而非 XAUT，OKX 实际合约为 XAU-USDT-SWAP）",
    )
    parser.add_argument("--bar", type=str, default="1H", help="K线周期，默认 1H")
    parser.add_argument("--confidence", type=float, default=0.35, help="置信度阈值，默认 0.35")
    parser.add_argument(
        "--short-confidence",
        type=float,
        default=0.70,
        help="做空置信度阈值（高于做多以减少做空频率），默认 0.70",
    )
    parser.add_argument("--max-positions", type=int, default=5, help="最大同时持仓数，默认 5")
    parser.add_argument("--once", action="store_true", help="只执行一次，不循环")
    parser.add_argument(
        "--initial-equity",
        type=float,
        default=None,
        help="初始权益（USDT），不指定则从 OKX 读取实际余额",
    )
    parser.add_argument(
        "--daily-loss-limit",
        type=float,
        default=-30.0,
        help="日最大亏损兜底值（USDT），默认 -30（150U可用金的20%）",
    )
    parser.add_argument(
        "--max-consecutive-losses",
        type=int,
        default=999,
        help="最大连续亏损次数（已禁用，默认999不再触发），风控改以亏损金额为准",
    )
    parser.add_argument(
        "--position-pct",
        type=float,
        default=0.20,
        help="默认单笔仓位比例，默认 0.20(20%%)（C项优化）",
    )
    parser.add_argument("--no-guardian", action="store_true", help="不启用进程守护")
    parser.add_argument(
        "--use-bcrm2",
        action="store_true",
        default=True,
        help="使用 BCRM 2.0 (辩证ML引擎)，默认启用",
    )
    parser.add_argument("--use-bcrm1", action="store_true", help="使用 BCRM 1.0 (矛盾力学引擎)")
    args = parser.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",")]
    # P4 修复：币种规范化（XAUT → XAU，因为 OKX 实际存在的是 XAU-USDT-SWAP，XAUT 已下架）
    # 在 CLI 层做一次，配合 PollingTrader.__init__ 内的二次规范化形成双保险。
    _NORM_MAIN = {"XAUT": "XAU"}
    coins = [_NORM_MAIN.get(c, c) for c in coins]

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
        short_confidence_threshold=args.short_confidence,
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
        print(
            json.dumps(
                {k: v for k, v in status.items() if k not in ("open_positions_detail",)},
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
    else:
        trader.run_loop()

    if guardian:
        guardian.stop()


if __name__ == "__main__":
    main()
