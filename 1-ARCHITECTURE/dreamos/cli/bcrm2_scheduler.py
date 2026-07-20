"""
BCRM 2.0 升级版自动化调度器

核心架构:
  - WDH时间特征引擎 (周/日/时三屏 + 量变质变规律)
  - 美林时钟周期特征 (跨资产资金流动周期)
  - 增量学习闭环 (交易→学习→再交易→再学习)
  - 模型版本管理 (版本保存/加载/回滚/清理)

完整S-A-C-G编排流程:
  S层: 意图识别 (场景分类 + 编排记忆表查询)
  A层: 图编排 (A0-A9决策链)
  C层: 资源分配 (算力/预算/特征工程)
  G层: 风险管理 (风险控制 + 离场策略 + 情报监控)

[DEPRECATED 2026-07-19] 本文件已废弃,统一使用 start_scheduler.py 作为唯一调度器入口。
    launchd 守护进程通过 com.dreambuddy.dreamos.plist 拉起 start_scheduler.py。
    本文件保留作历史参考,请勿新增依赖。

支持币种: BTC, ETH, SOL, AVAX, LINK, DOT, MATIC, BNB, OP, ARB
"""

from __future__ import annotations

import os
import sys
import time
import json
import logging
import threading
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)

_BCRM2_SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "MATIC", "BNB", "OP", "ARB"]


class TradeAction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"
    EXIT = "EXIT"


class ExecutionPhase(str, Enum):
    ANALYSIS = "analysis"
    RISK_CHECK = "risk_check"
    EXECUTION = "execution"
    EXIT_CHECK = "exit_check"
    LEARNING = "learning"
    MONITORING = "monitoring"


class BCRM2TradeRecord:
    """BCRM 2.0交易记录"""
    
    def __init__(self):
        self.id: Optional[int] = None
        self.timestamp: str = datetime.now().isoformat()
        self.symbol: str = ""
        self.direction: str = TradeAction.HOLD.value
        self.entry_price: float = 0.0
        self.exit_price: float = 0.0
        self.pnl_pct: float = 0.0
        self.confidence: float = 0.0
        self.model_version: str = ""
        self.hexagram: str = ""
        self.upper_gua: str = ""
        self.lower_gua: str = ""
        self.exit_reason: str = ""
        self.execution_time_ms: float = 0.0
        self.wdh_features_used: bool = False
        self.merrill_clock_enabled: bool = False
        self.incremental_learning_enabled: bool = False
        self.notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl_pct": self.pnl_pct,
            "confidence": self.confidence,
            "model_version": self.model_version,
            "hexagram": self.hexagram,
            "upper_gua": self.upper_gua,
            "lower_gua": self.lower_gua,
            "exit_reason": self.exit_reason,
            "execution_time_ms": self.execution_time_ms,
            "wdh_features_used": self.wdh_features_used,
            "merrill_clock_enabled": self.merrill_clock_enabled,
            "incremental_learning_enabled": self.incremental_learning_enabled,
            "notes": self.notes,
        }


