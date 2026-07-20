#!/usr/bin/env python3
"""
Dream OS 每小时自动调度任务 — BCRM 2.0 Phase 0 升级版

直接调用BCRM2Adapter执行推理，不依赖dreamos模块。

完整功能:
1. 分析10个币种（BTC、ETH、SOL、AVAX、LINK、DOT、MATIC、BNB、OP、ARB）
2. 触发完整S-A-C-G编排流程
3. BCRM 2.0架构（WDH时间特征+美林时钟+增量学习闭环）
4. 自动触发模型再训练和参数进化
5. 决策结果记录到SQLite和历史日志

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
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, Any, List
from pathlib import Path

# 设置路径
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "11-易经推理系统" / "scripts" / "memory_l4"))

logger = logging.getLogger(__name__)

SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "MATIC", "BNB", "OP", "ARB"]


def setup_logging(log_level: str = "INFO"):
    log_dir = PROJECT_ROOT / "1-ARCHITECTURE" / "dreamos" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "bcrm2_hourly.log", mode='a'),
        ]
    )


class BCRM2Database:
    """SQLite数据库管理"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(PROJECT_ROOT / "data" / "bcrm_trades.db")
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hourly_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                confidence REAL,
                l1_confidence REAL,
                l2_confidence REAL,
                hexagram TEXT,
                hexagram_cn TEXT,
                wdh_enabled INTEGER,
                merrill_enabled INTEGER,
                fail_closed INTEGER,
                latency_ms REAL,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                status TEXT DEFAULT 'active'
            )
        """)
        
        conn.commit()
        conn.close()
    
    def save_analysis(self, symbol: str, result: Dict) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO hourly_analysis (
                    timestamp, symbol, direction, confidence, l1_confidence,
                    l2_confidence, hexagram, hexagram_cn, wdh_enabled,
                    merrill_enabled, fail_closed, latency_ms, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                symbol,
                result.get('direction', 'FLAT'),
                result.get('confidence', 0),
                result.get('l1_confidence', 0),
                result.get('l2_confidence', 0),
                result.get('hexagram', ''),
                result.get('hexagram_cn', ''),
                1 if result.get('wdh_enabled') else 0,
                1 if result.get('merrill_enabled') else 0,
                1 if result.get('fail_closed') else 0,
                result.get('latency_ms', 0),
                result.get('notes', ''),
            ))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.warning(f"保存分析记录失败: {e}")
            conn.rollback()
            return -1
        finally:
            conn.close()
    
    def get_stats(self) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT COUNT(*) FROM hourly_analysis")
            analysis_count = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN direction = 'UP' THEN 1 ELSE 0 END) as up_count,
                    SUM(CASE WHEN direction = 'DOWN' THEN 1 ELSE 0 END) as down_count,
                    AVG(confidence) as avg_confidence
                FROM hourly_analysis
            """)
            row = cursor.fetchone()
            
            return {
                "analysis_count": analysis_count,
                "total": row[0],
                "up_count": row[1],
                "down_count": row[2],
                "avg_confidence": round(row[3] or 0, 3),
            }
        except Exception:
            return {}
        finally:
            conn.close()


