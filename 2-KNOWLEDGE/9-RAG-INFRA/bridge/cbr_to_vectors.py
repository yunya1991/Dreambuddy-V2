# -*- coding: utf-8 -*-
"""断层2：CBR 案例库向量化进 ChromaDB，统一 RAG 检索入口。

将 cbr_cases_v03.jsonl 中的已平仓案例转为文本 + 结构化 metadata，
直接 upsert 到 ChromaDB（source_type="cbr_case"），使 hybrid_search
能同时检索策略文档和历史交易案例。

设计原则：
- 直接 upsert ChromaDB，不落地中间 md 文件（保留 case_id/pnl/tag 等业务字段）
- 增量更新：先删除该 case_id 旧记录，再写入新记录
- FAIL-OPEN：单条失败不阻塞整体
- 与 build_index 共用同一 collection / embedder / db_path

运行: python cbr_to_vectors.py
"""

import json
import sys
from pathlib import Path
from typing import Dict, List

# === 路径 ===
_THIS_DIR = Path(__file__).resolve().parent  # 9-RAG-INFRA/bridge
_RAG_INFRA_DIR = _THIS_DIR.parent              # 9-RAG-INFRA
if str(_RAG_INFRA_DIR) not in sys.path:
    sys.path.insert(0, str(_RAG_INFRA_DIR))

from vector_store.config import CHROMA_DB_PATH, COLLECTION_NAME, DISTANCE_METRIC
from vector_store.embedder import Embedder

# CBR 案例库路径
_CBR_JSONL = Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/runtime/cbr_cases_v03.jsonl")

_embedder = Embedder()


# ============================================================
# Phase 3：CBR 案例标签升级（setup_type / regime / failure_reason）
# 基于案例已有技术指标字段推断，不修改原始 jsonl，仅在向量化时附加。
# ============================================================

def _infer_setup_type(case: Dict) -> str:
    """推断开仓形态类型。

    优先级：breakout > trend_follow > mean_reversion > momentum > consolidation > unknown
    """
    entry = case.get("entry_snapshot", {}) or {}
    direction = case.get("direction", "").upper()
    has_tech = entry.get("rsi_14") is not None

    if not has_tech:
        return "unknown"

    vol_q = entry.get("vol_20d_quantile")
    ma_order = entry.get("triple_ma_order", "")
    dist200 = entry.get("dist_sma200_pct")
    rsi = entry.get("rsi_14")
    roc5 = entry.get("roc_5d")
    bbw = entry.get("bollinger_width_pct")

    # 1. breakout：放量入场（量能分位>0.8）
    if vol_q is not None and vol_q > 0.8:
        return "breakout"

    # 2. trend_follow：均线排列与方向一致
    if ma_order:
        bull = ma_order.startswith("BULL")
        bear = ma_order.startswith("BEAR")
        if (direction == "LONG" and bull) or (direction == "SHORT" and bear):
            return "trend_follow"

    # 3. mean_reversion：方向与均线趋势相反（逆势交易）
    if ma_order:
        bull = ma_order.startswith("BULL")
        bear = ma_order.startswith("BEAR")
        if (direction == "LONG" and bear) or (direction == "SHORT" and bull):
            return "mean_reversion"

    # 4. momentum：ROC 与方向一致
    if roc5 is not None:
        if (direction == "LONG" and roc5 > 0) or (direction == "SHORT" and roc5 < 0):
            return "momentum"

    # 5. consolidation：布林带极窄
    if bbw is not None and bbw < 0.07:
        return "consolidation"

    return "unknown"


def _infer_regime(case: Dict) -> str:
    """推断市场状态：trend / range / volatile / trending_volatile / unknown"""
    entry = case.get("entry_snapshot", {}) or {}
    has_tech = entry.get("rsi_14") is not None

    if not has_tech:
        return "unknown"

    atr = entry.get("atr14_norm_pct")
    bbw = entry.get("bollinger_width_pct")
    ma_order = entry.get("triple_ma_order", "")

    is_volatile = atr is not None and atr > 0.055
    is_trending = ma_order in ("BULL_ALIGNMENT", "BEAR_ALIGNMENT")
    is_ranging = bbw is not None and bbw < 0.07

    if is_trending and is_volatile:
        return "trending_volatile"
    if is_volatile:
        return "volatile"
    if is_ranging and not is_trending:
        return "range"
    if is_trending:
        return "trend"
    return "unknown"


def _infer_failure_reason(case: Dict) -> str:
    """推断失败原因（盈利案例返回 none）。"""
    if case.get("is_profit"):
        return "none"

    exit_ = case.get("exit_snapshot", {}) or {}
    entry = case.get("entry_snapshot", {}) or {}
    exit_reason = exit_.get("exit_reason", "")
    sl_hit = exit_.get("sl_hit")
    atr = entry.get("atr14_norm_pct")
    hold_bars = exit_.get("hold_bars")
    ma_order = entry.get("triple_ma_order", "")
    direction = case.get("direction", "").upper()

    # 止损扫损
    if sl_hit is True or exit_reason == "sl":
        if atr is not None and atr > 0.055:
            return "volatility_sweep"
        return "sl_hit"

    # 趋势反转（逆势交易）
    if ma_order:
        bull = ma_order.startswith("BULL")
        bear = ma_order.startswith("BEAR")
        if (direction == "LONG" and bear) or (direction == "SHORT" and bull):
            return "trend_reversal"

    # 超时离场
    if hold_bars is not None and hold_bars > 24:
        return "timeout"

    # 未到止盈主动离场
    if exit_reason in ("polling_trader", "synth_filled"):
        return "tp_missed"

    return "unknown"