class BCRM2Database:
    """BCRM 2.0 SQLite数据库"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            project_root = str(Path(__file__).parent.parent.parent.parent)
            db_path = str(Path(project_root) / "data" / "bcrm_trades.db")
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL,
                pnl_pct REAL,
                confidence REAL,
                model_version TEXT,
                hexagram TEXT,
                upper_gua TEXT,
                lower_gua TEXT,
                exit_reason TEXT,
                execution_time_ms REAL,
                wdh_features_used INTEGER,
                merrill_clock_enabled INTEGER,
                incremental_learning_enabled INTEGER,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, timestamp, direction)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_versions (
                version_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sharpe_ratio REAL,
                win_rate REAL,
                total_trades INTEGER,
                train_bars INTEGER,
                feature_count INTEGER,
                status TEXT DEFAULT 'active',
                notes TEXT,
                wdh_enabled INTEGER,
                merrill_enabled INTEGER
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                cycle_id TEXT,
                intent_type TEXT,
                confidence REAL,
                action TEXT,
                rationale TEXT,
                latency_ms REAL,
                path TEXT,
                scenario TEXT,
                orchestration TEXT,
                nodes_executed INTEGER,
                tokens_used INTEGER,
                success INTEGER
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS performance_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                start_date TEXT,
                end_date TEXT,
                n_trades INTEGER,
                win_rate REAL,
                avg_pnl REAL,
                max_pnl REAL,
                min_pnl REAL,
                total_pnl REAL,
                sharpe_ratio REAL,
                max_drawdown REAL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def save_trade(self, record: BCRM2TradeRecord) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO trades (
                    timestamp, symbol, direction, entry_price, exit_price,
                    pnl_pct, confidence, model_version, hexagram, upper_gua,
                    lower_gua, exit_reason, execution_time_ms, wdh_features_used,
                    merrill_clock_enabled, incremental_learning_enabled, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.timestamp,
                record.symbol,
                record.direction,
                record.entry_price,
                record.exit_price,
                record.pnl_pct,
                record.confidence,
                record.model_version,
                record.hexagram,
                record.upper_gua,
                record.lower_gua,
                record.exit_reason,
                record.execution_time_ms,
                1 if record.wdh_features_used else 0,
                1 if record.merrill_clock_enabled else 0,
                1 if record.incremental_learning_enabled else 0,
                record.notes,
            ))
            conn.commit()
            return cursor.lastrowid
        except Exception:
            conn.rollback()
            return -1
        finally:
            conn.close()
    
    def save_analysis_log(self, symbol: str, analysis_result: Dict) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT INTO analysis_logs (
                    timestamp, symbol, cycle_id, intent_type, confidence,
                    action, rationale, latency_ms, path, scenario,
                    orchestration, nodes_executed, tokens_used, success
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                symbol,
                analysis_result.get("cycle_id", ""),
                analysis_result.get("intent", {}).get("type", ""),
                analysis_result.get("confidence", 0),
                analysis_result.get("action", "HOLD"),
                json.dumps(analysis_result.get("rationale", []), ensure_ascii=False),
                analysis_result.get("latency_ms", 0),
                analysis_result.get("_path", ""),
                analysis_result.get("_scenario", ""),
                analysis_result.get("_orchestration", ""),
                analysis_result.get("execution", {}).get("nodes_executed", 0),
                analysis_result.get("tokens_used", 0),
                1 if not analysis_result.get("error") else 0,
            ))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.warning(f"保存分析日志失败: {e}")
            conn.rollback()
            return -1
        finally:
            conn.close()
    
    def save_model_version(self, version_id: str, symbol: str, metrics: Dict,
                           wdh_enabled: bool = True, merrill_enabled: bool = True, notes: str = "") -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO model_versions (
                    version_id, symbol, created_at, sharpe_ratio, win_rate,
                    total_trades, train_bars, feature_count, status, notes,
                    wdh_enabled, merrill_enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                version_id,
                symbol,
                datetime.now().isoformat(),
                metrics.get("sharpe_ratio", 0),
                metrics.get("win_rate", 0),
                metrics.get("total_trades", 0),
                metrics.get("train_bars", 0),
                metrics.get("feature_count", 0),
                "active",
                notes,
                1 if wdh_enabled else 0,
                1 if merrill_enabled else 0,
            ))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def get_recent_performance(self, symbol: str, days: int = 30) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT COUNT(*) as n_trades,
                       AVG(pnl_pct) as avg_pnl,
                       SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate,
                       MAX(pnl_pct) as max_pnl,
                       MIN(pnl_pct) as min_pnl,
                       SUM(pnl_pct) as total_pnl
                FROM trades WHERE symbol = ?
            """, (symbol,))
            
            row = cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                result = dict(zip(columns, row))
                return result
            return {}
        except Exception:
            return {}
        finally:
            conn.close()
    
    def get_model_versions(self, symbol: str = None) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            if symbol:
                cursor.execute("SELECT * FROM model_versions WHERE symbol = ? ORDER BY created_at DESC", (symbol,))
            else:
                cursor.execute("SELECT * FROM model_versions ORDER BY created_at DESC")
            
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        except Exception:
            return []
        finally:
            conn.close()