class BCRM2HourlyRunner:
    """BCRM 2.0 每小时执行器"""
    
    def __init__(
        self,
        symbols: List[str] = None,
        dry_run: bool = True,
        wdh_enabled: bool = True,
        merrill_enabled: bool = True,
    ):
        self.symbols = symbols or SYMBOLS
        self.dry_run = dry_run
        self.wdh_enabled = wdh_enabled
        self.merrill_enabled = merrill_enabled
        self.db = BCRM2Database()
        self._adapters = {}
    
    def get_adapter(self, symbol: str):
        """获取BCRM2适配器（延迟初始化）"""
        if symbol not in self._adapters:
            try:
                from bcrm2_adapter import BCRM2Adapter
                adapter = BCRM2Adapter(
                    symbol=symbol,
                    timeframe="1H",
                    train_bars=2000,
                    tp_atr=3.0,
                    sl_atr=1.5,
                )
                self._adapters[symbol] = adapter
                logger.info(f"✅ {symbol} BCRM2适配器已加载")
            except Exception as e:
                logger.error(f"❌ {symbol} 加载适配器失败: {e}")
                return None
        return self._adapters.get(symbol)
    
    def get_klines(self, symbol: str) -> Any:
        """获取K线数据"""
        try:
            from bcrm2.data_fetcher import get_klines
            df = get_klines(symbol, "1H", max_bars=2000)
            return df
        except Exception as e:
            logger.error(f"获取K线数据失败 ({symbol}): {e}")
            return None
    
    def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        """分析单个币种"""
        start_time = time.time()
        logger.info(f"🔍 开始分析 {symbol}...")
        
        result = {
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            "direction": "FLAT",
            "confidence": 0,
            "l1_confidence": 0,
            "l2_confidence": 0,
            "hexagram": "",
            "hexagram_cn": "",
            "fail_closed": True,
            "wdh_enabled": self.wdh_enabled,
            "merrill_enabled": self.merrill_enabled,
            "error": None,
        }
        
        try:
            # 获取K线数据
            df = self.get_klines(symbol)
            if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 200:
                result["error"] = "数据不足"
                logger.warning(f"⚠ {symbol} 数据不足: {len(df) if df is not None else 0} bars")
                return result
            
            # 获取适配器并训练
            adapter = self.get_adapter(symbol)
            if adapter is None:
                result["error"] = "适配器初始化失败"
                return result
            
            # 检查是否需要重训
            adapter.maybe_retrain(df)
            
            # 执行推理
            infer_result = adapter.infer(df, idx=-1)
            
            if infer_result.get('ok'):
                next_state = infer_result.get('next_state', {})
                hexagram = infer_result.get('hexagram', {})
                
                # 解析derivation字符串提取L1/L2置信度
                derivation = next_state.get('derivation', '')
                l1_conf = 0.0
                l2_conf = 0.0
                if 'L1=' in derivation:
                    try:
                        l1_part = derivation.split('L1=')[1].split()[0]
                        l1_conf = float(l1_part) if l1_part not in ['None', 'N/A'] else 0.0
                    except:
                        l1_conf = 0.0
                if 'L2=' in derivation:
                    try:
                        l2_part = derivation.split('L2=')[1].split()[0]
                        l2_conf = float(l2_part) if l2_part not in ['None', 'N/A'] else 0.0
                    except:
                        l2_conf = 0.0
                
                result.update({
                    "direction": next_state.get('direction', 'FLAT'),
                    "confidence": next_state.get('confidence', 0),
                    "l1_confidence": l1_conf,
                    "l2_confidence": l2_conf,
                    "hexagram": hexagram.get('hexagram_name', ''),
                    "hexagram_cn": hexagram.get('hexagram_name_cn', ''),
                    "fail_closed": infer_result.get('is_fail_closed', lambda: True)(),
                })
                
                logger.info(f"📊 {symbol} 推理结果: {result['direction']} (置信度: {result['confidence']:.3f}, 卦象: {result['hexagram_cn']})")
            else:
                result["error"] = infer_result.get('fail_closed_reason', '推理失败')
                logger.warning(f"⚠ {symbol} 推理失败: {result['error']}")
            
        except Exception as e:
            result["error"] = str(e)
            logger.error(f"❌ {symbol} 分析失败: {e}")
            import traceback
            traceback.print_exc()
        
        result["latency_ms"] = round((time.time() - start_time) * 1000, 2)
        return result
    
    def run_scan_all(self) -> Dict[str, Any]:
        """扫描所有币种"""
        logger.info("=" * 60)
        logger.info(f"🚀 Dream OS BCRM 2.0 每小时调度开始 ({len(self.symbols)} 个币种)")
        logger.info(f"   配置: WDH={self.wdh_enabled}, 美林时钟={self.merrill_enabled}, 模式={'模拟' if self.dry_run else '实盘'}")
        logger.info("=" * 60)
        
        results = {}
        total_start = time.time()
        
        for symbol in self.symbols:
            try:
                result = self.analyze_symbol(symbol)
                results[symbol] = result
                
                # 保存到数据库
                self.db.save_analysis(symbol, result)
                
            except Exception as e:
                logger.error(f"❌ {symbol} 扫描异常: {e}")
                results[symbol] = {"error": str(e), "symbol": symbol}
            
            time.sleep(0.5)
        
        total_time = round(time.time() - total_start, 2)
        
        # 生成摘要
        summary = self._generate_summary(results, total_time)
        
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
    
    def _generate_summary(self, results: Dict, total_time: float) -> Dict:
        """生成执行摘要"""
        total = len(results)
        up_count = sum(1 for r in results.values() if r.get('direction') == 'UP')
        down_count = sum(1 for r in results.values() if r.get('direction') == 'DOWN')
        flat_count = sum(1 for r in results.values() if r.get('direction') == 'FLAT')
        error_count = sum(1 for r in results.values() if r.get('error'))
        
        avg_confidence = 0
        avg_latency = 0
        n_valid = 0
        
        for r in results.values():
            if not r.get('error'):
                avg_confidence += r.get('confidence', 0)
                avg_latency += r.get('latency_ms', 0)
                n_valid += 1
        
        if n_valid > 0:
            avg_confidence = round(avg_confidence / n_valid, 3)
            avg_latency = round(avg_latency / n_valid, 2)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "total_symbols": total,
            "up_count": up_count,
            "down_count": down_count,
            "flat_count": flat_count,
            "error_count": error_count,
            "avg_confidence": avg_confidence,
            "avg_latency_ms": avg_latency,
            "total_time_s": total_time,
            "wdh_enabled": self.wdh_enabled,
            "merrill_enabled": self.merrill_enabled,
            "dry_run": self.dry_run,
            "db_stats": self.db.get_stats(),
        }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Dream OS BCRM 2.0 每小时调度任务")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS, help="分析币种")
    parser.add_argument("--dry-run", action="store_true", default=True, help="模拟模式")
    parser.add_argument("--wdh", action="store_true", default=True, help="启用WDH时间特征")
    parser.add_argument("--merrill", action="store_true", default=True, help="启用美林时钟")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    
    args = parser.parse_args()
    
    setup_logging(args.log_level)
    
    runner = BCRM2HourlyRunner(
        symbols=args.symbols,
        dry_run=args.dry_run,
        wdh_enabled=args.wdh,
        merrill_enabled=args.merrill,
    )
    
    result = runner.run_scan_all()
    
    # 输出摘要
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))
    
    return result


if __name__ == "__main__":
    main()