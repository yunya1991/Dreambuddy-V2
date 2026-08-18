"""A系列选币层 — Hermes驱动大模型调用SKILL产出多空代币池

核心职责：
    1. 调用6-TRADING/skills中的asset-research和dream-attention-radar SKILL
    2. 融合多个SKILL输出，产出多头代币池和空头代币池
    3. 代币池作为整个系统的公共数据，写入共享State

调用方式：
    - 实盘：Hermes驱动大模型调用SKILL
    - 回测/测试：使用mock数据
"""
from __future__ import annotations

from typing import Any, Dict, List
from pathlib import Path
import os


class CoinSelector:
    """多空代币池选择器

    通过融合多个SKILL的分析结果，产出最适合做多和做空的代币池。
    """

    # SKILL路径
    SKILL_BASE = Path(__file__).parent.parent.parent.parent / "6-TRADING" / "skills"
    ASSET_RESEARCH_SKILL = SKILL_BASE / "asset-research"
    ATTENTION_RADAR_SKILL = SKILL_BASE / "dream-attention-radar"

    # 每周选币 cron 产出的持久化币池文件（共享数据契约）
    POOL_FILE = Path(__file__).parent.parent.parent / "cli" / "scheduler_data" / "coin_pool.json"
    POOL_MAX_AGE_DAYS = 8  # 每周产出一次，允许1天宽限

    def __init__(self, use_hermes: bool = True):
        """初始化选币器

        Args:
            use_hermes: 是否使用Hermes大模型调用SKILL（False=使用本地mock）
        """
        self.use_hermes = use_hermes
        self._skill_cache: Dict[str, Any] = {}

    def select(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """产出多空代币池

        Args:
            market_data: 市场数据，包含symbols列表、K线数据等

        Returns:
            {
                "long_pool": [{"symbol": "BTC", "score": 0.85, "reasons": [...]}],
                "short_pool": [{"symbol": "DOGE", "score": 0.72, "reasons": [...]}],
                "timestamp": "2026-08-14T02:00:00Z",
                "source": "hermes" | "mock"
            }
        """
        if self.use_hermes:
            return self._select_via_hermes(market_data)
        else:
            # 优先加载每周选币 cron 产出的持久化币池（真实数据）
            persisted = self._load_persisted_pools()
            if persisted is not None:
                return persisted
            return self._select_mock(market_data)

    def _load_persisted_pools(self) -> Dict[str, Any] | None:
        """加载每周选币 cron 写入的 coin_pool.json（新鲜度校验）

        Returns:
            池 dict（source="persisted"）；文件不存在/过期/损坏时返回 None
        """
        import json
        from datetime import datetime, timezone

        try:
            if not self.POOL_FILE.exists():
                return None
            age_days = (datetime.now(timezone.utc).timestamp() - self.POOL_FILE.stat().st_mtime) / 86400
            if age_days > self.POOL_MAX_AGE_DAYS:
                return None
            data = json.loads(self.POOL_FILE.read_text(encoding="utf-8"))
            if not data.get("long_pool") and not data.get("short_pool"):
                return None
            return {
                "long_pool": data.get("long_pool", []),
                "short_pool": data.get("short_pool", []),
                "timestamp": data.get("timestamp", ""),
                "source": f"persisted:{data.get('source', 'weekly-cron')}",
                # PROP-20260816: regime 透传(对冲激活门禁用)
                "regime": data.get("regime", ""),
            }
        except Exception:
            return None

    def _select_via_hermes(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """通过Hermes大模型调用SKILL进行选币

        Hermes调度流程：
            1. 调用asset-research SKILL → 资产调研结果
            2. 调用dream-attention-radar SKILL → 注意力排名
            3. 融合结果 → 多空代币池
        """
        # TODO: 接入Hermes API进行大模型SKILL调用
        # 当前阶段降级为mock，后续接入Hermes
        return self._select_mock(market_data)

    def _select_mock(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Mock选币逻辑（用于测试和开发阶段）

        Mock模式下仍然走融合流程：
            1. 调用 _call_asset_research（mock返回）
            2. 调用 _call_attention_radar（mock返回）
            3. 调用 _fuse_results 融合产出多空代币池
        """
        symbols = market_data.get("symbols", ["BTC", "ETH", "SOL"])

        # 调用 mock SKILL
        asset_research = self._call_asset_research(region="global")
        attention_radar = self._call_attention_radar(symbols=symbols)

        # 融合产出多空代币池
        fused = self._fuse_results(asset_research, attention_radar)

        from datetime import datetime, timezone
        return {
            "long_pool": fused["long_pool"],
            "short_pool": fused["short_pool"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "mock",
        }

    # ---- Task 2: SKILL 调用与融合 ----

    def _call_asset_research(self, region: str = "global") -> Dict[str, Any]:
        """调用asset-research SKILL进行资产调研

        Args:
            region: 调研区域，如 global / asia / americas

        Returns:
            {
                "engineName": "AssetResearch",
                "region": "global",
                "phase": "discovery",
                "priority_assets": [{"symbol": "BTC", "score": 0.9, "reason": "..."}],
                "source": "hermes" | "mock"
            }
        """
        if self.use_hermes:
            # TODO: 通过Hermes调用asset-research SKILL
            pass

        # Mock 返回
        return {
            "engineName": "AssetResearch",
            "region": region,
            "phase": "discovery",
            "priority_assets": [
                {"symbol": "BTC", "score": 0.9, "reason": "strong trend"},
                {"symbol": "ETH", "score": 0.8, "reason": "volume surge"},
                {"symbol": "SOL", "score": 0.75, "reason": "ecosystem growth"},
            ],
            "source": "mock",
        }

    def _call_attention_radar(self, symbols: List[str]) -> Dict[str, Any]:
        """调用dream-attention-radar SKILL获取注意力排名

        Args:
            symbols: 待排名的代币符号列表

        Returns:
            {
                "long_top": [{"symbol": "BTC", "score": 0.85, "reason": "..."}],
                "short_top": [{"symbol": "DOGE", "score": 0.65, "reason": "..."}],
                "source": "hermes" | "mock"
            }
        """
        if self.use_hermes:
            # TODO: 通过Hermes调用dream-attention-radar SKILL
            pass

        # Mock 返回
        long_top = []
        short_top = []
        for i, sym in enumerate(symbols):
            if i % 2 == 0:
                long_top.append({
                    "symbol": sym,
                    "score": 0.85 - i * 0.05,
                    "reason": "attention high",
                })
            else:
                short_top.append({
                    "symbol": sym,
                    "score": 0.65 - i * 0.05,
                    "reason": "attention low",
                })

        return {
            "long_top": long_top,
            "short_top": short_top,
            "source": "mock",
        }

    def _fuse_results(
        self,
        asset_research: Dict[str, Any],
        attention_radar: Dict[str, Any],
    ) -> Dict[str, Any]:
        """融合asset-research和attention-radar结果，产出多空代币池

        融合策略：
            1. 从asset_research的priority_assets中提取候选
            2. 与attention_radar的long_top/short_top做交集匹配
            3. 同时出现在两个来源的代币获得加权得分
            4. 仅出现在一个来源的代币降权保留

        Args:
            asset_research: _call_asset_research 的返回结果
            attention_radar: _call_attention_radar 的返回结果

        Returns:
            {
                "long_pool": [{"symbol": "...", "score": 0.0, "reasons": [...]}],
                "short_pool": [{"symbol": "...", "score": 0.0, "reasons": [...]}],
            }
        """
        # 构建 attention_radar 查找索引
        long_map: Dict[str, Dict[str, Any]] = {
            item["symbol"]: item for item in attention_radar.get("long_top", [])
        }
        short_map: Dict[str, Dict[str, Any]] = {
            item["symbol"]: item for item in attention_radar.get("short_top", [])
        }

        # 构建 asset_research 查找索引
        asset_map: Dict[str, Dict[str, Any]] = {
            item["symbol"]: item
            for item in asset_research.get("priority_assets", [])
        }

        long_pool: List[Dict[str, Any]] = []
        short_pool: List[Dict[str, Any]] = []

        # 处理 long_top：与 asset_research 交集优先，应用 crypto_priority
        for item in attention_radar.get("long_top", []):
            sym = item["symbol"]
            reasons = [item.get("reason", "attention signal")]
            if sym in asset_map:
                base_score = (item.get("score", 0.5) + asset_map[sym].get("score", 0.5)) / 2
                reasons.append(asset_map[sym].get("reason", "asset research"))
            else:
                base_score = item.get("score", 0.5) * 0.8  # 降权
            # crypto_priority: priority=1.0 保持原分，priority=0.5 降权
            crypto_priority = asset_map.get(sym, {}).get("priority", 1.0)
            score = base_score * crypto_priority
            long_pool.append({
                "symbol": sym,
                "score": round(score, 4),
                "reasons": reasons,
            })

        # 处理 short_top
        for item in attention_radar.get("short_top", []):
            sym = item["symbol"]
            reasons = [item.get("reason", "attention signal")]
            if sym in asset_map:
                base_score = (item.get("score", 0.5) + asset_map[sym].get("score", 0.5)) / 2
                reasons.append(asset_map[sym].get("reason", "asset research"))
            else:
                base_score = item.get("score", 0.5) * 0.8
            crypto_priority = asset_map.get(sym, {}).get("priority", 1.0)
            score = base_score * crypto_priority
            short_pool.append({
                "symbol": sym,
                "score": round(score, 4),
                "reasons": reasons,
            })

        # 补充仅出现在 asset_research 但不在 attention_radar 中的代币
        for item in asset_research.get("priority_assets", []):
            sym = item["symbol"]
            if sym not in long_map and sym not in short_map:
                crypto_priority = item.get("priority", 1.0)
                long_pool.append({
                    "symbol": sym,
                    "score": round(item.get("score", 0.5) * 0.7 * crypto_priority, 4),
                    "reasons": [item.get("reason", "asset research only")],
                })

        return {
            "long_pool": long_pool,
            "short_pool": short_pool,
        }

    # ---- Task 5: persist_pools ----

    def persist_pools(self, pools: Dict[str, Any], filepath: str) -> None:
        """Persist token pools to a JSON file with timestamp.

        Args:
            pools: The pools dict from select() containing long_pool, short_pool, etc.
            filepath: Path to the output JSON file.
        """
        import json
        from datetime import datetime

        data = {
            "long_pool": pools.get("long_pool", []),
            "short_pool": pools.get("short_pool", []),
            "timestamp": pools.get("timestamp", ""),
            "source": pools.get("source", ""),
            "persisted_at": datetime.utcnow().isoformat() + "Z",
        }

        Path(filepath).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# ---- PROP-20260816 模块1: 币池动态排名层 (pool_dynamic_scores) ----
# 周报 coin_pool.json 是 SSoT 只读; 动态分独立存储于运行时层,
# 编排选币按合并分排序: merged = 0.7×weekly_score + 0.3×dyn_score

DYNAMIC_SCORES_FILE = (
    Path(__file__).parent.parent.parent
    / "cli" / "scheduler_data" / "pool_dynamic_scores.json"
)
DYN_COLD_START = 0.5   # 冷启动中性分(退化回周报排名)
WEEKLY_WEIGHT = 0.7
DYN_WEIGHT = 0.3


def load_dynamic_scores() -> Dict[str, Any]:
    """加载动态排名层 {symbol: {dyn_score,last_dir,last_conf,cycles_seen,updated_at}}。

    文件不存在/损坏时返回空 dict（调用方按冷启动处理）。
    """
    import json

    try:
        if not DYNAMIC_SCORES_FILE.exists():
            return {}
        data = json.loads(DYNAMIC_SCORES_FILE.read_text(encoding="utf-8"))
        scores = data.get("scores") or {}
        return scores if isinstance(scores, dict) else {}
    except Exception:
        return {}


def save_dynamic_scores(scores: Dict[str, Any]) -> None:
    """原子写入动态排名层 (tmp+rename, 防半截文件)。"""
    import json
    from datetime import datetime, timezone

    try:
        DYNAMIC_SCORES_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "scores": scores,
        }
        tmp = str(DYNAMIC_SCORES_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DYNAMIC_SCORES_FILE)
    except Exception:
        pass  # 运行时层写入失败不阻断编排


def record_dynamic_score(symbol: str, confidence: float, direction: str = "") -> None:
    """upsert 回写已评估币的 B层 conf（orchestration_cycle 每周期调用）。"""
    from datetime import datetime, timezone

    if not symbol:
        return
    scores = load_dynamic_scores()
    entry = scores.get(symbol) or {"dyn_score": DYN_COLD_START, "cycles_seen": 0}
    conf = float(confidence or 0.0)
    entry["dyn_score"] = round(conf, 4)
    entry["last_conf"] = round(conf, 4)
    if direction:
        entry["last_dir"] = direction
    entry["cycles_seen"] = int(entry.get("cycles_seen", 0)) + 1
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    scores[symbol] = entry
    save_dynamic_scores(scores)


def merge_dynamic_scores(
    pool: List[Dict[str, Any]],
    dynamic: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    """按合并分排序币池: merged = 0.7×weekly + 0.3×dyn（冷启动 0.5）。

    返回新列表（降序），每项追加 dyn_score/merged_score 键；
    不修改入参与 coin_pool.json（周报 SSoT 只读）。
    """
    if dynamic is None:
        dynamic = load_dynamic_scores()
    merged_list: List[Dict[str, Any]] = []
    for item in pool or []:
        sym = (item or {}).get("symbol", "")
        weekly = float((item or {}).get("score", 0.0) or 0.0)
        dyn = float((dynamic.get(sym) or {}).get("dyn_score", DYN_COLD_START))
        merged = WEEKLY_WEIGHT * weekly + DYN_WEIGHT * dyn
        new_item = dict(item)
        new_item["dyn_score"] = round(dyn, 4)
        new_item["merged_score"] = round(merged, 4)
        merged_list.append(new_item)
    merged_list.sort(key=lambda x: x["merged_score"], reverse=True)
    return merged_list


# ---- Task 4: CoinSelectorNode ----

from dreamos.registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


class CoinSelectorNode(BaseNode):
    """CoinSelector node wrapper for DreamOS orchestration.

    Wraps CoinSelector into a BaseNode-compatible node,
    enabling it to participate in the DreamOS execution graph.
    """

    node_id: str = "COIN_SELECTOR"
    name: str = "Coin Selector"
    description: str = "Select long/short token pools via SKILL fusion"
    chain: str = "A"
    tags: list = ["trading", "selection"]

    def __init__(self, use_hermes: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._selector = CoinSelector(use_hermes=use_hermes)

    def execute_core(self, state: State) -> NodeResult:
        """Execute coin selection and return NodeResult with pools.

        Reads market data from state.market, calls CoinSelector.select(),
        and wraps the result into a NodeResult.
        """
        market_data = state.market or {"symbols": ["BTC", "ETH", "SOL"]}

        pools = self._selector.select(market_data=market_data)

        long_count = len(pools.get("long_pool", []))
        short_count = len(pools.get("short_pool", []))
        total = long_count + short_count

        confidence = min(1.0, total / 10.0) if total > 0 else 0.0

        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            confidence=confidence,
            outputs={
                "long_pool": pools.get("long_pool", []),
                "short_pool": pools.get("short_pool", []),
                "timestamp": pools.get("timestamp", ""),
                "source": pools.get("source", "mock"),
            },
        )