class BCRM2Scheduler:
    """BCRM 2.0升级版自动化调度器"""
    
    def __init__(
        self,
        symbols: List[str] = None,
        db_path: str = None,
        dry_run: bool = True,
        exchange: str = "okx",
        wdh_enabled: bool = True,
        merrill_enabled: bool = True,
        incremental_enabled: bool = True,
        retrain_trade_threshold: int = 100,
        retrain_win_rate_threshold: float = 0.5,
    ):
        self.symbols = symbols or _BCRM2_SYMBOLS
        self.dry_run = dry_run
        self.exchange = exchange.lower()
        self.wdh_enabled = wdh_enabled
        self.merrill_enabled = merrill_enabled
        self.incremental_enabled = incremental_enabled
        
        self.db = BCRM2Database(db_path)
        self._auto_trader = None
        self._incremental_learner = None
        self._running = False
        self._stop_event = threading.Event()
        self._last_trade_time = {}
        self._min_trade_interval_minutes = 30
        
        self.retrain_trade_threshold = retrain_trade_threshold
        self.retrain_win_rate_threshold = retrain_win_rate_threshold
    
    def get_auto_trader(self):
        if self._auto_trader is None:
            from dreamos.cli.auto_trader import AutoTrader
            self._auto_trader = AutoTrader(dry_run=self.dry_run, exchange=self.exchange)
        return self._auto_trader
    
    def get_incremental_learner(self):
        if self._incremental_learner is None and self.incremental_enabled:
            try:
                project_root = str(Path(__file__).parent.parent.parent.parent)
                memory_l4_path = str(Path(project_root) / "11-易经推理系统" / "scripts" / "memory_l4")
                if memory_l4_path not in sys.path:
                    sys.path.insert(0, memory_l4_path)
                from bcrm2.incremental_learner import IncrementalLearner
                db_path = str(Path(project_root) / "data" / "bcrm_trades.db")
                model_dir = str(Path(project_root) / "models")
                self._incremental_learner = IncrementalLearner(
                    db_path=db_path,
                    model_dir=model_dir,
                    retrain_trade_threshold=self.retrain_trade_threshold,
                    retrain_win_rate_threshold=self.retrain_win_rate_threshold,
                )
                logger.info(f"✅ 增量学习引擎已加载: db={db_path}, model_dir={model_dir}")
            except Exception as e:
                logger.warning(f"初始化增量学习引擎失败: {e}")
                self._incremental_learner = None
        return self._incremental_learner
    
    def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        """分析单个币种"""
        logger.info(f"🔍 开始分析 {symbol}...")
        
        trader = self.get_auto_trader()
        
        try:
            analysis_result = trader.run_full_analysis(symbol)
            
            self.db.save_analysis_log(symbol, analysis_result)
            
            a5_output = analysis_result.get("outputs", {}).get("A5", {})
            trade_order = a5_output.get("trade_order", {})
            direction = trade_order.get("action", "HOLD")
            confidence = a5_output.get("confidence", 0)
            
            logger.info(f"📊 {symbol} 分析结果: {direction} (置信度: {confidence:.3f})")
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"❌ {symbol} 分析失败: {e}")
            return {"error": str(e), "symbol": symbol}
    
    def execute_trade(self, symbol: str, analysis_result: Dict) -> Dict[str, Any]:
        """执行交易"""
        logger.info(f"⚡ 执行 {symbol} 交易...")
        
        trader = self.get_auto_trader()
        
        a5_output = analysis_result.get("outputs", {}).get("A5", {})
        trade_order = a5_output.get("trade_order", {})
        direction = trade_order.get("action", "HOLD")
        
        if direction == "HOLD":
            logger.info(f"⏸ {symbol} 方向为HOLD，跳过交易")
            return {"result": "SKIP", "reason": "方向为HOLD"}
        
        confidence = a5_output.get("confidence", 0)
        if confidence < 0.6:
            logger.info(f"⚠ {symbol} 置信度不足({confidence:.2f} < 0.6)，拒绝交易")
            return {"result": "CONFIDENCE_TOO_LOW", "confidence": confidence}
        
        risk_result = trader.check_risk_control(symbol, trade_order)
        if not risk_result["passed"]:
            logger.warning(f"🚫 {symbol} 风控检查失败: {risk_result['reason']}")
            return {"result": "RISK_REJECTED", "reason": risk_result["reason"]}
        
        exec_result = trader.execute_trade(trade_order)
        
        if exec_result.get("dry_run"):
            logger.info(f"📝 {symbol} 模拟交易: {direction} @ {trade_order.get('entry_price')}")
            record = BCRM2TradeRecord()
            record.symbol = symbol
            record.direction = direction
            record.entry_price = trade_order.get("entry_price", 0)
            record.confidence = confidence
            record.wdh_features_used = self.wdh_enabled
            record.merrill_clock_enabled = self.merrill_enabled
            record.incremental_learning_enabled = self.incremental_enabled
            record.notes = "dry_run"
            self.db.save_trade(record)
            
            self._try_trigger_incremental_learning(symbol)
            
            return {"result": "DRY_RUN", "details": exec_result}
        
        if exec_result.get("result") == "SUCCESS":
            logger.info(f"✅ {symbol} 交易成功: {direction}")
            record = BCRM2TradeRecord()
            record.symbol = symbol
            record.direction = direction
            record.entry_price = trade_order.get("entry_price", 0)
            record.confidence = confidence
            record.wdh_features_used = self.wdh_enabled
            record.merrill_clock_enabled = self.merrill_enabled
            record.incremental_learning_enabled = self.incremental_enabled
            self.db.save_trade(record)
            
            self._try_trigger_incremental_learning(symbol)
            
            return {"result": "SUCCESS", "details": exec_result}
        
        logger.error(f"❌ {symbol} 交易失败: {exec_result.get('error')}")
        return {"result": "FAILED", "error": exec_result.get("error")}
    
    def check_exit(self, symbol: str) -> Dict[str, Any]:
        """检查离场条件"""
        trader = self.get_auto_trader()
        
        try:
            positions = trader.get_account_status().get("positions", [])
            for pos in positions:
                if pos.get("coin") == symbol:
                    entry_price = float(pos.get("entry_px", 0))
                    size = float(pos.get("size", 0))
                    if entry_price > 0:
                        exit_result = trader.check_exit(symbol, entry_price, "LONG" if size > 0 else "SHORT")
                        
                        if exit_result["exit"]:
                            logger.info(f"📤 {symbol} 离场触发: {exit_result['reason']}")
                            exec_result = trader.execute_trade({
                                "action": "EXIT",
                                "coin": symbol,
                                "entry_price": entry_price,
                            })
                            exit_result["execution"] = exec_result
                            
                            exit_price = exit_result.get("exit_price", entry_price)
                            direction = "LONG" if size > 0 else "SHORT"
                            if entry_price > 0:
                                if direction == "LONG":
                                    pnl_pct = (exit_price - entry_price) / entry_price
                                else:
                                    pnl_pct = (entry_price - exit_price) / entry_price
                                pnl_pct -= 0.0008
                            else:
                                pnl_pct = 0.0
                            
                            record = BCRM2TradeRecord()
                            record.symbol = symbol
                            record.direction = direction
                            record.entry_price = entry_price
                            record.exit_price = exit_price
                            record.pnl_pct = pnl_pct
                            record.exit_reason = exit_result["reason"]
                            self.db.save_trade(record)
                            
                            self._try_trigger_incremental_learning(symbol)
                            
                        return exit_result
            
            return {"exit": False, "reason": "无持仓"}
        except Exception as e:
            logger.warning(f"检查离场条件失败: {e}")
            return {"exit": False, "error": str(e)}
    
    def _try_trigger_incremental_learning(self, symbol: str):
        """尝试触发增量学习"""
        if not self.incremental_enabled:
            return
        
        learner = self.get_incremental_learner()
        if not learner:
            return
        
        try:
            should_retrain, reason = learner.should_retrain(symbol)
            if should_retrain:
                logger.info(f"🔄 {symbol} 触发增量学习: {reason}")
        except Exception as e:
            logger.warning(f"检查增量学习条件失败: {e}")
    
    def run_full_cycle(self, symbol: str) -> Dict[str, Any]:
        """运行完整分析-交易周期"""
        start_time = time.time()
        result = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "phases": [],
            "final_result": "SKIP",
        }
        
        try:
            result["phases"].append({"phase": ExecutionPhase.ANALYSIS.value, "status": "running"})
            analysis = self.analyze_symbol(symbol)
            if analysis.get("error"):
                result["phases"].append({"phase": ExecutionPhase.ANALYSIS.value, "status": "failed", "error": analysis["error"]})
                result["final_result"] = "ANALYSIS_FAILED"
                return result
            result["phases"].append({
                "phase": ExecutionPhase.ANALYSIS.value,
                "status": "completed",
                "confidence": analysis.get("confidence"),
                "action": analysis.get("action"),
            })
            
            result["phases"].append({"phase": ExecutionPhase.EXECUTION.value, "status": "running"})
            exec_result = self.execute_trade(symbol, analysis)
            result["phases"].append({
                "phase": ExecutionPhase.EXECUTION.value,
                "status": exec_result.get("result", "UNKNOWN"),
                "details": exec_result,
            })
            result["final_result"] = exec_result.get("result", "UNKNOWN")
            
            if self.incremental_enabled:
                result["phases"].append({"phase": ExecutionPhase.LEARNING.value, "status": "running"})
                self._try_trigger_incremental_learning(symbol)
                result["phases"].append({"phase": ExecutionPhase.LEARNING.value, "status": "completed"})
            
            result["execution_time_ms"] = round((time.time() - start_time) * 1000, 2)
            
        except Exception as e:
            result["error"] = str(e)
            result["final_result"] = "EXCEPTION"
            logger.error(f"❌ {symbol} 完整周期失败: {e}")
        
        return result
    
    def run_scan_all(self) -> Dict[str, Any]:
        """扫描所有币种"""
        logger.info("=" * 60)
        logger.info(f"🚀 BCRM 2.0 升级版调度器开始扫描 ({len(self.symbols)} 个币种)")
        logger.info(f"   配置: WDH={self.wdh_enabled}, 美林时钟={self.merrill_enabled}, 增量学习={self.incremental_enabled}")
        logger.info("=" * 60)
        
        results = {}
        total_start = time.time()
        
        for symbol in self.symbols:
            try:
                result = self.run_full_cycle(symbol)
                results[symbol] = result
            except Exception as e:
                logger.error(f"❌ {symbol} 扫描异常: {e}")
                results[symbol] = {"error": str(e), "final_result": "EXCEPTION"}
            
            time.sleep(1)
        
        total_time = round(time.time() - total_start, 2)
        
        logger.info("=" * 60)
        logger.info(f"📊 BCRM 2.0 扫描完成 (总耗时: {total_time}s)")
        
        summary = self.generate_summary(results)
        logger.info(json.dumps(summary, indent=2, ensure_ascii=False))
        logger.info("=" * 60)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "symbols": self.symbols,
            "total_time_s": total_time,
            "results": results,
            "summary": summary,
        }
    
    def generate_summary(self, results: Dict) -> Dict:
        """生成扫描摘要"""
        total = len(results)
        success = sum(1 for r in results.values() if r.get("final_result") in ["SUCCESS", "DRY_RUN"])
        failed = sum(1 for r in results.values() if r.get("final_result") in ["FAILED", "EXCEPTION", "ANALYSIS_FAILED"])
        hold = sum(1 for r in results.values() if r.get("final_result") == "SKIP")
        
        avg_latency = 0
        total_latency = 0
        n_valid = 0
        
        for symbol, result in results.items():
            latency = result.get("execution_time_ms", 0)
            if latency > 0:
                total_latency += latency
                n_valid += 1
        
        if n_valid > 0:
            avg_latency = round(total_latency / n_valid, 2)
        
        return {
            "total_symbols": total,
            "success_count": success,
            "failed_count": failed,
            "hold_count": hold,
            "avg_latency_ms": avg_latency,
            "wdh_enabled": self.wdh_enabled,
            "merrill_clock_enabled": self.merrill_enabled,
            "incremental_learning_enabled": self.incremental_enabled,
        }
    
    def get_performance_stats(self, symbol: str = None) -> Dict:
        """获取绩效统计"""
        if symbol:
            return self.db.get_recent_performance(symbol)
        
        stats = {}
        for sym in self.symbols:
            stats[sym] = self.db.get_recent_performance(sym)
        return stats
    
    def get_model_versions(self, symbol: str = None) -> List[Dict]:
        """获取模型版本列表"""
        return self.db.get_model_versions(symbol)
    
    def start(self):
        """启动调度器"""
        self._running = True
        self._stop_event.clear()
        logger.info("✅ BCRM 2.0 调度器已启动")
    
    def stop(self):
        """停止调度器"""
        self._running = False
        self._stop_event.set()
        logger.info("🛑 BCRM 2.0 调度器已停止")
    
    def run_scheduled(self, cron_expr: str = "0 * * * *"):
        """按cron表达式运行调度"""
        self.start()
        
        try:
            import croniter
            cron = croniter.croniter(cron_expr, datetime.now())
            
            while self._running:
                next_run = cron.get_next(datetime)
                wait_seconds = max(0, (next_run - datetime.now()).total_seconds())
                
                logger.info(f"⏰ 下次扫描: {next_run} (等待 {wait_seconds:.0f}s)")
                
                if self._stop_event.wait(wait_seconds):
                    break
                
                self.run_scan_all()
                
                time.sleep(60)
            
        except ImportError:
            logger.error("❌ croniter未安装，请安装: pip install croniter")
            self.stop()
        except Exception as e:
            logger.error(f"❌ 调度器异常: {e}")
            self.stop()


