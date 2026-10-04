"""
Mood Board 情绪板生成器 (F7.3)

从 BDSM 快照 + BCRM 绩效 + 持仓数据生成可视化情绪板：
- 多空信号分布 (bar)
- 市场情绪指数 (gauge)
- 币种相关性矩阵 (heatmap)
- 风险热力图 (heatmap)
- 资金流向 Sankey (sankey)

持久化到 scheduler_data/mood_boards/{date}.json
前端通过 /api/mood-board 读取，复用 SynthesisChart 渲染。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

# F7.5: 产物中台归一存储 (FAIL-OPEN)
try:
    from dreamos.core.artifact import ArtifactStore, ArtifactType
    _ARTIFACT_STORE = ArtifactStore()
except Exception:
    _ARTIFACT_STORE = None

logger = logging.getLogger("dreamos.mood_board")

DATA_DIR = Path(__file__).resolve().parent / "scheduler_data"
MOOD_BOARDS_DIR = DATA_DIR / "mood_boards"


class MoodBoardGenerator:
    """情绪板生成器 — 复用 DreamOS 已有数据源"""

    def __init__(self) -> None:
        MOOD_BOARDS_DIR.mkdir(parents=True, exist_ok=True)

    def generate(self) -> Dict[str, Any]:
        """生成情绪板 artifact"""
        now = datetime.now(timezone.utc)
        bdsm = self._load_latest_bdsm()
        bcrm = self._load_latest_bcrm()
        positions = self._extract_positions(bdsm)

        charts: List[Dict[str, Any]] = []

        # 1. 市场情绪指数 (gauge) — 基于 BDSM 币种方向约束加权
        sentiment = self._compute_sentiment_gauge(bdsm)
        charts.append({"type": "gauge", "title": "市场情绪指数", "data": sentiment})

        # 2. 多空信号分布 (bar)
        bull_bear = self._compute_bull_bear_distribution(bdsm)
        charts.append({"type": "bar", "title": "多空信号分布", "data": bull_bear})

        # 3. 币种风险热力图 (heatmap) — row=symbol, col=risk维度, value=分数
        risk_heatmap = self._compute_risk_heatmap(bdsm)
        charts.append({"type": "heatmap", "title": "风险热力图", "data": risk_heatmap})

        # 4. 资金流向 Sankey (sankey) — 从持仓/预算流向币种
        sankey = self._compute_capital_flow_sankey(bdsm, positions)
        charts.append({"type": "sankey", "title": "资金流向", "data": sankey})

        mood_board = {
            "id": f"mood_board_{now.strftime('%Y%m%d_%H%M%S')}",
            "generated_at": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "source": {
                "bdsm_snapshot_date": bdsm.get("snapshot_date") if bdsm else None,
                "bcrm_date": bcrm.get("date") if bcrm else None,
            },
            "charts": charts,
        }

        self._persist(mood_board)
        return mood_board

    # ── 数据源加载 ────────────────────────────

    def _load_latest_bdsm(self) -> Dict[str, Any]:
        try:
            bdsm_dir = (
                Path(__file__).resolve().parent.parent.parent.parent
                / "11-易经推理系统" / ".workbuddy" / "bdsm"
            )
            snapshots = sorted(bdsm_dir.glob("bdsm_snapshot_*.json"), reverse=True)
            if not snapshots:
                return {}
            with open(snapshots[0], encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载 BDSM 快照失败: {e}")
            return {}

    def _load_latest_bcrm(self) -> Dict[str, Any]:
        try:
            stats_file = (
                Path(__file__).resolve().parent.parent.parent.parent
                / "11-易经推理系统" / ".workbuddy" / "memory_l4" / "stats" / "daily_stats.json"
            )
            if not stats_file.exists():
                return {}
            with open(stats_file, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data:
                return {}
            latest = max(data.keys())
            return data[latest] | {"date": latest}
        except Exception as e:
            logger.warning(f"加载 BCRM 绩效失败: {e}")
            return {}

    def _extract_positions(self, bdsm: Dict[str, Any]) -> List[Dict[str, Any]]:
        coins = bdsm.get("coins", {})
        positions = []
        for symbol, info in coins.items():
            if not isinstance(info, dict):
                continue
            sp = info.get("scaling_plan") or {}
            accumulated = sp.get("accumulated_notional", 0) or 0
            if accumulated > 0:
                positions.append({"symbol": symbol, "notional": accumulated})
        return positions

    # ── 图表计算 ──────────────────────────────

    def _compute_sentiment_gauge(self, bdsm: Dict[str, Any]) -> float:
        """市场情绪指数 0-100：BULL方向约束越多越高"""
        coins = bdsm.get("coins", {})
        if not coins:
            return 50.0
        bull = bear = neutral = 0
        for info in coins.values():
            if not isinstance(info, dict):
                continue
            direction = info.get("direction_constraint", "NEUTRAL")
            if direction == "LONG":
                bull += 1
            elif direction == "SHORT":
                bear += 1
            else:
                neutral += 1
        total = bull + bear + neutral
        if total == 0:
            return 50.0
        # 50 为中性，BULL 推高，BEAR 推低
        score = 50.0 + (bull - bear) / total * 50.0
        return round(max(0.0, min(100.0, score)), 1)

    def _compute_bull_bear_distribution(self, bdsm: Dict[str, Any]) -> Dict[str, int]:
        coins = bdsm.get("coins", {})
        result = {"BULL": 0, "BEAR": 0, "NEUTRAL": 0}
        for info in coins.values():
            if not isinstance(info, dict):
                continue
            direction = info.get("direction_constraint", "NEUTRAL")
            if direction == "LONG":
                result["BULL"] += 1
            elif direction == "SHORT":
                result["BEAR"] += 1
            else:
                result["NEUTRAL"] += 1
        return result

    def _compute_risk_heatmap(self, bdsm: Dict[str, Any]) -> List[List[Any]]:
        """风险热力图：row=symbol, col=风险维度, value=标准化分数(-100~100)"""
        coins = bdsm.get("coins", {})
        if not coins:
            return []
        cells: List[List[Any]] = []
        for symbol, info in coins.items():
            if not isinstance(info, dict):
                continue
            ta = info.get("technical_assessment") or {}
            # RSI 超买(>70)→负风险，超卖(<30)→正机会
            rsi = ta.get("rsi_14", 50) or 50
            rsi_score = round((50 - rsi), 1)  # >50超买→负, <50超卖→正
            # MA200 偏离：正偏离→过热(负)，负偏离→低估(正)
            ma_dev = ta.get("ma200_deviation", 0) or 0
            ma_score = round(-ma_dev, 1)
            # ATR 波动：越大风险越高(负)
            atr = ta.get("atr_pct", 0) or 0
            atr_score = round(-atr * 5, 1)
            # CVS 估值：越高越贵(负)
            cvs = info.get("cvs", 0) or 0
            cvs_score = round(-cvs * 100, 1)

            cells.append([symbol, "RSI", rsi_score])
            cells.append([symbol, "MA200偏离", ma_score])
            cells.append([symbol, "ATR波动", atr_score])
            cells.append([symbol, "CVS估值", cvs_score])
        return cells

    def _compute_capital_flow_sankey(
        self, bdsm: Dict[str, Any], positions: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """资金流向 Sankey：总预算 → 币种(目标/已用) → 方向"""
        coins = bdsm.get("coins", {})
        nodes = [{"name": "总预算"}]
        links: List[Dict[str, Any]] = []

        # 总预算 → 各币种目标名义价值
        total_target = 0.0
        symbol_targets: Dict[str, float] = {}
        for symbol, info in coins.items():
            if not isinstance(info, dict):
                continue
            sp = info.get("scaling_plan") or {}
            target = sp.get("target_notional_usdt", 0) or 0
            if target > 0:
                symbol_targets[symbol] = target
                total_target += target
                nodes.append({"name": symbol})

        for symbol, target in symbol_targets.items():
            links.append({"source": "总预算", "target": symbol, "value": round(target, 1)})

        # 币种 → 方向约束
        direction_nodes = set()
        for symbol, info in coins.items():
            if not isinstance(info, dict) or symbol not in symbol_targets:
                continue
            direction = info.get("direction_constraint", "NEUTRAL")
            direction_nodes.add(direction)
            accumulated = (info.get("scaling_plan") or {}).get("accumulated_notional", 0) or 0
            links.append({"source": symbol, "target": direction, "value": round(accumulated, 1)})

        for d in direction_nodes:
            nodes.append({"name": d})

        return {"nodes": nodes, "links": links}

    # ── 持久化 ────────────────────────────────

    def _persist(self, mood_board: Dict[str, Any]) -> None:
        date = mood_board["date"]
        path = MOOD_BOARDS_DIR / f"{date}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(mood_board, f, ensure_ascii=False, indent=2)
        logger.info(f"Mood Board 已持久化: {path}")

        # F7.5: 写入产物中台 (FAIL-OPEN)
        if _ARTIFACT_STORE is not None:
            try:
                aid = _ARTIFACT_STORE.save(
                    artifact_type=ArtifactType.MOOD_BOARD,
                    title=f"Mood Board {date}",
                    data=mood_board,
                    tags=["mood_board", date],
                    source="mood_board.py",
                    summary=f"{len(mood_board.get('charts', []))} 个图表",
                    artifact_id=mood_board.get("id"),
                )
                logger.info(f"Mood Board 已写入产物中台: {aid}")
            except Exception as e:
                logger.warning(f"Mood Board 写入产物中台失败 (不影响主流程): {e}")


def main() -> None:
    gen = MoodBoardGenerator()
    mb = gen.generate()
    print(f"已生成 Mood Board: {mb['id']}")
    print(f"图表数量: {len(mb['charts'])}")
    for c in mb["charts"]:
        print(f"  - {c['type']}: {c['title']}")


if __name__ == "__main__":
    main()
