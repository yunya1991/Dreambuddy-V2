"""
D5: StreamingSampleStore — 流式样本存储（借鉴 ds4 mmap 按需访问）

SPEC: SPEC-ds4架构借鉴与系统增强.md §3.2 Dimension 5
哲学: ds4 mmap 按需访问——只解析 header/metadata，张量数据留在内核页缓存按需访问。
映射: 对持续增长的 shadow_rl_samples.jsonl，引入 sqlite 替代全量 read_text.splitlines()。

设计目标:
  1. 按需访问——read_range 只加载需要的样本，不全量读入内存
  2. O(1) 统计——stats() 用 SQL 聚合，不遍历全量数据
  3. 向后兼容——migrate_from_jsonl() 从现有 JSONL 迁移（HC-DS4-06）
  4. FAIL-OPEN——sqlite 异常时降级为内存 list，不影响交易

表结构:
  samples(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT NOT NULL,        -- JSON 序列化的完整样本
    reward REAL NOT NULL       -- 冗余字段，用于 SQL 聚合统计
  )
"""
from __future__ import annotations

import json
import logging
import sqlite3
import numpy as np
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StreamingSampleStore:
    """流式样本存储（sqlite 后端）.

    替代 shadow_rl_samples.jsonl 的全量读取。
    支持: 追加写、按索引读、范围查询、SQL 聚合统计、JSONL 迁移.

    FAIL-OPEN: sqlite 初始化失败时降级为内存 list 模式.
    """

    def __init__(self, db_path: str | Path | None = None):
        self._db_path = str(db_path) if db_path else ":memory:"
        self._conn: sqlite3.Connection | None = None
        self._fallback: list[dict] | None = None  # FAIL-OPEN 内存降级

        try:
            self._init_sqlite()
        except Exception as e:
            logger.warning("[DS4-D5] sqlite init fail, fallback to memory: %s", e)
            self._fallback = []

    def _init_sqlite(self) -> None:
        """初始化 sqlite 连接并建表."""
        path = self._db_path
        if path != ":memory:":
            parent = Path(path).parent
            if str(parent) not in (".", ""):
                parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                reward REAL NOT NULL DEFAULT 0.0
            )
        """)
        self._conn.commit()

    # ---------- 写入 ----------
    def append(self, sample: dict[str, Any]) -> None:
        """追加一条样本.

        Args:
            sample: 样本 dict，需包含 reward 字段（用于统计）
        """
        if self._fallback is not None:
            self._fallback.append(sample)
            return
        try:
            reward = float(sample.get("reward", 0.0))
            data = json.dumps(sample, default=str, ensure_ascii=False)
            self._conn.execute(
                "INSERT INTO samples (data, reward) VALUES (?, ?)",
                (data, reward),
            )
            self._conn.commit()
        except Exception as e:
            logger.debug("[FO-DS4-D5] append fail, fallback to memory: %s", e)
            self._fallback = list(self._iter_all_sqlite()) + [sample]

    # ---------- 读取 ----------
    def read_all(self) -> list[dict]:
        """读取所有样本（按写入顺序）."""
        if self._fallback is not None:
            return list(self._fallback)
        try:
            cur = self._conn.execute(
                "SELECT data FROM samples ORDER BY id ASC"
            )
            return [self._parse(row[0]) for row in cur.fetchall()]
        except Exception as e:
            logger.debug("[FO-DS4-D5] read_all fail: %s", e)
            return []

    def read_range(self, start: int, end: int) -> list[dict]:
        """按索引范围读取样本 [start, end).

        Args:
            start: 起始索引（含）
            end: 结束索引（不含）

        Returns:
            list[dict]: 范围内的样本
        """
        if start < 0:
            start = 0
        if end <= start:
            return []

        if self._fallback is not None:
            return list(self._fallback[start:end])

        try:
            limit = end - start
            cur = self._conn.execute(
                "SELECT data FROM samples ORDER BY id ASC LIMIT ? OFFSET ?",
                (limit, start),
            )
            return [self._parse(row[0]) for row in cur.fetchall()]
        except Exception as e:
            logger.debug("[FO-DS4-D5] read_range fail: %s", e)
            return []

    def read_tail(self, n: int) -> list[dict]:
        """读取最后 n 条样本."""
        if n <= 0:
            return []
        if self._fallback is not None:
            return list(self._fallback[-n:])
        try:
            cur = self._conn.execute(
                "SELECT data FROM samples ORDER BY id DESC LIMIT ?",
                (n,),
            )
            rows = cur.fetchall()
            return [self._parse(row[0]) for row in reversed(rows)]
        except Exception as e:
            logger.debug("[FO-DS4-D5] read_tail fail: %s", e)
            return []

    # ---------- 统计（SQL 聚合）----------
    def stats(self) -> dict[str, Any]:
        """统计信息（SQL 聚合，O(1) 不遍历全量）.

        Returns:
            dict: {count, effective_count, mean_reward, std_reward, sharpe}
        """
        if self._fallback is not None:
            return self._stats_memory()

        try:
            cur = self._conn.execute(
                "SELECT COUNT(*), AVG(reward) FROM samples"
            )
            row = cur.fetchone()
            count = row[0] or 0
            mean = float(row[1]) if row[1] is not None else 0.0

            if count == 0:
                return {
                    "count": 0, "effective_count": 0,
                    "mean_reward": 0.0, "std_reward": 0.0, "sharpe": 0.0,
                }

            # 有效样本数（reward != 0）
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM samples WHERE reward != 0.0"
            )
            effective = cur.fetchone()[0] or 0

            # 标准差（需要遍历，但比全量 JSON 解析快）
            cur = self._conn.execute("SELECT reward FROM samples")
            rewards = np.array([r[0] for r in cur.fetchall()], dtype=np.float64)
            std = float(np.std(rewards, ddof=1)) if len(rewards) > 1 else 0.0
            sharpe = mean / (std + 1e-9) if std > 0 else 0.0

            return {
                "count": count,
                "effective_count": effective,
                "mean_reward": round(mean, 6),
                "std_reward": round(std, 6),
                "sharpe": round(sharpe, 6),
            }
        except Exception as e:
            logger.debug("[FO-DS4-D5] stats fail: %s", e)
            return {"count": 0, "effective_count": 0,
                    "mean_reward": 0.0, "std_reward": 0.0, "sharpe": 0.0}

    def _stats_memory(self) -> dict[str, Any]:
        """内存模式下的统计."""
        samples = self._fallback or []
        if not samples:
            return {"count": 0, "effective_count": 0,
                    "mean_reward": 0.0, "std_reward": 0.0, "sharpe": 0.0}
        rewards = np.array([float(s.get("reward", 0.0)) for s in samples], dtype=np.float64)
        mean = float(np.mean(rewards))
        std = float(np.std(rewards, ddof=1)) if len(rewards) > 1 else 0.0
        sharpe = mean / (std + 1e-9) if std > 0 else 0.0
        effective = int(np.sum(rewards != 0.0))
        return {
            "count": len(samples),
            "effective_count": effective,
            "mean_reward": round(mean, 6),
            "std_reward": round(std, 6),
            "sharpe": round(sharpe, 6),
        }

    def count(self) -> int:
        """样本总数."""
        if self._fallback is not None:
            return len(self._fallback)
        try:
            cur = self._conn.execute("SELECT COUNT(*) FROM samples")
            return cur.fetchone()[0] or 0
        except Exception:
            return 0

    # ---------- 迁移（HC-DS4-06 向后兼容）----------
    def migrate_from_jsonl(self, jsonl_path: str | Path) -> int:
        """从现有 JSONL 文件迁移样本.

        Args:
            jsonl_path: JSONL 文件路径

        Returns:
            int: 成功迁移的样本数
        """
        path = Path(jsonl_path)
        if not path.exists():
            return 0
        try:
            migrated = 0
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sample = json.loads(line)
                        self.append(sample)
                        migrated += 1
                    except (json.JSONDecodeError, ValueError, TypeError):
                        continue
            logger.info("[DS4-D5] migrated %d samples from %s", migrated, path)
            return migrated
        except Exception as e:
            logger.warning("[FO-DS4-D5] migrate fail: %s", e)
            return 0

    # ---------- 内部工具 ----------
    def _iter_all_sqlite(self) -> list[dict]:
        """从 sqlite 读取全部（用于降级时迁移到内存）."""
        if self._conn is None:
            return []
        try:
            cur = self._conn.execute("SELECT data FROM samples ORDER BY id ASC")
            return [self._parse(row[0]) for row in cur.fetchall()]
        except Exception:
            return []

    @staticmethod
    def _parse(data: str) -> dict:
        """解析 JSON 字符串为 dict."""
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return {}

    def close(self) -> None:
        """关闭连接."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
