"""
增量学习闭环 — 实盘数据反哺模型

BCRM理论映射:
  - 实践-认识-再实践-再认识: 交易→学习→再交易→再学习的循环
  - 量变积累: 积累交易数据达到阈值后触发再训练
  - 质变: 再训练后模型性能提升
  - 否定之否定: 旧模型被新模型否定, 但保留有用信息

核心组件:
  1. 交易记录存储 (SQLite)
  2. 模型版本管理
  3. 增量训练
  4. 再训练触发机制
"""

import sqlite3
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd

from .dialectical_ml_engine import DialecticalMLEngine


class TradeDatabase:
    """交易记录数据库"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(Path(__file__).parent.parent.parent / "data" / "bcrm_trades.db")
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 交易记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                direction INTEGER NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT,
                entry_price REAL NOT NULL,
                exit_price REAL,
                pnl_pct REAL,
                hold_bars INTEGER,
                exit_reason TEXT,
                confidence REAL,
                hexagram TEXT,
                upper_gua TEXT,
                lower_gua TEXT,
                position_factor REAL,
                model_version TEXT,
                fold_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, entry_time, direction)
            )
        """)

        # 模型版本表
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
                notes TEXT
            )
        """)

        # 模型性能监控表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS model_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                n_trades INTEGER,
                win_rate REAL,
                avg_pnl REAL,
                max_drawdown REAL,
                FOREIGN KEY(version_id) REFERENCES model_versions(version_id)
            )
        """)

        conn.commit()
        conn.close()

    def add_trade(self, trade_data: Dict) -> int:
        """添加交易记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO trades (
                    symbol, direction, entry_time, exit_time,
                    entry_price, exit_price, pnl_pct, hold_bars,
                    exit_reason, confidence, hexagram, upper_gua,
                    lower_gua, position_factor, model_version, fold_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_data.get("symbol", ""),
                trade_data.get("direction", 0),
                trade_data.get("entry_time", ""),
                trade_data.get("exit_time", ""),
                trade_data.get("entry_price", 0),
                trade_data.get("exit_price", 0),
                trade_data.get("pnl_pct", 0),
                trade_data.get("hold_bars", 0),
                trade_data.get("exit_reason", ""),
                trade_data.get("confidence", 0),
                trade_data.get("hexagram", ""),
                trade_data.get("upper_gua", ""),
                trade_data.get("lower_gua", ""),
                trade_data.get("position_factor", 1.0),
                trade_data.get("model_version", ""),
                trade_data.get("fold_id", 0),
            ))
            conn.commit()
            return cursor.lastrowid
        except Exception:
            conn.rollback()
            return -1
        finally:
            conn.close()

    def add_trades_batch(self, trades: List[Dict]) -> int:
        """批量添加交易记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            for trade in trades:
                cursor.execute("""
                    INSERT OR IGNORE INTO trades (
                        symbol, direction, entry_time, exit_time,
                        entry_price, exit_price, pnl_pct, hold_bars,
                        exit_reason, confidence, hexagram, upper_gua,
                        lower_gua, position_factor, model_version, fold_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.get("symbol", ""),
                    trade.get("direction", 0),
                    trade.get("entry_time", ""),
                    trade.get("exit_time", ""),
                    trade.get("entry_price", 0),
                    trade.get("exit_price", 0),
                    trade.get("pnl_pct", 0),
                    trade.get("hold_bars", 0),
                    trade.get("exit_reason", ""),
                    trade.get("confidence", 0),
                    trade.get("hexagram", ""),
                    trade.get("upper_gua", ""),
                    trade.get("lower_gua", ""),
                    trade.get("position_factor", 1.0),
                    trade.get("model_version", ""),
                    trade.get("fold_id", 0),
                ))
            conn.commit()
            return len(trades)
        except Exception:
            conn.rollback()
            return 0
        finally:
            conn.close()

    def save_model_version(self, version_id: str, symbol: str,
                          metrics: Dict, notes: str = "") -> bool:
        """保存模型版本"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO model_versions (
                    version_id, symbol, created_at, sharpe_ratio,
                    win_rate, total_trades, train_bars, feature_count, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_model_versions(self, symbol: str = None) -> List[Dict]:
        """获取模型版本列表"""
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

    def get_latest_version(self, symbol: str) -> Optional[Dict]:
        """获取最新模型版本"""
        versions = self.get_model_versions(symbol)
        return versions[0] if versions else None

    def get_trades_for_retraining(self, symbol: str,
                                  min_trades: int = 100) -> List[Dict]:
        """获取用于再训练的交易数据"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT * FROM trades WHERE symbol = ?
                ORDER BY entry_time DESC LIMIT ?
            """, (symbol, min_trades * 2))

            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
        except Exception:
            return []
        finally:
            conn.close()

    def get_recent_performance(self, symbol: str, days: int = 30) -> Dict:
        """获取最近一段时间的模型表现"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT COUNT(*) as n_trades,
                       AVG(pnl_pct) as avg_pnl,
                       SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
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


class ModelVersionManager:
    """模型版本管理器"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(Path(__file__).parent.parent.parent / "models")
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def get_version_dir(self, symbol: str, version_id: str) -> str:
        """获取版本目录"""
        return os.path.join(self.base_dir, symbol, version_id)

    def save_version(self, engine: DialecticalMLEngine, symbol: str,
                     version_id: str, metrics: Dict, notes: str = "") -> bool:
        """保存模型版本"""
        version_dir = self.get_version_dir(symbol, version_id)
        os.makedirs(version_dir, exist_ok=True)

        # 保存模型文件
        engine.save(version_dir)

        # 保存版本元数据
        meta = {
            "version_id": version_id,
            "symbol": symbol,
            "created_at": datetime.now().isoformat(),
            "metrics": metrics,
            "notes": notes,
        }
        with open(os.path.join(version_dir, "version_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # 更新latest软链接
        latest_dir = os.path.join(self.base_dir, symbol, "latest")
        if os.path.islink(latest_dir):
            os.remove(latest_dir)
        elif os.path.isdir(latest_dir):
            shutil.rmtree(latest_dir)
        os.symlink(version_dir, latest_dir)

        return True

    def load_version(self, symbol: str, version_id: str = "latest") -> Optional[DialecticalMLEngine]:
        """加载模型版本"""
        if version_id == "latest":
            version_dir = os.path.join(self.base_dir, symbol, "latest")
            if not os.path.exists(version_dir):
                return None
            version_dir = os.path.realpath(version_dir)
        else:
            version_dir = self.get_version_dir(symbol, version_id)
            if not os.path.exists(version_dir):
                return None

        # 加载元数据
        meta_path = os.path.join(version_dir, "version_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        else:
            meta = {}

        # 加载模型
        engine = DialecticalMLEngine(
            feature_names=meta.get("metrics", {}).get("feature_names", []),
            feature_names_by_gua=meta.get("metrics", {}).get("feature_names_by_gua", {}),
        )
        engine.load(version_dir)

        return engine

    def list_versions(self, symbol: str) -> List[Dict]:
        """列出模型版本"""
        symbol_dir = os.path.join(self.base_dir, symbol)
        if not os.path.exists(symbol_dir):
            return []

        versions = []
        for item in os.listdir(symbol_dir):
            item_path = os.path.join(symbol_dir, item)
            if os.path.isdir(item_path) and item != "latest":
                meta_path = os.path.join(item_path, "version_meta.json")
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    versions.append(meta)
                else:
                    versions.append({
                        "version_id": item,
                        "symbol": symbol,
                        "created_at": datetime.fromtimestamp(
                            os.path.getctime(item_path)).isoformat(),
                        "metrics": {},
                        "notes": "",
                    })

        return sorted(versions, key=lambda x: x["created_at"], reverse=True)

    def rollback(self, symbol: str, version_id: str) -> bool:
        """回退到指定版本"""
        version_dir = self.get_version_dir(symbol, version_id)
        if not os.path.exists(version_dir):
            return False

        latest_dir = os.path.join(self.base_dir, symbol, "latest")
        if os.path.islink(latest_dir):
            os.remove(latest_dir)
        elif os.path.isdir(latest_dir):
            shutil.rmtree(latest_dir)
        os.symlink(version_dir, latest_dir)

        return True


class IncrementalLearner:
    """
    增量学习引擎

    核心功能:
      1. 监控模型表现
      2. 当触发条件满足时, 自动进行增量训练
      3. 保存新版本并更新生产模型

    触发条件:
      - 积累N笔新交易
      - 胜率连续N天下降
      - 夏普比率低于阈值
      - 手动触发
    """

    def __init__(
        self,
        db_path: str = None,
        model_dir: str = None,
        retrain_trade_threshold: int = 100,    # 积累N笔交易触发再训练
        retrain_win_rate_threshold: float = 0.5,  # 胜率低于此值触发再训练
        retrain_sharpe_threshold: float = 1.0,    # 夏普低于此值触发再训练
        max_versions: int = 10,                 # 保留最多N个版本
    ):
        self.db = TradeDatabase(db_path)
        self.version_manager = ModelVersionManager(model_dir)
        self.retrain_trade_threshold = retrain_trade_threshold
        self.retrain_win_rate_threshold = retrain_win_rate_threshold
        self.retrain_sharpe_threshold = retrain_sharpe_threshold
        self.max_versions = max_versions

    def should_retrain(self, symbol: str) -> Tuple[bool, str]:
        """判断是否需要再训练"""
        performance = self.db.get_recent_performance(symbol)
        n_trades = performance.get("n_trades", 0)
        win_rate = performance.get("win_rate", 0) / 100 if performance.get("win_rate") else 0

        # 条件1: 积累足够交易
        if n_trades >= self.retrain_trade_threshold:
            return True, f"积累{self.retrain_trade_threshold}笔交易"

        # 条件2: 胜率低于阈值
        if win_rate > 0 and win_rate < self.retrain_win_rate_threshold:
            return True, f"胜率{win_rate:.1%}低于阈值{self.retrain_win_rate_threshold:.1%}"

        return False, ""

    def run_incremental_training(
        self,
        symbol: str,
        engine: DialecticalMLEngine,
        X_new: np.ndarray,
        y_new: np.ndarray,
        feature_names: List[str],
        metrics: Dict,
        notes: str = "",
    ) -> Tuple[bool, str, Optional[str]]:
        """
        运行增量训练

        Args:
            symbol: 交易对
            engine: 当前模型引擎
            X_new: 新特征数据
            y_new: 新标签数据
            feature_names: 特征名称列表
            metrics: 训练指标
            notes: 版本备注

        Returns:
            (成功标志, 消息, 版本ID)
        """
        lgb = None
        try:
            import lightgbm as lgb
        except ImportError:
            return False, "LightGBM未安装", None

        # 生成版本ID
        version_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 增量训练: 在已有模型基础上继续训练
        if engine.l1_model is not None:
            # 创建新的训练数据集
            lgb_train = lgb.Dataset(X_new, label=y_new)

            # 在已有模型基础上继续训练
            engine.l1_model = lgb.train(
                engine.l1_params,
                lgb_train,
                num_boost_round=50,
                init_model=engine.l1_model,
                verbose_eval=False,
            )

        # 保存新版本
        success = self.version_manager.save_version(engine, symbol, version_id, metrics, notes)
        if not success:
            return False, "保存版本失败", None

        # 保存到数据库
        self.db.save_model_version(version_id, symbol, metrics, notes)

        # 清理旧版本
        self._cleanup_old_versions(symbol)

        return True, f"增量训练完成, 版本{version_id}", version_id

    def log_trade(self, trade_data: Dict, model_version: str = "") -> int:
        """记录交易到数据库"""
        trade_data["model_version"] = model_version
        return self.db.add_trade(trade_data)

    def log_trades_batch(self, trades: List[Dict], model_version: str = "") -> int:
        """批量记录交易"""
        for t in trades:
            t["model_version"] = model_version
        return self.db.add_trades_batch(trades)

    def get_dashboard_data(self, symbol: str) -> Dict:
        """获取仪表盘数据"""
        latest_version = self.db.get_latest_version(symbol)
        performance = self.db.get_recent_performance(symbol)
        versions = self.db.get_model_versions(symbol)

        return {
            "symbol": symbol,
            "latest_version": latest_version,
            "recent_performance": performance,
            "n_versions": len(versions),
            "total_trades": performance.get("n_trades", 0),
        }

    def _cleanup_old_versions(self, symbol: str):
        """清理旧版本, 保留最近N个"""
        versions = self.version_manager.list_versions(symbol)
        if len(versions) <= self.max_versions:
            return

        # 删除最旧的版本
        versions_to_delete = sorted(versions, key=lambda x: x["created_at"])[:-self.max_versions]
        for v in versions_to_delete:
            version_dir = self.version_manager.get_version_dir(symbol, v["version_id"])
            if os.path.exists(version_dir):
                shutil.rmtree(version_dir)
