"""
TradeIndexBuilder — 系统级交易索引库构建器

聚合所有子交易系统的交易记录到统一索引库，供反思学习扫描器全局读取。

设计目标：
- 自动发现系统中所有交易记录源（JSONL + SQLite），无需手动配置
- 统一字段口径（coin/direction/pnl_pct/exit_time/source_system）
- 按 trade_id 去重，避免重复统计
- 增量构建，只处理新增记录

索引库位置: <project_root>/.workbuddy/trade_index/all_trades_index.jsonl
"""

import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 交易记录特征字段（用于自动发现）
_TRADE_SIGNATURE_FIELDS = {
    "trade_id",
    "coin",
    "symbol",
    "pnl",
    "pnl_pct",
    "entry_price",
    "exit_price",
    "direction",
}

# 自动发现时排除的目录
_EXCLUDE_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    "versions",
    "snapshots",
    "macro_cache",
    "chrome-profile",
    ".sandbox-home",
    "chroma_db",
}

# 自动发现时排除的文件名模式（日志/测试数据等）
_EXCLUDE_PATTERNS = {
    "trader_2",  # trader_YYYYMMDD.jsonl 是运行日志
    "decision_log",  # 决策日志不是已平仓交易
    "test_",
    "session_memory",
}

# SQLite 交易表特征名
_SQLITE_TRADE_TABLES = {"trades", "closed_trades", "trade_history"}