def _case_to_text(case: Dict) -> str:
    """将 CBR 案例转为可检索文本。"""
    symbol = case.get("symbol", "?")
    direction = case.get("direction", "?")
    pnl_pct = case.get("pnl_pct", 0.0)
    is_profit = case.get("is_profit", False)
    tag = case.get("tag", "NORMAL")
    entry = case.get("entry_snapshot", {}) or {}
    exit_ = case.get("exit_snapshot", {}) or {}

    # Phase 3：推断标签
    setup_type = _infer_setup_type(case)
    regime = _infer_regime(case)
    failure_reason = _infer_failure_reason(case)

    lines = [
        f"# CBR案例 {symbol} {direction}",
        f"- 盈亏: {pnl_pct*100:.2f}% ({'盈利' if is_profit else '亏损'})",
        f"- 标签: {tag}",
        f"- 资产类别: {case.get('asset_class', '?')}",
        f"- 开仓形态: {setup_type}",
        f"- 市场状态: {regime}",
    ]
    if not is_profit:
        lines.append(f"- 失败原因: {failure_reason}")
    if exit_.get("exit_reason"):
        lines.append(f"- 离场原因: {exit_['exit_reason']}")
    if exit_.get("hold_bars") is not None:
        lines.append(f"- 持仓时长: {exit_['hold_bars']} bars")
    if entry:
        lines.append("")
        lines.append("## 入场特征")
        for k in ("bcrm_confidence", "hexagram_name", "rsi_14", "macd_hist",
                   "dist_sma20_pct", "dist_sma50_pct", "dist_sma200_pct",
                   "triple_ma_order", "atr14_norm_pct", "bollinger_width_pct",
                   "vol_20d_quantile", "p1_output_label"):
            if k in entry and entry[k] is not None:
                lines.append(f"- {k}: {entry[k]}")
    if exit_:
        lines.append("")
        lines.append("## 离场特征")
        for k in ("exit_reason", "hold_bars", "sl_hit", "tp_hit", "upper_gua", "lower_gua"):
            if k in exit_ and exit_[k] is not None:
                lines.append(f"- {k}: {exit_[k]}")
    return "\n".join(lines)


def _case_to_meta(case: Dict) -> Dict:
    """结构化 metadata（扁平化，ChromaDB 要求 scalar）。"""
    entry = case.get("entry_snapshot", {}) or {}
    exit_ = case.get("exit_snapshot", {}) or {}

    # Phase 3：推断标签
    setup_type = _infer_setup_type(case)
    regime = _infer_regime(case)
    failure_reason = _infer_failure_reason(case)

    meta = {
        "source_type": "cbr_case",
        "source_file": f"cbr_cases_v03.jsonl::{case.get('case_id', '')}",
        "domain": "cbr",
        "heading": f"CBR案例 {case.get('symbol', '?')} {case.get('direction', '?')}",
        "heading_level": 1,
        "position": 0,
        "tags": f"cbr,{case.get('tag', 'NORMAL')},{setup_type},{regime}",
        "file_hash": case.get("case_id", ""),
        "case_id": case.get("case_id", ""),
        "symbol": case.get("symbol", ""),
        "asset_class": case.get("asset_class", ""),
        "direction": case.get("direction", ""),
        "is_profit": str(bool(case.get("is_profit", False))),
        "pnl_pct": float(case.get("pnl_pct", 0.0)),
        "tag": case.get("tag", "NORMAL"),
        # Phase 3 新增标签
        "setup_type": setup_type,
        "regime": regime,
        "failure_reason": failure_reason,
    }
    return meta


def sync_cbr_to_chroma() -> Dict:
    """将 CBR 案例库同步到 ChromaDB。

    Returns:
        统计字典：total / indexed / failed
    """
    import chromadb

    if not _CBR_JSONL.exists():
        return {"total": 0, "indexed": 0, "failed": 0, "error": f"案例库不存在: {_CBR_JSONL}"}

    cases: List[Dict] = []
    with open(_CBR_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
                # 只索引已平仓的案例（有 pnl_pct）
                if case.get("pnl_pct") is not None:
                    cases.append(case)
            except json.JSONDecodeError:
                continue

    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": DISTANCE_METRIC},
    )

    stats = {"total": len(cases), "indexed": 0, "failed": 0}

    for case in cases:
        try:
            case_id = case.get("case_id", "")
            if not case_id:
                stats["failed"] += 1
                continue

            text = _case_to_text(case)
            meta = _case_to_meta(case)
            emb = _embedder.embed_batch([text])[0]

            # 先删旧再写新（增量）
            try:
                collection.delete(where={"case_id": case_id})
            except Exception:
                pass

            collection.upsert(
                ids=[f"cbr::{case_id}"],
                documents=[text],
                embeddings=[emb.tolist()],
                metadatas=[meta],
            )
            stats["indexed"] += 1
        except Exception:
            stats["failed"] += 1

    return stats


if __name__ == "__main__":
    result = sync_cbr_to_chroma()
    print(json.dumps(result, ensure_ascii=False, indent=2))
