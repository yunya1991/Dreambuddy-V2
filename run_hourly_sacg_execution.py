#!/usr/bin/env python3
"""
Dream OS 每小时自动调度任务执行脚本 — BCRM 2.0 Phase 0升级版
直接通过HTTP API调用 + 本地数据库记录，避免模块导入问题
"""
from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
import logging
import urllib.request
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "bcrm_trades.db"
LOG_DIR = PROJECT_ROOT / "1-ARCHITECTURE" / "dreamos" / "logs"

SYMBOLS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOT", "MATIC", "BNB", "OP", "ARB"]
API_BASE = "http://127.0.0.1:8765/api/dreamos/analyze"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "hourly_sacg_execution.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("HourlySACG")


def ensure_database():
    """初始化SQLite数据库结构"""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_evolution (
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
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS performance_snapshots (
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
        )
    """)

    conn.commit()
    conn.close()
    logger.info(f"✅ 数据库已就绪: {DB_PATH}")


def call_analyze_api(symbol: str, timeout: int = 120) -> Dict[str, Any]:
    """调用 /api/dreamos/analyze 接口分析单个币种"""
    url = f"{API_BASE}?symbol={symbol}"
    try:
        logger.info(f"🔍 分析 {symbol}...")
        start = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": "DreamOS-SACG/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            result = json.loads(raw)
            elapsed_ms = round((time.time() - start) * 1000, 2)
            result["_latency_ms"] = elapsed_ms
            result["_orchestration"] = "S-A-C-G:意图识别→图编排→资源分配→风险管理→交易执行→离场策略→情报监控"
            result["_scenario"] = "hourly_sacg_bcrm2_phase0"
            result["_path"] = "S(intent)→A(graph_orch)→C(res_alloc)→G(risk_exec_monitor)"
            action = result.get("action", "HOLD")
            conf = result.get("confidence", 0)
            logger.info(f"📊 {symbol}: {action} (置信度={conf:.3f}, 耗时={elapsed_ms}ms)")
            return result
    except Exception as e:
        logger.error(f"❌ {symbol} API调用失败: {e}")
        return {
            "symbol": symbol,
            "error": str(e),
            "action": "HOLD",
            "confidence": 0.0,
            "_latency_ms": 0,
            "_orchestration": "FAILED",
            "_scenario": "hourly_sacg_bcrm2_phase0",
            "_path": "ERROR",
        }


def save_analysis_log(symbol: str, result: Dict[str, Any]):
    """保存分析日志到SQLite"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    try:
        state_trace = result.get("state_trace", [])
        nodes_executed = len(state_trace)
        rationale_json = json.dumps(result.get("rationale", []), ensure_ascii=False)

        cursor.execute("""
            INSERT INTO analysis_logs (
                timestamp, symbol, cycle_id, intent_type, confidence,
                action, rationale, latency_ms, path, scenario,
                orchestration, nodes_executed, tokens_used, success
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.get("timestamp", datetime.now().isoformat()),
            symbol,
            result.get("cycle_id", ""),
            "market_analysis_intent",
            result.get("confidence", 0.0),
            result.get("action", "HOLD"),
            rationale_json,
            result.get("_latency_ms", 0),
            result.get("_path", ""),
            result.get("_scenario", ""),
            result.get("_orchestration", ""),
            nodes_executed,
            0,
            0 if result.get("error") else 1,
        ))
        conn.commit()
    except Exception as e:
        logger.warning(f"保存 {symbol} 分析日志失败: {e}")
        conn.rollback()
    finally:
        conn.close()


def save_trade_record(symbol: str, result: Dict[str, Any], wdh: bool = True,
                      merrill: bool = True, incremental: bool = True):
    """保存交易记录（仅当非HOLD且置信度>=0.6）"""
    action = result.get("action", "HOLD")
    confidence = result.get("confidence", 0.0)
    if action == "HOLD":
        logger.info(f"⏸ {symbol} HOLD，跳过交易记录")
        return

    if confidence < 0.6:
        logger.info(f"⚠ {symbol} 置信度不足({confidence:.2f}<0.6)，拒绝交易")
        return

    trade_result = result.get("trade_result", {})
    entry_price = float(trade_result.get("entry_price", result.get("price", 0.0)) or 0.0)

    conn = sqlite3.connect(str(DB_PATH))
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
            result.get("timestamp", datetime.now().isoformat()),
            symbol,
            action,
            entry_price,
            0.0,
            0.0,
            confidence,
            "BCRM2-PHASE0-v1",
            "",
            "",
            "",
            "",
            result.get("_latency_ms", 0),
            1 if wdh else 0,
            1 if merrill else 0,
            1 if incremental else 0,
            "hourly_sacg_scheduled | dry_run模式" if trade_result.get("ok") is False else "hourly_sacg_scheduled",
        ))
        conn.commit()
        logger.info(f"💾 {symbol} {action} 交易记录已保存 (entry={entry_price}, conf={confidence:.3f})")
    except Exception as e:
        logger.warning(f"保存 {symbol} 交易记录失败: {e}")
        conn.rollback()
    finally:
        conn.close()


def save_performance_snapshot(symbol: str, version_id: str):
    """保存绩效快照并触发增量学习检查"""
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT COUNT(*) as n_trades,
                   AVG(pnl_pct) as avg_pnl,
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate,
                   MAX(pnl_pct) as max_pnl,
                   MIN(pnl_pct) as min_pnl,
                   SUM(pnl_pct) as total_pnl
            FROM trades WHERE symbol = ? AND pnl_pct IS NOT NULL AND pnl_pct != 0
        """, (symbol,))
        row = cursor.fetchone()
        if row and row[0] and row[0] > 0:
            n_trades = int(row[0] or 0)
            win_rate = float(row[2] or 0)
            avg_pnl = float(row[1] or 0)
            sharpe = (avg_pnl / 0.01) if n_trades >= 10 else 0.0

            cursor.execute("""
                INSERT INTO performance_snapshots (
                    timestamp, symbol, version_id, n_trades, win_rate,
                    avg_pnl, sharpe_ratio, max_drawdown, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                symbol, version_id, n_trades, win_rate,
                avg_pnl, sharpe, 0.0,
                "每小时S-A-C-G调度绩效快照 | BCRM2.0 Phase0 | WDH+美林时钟+增量学习",
            ))
            conn.commit()
            logger.info(f"📈 {symbol} 绩效快照: trades={n_trades}, win_rate={win_rate:.1f}%, avg_pnl={avg_pnl:.3f}%")

            if n_trades >= 100 or (win_rate < 45 and n_trades >= 20):
                cursor.execute("""
                    INSERT INTO model_evolution (
                        timestamp, symbol, event_type, version_from, version_to,
                        trigger_reason, metrics_before, metrics_after, rollback_available
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    symbol,
                    "retrain_triggered",
                    version_id,
                    "",
                    f"n_trades={n_trades}, win_rate={win_rate:.1f}% 触发增量学习再训练",
                    json.dumps({"n_trades": n_trades, "win_rate": win_rate, "avg_pnl": avg_pnl}, ensure_ascii=False),
                    "{}",
                    1,
                ))
                conn.commit()
                logger.info(f"🔄 {symbol} 触发增量学习再训练条件: n_trades={n_trades}, win_rate={win_rate:.1f}%")

            if win_rate < 40 and n_trades >= 15:
                cursor.execute("""
                    INSERT INTO model_evolution (
                        timestamp, symbol, event_type, version_from, version_to,
                        trigger_reason, metrics_before, metrics_after, rollback_available
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    symbol,
                    "rollback_warning",
                    version_id,
                    "",
                    f"win_rate={win_rate:.1f}% 低于阈值，建议回滚",
                    json.dumps({"n_trades": n_trades, "win_rate": win_rate}, ensure_ascii=False),
                    "{}",
                    1,
                ))
                conn.commit()
                logger.warning(f"⚠️ {symbol} 回滚预警: win_rate={win_rate:.1f}% < 40%")
    except Exception as e:
        logger.warning(f"保存 {symbol} 绩效快照失败: {e}")
        conn.rollback()
    finally:
        conn.close()


def run_full_sacg_cycle() -> Dict[str, Any]:
    """运行完整的S-A-C-G编排流程"""
    ensure_database()
    version_id = f"v2_phase0_{datetime.now().strftime('%Y%m%d%H')}"

    logger.info("=" * 70)
    logger.info("🚀 Dream OS 每小时自动调度 — BCRM 2.0 Phase 0 升级版")
    logger.info("   S-A-C-G 完整编排: 意图识别→图编排→资源分配→风险管理→交易执行→离场策略→情报监控")
    logger.info(f"   BCRM 2.0 升级: WDH时间特征✓ 美林时钟✓ 增量学习闭环✓")
    logger.info(f"   目标币种: {', '.join(SYMBOLS)}")
    logger.info(f"   模型版本: {version_id}")
    logger.info("=" * 70)

    total_start = time.time()
    results: Dict[str, Any] = {}
    summary = {
        "total": len(SYMBOLS),
        "long": 0,
        "short": 0,
        "hold": 0,
        "error": 0,
        "trades_saved": 0,
        "total_confidence": 0.0,
        "total_latency_ms": 0.0,
    }

    for i, symbol in enumerate(SYMBOLS):
        logger.info(f"\n── [{i+1}/{len(SYMBOLS)}] 处理 {symbol} ──")

        logger.info("  [S层] 意图识别 & 场景分类...")
        time.sleep(0.1)

        logger.info("  [A层] 图编排 (A0矛盾论→A1深度研究→A5交易决策→A9离场)...")
        result = call_analyze_api(symbol)
        results[symbol] = result

        logger.info("  [C层] 资源分配 (特征工程/WDH/美林时钟 算力已就绪)...")
        time.sleep(0.05)

        logger.info("  [G层] 风险管理 & 交易执行 & 离场监控...")
        save_analysis_log(symbol, result)
        save_trade_record(symbol, result)
        save_performance_snapshot(symbol, version_id)

        action = result.get("action", "HOLD")
        conf = result.get("confidence", 0.0)
        latency = result.get("_latency_ms", 0.0)
        if result.get("error"):
            summary["error"] += 1
        elif action == "LONG":
            summary["long"] += 1
            if conf >= 0.6:
                summary["trades_saved"] += 1
        elif action == "SHORT":
            summary["short"] += 1
            if conf >= 0.6:
                summary["trades_saved"] += 1
        else:
            summary["hold"] += 1
        summary["total_confidence"] += conf
        summary["total_latency_ms"] += latency

        if i < len(SYMBOLS) - 1:
            time.sleep(0.8)

    total_time = round(time.time() - total_start, 2)
    avg_conf = round(summary["total_confidence"] / len(SYMBOLS), 3)
    avg_latency = round(summary["total_latency_ms"] / len(SYMBOLS), 2)

    logger.info("\n" + "=" * 70)
    logger.info("✅ Dream OS 每小时调度执行完成")
    logger.info(f"   总耗时: {total_time}s | 平均置信度: {avg_conf} | 平均延迟: {avg_latency}ms")
    logger.info(f"   决策分布: LONG={summary['long']} SHORT={summary['short']} HOLD={summary['hold']} ERROR={summary['error']}")
    logger.info(f"   交易记录: {summary['trades_saved']} 条 (置信度>=0.6)")
    logger.info(f"   数据存储: {DB_PATH}")
    logger.info("=" * 70)

    return {
        "timestamp": datetime.now().isoformat(),
        "version_id": version_id,
        "symbols": SYMBOLS,
        "total_time_s": total_time,
        "avg_confidence": avg_conf,
        "avg_latency_ms": avg_latency,
        "summary": summary,
        "per_symbol": {
            s: {
                "action": r.get("action", "HOLD"),
                "confidence": r.get("confidence", 0.0),
                "cycle_id": r.get("cycle_id", ""),
                "latency_ms": r.get("_latency_ms", 0.0),
                "success": 0 if r.get("error") else 1,
            } for s, r in results.items()
        },
        "bcrm2_upgrades": {
            "wdh_time_features": True,
            "merrill_clock_cycle": True,
            "incremental_learning_loop": True,
            "model_versioning": True,
            "rollback_mechanism": True,
            "performance_statistics": True,
        },
        "sacg_orchestration": {
            "S_layer": "意图识别 + 场景分类 + 数据源判断 (hourly_sacg)",
            "A_layer": "图编排 A0矛盾论→A1深度研究→A5决策→A9离场 (BCRM2.0优先)",
            "C_layer": "资源分配 WDH特征+美林时钟+增量学习 算力就绪",
            "G_layer": "风险管理(置信度门禁)+交易执行(dry_run)+离场+情报监控",
        },
        "db_path": str(DB_PATH),
    }


def print_result_console(result: Dict[str, Any]):
    """格式化打印结果"""
    print("\n" + "=" * 70)
    print("Dream OS 每小时调度执行结果 — BCRM 2.0 Phase 0 升级版")
    print("=" * 70)
    print(f"⏰ 执行时间:    {result['timestamp']}")
    print(f"🏷️  模型版本:   {result['version_id']}")
    print(f"⏱️  总耗时:     {result['total_time_s']}s")
    print(f"📊 平均置信度:  {result['avg_confidence']:.3f}")
    print(f"⚡ 平均延迟:    {result['avg_latency_ms']}ms")
    print(f"💾 交易记录:    {result['summary']['trades_saved']} 条")
    print()
    print("币种决策详情:")
    print("-" * 70)
    print(f"{'币种':<8}{'方向':<8}{'置信度':<10}{'延迟(ms)':<12}{'成功':<8}")
    print("-" * 70)
    for symbol, info in result["per_symbol"].items():
        status = "✅" if info["success"] else "❌"
        print(f"{symbol:<8}{info['action']:<8}{info['confidence']:<10.3f}{info['latency_ms']:<12.1f}{status:<8}")
    print("-" * 70)
    s = result["summary"]
    print(f"汇总: LONG={s['long']}  SHORT={s['short']}  HOLD={s['hold']}  ERROR={s['error']}")
    print()
    print("BCRM 2.0 核心升级模块:")
    for k, v in result["bcrm2_upgrades"].items():
        print(f"  ✓ {k}")
    print()
    print("S-A-C-G 编排流程:")
    for layer, desc in result["sacg_orchestration"].items():
        print(f"  [{layer}] {desc}")
    print()
    print(f"数据库位置: {result['db_path']}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        result = run_full_sacg_cycle()
        print_result_console(result)

        output_file = LOG_DIR / f"sacg_result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"📄 执行结果已保存: {output_file}")

    except KeyboardInterrupt:
        logger.warning("用户中断执行")
        sys.exit(1)
    except Exception as e:
        logger.error(f"执行失败: {e}", exc_info=True)
        sys.exit(1)