class TradeIndexBuilder:
    """系统级交易索引库构建器 — 自动发现 + 聚合所有子系统交易记录"""

    # 索引库默认路径（项目根下）
    DEFAULT_INDEX_PATH = ".workbuddy/trade_index/all_trades_index.jsonl"

    # 已知交易记录源配置（作为保底，自动发现会补充更多）
    KNOWN_SOURCES = [
        {
            "path": "22-执行引擎中心/runtime/position_ledger.db",
            "source": "22-ledger",
            "type": "sqlite",
            "table": "fills",
            # F8: 排除 22 reconcile 产生的平仓流水（realized_pnl 恒 0，不是真实交易，
            # 计入会把 win_rate 拉向 0，导致 reflection_ri 恒 0.5）
            "where": (
                "action IN ('close','reduce','reduce_only') "
                "AND COALESCE(source,'') NOT LIKE '%reconcil%'"
            ),
        },
        {
            "path": ".workbuddy/trade_index/backtest_trades.jsonl",
            "source": "backtest",
            "type": "closed",
        },
    ]

    # 缓存 TTL
    CACHE_TTL = 300  # 5 分钟（索引构建）
    DISCOVERY_CACHE_TTL = 3600  # 1 小时（源发现，更慢才重扫）

    # 自动发现扫描深度限制
    MAX_SCAN_DEPTH = 5

    def __init__(
        self, project_root: str | Path | None = None, index_path: str | Path | None = None
    ):
        if project_root is None:
            project_root = Path.cwd()
        self._project_root = Path(project_root)
        if index_path is None:
            self._index_path = self._project_root / self.DEFAULT_INDEX_PATH
        else:
            self._index_path = Path(index_path)

        self._cache: list[dict[str, Any]] | None = None
        self._cache_ts: float = 0.0

        # 源发现缓存
        self._discovered_sources: list[dict[str, Any]] | None = None
        self._discovery_ts: float = 0.0

    # ==================================================================
    # 自动发现机制
    # ==================================================================

    def _discover_sources(self) -> list[dict[str, Any]]:
        """
        自动扫描项目目录，发现所有交易记录源。

        扫描策略：
        1. 遍历项目目录（限 MAX_SCAN_DEPTH 层）
        2. 对 .jsonl 文件：读首行，检查是否含交易特征字段
        3. 对 .db/.sqlite 文件：检查是否有 trades 表
        4. 排除日志、测试数据、缓存等
        5. 从路径推断来源子系统名
        """
        if self._discovered_sources is not None:
            if time.time() - self._discovery_ts < self.DISCOVERY_CACHE_TTL:
                return self._discovered_sources

        discovered: list[dict[str, Any]] = []
        seen_paths: set[str] = set()

        try:
            for item in self._walk_project():
                rel_path = str(item.relative_to(self._project_root))

                # 跳过排除模式
                if any(rel_path.startswith(p) or p in rel_path for p in _EXCLUDE_PATTERNS):
                    continue

                # 跳过索引库自身
                if rel_path == self.DEFAULT_INDEX_PATH:
                    continue

                # 跳过已知源（避免重复）
                if rel_path in seen_paths:
                    continue

                # 尝试 JSONL
                if item.suffix == ".jsonl":
                    src = self._try_discover_jsonl(item, rel_path)
                    if src:
                        discovered.append(src)
                        seen_paths.add(rel_path)

                # 尝试 SQLite
                elif item.suffix in (".db", ".sqlite", ".sqlite3"):
                    src = self._try_discover_sqlite(item, rel_path)
                    if src:
                        discovered.append(src)
                        seen_paths.add(rel_path)

        except Exception as e:
            logger.warning("[FO] discover_sources crash: %s", e)

        self._discovered_sources = discovered
        self._discovery_ts = time.time()
        return discovered

    def _walk_project(self):
        """遍历项目目录，返回候选文件（限深度、排除无用目录）"""
        for root, dirs, files in os.walk(self._project_root):
            # 计算深度
            rel_root = Path(root).relative_to(self._project_root)
            depth = len(rel_root.parts)
            if depth > self.MAX_SCAN_DEPTH:
                dirs.clear()
                continue

            # 排除无用目录
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS and not d.startswith(".")]

            for fname in files:
                if fname.endswith((".jsonl", ".db", ".sqlite", ".sqlite3")):
                    yield Path(root) / fname

    def _try_discover_jsonl(self, file_path: Path, rel_path: str) -> dict[str, Any] | None:
        """探测 JSONL 文件是否为交易记录"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                # 只读前 3 行，避免大文件
                for i, line in enumerate(f):
                    if i >= 3:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    fields = set(data.keys())
                    overlap = fields & _TRADE_SIGNATURE_FIELDS
                    # 至少命中 4 个交易字段才算交易记录
                    if len(overlap) >= 4:
                        # 排除 decision_log（outcome=PENDING 不是已平仓）
                        if data.get("outcome") == "PENDING":
                            continue
                        source = self._infer_source_name(rel_path)
                        return {
                            "path": rel_path,
                            "source": source,
                            "type": "closed",
                        }
        except Exception as e:
            logger.debug("[FO] 交易记录文件探测 fail: %s", e)
        return None

    def _try_discover_sqlite(self, file_path: Path, rel_path: str) -> dict[str, Any] | None:
        """探测 SQLite 文件是否有交易表"""
        try:
            import sqlite3

            conn = sqlite3.connect(str(file_path))
            cur = conn.cursor()
            tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            table_names = {t[0].lower() for t in tables}

            # 检查是否有交易表
            trade_table = None
            for tname in _SQLITE_TRADE_TABLES:
                if tname in table_names:
                    trade_table = tname
                    break

            if trade_table is None:
                conn.close()
                return None

            # 检查是否有数据
            count = cur.execute(f"SELECT COUNT(*) FROM {trade_table}").fetchone()[0]
            conn.close()

            if count == 0:
                return None

            source = self._infer_source_name(rel_path)
            return {
                "path": rel_path,
                "source": source,
                "type": "sqlite",
                "table": trade_table,
                "count": count,
            }
        except Exception:
            return None

    def _infer_source_name(self, rel_path: str) -> str:
        """从相对路径推断来源子系统名"""
        parts = Path(rel_path).parts
        # 取第一级目录名作为来源（如 "22-执行引擎中心" → "22"）
        if len(parts) > 0:
            top = parts[0]
            # 去掉数字前缀（如 "11-" → ""）
            if "-" in top:
                top = top.split("-", 1)[-1] if top[0].isdigit() else top
            # 简化中文名
            name_map = {
                "易经推理系统": "yijing",
                "四层闭环自进化交易架构": "evolution",
                "调控系统": "control",
                "架构": "arch",
                "数据获取中心": "datacenter",
                "通用风控模块": "risk",
                "基本面分析": "fundamental",
                "经典指标系统": "indicator",
            }
            return name_map.get(top, top[:12])
        return "unknown"

    # ==================================================================
    # 源聚合
    # ==================================================================

    def _glob_sources(self) -> list[dict[str, Any]]:
        """合并已知源 + 自动发现源"""
        sources = []
        base = self._repo_root()

        # 1. 已知源（通配符展开）；相对仓库根解析，23 子目录启动时也能读到 22 账本
        for src in self.KNOWN_SOURCES:
            pattern = src["path"]
            if "*" in pattern:
                for p in sorted(base.glob(pattern)):
                    sources.append(
                        {
                            **src,
                            "path": str(p.relative_to(base)),
                            "_root": str(base),
                        }
                    )
            else:
                if (base / pattern).exists():
                    sources.append({**src, "_root": str(base)})

        # 2. 自动发现源
        for src in self._discover_sources():
            # 去重：跳过已知源已覆盖的路径
            if not any(s["path"] == src["path"] for s in sources):
                sources.append(src)

        return sources

    def _repo_root(self) -> Path:
        """向上定位仓库根（含 22-执行引擎中心），避免 23 子目录启动时读不到 22 账本。"""
        cur = self._project_root
        for _ in range(4):
            if (cur / "22-执行引擎中心").exists():
                return cur
            if cur.parent == cur:
                break
            cur = cur.parent
        return self._project_root

    def _load_closed_trades(self, file_path: Path) -> list[dict[str, Any]]:
        """加载已平仓交易记录（jsonl 格式）"""
        trades = []
        if not file_path.exists():
            return trades
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        trades.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("[FO] load_closed_trades fail %s: %s", file_path, e)
        return trades

    def _load_sqlite_trades(
        self, file_path: Path, table: str, where: str | None = None
    ) -> list[dict[str, Any]]:
        """加载 SQLite 交易表（where 为可选过滤条件，供 fills 等流水表使用）"""
        trades = []
        try:
            conn = sqlite3.connect(str(file_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            sql = f"SELECT * FROM {table}"
            if where:
                sql = f"{sql} WHERE {where}"
            rows = cur.execute(sql).fetchall()
            for row in rows:
                trades.append(dict(row))
            conn.close()
        except Exception as e:
            logger.warning("[FO] load_sqlite_trades fail %s/%s: %s", file_path, table, e)
        return trades

    def _normalize_trade(
        self, raw: dict[str, Any], source: str, path: str = ""
    ) -> dict[str, Any] | None:
        """将各子系统的交易记录统一为索引库格式"""
        try:
            _inst = str(raw.get("inst_id") or "")
            coin = raw.get("coin") or raw.get("symbol") or (_inst.split("-")[0] if _inst else "")
            if not coin:
                return None
            # F8: 对账/幽灵仓清仓流水（source 含 reconcil）不是真实交易，收益恒 0，
            # 计入会污染 win_rate；自动发现的源同样适用，故在归一化层统一拦截
            if "reconcil" in str(raw.get("source") or "").lower():
                return None
            # F8: shadow_validation / ess_reflection / 「持仓消失」幽灵记录不是真实成交，
            # 其 pnl 为占位值（如 -100 / 0），不能进入 reflection 胜率统计
            _reason = str(raw.get("exit_reason") or "")
            _path_str = str(path)
            is_synthetic = (
                bool(raw.get("is_backtest") or raw.get("backtest"))
                or any(k in _path_str for k in ("shadow_validation", "ess_reflection"))
                or "持仓消失" in _reason
                or "ghost" in _reason.lower()
            )
            is_backtest = is_synthetic or "backtest" in _path_str
            # SQLite trades 表的 id 字段作为 trade_id
            trade_id = str(
                raw.get("trade_id")
                or raw.get("id")
                or f"{coin}_{raw.get('entry_time', raw.get('timestamp', ''))}"
            )
            # pnl: 22 fills 表用 realized_pnl；SQLite 可能只有 pnl_pct，没有 pnl 绝对值
            _pnl_raw = raw.get("pnl", raw.get("realized_pnl"))
            pnl = float(_pnl_raw) if _pnl_raw is not None else 0.0
            pnl_pct = float(raw.get("pnl_pct", 0))
            # F8: 只有 pnl 缺失且无 pnl_pct 的记录才算「收益不可用」，不参与胜率统计
            pnl_valid = _pnl_raw is not None or pnl_pct != 0
            if pnl == 0 and pnl_pct != 0:
                # 从 pnl_pct 推算 pnl（近似）
                entry = float(raw.get("entry_price", 0))
                pnl = entry * pnl_pct
            _exit_px = float(raw.get("exit_price", raw.get("px") or 0))
            _qty = float(raw.get("qty") or 0)
            if pnl_pct == 0 and pnl != 0 and _exit_px > 0 and _qty > 0:
                pnl_pct = pnl / (_exit_px * _qty)
            return {
                "trade_id": trade_id,
                "coin": coin,
                "inst_id": _inst or raw.get("inst_id", f"{coin}-USDT-SWAP"),
                "direction": str(raw.get("direction") or raw.get("pos_side") or "").lower(),
                "entry_price": float(raw.get("entry_price", 0)),
                "exit_price": _exit_px,
                "entry_time": str(
                    raw.get("entry_time") or raw.get("timestamp") or raw.get("created_at", "")
                ),
                "exit_time": str(
                    raw.get("exit_time") or raw.get("ts") or raw.get("created_at", "")
                ),
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "pnl_valid": pnl_valid and not is_synthetic,
                "is_backtest": is_backtest,
                "exit_reason": raw.get("exit_reason", ""),
                "confidence": float(raw.get("confidence", 0)),
                "source_system": source,
                "strategy_source": raw.get("strategy_source", source),
            }
        except Exception as e:
            logger.debug("[FO] normalize_trade fail: %s", e)
            return None

    def build_index(self, force: bool = False) -> list[dict[str, Any]]:
        """
        构建/更新系统级交易索引库。

        返回统一格式的交易记录列表（按 trade_id 去重）。
        """
        if not force and self._cache is not None:
            if time.time() - self._cache_ts < self.CACHE_TTL:
                return self._cache

        all_trades: dict[str, dict[str, Any]] = {}  # trade_id → trade
        source_stats: list[str] = []

        for src in self._glob_sources():
            file_path = Path(src.get("_root") or self._project_root) / src["path"]
            if src["type"] == "closed":
                raw_trades = self._load_closed_trades(file_path)
                for rt in raw_trades:
                    normalized = self._normalize_trade(rt, src["source"], src["path"])
                    if normalized:
                        all_trades[normalized["trade_id"]] = normalized
                if raw_trades:
                    source_stats.append(
                        f"{src['source']}({src['path']}): {len(raw_trades)}笔(jsonl)"
                    )
            elif src["type"] == "sqlite":
                table = src.get("table", "trades")
                raw_trades = self._load_sqlite_trades(file_path, table, src.get("where"))
                for rt in raw_trades:
                    normalized = self._normalize_trade(rt, src["source"], src["path"])
                    if normalized:
                        all_trades[normalized["trade_id"]] = normalized
                if raw_trades:
                    source_stats.append(
                        f"{src['source']}({src['path']}): {len(raw_trades)}笔(sqlite)"
                    )

        result = list(all_trades.values())
        # 按退出时间排序
        result.sort(key=lambda x: x.get("exit_time", ""), reverse=True)

        # 持久化索引库（原子写入：临时文件 + os.replace，避免中途截断损坏）
        try:
            self._index_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._index_path.with_suffix(self._index_path.suffix + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                for t in result:
                    f.write(json.dumps(t, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._index_path)
        except Exception as e:
            logger.warning("[FO] save index fail: %s", e)

        if source_stats:
            logger.info("[TradeIndex] 来源: %s | 总计 %d 笔", " | ".join(source_stats), len(result))

        self._cache = result
        self._cache_ts = time.time()
        return result

    def get_trades(self, force: bool = False) -> list[dict[str, Any]]:
        """获取索引库中的所有交易记录"""
        return self.build_index(force=force)

    def discover_sources(self, force: bool = False) -> list[dict[str, Any]]:
        """公开接口：返回所有已发现 + 已知的交易记录源（调试用）"""
        if force:
            self._discovered_sources = None
        return self._glob_sources()
