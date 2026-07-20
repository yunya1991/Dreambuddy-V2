"""
Dream OS 每小时自动调度任务 — BCRM 2.0 Phase 0升级版

完整功能:
  1. 定时调用 /api/dreamos/analyze 接口分析10个币种
  2. 触发完整S-A-C-G编排流程
  3. BCRM 2.0架构升级 (WDH时间特征+美林时钟+增量学习闭环)
  4. 自动触发模型再训练和参数进化
  5. 决策结果记录到历史日志和SQLite数据库
  6. 模型版本管理、回滚机制、绩效统计

使用方式:
  python -m dreamos.cli.auto_scheduler --mode scheduled   # 定时调度
  python -m dreamos.cli.auto_scheduler --mode run_once    # 单次运行

[DEPRECATED 2026-07-19] 本文件已废弃,统一使用 start_scheduler.py 作为唯一调度器入口。
    launchd 守护进程通过 com.dreambuddy.dreamos.plist 拉起 start_scheduler.py。
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
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "MATIC", "BNB", "OP", "ARB"]


def setup_logging(log_level: str = "INFO"):
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "bcrm2_auto_scheduler.log"),
        ]
    )


class TradeDatabase:
    
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


class DreamOSAnalyzer:
    
    def __init__(self, api_url: str = "http://localhost:8765/api/dreamos/analyze"):
        self.api_url = api_url
    
    def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        try:
            import urllib.request
            import urllib.parse
            
            url = f"{self.api_url}?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read().decode("utf-8")
                return json.loads(data)
        except Exception as e:
            logger.error(f"API调用失败 ({symbol}): {e}")
            return {"error": str(e), "symbol": symbol}


class BCRM2AutoScheduler:
    
    def __init__(self):
        self.db = TradeDatabase()
        self.analyzer = DreamOSAnalyzer()
        self._running = False
        self._stop_event = threading.Event()
    
    def run_analysis_cycle(self) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info(f"🚀 Dream OS 自动调度任务启动 ({len(SYMBOLS)} 个币种)")
        logger.info(f"   时间: {datetime.now().isoformat()}")
        logger.info("=" * 60)
        
        results = {}
        total_start = time.time()
        
        for symbol in SYMBOLS:
            try:
                logger.info(f"🔍 分析 {symbol}...")
                result = self.analyzer.analyze_symbol(symbol)
                
                if result.get("error"):
                    logger.error(f"❌ {symbol} 分析失败: {result['error']}")
                else:
                    action = result.get("action", "HOLD")
                    confidence = result.get("confidence", 0)
                    logger.info(f"📊 {symbol}: {action} (置信度: {confidence:.3f})")
                    
                    self.db.save_analysis_log(symbol, result)
                
                results[symbol] = result
                
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"❌ {symbol} 异常: {e}")
                results[symbol] = {"error": str(e)}
        
        total_time = round(time.time() - total_start, 2)
        
        summary = self.generate_summary(results, total_time)
        logger.info("=" * 60)
        logger.info(f"📊 Dream OS 调度完成 (总耗时: {total_time}s)")
        logger.info(json.dumps(summary, indent=2, ensure_ascii=False))
        logger.info("=" * 60)
        
        return summary
    
    def generate_summary(self, results: Dict, total_time: float) -> Dict:
        total = len(results)
        success = sum(1 for r in results.values() if not r.get("error"))
        failed = sum(1 for r in results.values() if r.get("error"))
        
        short_count = sum(1 for r in results.values() if r.get("action") == "SHORT")
        long_count = sum(1 for r in results.values() if r.get("action") == "LONG")
        hold_count = sum(1 for r in results.values() if r.get("action") == "HOLD")
        
        avg_confidence = 0
        n_valid = 0
        for r in results.values():
            if not r.get("error"):
                avg_confidence += r.get("confidence", 0)
                n_valid += 1
        if n_valid > 0:
            avg_confidence = round(avg_confidence / n_valid, 3)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_symbols": total,
            "success_count": success,
            "failed_count": failed,
            "short_count": short_count,
            "long_count": long_count,
            "hold_count": hold_count,
            "avg_confidence": avg_confidence,
            "total_time_s": total_time,
            "db_stats": self.db.get_stats(),
        }
    
    def start_scheduled(self, interval_hours: int = 1):
        self._running = True
        self._stop_event.clear()
        logger.info(f"✅ Dream OS 自动调度器已启动 (每{interval_hours}小时执行一次)")
        
        while self._running:
            try:
                self.run_analysis_cycle()
                
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
        logger.info("🛑 Dream OS 自动调度器已停止")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Dream OS 每小时自动调度任务")
    parser.add_argument("--mode", default="run_once", choices=["run_once", "scheduled"],
                        help="运行模式")
    parser.add_argument("--interval", type=int, default=1, help="调度间隔(小时)")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别")
    
    args = parser.parse_args()
    
    setup_logging(args.log_level)
    
    scheduler = BCRM2AutoScheduler()
    
    if args.mode == "run_once":
        summary = scheduler.run_analysis_cycle()
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    elif args.mode == "scheduled":
        scheduler.start_scheduled(interval_hours=args.interval)


if __name__ == "__main__":
    main()