class BCRM2EvolutionObserver:
    """BCRM 2.0 交易进化观测器

    核心功能:
      - 模型版本管理 (保存/加载/回滚/清理)
      - 绩效统计 (胜率/夏普/最大回撤)
      - 自动再训练触发 (增量学习闭环)
      - 进化事件记录 (版本变更/参数调整/回滚)
    """

    def __init__(self, db_path: str = None):
        if db_path is None:
            project_root = str(Path(__file__).parent.parent.parent.parent)
            db_path = str(Path(project_root) / "data" / "bcrm_trades.db")
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""CREATE TABLE IF NOT EXISTS model_evolution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            event_type TEXT NOT NULL,
            version_from TEXT,
            version_to TEXT,
            trigger_reason TEXT,
            metrics_before TEXT,
            metrics_after TEXT,
            rollback_available INTEGER DEFAULT 1
        )""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS performance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            version_id TEXT,
            n_trades INTEGER,
            win_rate REAL,
            avg_pnl REAL,
            sharpe_ratio REAL,
            max_drawdown REAL,
            notes TEXT
        )""")
        conn.commit()
        conn.close()

    def record_evolution_event(self, symbol: str, event_type: str,
                               version_from: str = "", version_to: str = "",
                               trigger_reason: str = "",
                               metrics_before: Dict = None,
                               metrics_after: Dict = None,
                               rollback_available: bool = True):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO model_evolution (
            timestamp, symbol, event_type, version_from, version_to,
            trigger_reason, metrics_before, metrics_after, rollback_available
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            datetime.now().isoformat(), symbol, event_type,
            version_from, version_to, trigger_reason,
            json.dumps(metrics_before or {}, ensure_ascii=False),
            json.dumps(metrics_after or {}, ensure_ascii=False),
            1 if rollback_available else 0,
        ))
        conn.commit()
        conn.close()

    def snapshot_performance(self, symbol: str, version_id: str,
                             n_trades: int = 0, win_rate: float = 0,
                             avg_pnl: float = 0, sharpe_ratio: float = 0,
                             max_drawdown: float = 0, notes: str = ""):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""INSERT INTO performance_snapshots (
            timestamp, symbol, version_id, n_trades, win_rate,
            avg_pnl, sharpe_ratio, max_drawdown, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
            datetime.now().isoformat(), symbol, version_id,
            n_trades, win_rate, avg_pnl, sharpe_ratio, max_drawdown, notes,
        ))
        conn.commit()
        conn.close()

    def get_evolution_history(self, symbol: str = None, limit: int = 20) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            if symbol:
                cursor.execute(
                    "SELECT * FROM model_evolution WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                    (symbol, limit))
            else:
                cursor.execute(
                    "SELECT * FROM model_evolution ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()

    def get_performance_trend(self, symbol: str, limit: int = 10) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM performance_snapshots WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                (symbol, limit))
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        finally:
            conn.close()

    def check_rollback_candidates(self, symbol: str,
                                   min_win_rate: float = 0.4,
                                   min_sharpe: float = 0.0) -> List[Dict]:
        """检查需要回滚的模型版本（当前绩效低于阈值）"""
        trend = self.get_performance_trend(symbol, limit=5)
        if not trend:
            return []
        recent = trend[0]
        if recent.get("win_rate", 1.0) < min_win_rate or recent.get("sharpe_ratio", 0) < min_sharpe:
            return [{
                "symbol": symbol,
                "current_version": recent.get("version_id"),
                "win_rate": recent.get("win_rate"),
                "sharpe_ratio": recent.get("sharpe_ratio"),
                "recommendation": "建议回滚到上一版本",
            }]
        return []


def run_hourly_sacg(symbols: List[str] = None,
                     dry_run: bool = True,
                     wdh_enabled: bool = True,
                     merrill_enabled: bool = True,
                     incremental_enabled: bool = True) -> Dict[str, Any]:
    """每小时自动调度入口 — 完整S-A-C-G编排流程

    流程:
      1. S层: 意图识别 (场景分类 + 数据源判断)
      2. A层: 图编排 (BCRM2.0优先 → BCRM1.0回退)
      3. C层: 资源分配 (算力/特征工程/模型选择)
      4. G层: 风险管理 (风控/离场/情报监控)
      5. 数据库记录 (决策/交易/分析日志/模型版本)
      6. 进化观测 (增量学习触发/绩效快照/回滚检查)
    """
    symbols = symbols or _BCRM2_SYMBOLS
    scheduler = BCRM2Scheduler(
        symbols=symbols, dry_run=dry_run,
        wdh_enabled=wdh_enabled, merrill_enabled=merrill_enabled,
        incremental_enabled=incremental_enabled,
    )
    observer = BCRM2EvolutionObserver()

    # 执行扫描
    result = scheduler.run_scan_all()

    # 进化观测
    for symbol in symbols:
        perf = scheduler.get_performance_stats(symbol)
        if perf:
            n_trades = perf.get("n_trades", 0) or 0
            win_rate = perf.get("win_rate", 0) or 0
            observer.snapshot_performance(
                symbol=symbol,
                version_id=f"v2_phase0_{datetime.now().strftime('%Y%m%d%H')}",
                n_trades=int(n_trades),
                win_rate=float(win_rate),
                avg_pnl=float(perf.get("avg_pnl", 0) or 0),
                notes="每小时自动调度绩效快照",
            )

        # 回滚检查
        rollback = observer.check_rollback_candidates(symbol)
        if rollback:
            for r in rollback:
                logger.warning(f"回滚预警: {r}")
                observer.record_evolution_event(
                    symbol=symbol,
                    event_type="rollback_warning",
                    trigger_reason=f"win_rate={r['win_rate']}, sharpe={r['sharpe_ratio']}",
                )

    return result


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description="BCRM 2.0 升级版自动化调度器")
    parser.add_argument("--mode", default="run_once", choices=["run_once", "scheduled", "sacg_hourly"],
                        help="运行模式: run_once(单次扫描) / scheduled(定时调度) / sacg_hourly(S-A-C-G每小时调度)")
    parser.add_argument("--symbols", nargs="+", default=_BCRM2_SYMBOLS,
                        help="待分析币种列表")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="模拟交易模式")
    parser.add_argument("--exchange", default="okx", choices=["okx", "hyperliquid"],
                        help="交易所")
    parser.add_argument("--wdh", action="store_true", default=True,
                        help="启用WDH时间特征")
    parser.add_argument("--merrill", action="store_true", default=True,
                        help="启用美林时钟")
    parser.add_argument("--incremental", action="store_true", default=True,
                        help="启用增量学习")
    parser.add_argument("--cron", default="0 * * * *",
                        help="cron表达式 (定时模式)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别")

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(Path(__file__).parent.parent / "logs" / "bcrm2_scheduler.log"),
        ]
    )

    if args.mode == "sacg_hourly":
        result = run_hourly_sacg(
            symbols=args.symbols, dry_run=args.dry_run,
            wdh_enabled=args.wdh, merrill_enabled=args.merrill,
            incremental_enabled=args.incremental,
        )
        print(json.dumps(result.get("summary", {}), indent=2, ensure_ascii=False))
        return

    scheduler = BCRM2Scheduler(
        symbols=args.symbols,
        dry_run=args.dry_run,
        exchange=args.exchange,
        wdh_enabled=args.wdh,
        merrill_enabled=args.merrill,
        incremental_enabled=args.incremental,
    )

    if args.mode == "run_once":
        result = scheduler.run_scan_all()
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    elif args.mode == "scheduled":
        scheduler.run_scheduled(args.cron)


if __name__ == "__main__":
    main()