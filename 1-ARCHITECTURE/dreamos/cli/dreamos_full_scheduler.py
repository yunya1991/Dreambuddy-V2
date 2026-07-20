"""
Dream OS 每小时自动调度任务 — BCRM 2.0 Phase 0升级版

完整功能:
  1. 调用 DreamOS API 分析10个币种
  2. 触发完整S-A-C-G编排流程（意图识别→图编排→资源分配→风险管理→交易执行→离场策略→情报监控）
  3. BCRM 2.0架构升级（WDH时间特征+美林时钟+增量学习闭环）
  4. 自动触发模型再训练和参数进化
  5. 决策结果记录到历史日志和SQLite交易数据库（data/bcrm_trades.db）
  6. 系统自动化调度编排和交易进化观测

支持币种: BTC, ETH, SOL, AVAX, LINK, DOT, MATIC, BNB, OP, ARB

[DEPRECATED 2026-07-19] 本文件已废弃,统一使用 start_scheduler.py 作为唯一调度器入口。
    launchd 守护进程通过 com.dreambuddy.dreamos.plist 拉起 start_scheduler.py,
    后者调用 scheduler.py 的 DreamOSScheduler(基于 croniter + 直接调 AutoTrader)。
    本文件保留作历史参考,请勿新增依赖。
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

logger = logging.getLogger(__name__)

SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "MATIC", "BNB", "OP", "ARB"]

MIN_LEVERAGE = 1
MAX_LEVERAGE = 5
DEFAULT_LEVERAGE = 3


def _calc_dynamic_leverage(confidence: float, min_lev: int = MIN_LEVERAGE,
                            max_lev: int = MAX_LEVERAGE,
                            threshold: float = 0.4) -> int:
    """基于置信度动态计算杠杆倍数"""
    if confidence <= threshold:
        return min_lev
    if confidence >= 0.8:
        return max_lev
    ratio = (confidence - threshold) / (0.8 - threshold)
    lev = min_lev + ratio * (max_lev - min_lev)
    return max(min_lev, min(max_lev, int(round(lev))))


def setup_logging(log_level: str = "INFO"):
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "dreamos_full_scheduler.log"),
        ]
    )


class BCRM2Database:
    
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
    
    def save_trade(self, record: Dict) -> int:
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
                record.get("timestamp", ""),
                record.get("symbol", ""),
                record.get("direction", ""),
                record.get("entry_price", 0),
                record.get("exit_price", 0),
                record.get("pnl_pct", 0),
                record.get("confidence", 0),
                record.get("model_version", ""),
                record.get("hexagram", ""),
                record.get("upper_gua", ""),
                record.get("lower_gua", ""),
                record.get("exit_reason", ""),
                record.get("execution_time_ms", 0),
                1 if record.get("wdh_features_used") else 0,
                1 if record.get("merrill_clock_enabled") else 0,
                1 if record.get("incremental_learning_enabled") else 0,
                record.get("notes", ""),
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
    
    def get_stats(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM analysis_logs")
            analysis_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM trades")
            trade_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM model_versions")
            version_count = cursor.fetchone()[0]
            
            return {
                "analysis_logs": analysis_count,
                "trades": trade_count,
                "model_versions": version_count,
            }
        except Exception:
            return {}
        finally:
            conn.close()
    
    def get_recent_performance(self, symbol: str) -> Dict:
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
                return dict(zip(columns, row))
            return {}
        except Exception:
            return {}
        finally:
            conn.close()


class DreamOSAPIClient:
    
    def __init__(self, api_url: str = "http://localhost:8765/api/dreamos/analyze"):
        self.api_url = api_url
    
    def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        try:
            import urllib.request
            import urllib.parse
            
            url = f"{self.api_url}?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read().decode("utf-8")
                return json.loads(data)
        except Exception as e:
            logger.error(f"API调用失败 ({symbol}): {e}")
            return {"error": str(e), "symbol": symbol}


class BCRM2EnhancedScheduler:
    
    def __init__(
        self,
        symbols: List[str] = None,
        db_path: str = None,
        dry_run: bool = True,
        exchange: str = "okx",
        wdh_enabled: bool = True,
        merrill_enabled: bool = True,
        incremental_enabled: bool = True,
        api_url: str = "http://localhost:8765/api/v1/analyze",
    ):
        self.symbols = symbols or SYMBOLS
        self.dry_run = dry_run
        self.exchange = exchange.lower()
        self.wdh_enabled = wdh_enabled
        self.merrill_enabled = merrill_enabled
        self.incremental_enabled = incremental_enabled
        
        self.db = BCRM2Database(db_path)
        self.api_client = DreamOSAPIClient(api_url)
        
        self._auto_trader = None
        self._incremental_learner = None
        self._running = False
        self._stop_event = threading.Event()
        
        self.retrain_trade_threshold = 100
        self.retrain_win_rate_threshold = 0.5
    
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
                logger.info(f"✅ 增量学习引擎已加载")
            except Exception as e:
                logger.warning(f"初始化增量学习引擎失败: {e}")
                self._incremental_learner = None
        return self._incremental_learner
    
    def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        logger.info(f"🔍 开始分析 {symbol}...")
        
        try:
            analysis_result = self.api_client.analyze_symbol(symbol)
            
            if analysis_result.get("error"):
                logger.warning(f"API分析失败，降级到本地分析: {symbol}")
                trader = self.get_auto_trader()
                analysis_result = trader.run_full_analysis(symbol)
            
            self.db.save_analysis_log(symbol, analysis_result)
            
            action = analysis_result.get("action", "HOLD")
            confidence = analysis_result.get("confidence", 0)
            
            logger.info(f"📊 {symbol} 分析结果: {action} (置信度: {confidence:.3f})")
            
            return analysis_result
            
        except Exception as e:
            logger.error(f"❌ {symbol} 分析失败: {e}")
            return {"error": str(e), "symbol": symbol}
    
    def execute_trade(self, symbol: str, analysis_result: Dict) -> Dict[str, Any]:
        logger.info(f"⚡ 执行 {symbol} 交易...")
        
        trader = self.get_auto_trader()
        
        action = analysis_result.get("action", "HOLD")
        confidence = analysis_result.get("confidence", 0)
        trade_order = {
            "action": action,
            "coin": symbol,
            "entry_price": analysis_result.get("price", 0),
            "position_size": 10.0,
            "leverage": _calc_dynamic_leverage(confidence),
        }
        
        if action == "HOLD":
            logger.info(f"⏸ {symbol} 方向为HOLD，跳过交易")
            return {"result": "SKIP", "reason": "方向为HOLD"}
        
        if confidence < 0.6:
            logger.info(f"⚠ {symbol} 置信度不足({confidence:.2f} < 0.6)，拒绝交易")
            return {"result": "CONFIDENCE_TOO_LOW", "confidence": confidence}
        
        risk_result = trader.check_risk_control(symbol, trade_order)
        if not risk_result["passed"]:
            logger.warning(f"🚫 {symbol} 风控检查失败: {risk_result['reason']}")
            return {"result": "RISK_REJECTED", "reason": risk_result["reason"]}
        
        exec_result = trader.execute_trade(trade_order)
        
        if exec_result.get("dry_run"):
            logger.info(f"📝 {symbol} 模拟交易: {action}")
            record = {
                "symbol": symbol,
                "direction": action,
                "entry_price": trade_order.get("entry_price", 0),
                "confidence": confidence,
                "wdh_features_used": self.wdh_enabled,
                "merrill_clock_enabled": self.merrill_enabled,
                "incremental_learning_enabled": self.incremental_enabled,
                "notes": "dry_run",
            }
            self.db.save_trade(record)
            
            self._try_trigger_incremental_learning(symbol)
            
            return {"result": "DRY_RUN", "details": exec_result}
        
        if exec_result.get("result") == "SUCCESS":
            logger.info(f"✅ {symbol} 交易成功: {action}")
            record = {
                "symbol": symbol,
                "direction": action,
                "entry_price": trade_order.get("entry_price", 0),
                "confidence": confidence,
                "wdh_features_used": self.wdh_enabled,
                "merrill_clock_enabled": self.merrill_enabled,
                "incremental_learning_enabled": self.incremental_enabled,
            }
            self.db.save_trade(record)
            
            self._try_trigger_incremental_learning(symbol)
            
            return {"result": "SUCCESS", "details": exec_result}
        
        logger.error(f"❌ {symbol} 交易失败: {exec_result.get('error')}")
        return {"result": "FAILED", "error": exec_result.get("error")}
    
    def _try_trigger_incremental_learning(self, symbol: str):
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
        start_time = time.time()
        result = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "phases": [],
            "final_result": "SKIP",
        }
        
        try:
            result["phases"].append({"phase": "analysis", "status": "running"})
            analysis = self.analyze_symbol(symbol)
            if analysis.get("error"):
                result["phases"].append({"phase": "analysis", "status": "failed", "error": analysis["error"]})
                result["final_result"] = "ANALYSIS_FAILED"
                return result
            result["phases"].append({
                "phase": "analysis",
                "status": "completed",
                "confidence": analysis.get("confidence"),
                "action": analysis.get("action"),
            })
            
            result["phases"].append({"phase": "execution", "status": "running"})
            exec_result = self.execute_trade(symbol, analysis)
            result["phases"].append({
                "phase": "execution",
                "status": exec_result.get("result", "UNKNOWN"),
                "details": exec_result,
            })
            result["final_result"] = exec_result.get("result", "UNKNOWN")
            
            if self.incremental_enabled:
                result["phases"].append({"phase": "learning", "status": "running"})
                self._try_trigger_incremental_learning(symbol)
                result["phases"].append({"phase": "learning", "status": "completed"})
            
            result["execution_time_ms"] = round((time.time() - start_time) * 1000, 2)
            
        except Exception as e:
            result["error"] = str(e)
            result["final_result"] = "EXCEPTION"
            logger.error(f"❌ {symbol} 完整周期失败: {e}")
        
        return result
    
    def run_scan_all(self) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info(f"🚀 Dream OS BCRM 2.0 升级版调度器开始扫描 ({len(self.symbols)} 个币种)")
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
            
            time.sleep(0.5)
        
        total_time = round(time.time() - total_start, 2)
        
        summary = self.generate_summary(results, total_time)
        logger.info("=" * 60)
        logger.info(f"📊 Dream OS 扫描完成 (总耗时: {total_time}s)")
        logger.info(json.dumps(summary, indent=2, ensure_ascii=False))
        logger.info("=" * 60)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "symbols": self.symbols,
            "total_time_s": total_time,
            "results": results,
            "summary": summary,
        }
    
    def generate_summary(self, results: Dict, total_time: float) -> Dict:
        total = len(results)
        success = sum(1 for r in results.values() if r.get("final_result") in ["SUCCESS", "DRY_RUN"])
        failed = sum(1 for r in results.values() if r.get("final_result") in ["FAILED", "EXCEPTION", "ANALYSIS_FAILED"])
        hold = sum(1 for r in results.values() if r.get("final_result") == "SKIP")
        
        short_count = sum(1 for r in results.values() if r.get("action") == "SHORT")
        long_count = sum(1 for r in results.values() if r.get("action") == "LONG")
        
        avg_confidence = 0
        n_valid = 0
        for r in results.values():
            if not r.get("error"):
                avg_confidence += r.get("confidence", 0)
                n_valid += 1
        if n_valid > 0:
            avg_confidence = round(avg_confidence / n_valid, 3)
        
        avg_latency = 0
        total_latency = 0
        for symbol, result in results.items():
            latency = result.get("execution_time_ms", 0)
            if latency > 0:
                total_latency += latency
        
        if n_valid > 0:
            avg_latency = round(total_latency / n_valid, 2)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_symbols": total,
            "success_count": success,
            "failed_count": failed,
            "hold_count": hold,
            "short_count": short_count,
            "long_count": long_count,
            "avg_confidence": avg_confidence,
            "avg_latency_ms": avg_latency,
            "total_time_s": total_time,
            "wdh_enabled": self.wdh_enabled,
            "merrill_clock_enabled": self.merrill_enabled,
            "incremental_learning_enabled": self.incremental_enabled,
            "db_stats": self.db.get_stats(),
        }
    
    def start_scheduled(self, interval_hours: int = 1):
        self._running = True
        self._stop_event.clear()
        logger.info(f"✅ Dream OS BCRM 2.0 自动调度器已启动 (每{interval_hours}小时执行一次)")
        
        while self._running:
            try:
                self.run_scan_all()
                
                next_run = datetime.now() + timedelta(hours=interval_hours)
                wait_seconds = max(0, (next_run - datetime.now()).total_seconds())
                
                logger.info(f"⏰ 下次调度: {next_run} (等待 {wait_seconds:.0f}s)")
                
                if self._stop_event.wait(wait_seconds):
                    break
            except Exception as e:
                logger.error(f"❌ 调度器异常: {e}")
                time.sleep(60)
    
    def stop(self):
        self._running = False
        self._stop_event.set()
        logger.info("🛑 Dream OS BCRM 2.0 自动调度器已停止")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Dream OS BCRM 2.0 升级版自动调度器")
    parser.add_argument("--mode", default="run_once", choices=["run_once", "scheduled"],
                        help="运行模式: run_once(单次扫描) / scheduled(定时调度)")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS,
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
    parser.add_argument("--interval", type=int, default=1, help="调度间隔(小时)")
    parser.add_argument("--api-url", default="http://localhost:8765/api/v1/analyze",
                        help="DreamOS API地址")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别")
    
    args = parser.parse_args()
    
    setup_logging(args.log_level)
    
    scheduler = BCRM2EnhancedScheduler(
        symbols=args.symbols,
        dry_run=args.dry_run,
        exchange=args.exchange,
        wdh_enabled=args.wdh,
        merrill_enabled=args.merrill,
        incremental_enabled=args.incremental,
        api_url=args.api_url,
    )
    
    if args.mode == "run_once":
        result = scheduler.run_scan_all()
        print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    elif args.mode == "scheduled":
        scheduler.start_scheduled(interval_hours=args.interval)


if __name__ == "__main__":
    main()