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


class PollingTrader:
    """易经推理轮询交易器（P2 完整版）"""

    def __init__(self,
                 interval: int = 300,
                 coins: list = None,
                 bar: str = "1H",
                 confidence_threshold: float = 0.45,
                 max_positions: int = 3,
                 kline_limit: int = 200,
                 initial_equity: float = 10000.0,
                 daily_loss_limit: float = -100.0,
                 max_consecutive_losses: int = 5,
                 default_position_pct: float = 0.10,
                 guardian: ProcessGuardian = None):
        self.interval = interval
        self.coins = coins or ["BTC", "ETH"]
        self.bar = bar
        self.confidence_threshold = confidence_threshold
        self.max_positions = max_positions
        self.kline_limit = kline_limit

        self.bcrm_engine = BCRMEngine()
        self.bagua_engine = BaguaEngine()
        self.okx_client = OKXSimulatedClient()

        self.running = False
        self.cycle_count = 0
        self.last_date = datetime.now().strftime("%Y-%m-%d")

        self.perf_tracker = PerformanceTracker(initial_equity=initial_equity)
        self.risk_manager = RiskManager(
            daily_loss_limit_usdt=daily_loss_limit,
            max_consecutive_losses=max_consecutive_losses,
            default_position_pct=default_position_pct,
        )
        self.position_tracker = PositionTracker()
        self.learning_scheduler = LearningScheduler(
            bcrm_engine=self.bcrm_engine,
            retrain_interval_cases=10,
            retrain_interval_hours=4,
            on_retrain_complete=self._on_retrain_complete,
        )
        self.guardian = guardian

        self.log_dir = Path("data/polling_trader")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"trader_{datetime.now().strftime('%Y%m%d')}.jsonl"

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
                )
                self._log(f"[持仓同步] 已同步 {coin} {pos['pos_side']} @ {pos['avg_px']}", "INFO")

        open_count = len(self.position_tracker.all_open_positions())
        self._log(f"[持仓同步] 完成，共 {open_count} 个持仓", "INFO")

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

        sl_px, tp_px, reduce_ratio = 0, 0, 0
        if bcrm_result.strategy_branches:
            b1 = next((b for b in bcrm_result.strategy_branches
                       if b.branch_id == "B1"), None)
            if b1:
                sl_px = b1.stop_loss_px
                tp_px = b1.take_profit_px
                reduce_ratio = b1.reduce_ratio

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
        }

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

    def _handle_close_position(self, inst_id: str, coin: str,
                                pos_side: str, exit_price: float,
                                exit_reason: str, pnl: float, pnl_pct: float):
        """处理平仓：生成交易记录、更新绩效、生成 case、更新风控

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

            retrain_result = self.learning_scheduler.trigger_retrain()
            if retrain_result.get("retrained"):
                self._log(f"[{coin}] 触发重训: {retrain_result.get('reason')}")

            return perf_summary
        else:
            self._log(f"[{coin}] 警告：平仓但无对应开仓记录 {inst_id}", "WARN")
            return {}

    def _execute_trade(self, inference: dict):
        """根据推理结果执行交易决策（P2 完整版）"""
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        fail_closed = inference["fail_closed"]
        is_ranging = inference["is_ranging"]
        volatility = inference.get("volatility", 0.03)

        pos_info = self._check_positions(coin)

        if pos_info.get("has_position"):
            pos_side = pos_info["pos_side"]
            upl = pos_info.get("upl", 0)
            upl_ratio = pos_info.get("upl_ratio", 0)

            signal_reverse = (
                (pos_side == "long" and direction == "DOWN"
                 and confidence >= self.confidence_threshold)
                or
                (pos_side == "short" and direction == "UP"
                 and confidence >= self.confidence_threshold)
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

            self._log(f"[{coin}] 持仓中 {pos_side} | "
                      f"浮动盈亏={upl:.2f}({upl_ratio:.2%}) | 维持持仓")
            return

        if fail_closed:
            self._log(f"[{coin}] fail-closed 跳过 | 卦象={inference['hexagram']}")
            return

        effective_threshold = self.confidence_threshold
        if is_ranging:
            effective_threshold = max(self.confidence_threshold, 0.5)
            self._log(f"[{coin}] 震荡市 | 置信度要求提高至 {effective_threshold}")

        if confidence < effective_threshold:
            self._log(f"[{coin}] 置信度不足 "
                      f"{confidence:.2f} < {effective_threshold} | "
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

        self._open_position(inference, is_reverse=False)

    def _open_position(self, inference: dict, is_reverse: bool = False):
        """开仓（动态仓位 + 持仓跟踪）"""
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        volatility = inference.get("volatility", 0.03)

        pos_size_info = self.risk_manager.calc_position_size(
            confidence=confidence,
            volatility=volatility,
            current_equity=self.perf_tracker.current_equity,
        )
        position_usdt = pos_size_info["position_usdt"]
        position_pct = pos_size_info["position_pct"]

        action = "open_long" if direction == "UP" else "open_short"
        pos_side = "long" if direction == "UP" else "short"
        sl_px = inference["stop_loss_px"]
        tp_px = inference["take_profit_px"]

        self._log(
            f"[{coin}] {'反手' if is_reverse else ''}开仓 {action} | "
            f"置信度={confidence:.2f} 卦象={inference['hexagram']} | "
            f"仓位={position_usdt:.2f}USDT ({position_pct:.1%}) | "
            f"价格={inference['price']} 止损={sl_px} 止盈={tp_px} | "
            f"原因={pos_size_info['reason']}"
        )

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

    def run_once(self):
        """执行一轮推理 + 交易"""
        self._check_date_rollover()
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

                self._execute_trade(inference)

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
    parser.add_argument("--interval", type=int, default=300,
                        help="轮询间隔（秒），默认 300")
    parser.add_argument("--coins", type=str, default="BTC,ETH",
                        help="币种列表，逗号分隔，默认 BTC,ETH")
    parser.add_argument("--bar", type=str, default="1H",
                        help="K线周期，默认 1H")
    parser.add_argument("--confidence", type=float, default=0.45,
                        help="置信度阈值，默认 0.45")
    parser.add_argument("--max-positions", type=int, default=3,
                        help="最大同时持仓数，默认 3")
    parser.add_argument("--once", action="store_true",
                        help="只执行一次，不循环")
    parser.add_argument("--initial-equity", type=float, default=10000.0,
                        help="初始权益（USDT），默认 10000")
    parser.add_argument("--daily-loss-limit", type=float, default=-100.0,
                        help="日最大亏损（USDT），默认 -100")
    parser.add_argument("--max-consecutive-losses", type=int, default=5,
                        help="最大连续亏损次数，默认 5")
    parser.add_argument("--position-pct", type=float, default=0.10,
                        help="默认单笔仓位比例，默认 0.10(10%%)")
    parser.add_argument("--no-guardian", action="store_true",
                        help="不启用进程守护")
    args = parser.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",")]

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
