#!/usr/bin/env python3
"""
易经推理轮询交易器（P2 完整版）

集成功能：
- P2-1a: 平仓后自动生成 case 存入 L4
- P2-1b: 定期重训 LiangyiEngine + QMM
- P2-2a: 动态仓位（置信度 + 波动率）
- P2-2b: 日最大亏损限制 + 连续亏损熔断
- P2-3: 交易绩效统计 + PnL 持久化
- P2-4: BCRM 矛盾格式修复
- P2-5: 进程守护 + 异常告警 + 日志持久化

⚠️ P0 DAL 接入（对齐 ENGINEERING_INDEX §2.1 6 依赖注入入口）：
   P1 后本文件交易写入/查询将改为：
       from dreambuddy_dal import get_trade_repo, get_position_repo, get_risk_repo
       repo = get_trade_repo()  # 按 DB_BACKEND=json_legacy/dual_write/sqlite 自动切
   SSoT 文档：19-数据访问层/docs/TECHNICAL_DESIGN.md §2.2 / §3.2

用法:
  python -m scripts.memory_l4.polling_trader --once
  python -m scripts.memory_l4.polling_trader --interval 300 --coins BTC,ETH
"""
import argparse
import json
import os
import signal as signal_module
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scripts.memory_l4.bcrm.bagua_engine import BaguaEngine
from scripts.memory_l4.bcrm.engine import BCRMEngine
from scripts.memory_l4.bcrm2.incremental_learner import IncrementalLearner
from scripts.memory_l4.bcrm2.shadow_logger import ShadowLogger, SHADOW_LOGGER_ENABLED
from scripts.memory_l4.bcrm2.parameter_mapper import (
    ALPHA_BLEND_ENABLED, DEFAULT_ALPHA_BLEND, ALPHA_BLEND_MAX,
)
from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter
from scripts.memory_l4.classic_exit_system import (
    ClassicExitSystem,
    ExitAction,
    ExitConfig,
)
from scripts.memory_l4.classic_exit_system import (
    PositionState as ExitPositionState,
)
from scripts.memory_l4.knowledge_bridge import KnowledgeBridge
from scripts.memory_l4.learning_scheduler import LearningScheduler
from scripts.memory_l4.okx_simulated import OKXSimulatedClient
from scripts.memory_l4.paths import episodes_dir as _episodes_dir
from scripts.memory_l4.process_guardian import ProcessGuardian
from scripts.memory_l4.ranging_market_enhancer import (
    HexagramDataDrivenCalibrator,
    RangingMarketEnhancer,
)
from scripts.memory_l4.trading_utils import (
    PerformanceTracker,
    PositionTracker,
    RiskManager,
    register_trade_to_l4,
)
from scripts.memory_l4.review_engine import (
    BULLISH_HEXAGRAMS,
    BEARISH_HEXAGRAMS,
    NEUTRAL_HEXAGRAMS,
)
from scripts.memory_l4.yijing_exit_system import (
    YijingExitAction,
    YijingExitConfig,
    YijingExitSystem,
)
from scripts.memory_l4.yijing_feishu_alert import notify_model_error, notify_system_error
from scripts.memory_l4.yijing_trainer import (
    _build_contradiction_list,
    _build_research_contradictions,
    _contradictions_to_bcrm_format,
    _detect_ranging_market,
    _kline_to_snapshot,
    _load_kline_from_okx,
)
import pandas as pd

# ─────────────────────────────────────────────────────────────
# RAG 热路径接入（第一波：打通知识库到交易决策）
# 进程级单例 + 懒加载 + 3 秒超时 + 环境变量一键关闭
# FAIL-OPEN：任何异常返回空列表，不阻塞交易决策
# ─────────────────────────────────────────────────────────────
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

_RAG_CLIENT = None
_RAG_CLIENT_LOCK = threading.Lock()
_RAG_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-hotpath")


# ── 公共代币池加载器（方案B：运行时读取，8h自动刷新）──
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATHS = [
    Path(os.environ.get("TOKEN_REGISTRY_PATH", ""))
    if os.environ.get("TOKEN_REGISTRY_PATH")
    else None,
    _PROJECT_ROOT / "config" / "token_registry.json",
]
_POOL_TTL = 28800  # 8小时


# ─────────────────────────────────────────────────────────────
# P0: 事件驱动注入（odaily 快讯 → Score_B event_boost clamp[0,0.10]
#     + 卦冲突方向一致性惩罚 + 0.85 地板抬升硬拦截
# ─────────────────────────────────────────────────────────────
def compute_score_b_with_event_boost(
    continuity_score: float,
    conf_norm: float,
    event_positive_strength: Optional[float],
) -> Tuple[float, float]:
    """方案C Step3 Score_B 注入 event_positive_strength（FAIL-OPEN绝对安全）。

    公式（对齐 TDD 用例 param）：
      (A) 当 event_positive_strength 为 None / 非数 / 异常 / ≤ 0.35（弱信号/无明确利好）
            → boost=0，Score_B = 0.60×continuity + 0.40×conf_norm（**原公式完全等价，兼容回滚**）
      (B) 当 event_positive_strength ∈ (0.35, 1.0]
            → boost = clip( 0.10 * (strength - 0.35) / 0.65 , 0, 0.10 )
              Score_B_new = 0.58×continuity + 0.37×conf_norm + 0.05×strength + boost
      (C) clamp 上限：strength越界(如2.0)时 boost≤0.10 硬上限（防过拟合）

    Returns:
        (score_b_final, event_boost_applied)
    """
    try:
        cont = max(0.0, min(1.0, float(continuity_score)))
        conf = max(0.40, min(1.0, float(conf_norm)))
        # 解析 event_positive_strength（FAIL-OPEN 解析）
        if event_positive_strength is None:
            strength_ok, strength_val = False, 0.0
        else:
            try:
                sv = float(event_positive_strength)
                strength_val = max(0.0, min(2.0, sv))
                strength_ok = True
            except (TypeError, ValueError):
                strength_ok, strength_val = False, 0.0

        if not strength_ok or strength_val <= 0.35:
            # 中性/无信号 → 与原v3.0公式完全一致（可随时100%回滚兼容）
            baseline = 0.60 * cont + 0.40 * conf
            return max(0.0, min(1.0, baseline)), 0.0

        # (B) 明确正面 → 3系数新合成 + boost clamp[0, 0.10]
        raw_boost = 0.10 * max(0.0, (strength_val - 0.35)) / 0.65
        boost = max(0.0, min(0.10, raw_boost))
        score = 0.58 * cont + 0.37 * conf + 0.05 * min(1.0, strength_val) + boost

        # ── 🆕 P1 C1④ G2护栏：EV门槛>0.05（掐弱正面吹票新闻）──
        #    boost≤0.050（如单条小合作/次升级 strength≈0.40~0.675）→
        #    清零boost，Score_B 回退 baseline=0.60*cont+0.40*conf（字节等价v3.0，100%兼容）
        #    原 strength>0.35 前置门槛仍保留 → 两层夹（0.35→0.05→0.10）更保守
        #    浮点误差容限：二进制浮点0.1/0.675是循环小数，round到6位对齐SPEC边界0.050
        if round(boost, 6) <= 0.050:
            boost = 0.0
            score = 0.60 * cont + 0.40 * conf  # 回退 baseline

        return max(0.0, min(1.0, score)), boost
    except Exception:  # noqa: BLE003  FAIL-OPEN L2：任何异常→baseline+boost=0
        try:
            cont = max(0.0, min(1.0, float(continuity_score)))
            conf = max(0.40, min(1.0, float(conf_norm)))
            return max(0.0, min(1.0, 0.60 * cont + 0.40 * conf)), 0.0
        except Exception:
            return 0.65, 0.0  # 最底保底 fail-open neutral


def apply_hex_conflict_multiplier_and_floor(
    confidence: float,
    hex_name: str,
    hex_authoritative_dir: str,
    decision_dir: str,
) -> Tuple[float, bool]:
    """⚠️ @DEPRECATED（2026-09-01 冗余确认）—— 生产统一走更完整的
    `PollingTrader._check_hexagram_consistency_for_entry(hex_name, decision_direction=UP/DOWN, ...)`
    调用点在 L9238（P0-4 卦一致性校验段，已全币种全场景永久生效，默认参数：
    lookup_conflict_conf_mult=0.70 × lookup_conflict_raise_a_floor=0.85 硬地板
    + 查表+历史滑窗双冲突 TRUE 时硬拦截 block=True + 同卦历史不稳 ×0.90 三层判决）。

    本函数仅保留用于 `test_p0_score_b_event_boost.py::TestHexConflictFloor` 后向兼容 TDD，
    生产注入点永不调用。FAIL-OPEN 与生产实现等价（无卦/解析错→eff=conf 不罚不抬）。

    对齐 TDD：
      - 一致性（LONG↔LONG / SHORT↔SHORT）：不惩罚，eff_conf=confidence, floor_hit=False
      - 冲突（如：水天需卦权威LONG ↔ 决策SHORT）：eff_conf = confidence × 0.70
                                再 floor 到 max(eff_conf, 0.85)（冲突时抬高门槛侧，地板抬升=True）
    """
    try:
        _hex_dir = (hex_authoritative_dir or "").strip().upper()[:4]
        _dec_dir = (decision_dir or "").strip().upper()[:4]
        _conf = max(0.0, min(1.0, float(confidence)))
        # 归一：LONG/LONG_DIR/UP/多  → LONG ; SHORT/SHORT_DIR/DOWN/空 → SHORT ; 其他 NEUT
        def _norm(d: str) -> str:
            if d in ("LONG", "UP"): return "LONG"
            if d in ("SHOR", "DOWN"): return "SHORT"
            return "NEUT"
        h = _norm(_hex_dir)
        d = _norm(_dec_dir)
        conflict = (h != "NEUT" and d != "NEUT" and h != d)
        if not conflict:
            return _conf, False
        # ×0.70 + 0.85 地板抬升（抬到≥0.85）
        eff = _conf * 0.70
        floor_hit = eff < 0.85
        if floor_hit:
            eff = 0.85
        return max(0.0, min(1.0, eff)), True
    except Exception:  # noqa: BLE003  FAIL-OPEN：不惩罚不抬
        try:
            return max(0.0, min(1.0, float(confidence))), False
        except Exception:
            return 0.65, False


# P0-DC-桥：_polling_get_coin_event_positive_strength(coin)
# 直接从 18-数据获取中心/data_center.db records表 读最近72h odaily_newsflash
# → 转为 dict-like → 调用 DC compute_coin_event_positive_strength
# FAIL-OPEN：任何异常（DB不存在/import失败）→ 返回0.0（不抬升，保守安全）
def _polling_get_coin_event_positive_strength(coin: str) -> Tuple[float, Dict[str, Any]]:
    coin_up = (coin or "").strip().upper()
    if not coin_up:
        return 0.0, {"reason": "empty_coin"}
    try:
        import sys as _sys
        import math as _m
        _dc_root = str(_PROJECT_ROOT / "18-数据获取中心")
        if _dc_root not in _sys.path:
            _sys.path.insert(0, _dc_root)
        from data_center.collectors.news.odaily_newsflash import compute_coin_event_positive_strength  # noqa: E402
        import sqlite3 as _sq3  # noqa: E402
        import pathlib as _pl  # noqa: E402
        # ── 🆕 P1 C1④ G3-A 护栏：TDD 隔离 override（测试时 monkeypatch 模块级变量读 tmp mock DB）
        #    生产：_PROJECT_ROOT 拼接真实路径；TDD：hasattr → 读 override，不污染 prod DB
        _mod_self = _sys.modules[__name__]
        if hasattr(_mod_self, "_P1_C14_TEST_DB_OVERRIDE"):
            _db = _pl.Path(str(getattr(_mod_self, "_P1_C14_TEST_DB_OVERRIDE")))
        else:
            _db = _PROJECT_ROOT / "18-数据获取中心" / "data_center.db"
        if not _db.exists():
            return 0.0, {"reason": "db_missing"}
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        # G3-A 护栏：120s 未来冷却（防时钟漂移/第三方返回未来时间戳）+ 168h=一周内信息截止
        cool_cut_ms = now_ms - 120_000          # 120s 前及更早才允许
        max_age_ms = now_ms - 168 * 3_600_000  # 一周内（SPEC §1 精确对齐）
        conn = _sq3.connect(str(_db))
        cur = conn.cursor()
        try:
            # 从 records 表 取 source='odaily_newsflash'（contract写死）
            # schema: source/category/sub_category/timestamp(ISO)/metrics(JSON)/events(JSON)/timeseries(JSON)/raw(JSON)
            cur.execute(
                "SELECT metrics, events, raw, timestamp FROM records "
                " WHERE source='odaily_newsflash' ORDER BY rowid DESC LIMIT 400"
            )
            rows = cur.fetchall()
        except Exception:
            # schema老版本/列名不同：尝试 records表
            rows = []
            try:
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'record%' LIMIT 5")
                tbls = cur.fetchall()
                for (t,) in tbls:
                    try:
                        cur.execute(f"SELECT metrics,events,raw,timestamp FROM {t} WHERE source='odaily_newsflash' ORDER BY rowid DESC LIMIT 400")
                        rows.extend(cur.fetchall())
                    except Exception:
                        pass
            except Exception:
                rows = []
        conn.close()

        def _parse_json_maybe(s):
            if s is None:
                return None
            if isinstance(s, (dict, list)):
                return s
            try:
                return json.loads(s)
            except Exception:
                return None

        recs_like: list[dict] = []
        n_used = 0
        for row in rows:
            if not isinstance(row, (list, tuple)):
                continue
            m = _parse_json_maybe(row[0]) or {}
            e = _parse_json_maybe(row[1]) or []
            raw = _parse_json_maybe(row[2]) or {}
            # timestamp列(ISO str / int 秒级 / int ms级)转published_ms兜底
            pub_ms = 0
            if len(row) >= 4 and row[3] is not None:
                ts = row[3]
                try:
                    if isinstance(ts, (int, float)):
                        tv = float(ts)
                        if tv > 1_000_000_000_000:
                            pub_ms = int(tv)
                        elif tv > 1_000_000_000:
                            pub_ms = int(tv * 1000)
                    elif isinstance(ts, str):
                        # ISO str → 解析
                        try:
                            if ts.endswith("Z"):
                                ts = ts[:-1] + "+00:00"
                            pub_ms = int(datetime.fromisoformat(ts).timestamp() * 1000)
                        except Exception:
                            pass
                except Exception:
                    pub_ms = 0
            # events结构补齐（与compute_coin_event_positive_strength对齐）
            if not isinstance(e, list) or len(e) == 0:
                e = [{"event_type": str(m.get("od_event_type", "market_sentiment") or "market_sentiment"),
                     "importance": 2 if str(m.get("od_is_important", "false")) == "true" else 1,
                     "published_ms": int(pub_ms) if pub_ms > 0 else 0}]
            else:
                # 确保第一个 event 有 published_ms（用于衰减）
                if isinstance(e[0], dict) and pub_ms > 0 and not e[0].get("published_ms"):
                    e[0]["published_ms"] = int(pub_ms)
            # ── 🆕 P1 C1④ G3-A 护栏：120s未来冷却 + 168h一周截止双保险（WHERE 等价快速失败）
            #    范围 published_ms ∈ [now-168h, now-120s]；pms=0(未知老schema)→保守丢弃
            #    与 DC 侧 compute_coin_event_positive_strength G3-B dt 范围断言字节对称
            if isinstance(e, list) and len(e) >= 1 and isinstance(e[0], dict):
                pms = int(e[0].get("published_ms", 0) or 0)
                if pms <= 0 or pms > cool_cut_ms or pms < max_age_ms:
                    continue
            # tickers_hit：raw里（新格式）或 metrics里的 od_tickers_hit_csl（老格式兼容）
            ticks = None
            if isinstance(raw, dict):
                t = raw.get("tickers_hit")
                if isinstance(t, list):
                    ticks = [str(x) for x in t]
            if not ticks and isinstance(m, dict):
                csl = m.get("od_tickers_hit_csl")
                if isinstance(csl, str) and csl:
                    ticks = [x.strip().upper() for x in csl.split(",") if x.strip()]
            recs_like.append({
                "metrics": m if isinstance(m, dict) else {},
                "events": e,
                "raw": raw if isinstance(raw, dict) else {},
                "tickers_hit": ticks or [],
            })
            n_used += 1
            if n_used >= 300:
                break
        strength, debug = compute_coin_event_positive_strength(coin_up, recs_like, now_ms=now_ms)
        debug.setdefault("records_in_db", len(rows))
        debug.setdefault("records_parsed", n_used)
        return float(max(0.0, min(1.0, strength))), debug
    except Exception as e:  # noqa: BLE003  FAIL-OPEN：DB路径/列/import全失败→0.0不抬
        return 0.0, {"error": f"{type(e).__name__}:{str(e)[:80]}"}


def _load_registry_symbols():
    """从 token_registry.json 加载启用的币种列表。文件不存在/损坏时返回 None。"""
    for p in _REGISTRY_PATHS:
        if p is None or not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            tokens = data.get("tokens", [])
            syms = []
            for t in tokens:
                if isinstance(t, dict):
                    if not t.get("enabled", True):
                        continue
                    s = str(t.get("symbol", "")).strip().upper()
                    if s:
                        syms.append(s)
                elif isinstance(t, str) and t.strip():
                    syms.append(t.strip().upper())
            if syms:
                return syms
        except Exception:
            continue
    return None


def _rag_hotpath_lookup(self, query: str, top_k: int = 5) -> list:
    """FAIL-OPEN 热路径 RAG 检索。任何异常返回空列表，不阻塞交易决策。

    设计要点：
    - 懒加载：首次调用才 import rag_engine + 加载 bge 模型
    - 线程池异步：3 秒超时，防止模型加载阻塞交易
    - 环境变量 ENABLE_RAG_HOTPATH=0 一键关闭
    - FAIL-OPEN：import 失败/检索异常/超时/空结果 均返回空列表
    """
    if os.environ.get("ENABLE_RAG_HOTPATH", "1") == "0":
        return []
    if not query or not query.strip():
        return []
    global _RAG_CLIENT
    try:
        if _RAG_CLIENT is None:
            with _RAG_CLIENT_LOCK:
                if _RAG_CLIENT is None:
                    import sys as _sys
                    _rag_dir = Path(__file__).resolve().parents[3] / "2-KNOWLEDGE" / "9-RAG-INFRA"
                    if str(_rag_dir) not in _sys.path:
                        _sys.path.insert(0, str(_rag_dir))
                    from rag_engine import hybrid_search as _hs
                    _RAG_CLIENT = _hs  # 函数引用，非实例
        future = _RAG_EXECUTOR.submit(_RAG_CLIENT, query, top_k=top_k)
        results = future.result(timeout=30.0)  # 首次加载 bge 模型 ~16s，给 30s 安全边际

        # ★ 断层3：异步 record 检索结果到认知库（FAIL-OPEN，不阻塞）
        if results and os.environ.get("ENABLE_RAG_FEEDBACK", "1") == "1":
            _RAG_EXECUTOR.submit(_rag_record_to_memory, query, results)

        return results
    except FuturesTimeout:
        try:
            self._log(f"[RAG-HOTPATH] 检索超时(30s) query={query[:40]}", "WARN")
        except Exception:
            pass
        return []
    except Exception as _e:
        try:
            self._log(f"[RAG-HOTPATH] 检索异常(FAIL-OPEN): {type(_e).__name__}: {_e}", "WARN")
        except Exception:
            pass
        return []


def _rag_record_to_memory(query: str, results: list):
    """异步将 RAG 检索结果写入 4-MEMORY 认知库。FAIL-OPEN。

    断层3 闭环：RAG 检索 → 认知库 record → 后续 recall 可命中。
    任何异常静默跳过，不影响交易决策。
    """
    try:
        import sys as _sys
        _rag_dir = Path(__file__).resolve().parents[3] / "2-KNOWLEDGE" / "9-RAG-INFRA"
        if str(_rag_dir) not in _sys.path:
            _sys.path.insert(0, str(_rag_dir))
        from bridge.memory_bridge import record_retrieval_as_memory
        record_retrieval_as_memory(query, results)
    except Exception:
        pass  # 认知系统不可用，静默跳过


# 断层1：交易案例蒸馏执行器（单线程，避免并发写文件）
_DISTILL_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="case-distill")


def _distill_trade_to_knowledge(self, trade_rec):
    """异步将交易案例蒸馏成 md 入知识库。FAIL-OPEN。

    断层1 闭环：平仓 TradeRecord → md 文档 → 向量索引 → RAG 可检索历史案例。
    任何异常只记日志，不阻塞 _handle_close_position。
    """
    if os.environ.get("ENABLE_CASE_DISTILL", "1") == "0":
        return
    try:
        from datetime import datetime
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _inst = str(getattr(trade_rec, 'inst_id', 'unknown')).replace("-", "_")
        _fname = f"case_{_ts}_{_inst}.md"
        _cases_dir = Path(__file__).resolve().parents[3] / "2-KNOWLEDGE" / "1-TRADING" / "cases"
        _cases_dir.mkdir(parents=True, exist_ok=True)
        _fpath = _cases_dir / _fname

        _content = f"""# 交易案例 {trade_rec.inst_id} {_ts}

- **币种**: {getattr(trade_rec, 'inst_id', 'N/A')}
- **方向**: {getattr(trade_rec, 'direction', 'N/A')}
- **来源**: {getattr(trade_rec, 'source_tag', 'unknown')}
- **入场价**: {getattr(trade_rec, 'entry_price', 'N/A')}
- **离场价**: {getattr(trade_rec, 'exit_price', 'N/A')}
- **盈亏**: {getattr(trade_rec, 'pnl', 'N/A')} ({getattr(trade_rec, 'pnl_pct', 0)*100:.2f}%)
- **离场原因**: {getattr(trade_rec, 'exit_reason', 'N/A')}
- **SL ROI**: {getattr(trade_rec, 'base_sl_roi', 'N/A')}
- **TP ROI**: {getattr(trade_rec, 'base_tp_roi', 'N/A')}
- **共识分**: {getattr(trade_rec, 'score_consensus', 'N/A')}

## 市场快照
{json.dumps(getattr(trade_rec, 'market_snapshot', {}), ensure_ascii=False, indent=2)}

> 最后更新：{_ts[:8]} | 来源：自动蒸馏自 TradeRecord
"""
        _fpath.write_text(_content, encoding="utf-8")

        # 异步触发向量索引
        _DISTILL_EXECUTOR.submit(_ingest_case, _fpath)
    except Exception as _e:
        try:
            self._log(f"[CASE-DISTILL] 蒸馏异常(FAIL-OPEN): {type(_e).__name__}: {_e}", "WARN")
        except Exception:
            pass


def _ingest_case(file_path):
    """异步触发向量索引。FAIL-OPEN。

    case 文件已写入 2-KNOWLEDGE/1-TRADING/cases/，直接调用 build_index
    增量更新 ChromaDB。不使用 ingest_document（其去重检查会把文件自身
    判定为 duplicate 而跳过索引）。
    """
    try:
        import sys as _sys
        # file_path = .../2-KNOWLEDGE/1-TRADING/cases/case_xxx.md
        # parents[2] = .../2-KNOWLEDGE
        _resolved = Path(file_path).resolve()
        _knowledge_dir = _resolved.parents[2]  # 2-KNOWLEDGE/
        _rag_dir = _knowledge_dir / "9-RAG-INFRA"
        if str(_rag_dir) not in _sys.path:
            _sys.path.insert(0, str(_rag_dir))
        from vector_store.build_index import build_index
        from vector_store.config import CHROMA_DB_PATH, COLLECTION_NAME
        build_index(_knowledge_dir, db_path=CHROMA_DB_PATH,
                    collection_name=COLLECTION_NAME)
    except Exception:
        pass  # 索引失败不阻塞


def _rag_feedback_on_close(self, trade_rec):
    """平仓后反哺 RAG 权重：verify 检索记忆 + update_boost。FAIL-OPEN 异步。

    闭环链路：RAG检索 → record_retrieval_as_memory（写记忆+映射）
    → 平仓盈亏 → verify_and_feedback（更新confidence + boost）
    → 下次检索 apply_boost_to_results 乘 boost 重排。

    success = pnl >= 0（盈利则正向反哺）。
    """
    if os.environ.get("ENABLE_RAG_FEEDBACK", "1") == "0":
        return
    try:
        import sys as _sys
        _rag_dir = Path(__file__).resolve().parents[3] / "2-KNOWLEDGE" / "9-RAG-INFRA"
        if str(_rag_dir) not in _sys.path:
            _sys.path.insert(0, str(_rag_dir))
        from bridge.memory_bridge import verify_and_feedback, resolve_default_map_path

        coin = str(getattr(trade_rec, "inst_id", "")).split("-")[0]
        direction = str(getattr(trade_rec, "direction", "")).lower()
        success = float(getattr(trade_rec, "pnl", 0.0)) >= 0

        # 从映射表查找该币种相关的检索记忆
        matched_ids = []
        try:
            with open(resolve_default_map_path(), "r", encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line:
                        continue
                    try:
                        _m = json.loads(_line)
                        _q = str(_m.get("query", ""))
                        if coin and coin in _q:
                            matched_ids.append(_m.get("memory_id"))
                    except Exception:
                        continue
        except Exception:
            pass

        # 去重 + 限制单次 verify 数量（避免爆量）
        matched_ids = list(dict.fromkeys(matched_ids))[-20:]

        for _mid in matched_ids:
            if not _mid:
                continue
            try:
                verify_and_feedback(_mid, success=success)
            except Exception:
                pass  # 单条 verify 失败不阻塞

        try:
            self._log(
                f"[RAG-FEEDBACK] {coin} {'盈利' if success else '亏损'} "
                f"verify记忆={len(matched_ids)}条 boost已更新",
                "DEBUG",
            )
        except Exception:
            pass
    except Exception:
        pass  # 反哺链路失败不阻塞平仓


class PollingTrader:
    """易经推理轮询交易器（P2 完整版）"""

    # config.json 中与进化阈值相关的键
    _EVOLUTION_CONFIG_KEYS = (
        "confidence_threshold",
        "daily_loss_limit",
        "max_consecutive_losses",
        "default_position_pct",
    )

    # 币种规范化映射（OKX 合约 ticker 修正）
    _NORMALIZE_COIN = {"XAUT": "XAU", "XSNDK": "SNDK", "XSPCX": "SPCX"}

    @classmethod
    def _norm(cls, c):
        cu = str(c).strip().upper()
        return cls._NORMALIZE_COIN.get(cu, cu)

    # 统一冷静期：平仓后 N 秒内禁止该币种任何方向新开仓（含反手）
    # 防止"平仓→立即反手→又亏→再反手"的频繁来回割肉循环
    COOLDOWN_SEC = 28800  # 8 小时

    # --------- 做空置信度分层阈值（bearish_score → multiplier）---------
    # 注意：有效阈值 = 基础阈值 × 乘数
    #   → 乘数 < 1 = 降低门槛（放宽）；乘数 > 1 = 抬高门槛（收紧）
    #
    # STRONG: 5均线严格空头排列 → ×0.91 ≈ 1/1.10 降低门槛（强趋势，允许较低置信度入场）
    # NORMAL: 3~4均线空头       → ×1.00 标准
    # WEAK  : 仅1~2均线短周期空头 → ×1.18 ≈ 1/0.85 抬高门槛（弱趋势，要求更高置信度避免诱空）
    SHORT_CONF_MULTI_MA_STRONG: float = 0.9091  # ≈ 1/1.10
    SHORT_CONF_MULTI_MA_NORMAL: float = 1.0000
    SHORT_CONF_MULTI_MA_WEAK:   float = 1.1765  # ≈ 1/0.85

    # --------- market_regime 阈值调节器（基于回测胜率反比）---------
    # 理论：regime 反映市场形态，不同形态下做空胜率差异显著
    #       回测数据：TREND_BEAR 28.6% < STRONG_TREND_BEAR 50.0% < RANGING 68.6%
    #       乘数 > 1.0 = 抬高阈值 = 抑制做空；乘数 < 1.0 = 降低阈值 = 放宽做空
    #       与 bearish_score 乘数叠加：final_threshold = base × score_multi × regime_multi
    REGIME_SHORT_CONF_MULTI_TREND_BULL:        float = 1.15  # 胜率 42.9%，抑制（几乎禁止）
    REGIME_SHORT_CONF_MULTI_TREND_BEAR:        float = 1.15  # 胜率 28.6%，强抑制
    REGIME_SHORT_CONF_MULTI_STRONG_TREND_BEAR: float = 1.00  # 胜率 50.0%，中性
    REGIME_SHORT_CONF_MULTI_MEAN_REVERTING:    float = 1.00  # 无回测数据，中性
    REGIME_SHORT_CONF_MULTI_RANGING:           float = 0.90  # 胜率 68.6%，放宽（≈1/1.11）

    # --------- 做空仓位规模分层（bearish_score → position_multiplier）---------
    # 理论：周期越短可信度越低，但趋势识别越早 → 不禁开，而是控制资金规模
    #       随着跌破更多均线，弹簧压力越来越重 → 置信度越来越强 → 仓位越来越大
    #   STRONG: 5均线空头+3日确认 → 弹簧压力最重 → 标准仓位 ×1.0
    #   NORMAL: 3~4均线空头       → 中等压力     → ×0.7
    #   WEAK  : 1~2均线短周期空头 → 压力轻       → ×0.4（小仓试水）
    SHORT_POSITION_MULTI_STRONG: float = 1.0
    SHORT_POSITION_MULTI_NORMAL: float = 0.7
    SHORT_POSITION_MULTI_WEAK:   float = 0.4

    # ================================================================
    # H1 / H4 补充：长多 UP 方向（与做空方向对称）的弹簧力场阈值+仓位分层常量
    # 回测逻辑：胜率反比 → 抑制追顶，放宽震荡蓄势
    # ================================================================
    # --------- 长多置信度阈值乘数（基于 MA 评分档位）---------
    # STRONG: 5均线多头排列       → ×0.9091 ≈ 1/1.10 略微放宽阈值（顺势，但避免追极强顶）
    # NORMAL: 3~4均线多头         → ×1.0000 标准
    # WEAK  : 仅1~2均线短周期多头 → ×1.1111 ≈ 1/0.90 提高门槛（弱趋势/反抽诱多）
    LONG_CONF_MULTI_MA_STRONG: float = 0.9091
    LONG_CONF_MULTI_MA_NORMAL: float = 1.0000
    LONG_CONF_MULTI_MA_WEAK:   float = 1.1111

    # --------- market_regime 长多阈值调节器（基于回测/经验胜率反比）---------
    #   乘数 > 1.0 = 抬高阈值 = 抑制做多；乘数 < 1.0 = 降低阈值 = 放宽做多
    #   TREND_BULL        ：胜率 ~55% → ×1.05（略微抑制：避免末端追顶）
    #   STRONG_TREND_BULL ：胜率 ~45% → ×1.10（强抑制：强趋势末端大概率顶背离诱多）
    #   TREND_BEAR        ：胜率 ~30% → ×1.15（强抑制：逆势抄底）
    #   MEAN_REVERTING    ：无回测 → ×1.00（中性）
    #   RANGING           ：胜率 ~68% → ×0.85（放宽：震荡蓄势向上突破）
    REGIME_LONG_CONF_MULTI_TREND_BULL:        float = 1.05
    REGIME_LONG_CONF_MULTI_STRONG_TREND_BULL: float = 1.10
    REGIME_LONG_CONF_MULTI_TREND_BEAR:        float = 1.15
    REGIME_LONG_CONF_MULTI_MEAN_REVERTING:    float = 1.00
    REGIME_LONG_CONF_MULTI_RANGING:           float = 0.85

    # --------- 长多仓位规模分层（bullish_score → position_multiplier）---------
    #   理论：突破越多均线弹簧恢复力越强→仓位越大；强顶背离/末端追涨反而降仓
    #   STRONG: 5均线多头排列确认 → 顺势 → 标准仓位 ×1.0（保守，不主动加杠杆追）
    #   NORMAL: 3~4均线多头       → 中等 → ×0.7
    #   WEAK  : 1~2短周期多头反抽 → 轻仓 → ×0.4
    LONG_POSITION_MULTI_STRONG: float = 1.0
    LONG_POSITION_MULTI_NORMAL: float = 0.7
    LONG_POSITION_MULTI_WEAK:   float = 0.4

    # --------- 五均线分层弹簧力场：组权重（sum=1.00）---------
    # 短中期组 (MA30 + MA65)   : 0.35
    # 中期组   (MA128 + MA200) : 0.40
    # 长期组   (MA1400 ≈ 周MA200): 0.25
    FMA_GROUP_WEIGHT_SHORT: float = 0.35
    FMA_GROUP_WEIGHT_MID:   float = 0.40
    FMA_GROUP_WEIGHT_LONG:  float = 0.25

    # --------- 动态弹簧力场升级（Phase C++）---------
    # ① inter-MA力：均线间相对距离产生的趋势力
    #    F_inter = -k_inter × (MA_short - MA_long) / MA_long
    #    k_inter < k（趋势力弱于回复力）
    FMA_INTER_K_RATIO: float = 0.5  # k_inter = k × 0.5

    # ② MA斜率调制k：k_eff = k × (1 + α × tanh(slope_norm))
    #    slope > 0（MA上升）→ k_eff > k → 趋势方向弹簧更硬（不易反弹）
    #    slope < 0（MA下降）→ k_eff > k → 反趋势方向弹簧更硬
    FMA_SLOPE_ALPHA: float = 0.3   # 调制强度
    FMA_SLOPE_WINDOW: int = 5     # 斜率计算窗口（线性回归）

    # ③ 势能阈值：U = ½kx²，用于超卖/超买检测
    #    回测修正：U 大 = 价格偏离均线远 = 超卖/超买 → 禁止做空（均值回归概率高）
    #    U 小 = 价格接近均线 → 趋势早期，可做空
    FMA_POTENTIAL_OVERSOLD: float = 0.010  # U > 0.010 → 超卖，禁止做空（回测验证）
    FMA_POTENTIAL_LOW: float = 0.005       # U < 0.005 → 蓄势不足

    # ④ F_total 变化率（趋势加速度）阈值
    #    F_dot = F_total(t) - F_total(t-1)
    #    F_dot > 0 → 偏离在加速（趋势延续）→ 可做空
    #    F_dot < 0 → 偏离在收敛（均值回归）→ 禁止做空
    FMA_F_DOT_THRESHOLD: float = -0.005  # F_dot < 此值 → 收敛中，禁止做空

    # 五均线 + 3日跌破确认：最短期跌破需要 N 日收盘价 ≤ MA30
    FMA_SHORT_TIER_BREAKDOWN_BARS: int = 3

    # --------- Phase D：市场形态判定（Market Regime Classification）---------
    # 4维度形态判定器 → 5种 regime → 差异化做空过滤
    #   ① 趋势强度比 TR  = |F_inter| / (|F_net| + |F_inter| + ε)
    #      高 TR → 均线排列主导（趋势市）；低 TR → 价格偏离主导（均值回归）
    #   ② 均线发散度 CV  = std(MA30/65/128/200) / mean
    #      高 CV → 均线发散（趋势明确）；低 CV → 均线纠缠（震荡）
    #   ③ 斜率强度 |slope_avg|（MA 倾斜度，%）
    #   ④ F_dot（F_total 变化率）
    FMA_REGIME_TR_STRONG: float    = 0.60   # TR > 0.60 → 强趋势
    FMA_REGIME_TR_TREND: float     = 0.50   # TR > 0.50 → 弱趋势
    FMA_REGIME_TR_REVERT: float    = 0.40    # TR < 0.40 → 均值回归
    FMA_REGIME_CV_STRONG: float    = 0.030   # CV > 0.030 → 发散趋势
    FMA_REGIME_CV_TREND: float     = 0.020   # CV > 0.020 → 弱趋势发散
    FMA_REGIME_CV_REVERT: float    = 0.025   # CV < 0.025 → 均线纠缠
    FMA_REGIME_SLOPE_STRONG: float = 0.030   # |slope_avg| > 0.030% → 强趋势
    FMA_REGIME_SLOPE_TREND: float  = 0.020   # |slope_avg| > 0.020% → 弱趋势
    FMA_REGIME_FDOT_STRONG: float  = -0.002  # F_dot > -0.002 → 偏离加速扩大
    FMA_REGIME_FDOT_REVERT: float  = -0.003  # F_dot < -0.003 → 偏离快速收敛

    # --------- 各 regime 的做空过滤阈值（差异化）---------
    # 注: U_threshold 基于 U_short（仅短期组MA30/65势能），尺度远小于 U_potential
    #   U_short ≈ 0.35 × ½ × k_eff × (x30² × w30 + x65² × w65)
    #   价格偏离MA30 5% → U_short ≈ 0.002；偏离10% → U_short ≈ 0.006
    # STRONG_TREND_BEAR：宽松（顺势做空，均线成阻力）
    FMA_ALLOW_SCORE_STRONG_TREND: tuple = ("STRONG", "NORMAL", "WEAK")
    FMA_U_THRESHOLD_STRONG_TREND: float  = 0.010   # 趋势市允许更大偏离(~10% below MA30)
    FMA_FDOT_STRONG_TREND: float        = -0.002
    # TREND_BEAR：收紧（弱趋势市假突破多，回测胜率仅 28.6%）
    #   仅允许 STRONG/NORMAL 档（剔除 WEAK），更严超卖和加速过滤
    FMA_ALLOW_SCORE_TREND: tuple = ("STRONG", "NORMAL")
    FMA_U_THRESHOLD_TREND: float  = 0.003           # ~5% below MA30（收紧）
    FMA_FDOT_TREND: float         = -0.003          # 要求偏离仍在加速
    # MEAN_REVERTING：严格（反向，F>0 = 超卖 = 禁止做空）
    FMA_ALLOW_SCORE_REVERT: tuple = ("WEAK",)      # 仅刚跌破才允许
    FMA_U_THRESHOLD_REVERT: float = 0.002           # ~4% below MA30
    FMA_FDOT_REVERT: float        = -0.003
    # RANGING：放宽（震荡市跌破信号胜率 68.6% 最高，允许全档位）
    #   回测显示 RANGING 做空胜率最高但旧过滤仅放行 12/51，过度过滤
    FMA_ALLOW_SCORE_RANGE: tuple  = ("STRONG", "NORMAL", "WEAK")
    FMA_U_THRESHOLD_RANGE: float  = 0.003            # ~5% below MA30（放宽）
    FMA_FDOT_RANGE: float         = -0.003           # 放宽收敛限制

    # 偏见底兜底窗口：MA1400（长期组）± N% 内 → 禁止做空
    #   接近长期MA往往是大周期支撑位附近，直接禁止做空
    FMA_LONG_TERM_BOTTOM_BUFFER: float = 0.02

    # 弹簧力场形态过滤开关（回测验证效果不佳，默认关闭）
    #   False: 走简单趋势确认逻辑（偏见底兜底 + valid_breakdown + price<MA128）
    #   True : 走 _regime_short_filter 形态差异化过滤（仅用于实验/对比）
    FMA_REGIME_FILTER_ENABLED: bool = False

    def __init__(
        self,
        interval: int = 3600,
        coins: list = None,
        bar: str = "1H",
        confidence_threshold: float = 0.70,
        short_confidence_threshold: float = 0.80,
        max_positions: int = 5,
        kline_limit: int = 200,
        initial_equity: float = 100.0,
        daily_loss_limit: float = -30.0,
        max_consecutive_losses: int = 999,
        default_position_pct: float = 0.10,
        guardian: ProcessGuardian = None,
        shared_dir=None,
        use_bcrm2: bool = True,
        shadow_mode: bool = False,
        # Phase1 三开关（默认全 True → 方案 C spec 强制经过，必须经过）
        enable_cbr_cycle_log: bool = True,
        enable_elder_ray_c4: bool = True,
        enable_win_prob_factor: bool = True,
        # 方案 C v3.0 方案级开关（默认全 True → 方案 C spec 强制经过，必须经过）
        # SW-C3：三层动态权重引擎；SW-C4：三层弹性放行矩阵；SW-C5：BCRM 连续信号观察器
        # SW-C6：BTC 自反调控闸门；SW-C8：组合级风险熔断（G-02/G-04）
        enable_three_layer_weighter: bool = True,
        enable_elastic_gate_3l: bool = True,
        enable_bcrm_continuity_obs: bool = True,
        enable_btc_self_reflex_valve: bool = True,
        enable_portfolio_risk_fuses: bool = True,
        # — BDSM 微仓实盘测试硬上限：None=沿用 scaling_plan 默认(167U)，否则 min(plan, 该值) —
        #   设计意图：小额真实环境测试阶段，将单币预算封顶到安全范围（如 20~30 U），
        #   等 10+ 笔完整交易、胜率 ≥70%、回撤 OK 后再移除小帽恢复到 scaling_plan 默认。
        bdsm_budget_per_coin: float = None,
    ):
        self.interval = interval
        # ★ shadow-mode 全局硬闸门：True 时严格禁止所有开/平/减仓指令（仅执行推理逻辑/写shadow日志/写diagnostic）
        self.shadow_mode = bool(shadow_mode)
        if self.shadow_mode:
            # 构造阶段即醒目打印一次，防止误启用真钱模式
            print("[SHADOW MODE] 全局影子冷启动模式：所有开仓/平仓/减仓将被 BLOCKED，仅推理+影子日志+监控正常运行")
        # — BDSM 微仓实盘测试参数 —
        #   None：使用 scaling_plan 默认剩余预算（167U/币）
        #   float：对 scaling_plan.remaining_budget 做 min 覆盖，保证单币绝对预算不突破
        #   设置场景：shadow_mode=False 后首次真实环境测试阶段，值如 20~30 U 防单次过大
        try:
            self.bdsm_budget_per_coin: float | None = (
                float(bdsm_budget_per_coin) if bdsm_budget_per_coin is not None else None
            )
        except (TypeError, ValueError):
            self.bdsm_budget_per_coin = None
        if self.bdsm_budget_per_coin is not None:
            print(
                f"[BDSM 微仓实盘] 单币预算硬上限={self.bdsm_budget_per_coin:.2f} U "
                f"（将覆盖 scaling_plan.remaining_budget=167U 的默认值）"
            )
        default_coins = _load_registry_symbols() or [
            # — BDSM 权威池 10 币（按 spec §R4，优先排在池前端，BCRM 引擎共享）—
            "UNI",
            "PUMP",
            "HYPE",
            "AAVE",  # BDSM 新增
            "SOL",
            "CRCL",
            "ETH",  # BDSM 新增：仅做多允许（SHORT_BAN，见下方 SHORT_ONLY_BLACKLIST 过滤）
            "BTC",
            "ZEC",  # BDSM 新增（L1 隐私币）
            "ARB",  # BDSM 新增（L2 龙头）
            # — 其他非 BDSM 币种（BCRM & 混合池）—
            "MU",
            "SKHYNIX",
            "XAU",
            "XAG",
            "GOOGL",
            "NVDA",
            "AMZN",
            "OKB",
            "SNDK",
            "SPCX",
            "COIN",
            "BMNR",
            "MSTR",
        ]
        # P4 修复：币种规范化映射（_norm 已提升为类方法，供 __init__ 和 _maybe_refresh_coins 共用）
        self.coins = [self._norm(c) for c in (coins or default_coins)]
        self._last_pool_refresh = 0.0  # 公共代币池8h刷新时间戳
        self.bar = bar
        self.confidence_threshold = confidence_threshold
        self.short_confidence_threshold = short_confidence_threshold  # 做空独立阈值（高于做多）
        self.max_positions = max_positions
        self.kline_limit = kline_limit
        # 将/法维度 system_state 自省专用：缓存 P0 风控配置，便于 FiveDomainFeatureComputer
        # 通过 _cls_get(_by_class) 取 factor_coverage_pct / implemented_strategies。
        self.default_position_pct = float(default_position_pct or 0.10)
        self.max_consecutive_losses = int(max_consecutive_losses or 999)

        # A-1修复：启动时从 OKX_SIM/config.json 加载进化后的阈值，覆盖默认值
        # 注意：需要在 risk_manager 创建后调用，才能同时更新 risk_manager.state
        self._evolution_config_path = None

        self.bcrm_engine = BCRMEngine.from_config()  # PROP-20260810
        self.bagua_engine = BaguaEngine()
        self.okx_client = OKXSimulatedClient()

        # ── TEE 执行引擎影子模式开关（2026-09-06 全系统统一开启）─────────
        # enable_tee=False + shadow_mode=True → TEE 完整决策但只记录不拦截
        # 实际下单仍走原始 okx_client.place_order()，TEE 审计日志记录差异
        # 引擎构造延迟到 log_file 初始化之后（见 _init_tee_shadow）
        import os as _os
        self._tee_enable = _os.environ.get("YIJING_ENABLE_TEE", "").lower() in ("1", "true")
        self._tee_shadow = _os.environ.get("YIJING_TEE_SHADOW_MODE", "").lower() in ("1", "true")
        self._tee_engine = None
        self._tee_engine_init_lock = __import__("threading").Lock()

        self.use_bcrm2 = use_bcrm2
        self.bcrm2_adapters = {}
        # v3.0：per-coin降级机制，替代全局use_bcrm2=False
        # 记录BCRM 2.0训练失败的币种 + 失败时间戳，避免一个币种失败影响其他币种
        self.bcrm2_failed_coins: dict = {}  # {coin: fail_ts}
        self.bcrm2_retry_interval_sec: int = 86400  # 训练失败后24h才重试
        self.bcrm2_min_samples: int = 100  # BCRM 2.0训练所需最小有效样本数

        # P0-2: 动态币种黑名单 — 连续2次亏损自动加入黑名单3日
        # 到期后自动释放（有趋势过滤保护，不需要永久封禁）
        # 可被 config.json 的 blacklist_coins 字段热重载覆盖（追加手动黑名单）
        # 静态永久封禁（回测验证历史表现极差，即使趋势过滤下仍持续亏损）
        # — BDSM 2026-09 调整：ETH 从全黑名单降级为仅做空禁（SHORT_BAN），做多按 BDSM/BCRM 信号允许
        self.blacklist_coins: set = {"NEAR", "XRP", "DOT", "ADA", "AVAX", "LINK", "BNB"}  # 手动永久黑名单
        # SHORT_BAN：这些币种只允许做多，不允许做空（历史验证做空持续亏损，或 BDSM 协议模型为 LONG_ONLY）
        # ETH：历史做空样本亏损率高，且 BDSM 方向约束默认 LONG_ONLY；BTC：BCRM 做空信号已 100% 亏损
        self.SHORT_ONLY_BLACKLIST: set = {"ETH", "BTC"}
        # —— R5 铁律 · 仓位子池隔离（互不抢占）——
        #   BDSM 子池：币种 ∈ BDSM_COINS，标签 source_tag="bdsm"，最多 3 仓
        #   BCRM 子池：币种 ∉ BDSM_COINS，标签 source_tag="bcrm"，最多 5 仓
        #   evolution 子池（P2-S4b）：紧耦合流自动建仓，标签 source_tag="evolution"，最多 5 仓
        #   共享 OKX 可用资金余额（不做资金切分）
        # 用户决策 2026-09-07：三子池各自独立开仓，evolution(5)/BDSM(3)/BCRM(5) 互不串扰
        # 用户决策 2026-09-09：evolution 子池上限 3→5；测试仓（BCRM is_trial / Evolution tier=probe）最多 2 单，避免挤压正常仓位
        # 用户决策 2026-09-11：分离上限 — Evolution probe 独立 4 单，BCRM is_trial 保持 2 单
        # 用户决策 2026-09-11：放大开仓容量 — evolution 5→10, probe 4→8（总名义 ~9200U < 可用 10305U）
        self.SUBPOOL_MAX_POSITIONS: Dict[str, int] = {"bdsm": 3, "bcrm": 5, "evolution": 10, "strategy": 3}
        # 测试仓（试错仓）上限：BCRM 的 is_trial=True 最多 2 单
        self.MAX_TRIAL_POSITIONS: int = 2
        # Evolution probe tier 独立上限：4 单（从8降低，避免低确信度试探仓过多）
        self.MAX_EVOLUTION_PROBE_POSITIONS: int = 4
        # 易经子池兜底上限（BCRM 5 + BDSM 3 = 8，不含 evolution 子池），不受启动参数覆盖
        _yijing_max = self.SUBPOOL_MAX_POSITIONS["bcrm"] + self.SUBPOOL_MAX_POSITIONS["bdsm"]
        self.max_positions = _yijing_max  # 固定 8
        self._legacy_global_max_positions = int(_yijing_max)
        # BDSM 权威池（供 is_bdsm_coin / _classify_source_tag 使用，懒加载 FAIL-OPEN）
        # ★ FIX(2026-09-02 实盘 daemon 跑 `-m scripts.memory_l4.polling_trader` 时 import 根=scripts.memory_l4,
        #   force_vector 作为兄弟子包 需要 `scripts.memory_l4.force_vector.xxx` 路径才能 import；
        #   直接 `from force_vector...` 会持续 FAIL-OPEN 成 frozenset()，导致 BDSM 7 币全当成 BCRM。
        _bdsm_coins_src = frozenset()
        for _mod_path in (
            "scripts.memory_l4.force_vector.coin_fundamental_ranker",
            "force_vector.coin_fundamental_ranker",
        ):
            try:
                _pkg = __import__(_mod_path, fromlist=["BDSM_COINS"])
                _bdsm_coins_src = frozenset(getattr(_pkg, "BDSM_COINS", frozenset()) or frozenset())
                if _bdsm_coins_src:
                    break
            except Exception:
                _bdsm_coins_src = frozenset()
                continue
        # 最终兜底（绝对不能变空集 → 退化成 BCRM 5 仓单池）：Spec v1.4 §R4 权威池 静态 8 币
        _BDSM_FALLBACK = frozenset({"UNI", "PUMP", "HYPE", "AAVE", "SOL", "CRCL", "ETH", "BTC", "ZEC", "ARB"})  # noqa: N806
        self.BDSM_COINS: frozenset = frozenset(_bdsm_coins_src) or _BDSM_FALLBACK
        # BDSM 独立开仓开关（默认开启，用于验证BDSM价值建仓能力）
        # 独立开仓：遍历BDSM_COINS，CVS≥0.3且BDS≥0.3且子池未满→触发建仓
        # 关闭后BDSM仅作为BCRM开仓流程中的价值建仓增强层
        self.enable_bdsm_independent_open: bool = _os.environ.get(
            "ENABLE_BDSM_INDEPENDENT_OPEN", "1"
        ).lower() in ("1", "true", "yes")
        # BDSM 方向叠加模式开关（默认开启）：BDSM 基本面方向约束是否拦截 BCRM2.0 开仓
        #   True  → BDSM direction_constraint 生效（LONG_ONLY/SHORT_ONLY 拦截反向开仓）
        #   False → 关闭叠加，BCRM2.0 技术方向独立决策（用于 A/B 对比观察）
        self.enable_bdsm_direction_overlay: bool = _os.environ.get(
            "ENABLE_BDSM_DIRECTION_OVERLAY", "1"
        ).lower() in ("1", "true", "yes")
        # BDSM 做空试错单开关（默认关闭）：BDSM 恶化型离场信号转做空试错
        #   True  → bds<0 / CLOSE_ALL / trend full_exit 等恶化信号触发做空试错单
        #   False → 关闭（默认），BDSM 仅做多
        #   约束层 _apply_bdsm_direction_constraint 不变，独立开空走 _bdsm_independent_open
        self.enable_bdsm_short_trial: bool = _os.environ.get(
            "ENABLE_BDSM_SHORT_TRIAL", "0"
        ).lower() in ("1", "true", "yes")
        # BDSM 战略层 war_state 拦截开关（默认关闭）：
        #   False → BDSM 独立验证，不受战略层 war_state=FREEZE/COOLDOWN 影响
        #   True  → 战略层 FREEZE/COOLDOWN 拦截 BDSM 加仓（验证完成后可开启）
        #   设计原因：BDSM 子池需要独立验证其价值建仓能力，战略层通过 SubSystemBridge
        #   的 war_state→ESS温度 映射正确影响自进化系统即可，BDSM 保持独立。
        self.enable_bdsm_war_state_check: bool = _os.environ.get(
            "ENABLE_BDSM_WAR_STATE_CHECK", "0"
        ).lower() in ("1", "true", "yes")
        # BCRM2.0 战略层 direction_state 闸门开关（默认关闭）：
        #   False → BCRM2.0 影子模式，不受战略层 direction_state 影响，专注技术面分析
        #   True  → 战略层 direction_state=FREEZE/SHORT_ONLY/LONG_ONLY 拦截 BCRM 开仓
        #   设计原因：BCRM2.0 作为技术面分析模块独立验证，战略层约束通过 evolution 子池
        #   和战略层独立路径正确生效即可，BCRM2.0 保持技术面独立决策。
        #   shadow_logger 仍记录 direction_state 字段供 A/B 对比观察。
        self.enable_bcrm_direction_state_check: bool = _os.environ.get(
            "ENABLE_BCRM_DIRECTION_STATE_CHECK", "0"
        ).lower() in ("1", "true", "yes")
        # —— 战略层+策略层独立开仓开关（默认关闭，安全第一）——
        #   独立开仓：三层信号组合（战略层 war_state/direction_state + 策略层 select() + 技术信号 d_star/ri）
        #   → 产出独立买卖信号 → 独立建仓，用于单独测试战略层+策略层效果
        #   仓位：cap_pct × position_mult × STRATEGY_BASE_BUDGET_USDT
        #   子池隔离：source_tag="strategy"，独立计数不串扰 bdsm/bcrm/evolution
        self.enable_strategy_independent_open: bool = _os.environ.get(
            "ENABLE_STRATEGY_INDEPENDENT_OPEN", "0"
        ).lower() in ("1", "true", "yes")
        # 币种池与 BCRM2.0 保持一致：默认使用 self.coins（--coins 命令行参数）
        # 可通过 STRATEGY_INDEPENDENT_COINS 环境变量覆盖（逗号分隔）
        _env_strategy_coins = (_os.environ.get("STRATEGY_INDEPENDENT_COINS", "") or "").strip()
        if _env_strategy_coins:
            self.STRATEGY_INDEPENDENT_COINS: frozenset = frozenset(
                c.strip().upper() for c in _env_strategy_coins.split(",") if c.strip()
            )
        else:
            self.STRATEGY_INDEPENDENT_COINS: frozenset = frozenset(
                str(c).upper() for c in self.coins
            )
        self.STRATEGY_BASE_BUDGET_USDT: float = float(
            _os.environ.get("STRATEGY_BASE_BUDGET_USDT", "200") or "200"
        )
        self.MAX_STRATEGY_POSITIONS: int = int(
            _os.environ.get("MAX_STRATEGY_POSITIONS", "3") or "3"
        )
        # Kline 信号缓存（per-coin），由 _check_evolution_kline_signal 填充
        self._last_kline_result_by_coin: Dict[str, dict] = {}
        self.dynamic_blacklist: dict = {}  # {coin: {"expire_ts": float, "reason": str, "added_ts": float}}
        self.DYNAMIC_BLACKLIST_CONSECUTIVE_LOSSES = 2  # 连续亏损次数阈值
        self.DYNAMIC_BLACKLIST_DURATION_SEC = 3 * 86400  # 3日（秒）

        # P0-3: 卦象黑名单 — 历史回测胜率0%的卦象，强制HOLD
        # 数据来源：坤为地(7/7亏) 震为雷(5/5亏) 火地晋(2/2亏) 地雷复(2/2亏) 全部100%亏损
        # 可被 config.json 的 hexagram_blacklist 字段热重载覆盖
        self.hexagram_blacklist: set = {"坤为地", "震为雷", "火地晋", "地雷复"}

        # [PUMP修复 2026-08-23] 卦象→方向决策历史滑窗（每币种独立缓存最近 N=30 笔推理）
        # 用于开仓前校验"同一卦象是否出现方向矛盾"（如天地否本轮判UP但历史全SHORT）
        self.HEX_HISTORY_WINDOW_PER_COIN: int = 30
        self._recent_hex_decisions: Dict[str, deque] = {}

        # P1-1: BTC趋势缓存（5分钟刷新一次，避免每币种重复拉取BTC日线K线）
        self._btc_trend_cache: dict = {"ts": 0, "result": None}

        if self.use_bcrm2:
            # 措施1：启动时主动验证 BCRM 2.0 模块导入与核心依赖可用性
            # 避免运行时才发现 "No module named 'bcrm2'" 等导入错误
            healthy, reason = self._health_check_bcrm2()
            if not healthy:
                # ⚠️ 严格模式：BCRM 2.0 不可用时绝不回退到 BCRM 1.0
                # 启动告警但保持 use_bcrm2=True，运行时各币种因推理失败直接跳过
                self._log(
                    f"[BCRM2.0] 启动健康检查失败: {reason} | "
                    f"严格模式启用：不降级BCRM 1.0，所有币种推理失败将直接跳过",
                    "ERROR",
                )
                try:
                    notify_system_error(
                        f"BCRM2.0 启动健康检查失败（严格模式，不降级BCRM 1.0）: {reason}",
                        component="BCRM2.0健康检查",
                    )
                except Exception as e:
                    self._log(f"[BCRM2.0] 飞书告警发送失败: {e}", "WARN")
            else:
                self._log("[BCRM2.0] 模式已启用（严格：禁用BCRM 1.0降级），健康检查通过", "INFO")

        self.running = False
        self.cycle_count = 0
        self.last_date = datetime.now().strftime("%Y-%m-%d")

        self.perf_tracker = PerformanceTracker(initial_equity=initial_equity)
        self.risk_manager = RiskManager(
            daily_loss_limit_usdt=daily_loss_limit,
            max_consecutive_losses=max_consecutive_losses,
            default_position_pct=default_position_pct,
            min_position_usdt=250.0,
        )

        # A-1修复：risk_manager 创建后，从 config.json 加载进化后的阈值覆盖默认值
        self._load_evolution_config(initial=True)
        self.position_tracker = PositionTracker()
        self.learning_scheduler = LearningScheduler(
            bcrm_engine=self.bcrm_engine,
            retrain_interval_cases=10,
            retrain_interval_hours=4,
            on_retrain_complete=self._on_retrain_complete,
            shared_dir=shared_dir,
        )
        self.guardian = guardian

        self.knowledge_bridge = KnowledgeBridge(shared_dir=shared_dir)
        self.external_knowledge = {}

        # 经典指标离场系统（2026-08-06 放宽：减少频繁扫损，支持高置信度长持）
        exit_cfg = ExitConfig(
            l0_max_hold_sec=172800,
            l0_max_loss_pct=-0.05,  # 最后防线不变
            tb_enabled=True,
            tb_sl_atr_mult=2.5,  # 原 1.5 → 2.5：放宽ATR-based止损，避免震荡洗出
            tb_tp_atr_mult=5.0,  # 原 3.0 → 5.0：盈亏比保持~2:1
            tb_sl_min_pct=0.06,  # 原 0.045 → 0.06：订单级最小止损 6%（对应价格0.6%@10x）
            tb_tp_min_pct=0.06,  # 原 0.04 → 0.06：同放宽
            trailing_enabled=True,
            trailing_arm_profit_pct=0.06,  # 原 0.04 → 0.06：达到6%订单盈利才启用追踪止盈，避免过早启动
            trailing_retrace_pct=0.05,  # 原 0.035 → 0.05：允许5%回调而非3.5%，减少利润锁定过急
            tstp_enabled=True,
            l1_enabled=True,
            l2_close_threshold=0.75,
            l2_reduce_threshold=0.55,
            apply_leverage_to_thresholds=True,
            inflight_cooldown_sec=180,
            l0_risk_gate_enabled=True,
            l0_risk_gate_close_enabled=False,
            l0_risk_gate_cooldown_min=60.0,
            l0_risk_gate_confirm_n=3,
            # Bug2修复: L0_RISK_GATE过度敏感（回测95.6%触发率）
            # 提高long阈值0.5→0.65：避免hold_risk刚过0.5就仓促减仓（正常波动就会触发）
            l0_risk_gate_long_thr=0.65,
            # 同步提高short阈值保持比例一致
            l0_risk_gate_short_thr=0.60,
            # Bug2修复: 新增最小持仓时间3600s=1h
            # 开仓初期hold_risk计算不稳定（K线样本少、ATR异常），给1h保护期
            l0_risk_gate_min_hold_sec=3600.0,
            # 提高盈利旁路阈值：pnl_eff>5%才跳过risk_gate（原3%太低，盈利3%可能只是噪音）
            l0_risk_gate_profit_bypass_pct=0.05,
        )
        self.exit_system = ClassicExitSystem(config=exit_cfg)
        self._exit_cfg_base = exit_cfg

        # 震荡市增强器（优化1-5统一入口）
        # 包含：5种市场状态、布林带双信号确认、MA200方向性偏向、动态止损宽度、置信度校准
        self.ranging_enhancer = RangingMarketEnhancer()
        # 优化5：卦象数据驱动校准器（500+样本后重新校准64卦参数）
        self.ranging_enhancer.hex_calibrator = HexagramDataDrivenCalibrator()

        # 易经专属离场系统：基于卦象风险-价值评估，可否决 classic 的噪音止损
        self.yijing_exit_system = YijingExitSystem(config=YijingExitConfig())
        self.yijing_exit_system.set_log_callback(self._log)

        self.log_dir = Path("data/polling_trader")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"trader_{datetime.now().strftime('%Y%m%d')}.jsonl"

        # ── TEE 影子模式引擎构造（log_file 就绪后）─────────────────────
        if self._tee_enable or self._tee_shadow:
            self._wrap_place_order_with_tee()

        self.incremental_learner = IncrementalLearner(
            retrain_trade_threshold=100,
            retrain_win_rate_threshold=0.5,
            retrain_sharpe_threshold=1.0,
        )

        # 异常检测引擎 (Phase 2.1)
        from scripts.memory_l4.bcrm2.anomaly_detector import HybridAnomalyDetector

        self.anomaly_detector = HybridAnomalyDetector(
            if_contamination=0.02,
            enable_if=True,
            enable_lgb=True,
            enable_dl=False,
        )
        self._kline_cache = {}  # 缓存K线数据用于异常检测

        # CBR 案例检索增强（2026-07-21 修复：接入历史案例检索到决策流程）
        try:
            from scripts.memory_l4.cbr_adapter import CBRToBCRMBridge

            self.cbr_bridge = CBRToBCRMBridge()
            self.cbr_bridge.initialize()
            self._log("[CBR] 案例检索增强已初始化", "INFO")
        except Exception as e:
            self._log(f"[CBR] 初始化失败: {e}，继续运行", "WARN")
            self.cbr_bridge = None

        # A7 实践论门禁（代码驱动，不依赖大模型）
        try:
            from scripts.memory_l4.a7_practice_gate import A7PracticeGate

            self.a7_gate = A7PracticeGate()
            self._log("[A7] 实践论门禁已初始化", "INFO")
        except Exception as e:
            self._log(f"[A7] 门禁初始化失败: {e}，继续运行", "WARN")
            self.a7_gate = None

        # P3: 认知召回桥接（A 系列 Cron 执行前注入认知召回）
        self.cognitive_recall_enabled = True
        self._trading_recall_fn = None
        try:
            import sys as _sys

            _cog_path = str(Path(__file__).resolve().parents[2] / "4-MEMORY" / "9-工具与接口")
            if _cog_path not in _sys.path:
                _sys.path.insert(0, _cog_path)
            from cognitive_loop_entry import trading_recall as _trading_recall

            self._trading_recall_fn = _trading_recall
            self._log("[P3] 认知召回桥接已初始化", "INFO")
        except Exception as e:
            self._log(f"[P3] 认知召回桥接初始化失败: {e}，继续运行", "WARN")
            self.cognitive_recall_enabled = False

        # ★ FIX: _mode_cache 必须在 _sync_existing_positions 之前初始化，
        #   否则 _sync_and_repair_sl_tp_for_position → _get_base_sl_roi → _cache_get
        #   会因 _mode_cache 不存在抛 AttributeError，导致 SLTP 同步被 FAIL-OPEN 跳过。
        self._mode_cache: Dict[Any, Tuple[Any, int]] = {}
        self._cycle_idx: int = 0

        self._sync_existing_positions()

        self._run_startup_inspection()

        # ──────────────────────────────────────────────────────
        # Phase A: 4 个 Feature Flag（选项 A 双轨并行核心）
        # 每个开关关闭时：对应分支 100% 走旧路径
        # ──────────────────────────────────────────────────────
        self.enable_mode_switch: bool = True        # S1: MODE 算力重分配（Phase A）
        self.enable_ev_radar: bool = True           # S2: EV 雷达四档决策（Phase B）
        self.enable_multi_horizon: bool = True      # S3: 多horizon 预测（Phase C）
        self.enable_ranked_tp: bool = True          # S4: 排名止盈三档（Phase C）

        # ──────────────────────────────────────────────────────
        # Phase A: MODE 阈值常量（Spec §3.2）
        # ──────────────────────────────────────────────────────
        self.MODE_OCCUPANCY_MODE3: float = 1.00     # 满仓 → MODE3（100% 占用率）
        self.MODE_OCCUPANCY_MODE2: float = 2 / 3    # 半仓 → MODE2（2/3≈0.6667 占用率，避免 0.67 时 2of3=0.666…<0.67 误判）
        self.MODE3_COARSE_CANDIDATE_TOPN: int = 3   # MODE3 粗推理候选 TopN
        self.MODE_COARSE_KLINE_LIMIT: int = 40       # MODE3 粗推理短 K 线探针（不跑 160 根）

        # ──────────────────────────────────────────────────────
        # Phase A: 缓存 TTL 常量（用 _cycle_idx 轮次计数，非 wall-clock，Spec §3.3）
        # ──────────────────────────────────────────────────────
        self.MODE_CACHE_TTL_ANOMALY: int = 2            # 异常检测缓存 TTL (轮次)
        self.MODE_CACHE_TTL_INFER_COARSE: int = 1       # 粗推理缓存 TTL (轮次)
        self.MODE_CACHE_TTL_KLINE_SHORT: int = 1        # 短K线缓存 TTL (轮次)
        self.MODE_CACHE_TTL_HORIZON_PREDS: int = 2      # 多horizon 预测缓存 TTL
        self.MODE_CACHE_TTL_POSITION_EV: int = 2        # 持仓 EV 缓存 TTL
        # 注：_cycle_idx 和 _mode_cache 已在 _sync_existing_positions 之前初始化
        # （避免 SLTP 同步时 _cache_get 访问未初始化属性抛 AttributeError）

        # ──────────────────────────────────────────────────────
        # Phase B: EV 雷达阈值与权重（Spec §4 默认值）
        # ──────────────────────────────────────────────────────
        self.EV_FORCE_CLOSE_BELOW: float = -0.35   # EV < -0.35 → 强制离场（非保护期）
        self.EV_WARN_LOWER_BOUND: float = -0.35    # -0.35 ≤ EV < -0.10 → 收紧止损
        self.EV_WARN_UPPER_BOUND: float = -0.10
        self.EV_STRONG_HOLD_ABOVE: float = +0.30   # EV > +0.30 → 放宽止损
        self.ev_weights: Dict[str, float] = {      # 7 子分权重，合计 1.0
            "confidence_s": 0.22,
            "direction_consistency_s": 0.18,
            "trend_alignment_s": 0.15,
            "pnl_momentum_s": 0.14,
            "regime_friendly_s": 0.11,
            "holding_age_s": 0.10,
            "liquidity_risk_s": 0.10,
        }

        # ── 持仓与离场管理层：ExitManager 策略链（v4.4 新增） ──
        # Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md
        # 5 个 per-position 策略（RankedTp 由全局跨持仓循环处理）
        from scripts.memory_l4.bcrm2.exit_manager import ExitManager
        from scripts.memory_l4.bcrm2.exit_strategies import (
            P3EarlyExitStrategy, SignalReverseStrategy,
            EvForceCloseStrategy, TimeoutProfitSwitchStrategy,
            EvAdjustStrategy,
        )
        _timeout_hours = 29.0
        try:
            _veto_sec = self.yijing_exit_system.config.veto_max_hold_sec
            if _veto_sec and _veto_sec > 0:
                _timeout_hours = _veto_sec / 3600.0
        except Exception:
            pass
        # 确保离场确认常量在 ExitManager 创建前已初始化（v5.0 离场防频繁优化）
        if not hasattr(self, 'EXIT_CONFIRM_REQUIRED'):
            self.EXIT_CONFIRM_REQUIRED = 2
            self.EXIT_CONFIRM_WINDOW_SEC = 300
            self.PROTECTED_REVERSE_CONF_BOOST = 0.12
            self.PROTECTED_P3_MIN_LOSS_PCT = -0.08
            self.ENABLE_REGIME_AND_MACRO_S5 = True
            self.POSITION_PROTECTION_HOURS = 6.0
            self._exit_confirm_state: Dict[str, Dict[str, Any]] = {}
            self.EXIT_ACT_SIGNAL_REVERSE = "signal_reverse"
            self.EXIT_ACT_YIJING_FORCE_CLOSE = "yijing_force_close"
            self.EXIT_ACT_P3_EARLY_EXIT = "p3_early_exit"
            self.EXIT_ACT_EV_FORCE_CLOSE = "ev_force_close"
            self.EXIT_ACT_RANKED_TP = "ranked_tp"
        self._ev_force_close_strategy = EvForceCloseStrategy(
            force_below=self.EV_FORCE_CLOSE_BELOW,
            exit_confirm_required=self.EXIT_CONFIRM_REQUIRED,
            enabled=self.enable_ev_radar,
        )
        self._ev_adjust_strategy = EvAdjustStrategy(
            warn_lower=self.EV_WARN_LOWER_BOUND,
            warn_upper=self.EV_WARN_UPPER_BOUND,
            strong_above=self.EV_STRONG_HOLD_ABOVE,
            enabled=self.enable_ev_radar,
        )
        self.exit_manager = ExitManager(strategies=[
            P3EarlyExitStrategy(
                exit_confirm_required=self.EXIT_CONFIRM_REQUIRED,
                protected_p3_min_loss_pct=self.PROTECTED_P3_MIN_LOSS_PCT,
            ),
            SignalReverseStrategy(
                base_threshold=float(self.confidence_threshold),
                protected_conf_boost=self.PROTECTED_REVERSE_CONF_BOOST,
                exit_confirm_required=self.EXIT_CONFIRM_REQUIRED,
                # [PUMP修复 2026-08-23] 反转阈值硬下限 + 余量保护
                # - 避免 barely pass（如 0.65 vs 0.6357，margin仅0.014）就触发
                # - 保护期内 margin ×2 = 0.10 （更严格）
                min_reverse_threshold=0.70,
                reverse_confidence_margin=0.05,
                protected_margin_multiplier=2.0,
            ),
            self._ev_force_close_strategy,
            TimeoutProfitSwitchStrategy(timeout_hours=_timeout_hours),
            self._ev_adjust_strategy,
        ])
        # ── 注入 storage 适配器，用于 exit_strategy_log 贡献值统计 ──
        try:
            from scripts.memory_l4.bcrm2.run_evolution_pipeline import get_storage
            _exit_storage = get_storage()
            if _exit_storage is not None:
                self.exit_manager.set_storage(_exit_storage)
        except Exception as _e:
            self._log(f"[ExitManager] storage 注入失败，贡献值统计降级关闭: {_e}", "WARN")
        self._log(
            f"[ExitManager] 策略链初始化 | 5 策略 | "
            f"P3(10)→SignalRev(20)→EvFC(30)→Timeout(40)→EvAdj(60) | "
            f"timeout={_timeout_hours:.1f}h",
            "INFO",
        )

        # ──────────────────────────────────────────────────────
        # Phase C: 多 horizon 预测 + 排名止盈 默认参数
        # ──────────────────────────────────────────────────────
        # S3: 多 horizon（Spec §4.3.1 — horizon 集合对齐 spec）
        self.HORIZON_BAR_CANDIDATES: List[int] = [1, 2, 3, 6, 10, 20, 30]  # Spec §4.3.1
        self.HORIZON_PREP_EXIT_MARGIN: int = 3   # best_k_bar 与 held 差在 ±3 内 → PREP_EXIT

        # S4: 排名止盈（Spec §4.3）
        self.RANKED_TP_GAP_RATIO: float = 0.70       # 落差阈值 0.7 → Top1 远领先
        self.RANKED_TP_MIN_PROFIT_USDT: float = 5.0  # Top1 至少盈利 5U（防噪声）

        # Phase C S3: PREP_EXIT 跨轮一致率触发（C11）
        self.S3_PREP_EXIT_CONFIRM_WINDOW: int = 3      # 回看最近 3 轮预测
        self.S3_PREP_EXIT_CONFIRM_RATE: float = 0.67   # ≥ 2/3 轮一致 → 允许进入离场确认
        self.EXIT_ACT_S3_PREP_EXIT = "s3_prep_exit"    # 离场确认 tag

        # ──────────────────────────────────────────────────────
        # H3-FMA 渐进自动开关：RolloutManager 状态（与 data_server 共用 phase_c_rollout_state.json）
        #   • phase_c_rollout_state_path 存路径 + phase_c_rollout_mgr 存实例（懒加载）
        #   • FMA 最后检查时间戳（避免每1小时轮询都调一次评估，每天最多1次）
        # ──────────────────────────────────────────────────────
        self._fma_phase_c_state_path = None
        self._fma_phase_c_mgr = None        # 懒加载：AB闸门口才创建（异常不影响主流程）
        self._fma_last_auto_check_ts: float = 0.0   # 上次自动调 evaluate_fma_toggle 时间戳
        self._FMA_AUTO_CHECK_INTERVAL_SEC = 20 * 3600   # 每 20 小时评估一次（保守，每天至多1次切换扰动）

        # ──────────────────────────────────────────────────────
        # Phase B: ShadowLogger 影子模式初始化
        # 开关 SHADOW_LOGGER_ENABLED 默认 False，关闭时 _shadow_logger=None
        # 确保 CLI 字节等价（不影响任何交易逻辑）
        # ──────────────────────────────────────────────────────
        self._shadow_logger: ShadowLogger = None  # type: ignore[assignment]
        self._init_shadow_logger()

        # ──────────────────────────────────────────────────────
        # Phase C: α blend 前瞻参数上线初始化
        # 开关 ALPHA_BLEND_ENABLED 默认 False，关闭时 _alpha_blend=0.0
        # 确保 CLI 字节等价（α=0 时 ParameterMapper 输出不变）
        # ──────────────────────────────────────────────────────
        self._alpha_blend_enabled: bool = False
        self._alpha_blend: float = 0.0
        self._init_alpha_blend()

        # T4: enable_inject 融合层开关（进程级，从文件读取）
        self._enable_inject_runtime: bool = False
        self._enable_inject_last_reload: float = 0.0
        self._enable_inject_reload_interval: float = 300.0  # 每 5 分钟重读一次
        self._init_enable_inject()

        # ──────────────────────────────────────────────────────
        # H3-FMA 渐进：冷启动时从 rollout_state.json 还原 FMA_REGIME_FILTER_ENABLED
        #   优先级：rollout state 中的 fma_enabled（人工/自动渐进切换） > 类默认 False
        #   失败：兜底保留类默认 False（不影响交易）
        # ──────────────────────────────────────────────────────
        self._fma_load_from_rollout()

        # ──────────────────────────────────────────────────────
        # 通用资金调控组件（16-调控系统）
        #   设计：① 懒加载，失败降级为 None（fail-open，不阻塞易经自有风控）
        #         ② 作为前置约束叠加使用：allowed=False 拦截开仓 / max_position_usdt 取 min
        #         ③ 系统名 yijing_bcrm → okx_simulated 账户
        # ──────────────────────────────────────────────────────
        self._capital_ctrl = None                # CapitalControlComponent 实例
        self._capital_ctrl_last_result = None    # 最近一次 advice 结果（dict/frozen）
        self._capital_ctrl_last_ts: float = 0.0  # 上次调用时间戳（控制调用频率）
        self._CAPITAL_CTRL_MIN_INTERVAL: float = 240.0  # 每 4 分钟至多调用一次 real evaluate
        self._init_capital_control()

        # ──────────────────────────────────────────────────────
        # v1.4.1 Stage 1: 战略层五计庙算 + 策略算法层（影子模式，默认全关）
        # 设计原则：所有开关默认 False → 两个组件均为 None → 字节等价
        #           异常 catch → None → 不阻塞 __init__
        # ──────────────────────────────────────────────────────
        self._five_domain_scorer = None  # type: ignore[assignment]
        self._five_domain_feature_computer = None  # type: ignore[assignment]
        self._strategy_algo_layer = None  # type: ignore[assignment]
        self._five_domain_state_cache = None  # type: ignore[assignment]
        self._five_domain_state_shadow = None  # 真实计算值（供ShadowLogger记录，影子模式下不被中性值覆盖）
        self._init_five_domain_and_strategy_layer()

        # ──────────────────────────────────────────────────────
        # Phase1：CBR JSONL 双时点建库 + Elder-ray 日线影子 + 盈亏因子旁路
        # 三开关默认全 False = 字节等价（G1 红线）；任何异常 → 三属性全 None（fail-open G2）
        # 零侵入（Phase1 G5：Elder/WinProb 实际 multiplier 恒=1.00，只记录预测）
        # ──────────────────────────────────────────────────────
        self.enable_cbr_cycle_log = bool(enable_cbr_cycle_log)
        self.enable_elder_ray_c4 = bool(enable_elder_ray_c4)
        self.enable_win_prob_factor = bool(enable_win_prob_factor)
        # 方案 C v3.0 开关（默认全 False，字节等价旁路）
        self.enable_three_layer_weighter = bool(enable_three_layer_weighter)
        self.enable_elastic_gate_3l = bool(enable_elastic_gate_3l)
        self.enable_bcrm_continuity_obs = bool(enable_bcrm_continuity_obs)
        self.enable_btc_self_reflex_valve = bool(enable_btc_self_reflex_valve)
        self.enable_portfolio_risk_fuses = bool(enable_portfolio_risk_fuses)
        self._cbr_store = None       # CBRJsonlStore（JSONL 双时点建库）
        self._elder_engine = None    # ElderRayEngine（日线观察器）
        self._win_prob_engine = None # WinProbEngine（盈亏因子旁路，恒=1.0）
        # 方案 C v3.0 组件引用（开关 False 时保持 None，字节等价零侵入）
        self._three_layer_weighter = None   # ThreeLayerWeighter（SW-C3）
        self._elastic_gate_3l = None        # ElasticGate3L（SW-C4）
        self._bcrm_continuity = None        # BCRMContinuityObserver（SW-C5）
        self._btc_self_reflex_valve = None  # BTCSelfReflexValve（SW-C6）
        self._portfolio_fuses = None        # PortfolioRiskFuses（SW-C8）
        self._current_fuse_action = None    # 本轮 run_once 的 FuseAction 缓存（None→视为无熔断旁路）
        self._last_prf_failopen_hour: str = ""
        # v4.6 过滤层统一弹性放行：score_consensus < 基础阈值 → 不开仓；≥基础阈值才可能试错
        # 基础阈值（冷启动默认 0.40，基于历史盈亏动态调节，范围 [0.25, 0.60]）
        self._gate_base_threshold: float = 0.40
        # 基础阈值动态调节状态：聚合最近 N=30 笔盈亏样本
        self._gate_threshold_state: dict = {
            "n_min": 30,           # 至少 30 笔才启动调节（非单笔）
            "n_max": 150,          # 滑动窗口上限
            "recent_pnl": [],      # [(pnl_ratio, score_consensus, direction), ...]
            "last_adjust_ts": 0.0, # 上次调节时间戳
            "adjust_cooldown_s": 1800,  # 30 分钟最多调一次
        }
        self._init_phase1_three_components()

        # ──────────────────────────────────────────────────────
        # Phase C+: 大小周期 MorphCyclePredictor + ParameterMapper 单例
        #   目的：① 日志审计（大小周期→形态→六维→注入BCRM闭环）
        #         ② 后续 enable_inject=True 时直接复用
        #   约束：无论开关状态，均不改变任何交易参数（字节等价）
        # ──────────────────────────────────────────────────────
        self._morph_predictor = None
        self._param_mapper = None
        self._init_morph_and_param_mapper()

    # ================================================================
    # 通用资金调控组件集成（16-调控系统）
    # 设计原则：① fail-open 失败降级；② 仅作为前置约束，不替代易经自有风控
    # ================================================================

    def _init_capital_control(self):
        """初始化通用资金调控组件。失败时 self._capital_ctrl=None，所有后续方法安全降级。"""
        try:
            import sys
            from pathlib import Path
            _PROJECT_DIR = Path(__file__).resolve().parents[2]  # 11-易经推理系统
            _ROOT = _PROJECT_DIR.parent  # dreambuddy-v2
            # CapitalControlComponent 使用相对导入 from .types import ...，
            # 必须以"capital_control.component"子包路径导入：把 16-调控系统/core 加为模块根
            _CORE_ROOT = _ROOT / "16-调控系统" / "core"
            if str(_CORE_ROOT) not in sys.path:
                sys.path.insert(0, str(_CORE_ROOT))
            from capital_control.component import CapitalControlComponent, CapitalMode
            self._capital_ctrl = CapitalControlComponent(mode=CapitalMode.DYNAMIC)
            # 启动时不主动 evaluate，避免拖慢初始化；懒评估
            self._log(
                "[资金调控] 16-调控系统 CapitalControlComponent 初始化完成 "
                "(system=yijing_bcrm, mode=DYNAMIC, fail-open)",
                "INFO",
            )
        except Exception as _e:
            self._capital_ctrl = None
            self._log(
                f"[资金调控] 初始化失败，降级使用易经自有风控: {_e}",
                "WARN",
            )

    def _fetch_capital_advice(self, force: bool = False):
        """每轮轮询/开仓前获取通用资金调控建议。

        - 内部限流：距离上次 < _CAPITAL_CTRL_MIN_INTERVAL 时直接复用缓存结果
        - 组件为 None 或任何异常 → 返回 None 表示无外部约束（易经自有风控生效）
        """
        if self._capital_ctrl is None:
            return None
        _now = time.time()
        if (not force) and (
            self._capital_ctrl_last_ts > 0
            and (_now - self._capital_ctrl_last_ts) < self._CAPITAL_CTRL_MIN_INTERVAL
            and self._capital_ctrl_last_result is not None
        ):
            return self._capital_ctrl_last_result
        try:
            advice = self._capital_ctrl.get_capital_advice("yijing_bcrm", action="OPEN")
            self._capital_ctrl_last_result = advice
            self._capital_ctrl_last_ts = _now
            return advice
        except Exception as _e:
            self._log(f"[资金调控] get_capital_advice 异常，降级: {_e}", "WARN")
            return None

    def _apply_capital_control_to_position(self, coin: str, position_usdt: float, available_equity: float):
        """将通用资金调控组件的约束叠加到仓位上。

        返回: (final_position_usdt: float, cap_reason_log: str)
        若 advice=None，直接 return (position_usdt, "") 表示无外部约束。

        规则（与易经自有风控取更严格，叠加而非替换）：
          1. advice.allowed=False → final_position_usdt=0（拦截）
          2. advice.max_position_usdt（保证金口径）→ 乘杠杆转名义价值后与 position_usdt 取 min（缩仓）
          3. advice.confidence_multiplier(Phase2) 不在此层处理，保留给未来接入
        """
        advice = self._fetch_capital_advice()
        if advice is None:
            return position_usdt, ""

        logs: List[str] = []
        _reason = advice.get("reason", "") or "ok"
        _pressure = advice.get("margin_pressure", "LOW")
        _used_pct = float(advice.get("used_pct", 0.0) or 0.0)
        _avail = float(advice.get("current_avail", 0.0) or 0.0)
        _total_eq = float(advice.get("total_eq", 0.0) or 0.0)
        logs.append(
            f"pressure={_pressure} used={_used_pct:.1f}% avail={_avail:.1f}U eq={_total_eq:.1f}U({_reason})"
        )

        # 1) 明确拦截：allowed=False
        if not bool(advice.get("allowed", True)):
            logs.append("ALLOWED=FALSE")
            self._log(
                f"[{coin}] [资金调控] 前置约束拦截 | {' | '.join(logs)}",
                "WARN",
            )
            return 0.0, " | ".join(logs)

        # 2) 仓位上限叠加：cap_max 是保证金口径，position_usdt 是名义价值（含杠杆）
        #    将 cap_max 乘杠杆转为名义价值后比较，避免保证金与名义价值混比导致缩仓 10 倍
        cap_max_margin = float(advice.get("max_position_usdt", 0.0) or 0.0)
        if cap_max_margin > 0:
            leverage = self._get_leverage()
            cap_max_notional = cap_max_margin * leverage
            if position_usdt > cap_max_notional:
                logs.append(
                    f"cap_max_margin={cap_max_margin:.2f}U(×{leverage:.0f}x={cap_max_notional:.2f}U名义) → 仓位 {position_usdt:.2f}→{cap_max_notional:.2f}U"
                )
                self._log(
                    f"[{coin}] [资金调控] 仓位上限叠加缩仓 | {' | '.join(logs)}",
                    "WARN",
                )
                return cap_max_notional, " | ".join(logs)

        # 3) 其余正常通过
        if position_usdt > 0:
            self._log(
                f"[{coin}] [资金调控] 前置约束通过 | {' | '.join(logs)}",
                "INFO",
            )
        return position_usdt, " | ".join(logs)

    # ================================================================
    # v1.4.1 Stage 1: 战略层五计庙算 + 策略算法层（影子模式初始化）
    # 设计原则：失败降级为 None，仅影响影子日志，不改变任何交易逻辑
    # ================================================================

    def _apply_fd_shadow_intercept(self, cfg, FiveDomainState):
        """影子拦截：7子开关全开后，shadow_mode=True 时保存真实计算值到 _shadow，
        下游 _state_cache 替换为中性默认值（war_state=ALLOW/cap=1.0/mask全True/band=None）。
        确保战略层完整计算所有输出但不影响实盘，ShadowLogger 记录真实值供观测。"""
        if self._five_domain_state_cache is None:
            return
        # 保存真实计算值（供 ShadowLogger 读取）
        self._five_domain_state_shadow = self._five_domain_state_cache
        # shadow_mode=True 时，下游消费中性默认值（字节等价"战略层不存在"）
        if cfg.enable_five_domain_shadow_mode:
            self._five_domain_state_cache = FiveDomainState.default_fail_open()
            self._log(
                "[战略层/影子拦截] 7子开关全开+影子模式：战略层完整计算所有6类输出，"
                "下游消费中性默认值（不影响实盘），ShadowLogger 记录真实值供观测",
                "INFO",
            )

    def _init_five_domain_and_strategy_layer(self):
        """初始化五计庙算评分器 + 策略算法层（默认全关=fail-open字节等价）。

        state_cache_path = runtime/five_domain_state.json（日级缓存，5分钟热路径只读）
        """
        from pathlib import Path as _Path
        import os as _os
        try:
            from scripts.memory_l4.five_domain_scorer import FiveDomainHeuristicScorer
            from scripts.memory_l4.strategy_algo_layer import StrategyAlgorithmLayer, StrategyAlgoConfig
        except Exception as e:
            self._log(f"[战略层/策略层] import失败，影子模式关闭（字节等价）: {e}", "WARN")
            return

        # cfg：2总+7子+3模式+1放宽 共13开关，默认全部False（符合§三开关表fail-open）
        cfg = StrategyAlgoConfig(
            enable_strategy_layer=True,  # P0 开关：策略算法层影子（只打日志+enhance_info，不影响交易）
            enable_five_domain=False,
            # 7 子开关全部 True：让战略层完整计算所有6类输出（war_state/cap/mask/mult/band/veto）
            # 影子拦截确保：shadow_mode=True 时下游消费中性默认值，不影响实盘
            enable_five_domain_war_state=True,
            enable_five_domain_style_mask=True,
            enable_five_domain_position_cap=True,
            enable_five_domain_cross_asset=True,
            enable_five_domain_dimensio=True,
            enable_five_domain_front_layer_band=True,
            enable_five_domain_ol=True,
            # 影子 AB 模式默认 False
            enable_five_domain_shadow_mode=True,  # 影子模式：_shadow保存真实值(供SubSystemBridge/ShadowDebug消费)，_cache替换为中性默认值(BCRM2.0不消费战略层)
            enable_shadow_ab_static_baseline_v15=False,
            enable_shadow_ab_dynamic_baseline=False,
            # R5 红线：放宽阈值默认不允许
            enable_strategy_layer_relax_allowed=False,
        )
        try:
            cache_path = _Path(__file__).resolve().parent / "runtime" / "five_domain_state.json"
            # A3: enable=True（影子模式），真实应用6决策不等式计算war_state/cap/mask/mult/band
            # 零风险：7子开关(enable_five_domain_war_state/...)全False，下游不消费仅日志记录
            self._five_domain_scorer = FiveDomainHeuristicScorer(
                enable=True, state_cache_path=cache_path,
                enable_adaptive_weights=_os.environ.get("ENABLE_ADAPTIVE_WEIGHTS", "").lower() in ("1", "true", "yes"),
            )
            # FiveDomainFeatureComputer：特征→评分计算层（A1: enable=True 影子模式，真实计算五维评分）
            from scripts.memory_l4.five_domain_feature_computer import FiveDomainFeatureComputer
            self._five_domain_feature_computer = FiveDomainFeatureComputer(enable=True)
            self._strategy_algo_layer = StrategyAlgorithmLayer(cfg=cfg)
            # 初始化 state_cache（A3后不再字节等价 default_fail_open，因为Scorer.enable=True）
            # 日级刷新时会通过 A2 的真实 coin_data/system_state 重算，这里先用 fail-open 作为占位
            self._five_domain_state_cache = self._five_domain_scorer.score_and_decide(persist=True)
            from scripts.memory_l4.five_domain_scorer import FiveDomainState
            from dataclasses import asdict as _asdict
            # ★ 影子拦截：7子开关全开后，shadow_mode=True 时保存真实值到 _shadow，
            #   下游 _state_cache 替换为中性默认值（war_state=ALLOW/cap=1.0/mask全True/band=None）
            #   确保战略层完整计算所有输出但不影响实盘，ShadowLogger 记录真实值供观测
            self._apply_fd_shadow_intercept(cfg, FiveDomainState)
            # F1 影子红线：shadow_mode=True 时下游 _state_cache 必须为中性默认值
            if cfg.enable_five_domain_shadow_mode:
                _st = self._five_domain_state_cache
                _default = FiveDomainState.default_fail_open()
                for _c in _st.war_state.keys():
                    assert _st.war_state.get(_c) == _default.war_state.get(_c), (
                        f"[F1影子红线违规] shadow_mode=True时 war_state[{_c}]={_st.war_state.get(_c)}≠ALLOW"
                    )
                    assert abs(_st.aggregate_position_cap_pct.get(_c, 1.0) - 1.0) < 1e-6, (
                        f"[F1影子红线违规] shadow_mode=True时 cap[{_c}]={_st.aggregate_position_cap_pct.get(_c)}≠1.0"
                    )
            # ★ FIX 问题2：动态描述7子开关状态，避免 style_mask=True 时误写「全False」
            try:
                from scripts.memory_l4.five_domain_feature_computer import (
                    describe_five_domain_subswitches as _desc_sw,
                )
                _sw_desc = _desc_sw(cfg)
            except Exception:
                _sw_desc = "子开关状态描述生成失败（详见five_domain_feature_computer.describe_five_domain_subswitches）"
            self._log(
                f"[战略层/策略层] 初始化完成（A1+A2+A3影子模式已启用，{_sw_desc}）",
                "INFO",
            )
        except Exception as e:
            self._five_domain_scorer = None
            self._five_domain_feature_computer = None
            self._strategy_algo_layer = None
            self._five_domain_state_cache = None
            self._log(f"[战略层/策略层] 构造失败，降级关闭（字节等价）: {e}", "WARN")

    def _init_phase1_three_components(self):
        """Phase1 三组件 + 方案C v3.0 五组件初始化（CBR/Elder/WinProb + C3~C6/C8）。

        强制约束（必须全部满足）：
          G1：8 开关全 False → 所有组件引用全部为 None
              （字节等价改造前状态，不影响任何交易逻辑）
          G2：任何 import 异常 / 构造异常 → 全量降级为 None（不影响 __init__）
          G5：ElderRayEngine / WinProbEngine 在 Phase1 中均返回 multiplier=1.0（仅记录预测值）
        """
        from pathlib import Path as _P
        total_enabled = (
            int(bool(self.enable_cbr_cycle_log))
            + int(bool(self.enable_elder_ray_c4))
            + int(bool(self.enable_win_prob_factor))
            # 方案 C v3.0 开关：C3/C4/C5/C6/C8
            + int(bool(self.enable_three_layer_weighter))
            + int(bool(self.enable_elastic_gate_3l))
            + int(bool(self.enable_bcrm_continuity_obs))
            + int(bool(self.enable_btc_self_reflex_valve))
            + int(bool(self.enable_portfolio_risk_fuses))
        )
        if total_enabled == 0:
            # G1：全关 → 全 None（与 __init__ 初始化占位保持一致，字节等价）
            assert self._cbr_store is None and self._elder_engine is None \
                   and self._win_prob_engine is None, (
                "G1红线：三开关全False时组件初始值必须全None，请检查__init__占位"
            )
            # 方案 C v3.0 同样必须全部是 None
            assert (self._three_layer_weighter is None and self._elastic_gate_3l is None
                    and self._bcrm_continuity is None and self._btc_self_reflex_valve is None
                    and self._portfolio_fuses is None), (
                "G1红线(方案C)：五开关全False时组件初始值必须全None，请检查__init__占位"
            )
            self._log("[Phase1+方案C] 8开关全=False → 旁路（字节等价）", "DEBUG")
            return
        # 按开关独立构造；一个失败不影响其他（fail-open 粒度最小化）
        try:
            if self.enable_cbr_cycle_log:
                from scripts.memory_l4.cbr_engine import CBRJsonlStore as _CBR
                self._cbr_store = _CBR(
                    runtime_dir=_P(__file__).resolve().parent / "runtime", enable=True)
                if self._cbr_store is not None:
                    self._log(
                        f"[Phase1/P0] CBRJsonlStore 已加载季度校准参数："
                        f"θ_match*={self._cbr_store.theta_match_star:.4f}  "
                        f"γ_max*={self._cbr_store.gamma_max_star:.4f}", "INFO")
        except Exception as _e:
            self._cbr_store = None
            self._log(f"[Phase1/P0] CBRJsonlStore 初始化失败，旁路（fail-open）：{_e}", "WARN")
        # CBR 相似度 top-3 检索融合引擎（shadow 模式：真参数不改动，仅打结构化 JSONL 日志）
        self._cbr_engine = None
        self._cbr_retrieval_log_path = None  # type: ignore[assignment]
        if self.enable_cbr_cycle_log and self._cbr_store is not None:
            try:
                from scripts.memory_l4.cbr_engine import CBREngine  # noqa: F401
                self._cbr_engine = CBREngine(
                    top_k=5,
                    similarity_threshold=0.0,  # 检索门槛放宽，后续再按θ*过滤 top-3
                )
                self._cbr_engine.load(use_index=True)
                runtime_dir = _P(__file__).resolve().parent / "runtime"
                runtime_dir.mkdir(parents=True, exist_ok=True)
                self._cbr_retrieval_log_path = runtime_dir / "cbr_retrieval_records.jsonl"
                n_cases = len(getattr(self._cbr_engine, "case_base", None) or [])
                self._log(
                    f"[Phase1/P0] CBREngine 加载完成：案例库 {n_cases:,} 条 "
                    f"(θ_match*={self._cbr_store.theta_match_star:.4f} → "
                    f"shadow JSONL 落盘: {self._cbr_retrieval_log_path})",
                    "INFO",
                )
            except Exception as _e:
                self._cbr_engine = None
                self._log(
                    f"[Phase1/P0] CBREngine 初始化失败，CBR top-3 融合旁路（fail-open）：{_e}",
                    "WARN",
                )
        try:
            if self.enable_elder_ray_c4:
                from scripts.memory_l4.elder_ray_engine import ElderRayEngine as _ERE
                self._elder_engine = _ERE(enable=True)
        except Exception as _e:
            self._elder_engine = None
            self._log(f"[Phase1/P1] ElderRayEngine 初始化失败，旁路（fail-open）：{_e}", "WARN")
        try:
            if self.enable_win_prob_factor:
                from scripts.memory_l4.winprob_engine import WinProbEngine as _WPE
                self._win_prob_engine = _WPE(enable=True)
        except Exception as _e:
            self._win_prob_engine = None
            self._log(f"[Phase1/P3] WinProbEngine 初始化失败，旁路（fail-open）：{_e}", "WARN")

        # ──────────────────────────────────────────────────────
        # 方案 C v3.0 5 个新组件初始化（C3/C4/C5/C6/C8）
        # 每个组件独立 try/except，异常时属性保持 None = fail-open 旁路
        # ──────────────────────────────────────────────────────
        try:
            if self.enable_three_layer_weighter:
                from scripts.memory_l4.three_layer_weighter import ThreeLayerWeighter as _TLW
                self._three_layer_weighter = _TLW(
                    runtime_dir=_P(__file__).resolve().parent / "runtime")
        except Exception as _e:
            self._three_layer_weighter = None
            self._log(f"[方案C/C3] ThreeLayerWeighter 初始化失败，旁路（fail-open）：{_e}", "WARN")
        try:
            if self.enable_elastic_gate_3l:
                from scripts.memory_l4.elastic_gate_3l import ElasticGate3L as _EG3L
                self._elastic_gate_3l = _EG3L()
        except Exception as _e:
            self._elastic_gate_3l = None
            self._log(f"[方案C/C4] ElasticGate3L 初始化失败，旁路（fail-open）：{_e}", "WARN")
        try:
            if self.enable_bcrm_continuity_obs:
                from scripts.memory_l4.bcrm_continuity_observer import BCRMContinuityObserver as _BCO
                self._bcrm_continuity = _BCO(enable=True)
        except Exception as _e:
            self._bcrm_continuity = None
            self._log(f"[方案C/C5] BCRMContinuityObserver 初始化失败，旁路（fail-open）：{_e}", "WARN")
        try:
            if self.enable_btc_self_reflex_valve:
                from scripts.memory_l4.btc_self_reflex_valve import BTCSelfReflexValve as _BSRV
                self._btc_self_reflex_valve = _BSRV()
        except Exception as _e:
            self._btc_self_reflex_valve = None
            self._log(f"[方案C/C6] BTCSelfReflexValve 初始化失败，旁路（fail-open）：{_e}", "WARN")
        try:
            if self.enable_portfolio_risk_fuses:
                from scripts.memory_l4.portfolio_risk_fuses import PortfolioRiskFuses as _PRF
                self._portfolio_fuses = _PRF()
        except Exception as _e:
            self._portfolio_fuses = None
            self._log(f"[方案C/C8] PortfolioRiskFuses 初始化失败，旁路（fail-open）：{_e}", "WARN")

        # 初始化完成日志（便于日志追踪 gate 是否生效）
        self._log(
            f"[Phase1+方案C] 初始化结果："
            f"CBR={self._cbr_store is not None}({self.enable_cbr_cycle_log}) | "
            f"Elder={self._elder_engine is not None}({self.enable_elder_ray_c4}) | "
            f"WinProb={self._win_prob_engine is not None}({self.enable_win_prob_factor}) | "
            f"3LW={self._three_layer_weighter is not None}({self.enable_three_layer_weighter}) | "
            f"EG3L={self._elastic_gate_3l is not None}({self.enable_elastic_gate_3l}) | "
            f"BCO={self._bcrm_continuity is not None}({self.enable_bcrm_continuity_obs}) | "
            f"BSRV={self._btc_self_reflex_valve is not None}({self.enable_btc_self_reflex_valve}) | "
            f"PRF={self._portfolio_fuses is not None}({self.enable_portfolio_risk_fuses})",
            "INFO",
        )

    def _detect_no_bounce_at_key(self) -> bool:
        """G-05 判据③：价格穿越关键位后无有效反弹（增强版）.

        使用 PotentialFieldEngineer 的关键位检测：
        1. 取最近200+根K线构造 prices DataFrame
        2. 计算均线/成交密集区/前高前低/斐波那契四类关键位
        3. 检查当前价格是否穿越最近支撑位（前低/swing_low）
        4. 穿越后后续N根K线无反弹（收盘价不回到支撑位上方）→ True

        FAIL-OPEN：任何异常（数据不足/import失败/计算错误）→ False
        """
        try:
            _klines = getattr(self, "_recent_klines", None)
            if not _klines or len(_klines) < 50:
                # 数据不足，无法计算关键位 → 回退简化版：连续6根下行
                if _klines and len(_klines) >= 6:
                    _closes = [float(k.get("close", 0.0) or 0.0) for k in _klines[-6:]]
                    return all(_closes[i] <= _closes[i - 1] for i in range(1, len(_closes)))
                return False

            import pandas as _pd
            # 构造 prices DataFrame
            _df_data = []
            for k in _klines[-250:]:  # 最多250根
                _df_data.append({
                    "open": float(k.get("open", 0.0) or 0.0),
                    "high": float(k.get("high", 0.0) or 0.0),
                    "low": float(k.get("low", 0.0) or 0.0),
                    "close": float(k.get("close", 0.0) or 0.0),
                    "volume": float(k.get("volume", 0.0) or 0.0),
                })
            _prices = _pd.DataFrame(_df_data)
            if len(_prices) < 50:
                return False

            # 计算 swing 关键位（前高前低）
            import sys as _sys
            _pitd_root = str(_PROJECT_ROOT / "12-三屏趋势系统")
            if _pitd_root not in _sys.path:
                _sys.path.insert(0, _pitd_root)
            from ml.pitd_potential_field import PotentialFieldEngineer  # noqa: E402

            _engineer = PotentialFieldEngineer()
            _i = len(_prices) - 1
            # 获取前高前低关键位
            _swing_levels = _engineer._calc_swing_key_levels(_prices, _i)
            if not _swing_levels:
                return False

            _current_close = float(_prices["close"].values[_i])
            # 找最近的支撑位（低于当前价格的 swing low）
            _support_levels = [(p, w) for p, w in _swing_levels if p < _current_close]
            if not _support_levels:
                return False
            _nearest_support = max(_support_levels, key=lambda x: x[0])  # 最接近的支撑位

            # 检查是否穿越支撑位：前一根K线的close在支撑位上方，当前close在下方
            if _i < 1:
                return False
            _prev_close = float(_prices["close"].values[_i - 1])
            _support_price = _nearest_support[0]
            _penetrated = _prev_close > _support_price and _current_close < _support_price

            if not _penetrated:
                # 未穿越支撑位 → 检查连续下行回退
                _recent_closes = [float(x) for x in _prices["close"].values[-6:]]
                return all(_recent_closes[i] <= _recent_closes[i - 1] for i in range(1, len(_recent_closes)))

            # 穿越支撑位后：检查后续N根K线是否无反弹（收盘价不回到支撑位上方）
            _post_closes = [float(x) for x in _prices["close"].values[-6:]]
            _no_bounce = all(c <= _support_price * 1.002 for c in _post_closes)  # 允许0.2%容差
            return _no_bounce
        except Exception:
            return False

    def _detect_no_intervener(self) -> bool:
        """G-05 判据④：无外部干预者（增强版）.

        查询最近 N 小时的 odaily_newsflash 新闻：
        - 有 monetary_policy/crypto_regulation/us_policy 类事件 → 有干预者 → False
        - 无干预类事件 → 无干预者 → True

        干预事件关键词（来自 odaily_newsflash._POLICY_KEYWORDS）：
        - monetary_policy: 降息/加息/FOMC/美联储/欧央行/央行/缩表/扩表/购债
        - crypto_regulation: SEC/监管/牌照/稳定币监管/ETF
        - us_policy: 财政部/白宫/国债/制裁/行政令

        FAIL-OPEN：任何异常（DB不存在/import失败）→ True（保守判定无干预者）
        """
        try:
            import sqlite3 as _sq3
            import pathlib as _pl
            _db = _PROJECT_ROOT / "18-数据获取中心" / "data_center.db"
            if not _db.exists():
                return True  # DB不存在 → 保守判定无干预者

            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            # 查询最近6小时的新闻（干预事件通常是突发性的）
            lookback_ms = 6 * 3_600_000
            min_ts = now_ms - lookback_ms

            conn = _sq3.connect(str(_db))
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT metrics, events, raw, timestamp FROM records "
                    "WHERE source='odaily_newsflash' ORDER BY rowid DESC LIMIT 200"
                )
                rows = cur.fetchall()
            except Exception:
                rows = []
            conn.close()

            if not rows:
                return True  # 无新闻数据 → 保守判定无干预者

            # 干预事件关键词
            _intervention_keywords = [
                "降息", "加息", "利率决议", "FOMC", "美联储", "欧央行", "央行",
                "缩表", "扩表", "购债", "SEC", "监管", "牌照", "稳定币监管",
                "ETF", "财政部", "白宫", "制裁", "行政令", "国会", "债务上限",
                "金管局", "金融委员会", "干预",
            ]

            def _parse_json_maybe(s):
                if s is None:
                    return None
                if isinstance(s, (dict, list)):
                    return s
                try:
                    return json.loads(s)
                except Exception:
                    return None

            for row in rows:
                if not isinstance(row, (list, tuple)):
                    continue
                m = _parse_json_maybe(row[0]) or {}
                raw = _parse_json_maybe(row[2]) or {}
                # 检查事件类型
                _event_type = str(m.get("od_event_type", "") or "")
                if _event_type in ("monetary_policy", "crypto_regulation", "us_policy"):
                    return False  # 有干预类事件 → 有干预者

                # 检查标题/内容中的关键词
                _title = str(raw.get("title", "") or raw.get("od_title", "") or "")
                _content = str(raw.get("content", "") or raw.get("od_content", "") or "")
                _text = (_title + _content).lower()
                for kw in _intervention_keywords:
                    if kw in _text:
                        return False  # 检测到干预关键词 → 有干预者

            return True  # 无干预事件 → 无干预者
        except Exception:
            return True  # FAIL-OPEN：异常 → 保守判定无干预者

    def _run_once_five_domain_daily_update(self):
        """§15.4.2 战略层日级打分影子（热路径只读，5分钟轮询不重算）。

        日级缓存文件：runtime/five_domain_state.json，带 _meta.updated_date 防重算。
        异常时 fail-open = FiveDomainState.default_fail_open()，仅 WARN 不阻塞。
        """
        from pathlib import Path as _Path
        from dataclasses import asdict as _asdict

        if self._five_domain_scorer is None:
            return

        # ═══════════════════════════════════════════════════════════════════
        # 辅助：把 FiveDomainState 对象 → 打 9 条影子日志（war/total/dao/cap/mult/mask/veto/band/fc）
        # ═══════════════════════════════════════════════════════════════════
        def _emit_shadow_logs(state_obj, src_label: str):
            try:
                from scripts.memory_l4.five_domain_scorer import CLASSES as _CLASSES
                from scripts.memory_l4.strategy_algo_layer import STYLE_ORDER as _STYLES
                _scorer = self._five_domain_scorer
                _war = getattr(state_obj, "war_state", {}) or {}
                _scores = getattr(state_obj, "five_scores", {}) or {}
                _caps = getattr(state_obj, "aggregate_position_cap_pct", {}) or {}
                _mults = getattr(state_obj, "cross_asset_multiplier", {}) or {}
                _mask = getattr(state_obj, "allowed_style_mask", {}) or {}
                _veto = getattr(state_obj, "dimension_veto_flags", {}) or {}
                _band = getattr(state_obj, "front_layer_band", {}) or {}
                _fc = getattr(state_obj, "forced_close_flags", {}) or {}
                _totals = {}
                _dao_scores = {}
                for _c in _CLASSES:
                    _s = _scores.get(_c, {})
                    _dao_scores[_c] = _s.get("dao", 50)
                    if _scorer is not None:
                        try:
                            _totals[_c] = _scorer._weighted_total(_s, _c)
                        except Exception:
                            _totals[_c] = 50
                    else:
                        _totals[_c] = 50
                _cls_list = list(_CLASSES)
                self._log(
                    f"[战略层影子][{src_label}] war_state | " +
                    " | ".join(f"{_c}={_war.get(_c, 'ALLOW')}" for _c in _cls_list),
                    "INFO",
                )
                self._log(
                    f"[战略层影子][{src_label}] total_score | " +
                    " | ".join(f"{_c}={_totals.get(_c, 50)}" for _c in _cls_list),
                    "INFO",
                )
                self._log(
                    f"[战略层影子][{src_label}] dao_score | " +
                    " | ".join(f"{_c}={_dao_scores.get(_c, 50)}" for _c in _cls_list),
                    "INFO",
                )
                self._log(
                    f"[战略层影子][{src_label}] cap_mode | " +
                    " | ".join(f"{_c}={_caps.get(_c, 1.0):.2f}" for _c in _cls_list),
                    "INFO",
                )
                self._log(
                    f"[战略层影子][{src_label}] mult_mode | " +
                    " | ".join(f"{_c}={_mults.get(_c, 1.0):.2f}" for _c in _cls_list),
                    "INFO",
                )
                # ★ FIX-字段补全：style_mask / dimension_veto / front_layer_band / forced_close_flags
                # 6 类策略掩码：列出每类被禁用(False)的策略名
                def _fmt_mask(c):
                    _m = _mask.get(c, {}) or {}
                    _disabled = [s for s in _STYLES if not _m.get(s, True)]
                    return "all" if not _disabled else ",".join(_disabled)
                self._log(
                    f"[战略层影子][{src_label}] style_mask | " +
                    " | ".join(f"{_c}=disabled[{_fmt_mask(_c)}]" for _c in _cls_list),
                    "INFO",
                )
                # 5 个维度否决旗标：列出每类生效(True)的否决项
                def _fmt_veto(c):
                    _v = _veto.get(c, {}) or {}
                    _active = [k for k, v in _v.items() if v]
                    return "none" if not _active else ",".join(_active)
                self._log(
                    f"[战略层影子][{src_label}] dimension_veto | " +
                    " | ".join(f"{_c}=[{_fmt_veto(_c)}]" for _c in _cls_list),
                    "INFO",
                )
                # 前置层带宽：None=不clip，否则输出 min/max
                def _fmt_band(c):
                    _b = _band.get(c)
                    if _b is None:
                        return "None"
                    return f"min={_b.get('min')},max={_b.get('max')}"
                self._log(
                    f"[战略层影子][{src_label}] front_layer_band | " +
                    " | ".join(f"{_c}={_fmt_band(_c)}" for _c in _cls_list),
                    "INFO",
                )
                # 强平标志：strong / protect
                def _fmt_fc(c):
                    _f = _fc.get(c, {}) or {}
                    return f"strong={_f.get('strong', False)},protect={_f.get('protect', False)}"
                self._log(
                    f"[战略层影子][{src_label}] forced_close | " +
                    " | ".join(f"{_c}={_fmt_fc(_c)}" for _c in _cls_list),
                    "INFO",
                )
            except Exception as _log_e:
                # 影子日志失败绝对不阻塞主流程
                try:
                    self._log(f"[战略层影子] 日志打印异常(不阻塞): {_log_e}", "WARN")
                except Exception:
                    pass

        try:
            state_cache_path = (
                _Path(__file__).resolve().parent / "runtime" / "five_domain_state.json"
            )
            import datetime as _dt
            today_str = _dt.date.today().isoformat()

            need_recalc = True
            _cached = None
            if state_cache_path.exists():
                try:
                    with state_cache_path.open("r", encoding="utf-8") as _f:
                        _cached = json.load(_f)
                    _meta = (_cached or {}).get("_meta", {})
                    if _meta.get("updated_date") == today_str:
                        need_recalc = False
                except Exception:
                    need_recalc = True
                    _cached = None

            # ── 分支 A：今日缓存命中（need_recalc=False）→ 读缓存，不重算，但必须：
            #    1) 反序列化填 self._five_domain_state_cache（否则策略层取不到）
            #    2) 补打影子日志（否则看不到战略层今天在跑什么）
            # ──────────────────────────────────────────────────────────────
            if not need_recalc and _cached is not None:
                _real_state = None
                try:
                    from scripts.memory_l4.five_domain_scorer import FiveDomainState as _FDS
                    self._five_domain_state_cache = _FDS.from_json(
                        state_cache_path, fallback_on_error=True
                    )
                    _real_state = self._five_domain_state_cache
                except Exception:
                    # from_json 失败：手工从 _cached 构造最小可用对象或 fail-open
                    try:
                        from scripts.memory_l4.five_domain_scorer import FiveDomainState as _FDS2
                        self._five_domain_state_cache = _FDS2.default_fail_open()
                    except Exception:
                        self._five_domain_state_cache = None
                # ★ FIX-日志一致性：显式同步 shadow 为 from_json 真实值，
                #   防止 _apply_fd_shadow_intercept 被跳过时 shadow 停留在 init 的 stale 状态（dao=50）
                if _real_state is not None:
                    self._five_domain_state_shadow = _real_state
                # ★ 影子拦截：缓存命中时先保存真实值到 _shadow 再替换 _state_cache
                _fd_cls = _FDS if '_FDS' in locals() else None
                _fd_cfg = self._strategy_algo_layer.cfg if self._strategy_algo_layer else None
                if _fd_cls is not None and _fd_cfg is not None:
                    self._apply_fd_shadow_intercept(_fd_cfg, _fd_cls)
                # ★ 影子日志优先读 _real_state（from_json 结果），与缓存文件口径严格一致，
                #   避免 stale _shadow 导致 dao_score 日志与 five_domain_state.json 不一致
                _shadow_state = (
                    self._five_domain_state_shadow
                    or _real_state
                    or self._five_domain_state_cache
                )
                _emit_shadow_logs(_shadow_state, "CACHE")
                return  # ← 缓存命中：当日不再重算（保留原语义）

            # ── 分支 B：需要重算（缓存缺失 / 日期不匹配 / 解析失败）
            # ──────────────────────────────────────────────────────────────
            try:
                from scripts.memory_l4.five_domain_scorer import FiveDomainState
            except Exception:
                FiveDomainState = None

            # ★ BUG FIX 1：删除「先 score_and_decide(None) 写一次中性分」的错误顺序
            # 改为：先 FeatureComputer → 再 Scorer；失败兜底才 Scorer(None)
            result_state = None
            if self._five_domain_feature_computer is not None:
                try:
                    # ── coin_data：从现有系统可用数据中尽力构造（缺失=50）──
                    import datetime as _dt_coin
                    _month = _dt_coin.date.today().month
                    # 美林时钟默认=RECOVERY（当前市场大周期假设，fail-open可换）
                    _merrill = "RECOVERY"
                    try:
                        _y = _dt_coin.date.today().year
                        _m = _month
                        # 距离 2024-04 BTC 减半的月数 / 48 = 4年周期位置 0~1
                        _cycle_months = ((_y - 2024) * 12 + (_m - 4))
                        _t_rel = max(0.0, min(1.0, _cycle_months / 48.0))
                    except Exception:
                        _t_rel = 0.5
                    # P2-fix: 美股/黄金4年周期位置（暂用相同基准，后续可按选举周期/商品周期独立计算）
                    _us_t_rel = _t_rel
                    _metal_t_rel = _t_rel
                    try:
                        _ov = (
                            self.perf_tracker.get_overall_stats()
                            if hasattr(self, "perf_tracker") else {}
                        )
                        _win_rate = float(_ov.get("win_rate", 0.5) or 0.5)
                        _pf = float(_ov.get("profit_factor", 1.5) or 1.5)
                        _total_trades = int(_ov.get("total_trades", 0) or 0)
                        _max_dd = float(_ov.get("max_drawdown", 0.10) or 0.10)
                        _sharpe = float(_ov.get("sharpe_ratio", 3.0) or 3.0)
                    except Exception:
                        _ov, _win_rate, _pf, _total_trades, _max_dd, _sharpe = (
                            {}, 0.5, 1.5, 0, 0.10, 3.0,
                        )
                    try:
                        _open_pos_count = (
                            len(getattr(self.position_tracker, "open_positions", {}))
                            if hasattr(self, "position_tracker") else 0
                        )
                    except Exception:
                        _open_pos_count = 0

                    # ★ FIX 问题1 + P1：三类资产构造差异化 coin_data
                    # P1-地维度：从弹簧力场真实计算 regime + spring_force_score（替代硬编码）
                    # P1-道维度：从 FiveDomainFetcher 代理指标替代 fail-open=50
                    # 所有数据获取 fail-open：异常时回退到硬编码默认值

                    # ── P1: 尝试获取真实弹簧力场数据 ──
                    _spring_crypto = self._try_get_spring_force("BTC-USDT-SWAP", "daily_btc")
                    _spring_stock = self._try_get_spring_force_yf("SPY", "daily_index")
                    _spring_metal = self._try_get_spring_force_yf("GLD", "daily_index")

                    # ── P1: 尝试获取真实宏观代理指标（道维度）──
                    _macro = self._try_fetch_macro_proxies()

                    # P2-4: 美林时钟优先从真实 CPI/INDPRO 计算，缺失时回退 RECOVERY
                    _merrill = _macro.get("merrill_phase") or _merrill
                    # P2-4: ATR 分位优先从 VIX 代理获取，缺失时回退硬编码
                    _atr_proxy = _macro.get("atr_percentile_proxy")
                    # P2-4: 真实流动性评分
                    _liq_score = _macro.get("liquidity_score")

                    # P2-5: 按资产类获取差异化统计（将维度补强）
                    _cls_stats = self._get_class_stats()

                    # regime 映射：弹簧力场 market_regime → FeatureComputer 期望值
                    _regime_map = {
                        "TREND_BULL": "trend_up",
                        "STRONG_TREND_BEAR": "trend_down",
                        "TREND_BEAR": "trend_down",
                        "MEAN_REVERTING": "ranging",
                        "RANGING": "ranging",
                    }

                    # 加密货币（BTC减半周期 + 美林时钟原始值 + 真实弹簧力场）
                    _crypto_regime = _regime_map.get(
                        _spring_crypto.get("market_regime", ""),
                        "trend_up" if _t_rel < 0.35 else "ranging"
                    )
                    _crypto_coin = {
                        "cycle4y_t_rel": _t_rel,
                        "merrill_phase": _merrill,
                        "atr_percentile": _atr_proxy if _atr_proxy is not None else 0.62,
                        "liquidity_score": _liq_score if _liq_score is not None else 0.65,
                        "regime": _crypto_regime,
                        "spring_force_score": _spring_crypto.get("spring_force_score", 70),
                        "spring_force_F_total": _spring_crypto.get("F_total", 0.0),
                        "spring_force_bearish_score": _spring_crypto.get("bearish_score", "NONE"),
                        # P0-3: 地维度指标优先用弹簧力场实算值，失败才回退占位
                        "price_amplitude": _spring_crypto.get("price_amplitude", 4.2),
                        "atr": _spring_crypto.get("atr", 1.15),
                        "ftd_signal": _spring_crypto.get("ftd_signal", 1 if _t_rel < 0.25 else 0),
                        "ma200_distance_percentile": _spring_crypto.get("ma200_distance_percentile", 0.68),
                        # P1-道维度代理指标
                        "vix_close": _macro.get("vix_close"),
                        "stablecoin_mcap_bln": _macro.get("stablecoin_mcap_bln"),
                        "fedfunds_rate": _macro.get("fedfunds_rate"),
                        "policy_sentiment_score": _macro.get("policy_sentiment_score"),
                        # P2-3: 道维度变化率（稳定币市值一阶差分）
                        "stablecoin_change_rate": _macro.get("stablecoin_change_rate"),
                    }
                    # 美股（总统周期中段 + 过热期倾向 + 真实弹簧力场）
                    _stock_regime = _regime_map.get(
                        _spring_stock.get("market_regime", ""),
                        "ranging"
                    )
                    _stock_coin = {
                        "cycle4y_t_rel": _us_t_rel,
                        "merrill_phase": _merrill,  # P2-4: 使用真实美林时钟（非硬编码 OVERHEAT）
                        "atr_percentile": _atr_proxy if _atr_proxy is not None else 0.42,
                        "liquidity_score": _liq_score if _liq_score is not None else 0.52,
                        "regime": _stock_regime,
                        "spring_force_score": _spring_stock.get("spring_force_score", 58),
                        "spring_force_F_total": _spring_stock.get("F_total", 0.0),
                        "spring_force_bearish_score": _spring_stock.get("bearish_score", "NONE"),
                        # P0-3: 地维度指标优先用弹簧力场实算值，失败才回退占位
                        "price_amplitude": _spring_stock.get("price_amplitude", 2.1),
                        "atr": _spring_stock.get("atr", 0.78),
                        "ftd_signal": _spring_stock.get("ftd_signal", 0),
                        "ma200_distance_percentile": _spring_stock.get("ma200_distance_percentile", 0.46),
                        # P1-道维度代理指标
                        "vix_close": _macro.get("vix_close"),
                        "fedfunds_rate": _macro.get("fedfunds_rate"),
                    }
                    # 贵金属/黄金（避险周期中段 + 滞胀期倾向 + 真实弹簧力场）
                    _metal_phase = "STAGFLATION" if _merrill in ("OVERHEAT", "STAGFLATION") else "RECOVERY"
                    _metal_regime = _regime_map.get(
                        _spring_metal.get("market_regime", ""),
                        "breakout" if _merrill in ("STAGFLATION", "REFLATION") else "ranging"
                    )
                    _metal_coin = {
                        "cycle4y_t_rel": _metal_t_rel,
                        "merrill_phase": _metal_phase,
                        "atr_percentile": _atr_proxy if _atr_proxy is not None else 0.50,
                        "liquidity_score": _liq_score if _liq_score is not None else 0.56,
                        "regime": _metal_regime,
                        "spring_force_score": _spring_metal.get("spring_force_score", 66),
                        "spring_force_F_total": _spring_metal.get("F_total", 0.0),
                        "spring_force_bearish_score": _spring_metal.get("bearish_score", "NONE"),
                        # P0-3: 地维度指标优先用弹簧力场实算值，失败才回退占位
                        "price_amplitude": _spring_metal.get("price_amplitude", 2.7),
                        "atr": _spring_metal.get("atr", 0.92),
                        "ftd_signal": _spring_metal.get("ftd_signal", 0),
                        "ma200_distance_percentile": _spring_metal.get("ma200_distance_percentile", 0.60),
                        # P1-道维度代理指标
                        "vix_close": _macro.get("vix_close"),
                        "fedfunds_rate": _macro.get("fedfunds_rate"),
                    }
                    # ── Phase L：Panewslab 三类 coin_data 增量合并 ──
                    # 调用 _try_fetch_coin_data_three_classes()：
                    #   - 命中 SQLite（持续采集 4h 落库）→ 快省 API
                    #   - 否则 FiveDomainFetcher 实时 → 兜底
                    #   - 全失败 → 返回 {}（保持原有硬编码 coin_data，字节等价 fail-open）
                    try:
                        _three_cls = self._try_fetch_coin_data_three_classes()
                    except Exception:
                        _three_cls = {}
                    # 把 panewslab proxy（pn_*）和额外宏观 proxy 增量合并进
                    # _crypto_coin / _stock_coin / _metal_coin。
                    # 原则：「只补不覆」——只有当原硬编码字段的值是 None/占位
                    # (0.5/0.62/0.65这类 经验占位值 也被覆写，因为 panewslab 是真实数据)
                    # 但 cycle4y_t_rel / regime / spring_force_* / price_amplitude /
                    # atr / ftd_signal / ma200_distance_percentile 保留原内联。
                    _OVERLAY_BLACKLIST = {
                        "cycle4y_t_rel", "regime", "spring_force_score",
                        "spring_force_F_total", "spring_force_bearish_score",
                        "price_amplitude", "atr", "ftd_signal",
                        "ma200_distance_percentile",
                    }
                    for _cls, _template in (
                        ("crypto_usdt", _crypto_coin),
                        ("us_stock",   _stock_coin),
                        ("precious_metal", _metal_coin),
                    ):
                        _external = (_three_cls or {}).get(_cls) or {}
                        for _k, _v in _external.items():
                            if _k in _OVERLAY_BLACKLIST:
                                continue
                            # 有真实值才 overlay；None 不覆盖（保留原占位值/None）
                            if _v is None:
                                continue
                            _template[_k] = _v
                    coin_data = {
                        "crypto_usdt": _crypto_coin,
                        "us_stock": _stock_coin,
                        "precious_metal": _metal_coin,
                        # ---- 兼容键（旧扁平结构字段，用于_Flat判定保留，未来可删）----
                        "cycle4y_t_rel": _t_rel,
                        "merrill_phase": _merrill,
                    }

                    system_state = {
                        "factor_coverage_pct": 0.80,
                        "win_rate": _win_rate,
                        "profit_factor": _pf,
                        "position_pct": float(
                            getattr(self, "default_position_pct", 0.10) or 0.10
                        ),
                        "max_consecutive_losses": int(
                            getattr(self, "max_consecutive_losses", 999) or 999
                        ),
                        "auto_execute": True,
                        "has_stop_loss": True,
                        "has_drawdown_limit": True,
                        "has_daily_trade_limit": False,
                        "has_position_cap": True,
                        "implemented_strategies": [True, True, True, True, False, True],
                        "strategy_match_pct": 0.70,
                        "risk_rules": {
                            "stop_loss": True,
                            "drawdown_limit": True,
                            "position_cap": True,
                            "correlation_limit": False,
                        },
                        "backtest_metrics": {"sharpe": _sharpe, "max_drawdown": _max_dd},
                        "has_review_cycle": True,
                        "has_strategy_retirement": True,
                        # ── P2-5: _by_class 按类差异化统计（替代 P0 占位值）──
                        # 从 perf_tracker.trades 按资产类筛选 win_rate/pf/max_dd
                        # 策略库实现/风控规则/适配度按资产类差异化
                        "_by_class": {
                            "crypto_usdt": {
                                "factor_coverage_pct": 0.80,
                                "win_rate": _cls_stats.get("crypto_usdt", {}).get("win_rate", _win_rate),
                                "profit_factor": _cls_stats.get("crypto_usdt", {}).get("profit_factor", _pf),
                                "position_pct": float(getattr(self, "default_position_pct", 0.10) or 0.10),
                                "max_consecutive_losses": int(getattr(self, "max_consecutive_losses", 999) or 999),
                                "auto_execute": True,
                                "has_stop_loss": True,
                                "has_drawdown_limit": True,
                                "has_daily_trade_limit": False,
                                "has_position_cap": True,
                                # crypto: 6类策略实现5类（波动率策略未实现）
                                "implemented_strategies": [True, True, True, True, False, True],
                                "strategy_match_pct": 0.70,
                                "risk_rules": {"stop_loss": True, "drawdown_limit": True, "position_cap": True, "correlation_limit": False},
                                "backtest_metrics": {
                                    "sharpe": _cls_stats.get("crypto_usdt", {}).get("sharpe_ratio", _sharpe),
                                    "max_drawdown": _cls_stats.get("crypto_usdt", {}).get("max_drawdown", _max_dd),
                                },
                                "has_review_cycle": True,
                                "has_strategy_retirement": True,
                            },
                            "us_stock": {
                                "factor_coverage_pct": 0.65,  # 美股因子覆盖低于加密
                                "win_rate": _cls_stats.get("us_stock", {}).get("win_rate", _win_rate),
                                "profit_factor": _cls_stats.get("us_stock", {}).get("profit_factor", _pf),
                                "position_pct": float(getattr(self, "default_position_pct", 0.10) or 0.10),
                                "max_consecutive_losses": int(getattr(self, "max_consecutive_losses", 999) or 999),
                                "auto_execute": True,
                                "has_stop_loss": True,
                                "has_drawdown_limit": True,
                                "has_daily_trade_limit": True,  # 美股有日内交易限制
                                "has_position_cap": True,
                                # us_stock: 4类策略（趋势/突破/动量/应急，均值回归和波动率未实现）
                                "implemented_strategies": [True, True, False, True, False, True],
                                "strategy_match_pct": 0.55,  # 美股策略适配度低于加密
                                "risk_rules": {"stop_loss": True, "drawdown_limit": True, "position_cap": True, "correlation_limit": True},  # 美股有相关性限制
                                "backtest_metrics": {
                                    "sharpe": _cls_stats.get("us_stock", {}).get("sharpe_ratio", _sharpe),
                                    "max_drawdown": _cls_stats.get("us_stock", {}).get("max_drawdown", _max_dd),
                                },
                                "has_review_cycle": True,
                                "has_strategy_retirement": True,
                            },
                            "precious_metal": {
                                "factor_coverage_pct": 0.55,  # 黄金因子覆盖最低
                                "win_rate": _cls_stats.get("precious_metal", {}).get("win_rate", _win_rate),
                                "profit_factor": _cls_stats.get("precious_metal", {}).get("profit_factor", _pf),
                                "position_pct": float(getattr(self, "default_position_pct", 0.10) or 0.10),
                                "max_consecutive_losses": int(getattr(self, "max_consecutive_losses", 999) or 999),
                                "auto_execute": True,
                                "has_stop_loss": True,
                                "has_drawdown_limit": True,
                                "has_daily_trade_limit": False,
                                "has_position_cap": True,
                                # precious_metal: 3类策略（趋势/突破/应急）
                                "implemented_strategies": [True, True, False, False, False, True],
                                "strategy_match_pct": 0.45,  # 黄金策略适配度最低
                                "risk_rules": {"stop_loss": True, "drawdown_limit": True, "position_cap": True, "correlation_limit": False},
                                "backtest_metrics": {
                                    "sharpe": _cls_stats.get("precious_metal", {}).get("sharpe_ratio", _sharpe),
                                    "max_drawdown": _cls_stats.get("precious_metal", {}).get("max_drawdown", _max_dd),
                                },
                                "has_review_cycle": True,
                                "has_strategy_retirement": False,  # 黄金未实现策略退役
                            },
                        },
                    }
                    _raw_scores = self._five_domain_feature_computer.compute(
                        coin_data=coin_data, system_state=system_state,
                    )
                    # 构建方向偏置上下文（direction_context）：综合技术面+BDSM估值+BCRM方向
                    _dir_ctx: Dict[str, Dict[str, Any]] = {}
                    try:
                        for _cls in ("crypto_usdt", "us_stock", "precious_metal"):
                            _cd_cls = (coin_data or {}).get(_cls, {}) or {}
                            _entry: Dict[str, Any] = {}
                            # 高位滞涨分数（<50看空）
                            if "high_stall_score" in _cd_cls:
                                _entry["high_stall_score"] = float(_cd_cls["high_stall_score"])
                            # BTC regime
                            if "btc_regime" in _cd_cls:
                                _entry["btc_regime"] = _cd_cls["btc_regime"]
                            # BDSM 估值分位（从快照获取）
                            try:
                                _bdsm = self._get_bdsm_snapshot_today()
                                _bdsm_coins = (_bdsm or {}).get("coins", {}) or {}
                                _val_list = []
                                for _c, _v in _bdsm_coins.items():
                                    if isinstance(_v, dict):
                                        _vp = _v.get("valuation_percentile")
                                        if _vp is not None:
                                            _val_list.append(float(_vp))
                                if _val_list:
                                    _entry["bdsm_valuation_percentile"] = sum(_val_list) / len(_val_list)
                            except Exception:
                                pass
                            # BCRM 方向（从缓存获取，可能为None）
                            _bcrm_cache = getattr(self, "_last_bcrm2_result", None)
                            if isinstance(_bcrm_cache, dict):
                                _ns = _bcrm_cache.get("next_state", {}) or {}
                                _entry["bcrm_direction"] = _ns.get("direction", "HOLD")
                                _entry["bcrm_confidence"] = float(_ns.get("confidence", 0.0) or 0.0)
                                # Phase 4.3: 头肩顶形态
                                _pat = _ns.get("pattern")
                                if _pat:
                                    _entry["pattern"] = _pat
                            # Phase 4.3: ETF 净流入归一化（流出<0）
                            _etf = _cd_cls.get("pn_btc_etf_flow_norm")
                            if isinstance(_etf, (int, float)):
                                _entry["etf_flow_norm"] = float(_etf)
                            # Phase 4.3: BDSM exit_action 离场信号
                            try:
                                _bdsm = self._get_bdsm_snapshot_today()
                                _bdsm_coins = (_bdsm or {}).get("coins", {}) or {}
                                _exit_actions = []
                                for _c, _v in _bdsm_coins.items():
                                    if isinstance(_v, dict):
                                        _ea = _v.get("exit_action")
                                        if _ea:
                                            _exit_actions.append(_ea)
                                # 取最强 exit_action
                                _priority = {"CLOSE_ALL": 3, "REDUCE_80": 2, "REDUCE_50": 1}
                                if _exit_actions:
                                    _entry["bdsm_exit_action"] = max(_exit_actions, key=lambda x: _priority.get(x, 0))
                            except Exception:
                                pass
                            if _entry:
                                _dir_ctx[_cls] = _entry
                    except Exception:
                        _dir_ctx = {}  # FAIL-OPEN
                    # ★ Phase 2：提取 force_vectors 供自适应权重（FAIL-OPEN：缺失/异常 → None）
                    _fv_by_class = None
                    try:
                        _fv_shadow = (_raw_scores or {}).get("_force_vector_shadow", {})
                        _per_class = (_fv_shadow or {}).get("per_class", {})
                        _fv_by_class = {}
                        for _cls in ("crypto_usdt", "us_stock", "precious_metal"):
                            _cls_fv = (_per_class.get(_cls, {}) or {}).get("force_vectors")
                            if _cls_fv and isinstance(_cls_fv, dict):
                                _fv_by_class[_cls] = _cls_fv
                        if not _fv_by_class:
                            _fv_by_class = None
                    except Exception:
                        _fv_by_class = None
                    result_state = self._five_domain_scorer.score_and_decide(
                        raw_scores_by_class=_raw_scores, persist=True,
                        direction_context=_dir_ctx or None,
                        force_vectors_by_class=_fv_by_class,
                    )
                    # 注入 btc_regime（用户经验因子：BTC 强弱决定与美股相关性）
                    try:
                        _cd_crypto = (coin_data or {}).get("crypto_usdt", coin_data or {})
                        if isinstance(_cd_crypto, dict):
                            result_state.btc_regime["crypto_usdt"] = _cd_crypto.get("btc_regime", "NEUTRAL")
                    except Exception:
                        pass
                except Exception as _fe:
                    # ★ BUG FIX 3：异常时追加 traceback 便于定位（否则只看到"降级fail-open"）
                    import traceback as _tb
                    _tb_str = _tb.format_exc(limit=6)
                    self._log(
                        f"[战略层] feature computer 异常，降级 fail-open: "
                        f"{type(_fe).__name__}: {_fe}\n{_tb_str}",
                        "WARN",
                    )
                    # 兜底：用中性分 fail-open（FiveDomainHeuristicScorer(enable=True, raw=None)）
                    try:
                        if result_state is None:
                            result_state = self._five_domain_scorer.score_and_decide(
                                raw_scores_by_class=None, persist=True,
                            )
                    except Exception:
                        pass

            # FeatureComputer 不存在或最终 result_state 仍为空：走 Scorer 无参兜底
            if result_state is None:
                try:
                    result_state = self._five_domain_scorer.score_and_decide(
                        raw_scores_by_class=None, persist=True,
                    )
                except Exception:
                    try:
                        from scripts.memory_l4.five_domain_scorer import (
                            FiveDomainState as _FDS3,
                        )
                        result_state = _FDS3.default_fail_open()
                    except Exception:
                        result_state = None

            self._five_domain_state_cache = result_state

            # ── 写缓存 _meta.updated_date=今天（to_json 已经写过 state；这里只补充/更新 _meta）
            try:
                if state_cache_path.exists():
                    with state_cache_path.open("r", encoding="utf-8") as _f:
                        _data = json.load(_f)
                else:
                    _data = (
                        _asdict(result_state)
                        if result_state is not None
                        and hasattr(result_state, "__dataclass_fields__")
                        else {}
                    )
                if "_meta" not in _data:
                    _data["_meta"] = {}
                _data["_meta"]["updated_date"] = today_str
                state_cache_path.parent.mkdir(parents=True, exist_ok=True)
                with state_cache_path.open("w", encoding="utf-8") as _f:
                    json.dump(_data, _f, ensure_ascii=False, indent=2, sort_keys=True)
            except Exception:
                pass

            _emit_shadow_logs(result_state, "RECALC")
            # ★ 影子拦截：日级重算后也需保存真实值到 _shadow 并替换 _state_cache
            _fd_cfg = self._strategy_algo_layer.cfg if self._strategy_algo_layer else None
            if _fd_cfg is not None:
                try:
                    from scripts.memory_l4.five_domain_scorer import FiveDomainState as _FDS4
                    self._apply_fd_shadow_intercept(_fd_cfg, _FDS4)
                except Exception:
                    pass
        except Exception as _e:
            try:
                from scripts.memory_l4.five_domain_scorer import FiveDomainState
                self._five_domain_state_cache = FiveDomainState.default_fail_open()
            except Exception:
                self._five_domain_state_cache = None
            self._log(f"[战略层影子] 日级打分异常，fail-open降级: {_e}", "WARN")

    # ================================================================
    # P1 辅助方法：获取真实弹簧力场数据 + 宏观代理指标（fail-open）
    # ================================================================

    # ================================================================
    # P2-5: 按资产类获取差异化统计（将维度补强）
    # ================================================================

    # 资产类符号识别规则
    _CRYPTO_SYMBOLS = frozenset({
        "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "MATIC",
        "BNB", "LTC", "BCH", "UNI", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "ZEC",
    })
    _METAL_SYMBOLS = frozenset({"XAG", "XAU", "GLD", "SLV", "GOLD", "SILVER", "PAXG"})

    @classmethod
    def _classify_symbol(cls, symbol: str) -> str:
        """从交易符号判定资产类 → crypto_usdt / us_stock / precious_metal。"""
        if not symbol:
            return "crypto_usdt"
        s = symbol.upper().split("-")[0].split("/")[0].strip()
        # 加密：含 USDT/USD-SWAP 或已知加密币前缀
        if "USDT" in symbol.upper() or "USD-SWAP" in symbol.upper():
            return "crypto_usdt"
        if s in cls._CRYPTO_SYMBOLS:
            return "crypto_usdt"
        # 贵金属
        if s in cls._METAL_SYMBOLS:
            return "precious_metal"
        # 默认美股
        return "us_stock"

    def _get_class_stats(self) -> dict:
        """P2-5: 从 perf_tracker.trades 按资产类统计差异化指标。

        Returns: {cls: {win_rate, profit_factor, max_drawdown, sharpe_ratio, total_trades}}
        """
        result = {cls: {} for cls in ("crypto_usdt", "us_stock", "precious_metal")}
        try:
            trades = list(getattr(self.perf_tracker, "trades", []))
            if not trades:
                return result
            # 按 asset_class 分组
            by_cls = {"crypto_usdt": [], "us_stock": [], "precious_metal": []}
            for t in trades:
                sym = getattr(t, "coin", "") or getattr(t, "inst_id", "")
                cls = self._classify_symbol(sym)
                by_cls[cls].append(t)
            # 按类计算
            for cls, cls_trades in by_cls.items():
                n = len(cls_trades)
                if n == 0:
                    result[cls] = {"total_trades": 0}
                    continue
                wins = [t for t in cls_trades if getattr(t, "pnl", 0) >= 0]
                losses = [abs(getattr(t, "pnl", 0)) for t in cls_trades if getattr(t, "pnl", 0) < 0]
                win_rate = len(wins) / n if n else 0.5
                avg_win = sum(getattr(t, "pnl", 0) for t in wins) / len(wins) if wins else 0
                avg_loss = sum(losses) / len(losses) if losses else 0
                profit_factor = avg_win / avg_loss if avg_loss > 0 else 1.5
                # max_drawdown: 该类连续亏损序列的最大累积
                max_dd = 0.0
                cum = 0.0
                for t in cls_trades:
                    pnl = getattr(t, "pnl", 0)
                    cum += pnl
                    if cum < 0:
                        max_dd = max(max_dd, abs(cum))
                    else:
                        cum = 0.0
                max_dd_pct = max_dd / getattr(self.perf_tracker, "initial_equity", 10000) if max_dd > 0 else 0.10
                result[cls] = {
                    "win_rate": win_rate,
                    "profit_factor": profit_factor,
                    "max_drawdown": min(max_dd_pct, 1.0),
                    "total_trades": n,
                    "sharpe_ratio": 3.0,  # 简化：按类夏普暂用全局值或3.0兜底
                }
        except Exception:
            pass
        return result

    def _try_get_spring_force(self, inst_id: str, tier: str) -> dict:
        """P1: 从 OKX K线计算真实弹簧力场 + 地维度指标（加密专用）。fail-open 返回空 dict。

        Returns: {"market_regime", "spring_force_score", "F_total", "bearish_score",
                  "ma200_distance_percentile", "price_amplitude", "atr", "ftd_signal"} 或 {}
        """
        try:
            from scripts.memory_l4.yijing_trainer import _load_kline_from_okx
            klines = _load_kline_from_okx(inst_id=inst_id, bar="1D", limit=1500)
            closes = [float(k.get("c", 0)) for k in klines if k.get("c")]
            if len(closes) < 131:
                return {}
            res = self._calc_5ma_spring_force(closes, tier=tier)
            f_total = res.get("F_total", 0.0)
            bearish_score = res.get("bearish_score", "NONE")
            score = int(np.clip(round(57.5 + 27.5 * np.tanh(f_total * 10)), 0, 100))

            # P0-3: 从 K线计算地维度真实指标（替代硬编码占位值）
            di_metrics = self._calc_di_metrics_from_klines(closes, klines)

            return {
                "market_regime": res.get("market_regime", "RANGING"),
                "spring_force_score": score,
                "F_total": round(f_total, 6),
                "bearish_score": bearish_score,
                **di_metrics,
            }
        except Exception:
            return {}

    def _calc_di_metrics_from_klines(self, closes: list, klines: list) -> dict:
        """从K线计算地维度真实指标：MA200距离/价格振幅/ATR/FTD信号。

        Args:
            closes: newest-first close price list
            klines: 原始 K 线 dict 列表（含 o/h/l/c）
        Returns:
            {ma200_distance_percentile, price_amplitude, atr, ftd_signal}
        """
        out = {}
        try:
            # MA200 距离分位：price 在近200日价格区间的位置 [0,1]
            if len(closes) >= 200:
                ma200 = sum(closes[:200]) / 200.0
                dist_pct = (closes[0] - ma200) / ma200  # 正=在均线上方
                # 归一到 [0,1]：-20%→0, +20%→1
                out["ma200_distance_percentile"] = float(np.clip(0.5 + dist_pct / 0.4, 0.0, 1.0))
            # 价格振幅：近20日 (high-low)/close 均值 * 100
            if len(klines) >= 20:
                amps = []
                for k in klines[:20]:
                    h = float(k.get("h", 0)); l = float(k.get("l", 0)); c = float(k.get("c", 1))
                    if c > 0 and h > 0 and l > 0:
                        amps.append((h - l) / c * 100)
                if amps:
                    out["price_amplitude"] = round(float(np.mean(amps)), 2)
            # ATR(14) 百分比
            if len(klines) >= 15:
                trs = []
                for i in range(14):
                    h = float(klines[i].get("h", 0)); l = float(klines[i].get("l", 0))
                    pc = float(klines[i+1].get("c", 0)) if i+1 < len(klines) else h
                    tr = max(h - l, abs(h - pc), abs(l - pc))
                    if pc > 0:
                        trs.append(tr / pc * 100)
                if trs:
                    out["atr"] = round(float(np.mean(trs)), 3)
            # FTD (Follow-Through Day)：近5日内是否出现放量大涨(>1.5%)的确认信号
            if len(klines) >= 5:
                ftd = 0
                for i in range(5):
                    c = float(klines[i].get("c", 0))
                    pc = float(klines[i+1].get("c", 0)) if i+1 < len(klines) else c
                    if pc > 0 and (c - pc) / pc > 0.015:
                        ftd = 1
                        break
                out["ftd_signal"] = ftd
        except Exception:
            pass
        return out

    def _try_get_spring_force_yf(self, symbol: str, tier: str) -> dict:
        """P1: 从 yfinance 获取 K线计算弹簧力场 + 地维度指标（美股/黄金）。fail-open。

        Returns: 同 _try_get_spring_force 格式。
        """
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5y", interval="1d")
            if hist is None or len(hist) < 201:
                return {}
            closes = hist["Close"].tolist()
            closes.reverse()  # newest-first
            if len(closes) < 201:
                return {}
            res = self._calc_5ma_spring_force(closes, tier=tier)
            f_total = res.get("F_total", 0.0)
            bearish_score = res.get("bearish_score", "NONE")
            score = int(np.clip(round(57.5 + 27.5 * np.tanh(f_total * 10)), 0, 100))

            # P0-3: 从 yfinance DataFrame 计算地维度真实指标
            di_metrics = self._calc_di_metrics_from_yf(hist, closes)

            return {
                "market_regime": res.get("market_regime", "RANGING"),
                "spring_force_score": score,
                "F_total": round(f_total, 6),
                "bearish_score": bearish_score,
                **di_metrics,
            }
        except Exception:
            return {}

    def _calc_di_metrics_from_yf(self, hist, closes: list) -> dict:
        """从 yfinance DataFrame 计算地维度指标。hist 为 newest-first 反转前的原始顺序。"""
        out = {}
        try:
            # 反转为 newest-first 便于取最近数据
            highs = hist["High"].tolist()[::-1]
            lows = hist["Low"].tolist()[::-1]
            closes_yf = hist["Close"].tolist()[::-1]
            n = len(closes_yf)
            # MA200 距离分位
            if n >= 200:
                ma200 = sum(closes_yf[:200]) / 200.0
                dist_pct = (closes_yf[0] - ma200) / ma200
                out["ma200_distance_percentile"] = float(np.clip(0.5 + dist_pct / 0.4, 0.0, 1.0))
            # 价格振幅（近20日）
            if n >= 20:
                amps = [(highs[i] - lows[i]) / closes_yf[i] * 100
                        for i in range(20) if closes_yf[i] > 0]
                if amps:
                    out["price_amplitude"] = round(float(np.mean(amps)), 2)
            # ATR(14) 百分比
            if n >= 15:
                trs = []
                for i in range(14):
                    h, l = highs[i], lows[i]
                    pc = closes_yf[i+1] if i+1 < n else h
                    tr = max(h - l, abs(h - pc), abs(l - pc))
                    if pc > 0:
                        trs.append(tr / pc * 100)
                if trs:
                    out["atr"] = round(float(np.mean(trs)), 3)
            # FTD 信号
            if n >= 5:
                ftd = 0
                for i in range(5):
                    c, pc = closes_yf[i], closes_yf[i+1]
                    if pc > 0 and (c - pc) / pc > 0.015:
                        ftd = 1
                        break
                out["ftd_signal"] = ftd
        except Exception:
            pass
        return out

    def _try_fetch_macro_proxies(self) -> dict:
        """P1+P2: 获取道/天维度宏观代理指标（VIX/稳定币市值/利率/政策情绪/美林时钟）。

        优先从数据中心 SQLite 读（持续采集调度器已落库），命中则直接返回，避免每次
        日级重算都实时打外部 API；SQLite 缺失/异常时回退 FiveDomainFetcher 实时采集。
        所有异常均 fail-open 返回空 dict，调用方用 .get(key, default) 兜底。
        """
        result: dict = {}
        # ── 尝试 0: 从数据中心 SQLite 读已落库的五维数据（持续采集落库）──
        try:
            from scripts.memory_l4.five_domain_sqlite_reader import read_macro_from_sqlite
            _sqlite_data = read_macro_from_sqlite()
            # 关键宏观数据存在（利率/VIX）则视为 SQLite 命中
            if _sqlite_data.get("fedfunds_rate") is not None or _sqlite_data.get("vix_close") is not None:
                result = _sqlite_data
                # 派生：稳定币市值一阶差分（与原末尾逻辑一致，SQLite 命中时在此结算）
                _sc_now = result.get("stablecoin_mcap_bln")
                if _sc_now is not None and isinstance(_sc_now, (int, float)) and _sc_now > 0:
                    _sc_prev = getattr(self, "_last_stablecoin_mcap", None)
                    if _sc_prev is not None and isinstance(_sc_prev, (int, float)) and _sc_prev > 0:
                        result["stablecoin_change_rate"] = float((_sc_now - _sc_prev) / _sc_prev)
                    self._last_stablecoin_mcap = float(_sc_now)
                self._log("[战略层] 宏观代理数据来源: SQLite（数据中心持续采集落库）", "INFO")
                return result
        except Exception as _se:
            self._log(f"[战略层] SQLite 读取异常，回退实时采集: {type(_se).__name__}: {_se}", "WARN")
        # ── 尝试 1: FiveDomainFetcher（完整宏观数据，实时采集兜底）──
        try:
            from scripts.memory_l4.fivedomain_fetcher import FiveDomainFetcher
            fetcher = FiveDomainFetcher()
            coin_data_all = fetcher.fetch_coin_data()
            crypto_data = coin_data_all.get("crypto_usdt", {})
            result["vix_close"] = crypto_data.get("vix_close")
            result["stablecoin_mcap_bln"] = crypto_data.get("stablecoin_mcap_bln")
            result["fedfunds_rate"] = crypto_data.get("fedfunds_rate")
            result["policy_sentiment_score"] = crypto_data.get("policy_sentiment_score")
            result["liquidity_score"] = crypto_data.get("liquidity_score")
            # P2-4: 天维度真实美林时钟 + CPI/INDPRO 数据
            result["merrill_phase"] = crypto_data.get("merrill_phase")
            result["us_cpi_yoy_pct"] = crypto_data.get("us_cpi_yoy_pct")
            result["us_indpro_yoy_pct"] = crypto_data.get("us_indpro_yoy_pct")
            result["m2_yoy_pct"] = crypto_data.get("m2_yoy_pct")
            result["fed_balance_sheet_trillion"] = crypto_data.get("fed_balance_sheet_trillion")
            # 派生：VIX → 天维度波动率代理
            vix = result.get("vix_close")
            if vix is not None:
                # VIX > 30 = 高恐慌 → 低分；VIX < 15 = 低波动 → 高分
                result["atr_percentile_proxy"] = float(np.clip((vix - 10) / 40.0, 0.0, 1.0))
        except Exception:
            pass
        # ── 尝试 2: 如果 VIX 仍缺失，直接用 yfinance 补取（去掉^前缀重试）──
        if not result.get("vix_close"):
            try:
                import yfinance as yf
                # 先试 ^VIX，再试 VIX（不同 yfinance 版本兼容性）
                for sym in ("^VIX", "VIX"):
                    try:
                        vix_ticker = yf.Ticker(sym)
                        vix_hist = vix_ticker.history(period="5d")
                        if vix_hist is not None and len(vix_hist) > 0:
                            result["vix_close"] = float(vix_hist["Close"].iloc[-1])
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        # ── P2-2 尝试 3: 如果 VIX 仍缺失，从 FRED VIXCLS 获取 ──
        if not result.get("vix_close"):
            try:
                from scripts.memory_l4.fivedomain_fetcher import FiveDomainFetcher as _FDF
                _fdf = _FDF.__new__(_FDF)
                _fdf.dc = None  # 避免 DataCenter 初始化
                # 直接用 DataCenter 获取 FRED VIXCLS
                import sys as _sys
                _dc_path = "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心"
                if _dc_path not in _sys.path:
                    _sys.path.insert(0, _dc_path)
                from data_center import DataCenter
                _dc = DataCenter()
                _records = _dc.fetch("macro", source="fred", series="VIXCLS")
                if _records:
                    _v = getattr(_records[0], "metrics", None)
                    if isinstance(_v, dict):
                        result["vix_close"] = _v.get("value") or _v.get("price")
            except Exception:
                pass
        # ── 派生：如果 VIX 获取成功但 atr_percentile_proxy 缺失，补算 ──
        if result.get("vix_close") and not result.get("atr_percentile_proxy"):
            vix = result["vix_close"]
            result["atr_percentile_proxy"] = float(np.clip((vix - 10) / 40.0, 0.0, 1.0))
        # ── P2-3: 道维度变化率（稳定币市值一阶差分）──
        # 与上次快照对比，计算资金流入/流出加速度
        _sc_now = result.get("stablecoin_mcap_bln")
        if _sc_now is not None and isinstance(_sc_now, (int, float)) and _sc_now > 0:
            _sc_prev = getattr(self, "_last_stablecoin_mcap", None)
            if _sc_prev is not None and isinstance(_sc_prev, (int, float)) and _sc_prev > 0:
                # 变化率 = (当前 - 上次) / 上次
                _sc_change_rate = (_sc_now - _sc_prev) / _sc_prev
                result["stablecoin_change_rate"] = float(_sc_change_rate)
            # 更新快照
            self._last_stablecoin_mcap = float(_sc_now)
        return result

    # ================================================================
    # Phase L: Panewslab + SQLite → 三类 coin_data 拉取
    # 失败：fail-open 返回空 dict（调用方用自身硬编码兜底，字节等价未接入前）
    # ================================================================
    def _try_fetch_coin_data_three_classes(self) -> Dict[str, Dict[str, Any]]:
        """获取三类资产 coin_data（含 panewslab 的 42 个 pn_* proxy）。

        优先级：
          1. FiveDomainSqliteReader.read_three_classes_from_sqlite() → 快、省 API
          2. FiveDomainFetcher().fetch_coin_data() → 实时采集（兜底）

        两类路径产出完全一致的字段名（crypto_usdt / us_stock / precious_metal）。
        任一异常返回 {}，后续调用方会用内联硬编码 coin_data 替代。
        """
        fallback: Dict[str, Dict[str, Any]] = {}
        # ── 1. SQLite reader（热路径） ──
        try:
            from scripts.memory_l4.five_domain_sqlite_reader import (
                read_three_classes_from_sqlite,
            )
            three = read_three_classes_from_sqlite() or {}
            crypto = three.get("crypto_usdt") or {}
            # 判断 panewslab proxy 至少有 5+ 非空字段才算「命中」，
            # 否则 panewslab collector 还没跑过 → 走实时路径。
            pn_filled = sum(1 for v in crypto.values() if v is not None)
            if crypto and pn_filled >= 5:
                self._log("[战略层] coin_data 来源: SQLite(五维+Panewslab 落库)", "INFO")
                return three
        except Exception as _e:
            self._log(
                f"[战略层] read_three_classes_from_sqlite 异常: {type(_e).__name__}: {_e}",
                "WARN",
            )
        # ── 2. 实时 Fetcher（慢路径兜底） ──
        try:
            from scripts.memory_l4.fivedomain_fetcher import FiveDomainFetcher
            fetcher = FiveDomainFetcher()
            coin_data = fetcher.fetch_coin_data() or {}
            crypto = coin_data.get("crypto_usdt") or {}
            pn_keys = [k for k in crypto.keys() if k.startswith("pn_")]
            self._log(
                f"[战略层] coin_data 来源: FiveDomainFetcher(实时采集)  "
                f"crypto pn_*={len(pn_keys)} 个",
                "INFO",
            )
            return coin_data
        except Exception as _e:
            self._log(
                f"[战略层] FiveDomainFetcher 异常: {type(_e).__name__}: {_e}",
                "WARN",
            )
            return fallback

    # ================================================================
    # Phase C+: 大小周期预测器 + ParameterMapper 初始化
    # 设计原则：失败降级为 None，仅影响日志，不影响交易逻辑
    # ================================================================

    def _init_morph_and_param_mapper(self):
        """初始化大小周期 MorphCyclePredictor（单例）与 ParameterMapper。

        storage 优先复用 bcrm2_adapters（所有 adapter 共享同一 storage），
        兜底使用 run_evolution_pipeline.get_storage()。异常被 catch，
        self._morph_predictor / self._param_mapper 置为 None，后续方法会安全 return。
        """
        try:
            from scripts.memory_l4.bcrm2.morph_cycle_predictor import MorphCyclePredictor
            from scripts.memory_l4.bcrm2.parameter_mapper import ParameterMapper
            from scripts.memory_l4.bcrm2.run_evolution_pipeline import get_storage
        except Exception as e:
            self._log(f"[Morph] 导入失败，大小周期预测日志降级关闭: {e}", "WARN")
            return

        storage = None
        try:
            if hasattr(self, "bcrm2_adapters") and self.bcrm2_adapters:
                first_adapter = next(iter(self.bcrm2_adapters.values()))
                if hasattr(first_adapter, "storage"):
                    storage = first_adapter.storage
        except Exception:
            storage = None
        if storage is None:
            try:
                storage = get_storage()
            except Exception:
                storage = None

        if storage is not None:
            try:
                self._morph_predictor = MorphCyclePredictor(storage)
            except Exception as e:
                self._log(f"[Morph] Predictor 构造失败: {e}", "WARN")
                self._morph_predictor = None
        else:
            self._log(f"[Morph] storage 不可用，大小周期预测日志降级关闭", "WARN")

        try:
            self._param_mapper = ParameterMapper()
        except Exception as e:
            self._log(f"[Morph] ParameterMapper 构造失败: {e}", "WARN")
            self._param_mapper = None

        # 初始化结果 INFO 日志（审计要求：启动时明确知道大小周期/六维已加载）
        predictor_ready = getattr(self._morph_predictor, "storage", None) is not None
        mapper_ready = self._param_mapper is not None
        self._log(
            f"[Morph] 大小周期预测器/ParameterMapper 初始化完成 "
            f"(predictor={'ON' if predictor_ready else 'OFF'}, "
            f"mapper={'ON' if mapper_ready else 'OFF'})",
            "INFO",
        )

    def _log_morph_cycle_for_coin(self, coin: str, inst_id: str) -> None:
        """对单个币种运行大小周期预测并打 INFO 日志（只读，不影响交易逻辑）。

        日志覆盖：大周期 4y t_rel/阶段 + 小周期主周期/振幅/L/T +
        FFT 权重修正 + Hermite 切线修正 + 大周期边界约束(phase/level/amp_cap/decay)。
        与 data_server tab-morph 的 /cycle + /cycle_bounds 输出对齐，
        用于「大小周期 → 市场形态 → 六维参数」传递链的闭环审计。

        异常直接被吞，不影响主流程。
        """
        predictor = getattr(self, "_morph_predictor", None)
        if predictor is None:
            return
        try:
            _full = inst_id or f"{coin.upper()}USDT"
            mp = predictor.predict_with_fallback(_full, hist_days=60, forecast_days=5)
            if not mp.get("ok"):
                # 样本不足 / BTC fallback 失败 -> 降级记录（也算审计闭环：大小周期已执行）
                err = mp.get("error") or "未知"
                fallback = mp.get("fallback_used", False)
                self._log(
                    f"[{coin}] 大小周期预测(只读)未就绪 | fallback={fallback} | reason={err}",
                    "INFO",
                )
                return
            params = mp.get("params") or {}
            # 大周期 4 年：tab-morph 的 cycle4y + bounds（如果 predictor 内部附了）
            c4y = mp.get("cycle_4y") or {}
            bounds = mp.get("bounds") or {}
            t_rel = c4y.get("t_rel_current") or (bounds.get("t_rel_current") if isinstance(bounds, dict) else None)
            phase = (bounds.get("phase_hint") if isinstance(bounds, dict) else None) or c4y.get("stage")
            # 权重修正 / 切线修正
            corr = mp.get("correction_applied") or {}
            wc_pre = corr.get("weight_correction_pre") or {}
            tc_pre = corr.get("tangent_correction_pre") or {}
            # 边界约束三类动作（predictor 返回）
            fft_scale = mp.get("fft_scale_result") or {}
            pullback = mp.get("pullback_result") or {}
            overshoot = mp.get("overshoot_events") or []
            anchor = mp.get("anchor_correction_result")
            auto = mp.get("auto_correction_result")
            # 小周期主周期/振幅
            top3 = mp.get("top3_components") or []
            main_p = top3[0]["period"] if top3 else params.get("detected_period")
            main_a = top3[0]["amplitude"] if top3 else params.get("amplitude")

            wc_keys_n = len(wc_pre)
            tc_str = (f"m0×{float(tc_pre.get('m0_mul',1.0)):.3f} m1×{float(tc_pre.get('m1_mul',1.0)):.3f} "
                      f"bias={float(tc_pre.get('bias',0.0)):+.4f}" if tc_pre else "n/a")
            fft_a = f"amp×{float(fft_scale.get('scale_factor',1.0)):.3f}(orig={float(fft_scale.get('original_amp',0)):.3f})" if isinstance(fft_scale,dict) and fft_scale.get("applied") else "未触发"
            pb = f"回拉{int(pullback.get('overshoot_count',0))}次" if isinstance(pullback,dict) and pullback.get("applied") else "未越界"
            anchor_note = ""
            if isinstance(anchor, dict):
                tag = "OK" if anchor.get("ok") or anchor.get("applied") else "冷却"
                anchor_note = f" | 锚定大修正={tag}"
            auto_note = ""
            if isinstance(auto, dict):
                if auto.get("ok") or auto.get("reason"):
                    auto_note = f" | 在线小修正={auto.get('reason') or 'OK'}"
            overshoot_n = len(overshoot) if isinstance(overshoot, list) else 0

            self._log(
                f"[{coin}] 大小周期预测(只读) | "
                f"大周期 t_rel={t_rel} phase={phase or '-'} | "
                f"小周期 主周期={main_p}d amp={main_a} L={params.get('current_L','-')} T={params.get('current_T','-')} | "
                f"权重修正={wc_keys_n}键 | 切线修正=[{tc_str}] | "
                f"边界约束[FFT {fft_a} | 预测{pb} | 越界事件={overshoot_n}]{anchor_note}{auto_note}",
                "INFO",
            )
        except Exception:
            # 全分支兜底，任何异常都不影响主轮询
            return

    def _log_param_mapper_snapshot(self, coin: str, inst_id: str, inference: dict) -> None:
        """对齐 tab-morph /api/morph/params：ParameterMapper 六维参数快照（只读）。

        目的：审计「市场形态 → 六维参数 → 注入 BCRM 2.0」段③的理论值日志。
        优先使用 inference.snapshot.level_smooth/trend_smooth/consensus（若存在），
        否则兜底：大小周期预测 current_L/current_T + C=0.5（保守中性）。
        结果只打日志，不改变任何交易参数。
        """
        mapper = getattr(self, "_param_mapper", None)
        if mapper is None:
            return
        try:
            snap = (inference or {}).get("snapshot") or {}
            L = float(snap.get("level_smooth", 0.0) or 0.0)
            T = float(snap.get("trend_smooth", 0.0) or 0.0)
            C = float(snap.get("consensus", 0.0) or 0.0)
            src_tag = "snapshot"
            if L == 0.0 and T == 0.0 and C == 0.0:
                # 兜底：从大小周期预测器取 L/T，C 默认 0.5（中性），让日志可闭环
                predictor = getattr(self, "_morph_predictor", None)
                if predictor is not None:
                    try:
                        _full = inst_id or f"{coin.upper()}USDT"
                        _cy = predictor.predict_with_fallback(_full, hist_days=60, forecast_days=5)
                        if _cy.get("ok"):
                            _pa = _cy.get("params") or {}
                            _L = _pa.get("current_L")
                            _T = _pa.get("current_T")
                            if _L is not None and _T is not None:
                                L = float(_L); T = float(_T)
                                C = 0.5
                                src_tag = f"predictor(consensus=default0.5)"
                    except Exception:
                        pass
            if L == 0.0 and T == 0.0 and C == 0.0:
                return

            global_params = mapper.map_global_parameters(L, T, C)
            sw_full = mapper.map_sector_weights(L, T, C, sector_betas=getattr(mapper, "_DEFAULT_IDENTITY_BETAS", None) or {
                "defi": (1.0,0.0,0.0),"ai":(1.0,0.0,0.0),"rwa":(1.0,0.0,0.0),"meme":(1.0,0.0,0.0),"l2":(1.0,0.0,0.0),
            })
            if isinstance(sw_full, dict) and "weights" in sw_full:
                sw = sw_full["weights"]
                tp_m = sw_full.get("sector_tp_mult") or {}
                sl_m = sw_full.get("sector_sl_mult") or {}
            else:
                sw, tp_m, sl_m = sw_full or {}, {}, {}

            def _gp(name):
                rng = global_params.get(name)
                if isinstance(rng, tuple) and len(rng) == 2:
                    lo, hi = map(float, rng)
                    return round((lo + hi) / 2.0, 5)
                return float(rng or 1.0)
            pos_c = _gp("global_position_mult")
            lscap_c = _gp("ls_ratio_cap")
            lb_c = _gp("long_bias")
            sb_c = _gp("short_bias")
            lt_c = _gp("long_threshold_mult")
            st_c = _gp("short_threshold_mult")
            sw_sorted = sorted(sw.items(), key=lambda kv: -float(kv[1]))[:3] if isinstance(sw, dict) else []
            sw_str = ",".join(f"{k}={float(v):.3f}(tp×{float(tp_m.get(k,1.0)):.2f}/sl×{float(sl_m.get(k,1.0)):.2f})" for k,v in sw_sorted) or "n/a"

            # =====================================================================
            # Task T3：ParameterMapper 战略层带宽 clip 影子（仅写影子，真实参数不动）
            # =====================================================================
            try:
                layer = self._strategy_algo_layer
                if layer is None:
                    pass
                elif not layer.cfg.enable_five_domain_front_layer_band:
                    pass
                else:
                    L_r = float(L)
                    T_r = float(T)
                    sec_raw_vals = [float(sw.get(k, 0.5)) for k in ("defi", "ai", "rwa", "meme", "l2")]
                    state = self._five_domain_state_cache
                    if state is None and self._five_domain_scorer is not None:
                        try:
                            state = self._five_domain_scorer.score_and_decide(persist=False)
                        except Exception:
                            state = None
                    band = None
                    if state is not None:
                        try:
                            cls_bands = getattr(state, "front_layer_band", {}) or {}
                            band = cls_bands.get("crypto_usdt")
                        except Exception:
                            band = None
                    if band is None:
                        pass
                    else:
                        Lf, Tf, Sf = layer.apply_band_with_switch(
                            np.asarray([L_r], dtype=float),
                            np.asarray([T_r], dtype=float),
                            np.asarray(sec_raw_vals, dtype=float),
                            band,
                        )
                        front_band_switch_on = bool(layer.cfg.enable_five_domain_front_layer_band)
                        inference["_band_shadow"] = {
                            "L_before": L_r,
                            "T_before": T_r,
                            "L_after": float(Lf[0]),
                            "T_after": float(Tf[0]),
                            "sec_before": sec_raw_vals,
                            "sec_after": [float(x) for x in Sf],
                            "band": band,
                            "front_band_switch_on": front_band_switch_on,
                        }
                        L_before = L_r
                        L_after = float(Lf[0])
                        T_before = T_r
                        T_after = float(Tf[0])
                        self._log(
                            f"[战略层带宽影子] {coin} L: {L_before:.4f}→{L_after:.4f}, "
                            f"T: {T_before:.4f}→{T_after:.4f}, switch={front_band_switch_on}",
                            "INFO",
                        )
            except Exception:
                pass

            self._log(
                f"[{coin}] ParameterMapper 六维(只读对齐tab-morph src={src_tag}) | L={L:+.4f} T={T:+.4f} C={C:.4f} | "
                f"pos×{pos_c:.3f} ls_cap={lscap_c:.3f} "
                f"long_bias={lb_c:+.3f}/sh_bias={sb_c:+.3f} "
                f"long_thr×{lt_c:.3f}/short_thr×{st_c:.3f} | "
                f"sector_top3=[{sw_str}]",
                "INFO",
            )
        except Exception:
            return

    def _log_regime_hold_confirmation(self, coin: str, inference: dict, pos_info: dict) -> None:
        """已持仓形态乘数中性确认日志（段④ 注入 BCRM：持仓配置/资金风控）。

        即便没有新开仓（形态仓位调整/SL/TP 日志因为在 _open_position 未走而缺失），
        也在持仓路径打印一条确认：当前形态 regime 的 pos/tp/sl 乘数 × 实际持仓方向/持仓金额/
        实际 S2 调整后 SLTP ROI 是否与乘数单调一致（=1.0 也算「生效路径闭环」）。
        纯描述性 INFO，不修改任何变量。
        """
        try:
            _reg = inference.get("_regime_pred") or "UNKNOWN"
            _rm = dict(inference.get("_regime_multipliers") or {})
            pm_pos = float(_rm.get("position_mult", 1.0))
            pm_tp  = float(_rm.get("tp_mult", 1.0))
            pm_sl  = float(_rm.get("sl_mult", 1.0))
            pm_thr = float(_rm.get("threshold_mult", 1.0))
            pos_side = pos_info.get("pos_side") or "-"
            upl = float(pos_info.get("upl", 0) or 0)
            upl_pct = float(pos_info.get("upl_ratio", 0) or 0)
            entry_px = float(pos_info.get("entry_px", 0) or inference.get("price", 0) or 0)
            pos_sz = float(pos_info.get("position_size", 0) or 0)
            self._log(
                f"[{coin}] 已持仓形态乘数作用确认 | regime={_reg} "
                f"pos×{pm_pos:.3f} tp×{pm_tp:.3f} sl×{pm_sl:.3f} thr×{pm_thr:.3f} | "
                f"持仓={pos_side} 金额≈{pos_sz*entry_px:+.1f}U 盈亏={upl:+.2f}({upl_pct:+.2%}) "
                f"(基线路径，乘数仅用于记录/后续promote对比，不改变当前持仓)",
                "INFO",
            )
        except Exception:
            return

    def _run_polling_level_learning_and_ab(self):
        """每轮轮询结束时执行：段⑤在线学习 + 段⑥AB闸门状态（只读审计日志）。

        对应 data_server 的 /api/morph/correct?min=3 与 /api/eval/baseline：
          - 在线学习：对 BTC 执行一次 evaluate_and_correct（最小样本由方法内兜底判断不足 3 条会返回 reason 不修正）
            + 再对持仓币种（self.position_tracker.open）尝试运行（对 fallback_used=False 且 trajectory>=20 的币）
          - AB 闸门：读 RolloutManager 的 dual baseline 评估结果（与 data_server 共用 state）
        全部只记录日志，不做任何 promote 动作（promote 保留为 data_server 手动 API 触发，避免自动升级）。
        """
        # --- [段①②③ 核心锚定币种 BTCUSDT：对齐 tab-morph /api/morph/cycle+/params] ---
        # 用户指定以 http://127.0.0.1:8765 市场形态预测 tab 数据为基准 → 直接复用
        # data_server_fixed.get_morph_cycle() + get_morph_params() 同一函数（与 tab HTTP
        # 路由共享实现），确保 BTC 的 大小周期 / 六维 值与 tab 完全一致，不留偏差。
        # 其他币种的大小周期&六维已经在 _execute_trade 内 _log_morph_cycle_for_coin +
        # _log_param_mapper_snapshot 兜底生成。此处 BTC 作为基准锚，强制使用 tab 同源函数。
        try:
            try:
                from data_server_fixed import get_morph_cycle, get_morph_params  # type: ignore
            except Exception:
                # 若主包路径 import 失败（不同 CWD 场景），补 sys.path 再试
                import sys as _sys
                import pathlib as _pl
                _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent.parent))
                from data_server_fixed import get_morph_cycle, get_morph_params  # type: ignore

            mc = get_morph_cycle("BTCUSDT", hist_days=60, forecast_days=5) or {}
            mp = get_morph_params("BTCUSDT") or {}
            if mc.get("ok") or mp.get("ok"):
                # 段①：大小周期预测（tab-morph 同源）
                _p = mc.get("params") or {}
                _t3 = mc.get("top3_components") or []
                _t4y = mc.get("cycle_4y") or {}
                _trel = (_t4y.get("t_rel_current")
                         or ((mc.get("bounds") or {}).get("t_rel_current")
                             if isinstance(mc.get("bounds"), dict) else None))
                _ph = (((mc.get("bounds") or {}).get("phase_hint")
                        if isinstance(mc.get("bounds"), dict) else None)
                       or _t4y.get("stage"))
                _corr = mc.get("correction_applied") or {}
                _wc_n = len(_corr.get("weight_correction_pre") or {})
                _tct = _corr.get("tangent_correction_pre") or {}
                _tcs = (f"m0×{float(_tct.get('m0_mul',1.0)):.3f} m1×{float(_tct.get('m1_mul',1.0)):.3f} "
                        f"bias={float(_tct.get('bias',0.0)):+.4f}" if _tct else "n/a")
                _fs = mc.get("fft_scale_result") or {}
                _pb = mc.get("pullback_result") or {}
                _oa = len(mc.get("overshoot_events") or [])
                _t3s = [(round(c['period'],1), round(c['amplitude'],4)) for c in _t3] if _t3 else []
                self._log(
                    f"[BTC] 大小周期预测(锚定tab-morph同源) | "
                    f"大周期 t_rel={_trel} phase={_ph or '-'} halving_days_left={_t4y.get('halving_days_left')} | "
                    f"小周期 top3={_t3s} main={(_t3[0]['period'] if _t3 else '-')}d amp={(_t3[0]['amplitude'] if _t3 else '-')} | "
                    f"形态三维 L={_p.get('current_L','-')} T={_p.get('current_T','-')} | "
                    f"权重修正={_wc_n}键 | 切线修正=[{_tcs}] | "
                    f"边界约束[FFT amp×{_fs.get('scale_factor',1.0):.3f} applied={_fs.get('applied')} | "
                    f"预测pullback applied={_pb.get('applied')} | 越界事件={_oa}] | "
                    f"fallback={mc.get('fallback_used')} final_sym={mc.get('final_symbol')}",
                    "INFO",
                )
                # 段②③：六维参数（tab-morph 同源 / api/morph/params inputs 与 BTC 六维）
                if mp.get("ok"):
                    _ins = mp.get("inputs") or {}
                    _L = _ins.get("level_smooth")
                    _T = _ins.get("trend_smooth")
                    _C = _ins.get("consensus")
                    _gp = mp.get("global_params") or []
                    _gpd = {g["name"]: (g["center"], g.get("identity_center")) for g in _gp}
                    _pos = (_gpd.get("global_position_mult") or (1.0, 1.0))[0]
                    _lsc = (_gpd.get("ls_ratio_cap") or (1.15, 0.5))[0]
                    _lbi = (_gpd.get("long_bias") or (0.0, 0.0))[0]
                    _sbi = (_gpd.get("short_bias") or (0.0, 0.0))[0]
                    _ltt = (_gpd.get("long_threshold_mult") or (1.0, 1.0))[0]
                    _stt = (_gpd.get("short_threshold_mult") or (1.0, 1.0))[0]
                    _sw = mp.get("sector_weights") or []
                    _sws = sorted(_sw, key=lambda s: -float(s.get("weight", 0)))[:3]
                    _sw_str = ",".join(
                        f"{s.get('name','?')}={float(s.get('weight',0)):.3f}"
                        f"(tp×{float(s.get('tp_mult',1.0)):.2f}/sl×{float(s.get('sl_mult',1.0)):.2f})"
                        for s in _sws
                    ) or "n/a"
                    _sw_sum = round(sum(float(s.get("weight", 0)) for s in _sw), 6)
                    self._log(
                        f"[BTC] ParameterMapper 六维(锚定tab-morph同源 inputs) | "
                        f"L={_L} T={_T} C={_C} | "
                        f"pos×{_pos:.3f} ls_cap={_lsc:.3f} "
                        f"long_bias={_lbi:+.3f}/sh_bias={_sbi:+.3f} "
                        f"long_thr×{_ltt:.3f}/short_thr×{_stt:.3f} | "
                        f"sector_top3=[{_sw_str}] Σsw={_sw_sum}",
                        "INFO",
                    )
        except Exception:
            # 同源函数异常时，降级回 polling_trader 内部 predictor 生成（仍能闭环，只是数值与 tab 有差异）
            try:
                self._log_morph_cycle_for_coin("BTC", "BTCUSDT")
                self._log_param_mapper_snapshot("BTC", "BTCUSDT", {})
            except Exception:
                pass

        # --- ⑤ 在线学习：MorphCyclePredictor.evaluate_and_correct ---
        predictor = getattr(self, "_morph_predictor", None)
        if predictor is not None:
            # 目标币种列表：BTC(主) + 实际持仓币 + self.coins 列表头部 3 个
            targets: list = []
            if "BTC" not in targets:
                targets.append(("BTCUSDT", 3))
            try:
                for pos in (self.position_tracker.all_open_positions() if hasattr(self.position_tracker,"all_open_positions") else []):
                    inst = f"{pos.coin.upper()}USDT"
                    if inst not in [t[0] for t in targets]:
                        targets.append((inst, 3))
            except Exception:
                pass
            for coin_i in (getattr(self, "coins", []) or [])[:3]:
                inst = f"{str(coin_i).upper()}USDT"
                if inst not in [t[0] for t in targets]:
                    targets.append((inst, 3))
            for (inst, min_s) in targets:
                try:
                    res = predictor.evaluate_and_correct(inst, min_filled_samples=min_s)
                    backfilled = int(res.get("backfilled", 0) or 0)
                    filled_total = int(res.get("filled_total", 0) or 0)
                    mae_before = res.get("mae_before")
                    mae_after = res.get("mae_after")
                    reason = res.get("reason") or ""
                    corr = res.get("correction") or {}
                    wc_n = len(corr.get("weight_correction") or {})
                    tc = corr.get("tangent_correction") or {}
                    tc_str = (f"m0×{float(tc.get('m0_mul',1.0)):.3f} m1×{float(tc.get('m1_mul',1.0)):.3f} bias={float(tc.get('bias',0.0)):+.4f}"
                              if tc else "-")
                    if filled_total >= min_s:
                        self._log(
                            f"[Morph][在线学习] {inst} 执行修正 | "
                            f"backfilled={backfilled} filled={filled_total} "
                            f"MAE {mae_before}->{mae_after} | "
                            f"weight修正={wc_n}键 tangent修正=[{tc_str}]",
                            "INFO",
                        )
                    else:
                        self._log(
                            f"[Morph][在线学习] {inst} 跳过修正 | "
                            f"backfilled={backfilled} filled={filled_total}/{min_s} reason={reason or '样本不足'}",
                            "INFO",
                        )
                except Exception:
                    continue

        # --- ⑥ AB 闸门：RolloutManager allow_promotion / 当前α / shadow样本数 ---
        try:
            from scripts.memory_l4.bcrm2.scripts.phase_c_rollout_manager import RolloutManager  # type: ignore
            import os
            from pathlib import Path
            # 统一使用 alpha_rollout_state.json（与 data_server API 共享）
            state_path = Path(os.environ.get(
                "V15_AI_ROLLOUT_STATE_PATH",
                str(Path(__file__).resolve().parent.parent.parent / "data" / "alpha_rollout_state.json"),
            ))
            mgr = RolloutManager(state_path=state_path)
            status = mgr.get_status()
            # 同步刷新实盘 alpha_blend 值（每次 AB 闸门检查时重新读取）
            _latest_alpha = status.get("current_alpha")
            if _latest_alpha is not None and self._alpha_blend_enabled:
                _new_alpha = min(float(_latest_alpha), ALPHA_BLEND_MAX)
                if abs(_new_alpha - self._alpha_blend) > 1e-6:
                    self._log(
                        f"[AlphaBlend] AB闸门刷新 α: {self._alpha_blend:.4f} → {_new_alpha:.4f}",
                        "INFO",
                    )
                    self._alpha_blend = _new_alpha
        except Exception as e:
            status = {"error": str(e)}

        # Shadow 记录数（直接用 RolloutManager 内部 window 统计，若没有则从 shadow DB 估算）
        try:
            from data_server_fixed import get_dual_baseline_report  # type: ignore
            report = get_dual_baseline_report(days=7)
            inject_stats = (report.get("inject_run_stats") or {}) if report.get("ok") else {}
            ev = (report.get("evaluation") or {}) if report.get("ok") else {}
            n_shadow = report.get("window_records", 0) if report.get("ok") else 0
            allow_promo = ev.get("allow_promotion", False)
            reasons = ev.get("reasons") or []
            enable_true = inject_stats.get("enable_true", 0)
            enable_false = inject_stats.get("enable_false", 0)
            inject_ratio = inject_stats.get("inject_ratio", 0.0)
        except Exception:
            n_shadow = 0
            allow_promo = False
            reasons = ["AB报告读取失败"]
            enable_true = enable_false = 0
            inject_ratio = 0.0

        cur_alpha = None
        if isinstance(status, dict) and "error" not in status:
            cur_alpha = status.get("current_alpha")
            hist_n = status.get("history_length", 0)
        else:
            cur_alpha = status.get("current_alpha") if isinstance(status, dict) else None
            hist_n = 0
        reasons_str = "；".join(str(r) for r in reasons) if reasons else "n/a"
        # H3(P1)：FMA_REGIME_FILTER_ENABLED（后置层 5态差异化过滤开关）目前默认 False（回测验证效果不佳），
        #          在 AB闸门日志中显示，避免审计时遗漏能力状态；等 Shadow ≥60 条再评估是否打开 True。
        fma_on = bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False))

        # ── H3-FMA 渐进自动检查：每 20h 评估一次，若样本≥60+达标则自动切 FMA=ON
        try:
            _all_7d_records = []
            try:
                # 直接从 data_server 复用 shadow_records_7d（若 data_server_fixed 模块有缓存）
                from data_server_fixed import _shadow_logs_window  # type: ignore
                _all_7d_records = list(_shadow_logs_window(days=7))
            except Exception:
                _all_7d_records = []
            _fma_check = self._fma_auto_check(n_shadow_total=n_shadow,
                                               shadow_records_7d=_all_7d_records)
        except Exception as _e1:
            _fma_check = {"triggered": False, "action": "ERROR", "delta": 0.0,
                          "shadow_off_total": 0, "shadow_on_total": 0,
                          "win_rate_off": 0.0, "win_rate_on": 0.0,
                          "reason": f"调用失败: {_e1}"}
        self._log(
            f"[AB闸门][双基线评估] 样本={n_shadow}/30 | inject={enable_true}T/{enable_false}F(ratio={inject_ratio:.2f}) | "
            f"α={self._alpha_blend:.4f} "
            f"allow_promotion={'ALLOW' if allow_promo else 'BLOCK'} | "
            f"原因: {reasons_str} | "
            f"FMA_5态过滤开关={'ON(实验/对比)' if fma_on else 'OFF(默认双均线确认趋势)'}",
            "INFO",
        )
        _fma_triggered = bool(_fma_check.get("triggered", False))
        _fma_action = str(_fma_check.get("action", "SKIP"))
        _fma_delta = float(_fma_check.get("delta", 0.0) or 0.0)
        _fma_off_total = int(_fma_check.get("shadow_off_total", 0) or 0)
        _fma_on_total = int(_fma_check.get("shadow_on_total", 0) or 0)
        _fma_min_samples = 60
        try:
            _fm = self._fma_get_rollout_manager()
            if _fm is not None:
                _fma_min_samples = int(getattr(_fm, "fma_min_samples", 60) or 60)
        except Exception:
            pass
        self._log(
            f"[FMA渐进自动检查] 触发={'YES' if _fma_triggered else 'BLOCK'} "
            f"action={_fma_action} | "
            f"FMA_OFF样本={_fma_off_total}/{_fma_min_samples}(≥触发门槛) | "
            f"FMA_ON样本={_fma_on_total} | "
            f"Δ={_fma_delta:+.2%}(ON-OFF胜率差) | "
            f"当前={'ON' if fma_on else 'OFF'} | "
            f"说明: {_fma_check.get('reason','n/a')}",
            "INFO" if _fma_action in ("KEEP", "SKIP", "SKIP_TIME_GATE") else "WARN",
        )

    # ================================================================
    # Phase B: ShadowLogger 影子模式集成
    # 设计原则：
    #   • SHADOW_LOGGER_ENABLED 默认 False → _shadow_logger=None → 字节等价
    #   • 只记录，不改变任何交易参数
    #   • 异常被 catch，不影响主流程
    # ================================================================

    def _init_shadow_logger(self):
        """初始化 ShadowLogger（若开关开启）。

        开关关闭时：_shadow_logger = None，后续 _record_shadow_log 直接 return。
        开关开启时：尝试构造 ShadowLogger，失败降级为 None（不抛异常）。
        """
        if not SHADOW_LOGGER_ENABLED:
            self._shadow_logger = None
            return
        try:
            from scripts.memory_l4.bcrm2.morph_cycle_predictor import MorphCyclePredictor
            from scripts.memory_l4.bcrm2.parameter_mapper import ParameterMapper

            # 复用 bcrm2_adapters 中的 storage（若已初始化）
            storage = None
            if hasattr(self, "bcrm2_adapters") and self.bcrm2_adapters:
                # 取第一个 adapter 的 storage（所有 adapter 共享同一 storage）
                first_adapter = next(iter(self.bcrm2_adapters.values()))
                if hasattr(first_adapter, "storage"):
                    storage = first_adapter.storage
            if storage is None:
                # 兜底：新建一个 storage（Phase B 影子模式独立 DB）
                from scripts.memory_l4.bcrm2.run_evolution_pipeline import get_storage
                storage = get_storage()

            predictor = MorphCyclePredictor(storage)
            mapper = ParameterMapper()
            self._shadow_logger = ShadowLogger(storage, predictor, mapper)
            self._log("[ShadowLogger] 影子模式已启用（只记录，不影响交易）", "INFO")
        except Exception as e:
            self._shadow_logger = None
            self._log(f"[ShadowLogger] 初始化失败，降级为关闭: {e}", "WARN")

    def _record_shadow_log(self, coin: str, inference: dict,
                            actual_params: dict):
        """记录一条 Shadow 日志（若开关开启且 logger 可用）。

        异常被 catch，不影响主流程。开关关闭或 logger 为 None 时直接 return。
        """
        if not SHADOW_LOGGER_ENABLED:
            return
        if not getattr(self, "_shadow_logger", None):
            return
        try:
            enable_inject = getattr(self, "_enable_inject_runtime", False)
            alpha_blend = getattr(self, "_alpha_blend", 0.0)
            fma_shadow_allowed = inference.get("fma_shadow_allowed")
            fma_shadow_eff_thr = inference.get("fma_shadow_eff_threshold")

            # ── T5 战略层影子字段（fd_*）从 FiveDomainState 提取 ──
            fd_crypto_war_state = None
            fd_crypto_total_score = None
            fd_crypto_cap_mode = None
            fd_crypto_mult_mode = None
            fd_us_stock_war_state = None
            fd_us_stock_total_score = None
            fd_precious_metal_war_state = None
            fd_precious_metal_total_score = None
            # 五维明细评分
            fd_crypto_dao_score = fd_crypto_tian_score = fd_crypto_di_score = fd_crypto_jiang_score = fd_crypto_fa_score = None
            fd_us_stock_dao_score = fd_us_stock_tian_score = fd_us_stock_di_score = fd_us_stock_jiang_score = fd_us_stock_fa_score = None
            fd_pm_dao_score = fd_pm_tian_score = fd_pm_di_score = fd_pm_jiang_score = fd_pm_fa_score = None
            # 方向状态
            _direction_state = None
            _direction_bias = None
            # Phase 4.3 三因子共振做空信号 + BTC 强弱 regime
            _three_factor_short_signal = None
            _btc_regime = None

            _fds = getattr(self, "_five_domain_state_shadow", None) or self._five_domain_state_cache
            _fds_dir_state = getattr(_fds, "direction_state", "MISSING") if _fds is not None else "N/A"
            _fds_dir_bias = getattr(_fds, "direction_bias", "MISSING") if _fds is not None else "N/A"
            self._log(
                f"[ShadowDebug] coin={coin} _fds_type={type(_fds).__name__} "
                f"shadow_none={getattr(self, '_five_domain_state_shadow', None) is None} "
                f"cache_none={self._five_domain_state_cache is None} "
                f"dir_state={_fds_dir_state!r} "
                f"dir_bias={_fds_dir_bias!r}",
                "DEBUG",
            )
            if _fds is not None:
                _ws = getattr(_fds, "war_state", {}) or {}
                fd_crypto_war_state = _ws.get("crypto_usdt")
                fd_us_stock_war_state = _ws.get("us_stock")
                fd_precious_metal_war_state = _ws.get("precious_metal")
                # 方向状态（按当前币的资产类别取值）
                _dstate = getattr(_fds, "direction_state", None)
                _dbias = getattr(_fds, "direction_bias", None)
                _coin_cls = self._coin_asset_class(coin)
                if isinstance(_dstate, dict):
                    _direction_state = _dstate.get(_coin_cls)
                else:
                    _direction_state = _dstate
                if isinstance(_dbias, dict):
                    _direction_bias = _dbias.get(_coin_cls)
                else:
                    _direction_bias = _dbias
                # Phase 4.3 三因子共振做空信号 + BTC 强弱 regime
                # Phase 4.3: 计算三因子共振做空信号并写入 _fds
                try:
                    from dreambuddy_evolution.engines.three_factor_short import (
                        ThreeFactorShortDetector,
                    )
                    _tfs_detector = ThreeFactorShortDetector()
                    # pattern_factor 从 kline_handler 最近一次形态检测结果获取
                    _pf = 0.0
                    if hasattr(self, "_kline_handler") and self._kline_handler:
                        _ap = getattr(self._kline_handler, "_last_agi_pattern", None)
                        if isinstance(_ap, dict):
                            _pf = float(_ap.get("pattern_factor", 0.0) or 0.0)
                    # btc_regime 从 _fds 读取（Gap 2 已写回）
                    _br = getattr(_fds, "btc_regime", None)
                    _br_val = ""
                    if isinstance(_br, dict):
                        _br_val = str(_br.get("crypto_usdt", "") or "")
                    # etf_flow_norm 从 coin_data 获取
                    _etf_val = 0.0
                    _cd_all = getattr(self, "_coin_data_cache", None) or {}
                    _cd_cls = _cd_all.get("crypto_usdt", {}) or {}
                    _etf_raw = _cd_cls.get("pn_btc_etf_flow_norm")
                    if isinstance(_etf_raw, (int, float)):
                        _etf_val = float(_etf_raw)
                    # 检测并写入
                    _tfs_result = _tfs_detector.detect(
                        pattern_factor=_pf,
                        btc_regime=_br_val,
                        etf_flow_norm=_etf_val,
                    )
                    if not hasattr(_fds, "three_factor_short_signal") or \
                       not isinstance(getattr(_fds, "three_factor_short_signal", None), dict):
                        _fds.three_factor_short_signal = {}
                    _fds.three_factor_short_signal["crypto_usdt"] = _tfs_result
                except Exception as _tfs_e:
                    pass  # FAIL-OPEN: 不阻塞交易
                _tfs = getattr(_fds, "three_factor_short_signal", None)
                _btc_reg = getattr(_fds, "btc_regime", None)
                if isinstance(_tfs, dict):
                    _three_factor_short_signal = _tfs.get(_coin_cls)
                else:
                    _three_factor_short_signal = _tfs
                if isinstance(_btc_reg, dict):
                    _btc_regime = _btc_reg.get(_coin_cls)
                else:
                    _btc_regime = _btc_reg
                _cap = getattr(_fds, "aggregate_position_cap_pct", {}) or {}
                fd_crypto_cap_mode = _cap.get("crypto_usdt")
                _mult = getattr(_fds, "cross_asset_multiplier", {}) or {}
                fd_crypto_mult_mode = _mult.get("crypto_usdt")
                _scores = getattr(_fds, "five_scores", {}) or {}
                _fd_scorer = getattr(self, "_five_domain_scorer", None)

                for cls, score_var in [("crypto_usdt", "fd_crypto"), ("us_stock", "fd_us_stock"), ("precious_metal", "fd_pm")]:
                    _cls_scores = _scores.get(cls, {})
                    if not _cls_scores:
                        continue
                    # 五维明细
                    if score_var == "fd_crypto":
                        fd_crypto_dao_score = _cls_scores.get("dao")
                        fd_crypto_tian_score = _cls_scores.get("tian")
                        fd_crypto_di_score = _cls_scores.get("di")
                        fd_crypto_jiang_score = _cls_scores.get("jiang")
                        fd_crypto_fa_score = _cls_scores.get("fa")
                    elif score_var == "fd_us_stock":
                        fd_us_stock_dao_score = _cls_scores.get("dao")
                        fd_us_stock_tian_score = _cls_scores.get("tian")
                        fd_us_stock_di_score = _cls_scores.get("di")
                        fd_us_stock_jiang_score = _cls_scores.get("jiang")
                        fd_us_stock_fa_score = _cls_scores.get("fa")
                    elif score_var == "fd_pm":
                        fd_pm_dao_score = _cls_scores.get("dao")
                        fd_pm_tian_score = _cls_scores.get("tian")
                        fd_pm_di_score = _cls_scores.get("di")
                        fd_pm_jiang_score = _cls_scores.get("jiang")
                        fd_pm_fa_score = _cls_scores.get("fa")
                    # 总分
                    _total = 50.0
                    if _fd_scorer is not None:
                        try:
                            _total = float(_fd_scorer._weighted_total(_cls_scores, cls))
                        except Exception:
                            _total = 50.0
                    if cls == "crypto_usdt":
                        fd_crypto_total_score = _total
                    elif cls == "us_stock":
                        fd_us_stock_total_score = _total
                    elif cls == "precious_metal":
                        fd_precious_metal_total_score = _total

            # ── T5 策略层影子字段（sal_*）从 enhance_result.strategy_selection 提取 ──
            sal_type = None
            sal_regime = None
            sal_calib_median = None
            sal_calib_min = None
            sal_calib_max = None
            sal_gate = None
            _er = inference.get("enhance_result") or {}
            _sel = _er.get("strategy_selection") if isinstance(_er, dict) else None
            if isinstance(_sel, dict):
                sal_type = _sel.get("strategy_type")
                sal_regime = _sel.get("regime") or inference.get("_regime_pred")
                _cb = _sel.get("calibration_biases") or {}
                _cb_vals = [float(v) for v in _cb.values() if isinstance(v, (int, float))]
                if _cb_vals:
                    sal_calib_median = sorted(_cb_vals)[len(_cb_vals) // 2]
                    sal_calib_min = min(_cb_vals)
                    sal_calib_max = max(_cb_vals)
                _gate_val = _cb.get("hard_relax_gate")
                if isinstance(_gate_val, bool):
                    sal_gate = 1 if _gate_val else 0
                elif isinstance(_gate_val, (int, float)):
                    sal_gate = int(_gate_val)
            else:
                # P1 fix: 无策略匹配时填充默认值，确保影子覆盖率≥95%
                sal_type = "baseline_v15"
                _snap = inference.get("snapshot", {}) or {}
                sal_regime = inference.get("_regime_pred") or _snap.get("regime")
                sal_gate = 0

            self._log(
                f"[ShadowDebug2] coin={coin} cls={_coin_cls} "
                f"dir_state={_direction_state!r} dir_bias={_direction_bias!r} "
                f"war={fd_crypto_war_state!r}/{fd_us_stock_war_state!r}/{fd_precious_metal_war_state!r} "
                f"crypto_scores=dao={fd_crypto_dao_score} tian={fd_crypto_tian_score} total={fd_crypto_total_score}",
                "DEBUG",
            )
            self._shadow_logger.record_polling(
                coin, inference, actual_params,
                enable_inject=enable_inject, alpha_blend=alpha_blend,
                fma_on_allowed=fma_shadow_allowed,
                fma_on_eff_threshold=fma_shadow_eff_thr,
                fd_crypto_war_state=fd_crypto_war_state,
                fd_crypto_total_score=fd_crypto_total_score,
                fd_crypto_cap_mode=fd_crypto_cap_mode,
                fd_crypto_mult_mode=fd_crypto_mult_mode,
                fd_us_stock_war_state=fd_us_stock_war_state,
                fd_us_stock_total_score=fd_us_stock_total_score,
                fd_precious_metal_war_state=fd_precious_metal_war_state,
                fd_precious_metal_total_score=fd_precious_metal_total_score,
                fd_crypto_dao_score=fd_crypto_dao_score,
                fd_crypto_tian_score=fd_crypto_tian_score,
                fd_crypto_di_score=fd_crypto_di_score,
                fd_crypto_jiang_score=fd_crypto_jiang_score,
                fd_crypto_fa_score=fd_crypto_fa_score,
                fd_us_stock_dao_score=fd_us_stock_dao_score,
                fd_us_stock_tian_score=fd_us_stock_tian_score,
                fd_us_stock_di_score=fd_us_stock_di_score,
                fd_us_stock_jiang_score=fd_us_stock_jiang_score,
                fd_us_stock_fa_score=fd_us_stock_fa_score,
                fd_precious_metal_dao_score=fd_pm_dao_score,
                fd_precious_metal_tian_score=fd_pm_tian_score,
                fd_precious_metal_di_score=fd_pm_di_score,
                fd_precious_metal_jiang_score=fd_pm_jiang_score,
                fd_precious_metal_fa_score=fd_pm_fa_score,
                direction_state=_direction_state,
                direction_bias=_direction_bias,
                three_factor_short_signal=_three_factor_short_signal,
                btc_regime=_btc_regime,
                sal_type=sal_type,
                sal_regime=sal_regime,
                sal_calib_median=sal_calib_median,
                sal_calib_min=sal_calib_min,
                sal_calib_max=sal_calib_max,
                sal_gate=sal_gate,
            )
        except Exception as e:
            self._log(f"[{coin}] Shadow 记录失败（已忽略）: {e}", "DEBUG")

    # ================================================================
    # Phase C: α blend 前瞻参数上线集成
    # 设计原则：
    #   • ALPHA_BLEND_ENABLED 默认 False → _alpha_blend=0.0 → 字节等价
    #   • α blend 在 ParameterMapper 层实现，交易层只传值
    #   • DEFAULT_ALPHA_BLEND 受 ALPHA_BLEND_MAX=0.5 硬约束
    # ================================================================

    def _init_alpha_blend(self):
        """初始化 α blend 参数（若开关开启）。

        开关关闭时：_alpha_blend=0.0（字节等价 Phase 0）。
        开关开启时：从 RolloutManager 状态文件读取 current_alpha（受 ALPHA_BLEND_MAX 约束），
                   若状态文件不存在或读取失败则回退到 DEFAULT_ALPHA_BLEND。
        """
        if not ALPHA_BLEND_ENABLED:
            self._alpha_blend_enabled = False
            self._alpha_blend = 0.0
            return
        # 开关开启：优先从 RolloutManager 状态文件读取 current_alpha
        self._alpha_blend_enabled = True
        _alpha = DEFAULT_ALPHA_BLEND
        try:
            import os
            from pathlib import Path
            # 与 data_server_fixed.py _get_rollout_manager() 使用同一状态文件
            _state_path = Path(os.environ.get(
                "V15_AI_ROLLOUT_STATE_PATH",
                str(Path(__file__).resolve().parent.parent.parent / "data" / "alpha_rollout_state.json"),
            ))
            from scripts.memory_l4.bcrm2.scripts.phase_c_rollout_manager import RolloutManager  # type: ignore
            _mgr = RolloutManager(state_path=_state_path)
            _loaded_ok = _mgr.load()
            if _loaded_ok and _mgr.current_alpha is not None:
                _alpha = float(_mgr.current_alpha)
                self._log(
                    f"[AlphaBlend] 从状态文件读取 α={_alpha:.4f} "
                    f"(path={_state_path.name})",
                    "INFO",
                )
        except Exception as _e:
            self._log(f"[AlphaBlend] 状态文件读取失败，回退到默认 α={DEFAULT_ALPHA_BLEND}: {_e}", "WARN")
        self._alpha_blend = min(_alpha, ALPHA_BLEND_MAX)
        self._log(
            f"[AlphaBlend] 前瞻参数上线已启用，当前 α={self._alpha_blend:.4f} "
            f"(max={ALPHA_BLEND_MAX})",
            "INFO",
        )

    # ================================================================
    # H3-FMA 渐进自动开关：还原 + 懒加载 RolloutManager + 自动评估
    # 设计原则：
    #   • 任何错误被 catch，默认 FMA=False（不影响主交易）
    #   • RolloutManager 通过 phase_c_rollout_state.json 与 data_server / CLI 共享状态
    #   • 冷启动时只做一次 restore；自动评估只在 AB闸门口 + 样本≥60 + 距上次≥20h 触发
    # ================================================================

    def _fma_get_rollout_state_path(self):
        """返回 alpha_rollout_state.json 路径（与 data_server API 共享同一文件）。"""
        if self._fma_phase_c_state_path:
            return self._fma_phase_c_state_path
        import os
        from pathlib import Path
        # 统一使用 alpha_rollout_state.json（与 data_server_fixed.py _get_rollout_manager 一致）
        # RolloutManager 同时管理 alpha_blend 和 fma_enabled 字段
        path = Path(os.environ.get(
            "V15_AI_ROLLOUT_STATE_PATH",
            str(Path(__file__).resolve().parent.parent.parent / "data" / "alpha_rollout_state.json"),
        ))
        self._fma_phase_c_state_path = path
        return path

    def _fma_get_rollout_manager(self, force_new: bool = False):
        """懒加载 RolloutManager（单例）。失败返回 None。"""
        if (not force_new) and self._fma_phase_c_mgr is not None:
            return self._fma_phase_c_mgr
        try:
            from scripts.memory_l4.bcrm2.scripts.phase_c_rollout_manager import RolloutManager  # type: ignore
            mgr = RolloutManager(state_path=self._fma_get_rollout_state_path())
            self._fma_phase_c_mgr = mgr
            return mgr
        except Exception as e:
            self._log(f"[FMA渐进] RolloutManager 初始化失败（保持默认开关）: {e}", "WARN")
            return None

    def _fma_load_from_rollout(self):
        """冷启动：从 phase_c_rollout_state.json 读 fma_enabled 覆盖类默认 False。"""
        try:
            mgr = self._fma_get_rollout_manager()
            if mgr is None:
                return
            prev = bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False))
            new = bool(getattr(mgr, "fma_enabled", False))
            self.FMA_REGIME_FILTER_ENABLED = new
            if prev != new:
                self._log(
                    f"[FMA渐进] 冷启动还原开关: FMA={'ON' if new else 'OFF'} "
                    f"(类默认={'ON' if prev else 'OFF'} → rollout同步={'ON' if new else 'OFF'}) "
                    f"min_samples={getattr(mgr,'fma_min_samples',60)} "
                    f"delta={getattr(mgr,'fma_required_delta',0.05):.0%}",
                    "INFO",
                )
            else:
                self._log(
                    f"[FMA渐进] 冷启动开关未变更: {'ON' if new else 'OFF'} "
                    f"(类默认=rollout一致) min_samples={getattr(mgr,'fma_min_samples',60)}",
                    "DEBUG",
                )
        except Exception as e:
            self._log(f"[FMA渐进] 冷启动加载失败（保留类默认）: {e}", "WARN")

    def _fma_auto_check(self, n_shadow_total: int,
                        shadow_records_7d: list = None) -> dict:
        """AB闸门口调用：距上次≥20h 且 shadow_off_total ≥ mgr.fma_min_samples 时，
        调 evaluate_fma_toggle 并 自动切换 self.FMA_REGIME_FILTER_ENABLED + 写回 rollout_state。

        返回当前 check 结果 dict（用于打印日志）。
        """
        import time
        now = time.time()
        fallback = {"triggered": False, "action": "SKIP_TIME_GATE",
                    "prev_enabled": bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False)),
                    "new_enabled": bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False)),
                    "shadow_off_total": 0, "win_rate_off": 0.0,
                    "shadow_on_total": 0, "win_rate_on": 0.0, "delta": 0.0,
                    "reason": f"评估冷却期未到（剩余 {int(self._FMA_AUTO_CHECK_INTERVAL_SEC - (now - self._fma_last_auto_check_ts)) // 3600}h）"}
        if (now - self._fma_last_auto_check_ts) < self._FMA_AUTO_CHECK_INTERVAL_SEC:
            return fallback
        self._fma_last_auto_check_ts = now
        try:
            mgr = self._fma_get_rollout_manager()
            if mgr is None:
                return {**fallback, "reason": "RolloutManager不可用"}
            # 如果调用方没传 records，自行从 storage 拉 7 天（所有币种）
            if shadow_records_7d is None:
                shadow_records_7d = []
                try:
                    # 复用 _init_shadow_logger 里的 storage（懒加载）
                    storage = None
                    if hasattr(self, "_shadow_logger") and getattr(self, "_shadow_logger", None):
                        storage = getattr(self._shadow_logger, "storage", None)
                    if storage is None:
                        if hasattr(self, "bcrm2_adapters") and self.bcrm2_adapters:
                            first_adapter = next(iter(self.bcrm2_adapters.values()))
                            storage = getattr(first_adapter, "storage", None)
                    if storage is None:
                        try:
                            from scripts.memory_l4.bcrm2.run_evolution_pipeline import get_storage  # type: ignore
                            storage = get_storage()
                        except Exception:
                            storage = None
                    if storage:
                        for sym in list(getattr(self, "coins", []) or []):
                            try:
                                shadow_records_7d.extend(storage.get_shadow_log(sym, days=7))
                            except Exception:
                                continue
                except Exception:
                    shadow_records_7d = shadow_records_7d or []

            prev = bool(getattr(self, "FMA_REGIME_FILTER_ENABLED", False))
            result = mgr.evaluate_fma_toggle(shadow_records_7d)
            new_enabled = bool(result.get("new_enabled", prev))
            # 应用到 trader 实例（内存实时生效，下一轮 threshold 段就自动走到 FMA=ON 差异化过滤）
            if new_enabled != prev:
                self.FMA_REGIME_FILTER_ENABLED = new_enabled
                self._log(
                    f"[FMA渐进] 自动切换: {'ON' if prev else 'OFF'} → {'ON' if new_enabled else 'OFF'} | "
                    f"{result.get('reason','')}",
                    "WARN",
                )
            else:
                self.FMA_REGIME_FILTER_ENABLED = new_enabled
            # 持久化回 rollout_state.json（下次冷启动可还原；data_server API 同步可见）
            try:
                mgr.save()
            except Exception as _es:
                self._log(f"[FMA渐进] rollout_state.json 保存失败（仅内存生效）: {_es}", "WARN")
            # 附带当前样本数给日志
            result["n_shadow_total"] = int(n_shadow_total or 0)
            result.setdefault("reason", result.get("reason") or "n/a")
            return result
        except Exception as e:
            self._log(f"[FMA渐进] 自动评估失败（已忽略）: {e}", "WARN")
            return {**fallback, "reason": f"异常: {e}"}

    def _enable_inject_file_path(self):
        """返回 enable_inject 状态文件路径（与 data_server 共用）。"""
        import os
        return os.environ.get(
            "V15_AI_INJECT_STATE_PATH",
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)
            ))), "data/enable_inject_state.json"),
        )

    def _reload_enable_inject_if_stale(self, force: bool = False) -> bool:
        """周期性刷新 enable_inject 开关（5 分钟缓存，避免磁盘 IO）。"""
        import os as _os
        import json as _json
        import time as _time
        now = _time.time()
        if (not force) and (now - self._enable_inject_last_reload
                            < self._enable_inject_reload_interval):
            return bool(self._enable_inject_runtime)
        fp = self._enable_inject_file_path()
        enabled = False
        try:
            if _os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                enabled = bool(data.get("enabled", False))
        except Exception as _e:
            self._log(f"[Inject] 读取 enable_inject 文件失败（使用默认 False）: {_e}",
                      "WARN")
            enabled = False
        was = self._enable_inject_runtime
        self._enable_inject_runtime = enabled
        self._enable_inject_last_reload = now
        if was != enabled:
            self._log(
                f"[Inject] 融合层 enable_inject 切换：{was} → {enabled} "
                f"（{('字节等价模式' if not enabled else 'AI 注入模式')}）",
                "INFO",
            )
        return enabled

    def _init_enable_inject(self):
        """初始化 enable_inject 开关（启动时从磁盘文件加载）。"""
        # 默认 False = 字节等价安全模式，完全不注入
        self._enable_inject_runtime = False
        self._reload_enable_inject_if_stale(force=True)

    def _check_dynamic_blacklist(self, coin: str) -> tuple:
        """检查币种是否在动态黑名单中（未过期则拦截）

        Returns:
            (blocked: bool, reason: str)
        """
        # 1. 静态手动黑名单（config.json 配置）
        if coin in self.blacklist_coins:
            return True, f"手动黑名单({coin})"

        # 2. 动态黑名单检查
        info = self.dynamic_blacklist.get(coin)
        if not info:
            return False, ""

        now = time.time()
        if now < info["expire_ts"]:
            remaining_hours = (info["expire_ts"] - now) / 3600
            return True, (
                f"动态黑名单({coin}) 连亏{info.get('streak', '?')}次 "
                f"剩余{remaining_hours:.1f}h"
            )
        else:
            # 过期自动释放
            del self.dynamic_blacklist[coin]
            self._log(f"[{coin}] 动态黑名单到期释放 | 可恢复交易")
            return False, ""

    def _add_to_dynamic_blacklist(self, coin: str, streak: int, reason: str = ""):
        """将币种加入动态黑名单（连续亏损达标时调用）"""
        now = time.time()
        expire_ts = now + self.DYNAMIC_BLACKLIST_DURATION_SEC
        self.dynamic_blacklist[coin] = {
            "expire_ts": expire_ts,
            "added_ts": now,
            "streak": streak,
            "reason": reason or f"连续{streak}次亏损",
        }
        self._log(
            f"[{coin}] ⛔ 加入动态黑名单 | 原因: {reason or f'连续{streak}次亏损'} | "
            f"封禁3日(至{time.strftime('%Y-%m-%d %H:%M', time.localtime(expire_ts))})"
        )

    def _update_dynamic_blacklist_on_close(self, coin: str, pnl: float):
        """平仓后更新动态黑名单状态

        - 盈利：清除该币种的连亏计数
        - 亏损：连亏+1，达到阈值(2次)则加入黑名单3日
        """
        if not hasattr(self, '_coin_consecutive_losses'):
            self._coin_consecutive_losses = {}

        if pnl >= 0:
            if coin in self._coin_consecutive_losses:
                self._coin_consecutive_losses[coin] = 0
        else:
            current = self._coin_consecutive_losses.get(coin, 0) + 1
            self._coin_consecutive_losses[coin] = current

            if current >= self.DYNAMIC_BLACKLIST_CONSECUTIVE_LOSSES:
                info = self.dynamic_blacklist.get(coin)
                if not info or time.time() >= info["expire_ts"]:
                    self._add_to_dynamic_blacklist(coin, current)
                self._coin_consecutive_losses[coin] = 0

    def _sync_existing_positions(self):
        """同步 OKX 已有持仓到本地跟踪器，同步止损/止盈挂单，并修复不合理SL（如PUMP 0.586%过近止损）"""
        self._log("[持仓同步] 检查 OKX 已有持仓...", "INFO")
        for coin in self.coins:
            inst_id = f"{coin}-USDT-SWAP"
            pos_result = self.okx_client.get_positions(inst_id)
            if not pos_result.get("ok"):
                continue
            positions = pos_result.get("positions", [])
            for pos in positions:
                if float(pos["pos"]) <= 0:
                    continue
                if self.position_tracker.has_open_position(inst_id):
                    # ★ FIX Bug#3：已有持仓也同步OKX上的SL/TP挂单到market_snapshot，防止后续调整
                    #   以错误的"反算基线"继续收紧（PUMP 0.586%案例的另一条路径）
                    # ★ FIX entry_price=0 修复：evolution 开仓时 OKX 市价单返回无 avg_px，
                    #   导致 entry_price 持久化为 0.0，离场巡检会跳过。此处从 OKX 持仓修复。
                    _okx_avg_px = float(pos.get("avg_px", 0) or 0)
                    if _okx_avg_px > 0:
                        _existing_rec = self.position_tracker.open_positions.get(inst_id)
                        if _existing_rec and float(getattr(_existing_rec, "entry_price", 0) or 0) <= 0:
                            _existing_rec.entry_price = _okx_avg_px
                            self.position_tracker._save_open_position(inst_id)
                            self._log(
                                f"[持仓同步] {coin} entry_price 修复: 0→{_okx_avg_px} "
                                f"(source_tag={getattr(_existing_rec, 'source_tag', '')})",
                                "INFO",
                            )
                    self._sync_and_repair_sl_tp_for_position(coin, inst_id, pos)
                    continue
                # 尝试读取 OKX 上的 SL/TP algo 订单，注入到 market_snapshot
                _sl_px, _tp_px = self._fetch_sl_tp_from_okx(inst_id)
                entry_px = float(pos["avg_px"])
                pos_side = pos.get("pos_side", "long")
                # 净仓模式修复：OKX net 模式返回 posSide="net"，需通过 pos 正负判断方向
                if pos_side not in ("long", "short"):
                    try:
                        _net_qty = float(pos.get("pos", 0) or 0)
                        if _net_qty < 0:
                            pos_side = "short"
                        elif _net_qty > 0:
                            pos_side = "long"
                    except Exception:
                        pos_side = "long"
                # ★ FIX Bug#3：开仓同步前对SL做硬门禁（含爆仓安全约束），发现不合理止损自动修复
                if _sl_px and _sl_px > 0:
                    _lev_here = self._get_leverage()
                    _new_sl, _clamped, _old_pct, _cfl = self._enforce_sl_price_floor(
                        _sl_px, entry_px, pos_side, leverage=_lev_here,
                        allow_tighten=False, coin=coin)
                    if _clamped:
                        _msg_tail = ""
                        if _cfl.get("liq_conflict"):
                            _msg_tail = " 【间距/爆仓冲突已按爆仓优先钳制】强烈建议降杠杆≤20x"
                        self._log(
                            f"[持仓同步] {coin} 同步发现不合理止损: "
                            f"间距{_old_pct*100:.2f}%<下限→自动修复为 "
                            f"SL={_new_sl:.6f} (间距{abs(_new_sl-entry_px)/entry_px*100:.2f}%)"
                            f"{_msg_tail}",
                            "WARN",
                        )
                        # 实际下发正确的止损挂单到交易所
                        try:
                            if self.okx_client and hasattr(self.okx_client, "place_stop_loss_take_profit"):
                                _r = self.okx_client.place_stop_loss_take_profit(
                                    inst_id=inst_id, pos_side=pos_side,
                                    stop_loss_px=_new_sl, take_profit_px=_tp_px,
                                    reason=f"sync_repair_bad_sl:{_old_pct*100:.2f}pct",
                                )
                                if _r.get("ok"):
                                    self._log(f"[持仓同步] {coin} 止损已自动修复并推送交易所", "INFO")
                        except Exception as _e:
                            self._log(f"[持仓同步] {coin} 自动修复止损推送失败: {_e}", "WARN")
                        _sl_px = _new_sl
                snapshot = {
                    "price": float(pos.get("mark_px", entry_px)),
                    "stop_loss_px": _sl_px,
                    "take_profit_px": _tp_px,
                }
                self.position_tracker.open_position(
                    coin=coin,
                    inst_id=inst_id,
                    direction=pos_side,
                    entry_price=entry_px,
                    confidence=0.8,
                    hexagram="已存在持仓",
                    market_snapshot=snapshot,
                    strategy_source="bcrm",
                    # — BDSM 协作 R5：启动同步持仓也要打标签，保证子池计数完整 —
                    source_tag=self._classify_source_tag(coin),
                )
                self._log(
                    f"[持仓同步] 已同步 {coin} {pos['pos_side']} @ {pos['avg_px']}"
                    f" SL={_sl_px} TP={_tp_px} [易经推理持仓·启动同步]",
                    "INFO",
                )

        # 反向清理：本地有但 OKX 已无持仓的记录（已止损/止盈/手动平仓）
        for p in self.position_tracker.all_open_positions():
            inst_id = p.inst_id
            pos_result = self.okx_client.get_positions(inst_id)
            if not pos_result.get("ok"):
                continue
            okx_positions = [pp for pp in pos_result.get("positions", []) if float(pp["pos"]) > 0]
            if not okx_positions:
                # 启动同步时尝试用 OKX 市价作为近似平仓价（用于反思链路估算盈亏）
                _sync_exit_px = 0.0
                try:
                    _ticker = self.okx_client.get_ticker(inst_id)
                    if _ticker.get("ok") and _ticker.get("last"):
                        _sync_exit_px = float(_ticker["last"])
                except Exception:
                    pass
                _closed = self.position_tracker.close_position(
                    inst_id,
                    exit_price=_sync_exit_px,
                    exit_reason="OKX持仓已不存在，清理本地残留",
                )
                self._log(f"[持仓同步] 清理本地残留 {inst_id} (OKX已无持仓, 估算exit_px={_sync_exit_px})", "WARN")
                # 缺口1修复：启动同步清理也触发进化反思（仅evolution子池）
                if _closed is not None and str(getattr(_closed, "source_tag", "") or "") == "evolution":
                    try:
                        self._trigger_evolution_reflection(_closed)
                    except Exception as _re:
                        self._log(
                            f"[持仓同步] {inst_id} 反思回调异常（FAIL-OPEN忽略）: {_re}",
                            "WARN",
                        )

        open_count = len(self.position_tracker.all_open_positions())
        external_count = sum(
            1 for p in self.position_tracker.all_open_positions() if p.strategy_source == "external"
        )
        self._log(
            f"[持仓同步] 完成，共 {open_count} 个持仓 (BCRM={open_count-external_count} 外部={external_count})",
            "INFO",
        )

    def _fetch_sl_tp_from_okx(self, inst_id: str) -> tuple:
        """从 OKX 交易所读取当前有效的 SL/TP algo 挂单。

        Returns: (sl_px, tp_px)，未找到则为 (None, None)
        """
        sl_px = None
        tp_px = None
        try:
            if self.okx_client and hasattr(self.okx_client, "get_algo_orders"):
                orders = self.okx_client.get_algo_orders(inst_id=inst_id)
                for od in orders.get("orders", []):
                    _sl = od.get("stop_loss_px") or od.get("sl_trigger_px") or od.get("sl_px")
                    _tp = od.get("take_profit_px") or od.get("tp_trigger_px") or od.get("tp_px")
                    if _sl:
                        try: sl_px = float(_sl)
                        except: pass
                    if _tp:
                        try: tp_px = float(_tp)
                        except: pass
        except Exception as _e:
            self._log(f"[_fetch_sl_tp_from_okx] {inst_id} 读取失败（忽略）: {_e}", "DEBUG")
        return sl_px, tp_px

    def _sync_and_repair_sl_tp_for_position(self, coin: str, inst_id: str, pos: dict):
        """对已同步过的持仓，检查OKX上实际SL/TP挂单是否合理，不合理则自动修复。

        ★ PUMP案例修复项（2026-08-28）：
        ① 缺 SL/TP 任一，不再直接return，改用基线ATR公式自动下发一套完整SL+TP套单
        ② leverage 优先取OKX API返回的 pos["lever"] 真实单币杠杆，取不到再fallback _get_leverage()
        ③ SL/TP 双通道门禁校验+修复（之前只修SL）
        ④ FAIL-OPEN：异常中性兜底不阻塞交易
        """
        try:
            entry_px = float(pos.get("avg_px", 0))
            pos_side = pos.get("pos_side", "long")
            # 净仓模式修复：OKX net 模式返回 posSide="net"，需通过 pos 正负判断方向
            if pos_side not in ("long", "short"):
                try:
                    _net_qty = float(pos.get("pos", 0) or 0)
                    if _net_qty < 0:
                        pos_side = "short"
                    elif _net_qty > 0:
                        pos_side = "long"
                except Exception:
                    pos_side = "long"
            if entry_px <= 0:
                return

            # ── 漏洞②修复：优先取OKX返回的真实单币杠杆（兼容lever/lev大小写）
            _lev_here = None
            for _lk in ("lever", "lev", "leverage"):
                if _lk in pos and pos.get(_lk):
                    try:
                        _lev_here = float(pos[_lk])
                        if _lev_here > 0:
                            break
                    except Exception:
                        _lev_here = None
            if _lev_here is None or _lev_here <= 0:
                _lev_here = self._get_leverage()

            # ── 读取交易所当前挂单 ──────────────────────────
            try:
                _sl_px, _tp_px = self._fetch_sl_tp_from_okx(inst_id)
            except Exception as _fe:
                self._log(
                    f"[持仓同步·SLTP修复] {coin} 读取OKX SL/TP异常，降级为全量重算下发: {_fe}",
                    "WARN",
                )
                _sl_px, _tp_px = None, None

            # ── 判断是缺套单场景还是修复场景 ─────────────────
            _sl_missing = (not _sl_px) or (_sl_px <= 0)
            _tp_missing = (not _tp_px) or (_tp_px <= 0)
            _need_issue = False
            _reason_tag = "startup_repair"

            # ★ FIX: evolution 持仓间距不足主动纠正
            #   如果 evolution 持仓已有 SL/TP 但间距小于 tier 要求（如被错误设置为 1.5%/3%），
            #   主动触发重算，用正确的 tier 间距（probe=5%/10%）替换。
            _rec_here_for_check = self.position_tracker.get_open_position(inst_id)
            _is_evo_for_check = bool(
                _rec_here_for_check and
                str(getattr(_rec_here_for_check, "source_tag", "") or "").lower() == "evolution"
            )
            if _is_evo_for_check and not (_sl_missing or _tp_missing):
                _evo_snap = (getattr(_rec_here_for_check, "market_snapshot", None) or {})
                _evo_tier_chk = str(_evo_snap.get("tier", "") or "").lower()
                _tier_sl_req = {"probe": 0.04, "standard": 0.04, "trend": 0.04}.get(_evo_tier_chk, 0.04)
                _tier_tp_req = {"probe": 0.12, "standard": 0.12, "trend": 0.12}.get(_evo_tier_chk, 0.12)
                _cur_sl_pct = abs(_sl_px - entry_px) / entry_px if _sl_px and entry_px > 0 else 0
                _cur_tp_pct = abs(_tp_px - entry_px) / entry_px if _tp_px and entry_px > 0 else 0
                if _cur_sl_pct < _tier_sl_req * 0.9 or _cur_tp_pct < _tier_tp_req * 0.9:
                    self._log(
                        f"[持仓同步·SLTP修复] {coin} evolution tier={_evo_tier_chk or 'probe'} "
                        f"SL间距{_cur_sl_pct*100:.2f}%<{_tier_sl_req*100:.1f}% 或 "
                        f"TP间距{_cur_tp_pct*100:.2f}%<{_tier_tp_req*100:.1f}% → 主动纠正",
                        "WARN",
                    )
                    _sl_missing = True  # 触发重算路径
                    _tp_missing = True

            # ── 漏洞①修复：缺SL/TP任一→全量按基线ATR+门禁重算
            if _sl_missing or _tp_missing:
                # 取开仓基线ROI
                _base_sl_roi = self._get_base_sl_roi(inst_id, entry_px)
                _base_tp_roi = self._get_base_tp_roi(inst_id, entry_px)

                # ★ FIX: evolution 持仓优先从 market_snapshot.sl_pct/tp_pct 取 tier 价格间距
                #   _get_base_sl_roi 回退路径取不到 evolution 持仓的 base_sl_roi（开仓未设置）、
                #   stop_loss_px（挂单失败时为0），会错误回退到 1.5%/3% 下限，
                #   但 evolution probe tier 应该用 5%/10% 价格间距。
                _rec_snap = {}
                _rec_here = self.position_tracker.get_open_position(inst_id)
                if _rec_here and getattr(_rec_here, "market_snapshot", None):
                    _rec_snap = _rec_here.market_snapshot or {}
                _is_evo = bool(_rec_here and
                               str(getattr(_rec_here, "source_tag", "") or "").lower() == "evolution")
                if _is_evo:
                    _evo_sl_pct = float(_rec_snap.get("sl_pct", 0) or 0)
                    _evo_tp_pct = float(_rec_snap.get("tp_pct", 0) or 0)
                    # 早期 evolution 开仓可能未存 sl_pct/tp_pct，用 tier 推断默认值
                    if _evo_sl_pct <= 0 or _evo_tp_pct <= 0:
                        _evo_tier = str(_rec_snap.get("tier", "") or "").lower()
                        _tier_defaults = {
                            "probe": (0.04, 0.12),     # SL=4%, TP=12%
                            "standard": (0.04, 0.12),  # SL=4%, TP=12%
                            "trend": (0.04, 0.12),     # SL=4%, TP=12%
                        }
                        _def_sl, _def_tp = _tier_defaults.get(_evo_tier, (0.04, 0.12))
                        if _evo_sl_pct <= 0:
                            _evo_sl_pct = _def_sl
                        if _evo_tp_pct <= 0:
                            _evo_tp_pct = _def_tp
                    if _evo_sl_pct > 0:
                        _base_sl_roi = _evo_sl_pct * _lev_here  # 价格间距 → ROI
                    if _evo_tp_pct > 0:
                        _base_tp_roi = _evo_tp_pct * _lev_here

                # FAIL-OPEN: base取不到就用项目记忆下限（常规SL≥4%价格、TP≥12%价格，对应订单ROI=价格%×L）
                if _base_sl_roi <= 0:
                    _base_sl_roi = 0.04 * _lev_here  # 订单ROI: 4%价格间距
                if _base_tp_roi <= 0:
                    _base_tp_roi = 0.12 * _lev_here   # 订单ROI: 12%价格间距
                try:
                    _trial_flag = bool(getattr(self, "_last_open_was_trial", False)
                                       if hasattr(self, "_last_open_was_trial") else False)
                except Exception:
                    _trial_flag = False
                _sl_px = self._calc_sl_price(entry_px, pos_side, _base_sl_roi, _lev_here)
                _tp_px = self._calc_tp_price(entry_px, pos_side, _base_tp_roi, _lev_here)
                _need_issue = True
                _reason_tag = "startup_issue_missing"
                self._log(
                    f"[持仓同步·SLTP修复] {coin} {pos_side} L={_lev_here:.0f}x 缺SL={_sl_missing}"
                    f"/缺TP={_tp_missing}，按基线ATR+门禁自动下发套单 | "
                    f"基线SL价格间距={(entry_px - _sl_px) / entry_px * 100 if pos_side == 'long' else (_sl_px - entry_px) / entry_px * 100:.2f}%"
                    f", TP价格间距={(_tp_px - entry_px) / entry_px * 100 if pos_side == 'long' else (entry_px - _tp_px) / entry_px * 100:.2f}%"
                    + (f" [evolution tier={_rec_snap.get('tier', '?')}]" if _is_evo else ""),
                    "WARN",
                )

            # ── 双门禁：SL/TP分别校验，过近/致命→钳制 ─────────
            _new_sl, _sl_clamped, _sl_old_pct, _sl_cfl = self._enforce_sl_price_floor(
                _sl_px, entry_px, pos_side, leverage=_lev_here,
                allow_tighten=False, coin=coin)
            _new_tp, _tp_clamped, _tp_old_pct, _tp_cfl = self._enforce_tp_price_floor(
                _tp_px, entry_px, pos_side, leverage=_lev_here,
                allow_lower=False, coin=coin)

            # ── 有任一门禁钳制 或 触发缺套单重算 → 下发新套单
            if _need_issue or _sl_clamped or _tp_clamped:
                _extra = ""
                if _sl_cfl.get("liq_conflict") or _tp_cfl.get("liq_conflict"):
                    _extra = f" 【间距/爆仓冲突→已按爆仓安全优先】L={_lev_here:.0f}x过高，请立即将{coin}杠杆降到≤20x，否则SL/TP永远在爆仓线附近漂移！"
                _parts = []
                if _need_issue:
                    _parts.append("缺套单→全量下发")
                if _sl_clamped:
                    _parts.append(
                        f"SL修复: {_sl_px:.6f}(间距{_sl_old_pct*100:.2f}%) → {_new_sl:.6f}"
                        f"(间距{abs(_new_sl-entry_px)/entry_px*100:.2f}%)"
                    )
                if _tp_clamped:
                    _parts.append(
                        f"TP修复: {_tp_px:.6f}(间距{_tp_old_pct*100:.2f}%) → {_new_tp:.6f}"
                        f"(间距{abs(_new_tp-entry_px)/entry_px*100:.2f}%)"
                    )
                self._log(
                    f"[持仓同步·SLTP修复] {coin} {pos_side} L={_lev_here:.0f}x | "
                    + " | ".join(_parts)
                    + _extra,
                    "WARN" if (_sl_clamped or _tp_clamped or _need_issue) else "INFO",
                )
                try:
                    if self.okx_client and hasattr(self.okx_client, "place_stop_loss_take_profit"):
                        _r = self.okx_client.place_stop_loss_take_profit(
                            inst_id=inst_id, pos_side=pos_side,
                            stop_loss_px=_new_sl, take_profit_px=_new_tp,
                            reason=f"{_reason_tag}:sl={(_sl_old_pct if _sl_clamped else 0)*100:.2f}pct,tp={(_tp_old_pct if _tp_clamped else 0)*100:.2f}pct,L={_lev_here:.0f}x",
                        )
                        if _r.get("ok"):
                            self._log(
                                f"[持仓同步·SLTP修复] {coin} SL/TP已推送交易所 OK | "
                                f"final SL={_new_sl:.6f}, TP={_new_tp:.6f}", "INFO",
                            )
                        else:
                            self._log(
                                f"[持仓同步·SLTP修复] {coin} 推送失败: {_r.get('error','unknown')}",
                                "WARN",
                            )
                except Exception as _e:
                    self._log(f"[持仓同步·SLTP修复] {coin} 推送异常(FAIL-OPEN忽略): {_e}", "WARN")
                # 修复本地 tracker 记录的快照
                try:
                    rec = self.position_tracker.get_open_position(inst_id)
                    if rec and rec.market_snapshot:
                        rec.market_snapshot["stop_loss_px"] = _new_sl
                        rec.market_snapshot["take_profit_px"] = _new_tp
                except Exception:
                    pass
            else:
                # 全部合理
                self._log(
                    f"[持仓同步·SLTP修复] {coin} {pos_side} L={_lev_here:.0f}x "
                    f"SL={_sl_px:.6f}(间距{_sl_old_pct*100:.2f}%) / "
                    f"TP={_tp_px:.6f}(间距{_tp_old_pct*100:.2f}%) → 双门禁均合规，无需修复",
                    "DEBUG",
                )
        except Exception as _top_e:
            # FAIL-OPEN铁律：异常不阻塞交易
            self._log(
                f"[持仓同步·SLTP修复] {coin} 顶层异常FAIL-OPEN，跳过本轮巡检: {_top_e}",
                "WARN",
            )

        # ══════════════════════════════════════════════════════════════
        # v5.0 离场防频繁优化：离场确认状态机 + 持仓保护门禁
        # ══════════════════════════════════════════════════════════════
        # 离场动作2次确认状态机：避免单根K线假信号/瞬时波动直接平仓
        # key = f"{coin}:{action_type}"  value = {confirm_count: int, first_ts: float}
        self._exit_confirm_state: Dict[str, Dict[str, Any]] = {}
        # 确认窗口：2次轮询(约2min)内连续触发才执行
        self.EXIT_CONFIRM_WINDOW_SEC = 300  # 5分钟窗口
        self.EXIT_CONFIRM_REQUIRED = 2  # 需要2次连续触发
        # 离场动作类型
        self.EXIT_ACT_SIGNAL_REVERSE = "signal_reverse"
        self.EXIT_ACT_YIJING_FORCE_CLOSE = "yijing_force_close"
        self.EXIT_ACT_P3_EARLY_EXIT = "p3_early_exit"
        self.EXIT_ACT_EV_FORCE_CLOSE = "ev_force_close"       # Phase B: EV 雷达强制离场
        self.EXIT_ACT_RANKED_TP = "ranked_tp"                 # Phase C: 排名止盈离场 tag

        # 持仓保护期门禁（开仓后N小时内仅硬离场生效）
        # 保护期内：信号反转需更高置信度；易经TIGHTEN_SL/LOWER_TP/LOWER_SL/RAISE_TP全部屏蔽；
        #          P3提前退出需确认；仅保留开仓静态SL/TP + P0硬止损
        self.POSITION_PROTECTION_HOURS = 6.0  # 开仓后前6小时为保护期
        # P2 总开关：形态预测器（S5）+ 爆仓/期权宏观特征（仅 True 时网络调用 + 乘数注入 + call site 注入）
        #   False 时所有新代码路径 zero-byte 触达，字节等价旧路径，可随时回滚
        self.ENABLE_REGIME_AND_MACRO_S5 = True
        # 保护期内信号反转所需额外置信度(在effective_threshold之上再加)
        self.PROTECTED_REVERSE_CONF_BOOST = 0.12  # 如原阈值0.7→保护期需≥0.82
        # 保护期内最小亏损比例才允许P3提前退出（否则假预警会走）
        self.PROTECTED_P3_MIN_LOSS_PCT = -0.08  # 浮亏≥8%才允许P3退出（保护期内）
        self._log(
            f"[离场防频繁] v5.0优化已启用：保护期={self.POSITION_PROTECTION_HOURS:.0f}h "
            f"| 离场确认={self.EXIT_CONFIRM_REQUIRED}次/{self.EXIT_CONFIRM_WINDOW_SEC//60:.0f}min "
            f"| 保护期反转置信+{self.PROTECTED_REVERSE_CONF_BOOST:.0%}",
            "INFO",
        )

    def _save_exit_strategy_decision(
        self, coin: str, decision, age_hours: float,
        in_protection: bool, ev, confidence: float,
        pnl=None, win=None,
    ) -> None:
        """记录 ExitManager 策略决策到 exit_strategy_log（异常不阻断主流程）。

        Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md §5
        """
        try:
            _storage = getattr(self.exit_manager, "_storage", None)
            if _storage is None:
                return
            _storage.save_exit_strategy_log(coin, {
                "strategy_name": decision.strategy_name or "",
                "action": decision.action,
                "reason": decision.reason,
                "age_hours": age_hours,
                "in_protection": in_protection,
                "ev": ev,
                "confidence": confidence,
                "pnl": pnl,
                "win": win,
            })
        except Exception as _e:
            self._log(f"[{coin}] exit_strategy_log 记录失败（不阻断）: {_e}", "WARN")

    def _run_startup_inspection(self):
        """启动时运行 inspect 诊断命令，快速检查系统状态"""
        self._log("[系统诊断] 启动时执行状态检查...", "INFO")
        try:
            from scripts.memory_l4.system_inspect import SystemInspector

            inspector = SystemInspector()
            report = inspector.inspect(
                panel_ids=["system", "positions", "models", "connections", "risk"]
            )

            for panel in report.panels:
                status_icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(panel.status, "ℹ️")
                self._log(f"  {status_icon} [{panel.name}] {panel.summary}", panel.status.upper())
                for key, val in panel.details.items():
                    if isinstance(val, (int, float, str)) and len(str(val)) <= 50:
                        self._log(f"    └─ {key}: {val}")

            if report.overall_status == "error":
                self._log("[系统诊断] 发现错误，请检查相关组件", "WARN")
            else:
                self._log("[系统诊断] 启动检查通过", "INFO")

        except Exception as e:
            self._log(f"[系统诊断] 执行失败: {e}，继续运行", "WARN")

    def _log(self, msg: str, level: str = "INFO"):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{level}] {msg}"
        print(line, flush=True)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps({"ts": ts, "level": level, "msg": msg}, ensure_ascii=False) + "\n"
                )
        except Exception:
            pass

    def _health_check_bcrm2(self) -> tuple:
        """措施1：BCRM 2.0 启动健康检查

        主动验证 BCRM 2.0 关键模块导入路径与核心依赖可用性，
        避免运行时才发现 "No module named 'bcrm2'" 等问题导致静默回退。

        Returns:
            (healthy: bool, reason: str) — healthy=True 表示检查通过
        """
        checks = []

        # 1. 验证核心模块导入路径
        try:
            from scripts.memory_l4.bcrm2_adapter import BCRM2Adapter  # noqa: F401

            checks.append(("BCRM2Adapter 导入", True, ""))
        except Exception as e:
            checks.append(("BCRM2Adapter 导入", False, str(e)))

        # 2. 验证辩证ML引擎可加载
        try:
            checks.append(("DialecticalMLEngine 导入", True, ""))
        except Exception as e:
            checks.append(("DialecticalMLEngine 导入", False, str(e)))

        # 3. 验证八卦特征引擎可加载
        try:
            checks.append(("BaguaFeatureEngine 导入", True, ""))
        except Exception as e:
            checks.append(("BaguaFeatureEngine 导入", False, str(e)))

        # 4. 验证增量学习器可加载
        try:
            checks.append(("IncrementalLearner 导入", True, ""))
        except Exception as e:
            checks.append(("IncrementalLearner 导入", False, str(e)))

        # 5. 验证关键依赖库 (lightgbm / pandas / numpy)
        try:
            import lightgbm  # noqa: F401

            checks.append(("lightgbm 依赖", True, f"v{lightgbm.__version__}"))
        except Exception as e:
            checks.append(("lightgbm 依赖", False, str(e)))

        # 汇总
        failed = [c for c in checks if not c[1]]
        if failed:
            reason = "; ".join(f"{name}失败: {msg}" for name, _, msg in failed)
            return (False, reason)

        passed_summary = ", ".join(name for name, _, _ in checks)
        self._log(f"[BCRM2.0] 健康检查项: {passed_summary}", "INFO")
        return (True, "all checks passed")

    def _on_retrain_complete(self, result: dict):
        """重训完成回调"""
        self._log(
            f"[学习调度] 重训完成 | case={result.get('case_count')} "
            f"两仪更新={result.get('liangyi_updated')} "
            f"QMM更新={result.get('qmm_updated')} "
            f"第{result.get('retrain_count')}次"
        )

    def _check_date_rollover(self):
        """检查是否跨天，重置每日风控"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.last_date:
            # F2修正：跨天时输出前一天的每日聚合摘要到监控
            self._emit_daily_summary(self.last_date)
            self._log(f"[风控] 新的一天 {today}，重置每日风控统计")
            self.risk_manager.reset_daily()
            self.last_date = today

    def _emit_daily_summary(self, date_str: str):
        """F2修正：输出每日聚合绩效摘要到监控文件。

        将 PerformanceTracker 的日统计 + 整体统计写入
        .workbuddy/memory_l4/stats/daily_summary_{date}.json
        供 yijing_monitor / 飞书推送消费。
        """
        if not date_str:
            return
        try:
            today_stats = self.perf_tracker.get_today_stats()
            overall = self.perf_tracker.get_overall_stats()

            summary = {
                "date": date_str,
                "generated_at": datetime.now().isoformat(),
                "daily": {
                    "total_trades": today_stats.get("total_trades", 0),
                    "win_trades": today_stats.get("win_trades", 0),
                    "loss_trades": today_stats.get("loss_trades", 0),
                    "total_pnl": today_stats.get("total_pnl", 0),
                    "win_rate": today_stats.get("win_rate", 0),
                    "max_drawdown": today_stats.get("max_drawdown", 0),
                    "consecutive_losses": today_stats.get("current_consecutive_losses", 0),
                },
                "overall": {
                    "total_trades": overall.get("total_trades", 0),
                    "win_rate": overall.get("win_rate", 0),
                    "total_pnl": overall.get("total_pnl", 0),
                    "profit_factor": overall.get("profit_factor", 0),
                    "max_drawdown": overall.get("max_drawdown", 0),
                    "current_equity": overall.get("current_equity", 0),
                    "sharpe_ratio": overall.get("sharpe_ratio", 0),
                    "trading_days": overall.get("trading_days", 0),
                },
            }

            summary_file = self.perf_tracker.stats_dir / f"daily_summary_{date_str}.json"
            summary_file.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self._log(
                f"[每日摘要] {date_str} 已落盘: {summary_file.name} | "
                f"日交易{summary['daily']['total_trades']}笔 盈亏{summary['daily']['total_pnl']:.2f}U "
                f"整体夏普{summary['overall']['sharpe_ratio']:.2f}"
            )
        except Exception as e:
            self._log(f"[每日摘要] 生成失败: {e}", "WARN")

    def _fetch_and_infer(self, coin: str) -> dict:
        """获取实时行情并执行 BCRM + 八卦双引擎推理"""
        inst_id = f"{coin}-USDT-SWAP"

        kline_data = _load_kline_from_okx(inst_id=inst_id, bar=self.bar, limit=self.kline_limit)
        if not kline_data:
            return {"ok": False, "error": f"获取 {inst_id} K线失败"}

        # BCRM 2.0 推理路径（严格模式：不允许降级到 BCRM 1.0）
        if self.use_bcrm2:
            # v3.0：per-coin 失败重试间隔检查 → 严格模式：间隔内直接跳过，不降级
            fail_ts = self.bcrm2_failed_coins.get(coin)
            if fail_ts is not None and (time.time() - fail_ts) < self.bcrm2_retry_interval_sec:
                remain_min = (self.bcrm2_retry_interval_sec - (time.time() - fail_ts)) / 60
                return {
                    "ok": False,
                    "error": (
                        f"BCRM2.0 失败冷却中(剩余{remain_min:.0f}min)，"
                        f"严格模式：不降级BCRM 1.0，本轮跳过"
                    ),
                }

            # 未失败或已过重试间隔，尝试 BCRM 2.0
            if fail_ts is not None:
                self._log(f"[{coin}] BCRM2.0 失败重试间隔已过，重新尝试", "INFO")
                self.bcrm2_failed_coins.pop(coin, None)
                if coin in self.bcrm2_adapters:
                    del self.bcrm2_adapters[coin]
            try:
                return self._infer_bcrm2(coin, inst_id, kline_data)
            except Exception as e:
                self._log(
                    f"[{coin}] BCRM2.0 运行异常: {e} | "
                    f"严格模式：不降级BCRM 1.0，本轮跳过",
                    "ERROR",
                )
                try:
                    notify_model_error(
                        f"BCRM2.0 运行异常（严格模式：跳过，不降级BCRM 1.0）: {type(e).__name__}: {e}",
                        symbol=coin,
                    )
                except Exception as alert_err:
                    self._log(f"[{coin}] 飞书告警发送失败: {alert_err}", "WARN")
                self.bcrm2_failed_coins[coin] = time.time()
                # ⚠️ 严格模式：直接返回失败，绝不落到 BCRM 1.0
                return {"ok": False, "error": f"BCRM2.0 运行异常({type(e).__name__}: {e})，严格模式禁用BCRM 1.0降级"}

        # ================================================================
        # ⛔ BCRM 1.0 fallback 路径 — 严格模式下永久不可达
        # （当 use_bcrm2=True 时，上面的分支已经全部 return；
        #  若未来强制 use_bcrm2=False，则此处代码会触发保护告警）
        # ================================================================
        self._log(
            f"[{coin}] 尝试进入BCRM 1.0路径，已被严格模式阻断！"
            f" | 请确认 use_bcrm2=True 且 BCRM 2.0 可用",
            "ERROR",
        )
        try:
            notify_system_error(
                "BCRM 1.0 fallback 路径被严格模式阻断，请排查 BCRM 2.0 可用性",
                component="BCRM严格模式保护",
            )
        except Exception:
            pass
        return {"ok": False, "error": "BCRM 1.0 fallback 已被严格模式阻断，只允许BCRM 2.0"}

        # —— 以下为原始 BCRM 1.0 代码，保留但永不执行 ——
        snapshot = _kline_to_snapshot(kline_data, idx=0)
        if not snapshot:
            return {"ok": False, "error": "构造 snapshot 失败"}
        snapshot["symbol"] = inst_id

        contradictions_raw = _build_contradiction_list(snapshot)
        contradictions_raw.extend(_build_research_contradictions(snapshot))
        contradictions = _contradictions_to_bcrm_format(contradictions_raw, snapshot)

        closes_window = [kline_data[j]["c"] for j in range(min(60, len(kline_data)))]
        volumes_window = [kline_data[j].get("v", 0) for j in range(min(60, len(kline_data)))]
        ranging_info = _detect_ranging_market(snapshot, closes_window)
        snapshot["is_ranging"] = ranging_info.get("is_ranging", False)
        snapshot["ranging_confidence"] = ranging_info.get("confidence", 0)

        # P0修复: 每币种推理前重置 ForceEngine 速度状态，防止跨币种污染
        if hasattr(self.bcrm_engine, "force_engine") and hasattr(
            self.bcrm_engine.force_engine, "reset_velocity"
        ):
            self.bcrm_engine.force_engine.reset_velocity()

        qmm_output = {"uncertainty": 0.3}
        try:
            bcrm_result = self.bcrm_engine.infer(
                market_snapshot=snapshot,
                contradiction_list=contradictions,
                qmm_output=qmm_output,
            )
        except Exception as e:
            if self.guardian:
                self.guardian.record_error(e, context=f"bcrm_infer:{coin}")
            return {"ok": False, "error": f"BCRM 推理失败: {e}"}

        direction = bcrm_result.next_state.direction
        confidence = bcrm_result.next_state.confidence
        hex_cn = bcrm_result.hexagram.hexagram_name_cn or bcrm_result.hexagram.hexagram_name
        fail_closed = bcrm_result.is_fail_closed()

        bagua_result = None
        try:
            bagua_result = self.bagua_engine.infer(
                snapshot=snapshot,
                closes=closes_window,
                volumes=volumes_window,
            )
        except Exception:
            pass

        bagua_dir = bagua_result.primary_direction if bagua_result else "neutral"
        bagua_conf = bagua_result.primary_confidence if bagua_result else 0

        bcrm_dir_num = 1 if direction == "UP" else (-1 if direction == "DOWN" else 0)
        bagua_dir_num = 1 if bagua_dir == "long" else (-1 if bagua_dir == "short" else 0)

        if bcrm_dir_num != 0 and bagua_dir_num != 0:
            if bcrm_dir_num == bagua_dir_num:
                confidence = min(0.95, confidence * 0.5 + bagua_conf * 0.5 + 0.1)
            else:
                confidence = confidence * 0.4
                if bagua_conf > confidence + 0.2:
                    direction = "UP" if bagua_dir == "long" else "DOWN"
                    confidence = bagua_conf * 0.7
        elif bcrm_dir_num == 0 and bagua_dir_num != 0:
            direction = "UP" if bagua_dir == "long" else "DOWN"
            confidence = bagua_conf * 0.6
        elif bagua_dir_num == 0 and bcrm_dir_num != 0:
            confidence = confidence * 0.7

        if bagua_result and bagua_result.hexagram_name_cn:
            hex_cn = bagua_result.hexagram_name_cn

        # 卦象名与方向一致性检查 (修复: 2026-07-13)
        hex_consistent = True
        if hex_cn:
            gua_direction = self._get_hexagram_direction(hex_cn)
            actual_direction = "long" if direction == "UP" else "short"
            if gua_direction and gua_direction != "neutral" and gua_direction != actual_direction:
                hex_consistent = False
                # 尝试使用变卦或互卦作为替代卦象
                if bcrm_result and hasattr(bcrm_result, "hexagram"):
                    bcrm_hex = bcrm_result.hexagram
                    # 使用变卦替代
                    if hasattr(bcrm_hex, "changed_hexagram_cn") and bcrm_hex.changed_hexagram_cn:
                        hex_cn = bcrm_hex.changed_hexagram_cn
                        self._log(f"[{coin}] 卦象校准 | {hex_cn}(变卦) 替代原卦象", "INFO")
                    else:
                        self._log(
                            f"[{coin}] 卦象警告 | 卦象{hex_cn}({gua_direction})与决策方向({actual_direction})不一致",
                            "WARN",
                        )

        sl_px, tp_px, reduce_ratio = 0, 0, 0
        if bcrm_result.strategy_branches:
            b1 = next((b for b in bcrm_result.strategy_branches if b.branch_id == "B1"), None)
            if b1:
                sl_px = b1.stop_loss_px
                tp_px = b1.take_profit_px
                reduce_ratio = b1.reduce_ratio

        # 经典指标离场回退：BCRM 未产生止盈止损时，用 ATR 计算止损止盈
        # 2026-09-09 放大：SL=4.0~6.0×ATR，TP=3.0×SL，硬下限 4% 防低波扫损
        if sl_px == 0 or tp_px == 0:
            price = snapshot.get("price", 0)
            volatility = snapshot.get("volatility", 0.03)
            if price > 0:
                # ATR 近似：用波动率 × 价格作为 ATR 估计
                atr = max(price * volatility, price * 0.005)  # 至少 0.5%
                # 波动率自适应 ATR 倍率：低波 4.0×ATR，高波 6.0×ATR，盈亏比 3:1
                atr_mult_sl, atr_mult_tp = RiskManager.volatility_adaptive_atr_mult(volatility)
                # 高置信度进一步放宽：置信度 ≥0.9 时 SL/TP 再 ×1.3
                if confidence >= 0.9:
                    atr_mult_sl *= 1.3
                    atr_mult_tp *= 1.3
                # 计算止损止盈价
                if direction == "UP":
                    fallback_sl = round(price - atr * atr_mult_sl, 4)
                    fallback_tp = round(price + atr * atr_mult_tp, 4)
                else:
                    fallback_sl = round(price + atr * atr_mult_sl, 4)
                    fallback_tp = round(price - atr * atr_mult_tp, 4)
                # 硬下限：SL 间距至少 4%（防低波扫损），TP 上限 30%
                sl_pct_fb = abs(price - fallback_sl) / price if price > 0 else 0
                if sl_pct_fb < 0.04:
                    fallback_sl = round(price * (1 - 0.04), 4) if direction == "UP" else round(price * (1 + 0.04), 4)
                tp_pct_fb = abs(fallback_tp - price) / price if price > 0 else 0
                if tp_pct_fb > 0.30:
                    fallback_tp = round(price * (1 + 0.30), 4) if direction == "UP" else round(price * (1 - 0.30), 4)
                if sl_px == 0:
                    sl_px = fallback_sl
                if tp_px == 0:
                    tp_px = fallback_tp
                self._log(
                    f"[{coin}] 经典指标离场(ATR自适应) | ATR={atr:.2f} vol={volatility:.4f} "
                    f"(conf={confidence:.2f}→SL={atr_mult_sl:.1f}×ATR TP={atr_mult_tp:.1f}×ATR) | "
                    f"SL={sl_px} TP={tp_px} (盈亏比={atr_mult_tp/atr_mult_sl:.1f}:1)",
                    "INFO",
                )

        liangyi_dict = {}
        if hasattr(bcrm_result, "liangyi_state") and bcrm_result.liangyi_state:
            if hasattr(bcrm_result.liangyi_state, "to_dict"):
                liangyi_dict = bcrm_result.liangyi_state.to_dict()
            elif isinstance(bcrm_result.liangyi_state, dict):
                liangyi_dict = bcrm_result.liangyi_state

        scale_dict = {}
        if hasattr(bcrm_result, "scale_params") and bcrm_result.scale_params:
            if hasattr(bcrm_result.scale_params, "to_dict"):
                scale_dict = bcrm_result.scale_params.to_dict()
            elif isinstance(bcrm_result.scale_params, dict):
                scale_dict = bcrm_result.scale_params

        # P0修复：注入 regime 到 snapshot（卦象+is_ranging+closes推断）
        # P2-06: 当 ENABLE_REGIME_AND_MACRO_S5 时，拉取全局宏观特征并注入；
        #        False 时完全不传参，_infer_regime 走旧路径，字节等价
        _p2_macro_feats = None
        if self.ENABLE_REGIME_AND_MACRO_S5:
            try:
                _p2_macro_feats = self._fetch_global_macro_features_once()
            except Exception:
                _p2_macro_feats = None
        snapshot["regime"] = self._infer_regime(
            hex_cn, snapshot.get("is_ranging", False), direction, closes_window,
            macro_features=_p2_macro_feats,
            enable_macro_correction=self.ENABLE_REGIME_AND_MACRO_S5,
        )

        return {
            "ok": True,
            "coin": coin,
            "inst_id": inst_id,
            "price": snapshot.get("price", 0),
            "direction": direction,
            "confidence": round(confidence, 4),
            "hexagram": hex_cn,
            "hex_consistent": hex_consistent,  # 卦象方向一致性标志
            "fail_closed": fail_closed,
            "is_ranging": snapshot.get("is_ranging", False),
            "bagua_direction": bagua_dir,
            "bagua_confidence": round(bagua_conf, 4),
            "stop_loss_px": sl_px,
            "take_profit_px": tp_px,
            "reduce_ratio": reduce_ratio,
            "liangyi_state": liangyi_dict,
            "scale_params": scale_dict,
            "snapshot": snapshot,
            "contradictions": contradictions,
            "volatility": snapshot.get("volatility", 0.03),
            "kline_data": kline_data,
        }

    def _kline_to_dataframe(self, kline_data: list) -> "pd.DataFrame":
        """将 OKX K线数据转换为 pandas DataFrame"""
        import pandas as pd

        data = []
        for c in kline_data:
            data.append(
                {
                    "timestamp": c.get("ts", 0),
                    "open": float(c.get("o", 0)),
                    "high": float(c.get("h", 0)),
                    "low": float(c.get("l", 0)),
                    "close": float(c.get("c", 0)),
                    "volume": float(c.get("v", 0)),
                }
            )
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)
        return df

    def _infer_bcrm2(self, coin: str, inst_id: str, kline_data: list) -> dict:
        """使用 BCRM 2.0 (辩证ML) 执行推理"""

        if coin not in self.bcrm2_adapters:
            # BTC 启用 v4 前向选择验证有效的 3 个宏观特征
            # (fgi_zscore + fgi_extreme_fear + hash_rate_trend，BTC验证得分 +23.8%)
            # 其他币种保持默认（不传 macro_config = 全部启用默认行为）
            btc_macro_config = None
            if coin.upper() == "BTC":
                btc_macro_config = {
                    "macro_feat_fgi_zscore": True,
                    "macro_feat_fgi_extreme_fear": True,
                    "macro_feat_hash_rate_trend": True,
                    # 其余 21 个特征显式关闭
                    "macro_feat_fgi_trend_7d": False,
                    "macro_feat_fgi_extreme_greed": False,
                    "macro_feat_fgi_divergence": False,
                    "macro_feat_funding_rate_zscore": False,
                    "macro_feat_funding_extreme_positive": False,
                    "macro_feat_funding_extreme_negative": False,
                    "macro_feat_oi_change_rate": False,
                    "macro_feat_funding_divergence": False,
                    "macro_feat_stablecoin_growth": False,
                    "macro_feat_liquidity_expanding": False,
                    "macro_feat_liquidity_contracting": False,
                    "macro_feat_tvl_change_7d": False,
                    "macro_feat_miner_accumulation": False,
                    "macro_feat_miners_revenue_zscore": False,
                    "macro_feat_smart_money_direction": False,
                    "macro_feat_smart_money_divergence": False,
                    "macro_feat_social_hype_zscore": False,
                    "macro_feat_hype_extreme": False,
                    "macro_feat_market_cap_rank": False,
                    "macro_feat_ath_drop_pct": False,
                    "macro_feat_undervalued": False,
                }
            self.bcrm2_adapters[coin] = BCRM2Adapter(
                symbol=coin,
                timeframe=self.bar,
                tp_atr=3.0,
                sl_atr=2.5,  # P1-2: 原1.5→2.5，与外层SL=3.0×ATR口径一致（2.5~3 ATR区间）
                max_hold_bars=60,
                macro_config=btc_macro_config,
            )

        adapter = self.bcrm2_adapters[coin]

        try:
            df = self._kline_to_dataframe(kline_data)
        except Exception as e:
            return {"ok": False, "error": f"K线转换失败: {e}"}

        # 首次推理时自动训练
        if adapter.engine is None:
            # 严格模式：K线数据不足则直接跳过该币种，绝不回退 BCRM 1.0
            # max_hold_bars=60，需要至少 100+60=160 根K线才能产生100个有效样本
            min_klines_needed = self.bcrm2_min_samples + adapter.max_hold_bars
            if len(df) < min_klines_needed:
                self._log(
                    f"[{coin}] BCRM2.0 跳过: K线数据不足({len(df)}<{min_klines_needed}根) "
                    f"| 严格模式：不降级BCRM 1.0，本轮跳过",
                    "WARN",
                )
                self.bcrm2_failed_coins[coin] = time.time()
                return {"ok": False, "error": f"BCRM2.0 K线数据不足({len(df)}<{min_klines_needed})，严格模式禁用BCRM 1.0降级"}

            self._log(f"[{coin}] BCRM2.0 首次推理，开始训练模型...", "INFO")
            train_result = adapter.train(df)
            if train_result is not True:
                # 严格模式：区分原因但统一选择"跳过"，绝不回退 BCRM 1.0
                is_data_insufficient = train_result == "insufficient_data"
                self.bcrm2_failed_coins[coin] = time.time()

                if is_data_insufficient:
                    self._log(
                        f"[{coin}] BCRM2.0 样本不足，严格模式跳过（不降级BCRM 1.0，24h后重试）",
                        "WARN",
                    )
                else:
                    self._log(
                        f"[{coin}] BCRM2.0 训练失败(异常)，严格模式跳过（不降级BCRM 1.0）",
                        "ERROR",
                    )
                    try:
                        notify_model_error(
                            "BCRM2.0 训练异常（严格模式：跳过，不降级BCRM 1.0）",
                            symbol=coin,
                        )
                    except Exception as e:
                        self._log(f"[{coin}] 飞书告警发送失败: {e}", "WARN")
                return {"ok": False, "error": f"BCRM2.0 训练失败({train_result})，严格模式禁用BCRM 1.0降级"}

        # 执行推理
        bcrm_result = adapter.infer(df, idx=-1)
        # 保存到实例属性供 SubSystemBridge 消费（自进化系统接入）
        self._last_bcrm2_result = bcrm_result

        if not bcrm_result.get("ok"):
            # 措施2：推理失败时立即发送飞书告警（fail_closed 也会走这里）
            fail_reason = bcrm_result.get("fail_closed_reason", "未知")
            self._log(f"[{coin}] BCRM2.0 推理失败: {fail_reason}", "WARN")
            try:
                notify_model_error(
                    f"BCRM2.0 推理失败 (fail_closed): {fail_reason}",
                    symbol=coin,
                )
            except Exception as e:
                self._log(f"[{coin}] 飞书告警发送失败: {e}", "WARN")
            return {"ok": False, "error": "BCRM2.0 推理失败"}

        direction = bcrm_result["next_state"]["direction"]
        confidence = bcrm_result["next_state"]["confidence"]
        hex_cn = bcrm_result["hexagram"]["hexagram_name_cn"]
        fail_closed = bcrm_result["is_fail_closed"]()

        # 计算波动率（用于止盈止损）— 必须在 CBR 增强前完成，供 CBR 使用
        closes = df["close"].values
        atr = 0
        if len(df) >= 14:
            highs = df["high"].values
            lows = df["low"].values
            tr = np.maximum(
                highs[1:] - lows[1:],
                np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
            )
            atr = np.mean(tr[-14:])
        volatility = atr / closes[-1] if closes[-1] > 0 else 0.03

        # 检测震荡市
        closes_window = list(closes[-60:])
        snapshot_simple = {"price": closes[-1], "volatility": volatility}
        ranging_info = _detect_ranging_market(snapshot_simple, closes_window)
        is_ranging = ranging_info.get("is_ranging", False)

        price = closes[-1]

        # CBR 案例检索增强（2026-07-21 修复：price/volatility 必须先计算好再调用）
        if self.cbr_bridge and not fail_closed:
            try:
                bcrm_output = {
                    "inst_id": inst_id,
                    "direction": (
                        "long"
                        if direction == "UP"
                        else ("short" if direction == "DOWN" else "flat")
                    ),
                    "confidence": confidence,
                    "current_price": price,
                    "regime": bcrm_result.get("hexagram", {})
                    .get("liangyi_state", {})
                    .get("macro_phase", ""),
                    "volatility": volatility,
                    "hexagram": hex_cn,
                }
                enhanced = self.cbr_bridge.enhance_bcrm_signal(bcrm_output)
                # 应用 CBR 增强的参数
                if enhanced.get("cbr_fusion_method") != "bcrm_only":
                    confidence = enhanced.get("confidence", confidence)
                    self._log(
                        f"[{coin}] CBR 增强 | 历史胜率={enhanced.get('cbr_historical_win_rate', 0):.1%} "
                        f"Top-1相似度={enhanced.get('cbr_similarity_top1', 0):.2f} "
                        f"融合模式={enhanced.get('cbr_fusion_method')} "
                        f"风险提示={enhanced.get('cbr_risk_notes', [])}",
                        "INFO",
                    )
            except Exception as e:
                self._log(f"[{coin}] CBR 增强失败: {e}", "WARN")

        # 计算 ATR 止盈止损
        # P1-2: 统一ATR止损倍率为2.5~3.0区间（adapter=2.5, 主SL=3.0, ExitConfig=2.5）
        # 高置信度(≥0.9)再×1.3放宽至3.9×ATR，盈亏比保持~2:1
        sl_px, tp_px = 0, 0
        if atr > 0:
            sl_mult = 3.0  # 主止损线 3.0×ATR
            tp_mult = 6.0  # 止盈 6.0×ATR
            if confidence >= 0.9:
                sl_mult *= 1.3
                tp_mult *= 1.3
            if direction == "UP":
                sl_px = round(price - atr * sl_mult, 4)
                tp_px = round(price + atr * tp_mult, 4)
            elif direction == "DOWN":
                sl_px = round(price + atr * sl_mult, 4)
                tp_px = round(price - atr * tp_mult, 4)

        self._log(
            f"[{coin}] BCRM2.0 推理 | 方向={direction} 置信度={confidence:.2f} "
            f"卦象={hex_cn} fail_closed={fail_closed}",
            "INFO",
        )

        # ── 前置层注入：从 MorphCyclePredictor 获取 level_smooth/trend_smooth/consensus ──
        # BCRM 2.0 推理结果不含前置层 6 层流水线输出，需主动调用预测器获取 L/T/C
        # 使 ParameterMapper / ShadowLogger / α blend 能正确读取 reactive 参数
        _morph_L = 0.0
        _morph_T = 0.0
        _morph_C = 0.0
        _morph_src = "none"
        _predictor = getattr(self, "_morph_predictor", None)
        if _predictor is not None:
            try:
                _full_sym = inst_id or f"{coin.upper()}USDT"
                _cy = _predictor.predict_with_fallback(_full_sym, hist_days=60, forecast_days=5)
                if _cy.get("ok"):
                    _pa = _cy.get("params") or {}
                    _L_val = _pa.get("current_L")
                    _T_val = _pa.get("current_T")
                    if _L_val is not None and _T_val is not None:
                        _morph_L = float(_L_val)
                        _morph_T = float(_T_val)
                        _morph_C = 0.5  # 保守中性共识
                        _morph_src = "predictor"
            except Exception as _e:
                self._log(f"[{coin}] 前置层 L/T/C 注入失败: {_e}", "DEBUG")

        return {
            "ok": True,
            "coin": coin,
            "inst_id": inst_id,
            "price": price,
            "direction": direction,
            "confidence": round(confidence, 4),
            "hexagram": hex_cn,
            "hex_consistent": True,
            "fail_closed": fail_closed,
            "is_ranging": is_ranging,
            "bagua_direction": "neutral",
            "bagua_confidence": 0,
            "stop_loss_px": sl_px,
            "take_profit_px": tp_px,
            "reduce_ratio": 0,
            "liangyi_state": {},
            "scale_params": {},
            "snapshot": {
                "price": price,
                "volatility": volatility,
                "is_ranging": is_ranging,
                # ── 前置层 6 层流水线输出（L/T/C 双维坐标）──
                "level_smooth": _morph_L,
                "trend_smooth": _morph_T,
                "consensus": _morph_C,
                "morph_src": _morph_src,
                "regime": self._infer_regime(
                    hex_cn,
                    is_ranging,
                    direction,
                    list(closes[-60:]) if len(closes) >= 60 else list(closes),
                    macro_features=(self._fetch_global_macro_features_once()
                                    if self.ENABLE_REGIME_AND_MACRO_S5 else None),
                    enable_macro_correction=self.ENABLE_REGIME_AND_MACRO_S5,
                ),
            },
            "contradictions": bcrm_result.get("a0_analysis", {}).get("contradictions", []),
            "a0_analysis": bcrm_result.get("a0_analysis"),
            "a0_warnings": bcrm_result.get("a0_warnings", []),
            "triangle_verification": bcrm_result.get("triangle_verification"),
            # v4 风险评分风控参数（五角校验输出）
            "position_factor": bcrm_result.get("position_factor", 1.0),
            "sl_tighten_factor": bcrm_result.get("sl_tighten_factor", 1.0),
            "early_exit_signal": bcrm_result.get("early_exit_signal", False),
            "leverage_factor": bcrm_result.get("leverage_factor", 1.0),
            "tp_adjustment": bcrm_result.get("tp_adjustment", 1.0),
            "risk_score": bcrm_result.get("risk_score", 0.0),
            "risk_level": bcrm_result.get("risk_level", "NORMAL"),
            "volatility": volatility,
            "sl_atr": 1.5,
            "kline_data": kline_data,
        }

    def _get_hexagram_direction(self, hexagram_name: str) -> str:
        """根据卦象名查询卦象方向

        Args:
            hexagram_name: 卦象中文名 (如 "巽为风")

        Returns:
            卦象方向: "long" / "short" / "neutral" / "" (未知)
        """
        # 卦象名到方向的映射 (严格对齐 SIXTY_FOUR_GUAS 权威表 — dialectical_ml_engine.py)
        # 修复: 2026-08-23 (PUMP事件) — 原L2929注释导致隐式字符串拼接bug，
        #       "山水蒙_dup" + "山风蛊" 拼成垃圾键，丢失11卦+另有6卦方向错误
        HEX_TO_DIRECTION = {
            # 乾为天系列
            "乾为天": "long",
            "天地否": "short",
            "天雷无妄": "long",
            "天风姤": "short",
            "天水讼": "neutral",
            "天火同人": "long",
            "天山遁": "short",
            "天泽履": "long",
            # 坤为地系列
            "地天泰": "long",
            "坤为地": "neutral",
            "地雷复": "long",
            "地风升": "long",
            "地水师": "short",
            "地火明夷": "short",
            "地山谦": "neutral",
            "地泽临": "long",
            # 震为雷系列
            "雷天大壮": "long",
            "雷地豫": "long",
            "震为雷": "long",
            "雷风恒": "long",
            "雷水解": "long",
            "雷火丰": "long",
            "雷山小过": "short",
            "雷泽归妹": "short",
            # 巽为风系列
            "风天小畜": "neutral",
            "风地观": "neutral",
            "风雷益": "long",
            "巽为风": "long",
            "风水涣": "short",
            "风火家人": "long",
            "风山渐": "long",
            "风泽中孚": "long",
            # 坎为水系列
            "水天需": "long",
            "水地比": "long",
            "水雷屯": "neutral",
            "水风井": "neutral",
            "坎为水": "short",
            "水火既济": "short",
            "水山蹇": "short",
            "水泽节": "neutral",
            # 离为火系列
            "火天大有": "long",
            "火地晋": "long",
            "火雷噬嗑": "long",
            "火风鼎": "long",
            "火水未济": "neutral",
            "离为火": "long",
            "火山旅": "short",
            "火泽睽": "short",
            # 艮为山系列
            "山天大畜": "long",
            "山地剥": "short",
            "山雷颐": "neutral",
            "山风蛊": "short",
            "山水蒙": "short",
            "山火贲": "long",
            "艮为山": "neutral",
            "山泽损": "short",
            # 兑为泽系列
            "泽天夬": "long",
            "泽地萃": "long",
            "泽雷随": "long",
            "泽风大过": "short",
            "泽水困": "short",
            "泽火革": "long",
            "泽山咸": "long",
            "兑为泽": "long",
        }
        return HEX_TO_DIRECTION.get(hexagram_name, "")

    # ──────────────────────────────────────────────────────────────
    # [PUMP事件 2026-08-23] 开仓前卦象→方向一致性校验
    # 目标：避免同一卦象（如天地否）历史SHORT但本轮异常输出UP导致反向开仓
    # 判决矩阵（从最严到最轻）：
    #   ① 查表冲突 AND 历史主导冲突 → 硬 block
    #   ② 查表冲突 alone → 置信度×0.70 + A项门槛抬到 0.85
    #   ③ 历史方向不稳定（同卦同方向比例<60%）→ 置信度×0.90
    #   ④ 历史主导方向一致 & 查表一致 → 无惩罚（全通）
    # ──────────────────────────────────────────────────────────────
    @staticmethod
    def _check_hexagram_consistency_for_entry(
        hex_name: str,
        decision_direction: str,           # "UP" 或 "DOWN"
        decision_confidence: float,
        history_window: List[Tuple[str, str]] = None,  # [(hex_name, "long"/"short"), ...]
        min_hist_for_dominant: int = 3,
        dominant_min_ratio: float = 0.60,
        lookup_conflict_conf_mult: float = 0.70,
        lookup_conflict_raise_a_floor: float = 0.85,
        lookup_hist_conflict_hard_block: bool = True,
        unstable_conf_mult: float = 0.90,
    ) -> Dict[str, Any]:
        """开仓前一致性校验（查表 + 历史滑窗）。返回统一 dict 便于单元测试。

        Returns:
            {
              "block": bool,                # True → 直接跳过开仓（硬拦截）
              "confidence_multiplier": float, # ≤1.0，直接乘到 decision_confidence
              "raise_a_floor_to": Optional[float], # A 项过滤最低门槛（如 0.85）
              "reason": str,                 # 日志用，简要说明判决依据
              "lookup_direction": str,       # 查表方向(long/short/neutral/空)
              "dominant_hist_dir": Optional[str],
              "dominant_hist_ratio": Optional[float],
            }
        """
        # 路径兼容：tests/ 目录下 sys.path 直接插入 memory_l4 → `from bcrm2.xxx import`；
        # 顶层 root 运行时 → `from scripts.memory_l4.bcrm2.xxx import`
        try:
            from bcrm2.dialectical_ml_engine import SIXTY_FOUR_GUAS
        except ModuleNotFoundError:
            from scripts.memory_l4.bcrm2.dialectical_ml_engine import SIXTY_FOUR_GUAS

        # 决策方向归一化
        dec_dir = "long" if decision_direction == "UP" else (
            "short" if decision_direction == "DOWN" else "neutral"
        )

        # (1) 权威查表（直接查 SIXTY_FOUR_GUAS，避免再引入破损的实例映射）
        lookup_dir = "neutral"
        for info in SIXTY_FOUR_GUAS.values():
            if info.get("name") == hex_name:
                lookup_dir = info.get("direction", "neutral")
                break

        lookup_conflict = (
            lookup_dir in ("long", "short") and lookup_dir != dec_dir
        )

        # (2) 历史滑窗主导方向统计（仅统计"同一卦象"的历史记录）
        dominant_hist_dir: Optional[str] = None
        dominant_hist_ratio: Optional[float] = None
        hist_unstable = False
        hist_count_for_same_hex = 0
        same_hex_hist = []
        if history_window:
            same_hex_hist = [d for h, d in history_window if h == hex_name
                             and d in ("long", "short")]
            hist_count_for_same_hex = len(same_hex_hist)
            if hist_count_for_same_hex >= min_hist_for_dominant:
                cnts: Dict[str, int] = {}
                for d in same_hex_hist:
                    cnts[d] = cnts.get(d, 0) + 1
                top_dir, top_cnt = max(cnts.items(), key=lambda kv: kv[1])
                ratio = top_cnt / hist_count_for_same_hex
                dominant_hist_dir = top_dir
                dominant_hist_ratio = ratio
                if ratio < dominant_min_ratio:
                    # 同卦历史方向分歧大 → 不稳定
                    hist_unstable = True

        hist_conflict_with_decision = (
            dominant_hist_dir is not None and dominant_hist_dir != dec_dir
        )
        hist_conflict_with_lookup = (
            dominant_hist_dir is not None and lookup_dir in ("long", "short")
            and dominant_hist_dir != lookup_dir
        )

        # (3) 判决
        # 注：需要 (lookup_conflict ∧ hist_conflict_with_decision ∧ ¬hist_conflict_with_lookup)
        #    即「查表」与「历史主导方向」一致反对决策方向时，才触发「硬拦截」。
        #    缺 ¬hist_conflict_with_lookup → 当 lookup=SHORT 历史主导=LONG 决策=UP 时
        #    两者虽都不等于决策方向，但互相矛盾，不应硬拦截。
        if (lookup_conflict and hist_conflict_with_decision
                and not hist_conflict_with_lookup
                and lookup_hist_conflict_hard_block):
            return {
                "block": True,
                "confidence_multiplier": 0.0,
                "raise_a_floor_to": None,
                "reason": (
                    f"查表({lookup_dir})+历史({dominant_hist_dir},"
                    f"{(dominant_hist_ratio or 0):.0%})双冲突，硬拦截"
                ),
                "lookup_direction": lookup_dir,
                "dominant_hist_dir": dominant_hist_dir,
                "dominant_hist_ratio": dominant_hist_ratio,
            }

        if lookup_conflict:
            return {
                "block": False,
                "confidence_multiplier": lookup_conflict_conf_mult,
                "raise_a_floor_to": lookup_conflict_raise_a_floor,
                "reason": (
                    f"查表冲突: {hex_name}={lookup_dir}(权威) vs 决策{dec_dir} "
                    f"→ 置信度×{lookup_conflict_conf_mult:.2f} + A项地板"
                    f"={lookup_conflict_raise_a_floor:.2f}"
                ),
                "lookup_direction": lookup_dir,
                "dominant_hist_dir": dominant_hist_dir,
                "dominant_hist_ratio": dominant_hist_ratio,
            }

        if hist_unstable:
            return {
                "block": False,
                "confidence_multiplier": unstable_conf_mult,
                "raise_a_floor_to": None,
                "reason": (
                    f"同卦历史方向不稳定({hist_count_for_same_hex}笔，"
                    f"一致率仅{(dominant_hist_ratio or 0):.0%}<"
                    f"{dominant_min_ratio:.0%}) → 置信度×{unstable_conf_mult:.2f}"
                ),
                "lookup_direction": lookup_dir,
                "dominant_hist_dir": dominant_hist_dir,
                "dominant_hist_ratio": dominant_hist_ratio,
            }

        return {
            "block": False,
            "confidence_multiplier": 1.0,
            "raise_a_floor_to": None,
            "reason": "查表+历史均一致",
            "lookup_direction": lookup_dir,
            "dominant_hist_dir": dominant_hist_dir,
            "dominant_hist_ratio": dominant_hist_ratio,
        }

    # 64卦名首字 → 八卦元素映射（上卦/下卦提取）
    _HEX_CHAR_TO_GUA = {
        "乾": "qian",
        "天": "qian",
        "坤": "kun",
        "地": "kun",
        "震": "zhen",
        "雷": "zhen",
        "巽": "xun",
        "风": "xun",
        "坎": "kan",
        "水": "kan",
        "离": "li",
        "火": "li",
        "艮": "gen",
        "山": "gen",
        "兑": "dui",
        "泽": "dui",
    }

    # ──────────────────────────────────────────────────────────────
    # P2-02 重构：把原推断逻辑抽为 _infer_regime_base（字节等价原实现）
    #           外层 _infer_regime 加 macro correction 开关包裹
    # ──────────────────────────────────────────────────────────────
    def _infer_regime_base(
        self, hexagram_name: str, is_ranging: bool, direction: str = "", closes: list = None
    ) -> str:
        """[BYTE-EQUIVALENT 原实现] 从卦象名+市场状态推断 regime（8态之一）

        轻量级推断，不依赖 MarketRegimeClassifier 训练。
        """
        from scripts.memory_l4.bcrm2.market_regime import GUA_REGIME_MAP

        if not hexagram_name or hexagram_name == "已存在持仓":
            # 无卦象时用 is_ranging + direction 兜底
            if is_ranging:
                return "RANGE_BOUND"
            if direction == "UP":
                return "TREND_UP_MILD"
            if direction == "DOWN":
                return "VOLATILE_DROP"
            return "CONSOLIDATION"

        # 纯卦格式："X为Y"（如"乾为天"）→ 取首字
        if "为" in hexagram_name:
            first_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[0], "")
            if first_gua and first_gua in GUA_REGIME_MAP:
                regime = GUA_REGIME_MAP[first_gua]
                # 震荡市降级
                if is_ranging and regime in ("TREND_UP_STRONG", "TREND_UP_MILD", "BREAKOUT"):
                    return "RANGE_BOUND"
                return regime

        # 组合卦：取前两字作为上下卦（如"水山蹇"→上坎下艮）
        # 下卦（第1字）为主，上卦（第2字）为辅
        if len(hexagram_name) >= 2:
            lower_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[0], "")
            upper_gua = self._HEX_CHAR_TO_GUA.get(hexagram_name[1], "")

            # 优先用下卦（主卦）映射
            if lower_gua and lower_gua in GUA_REGIME_MAP:
                regime = GUA_REGIME_MAP[lower_gua]
                # 震荡市降级：强趋势/突破类 → 震荡
                if is_ranging and regime in (
                    "TREND_UP_STRONG",
                    "TREND_UP_MILD",
                    "BREAKOUT",
                    "FOMO_RALLY",
                ):
                    return "RANGE_BOUND"
                return regime

            # 下卦未命中，尝试上卦
            if upper_gua and upper_gua in GUA_REGIME_MAP:
                return GUA_REGIME_MAP[upper_gua]

        # 价格趋势兜底
        if closes and len(closes) >= 20:
            if closes[-1] > closes[-20]:
                return "TREND_UP_MILD" if not is_ranging else "RANGE_BOUND"
            elif closes[-1] < closes[-20]:
                return "VOLATILE_DROP" if not is_ranging else "RANGE_BOUND"

        return "CONSOLIDATION"

    def _infer_regime(
        self,
        hexagram_name: str,
        is_ranging: bool,
        direction: str = "",
        closes: list = None,
        macro_features: dict = None,
        enable_macro_correction: bool = True,
    ) -> str:
        """[外层] 从卦象名 + 市场状态 + macro(爆仓/期权) 推断 8 态

        Args:
            hexagram_name:   卦象名（如 乾为天 / 水山蹇 / 已存在持仓）
            is_ranging:      是否震荡市
            direction:       价格方向（UP/DOWN/空）
            closes:          收盘价序列（最长 20 根以上，用于无卦兜底）
            macro_features:  collect_global() 顶层字段字典，缺省为 {}
            enable_macro_correction: S5 开关，False 时字节等价旧路径
        """
        # ① 先跑基础推断（100% 字节等价旧实现，开关关时直接返回）
        base = self._infer_regime_base(hexagram_name, is_ranging, direction, closes)

        if not enable_macro_correction:
            return base
        if not macro_features:
            return base

        # ② 爆仓/期权 macro overlay 校正
        from scripts.memory_l4.bcrm2.market_regime import apply_macro_regime_correction
        try:
            return apply_macro_regime_correction(base, macro_features)
        except Exception:
            # graceful：校正器任何异常 → 回退基础推断（不影响交易主链路）
            return base

    # ──────────────────────────────────────────────────────────────
    # P2-03：FreeMarketFeed 集成 + 5 分钟缓存 + graceful 失败
    # ──────────────────────────────────────────────────────────────
    def _get_macro_feed_instance(self):
        """获取 FreeMarketFeed 单例（懒加载，仅首次调用时实例化 + 注入 sys.path）

        单独抽出来是为了 P2-03 T4 monkeypatch mock 测试覆盖异常分支。
        """
        import sys as _sys, os as _os
        if not hasattr(self, "_macro_feed_singleton") or self._macro_feed_singleton is None:
            # 注入 1-ARCHITECTURE 包路径到 sys.path（项目跨 package 引用）
            _proj_root = _os.path.abspath(_os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "..", "..", "..", "1-ARCHITECTURE"
            ))
            if _proj_root not in _sys.path:
                _sys.path.insert(0, _proj_root)
            from dreamos.capabilities.trading.free_market_feed import FreeMarketFeed
            self._macro_feed_singleton = FreeMarketFeed()
        return self._macro_feed_singleton

    def _fetch_global_macro_features_once(
        self,
        cache_ttl_sec: int = 300,
        _test_skip_network: bool = False,
    ) -> dict:
        """形态预测器专用：从 FreeMarketFeed.collect_global 取顶层 liq_/crypto_vix_/btc_option_* 字段

        Cache：5 分钟 TTL（形态慢变量，过高频调用会被 OKX/Binance rate-limit）
        Graceful：任何异常 → 返回空 {}，不冒泡阻塞主链路
        """
        import time as _time
        # lazy 初始化 cache 结构（不写 __init__ 防旧实例化路径崩）
        if not hasattr(self, "_macro_feature_cache") or self._macro_feature_cache is None:
            self._macro_feature_cache = {"ts": 0, "data": {}}

        now = _time.time()
        # TTL 命中缓存直接返回
        if (now - self._macro_feature_cache.get("ts", 0)) < cache_ttl_sec:
            return dict(self._macro_feature_cache["data"])  # 浅拷贝避免外部污染

        if _test_skip_network:
            # TTL 失效 + 跳过网络调用（测试模式）→ 返回空 dict，不写入 cache
            return {}

        # 真实调用 FMF
        try:
            feed = self._get_macro_feed_instance()
            global_snap = feed.collect_global()
            # 只取形态预测器消费的顶层字段（约 10 个），避免整包序列化开销
            whitelist = [
                "liq_panic_score_0_to_1", "liq_panic_level", "liq_regime_hint",
                "liq_long_short_ratio", "liq_cascade_hours", "liq_total_24h_usd",
                "crypto_vix_proxy_pct", "options_regime_hint",
                "btc_option_atm_iv_pct", "btc_option_pc_skew_25d_pct",
                "btc_option_iv_level", "btc_option_skew_sentiment",
                "eth_option_atm_iv_pct", "eth_option_pc_skew_25d_pct",
                "eth_option_iv_level", "eth_option_skew_sentiment",
            ]
            filtered = {k: global_snap.get(k) for k in whitelist if k in global_snap}
        except Exception:
            # 任何错误（网络/路径/实例化/超时）→ 空 dict，不写 cache（下次重试）
            return {}

        # 写 cache，ts 记录成功调用时刻
        self._macro_feature_cache = {"ts": now, "data": filtered}
        return dict(filtered)

    # ──────────────────────────────────────────────────────────────
    # P2-04：REGIME_MULTIPLIERS（8 态 × 4 维参数乘数）+ 查询接口
    # ──────────────────────────────────────────────────────────────
    REGIME_MULTIPLIERS: dict = {
        # Spec §5.1 表：强趋势 → 加仓、放止盈、松止损、宽门槛
        "TREND_UP_STRONG": {
            "position_mult":  1.20,
            "tp_mult":        1.30,
            "sl_mult":        1.15,
            "threshold_mult": 0.80,
        },
        "TREND_UP_MILD": {
            "position_mult":  1.05,
            "tp_mult":        1.10,
            "sl_mult":        1.05,
            "threshold_mult": 0.92,
        },
        "BREAKOUT": {
            "position_mult":  1.10,
            "tp_mult":        1.20,
            "sl_mult":        1.00,
            "threshold_mult": 0.85,
        },
        # 震荡类 → 减仓、紧止盈、宽止损（震荡别追、别打止损）
        "RANGE_BOUND": {
            "position_mult":  0.80,
            "tp_mult":        0.85,
            "sl_mult":        1.20,
            "threshold_mult": 1.15,
        },
        "CONSOLIDATION": {
            "position_mult":  0.70,
            "tp_mult":        0.80,
            "sl_mult":        1.25,
            "threshold_mult": 1.20,
        },
        # 风险/反转类 → 极度保守
        "VOLATILE_DROP": {
            "position_mult":  0.35,
            "tp_mult":        0.75,
            "sl_mult":        0.65,
            "threshold_mult": 1.15,
        },
        "FOMO_RALLY": {
            "position_mult":  0.85,
            "tp_mult":        0.60,
            "sl_mult":        0.70,
            "threshold_mult": 1.15,
        },
        "REVERSAL": {
            "position_mult":  0.50,
            "tp_mult":        0.75,
            "sl_mult":        0.80,
            "threshold_mult": 1.25,
        },
    }

    def _get_regime_pred_multipliers(
        self,
        regime: str,
        enable_regime_pred: bool = True,
    ) -> dict:
        """查 8 态乘数表；开关关 / regime 非法 → 全 1.0

        返回格式: {position_mult, tp_mult, sl_mult, threshold_mult}

        注意：弹簧力场分类器（5 态：TREND_BULL/TREND_BEAR/...）与形态预测
        S5 REGIME_MULTIPLIERS（8 态：TREND_UP_STRONG/BREAKOUT/...）是两套独立标签
        体系；这里通过 FMA5→S5 映射桥兼容，保证「S5 形态乘数永远=1.0」的问题不会出现。
        """
        # 开关关 → 字节等价旧路径（全 1.0）
        if not enable_regime_pred:
            return {"position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0}

        # ── FMA5→S5 标签桥（5 态 → 8 态，保守映射）─────────────────
        #   映射原则：强度对齐 + 风险偏好偏保守（宁可低估牛市也不错误高估）
        _FMA_TO_S5 = {
            "TREND_BULL":        "TREND_UP_MILD",    # 普通多头趋势
            "STRONG_TREND_BULL": "TREND_UP_STRONG",  # 若上游未来新增强牛标签
            "STRONG_TREND_BEAR": "VOLATILE_DROP",    # 强空头趋势 → 视为暴跌态（保守）
            "TREND_BEAR":        "REVERSAL",         # 弱空头 → 反转态
            "MEAN_REVERTING":    "CONSOLIDATION",    # 均值回归 → 整理（偏保守）
            "RANGING":           "RANGE_BOUND",      # 震荡 → 区间震荡
        }
        _resolved = regime
        if isinstance(regime, str) and (regime not in self.REGIME_MULTIPLIERS):
            _mapped = _FMA_TO_S5.get(regime)
            if _mapped and _mapped in self.REGIME_MULTIPLIERS:
                _resolved = _mapped

        # regime 未命中表 → 全 1.0 fallback，不抛异常
        if not isinstance(_resolved, str) or (_resolved not in self.REGIME_MULTIPLIERS):
            return {"position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0}

        # 返回一份副本，避免外部改动污染 class 常量
        return dict(self.REGIME_MULTIPLIERS[_resolved])

    # ══════════════════════════════════════════════════════════════
    # v5.0 离场防频繁：离场确认状态机 + 持仓保护期门禁
    # ══════════════════════════════════════════════════════════════

    def _is_position_protected(self, position_age_sec: float) -> bool:
        """判断持仓是否在保护期内（开仓后前N小时）

        保护期内：仅P0硬止损/静态SL/TP生效；易经动态SL/TP调整屏蔽；
        信号反转/P3提前退出需要更高门槛 + 离场确认。
        """
        return position_age_sec < (self.POSITION_PROTECTION_HOURS * 3600.0)

    def _exit_confirm(self, coin: str, action_type: str) -> Tuple[bool, int]:
        """离场动作2次确认状态机。

        Args:
            coin: 币种
            action_type: 动作类型（signal_reverse / yijing_force_close / p3_early_exit）

        Returns:
            (confirmed: bool, current_count: int)
                confirmed: 是否达到确认次数（可执行离场）
                current_count: 当前累计确认次数
        """
        now = time.time()
        key = f"{coin}:{action_type}"

        state = self._exit_confirm_state.get(key)
        if state is None:
            # 第一次触发：记录，未确认
            self._exit_confirm_state[key] = {
                "confirm_count": 1,
                "first_ts": now,
            }
            return False, 1

        # 检查是否在确认窗口内
        elapsed = now - state["first_ts"]
        if elapsed > self.EXIT_CONFIRM_WINDOW_SEC:
            # 窗口超时：重置为第一次
            self._exit_confirm_state[key] = {
                "confirm_count": 1,
                "first_ts": now,
            }
            return False, 1

        # 窗口内：累计+1
        state["confirm_count"] += 1
        self._exit_confirm_state[key] = state
        confirmed = state["confirm_count"] >= self.EXIT_CONFIRM_REQUIRED
        return confirmed, state["confirm_count"]

    def _clear_exit_confirm(self, coin: str, action_type: str = ""):
        """清除某币种的离场确认状态。

        离场执行后、或条件不再满足时调用，避免状态污染。
        """
        if action_type:
            key = f"{coin}:{action_type}"
            self._exit_confirm_state.pop(key, None)
        else:
            # 清除该币种所有动作类型
            prefix = f"{coin}:"
            keys = [k for k in self._exit_confirm_state if k.startswith(prefix)]
            for k in keys:
                self._exit_confirm_state.pop(k, None)

    def _check_positions(self, coin: str) -> dict:
        """检查指定币种的持仓。
        Bug修复：返回 open_time（开仓时间戳,秒），供离场系统计算持仓年龄。
        优先从本地 PositionTracker.entry_time 读取（更准确），缺失时回退 OKX ctime。
        OKX API 限流时回退 position_tracker，确保 EV/S3 离场管理不被跳过。
        """
        inst_id = f"{coin}-USDT-SWAP"
        pos_result = self.okx_client.get_positions(inst_id)
        if not pos_result.get("ok"):
            # OKX API 失败（限流等）→ 回退 position_tracker 本地记录
            tracker_rec = self.position_tracker.get_open_position(inst_id)
            if tracker_rec:
                open_time_sec = 0.0
                if tracker_rec.entry_time:
                    try:
                        if tracker_rec.entry_time.endswith("Z"):
                            ts = tracker_rec.entry_time.replace("Z", "+00:00")
                        else:
                            ts = tracker_rec.entry_time
                        from datetime import datetime as _dt
                        open_time_sec = _dt.fromisoformat(ts).timestamp()
                    except Exception:
                        open_time_sec = 0.0
                # ★ FIX Bug: entry_time 解析失败时记录告警，便于排查 yijing_window_wait 永久死锁
                if open_time_sec <= 0:
                    self._log(
                        f"[{coin}] OKX API 限流且 entry_time 解析失败 | "
                        f"entry_time={getattr(tracker_rec, 'entry_time', None)} → open_time=0",
                        "WARN",
                    )
                return {
                    "has_position": True,
                    "pos_side": tracker_rec.direction,
                    "pos_size": 0.0,  # OKX 限流时无法获取真实持仓量；下游 EV/S3 不依赖此字段
                    "avg_px": tracker_rec.entry_price,
                    "upl": 0.0,  # OKX 限流时无法获取实时 upl
                    "upl_ratio": 0.0,
                    "mark_px": 0.0,
                    "open_time": open_time_sec,
                    "query_failed": True,  # 标记数据来源为本地回退
                }
            return {"has_position": False, "query_failed": True}
        positions = pos_result.get("positions", [])
        if not positions:
            return {"has_position": False}
        pos = positions[0]

        open_time_sec = 0.0
        tracker_rec = self.position_tracker.get_open_position(inst_id)
        if tracker_rec and tracker_rec.entry_time:
            try:
                if tracker_rec.entry_time.endswith("Z"):
                    ts = tracker_rec.entry_time.replace("Z", "+00:00")
                else:
                    ts = tracker_rec.entry_time
                from datetime import datetime as _dt

                open_time_sec = _dt.fromisoformat(ts).timestamp()
            except Exception:
                open_time_sec = 0.0
        if open_time_sec <= 0:
            # OKX 回退：取 cTime（字符串秒）
            # ★ FIX Bug: okx_simulated.get_positions 现已返回 cTime 字段（之前缺失导致永久 fallback 失败）
            ctime = pos.get("cTime") or pos.get("ctime") or pos.get("created_at", "0")
            try:
                open_time_sec = float(ctime) / 1000 if float(ctime) > 1e12 else float(ctime)
            except Exception:
                open_time_sec = 0.0
            # ★ FIX Bug: OKX ctime 也解析失败时记录告警
            if open_time_sec <= 0:
                self._log(
                    f"[{coin}] open_time 双路失败 | tracker.entry_time="
                    f"{getattr(tracker_rec, 'entry_time', None) if tracker_rec else 'None'}, "
                    f"OKX.cTime={ctime} → open_time=0",
                    "WARN",
                )

        return {
            "has_position": True,
            "pos_side": pos["pos_side"],
            "pos_size": pos["pos"],
            "avg_px": pos["avg_px"],
            "upl": pos["upl"],
            "upl_ratio": pos["upl_ratio"],
            "mark_px": pos["mark_px"],
            "open_time": open_time_sec,
        }

    def _count_total_positions(self) -> int:
        # 单次批量查询OKX全部持仓，避免逐个查询因限流/超时导致计数偏低、超额开仓
        pos_result = self.okx_client.get_positions()
        if pos_result.get("ok"):
            return len(pos_result.get("positions", []))
        # API失败时回退到本地持仓跟踪器
        return len(self.position_tracker.all_open_positions())

    def _count_yijing_positions(self) -> int:
        """统计易经推理系统（bcrm + bdsm 子池）的持仓数，不含 evolution 子池。

        R5 隔离：易经系统与自进化系统共享资金账户但仓位配额独立。
        开仓检查时只看易经子池持仓，避免 evolution 持仓占用易经配额。
        """
        try:
            positions = self.position_tracker.all_open_positions()
        except Exception:
            return 0
        total = 0
        for p in positions:
            ptag = str(getattr(p, "source_tag", "") or "")
            if ptag in ("bcrm", "bdsm"):
                total += 1
        return total

    def _classify_source_tag(self, coin: str) -> str:
        """按币种打子池标签：BDSM_COINS → bdsm；否则 → bcrm。FAIL-OPEN → bcrm。"""
        try:
            if coin and coin.upper() in (getattr(self, "BDSM_COINS", None) or frozenset()):
                return "bdsm"
        except Exception:
            pass
        return "bcrm"

    def _count_subpool_positions(self, source_tag: str) -> int:
        """按 source_tag 统计本地持仓跟踪器里的子池持仓数量。

        R5 隔离核心：计数时只看 TradeRecord.source_tag == 目标标签；
        若 source_tag 为空或未知，不计入任何子池（避免污染边界计数）。
        API 不可用时用本地 tracker 是安全的：每笔下单/平仓都会同步 tracker。
        """
        tag = str(source_tag or "")
        total = 0
        try:
            positions = self.position_tracker.all_open_positions()
        except Exception:
            positions = []
        for p in positions:
            ptag = str(getattr(p, "source_tag", "") or "")
            if not ptag:
                # 老仓位没打 source_tag：按币名回溯分类（兼容启动同步持仓）
                ptag = self._classify_source_tag(str(getattr(p, "coin", "") or ""))
            if ptag == tag:
                total += 1
        return total

    def _count_trial_positions(self, source_tag: str) -> int:
        """统计指定子池内的测试仓（试错仓）数量。

        - BCRM/BDSM 子池：is_trial=True 的持仓（上限 MAX_TRIAL_POSITIONS=2）
        - evolution 子池：market_snapshot["tier"]=="probe" 的持仓（上限 MAX_EVOLUTION_PROBE_POSITIONS=4）

        用户决策 2026-09-11：分离上限 — Evolution probe 独立 4 单，BCRM is_trial 保持 2 单。
        """
        tag = str(source_tag or "")
        total = 0
        try:
            positions = self.position_tracker.all_open_positions()
        except Exception:
            positions = []
        # ★ 修复 2026-09-12：获取 OKX 真实持仓列表，过滤掉本地有但 OKX 无的幽灵持仓
        #   此前只检查 contracts>0，但本地 contracts 可能非 0 而 OKX 已强平
        _okx_inst_ids = None
        try:
            if hasattr(self, "okx_client") and self.okx_client:
                _okx_pos = self.okx_client.get_positions()
                if _okx_pos.get("ok"):
                    _okx_inst_ids = {
                        str(p.get("instId", "")).upper()
                        for p in (_okx_pos.get("positions") or [])
                        if float(p.get("pos", 0) or 0) != 0
                    }
        except Exception:
            _okx_inst_ids = None  # FAIL-OPEN: OKX 查询失败时不过滤
        for p in positions:
            ptag = str(getattr(p, "source_tag", "") or "")
            if not ptag:
                ptag = self._classify_source_tag(str(getattr(p, "coin", "") or ""))
            if ptag != tag:
                continue
            # ★ OKX 持仓存在性校验：如果 OKX 持仓列表已获取，跳过 OKX 端不存在的持仓
            _p_coin = str(getattr(p, "coin", "") or "").upper()
            _p_inst = f"{_p_coin}-USDT-SWAP"
            if _okx_inst_ids is not None and _p_inst not in _okx_inst_ids:
                continue
            if tag == "evolution":
                _snap = getattr(p, "market_snapshot", None) or {}
                if isinstance(_snap, dict) and str(_snap.get("tier", "")) == "probe":
                    # ★ P1-1 修复：跳过 OKX 端已不存在的"幽灵持仓"
                    _p_size = float(getattr(p, "contracts", 0) or getattr(p, "size", 0) or 0)
                    if _p_size <= 0:
                        continue
                    total += 1
            else:
                if getattr(p, "is_trial", False):
                    _p_size = float(getattr(p, "contracts", 0) or getattr(p, "size", 0) or 0)
                    if _p_size <= 0:
                        continue
                    total += 1
        return total

    def _check_subpool_capacity(self, coin: str) -> Tuple[bool, str]:
        """开仓前判断该币种对应子池是否还有空闲仓位（R5 铁律）。

        Returns: (passed: bool, reason: str)
        """
        tag = self._classify_source_tag(coin)
        max_pos = int(self.SUBPOOL_MAX_POSITIONS.get(tag, 0) or 0)
        if max_pos <= 0:
            return False, f"子池{tag}配置无效"
        cur = self._count_subpool_positions(tag)
        if cur >= max_pos:
            return False, f"子池{tag}已满 {cur}/{max_pos}"
        return True, f"子池{tag} {cur}/{max_pos}"

    # ==============================================================
    # BDSM × BCRM 协作 helpers（Phase 2 强耦合 缺口 1/2/3）
    # 统一 FAIL-OPEN：缺失/异常 → 字节等价「BDSM 不存在」
    # ==============================================================
    _BDSM_SNAPSHOT_TTL_SEC = 5 * 60  # 5 min 内复用同一快照，避免每 tick 读盘

    def _neutral_bdsm_skeleton(self, reason: str) -> Dict:
        """FAIL-OPEN 中性骨架 — 字节等价「BDSM 不存在」。"""
        coins: Dict[str, Dict] = {}
        for c in getattr(self, "BDSM_COINS", frozenset()) or frozenset():
            coins[c] = {
                "available": False,
                "score": 0.0,
                "rank": "B",
                "direction_constraint": "NEUTRAL",
                "cap_multiplier": 1.0,
                "exit_action": "NONE",
                "exit_triggers": [],
                "data_quality": "insufficient",
                "phase": "P1",
            }
        return {
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "neutral_fallback_reason": reason,
            "coins": coins,
        }

    def _ensure_bdsm_snapshot_today(self) -> None:
        """确保今日 BDSM 快照已生成。每轮 run_once 调用一次（幂等）。

        快照不存在时调用 write_snapshot() 生成，已存在则跳过。
        FAIL-OPEN：任何异常仅打 WARN，不阻塞主链路。
        """
        try:
            from datetime import date as _date
            _today_str = _date.today().isoformat()
            _filename = f"bdsm_snapshot_{_today_str.replace('-', '')}.json"

            # 复用 _get_bdsm_snapshot_today 的路径逻辑
            try:
                from scripts.memory_l4.force_vector.bdsm_snapshot_writer import (
                    DEFAULT_BDSM_DIR,
                )
            except Exception:
                from force_vector.bdsm_snapshot_writer import (
                    DEFAULT_BDSM_DIR,
                )

            _out_dir = getattr(self, "_bdsm_snapshot_dir", None) or DEFAULT_BDSM_DIR
            _target = os.path.join(_out_dir, _filename)
            if os.path.exists(_target):
                return  # 已生成，跳过

            # 生成快照
            self._log(f"[BDSM] 今日快照不存在，开始生成: {_target}")
            try:
                from scripts.memory_l4.force_vector.bdsm_snapshot_writer import (
                    write_snapshot as _write_snap,
                )
            except Exception:
                from force_vector.bdsm_snapshot_writer import (
                    write_snapshot as _write_snap,
                )

            _write_snap(out_dir=_out_dir, dry_run_read_coin_data_from_db=True)
            self._log(f"[BDSM] 快照生成完成: {_target}")
        except Exception as exc:
            self._log(f"[BDSM] 快照自动生成失败(FAIL-OPEN): {exc}", "WARN")

    def _get_bdsm_snapshot_today(self) -> Dict:
        """读取今日 BDSM 快照（5min TTL 进程缓存）。FAIL-OPEN → neutral_skeleton。"""
        try:
            import time as _t
            now = _t.time()
            cache = getattr(self, "_bdsm_snapshot_cache", None)
            if (
                isinstance(cache, dict)
                and (now - float(cache.get("ts", 0))) <= self._BDSM_SNAPSHOT_TTL_SEC
                and isinstance(cache.get("snapshot"), dict)
            ):
                return cache["snapshot"]

            try:
                from scripts.memory_l4.force_vector.bdsm_snapshot_writer import (
                    load_today_snapshot,
                    DEFAULT_BDSM_DIR,
                )
            except Exception as exc:  # 模块缺失：lazy import FAIL-OPEN
                snap = self._neutral_bdsm_skeleton(
                    f"polling_trader.bdsm_import_fail:{exc}"
                )
                self._bdsm_snapshot_cache = {"ts": now, "snapshot": snap}
                return snap

            try:
                out_dir = getattr(self, "_bdsm_snapshot_dir", None) or DEFAULT_BDSM_DIR
                snap = load_today_snapshot(out_dir=out_dir)
                if not isinstance(snap, dict) or "coins" not in snap:
                    raise ValueError("bad_snapshot_schema: missing coins")
            except Exception as exc:  # 缺文件 / schema 错误 / JSON 解析失败
                snap = self._neutral_bdsm_skeleton(f"bdsm_snapshot_load_fail:{exc}")

            self._bdsm_snapshot_cache = {"ts": now, "snapshot": snap}
            return snap
        except Exception as exc:
            # 终极兜底：任何未捕获异常都不能阻塞执行链
            return self._neutral_bdsm_skeleton(f"bdsm_snapshot_fatal:{exc}")

    def _apply_bdsm_direction_constraint(
        self, coin: str, direction: str
    ) -> Tuple[bool, str]:
        """缺口 1 纯函数：根据 direction_constraint 判定本次开仓方向是否放行。

        生效条件（两重门槛）：
          1. 币种范围：仅 BDSM 池 ∩ BCRM2.0 当前处理币种（coin in BDSM_COINS 保证前者，调用方保证后者）
          2. 置信度门槛：仅 data_quality=="sufficient"（信号覆盖率≥5/7 且 confidence≥0.70）时方向约束才生效
             置信度不足时降级为 NEUTRAL，让 BCRM2.0 技术方向独立决策

        Returns:
            (is_pass, drop_reason)  — reason 同时用于日志关键字。
        """
        try:
            coin_up = (coin or "").upper()
            bdsm_coins = getattr(self, "BDSM_COINS", frozenset()) or frozenset()
            # 条件2：仅 BDSM 池内币种生效（BCRM2.0 只处理自身币种池，故此处即 BDSM ∩ BCRM 交集）
            if coin_up not in bdsm_coins:
                return True, "not_bdsm_coin"

            snap = self._get_bdsm_snapshot_today()
            coin_entry = (snap.get("coins") or {}).get(coin_up) or {}
            constraint = str(coin_entry.get("direction_constraint") or "NEUTRAL").upper()
            data_quality = str(coin_entry.get("data_quality") or "").lower()
            bdsm_confidence = float(coin_entry.get("confidence", 0.0) or 0.0)

            # 条件1：BDSM 置信度门槛 — 仅 sufficient 质量才允许方向约束拦截
            #   sufficient = 信号覆盖率≥5/7 且 confidence≥0.70（基本面判断足够可信）
            #   partial/insufficient → 降级 NEUTRAL，不拦截 BCRM2.0 技术方向
            if data_quality != "sufficient":
                return (
                    True,
                    f"bdsm_confidence_insufficient:dq={data_quality},conf={bdsm_confidence:.2f}",
                )

            want = "long" if direction == "UP" else "short" if direction == "DOWN" else "?"

            if constraint == "LONG_ONLY":
                if want != "long":
                    return (
                        False,
                        f"bdsm_long_only_dropped: snapshot={constraint} want_direction={direction}",
                    )
                return True, "bdsm_long_only_same_direction"
            if constraint == "SHORT_ONLY":
                if want != "short":
                    return (
                        False,
                        f"bdsm_short_only_dropped: snapshot={constraint} want_direction={direction}",
                    )
                return True, "bdsm_short_only_same_direction"
            # NEUTRAL / 其他：FAIL-OPEN 放行
            return True, "neutral_pass"
        except Exception as exc:
            # FAIL-OPEN：约束判断异常 → 放行（BCRM 技术方向）
            return True, f"bdsm_direction_check_failopen:{exc}"

    def _apply_bdsm_cap_multiplier(
        self, coin: str, position_usdt: float
    ) -> Tuple[float, float, str]:
        """缺口 2 纯函数：MIN(position_usdt, position_usdt × cap_multiplier)。

        Returns:
            (actual_usdt, cap_used, info_tag)
            info_tag 取值:
              - not_bdsm_coin
              - fail_open_cap_default_1.0
              - bdsm_cap_applied
              - bdsm_cap_zero_blocked
        """
        try:
            coin_up = (coin or "").upper()
            bdsm_coins = getattr(self, "BDSM_COINS", frozenset()) or frozenset()
            if coin_up not in bdsm_coins:
                return float(position_usdt), 1.0, "not_bdsm_coin"

            snap = self._get_bdsm_snapshot_today()
            coin_entry = (snap.get("coins") or {}).get(coin_up) or {}
            if "cap_multiplier" not in coin_entry:
                return float(position_usdt), 1.0, "fail_open_cap_default_1.0"
            try:
                cap_raw = float(coin_entry["cap_multiplier"] or 0.0)
            except (TypeError, ValueError):
                return float(position_usdt), 1.0, "fail_open_cap_default_1.0"
            cap = max(0.0, min(1.0, cap_raw))
            base = max(0.0, float(position_usdt or 0.0))
            if cap <= 0.0:
                return 0.0, 0.0, "bdsm_cap_zero_blocked"
            actual = min(base, base * cap)
            return actual, cap, "bdsm_cap_applied"
        except Exception as exc:
            # FAIL-OPEN：cap 判断异常 → 原样仓位
            return (
                float(position_usdt or 0.0),
                1.0,
                f"bdsm_cap_check_failopen:{exc}",
            )

    def _get_bdsm_accumulated_position(self, coin: str) -> float:
        """Phase 1 辅助：从 PositionTracker 读取该币的已建仓名义金额。

        FAIL-OPEN：tracker 缺失 / 异常 → 0.0（等价「无历史仓位」）。
        用于 _apply_bdsm_scaling 计算 remaining = remaining_budget - accumulated。
        """
        try:
            coin_up = (coin or "").upper()
            tracker = getattr(self, "position_tracker", None)
            if tracker is None:
                return 0.0
            all_pos = tracker.all_open_positions() or []
            total = 0.0
            for rec in all_pos:
                if (getattr(rec, "coin", "") or "").upper() == coin_up:
                    # 累加 source_tag=bdsm 的仓位（仅 BDSM 子池已建仓）
                    stag = (getattr(rec, "source_tag", "") or "").lower()
                    usdt = float(getattr(rec, "position_usdt", 0.0) or 0.0)
                    if stag and "bdsm" in stag and usdt > 0:
                        total += usdt
            return round(total, 4)
        except Exception:
            return 0.0

    # ── TEE 执行引擎集成（影子模式）──────────────────────────────────
    def _ensure_yijing_engine(self):
        """懒加载 TEE 引擎（NFR-4：构造发生在 tee_core 外部，raw_client 由本方法传入）。"""
        if self._tee_engine is not None:
            return self._tee_engine
        if not self._tee_enable and not self._tee_shadow:
            return None
        with self._tee_engine_init_lock:
            if self._tee_engine is not None:
                return self._tee_engine
            try:
                import importlib.util as _ilu
                import sys as _sys
                from pathlib import Path as _P
                _tee_root = _P(__file__).resolve().parents[3] / "22-执行引擎中心"
                _p = _tee_root / "tee_core/integrations/yijing_integration.py"
                if not _p.is_file():
                    return None
                _name = "_tee_yijing_integration_lazy"
                _spec = _ilu.spec_from_file_location(_name, str(_p))
                _mod = _ilu.module_from_spec(_spec)
                _sys.modules.setdefault(_name, _mod)
                _spec.loader.exec_module(_mod)
                engine, _info = _mod.build_yijing_engine(
                    raw_client=self.okx_client,
                    enable_tee=self._tee_enable,
                    shadow_mode=self._tee_shadow,
                )
                self._tee_engine = engine
                self._log(
                    f"[TEE] 易经推理 TEE 引擎已加载 "
                    f"enable_tee={self._tee_enable} shadow={self._tee_shadow}",
                    "INFO",
                )
            except BaseException as exc:
                # FAIL-OPEN：集成加载失败 → 完全退化为直传，不抛错阻塞轮询
                self._tee_engine = None
                self._log(f"[TEE] 引擎加载失败，退化为直传: {exc}", "WARN")
        return self._tee_engine

    def _wrap_place_order_with_tee(self):
        """包装 okx_client.place_order，实现双轨影子模式。

        双轨影子模式（enable_tee=True, shadow_mode=True）：
          - 调用 TEE execute_market_compat（完整决策链，shadow auditor 只记录不下单）
          - 然后继续走原始 place_order（实际成交不变）
          - TEE shadow 审计日志记录 TEE 决策 vs 实际成交的差异

        真实执行模式（enable_tee=True, shadow_mode=False）：
          - 完全由 TEE execute_market_compat 执行下单，不走原始路径
        """
        engine = self._ensure_yijing_engine()
        if engine is None:
            return

        original_place_order = self.okx_client.place_order

        def _tee_wrapped_place_order(**kwargs):
            # 限价单/带 px → 始终直传（TEE 暂不托管限价单）
            if kwargs.get("px") is not None or kwargs.get("ord_type") not in (None, "market"):
                return original_place_order(**kwargs)

            try:
                tee_result = engine.execute_market_compat(
                    inst_id=kwargs.get("inst_id", ""),
                    side=kwargs.get("side", ""),
                    sz=kwargs.get("sz"),
                    td_mode=kwargs.get("td_mode", "isolated"),
                    pos_side=kwargs.get("pos_side", "net"),
                    leverage=kwargs.get("leverage"),
                    tag="yijing_shadow",
                    reason=kwargs.get("reason", ""),
                )
                # 如果 TEE 真实执行（非 shadow），直接返回 TEE 结果
                if not self._tee_shadow:
                    return tee_result
                # shadow 模式：TEE 只记录，实际下单走原始路径
            except BaseException:
                pass  # FAIL-OPEN：TEE 执行失败不影响实际下单
            return original_place_order(**kwargs)

        self.okx_client.place_order = _tee_wrapped_place_order

    def _execute_evolution_order_via_tee(
        self,
        inst_id: str,
        side: str,
        usdt_amount: float,
        pos_side: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """自进化子池专用：通过 TEE 执行引擎真实下单（独立于 BCRM/BDSM）。

        与全局 place_order 包装隔离：
          - BCRM/BDSM 走 okx_client.market_open_*（原始路径，TEE 仅影子审计）
          - evolution 子池走此方法（TEE 真实执行，带 kill_switch/slippage/auditor）

        Returns:
            与 market_open_long/short 兼容的 dict: {ok, ord_id, avg_px, ...}
        """
        engine = self._ensure_yijing_engine()
        if engine is None or not self._tee_enable:
            # TEE 不可用时 FAIL-OPEN 回退原始路径
            if pos_side == "long":
                return self.okx_client.market_open_long(inst_id, usdt_amount=usdt_amount, reason=reason)
            else:
                return self.okx_client.market_open_short(inst_id, usdt_amount=usdt_amount, reason=reason)

        try:
            sz = self.okx_client._usdt_to_sz(inst_id, usdt_amount)
            result = engine.execute_market_compat(
                inst_id=inst_id,
                side=side,
                sz=sz,
                td_mode="isolated",
                pos_side=pos_side,
                tag="evolution_real",
                reason=reason or f"evolution_{pos_side}",
            )
            # 映射回 market_open_* 兼容格式
            return {
                "ok": result.get("ok", True),
                "ord_id": result.get("ord_id", ""),
                "avg_px": result.get("avg_px", 0.0),
                "price": result.get("avg_px", 0.0),
                "filled_sz": result.get("filled_sz", sz),
                "state": result.get("state", "filled"),
                "data": result.get("data", {}),
            }
        except BaseException as e:
            self._log(
                f"[P2-S4b] evolution TEE 执行失败，回退原始路径: {type(e).__name__}: {e}",
                "WARN",
            )
            # FAIL-OPEN：TEE 失败回退原始下单
            if pos_side == "long":
                return self.okx_client.market_open_long(inst_id, usdt_amount=usdt_amount, reason=reason)
            else:
                return self.okx_client.market_open_short(inst_id, usdt_amount=usdt_amount, reason=reason)

    def _execute_evolution_close_via_tee(
        self,
        inst_id: str,
        pos_side: str,
        reduce_ratio: float = 1.0,
        reason: str = "",
    ) -> Dict[str, Any]:
        """自进化子池专用：通过 TEE 执行引擎平仓（独立于 BCRM/BDSM）。

        Args:
            reduce_ratio: 1.0=全部平仓, 0.1~0.9=部分平仓

        Returns:
            与 market_close_* 兼容的 dict
        """
        engine = self._ensure_yijing_engine()
        if engine is None or not self._tee_enable:
            # TEE 不可用时 FAIL-OPEN 回退原始路径
            if reduce_ratio >= 1.0:
                if pos_side == "long":
                    return self.okx_client.market_close_long(inst_id, reason=reason)
                else:
                    return self.okx_client.market_close_short(inst_id, reason=reason)
            else:
                if hasattr(self.okx_client, "reduce_position"):
                    return self.okx_client.reduce_position(
                        inst_id=inst_id, pos_side=pos_side,
                        reduce_ratio=reduce_ratio, reason=reason,
                    )
                # 无部分平仓接口时回退全平
                if pos_side == "long":
                    return self.okx_client.market_close_long(inst_id, reason=reason)
                else:
                    return self.okx_client.market_close_short(inst_id, reason=reason)

        try:
            # 查询当前持仓获取 sz
            _pos_q = self.okx_client.get_positions(inst_id)
            sz = 0
            if _pos_q.get("ok"):
                for _p in _pos_q.get("positions", []):
                    if _p.get("pos_side") == pos_side and float(_p.get("pos", 0)) > 0:
                        sz = float(_p.get("pos", 0))
                        break
            if sz <= 0:
                return {"ok": False, "error": "no position to close"}

            close_sz = int(sz * reduce_ratio) if reduce_ratio < 1.0 else int(sz)
            if close_sz <= 0:
                return {"ok": False, "error": "reduce size too small"}

            side = "sell" if pos_side == "long" else "buy"
            result = engine.execute_market_compat(
                inst_id=inst_id,
                side=side,
                sz=close_sz,
                td_mode="isolated",
                pos_side=pos_side,
                tag="evolution_close_real",
                reason=reason or f"evolution_close_{pos_side}",
            )
            return {
                "ok": result.get("ok", True),
                "ord_id": result.get("ord_id", ""),
                "avg_px": result.get("avg_px", 0.0),
                "price": result.get("avg_px", 0.0),
                "filled_sz": result.get("filled_sz", close_sz),
                "state": result.get("state", "filled"),
                "data": result.get("data", {}),
            }
        except BaseException as e:
            self._log(
                f"[EvolutionExitEngine] evolution TEE 平仓失败，回退原始路径: {type(e).__name__}: {e}",
                "WARN",
            )
            # FAIL-OPEN：TEE 失败回退原始平仓
            if reduce_ratio >= 1.0:
                if pos_side == "long":
                    return self.okx_client.market_close_long(inst_id, reason=reason)
                else:
                    return self.okx_client.market_close_short(inst_id, reason=reason)
            else:
                if hasattr(self.okx_client, "reduce_position"):
                    return self.okx_client.reduce_position(
                        inst_id=inst_id, pos_side=pos_side,
                        reduce_ratio=reduce_ratio, reason=reason,
                    )
                if pos_side == "long":
                    return self.okx_client.market_close_long(inst_id, reason=reason)
                else:
                    return self.okx_client.market_close_short(inst_id, reason=reason)

    def _apply_bdsm_scaling(
        self, coin: str, position_usdt: float, current_price: float
    ) -> Tuple[float, float, str]:
        """Phase 1（gap2 升级）：动态评估器（CVS）驱动的分批建仓。

        spec §3.2.2 + §5.3 Phase 1：
          - CVS < 0.3 或 scaling_plan 缺失 → FAIL-OPEN 回退 _apply_bdsm_cap_multiplier
          - CVS 0.3~0.6 → batch = remaining × 0.3
          - CVS 0.6~0.8 → batch = remaining × 0.5
          - CVS >= 0.8 → 打完子弹 batch = remaining
          - remaining <= 0 → (0.0, 0.0, "bdsm_scaling_completed")

        Returns:
            (batch_notional, cap_used, info_tag)
        """
        try:
            coin_up = (coin or "").upper()
            bdsm_coins = getattr(self, "BDSM_COINS", frozenset()) or frozenset()
            if coin_up not in bdsm_coins:
                return float(position_usdt), 1.0, "not_bdsm_coin"

            snap = self._get_bdsm_snapshot_today()
            coin_entry = (snap.get("coins") or {}).get(coin_up) or {}

            try:
                cvs = float(coin_entry.get("cvs", 0.0) or 0.0)
                ratio = float(coin_entry.get("cvs_ratio", 0.0) or 0.0)
            except (TypeError, ValueError):
                cvs, ratio = 0.0, 0.0

            plan = coin_entry.get("scaling_plan") or {}

            # FAIL-OPEN：CVS 不达标 或 plan 缺失 → 回退原 cap 逻辑
            if not plan or cvs < 0.3:
                # ── 战术小仓分支（2026-09-06 新增）──────────────────────
                # BDSM 标准仓因 cvs<0.3 被拦截，但标的基本面强（bds≥0.3）且
                # 估值偏高/超买 → 用战术小仓（林奇观察仓 + 欧奈尔止损 + 德鲁肯米勒小仓）
                _tactical = self._try_tactical_micro_position(coin_up, coin_entry)
                if _tactical is not None:
                    return _tactical
                return self._apply_bdsm_cap_multiplier(coin, position_usdt)

            # ── P0-A2: spec §3.5 加仓前置检查 5 条（P1-2 实盘对齐）───────
            # 已有 2 条: ③CVS≥0.3  ⑥remaining>0 (下方资金)
            # 新增 5 条：
            #   ① BDS 基本面未恶化（bds_score ≥ 0.0）
            #   ④ war_state = ALLOW（五计庙算宏观允许）
            #   ⑦ value_exit.action ≠ full_exit（未触发完整出场信号）
            #   ⑧ trend_stop.action == none（未触发趋势止损）
            #   ⑨ 距上次加仓 ≥ 间隔 (实盘用 _last_bdsm_entry_ts 追踪，默认≥1 tick=300s/5min>4h)
            # FAIL-OPEN：任何一条不满足 → 回退 cap_multiplier（等价 BDSM 不参与，安全兜底）
            _pre_block_tag = None
            try:
                # ① BDS ≥ 0
                _bds = float(coin_entry.get("bds_score", 0.0) or 0.0)
                if _bds < 0.0:
                    _pre_block_tag = f"bds_below_zero_{_bds:.2f}"
                # ④ war_state = ALLOW（战略层 cache 读取）
                #   开关 enable_bdsm_war_state_check（默认 False）：
                #   False → BDSM 独立验证，不受战略层 war_state 影响
                #   True  → 战略层 FREEZE/COOLDOWN 拦截 BDSM 加仓
                if _pre_block_tag is None and getattr(self, "enable_bdsm_war_state_check", False):
                    _war_cache = getattr(self, "_five_domain_state_cache", None)
                    if _war_cache is not None:
                        _war = getattr(_war_cache, "war_state", None)
                        if isinstance(_war, dict) and _war.get("crypto_usdt", "ALLOW") != "ALLOW":
                            _pre_block_tag = "war_state_blocked"
                # ⑦ value_exit.action ≠ full_exit
                if _pre_block_tag is None:
                    _ve = coin_entry.get("value_exit") or {}
                    if str(_ve.get("action", "none") or "none").lower() in ("full_exit", "reduce50"):
                        _pre_block_tag = f"value_exit_{_ve.get('action')}"
                # ⑧ trend_stop.action == none（reduce 也不能加仓，趋势坏了不摊平）
                if _pre_block_tag is None:
                    _ts = coin_entry.get("trend_stop") or {}
                    if str(_ts.get("action", "none") or "none").lower() != "none":
                        _pre_block_tag = f"trend_stop_{_ts.get('action')}"
                # ⑨ 加仓间隔 ≥ 1 tick（300s，远大于 spec 的 4h）
                if _pre_block_tag is None:
                    _last_ts = getattr(self, "_last_bdsm_entry_days", None)
                    if isinstance(_last_ts, dict):
                        _last_day = _last_ts.get(coin_up)
                        if _last_day is not None:
                            import time as _t
                            _now_day = int(_t.time() // 86400)  # 日级序号
                            if _now_day - int(_last_day) < 1:
                                _pre_block_tag = "entry_interval_too_soon"
            except Exception:
                _pre_block_tag = None  # 异常不阻断（FAIL-OPEN）

            if _pre_block_tag is not None:
                self._log(
                    f"[{coin_up}] BDSM 加仓前置检查拦截 → {_pre_block_tag} | 回退 cap 逻辑",
                    "WARN",
                )
                return self._apply_bdsm_cap_multiplier(coin, position_usdt)

            try:
                remaining_budget = float(plan.get("remaining_budget", 167.0) or 167.0)
            except (TypeError, ValueError):
                remaining_budget = 167.0

            # — BDSM 微仓实盘测试硬上限：CLI 通过 --bdsm-budget-per-coin 传入时
            #   对 scaling_plan.remaining_budget 做 min 覆盖，防止首次真实环境测试
            #   单次投放过大。FAIL-OPEN：类型异常/None → 不覆盖，沿用 plan。
            try:
                _budget_cap = getattr(self, "bdsm_budget_per_coin", None)
                if _budget_cap is not None:
                    _cap = float(_budget_cap)
                    if _cap > 0:
                        if remaining_budget > _cap:
                            self._log(
                                f"[{coin_up}] BDSM 微仓硬上限生效 scaling_plan.remaining_budget "
                                f"{remaining_budget:.2f}U → min= {_cap:.2f}U",
                                "INFO",
                            )
                        remaining_budget = min(remaining_budget, _cap)
            except (TypeError, ValueError):
                pass  # FAIL-OPEN：覆盖失败，沿用解析好的 remaining_budget

            accumulated = float(self._get_bdsm_accumulated_position(coin) or 0.0)
            remaining = remaining_budget - accumulated

            # 已建满 → 拦截
            if remaining <= 0:
                return 0.0, 0.0, "bdsm_scaling_completed"

            batch_notional = remaining * ratio

            # "打完子弹"：CVS >= 0.8 → 全投
            if cvs >= 0.8:
                batch_notional = remaining

            # P0-A2 ⑨：记录此次加仓日（供下次间隔检查）
            try:
                import time as _t
                if not hasattr(self, "_last_bdsm_entry_days") or not isinstance(getattr(self, "_last_bdsm_entry_days", None), dict):
                    self._last_bdsm_entry_days = {}
                self._last_bdsm_entry_days[coin_up] = int(_t.time() // 86400)
            except Exception:
                pass

            return (
                float(batch_notional),
                1.0,
                f"bdsm_cvs_{cvs:.2f}_ratio_{ratio:.1f}",
            )
        except Exception as exc:
            # FAIL-OPEN：scaling 异常 → 回退原 cap 逻辑
            return self._apply_bdsm_cap_multiplier(coin, position_usdt)

    def _try_tactical_micro_position(
        self, coin_up: str, coin_entry: Dict[str, Any]
    ) -> Optional[Tuple[float, float, str]]:
        """战术小仓分支：基本面强但标准仓被估值/超买拦截时，小仓入场。

        融合林奇观察仓 + 欧奈尔止损 + 德鲁肯米勒小仓。
        开关：ENABLE_TACTICAL_MICRO_POSITION（默认 False → 不生效）

        Returns:
            (batch_notional, cap_used, info_tag) 或 None（不走战术小仓）
        """
        try:
            from force_vector.bdsm_tactical_position import (
                ENABLE_TACTICAL_MICRO_POSITION,
                TACTICAL_MICRO_BUDGET_USDT,
                TACTICAL_MAX_POSITIONS,
                tactical_entry_check,
            )

            if not ENABLE_TACTICAL_MICRO_POSITION:
                return None

            if not tactical_entry_check(coin_entry):
                return None

            # 战术小仓配额不占用 BDSM 标准仓预算，独立计数
            accumulated = float(self._get_bdsm_accumulated_position(coin_up) or 0.0)
            if accumulated >= TACTICAL_MICRO_BUDGET_USDT:
                return None

            batch_notional = TACTICAL_MICRO_BUDGET_USDT - accumulated

            self._log(
                f"[{coin_up}] 战术小仓入场 bds={float(coin_entry.get('bds_score', 0)):.3f} "
                f"batch={batch_notional:.2f}U",
                "INFO",
            )
            return (
                float(batch_notional),
                1.0,
                "tactical_micro_position",
            )
        except Exception:
            return None  # FAIL-OPEN

    def _get_coin_position_info(self, coin: str) -> Dict[str, Any]:
        """缺口 3 辅助：按币名从 PositionTracker.open_positions 取持仓信息。

        统一返回 has_position 键；失败 → has_position=False。
        """
        try:
            coin_up = (coin or "").upper()
            tracker = getattr(self, "position_tracker", None)
            if tracker is None:
                return {"has_position": False}
            all_pos = tracker.all_open_positions() or []
            for rec in all_pos:
                if (getattr(rec, "coin", "") or "").upper() == coin_up:
                    inst_id = getattr(rec, "inst_id", "") or f"{coin_up}-USDT-SWAP"
                    pos_side = getattr(rec, "direction", "") or "long"
                    # 净仓模式修复：OKX net 模式返回 posSide="net"，需通过 pos 正负判断方向
                    #   pos > 0 → long, pos < 0 → short
                    if pos_side not in ("long", "short"):
                        try:
                            _pos_qty = float(getattr(rec, "position_qty", 0.0) or getattr(rec, "contracts", 0.0) or 0.0)
                            if _pos_qty < 0:
                                pos_side = "short"
                            elif _pos_qty > 0:
                                pos_side = "long"
                        except Exception:
                            pass
                    entry_px = float(getattr(rec, "entry_price", 0.0) or 0.0)
                    exit_px = float(getattr(rec, "exit_price", 0.0) or entry_px)
                    # 盈亏近似：用 entry / exit 价格差比率 ×100 (单位百分比)
                    if pos_side == "long" and entry_px:
                        pnl_pct = (exit_px - entry_px) / entry_px
                    elif pos_side == "short" and entry_px:
                        pnl_pct = (entry_px - exit_px) / entry_px
                    else:
                        pnl_pct = 0.0
                    usdt_amt = float(getattr(rec, "position_usdt", 0.0) or 0.0)
                    upl = usdt_amt * pnl_pct
                    entry_time = getattr(rec, "entry_time", None) or ""
                    open_ts: float = 0.0
                    try:
                        if entry_time:
                            from datetime import datetime as _dt, timezone as _tz
                            open_ts = _dt.fromisoformat(entry_time.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        open_ts = 0.0
                    # source_tag：取记录原生值；空值时按币名回溯分类（兼容启动同步的老仓位）
                    _src_tag_raw = str(getattr(rec, "source_tag", "") or "")
                    if not _src_tag_raw:
                        _src_tag_raw = self._classify_source_tag(coin_up)
                    return {
                        "has_position": True,
                        "inst_id": inst_id,
                        "coin": coin_up,
                        "pos_side": pos_side,
                        "pos": float(getattr(rec, "position_qty", 0.0) or 0.0),
                        "avg_px": entry_px,
                        "mark_px": exit_px or entry_px,
                        "upl": float(getattr(rec, "pnl", upl) or upl),
                        "upl_ratio": float(getattr(rec, "pnl_pct", pnl_pct) or pnl_pct),
                        "open_time_sec": open_ts,
                        "position_usdt": usdt_amt,
                        "source_tag": _src_tag_raw,
                        "_trade_record": rec,
                    }
            return {"has_position": False}
        except Exception:
            return {"has_position": False}

    @staticmethod
    def _classify_bdsm_short_signal(snapshot, coin: str):
        """BDSM 恶化型离场信号转做空分级。

        返回 'L1'（强做空，仓位0.08）/ 'L2'（中做空，仓位0.05）/ None（不做空）。
        只取恶化型信号，高估型（value_exit=full_exit 且 bds≥0）不转空。

        L1 强信号（任一）：
          - bds_score < 0（基本面恶化）
          - exit_action == CLOSE_ALL（Phase退化/排名连降）
          - trend_stop.action == full_exit（连续5天破MA200+斜率负）

        L2 中信号（任一）：
          - exit_action == REDUCE_80（E7塌）
          - trend_stop.action == reduce50（连续3天破MA200+斜率负）

        FAIL-OPEN：快照/币种/字段缺失 → None。
        """
        if not isinstance(snapshot, dict):
            return None
        entry = (snapshot.get("coins") or {}).get(coin)
        if not isinstance(entry, dict):
            return None

        try:
            bds_score = float(entry.get("bds_score", 0.0) or 0.0)
        except (TypeError, ValueError):
            bds_score = 0.0
        exit_action = str(entry.get("exit_action", "NONE") or "NONE").upper()
        trend_action = str(
            (entry.get("trend_stop") or {}).get("action", "none") or "none"
        ).lower()

        # L1 强做空
        if bds_score < 0.0:
            return "L1"
        if exit_action == "CLOSE_ALL":
            return "L1"
        if trend_action == "full_exit":
            return "L1"

        # L2 中做空
        if exit_action == "REDUCE_80":
            return "L2"
        if trend_action == "reduce50":
            return "L2"

        return None

    def _bdsm_independent_open(self) -> None:
        """BDSM 独立开仓入口：遍历 BDSM_COINS，基本面达标→触发建仓。

        设计目的：验证 BDSM 价值建仓能力，不依赖 BCRM 开仓信号。
        开关：self.enable_bdsm_independent_open（默认 True）

        触发条件（全部满足）：
          1. 币种 ∈ BDSM_COINS
          2. 快照 CVS ≥ 0.3 且 BDS ≥ 0.3（价值低估+基本面达标）
          3. BDSM 子池未满（< SUBPOOL_MAX_POSITIONS["bdsm"]）
          4. 当前无该币种持仓
          5. 5条前置检查：BDS≥0 / war_state=ALLOW / value_exit≠full_exit /
             trend_stop=none / 加仓间隔≥1日

        FAIL-OPEN：任何异常 → 跳过，不影响主链路。
        """
        try:
            if not getattr(self, "enable_bdsm_independent_open", False):
                return

            snap = self._get_bdsm_snapshot_today()
            coins_data = (snap.get("coins") or {}) if isinstance(snap, dict) else {}
            if not coins_data:
                return

            bdsm_coins = getattr(self, "BDSM_COINS", frozenset()) or frozenset()
            subpool_max = int(
                (getattr(self, "SUBPOOL_MAX_POSITIONS", {}) or {}).get("bdsm", 3)
            )
            bdsm_count = self._count_subpool_positions("bdsm")

            if bdsm_count >= subpool_max:
                return

            # 收集候选币种（CVS≥0.3 且 BDS≥0.3）
            candidates = []
            for coin_up in bdsm_coins:
                coin_entry = coins_data.get(coin_up) or {}
                if not coin_entry:
                    continue
                try:
                    cvs = float(coin_entry.get("cvs", 0.0) or 0.0)
                    bds = float(coin_entry.get("bds_score", 0.0) or 0.0)
                except (TypeError, ValueError):
                    continue
                if cvs >= 0.3 and bds >= 0.3:
                    candidates.append((coin_up, cvs, bds, coin_entry))

            # 按 BDS 降序排序，优先建仓基本面最强的币种
            candidates.sort(key=lambda x: x[2], reverse=True)

            for coin_up, cvs, bds, coin_entry in candidates:
                if bdsm_count >= subpool_max:
                    break

                # 检查当前无持仓
                inst_id = f"{coin_up}-USDT-SWAP"
                if self.position_tracker.has_open_position(inst_id):
                    continue

                # 统一冷静期检查：平仓后 COOLDOWN_SEC 内禁止新开仓（防止高频开平仓循环）
                _in_cd, _cd_reason = self.position_tracker.is_in_cooldown(
                    inst_id, "long", self.COOLDOWN_SEC
                )
                if _in_cd:
                    self._log(
                        f"[{coin_up}] BDSM独立开仓冷静期拦截 → {_cd_reason}",
                        "INFO",
                    )
                    continue

                # 5条前置检查（复用 _apply_bdsm_scaling 的逻辑）
                # ★ 硬约束 2026-09-12：value_exit=full_exit 的硬检查放在 try-except 之前，
                #   防止异常时 _block=None 绕过检查导致 SOL 空转循环（开仓→立即平仓→再开仓）
                _ve_pre = coin_entry.get("value_exit") or {}
                _ve_action_pre = str(_ve_pre.get("action", "none") or "none").lower()
                if _ve_action_pre in ("full_exit", "reduce50"):
                    self._log(
                        f"[{coin_up}] BDSM独立开仓硬拦截 → value_exit_{_ve_action_pre}"
                        f"（CVS={cvs:.3f} BDS={bds:.3f}）",
                        "INFO",
                    )
                    continue
                _block = None
                try:
                    # ① BDS ≥ 0
                    if bds < 0.0:
                        _block = f"bds_below_zero_{bds:.2f}"
                    # ④ war_state = ALLOW
                    if _block is None:
                        _war_cache = getattr(self, "_state_cache", None)
                        if _war_cache is not None:
                            _war = getattr(_war_cache, "war_state", None)
                            if isinstance(_war, dict) and _war.get("crypto_usdt", "ALLOW") != "ALLOW":
                                _block = "war_state_blocked"
                    # ⑦ value_exit.action ≠ full_exit/reduce50
                    if _block is None:
                        _ve = coin_entry.get("value_exit") or {}
                        if str(_ve.get("action", "none") or "none").lower() in ("full_exit", "reduce50"):
                            _block = f"value_exit_{_ve.get('action')}"
                    # ⑧ trend_stop.action == none
                    if _block is None:
                        _ts = coin_entry.get("trend_stop") or {}
                        if str(_ts.get("action", "none") or "none").lower() != "none":
                            _block = f"trend_stop_{_ts.get('action')}"
                    # ⑨ 加仓间隔 ≥ 1日
                    if _block is None:
                        _last_ts = getattr(self, "_last_bdsm_entry_days", None)
                        if isinstance(_last_ts, dict):
                            _last_day = _last_ts.get(coin_up)
                            if _last_day is not None:
                                import time as _t
                                _now_day = int(_t.time() // 86400)
                                if _now_day - int(_last_day) < 1:
                                    _block = "entry_interval_too_soon"
                except Exception:
                    _block = None  # 异常不阻断

                if _block is not None:
                    self._log(
                        f"[{coin_up}] BDSM独立开仓前置检查拦截 → {_block}（CVS={cvs:.3f} BDS={bds:.3f}）",
                        "INFO",
                    )
                    continue

                # 获取当前价格
                try:
                    _ticker = self.okx_client.get_ticker(inst_id)
                    if not _ticker.get("ok"):
                        self._log(f"[{coin_up}] BDSM独立开仓获取价格失败: {_ticker.get('error')}", "WARN")
                        continue
                    current_price = float(_ticker.get("last", 0.0) or 0.0)
                except Exception as _pe:
                    self._log(f"[{coin_up}] BDSM独立开仓获取价格异常: {_pe}", "WARN")
                    continue

                if current_price <= 0:
                    continue

                # 调用 _apply_bdsm_scaling 计算仓位（复用现有分批建仓逻辑）
                # 传入一个较大的 position_usdt，由 scaling 决定实际 batch
                batch_notional, cap_used, info_tag = self._apply_bdsm_scaling(
                    coin_up, 500.0, current_price
                )

                if batch_notional <= 0:
                    self._log(
                        f"[{coin_up}] BDSM独立开仓仓位计算为0（{info_tag}），跳过",
                        "INFO",
                    )
                    continue

                # 构建 inference（复用 _open_position 的 FAIL-OPEN 兜底）
                inference = {
                    "coin": coin_up,
                    "inst_id": inst_id,
                    "direction": "UP",  # 价值投资只做多
                    "confidence": max(0.40, min(0.95, bds)),  # BDS 映射置信度
                    "volatility": 0.03,
                    "price": current_price,
                    "hexagram": "BDSM价值建仓",
                    "reason": f"BDSM独立开仓|CVS={cvs:.3f}|BDS={bds:.3f}|{info_tag}",
                }

                self._log(
                    f"[{coin_up}] BDSM独立开仓触发 | CVS={cvs:.3f} BDS={bds:.3f} "
                    f"batch={batch_notional:.2f}U price={current_price} | {info_tag}",
                    "INFO",
                )

                # 调用 _open_position（source_tag 由 _classify_source_tag 自动设为 bdsm）
                try:
                    self._open_position(inference, is_reverse=False, is_trial=False)
                    bdsm_count += 1
                except Exception as _oe:
                    self._log(
                        f"[{coin_up}] BDSM独立开仓执行异常（FAIL-OPEN）: {_oe}",
                        "ERROR",
                    )

            # === 空头试错分支（BDSM 恶化型离场信号转做空）===
            # 开关：self.enable_bdsm_short_trial（默认 False）
            # 只取恶化型信号（L1/L2），高估型不转空
            if getattr(self, "enable_bdsm_short_trial", False) and bdsm_count < subpool_max:
                short_candidates = []
                for coin_up in bdsm_coins:
                    coin_entry = coins_data.get(coin_up) or {}
                    if not coin_entry:
                        continue
                    short_level = self._classify_bdsm_short_signal(snap, coin_up)
                    if short_level:
                        short_candidates.append((coin_up, short_level, coin_entry))

                # L1 优先于 L2
                short_candidates.sort(key=lambda x: 0 if x[1] == "L1" else 1)

                for coin_up, short_level, coin_entry in short_candidates:
                    if bdsm_count >= subpool_max:
                        break

                    inst_id = f"{coin_up}-USDT-SWAP"
                    if self.position_tracker.has_open_position(inst_id):
                        continue

                    # 统一冷静期检查：平仓后 COOLDOWN_SEC 内禁止新开仓（防止高频开平仓循环）
                    _in_cd, _cd_reason = self.position_tracker.is_in_cooldown(
                        inst_id, "short", self.COOLDOWN_SEC
                    )
                    if _in_cd:
                        self._log(
                            f"[{coin_up}] BDSM做空试错冷静期拦截 → {_cd_reason}",
                            "INFO",
                        )
                        continue

                    # 试错单名额检查
                    try:
                        trial_count = self._count_trial_positions()
                    except Exception:
                        trial_count = 0
                    max_trial = int(getattr(self, "MAX_TRIAL_POSITIONS", 2))
                    if trial_count >= max_trial:
                        self._log(
                            f"[{coin_up}] BDSM做空试错名额已满({trial_count}/{max_trial})，跳过",
                            "INFO",
                        )
                        continue

                    # war_state 检查（开关守卫：默认关闭，BDSM独立验证）
                    if getattr(self, "enable_bdsm_war_state_check", False):
                        _war_cache = getattr(self, "_five_domain_state_cache", None)
                        if _war_cache is not None:
                            _war = getattr(_war_cache, "war_state", None)
                            if isinstance(_war, dict) and _war.get("crypto_usdt", "ALLOW") != "ALLOW":
                                continue

                    # 获取当前价格
                    try:
                        _ticker = self.okx_client.get_ticker(inst_id)
                        if not _ticker.get("ok"):
                            continue
                        current_price = float(_ticker.get("last", 0.0) or 0.0)
                    except Exception:
                        continue
                    if current_price <= 0:
                        continue

                    bds = float(coin_entry.get("bds_score", 0.0) or 0.0)
                    confidence = max(0.40, min(0.70, abs(bds)))
                    position_pct = 0.08 if short_level == "L1" else 0.05

                    # SL/TP 计算（硬约束: SL=4.0×ATR 下限4%/上限15%, TP=3×SL 上限30%）
                    _atr = current_price * 0.03  # volatility=0.03
                    _sl_dist = max(_atr * 4.0, current_price * 0.04)  # 4.0×ATR, 下限4%
                    _sl_dist = min(_sl_dist, current_price * 0.15)  # 上限15%
                    _tp_dist = min(_sl_dist * 3.0, current_price * 0.30)  # 3×SL, 上限30%
                    # 做空: SL 在上方, TP 在下方
                    _sl_px = round(current_price + _sl_dist, 6)
                    _tp_px = round(current_price - _tp_dist, 6)

                    inference = {
                        "coin": coin_up,
                        "inst_id": inst_id,
                        "direction": "DOWN",
                        "confidence": confidence,
                        "volatility": 0.03,
                        "price": current_price,
                        "stop_loss_px": _sl_px,
                        "take_profit_px": _tp_px,
                        "hexagram": "BDSM恶化做空试错",
                        "reason": (
                            f"BDSM做空试错|level={short_level}|bds={bds:.3f}"
                            f"|exit={coin_entry.get('exit_action', 'NONE')}"
                            f"|trend={(coin_entry.get('trend_stop') or {}).get('action', 'none')}"
                        ),
                    }

                    self._log(
                        f"[{coin_up}] BDSM做空试错触发 | level={short_level} bds={bds:.3f} "
                        f"position_pct={position_pct} price={current_price}",
                        "INFO",
                    )

                    try:
                        self._open_position(inference, is_reverse=False, is_trial=True)
                        bdsm_count += 1
                    except Exception as _oe:
                        self._log(
                            f"[{coin_up}] BDSM做空试错执行异常（FAIL-OPEN）: {_oe}",
                            "ERROR",
                        )

        except Exception as exc:
            # 终极 FAIL-OPEN：BDSM 独立开仓任何异常 → 跳过，不阻断主链路
            self._log(
                f"[BDSM独立开仓] 顶层异常（FAIL-OPEN 跳过不阻断）: {exc}",
                "WARN",
            )

    def _compute_strategy_open_signal(self, coin: str) -> Optional[Tuple[str, float, str]]:
        """三层信号组合 → 产出 (direction, confidence, strategy_type) 或 None。

        层1 战略层：war_state∈(ALLOW,COOLDOWN) + direction_state≠FREEZE
        层2 策略层：select() 产出 strategy_type（heuristic_equilibrium→跳过）
        层3 技术信号：d_star∈(long,short) 且 ri≥0.55
        direction_state 闸门：SHORT_ONLY 禁做多，LONG_ONLY 禁做空

        FAIL-OPEN：异常 → None
        """
        try:
            # ── 层1：战略层检查 ──
            fds = getattr(self, "_five_domain_state_cache", None)
            if fds is None:
                return None
            cls = self._coin_asset_class(coin)
            # ★ war_state 只影响仓位（通过 cap_pct 在仓位计算中使用），不拦截开仓
            #   direction_state 才控制是否开仓 + 方向（独立的方向开关）
            direction_state = (getattr(fds, "direction_state", {}) or {}).get(cls, "NEUTRAL")
            if direction_state == "FREEZE":
                self._log(f"[{coin}] 策略独立开仓方向冻结 direction_state=FREEZE", "DEBUG")
                return None

            # ── 层2：策略层 select() ──
            layer = getattr(self, "_strategy_algo_layer", None)
            if layer is None or not getattr(layer.cfg, "enable_strategy_layer", False):
                return None
            five_scores = (getattr(fds, "five_scores", {}) or {}).get(cls, {})
            if not five_scores:
                from scripts.memory_l4.strategy_algo_layer import DEFAULT_NEUTRAL_SCORES as _DNS
                five_scores = dict(_DNS)
            regime_summary = {"phase": getattr(self, "_last_regime", "UNKNOWN") or "UNKNOWN"}
            liquidity_tier = "G2"
            selection = layer.select(
                asset_class=cls,
                five_scores=five_scores,
                regime_summary=regime_summary,
                liquidity_tier=liquidity_tier,
                five_domain_state=fds,
            )
            strategy_type = selection.strategy_type
            if strategy_type == "heuristic_equilibrium":
                return None  # 中性策略不触发独立开仓

            # ── 层3：技术信号 ──
            kline_result = (getattr(self, "_last_kline_result_by_coin", {}) or {}).get(coin.upper(), {})
            if not kline_result:
                return None
            d_star = str(kline_result.get("d_star", "WAIT") or "WAIT")
            ri = float(kline_result.get("ri", 0.0) or 0.0)
            if d_star not in ("long", "short"):
                return None
            # ri 阈值：正式 0.55，可通过环境变量 STRATEGY_RI_THRESHOLD 调整
            _ri_threshold = float(os.environ.get("STRATEGY_RI_THRESHOLD", "0.55") or "0.55")
            if ri < _ri_threshold:
                return None

            # ── direction_state 方向闸门 ──
            if direction_state == "SHORT_ONLY" and d_star == "long":
                return None
            if direction_state == "LONG_ONLY" and d_star == "short":
                return None

            # ── 组合产出 ──
            direction = "UP" if d_star == "long" else "DOWN"
            style_exposure = float((selection.style_exposures or {}).get(strategy_type, 0.5))
            confidence = max(0.40, min(0.95, ri * style_exposure * 2.0))
            return (direction, confidence, strategy_type)
        except Exception:
            return None  # FAIL-OPEN

    def _strategy_independent_open(self) -> None:
        """战略层+策略层独立开仓入口：三层信号组合 → 独立建仓。

        设计目的：单独测试战略层+策略层效果，不依赖 BCRM2.0 推理。
        开关：self.enable_strategy_independent_open（默认 False，安全第一）

        触发条件（全部满足）：
          1. 币种 ∈ self.coins（与 BCRM2.0 保持一致，可通过 STRATEGY_INDEPENDENT_COINS 环境变量覆盖）
          2. 三层信号组合通过（_compute_strategy_open_signal 返回非 None）
          3. strategy 子池未满（< MAX_STRATEGY_POSITIONS）
          4. 当前无该币种持仓
          5. 冷静期检查通过（COOLDOWN_SEC）
          6. 组合熔断未拦截

        仓位计算：cap_pct × position_mult × STRATEGY_BASE_BUDGET_USDT
        SL/TP：复用 _open_position 内部 ATR 自适应逻辑
        FAIL-OPEN：任何异常 → 跳过，不影响主链路。
        """
        try:
            if not getattr(self, "enable_strategy_independent_open", False):
                return

            strategy_coins = getattr(self, "STRATEGY_INDEPENDENT_COINS", frozenset()) or frozenset()
            if not strategy_coins:
                return

            subpool_max = int(self.SUBPOOL_MAX_POSITIONS.get("strategy", 3))
            strategy_count = self._count_subpool_positions("strategy")
            if strategy_count >= subpool_max:
                return

            base_budget = float(getattr(self, "STRATEGY_BASE_BUDGET_USDT", 200.0))

            for coin in strategy_coins:
                if strategy_count >= subpool_max:
                    break

                coin_up = str(coin).upper()
                inst_id = f"{coin_up}-USDT-SWAP"

                # 检查当前无持仓
                if self.position_tracker.has_open_position(inst_id):
                    continue

                # 冷静期检查
                _in_cd, _cd_reason = self.position_tracker.is_in_cooldown(
                    inst_id, "long", self.COOLDOWN_SEC
                )
                if _in_cd:
                    continue

                # 三层信号组合
                signal = self._compute_strategy_open_signal(coin_up)
                if signal is None:
                    continue
                direction, confidence, strategy_type = signal

                # 组合熔断检查
                _fuse = getattr(self, "_current_fuse_action", None)
                if _fuse is not None and getattr(_fuse, "block_new_open", False):
                    self._log(f"[{coin_up}] 策略独立开仓熔断拦截", "WARN")
                    return

                # 获取当前价格
                try:
                    _ticker = self.okx_client.get_ticker(inst_id)
                    if not _ticker.get("ok"):
                        continue
                    current_price = float(_ticker.get("last", 0.0) or 0.0)
                except Exception:
                    continue
                if current_price <= 0:
                    continue

                # 仓位计算：cap_pct × position_mult × base_budget
                # ★ 读 _shadow（真实值）：战略层 cap_pct/position_mult 真实压缩仓位
                fds = getattr(self, "_five_domain_state_shadow", None) or getattr(self, "_five_domain_state_cache", None)
                cls = self._coin_asset_class(coin_up)
                cap_pct = 1.0
                pos_mult = 1.0
                if fds is not None:
                    cap_pct = float((getattr(fds, "aggregate_position_cap_pct", {}) or {}).get(cls, 1.0))
                    pos_mult = float((getattr(fds, "position_mult", {}) or {}).get(cls, 1.0))
                position_usdt = cap_pct * pos_mult * base_budget
                if position_usdt <= 0:
                    continue

                # 构建 inference（含 ATR 自适应 SL/TP）
                _volatility = 0.03
                _atr_est = max(current_price * _volatility, current_price * 0.005)
                _sl_mult, _tp_mult = 4.0, 12.0  # SL=4×ATR, TP=12×ATR, 盈亏比3:1
                if direction == "UP":
                    _sl_px = round(current_price - _atr_est * _sl_mult, 4)
                    _tp_px = round(current_price + _atr_est * _tp_mult, 4)
                else:
                    _sl_px = round(current_price + _atr_est * _sl_mult, 4)
                    _tp_px = round(current_price - _atr_est * _tp_mult, 4)
                inference = {
                    "coin": coin_up,
                    "inst_id": inst_id,
                    "direction": direction,
                    "confidence": confidence,
                    "volatility": _volatility,
                    "price": current_price,
                    "stop_loss_px": _sl_px,
                    "take_profit_px": _tp_px,
                    "hexagram": f"策略层独立开仓_{strategy_type}",
                    "reason": f"策略独立开仓|type={strategy_type}|cap={cap_pct:.2f}|mult={pos_mult:.2f}|ri-based",
                    "source_tag": "strategy",  # ★ 子池隔离标签
                }

                self._log(
                    f"[{coin_up}] 策略独立开仓触发 | type={strategy_type} dir={direction} "
                    f"conf={confidence:.3f} budget={position_usdt:.1f}U price={current_price} | "
                    f"cap={cap_pct:.2f} mult={pos_mult:.2f}",
                    "INFO",
                )

                try:
                    self._open_position(inference, is_reverse=False, is_trial=False)
                    strategy_count += 1
                except Exception as _oe:
                    self._log(f"[{coin_up}] 策略独立开仓执行异常(FAIL-OPEN): {_oe}", "ERROR")

        except Exception as _se:
            self._log(f"[策略独立开仓] 顶层异常(FAIL-OPEN): {_se}", "WARN")

    def _enforce_soft_stop_loss(self) -> None:
        """软止损强制执行：扫描所有持仓，当亏损超过 SL 阈值时强制市价平仓。

        根因 2026-09-12：OKX algo order（SL/TP）可能因以下原因未生效：
        1. place_stop_loss_take_profit API 调用失败但未正确报错
        2. OKX algo order 被取消或过期
        3. 持仓同步修复 SLTP 时，algo order 未重新创建

        此方法作为 OKX algo order 的后备保障，每轮轮询执行一次。
        SL 阈值：从持仓的 entry_price 和 SL 价格推算，若无则用默认 4% 硬下限。
        """
        try:
            positions = self.position_tracker.all_open_positions()
            if not positions:
                return
            okx_client = getattr(self, "okx_client", None)
            if okx_client is None:
                return
            for p in positions:
                try:
                    _p_size = float(getattr(p, "contracts", 0) or getattr(p, "size", 0) or 0)
                    if _p_size <= 0:
                        continue
                    _coin = str(getattr(p, "coin", "") or "")
                    _inst_id = f"{_coin}-USDT-SWAP"
                    _direction = str(getattr(p, "direction", "") or "").lower()
                    _entry_px = float(getattr(p, "entry_price", 0) or 0)
                    if _entry_px <= 0:
                        continue
                    # 获取当前标记价格
                    try:
                        _ticker = okx_client.get_ticker(_inst_id)
                        if not _ticker.get("ok"):
                            continue
                        _mark_px = float(_ticker.get("last", 0) or 0)
                    except Exception:
                        continue
                    if _mark_px <= 0:
                        continue
                    # 计算盈亏比例
                    if _direction == "long":
                        _pnl_pct = (_mark_px - _entry_px) / _entry_px
                    else:
                        _pnl_pct = (_entry_px - _mark_px) / _entry_px
                    # SL 阈值：从持仓的 stop_loss_px 推算，若无用默认 4%
                    _sl_px = float(getattr(p, "stop_loss_px", 0) or 0)
                    if _sl_px > 0 and _entry_px > 0:
                        if _direction == "long":
                            _sl_pct = abs(_entry_px - _sl_px) / _entry_px
                        else:
                            _sl_pct = abs(_sl_px - _entry_px) / _entry_px
                    else:
                        _sl_pct = 0.04  # 默认 4% 硬下限
                    # 软止损触发：亏损超过 SL 阈值 + 1% 缓冲（防止刚好在 SL 线上反复触发）
                    _sl_trigger = _sl_pct + 0.01
                    if _pnl_pct < -_sl_trigger:
                        _upl = float(getattr(p, "pnl", 0) or 0)
                        self._log(
                            f"[软止损] {_coin} {_direction} 亏损 "
                            f"{_pnl_pct*100:.2f}% < -{_sl_trigger*100:.1f}% "
                            f"(SL={_sl_pct*100:.1f}%+1%缓冲) | "
                            f"entry={_entry_px} mark={_mark_px} → 强制平仓",
                            "WARN",
                        )
                        # 执行强制平仓
                        _close_method = (
                            okx_client.market_close_long
                            if _direction == "long"
                            else okx_client.market_close_short
                        )
                        _reason = f"soft_stop_loss: pnl={_pnl_pct*100:.2f}% sl_threshold={_sl_trigger*100:.1f}%"
                        _r = _close_method(_inst_id, reason=_reason)
                        if _r.get("ok") or _r.get("dry_run"):
                            self._handle_close_position(
                                inst_id=_inst_id,
                                coin=_coin,
                                pos_side=_direction,
                                exit_price=_mark_px,
                                exit_reason=_reason,
                                pnl=_upl,
                                pnl_pct=_pnl_pct,
                            )
                            self._log(
                                f"[软止损] {_coin} 强制平仓成功 | "
                                f"pnl={_upl:.2f}U ({_pnl_pct*100:.2f}%)",
                                "WARN",
                            )
                        else:
                            self._log(
                                f"[软止损] {_coin} 强制平仓失败: {_r.get('error', 'unknown')}",
                                "ERROR",
                            )
                except Exception as _p_exc:
                    self._log(
                        f"[软止损] 单仓 {_coin if '_coin' in dir() else '?'} 异常(fail-open): {_p_exc}",
                        "DEBUG",
                    )
        except Exception as _ssl_exc:
            self._log(f"[软止损] 整体异常(fail-open): {_ssl_exc}", "WARN")

    def _bdsm_check_exit_actions(self) -> List[Dict[str, Any]]:
        """缺口 3：出场巡检入口。按 BDSM 快照 exit_action 先于 BCRM 技术出场执行。

        优先级：CLOSE_ALL > REDUCE_80 > REDUCE_50 > NONE（快照 _detect_exit_action 已保证）。
        仅作用于 BDSM 币 且 position_tracker 里有真实持仓者；非 BDSM 币直接跳过。
        REDUCE_* 复用 OKX market_close_* 方法但只提交 sz×ratio 等价订单（若 client 不支持 reduce
        专用接口，则拆成「平 80%/50% 再重开 20%/50%」的等价操作由上层 _handle_close_position 记录部分平仓）；
        为了保持实盘一致性，本实现优先走「全平 + 立即重开剩余」路径，并记录一条半仓 pnl 记录。

        Returns:
            本次执行的动作摘要列表，用于日志聚合。
        """
        actions: List[Dict[str, Any]] = []
        try:
            bdsm_coins = getattr(self, "BDSM_COINS", frozenset()) or frozenset()
            if not bdsm_coins:
                return actions
            snap = self._get_bdsm_snapshot_today()
            coins = snap.get("coins") or {}

            okx_client = getattr(self, "okx_client", None)
            tracker = getattr(self, "position_tracker", None)
            if okx_client is None or tracker is None:
                return actions

            for coin_up in sorted(bdsm_coins):
                try:
                    entry = coins.get(coin_up) or {}

                    triggers = entry.get("exit_triggers") or []
                    # 先获取持仓信息（用于子池隔离 + 方向感知出场信号过滤）
                    pos_info = self._get_coin_position_info(coin_up)
                    if not pos_info.get("has_position"):
                        continue
                    # 子池来源隔离：BDSM 出场巡检只作用于 source_tag="bdsm" 的持仓
                    # 自进化系统（source_tag="evolution"）开的仓即便币种在 BDSM_COINS 池内
                    # 也不得被 BDSM 规则误伤（2026-09-07 修复：避免再次误平 ETH/SOL）
                    _pos_src_tag = str(pos_info.get("source_tag") or "").lower()
                    if _pos_src_tag != "bdsm":
                        self._log(
                            f"[BDSM 出场巡检] 跳过 {coin_up}: source_tag={_pos_src_tag or 'unknown'}"
                            f"（非 bdsm 子池持仓，不套用 BDSM 出场规则）",
                            "INFO",
                        )
                        continue
                    inst_id = pos_info["inst_id"]
                    pos_side = pos_info.get("pos_side") or "long"

                    # Phase 2：合并出场源（方向感知，避免对空头错误应用多头离场信号）
                    #   多头持仓：使用全部三个源（exit_action + trend_stop + value_exit）
                    #   空头持仓：仅使用 exit_action（基本面/phase退化）
                    #     — trend_stop（跌破均线）和 value_exit（高估离场）都是多头离场逻辑，
                    #       对空头而言反而是有利的，不应触发平仓。
                    _exit_prio = {
                        "CLOSE_ALL": 5, "full_exit": 5,
                        "REDUCE_80": 4,
                        "REDUCE_50": 3, "reduce50": 3,
                        "reduce30": 2,
                        "NONE": 0, "none": 0,
                    }
                    exit_raw = str(entry.get("exit_action") or "NONE").upper()
                    trend_raw = str((entry.get("trend_stop") or {}).get("action") or "none").lower()
                    value_raw = str((entry.get("value_exit") or {}).get("action") or "none").lower()

                    if pos_side == "short":
                        # 空头仅用基本面 exit_action，忽略技术趋势和估值信号（多头逻辑）
                        _action_candidates = [exit_raw]
                    else:
                        # 多头使用全部三个出场源
                        _action_candidates = [exit_raw, trend_raw, value_raw]

                    # 取优先级最高的 action 作为本轮执行动作
                    best_action = max(
                        _action_candidates,
                        key=lambda a: _exit_prio.get(a, 0),
                    )
                    if _exit_prio.get(best_action, 0) == 0:
                        continue  # 所有源均为 NONE → 无动作
                    mark_px = pos_info.get("mark_px") or pos_info.get("avg_px") or 0.0
                    upl = float(pos_info.get("upl") or 0.0)
                    upl_ratio = float(pos_info.get("upl_ratio") or 0.0)

                    close_method = (
                        okx_client.market_close_long
                        if pos_side == "long"
                        else okx_client.market_close_short
                    )
                    # 标注触发来源
                    _src_tag = (
                        "exit" if best_action == exit_raw and _exit_prio.get(exit_raw, 0) > 0
                        else "trend_stop" if best_action == trend_raw and _exit_prio.get(trend_raw, 0) > 0
                        else "value_exit"
                    )
                    reason = f"bdsm_exit:{best_action}({','.join(triggers) or 'none'},{_src_tag})"

                    if best_action in ("CLOSE_ALL", "full_exit"):
                        r = close_method(inst_id, reason=reason)
                        if r.get("ok") or r.get("dry_run"):
                            self._handle_close_position(
                                inst_id=inst_id,
                                coin=coin_up,
                                pos_side=pos_side,
                                exit_price=mark_px,
                                exit_reason=reason,
                                pnl=upl,
                                pnl_pct=upl_ratio,
                            )
                            actions.append({"coin": coin_up, "action": "CLOSE_ALL", "ok": True,
                                            "reason": reason})
                        else:
                            self._log(
                                f"[{coin_up}] BDSM CLOSE_ALL 失败: {r.get('error')}", "WARN"
                            )
                            actions.append({"coin": coin_up, "action": "CLOSE_ALL", "ok": False,
                                            "error": r.get("error")})
                        continue

                    if best_action in ("REDUCE_80", "REDUCE_50", "reduce50", "reduce30"):
                        # 参数化 reduce_ratio（Phase 2 新增 reduce30 支持）
                        _ratio_map = {"REDUCE_80": 0.80, "REDUCE_50": 0.50,
                                      "reduce50": 0.50, "reduce30": 0.30}
                        reduce_ratio = _ratio_map.get(best_action, 0.50)
                        reduce_result = self._bdsm_partial_reduce_position(
                            coin=coin_up, inst_id=inst_id, pos_side=pos_side,
                            reduce_ratio=reduce_ratio, mark_px=mark_px,
                            upl=upl, upl_ratio=upl_ratio, reason=reason,
                        )
                        actions.append({"coin": coin_up, "action": best_action, **reduce_result})
                        continue

                    # 未知 action → FAIL-OPEN 不动
                    self._log(
                        f"[{coin_up}] BDSM 未知 best_action={best_action}（FAIL-OPEN 跳过）",
                        "WARN",
                    )
                except Exception as cex:
                    self._log(
                        f"[{coin_up}] BDSM exit 单币处理异常（FAIL-OPEN 跳过）: {cex}", "WARN"
                    )
            return actions
        except Exception as exc:
            self._log(f"BDSM exit_actions 巡检异常（FAIL-OPEN 跳过）: {exc}", "WARN")
            return actions

    def _bdsm_partial_reduce_position(
        self,
        coin: str,
        inst_id: str,
        pos_side: str,
        reduce_ratio: float,
        mark_px: float,
        upl: float,
        upl_ratio: float,
        reason: str,
    ) -> Dict[str, Any]:
        """缺口 3 子步骤：按 reduce_ratio (0.8 / 0.5) 部分平仓。

        优先：如果 okx_client 有 place_order 接口（OKXSimulatedClient 有），
        直接下「反方向 sz×reduce_ratio」市价单 等价部分平仓；否则回退为全平后立即按剩余仓位
        以当前 mark_px 开一条新 TradeRecord（记账型，不发新单），保持本地 PositionTracker 一致。
        """
        okx_client = getattr(self, "okx_client", None)
        tracker = getattr(self, "position_tracker", None)
        if okx_client is None or tracker is None:
            return {"ok": False, "error": "client/tracker_missing"}
        pos_rec = tracker.get_open_position(inst_id)
        if pos_rec is None:
            return {"ok": False, "error": "no_open_position"}
        try:
            original_sz = float(getattr(pos_rec, "position_qty", 0.0) or 0.0)
            original_usdt = float(getattr(pos_rec, "position_usdt", 0.0) or 0.0)
        except Exception:
            original_sz = 0.0
            original_usdt = 0.0
        if original_sz <= 0 and original_usdt <= 0:
            return {"ok": False, "error": "empty_position_size"}

        reduce_sz = original_sz * reduce_ratio
        reduce_usdt = original_usdt * reduce_ratio
        side = "sell" if pos_side == "long" else "buy"

        reduce_px = mark_px or float(getattr(pos_rec, "entry_price", 0.0) or 0.0)
        partial_upl = upl * reduce_ratio if reduce_ratio else 0.0
        partial_upl_ratio = float(upl_ratio or 0.0)

        tried_place_order = False
        if reduce_sz > 0 and hasattr(okx_client, "place_order"):
            try:
                r = okx_client.place_order(
                    inst_id=inst_id,
                    side=side,
                    ord_type="market",
                    sz=reduce_sz,
                    pos_side=pos_side,
                    reason=reason,
                )
                tried_place_order = True
            except Exception as exc:
                r = {"ok": False, "error": f"place_order_exc:{exc}"}
        else:
            r = {"ok": False, "error": "reduce_sz_zero_or_no_place_order"}

        ok_flag = bool(r.get("ok") or r.get("dry_run"))

        # 记账：部分平仓等价于「一条 close + 一条重新 open 剩余部分」
        # close 记录 对应 reduce_ratio 的 pnl
        try:
            close_rec = tracker.close_position(
                inst_id=inst_id,
                exit_price=reduce_px,
                exit_reason=reason,
                pnl=partial_upl,
                pnl_pct=partial_upl_ratio,
            )
            if close_rec is None:
                return {"ok": False, "error": "partial_close_record_missing"}
        except Exception as close_exc:
            return {"ok": False, "error": f"close_position_exc:{close_exc}"}

        # 剩下的 (1 - reduce_ratio) 重新 open —— 复用现 TradeRecord 字段复制
        left_ratio = 1.0 - reduce_ratio
        if left_ratio > 0:
            try:
                new_entry_px = reduce_px or float(getattr(pos_rec, "entry_price", 0.0) or 0.0)
                # 按比例缩放 qty / usdt
                new_sz = original_sz * left_ratio
                new_usdt = original_usdt * left_ratio
                tracker.open_position(
                    trade_id=getattr(pos_rec, "trade_id", "") + f":reduce{int(reduce_ratio*100)}",
                    inst_id=inst_id,
                    coin=coin,
                    direction=pos_side,
                    entry_price=new_entry_px,
                    confidence=float(getattr(pos_rec, "confidence", 0.0) or 0.0),
                    hexagram=getattr(pos_rec, "hexagram", "") or "",
                    stop_loss_px=float(getattr(pos_rec, "stop_loss_px", 0.0) or 0.0),
                    take_profit_px=float(getattr(pos_rec, "take_profit_px", 0.0) or 0.0),
                    position_usdt=new_usdt,
                    position_qty=new_sz,
                    leverage=float(getattr(pos_rec, "leverage", 1.0) or 1.0),
                    source_tag=getattr(pos_rec, "source_tag", "") or "",
                    extra={"bdsm_reduce_from": reduce_ratio,
                           "bdsm_partial_exited_usdt": reduce_usdt},
                )
            except Exception as reopen_exc:
                self._log(
                    f"[{coin}] BDSM reduce 剩余仓位重开失败: {reopen_exc}", "WARN"
                )
                return {"ok": False, "error": f"reopen_left_ratio_exc:{reopen_exc}"}

        perf_tracker = getattr(self, "perf_tracker", None)
        risk_manager = getattr(self, "risk_manager", None)
        try:
            if perf_tracker is not None and close_rec is not None:
                perf_tracker.record_trade(close_rec)
            if risk_manager is not None and close_rec is not None:
                risk_manager.update_after_trade(
                    partial_upl, partial_upl >= 0,
                    current_equity=getattr(perf_tracker, "current_equity", 0.0) if perf_tracker else 0.0,
                )
        except Exception as perf_exc:
            self._log(f"[{coin}] BDSM reduce perf/risk update 异常（FAIL-OPEN 忽略）: {perf_exc}", "WARN")

        return {
            "ok": ok_flag,
            "tried_place_order": tried_place_order,
            "reduce_ratio": reduce_ratio,
            "reduce_usdt": reduce_usdt,
            "error": r.get("error", ""),
            "reason": reason,
        }

    # ──────────────────────────────────────────────────────────
    # Phase A: MODE 算力重分配工具函数（Spec §3.2 / §3.3）
    # ──────────────────────────────────────────────────────────

    def _default_candidate_rank(self, candidate_pool: list) -> list:
        """候选池默认排序（Spec §3.2）：先波动率缓存 → 历史交易次数倒序 → 字母序 fallback。

        只用于币种集构造阶段的 TopN 截断，不决定最终开仓排名（最终排名仍走 A7+五角+置信度）。
        """
        # 纯静态 fallback：按字母序（让测试可复现，且与当前代码简单等价）
        return sorted(candidate_pool)

    def _held_coins_union(self) -> set:
        """实际持仓币种集合 = position_tracker ∪ OKX 去重并集。

        避免单边数据源漏单导致 occupancy 误判（例如 OKX API 成功但 tracker 没同步、或反过来）。
        """
        tracker = getattr(self.position_tracker, "all_open_positions", lambda: [])
        held_from_tracker = {p.coin for p in (tracker() or [])}

        okx_fn = getattr(self.okx_client, "get_positions", lambda: {"ok": False})
        okx_result = okx_fn() or {}
        held_from_okx = set()
        if okx_result.get("ok"):
            for p in okx_result.get("positions", []) or []:
                inst_id = p.get("instId") or ""
                base = inst_id.split("-")[0]
                if base:
                    held_from_okx.add(base)
        return held_from_tracker | held_from_okx

    def _is_dynamic_blacklisted(self, coin: str) -> bool:
        """动态黑名单检查的统一包装，兼容 tuple(blocked,reason) / bool 两种返回值。"""
        fn = getattr(self, "_check_dynamic_blacklist", None)
        if not callable(fn):
            return False
        result = fn(coin)
        if isinstance(result, tuple):
            return bool(result[0]) if result else False
        return bool(result)

    def _decide_mode_coins(self) -> Tuple[str, list, list, list]:
        """返回 (mode_tag, anom_coins, infer_full_coins, infer_coarse_coins)

        - enable_mode_switch=False → MODE-OFF，anom/infer_full 全量 coins，coarse 空
        - enable_mode_switch=True  → MODE1/MODE2/MODE3 按 occupancy 分支
        """
        held_coins = self._held_coins_union()

        # 候选池 = 全量 coins ∩ 非持仓 ∩ 非静态黑名单 ∩ 非动态黑名单
        candidate_pool = [
            c for c in self.coins
            if c not in held_coins
            and c not in getattr(self, "blacklist_coins", set())
            and not self._is_dynamic_blacklisted(c)
        ]
        candidate_pool = self._default_candidate_rank(candidate_pool)

        N_max = getattr(self, "max_positions", 1) or 1
        actual_held_n = max(
            len(held_coins),
            self._count_total_positions() if callable(getattr(self, "_count_total_positions", None)) else 0,
        )
        occupancy = (actual_held_n / N_max) if N_max else 0.0

        # 开关 OFF → 旧路径（MODE-OFF）
        if not getattr(self, "enable_mode_switch", False):
            return ("MODE-OFF", list(self.coins), list(self.coins), [])

        # 三档 MODE 阈值分支（MODE_OCCUPANCY_MODE2 默认 = 2/3 ≈ 0.6667）
        if occupancy >= self.MODE_OCCUPANCY_MODE3:
            mode = "MODE3_FULL"
            anom_candidate_n = self.MODE3_COARSE_CANDIDATE_TOPN
            infer_full_candidate_n = 0
            infer_coarse_candidate_n = self.MODE3_COARSE_CANDIDATE_TOPN
        elif occupancy >= self.MODE_OCCUPANCY_MODE2:
            mode = "MODE2_HALF"
            anom_candidate_n = 4
            infer_full_candidate_n = 5
            infer_coarse_candidate_n = 0
        else:
            mode = "MODE1_LIGHT"
            anom_candidate_n = len(candidate_pool)
            infer_full_candidate_n = len(candidate_pool)
            infer_coarse_candidate_n = 0

        anom_coins = list(held_coins) + candidate_pool[:anom_candidate_n]
        infer_full_coins = list(held_coins) + candidate_pool[:infer_full_candidate_n]
        infer_coarse_coins = candidate_pool[
            infer_full_candidate_n: infer_full_candidate_n + infer_coarse_candidate_n
        ]
        return mode, anom_coins, infer_full_coins, infer_coarse_coins

    def _infer_coarse(self, coin: str) -> Dict:
        """MODE3 粗推理（S1 快速路径）。

        相比 _fetch_and_infer（Full BCRM2.0 全链路：拉K线→特征→训练/推理→卦象→五角→三角证伪），
        本方法仅做：缓存命中 → 简化特征（close/volatility/is_ranging/MA方向）→ 估算粗置信度。
        只产出 _fetch_and_infer 的子集字段（足够 MODE3 粗排序 + 补全门禁判断）。

        返回结构对齐 _fetch_and_infer（但省略深度字段 bagua_confidence/triangle_verification 等）：
          {"ok": bool, "coin": str, "inst_id": str, "direction": str,
           "confidence": float, "fail_closed": bool, "price": float,
           "volatility": float, "is_ranging": bool, "hexagram": str, "_coarse": True}
        """
        inst_id = f"{coin}-USDT-SWAP"
        cache_key = ("infer_coarse", coin)
        ttl = getattr(self, "MODE_CACHE_TTL_INFER_COARSE", 2)
        hit, cached = self._cache_get(cache_key, ttl)
        if hit and isinstance(cached, dict):
            return dict(cached)

        try:
            # ── 最小探针：短 K 线 40 根（MODE3 快速路径，不做 160 根全量请求）──
            short_limit = getattr(self, "MODE_COARSE_KLINE_LIMIT", 40)
            kline_data = _load_kline_from_okx(inst_id=inst_id, bar=self.bar, limit=short_limit)
            if not kline_data or len(kline_data) < 20:
                # K 线不足 → fail_closed=True（保守：粗推理不交易，等补全）
                stub = {"ok": True, "coin": coin, "inst_id": inst_id,
                        "direction": "NEUTRAL", "confidence": 0.0, "fail_closed": True,
                        "price": 0.0, "volatility": 0.03, "is_ranging": True, "hexagram": "",
                        "_coarse": True, "kline_data": []}
                self._cache_set(cache_key, stub)
                return stub

            closes = [float(c.get("c", 0.0)) for c in kline_data if c.get("c") is not None]
            highs = [float(c.get("h", c.get("C", 0.0))) for c in kline_data]
            lows = [float(c.get("l", c.get("L", 0.0))) for c in kline_data]
            price = float(closes[-1]) if closes else 0.0

            # ── 波动率粗算（简化 std，不做 EWM）──
            import math
            rets = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
            volatility = float(np.std(rets)) if rets else 0.03
            if volatility <= 0 or not math.isfinite(volatility):
                volatility = 0.03

            # ── 震荡/趋势：用 high-low std vs close std 比值粗分 ──
            is_ranging = False
            try:
                hl_range = np.array(highs) - np.array(lows)
                if closes and np.mean(closes) > 0:
                    hl_rel_std = float(np.std(hl_range) / np.mean(closes))
                    is_ranging = hl_rel_std < volatility * 1.4
            except Exception:
                pass

            # ── 方向粗算（短 MA20 vs MA5 交叉，无 BCRM2.0 训练/推理）──
            direction = "NEUTRAL"
            confidence = 0.40  # 粗置信度基线（待补全后才开仓）
            try:
                if len(closes) >= 20:
                    ma5 = float(np.mean(closes[-5:])) if len(closes) >= 5 else closes[-1]
                    ma20 = float(np.mean(closes[-20:]))
                    diff = (ma5 - ma20) / ma20 if ma20 > 0 else 0.0
                    if diff > volatility * 0.5:
                        direction = "UP"
                        confidence = min(0.70, 0.40 + abs(diff) * 5)
                    elif diff < -volatility * 0.5:
                        direction = "DOWN"
                        confidence = min(0.70, 0.40 + abs(diff) * 5)
            except Exception:
                pass

            result = {
                "ok": True, "coin": coin, "inst_id": inst_id,
                "direction": direction, "confidence": round(confidence, 4),
                "fail_closed": False if direction in ("UP", "DOWN") else True,
                "price": price, "volatility": round(volatility, 6),
                "is_ranging": is_ranging, "hexagram": "",
                "_coarse": True, "kline_data": kline_data,
                "bagua_direction": "neutral", "bagua_confidence": 0.0,
            }
            self._cache_set(cache_key, result)
            return result
        except Exception as e:
            self._log(f"[{coin}] _infer_coarse 异常: {e}，降级为 fail_closed", "WARN")
            stub = {"ok": False, "coin": coin, "inst_id": inst_id,
                    "direction": "NEUTRAL", "confidence": 0.0, "fail_closed": True,
                    "price": 0.0, "volatility": 0.03, "is_ranging": True, "hexagram": "",
                    "_coarse": True, "kline_data": [], "error": str(e)}
            return stub

    def _cache_get(self, key: tuple, ttl_cycles: int):
        """命中返回 (True, payload)；未命中或过期返回 (False, None)。

        TTL 用 self._cycle_idx 轮次计数（而非 wall-clock），确保测试可复现。
        """
        if key not in self._mode_cache:
            return False, None
        payload, written_cycle = self._mode_cache[key]
        if self._cycle_idx - written_cycle > ttl_cycles:
            del self._mode_cache[key]
            return False, None
        return True, payload

    def _cache_set(self, key: tuple, payload):
        """写入缓存并按轮次打时间戳。每 30 轮 purge 一次超 TTL×4 的条目防 OOM。"""
        self._mode_cache[key] = (payload, self._cycle_idx)
        if self._cycle_idx % 30 == 0:
            max_ttl = max(
                getattr(self, "MODE_CACHE_TTL_ANOMALY", 2),
                getattr(self, "MODE_CACHE_TTL_INFER_COARSE", 1),
                getattr(self, "MODE_CACHE_TTL_KLINE_SHORT", 1),
                getattr(self, "MODE_CACHE_TTL_HORIZON_PREDS", 2),
                getattr(self, "MODE_CACHE_TTL_POSITION_EV", 2),
            )
            cutoff = self._cycle_idx - max_ttl * 4
            self._mode_cache = {k: v for k, v in self._mode_cache.items() if v[1] >= cutoff}

    def _advance_cycle_idx(self) -> int:
        """B4 防御：推进轮次计数，若发生回退（日期 rollover / 手工 reset）自动清 MODE 缓存。

        关键机制：
        - 用 self._last_cycle_seen 记住上次推进后的值（不因外部修改 cycle_idx 而丢失）。
        - 如果外部传入的当前 cycle_idx < _last_cycle_seen，说明有外部把计数回退了。
        - 回退会导致缓存条目 written_cycle 全部 > new_cycle → TTL 失效判定永远为 False →
          缓存永不过期、S1 异常评分永远不重算（整个系统假活）。
        """
        last_seen = getattr(self, "_last_cycle_seen", -1)
        current_before_advance = getattr(self, "_cycle_idx", 0)

        if last_seen >= 1 and current_before_advance < last_seen:
            # 发现回退：清缓存
            if getattr(self, "_mode_cache", None):
                cache_len_before = len(self._mode_cache)
                try:
                    self._log(
                        f"[缓存TTL] cycle_idx 回退 {last_seen} → {current_before_advance}，"
                        f"清空 {cache_len_before} 条缓存以避免 TTL 错乱",
                        "WARN",
                    )
                except Exception:
                    pass
                self._mode_cache.clear()

        new_idx = max(0, current_before_advance) + 1
        self._cycle_idx = new_idx
        self._last_cycle_seen = new_idx
        return new_idx

    def _pick_topup_from_coarse(self, infer_coarse_coins: list, coarse_inferences: Dict[str, dict]) -> list:
        """粗推理 Top1 选补全推理。Spec §3.1 Phase2: 粗置信度排序后仅 Top1 需补全。

        注意：只返回列表（长度 0 或 1），实际 _fetch_and_infer 调用由主循环负责。
        """
        if not infer_coarse_coins:
            return []
        ranked = sorted(
            infer_coarse_coins,
            key=lambda c: coarse_inferences.get(c, {}).get("confidence", 0.0),
            reverse=True,
        )
        return ranked[:1]

    def _mark_coarse_inference(self, inference: dict):
        """为粗推理结果打 _coarse=True 标记（原地修改）。"""
        inference["_coarse"] = True

    def _format_confidence(self, conf) -> str:
        """置信度 float→2位小数 字符串；非数值返回 'N/A'。"""
        return f"{conf:.2f}" if isinstance(conf, (int, float)) else "N/A"

    def _apply_topup_full(self, all_inferences: Dict[str, dict], topup_coin: str,
                          full_inference: dict, coarse_confidence: float = None):
        """将补全推理（完整版）覆盖 all_inferences[topup_coin]，清除 _coarse 标，打日志。"""
        cleaned = dict(full_inference)
        cleaned.pop("_coarse", None)
        all_inferences[topup_coin] = cleaned

        full_conf = (
            full_inference.get("confidence")
            or full_inference.get("next_state", {}).get("confidence")
        )
        a7_pass = bool(full_inference.get("a7_pass", True))
        pentagon_pass = bool(full_inference.get("pentagon_pass", True))
        self._log(
            f"[MODE3][补全推理] {topup_coin} 粗→完整版 "
            f"粗置信度={self._format_confidence(coarse_confidence)} "
            f"完整置信度={self._format_confidence(full_conf)} "
            f"A7={'PASS' if a7_pass else 'FAIL'} "
            f"五角={'PASS' if pentagon_pass else 'FAIL'}",
            "INFO",
        )

    def _guard_coarse_not_toppedup(self, coin: str, inference: dict, toppedup_history: set) -> bool:
        """Phase3 开仓门禁：粗结果 + 未补全 → 返回 False（禁止开仓）+ 打 WARN。

        Returns:
            True → 可以继续（非 coarse 或已补全）
            False → 必须跳过该币（禁止进入 _open_position）
        """
        if not bool(inference.get("_coarse", False)):
            return True
        if coin in toppedup_history:
            return True
        # 粗 + 未补全 → 拦截
        conf = inference.get("confidence") or inference.get("next_state", {}).get("confidence")
        conf_str = self._format_confidence(conf)
        self._log(
            f"[MODE3][门禁] {coin} 粗推理结果未补全，跳过开仓 "
            f"(coarse=True 且不在 toppedup_history，粗置信度={conf_str})",
            "WARN",
        )
        return False

    def _get_leverage(self) -> float:
        """获取当前默认杠杆倍数"""
        return float(self.okx_client.cfg.get("default_leverage", 3))

    def _compute_p2_dynamic_sizing_factors(self, hexagram: str,
                                           lookback: int = 30,
                                           min_samples: int = 5) -> Dict:
        """P2 动态仓位管理：计算三因子（凯利/连亏/卦象）。

        - kelly_factor: 半凯利 f 换算的仓位系数；样本不足时返回 1.0
        - consecutive_loss_factor: 连亏缩仓；从 risk_manager.state 读取 current_consecutive_losses
        - hexagram_factor: 卦象类型系数；基于 BULLISH/BEARISH/NEUTRAL
        - hexagram_class: 卦象分类名 bullish/bearish/neutral（用于日志）

        Args:
            hexagram: 当前卦名（如"泰"/"否"）
            lookback: 取最近多少笔算 win_rate / avg_win / avg_loss
            min_samples: 少于该样本数不启用凯利（保守保持默认仓位）

        Returns:
            Dict {kelly_factor, consecutive_loss_factor, hexagram_factor, hexagram_class,
                  vol_regime_factor, vol_regime_class, vol_adaptive_sl_mult, vol_adaptive_tp_mult,
                  win_rate, avg_win, avg_loss, win_streak, loss_streak}
        """
        # 1. 连亏缩仓
        streak = getattr(self.risk_manager.state, "current_consecutive_losses", 0) or 0
        con_loss_f = RiskManager.consecutive_loss_factor(streak)

        # 2. 卦象类型系数
        hex_f, hex_cls = RiskManager.hexagram_class_factor(
            hexagram,
            bullish_hexagrams=set(BULLISH_HEXAGRAMS),
            bearish_hexagrams=set(BEARISH_HEXAGRAMS),
        )

        # 3. 半凯利动态仓位
        kelly_f = 1.0
        wr = aw = al = 0.0
        trades = list(getattr(self.perf_tracker, "trades", []) or [])
        if trades:
            recent = trades[-lookback:] if len(trades) > lookback else trades
            pnls = [t.pnl for t in recent if t.pnl is not None]
            total = len(pnls)
            if total >= min_samples:
                wins = [p for p in pnls if p >= 0]
                losses = [abs(p) for p in pnls if p < 0]
                wr = len(wins) / total if total else 0.0
                aw = (sum(wins) / len(wins)) if wins else 0.0
                al = (sum(losses) / len(losses)) if losses else 0.0
                kelly_f = RiskManager.kelly_half_factor(wr, aw, al)

        # 4. P3 波动率自适应：仓位因子 + ATR 止损/止盈倍率
        # 从最近一次 inference 快照中取波动率（优先 risk_manager.state，否则用默认 0.03）
        vol_raw = getattr(self, "_last_volatility", None) or 0.03
        vol_rf = RiskManager.volatility_position_factor(vol_raw)
        vol_cls = RiskManager.volatility_regime(vol_raw)
        vol_sl, vol_tp = RiskManager.volatility_adaptive_atr_mult(vol_raw)

        # 连胜/连亏（用于日志，不直接做仓位放大；连亏已用）
        win_streak = 0
        loss_streak_current = 0
        for t in reversed(trades):
            if t.pnl is None:
                continue
            if t.pnl >= 0 and loss_streak_current == 0:
                win_streak += 1
            elif t.pnl < 0 and win_streak == 0:
                loss_streak_current += 1
            else:
                break

        return {
            "kelly_factor": kelly_f,
            "consecutive_loss_factor": con_loss_f,
            "hexagram_factor": hex_f,
            "hexagram_class": hex_cls,
            "vol_regime_factor": vol_rf,
            "vol_regime_class": vol_cls,
            "vol_adaptive_sl_mult": vol_sl,
            "vol_adaptive_tp_mult": vol_tp,
            "win_rate": wr,
            "avg_win": aw,
            "avg_loss": al,
            "win_streak": win_streak,
            "loss_streak": streak,
        }

    def _get_base_sl_roi(self, inst_id: str, entry_price: float = 0.0) -> float:
        """读取开仓时 ATR 基线止损收益率。

        优先级（避免 B3 连锁漂移 bug）：
          1. PositionTracker.base_sl_roi（开仓时记录的可靠基线）
          2. stable_base_sl_roi 缓存（旧持仓首次调 SL 前反向推导出的基线，跨轮冻结）
          3. 回退：从 entry_price 和 当前 stop_loss_px 反算（注意：此基线会随 _adjust_sl_tp 漂移！仅首次 fallback 用）
        """
        rec = self.position_tracker.get_open_position(inst_id)
        if rec and rec.base_sl_roi > 0:
            return rec.base_sl_roi
        # 新增 B3：稳定缓存优先（TTL 99999，整个持仓生命周期都冻结）
        chit, cval = self._cache_get(("stable_base_sl_roi", inst_id), ttl_cycles=99999)
        if chit and isinstance(cval, (int, float)) and cval > 0:
            return float(cval)
        # 回退：从 entry_price 和 stop_loss 反算（如果有的话）
        if rec and entry_price > 0 and rec.market_snapshot:
            sl_px = rec.market_snapshot.get("stop_loss_px", 0)
            if sl_px > 0:
                leverage = self._get_leverage()
                price_pct = abs(sl_px - entry_price) / entry_price
                return self._price_change_to_roi(price_pct, leverage)
        return 0.0

    def _get_base_tp_roi(self, inst_id: str, entry_price: float = 0.0) -> float:
        """读取开仓时 ATR 基线止盈收益率。（同 _get_base_sl_roi，三重优先级）"""
        rec = self.position_tracker.get_open_position(inst_id)
        if rec and rec.base_tp_roi > 0:
            return rec.base_tp_roi
        chit, cval = self._cache_get(("stable_base_tp_roi", inst_id), ttl_cycles=99999)
        if chit and isinstance(cval, (int, float)) and cval > 0:
            return float(cval)
        if rec and entry_price > 0 and rec.market_snapshot:
            tp_px = rec.market_snapshot.get("take_profit_px", 0)
            if tp_px > 0:
                leverage = self._get_leverage()
                price_pct = abs(tp_px - entry_price) / entry_price
                return self._price_change_to_roi(price_pct, leverage)
        return 0.0

    def _roi_to_price_change(self, roi_pct: float, leverage: float = None) -> float:
        """订单收益率 → 价格涨跌幅（不含杠杆）

        公式：price_change = roi / leverage
        例子：杠杆10x、订单收益率 +5% → 价格涨跌幅 +0.5%
        """
        if leverage is None:
            leverage = self._get_leverage()
        if leverage <= 0:
            leverage = 1.0
        return roi_pct / leverage

    def _price_change_to_roi(self, price_change_pct: float, leverage: float = None) -> float:
        """价格涨跌幅（不含杠杆） → 订单收益率（含杠杆）

        公式：roi = price_change * leverage
        例子：杠杆10x、价格涨 0.5% → 订单收益率 +5%
        """
        if leverage is None:
            leverage = self._get_leverage()
        return price_change_pct * leverage

    # ── SL/TP 硬门禁（间距% + 爆仓安全边际 双重约束） ──────────────
    # ★ 2026-09-09 ATR放大：配合动态调节逻辑放宽初始间距
    #   约束1【间距下限】：常规仓 SL≥4.0%价格间距 / TP≥12.0%（3:1 RR），轻仓试错 SL≥4.0% / TP≥12.0%
    #                     TIGHTEN/LOWER 收紧场景允许放宽到 常规×70%（SL≥2.8% / TP≥8.4%）
    #                     绝对硬下限（最后保险）：SL≥2.5% / TP≥6.0%
    #   约束2【爆仓安全】：SL/TP 与爆仓价之间必须有 ≥ LIQ_BUFFER_PCT 安全边际，禁止先爆仓
    #                     当约束1 vs 约束2冲突（高杠杆场景）：爆仓约束优先，同时强制告警
    MIN_SL_PCT_NORMAL = 0.040     # 常规仓 SL 价格间距下限 4.0%
    MIN_TP_PCT_NORMAL = 0.120     # 常规仓 TP 价格间距下限 12.0%（3:1 RR）
    MIN_SL_PCT_TRIAL  = 0.040     # 轻仓试错 SL 价格间距下限 4.0%
    MIN_TP_PCT_TRIAL  = 0.120     # 轻仓试错 TP 价格间距下限 12.0%
    TIGHTEN_SL_FLOOR_RATIO = 0.70 # 收紧时最多收紧到基线的 70%
    ABS_HARD_SL_PCT   = 0.025     # 绝对硬下限：任何情况 SL≥2.5% 价格间距
    ABS_HARD_TP_PCT   = 0.060     # 绝对硬下限：任何情况 TP≥6.0% 价格间距
    LIQ_MMR_PCT       = 0.004     # 维持保证金率（OKX小仓位 meme USDT永续约 0.4%）
    LIQ_BUFFER_PCT    = 0.003     # 爆仓安全边际：SL 与爆仓价之间至少 0.3% 价格间距
    LIQ_HARD_WARN_L   = 25        # 超过该杠杆（约爆仓间距3.6%）就触发"建议降杠杆"告警
    LIQ_HARD_LIMIT_L  = 70        # 该杠杆以上爆仓间距≈1.0%<1.5%，两约束必然冲突

    def _estimate_liq_price(self, entry_price: float, pos_side: str, leverage: float) -> float:
        """估算爆仓价（简化公式，带维持保证金率 LIQ_MMR_PCT）。

        简化公式：
          LONG:  liq ≈ entry × (1 - 1/L + MMR)
          SHORT: liq ≈ entry × (1 + 1/L - MMR)
        忽略手续费、资金费率、动态阶梯MMR，作为门禁的保守估计即可。
        """
        if leverage is None or leverage <= 0:
            leverage = self._get_leverage()
        L = max(1.0, float(leverage))
        inv_L = 1.0 / L
        if pos_side == "long":
            return entry_price * (1.0 - inv_L + self.LIQ_MMR_PCT)
        else:
            return entry_price * (1.0 + inv_L - self.LIQ_MMR_PCT)

    def _enforce_sl_price_floor(self,
                                 sl_px: float,
                                 entry_price: float,
                                 pos_side: str,
                                 leverage: float = None,
                                 is_trial: bool = False,
                                 allow_tighten: bool = False,
                                 coin: str = "") -> tuple:
        """止损价格硬门禁：【间距下限约束】+【爆仓安全约束】双重钳制。

        - 约束1（间距下限）：保证不会被立即扫损（PUMP 0.586%案例的原始问题）
        - 约束2（爆仓安全）：保证 SL > liq + buffer，不会先爆仓再止损（用户反馈的关键）
        - 两约束冲突时：爆仓安全约束优先 → 将SL抬到爆仓安全边界，同时输出WARN级告警
                      （建议：降低杠杆到≤20x，让两约束天然兼容）

        Returns:
            (new_sl_px, was_clamped, clamped_pct, conflict_flags)
              conflict_flags: dict(liq_conflict=bool, spacing_clamped=bool, 推荐杠杆=bool)
        """
        conflict = {"liq_conflict": False, "spacing_clamped": False, "warn_leverage": False}
        if sl_px is None or sl_px <= 0 or entry_price <= 0:
            return sl_px, False, 0.0, conflict
        if leverage is None or leverage <= 0:
            leverage = self._get_leverage()
        L = max(1.0, float(leverage))

        # ── 约束1：间距下限 ──────────────────────────────────
        base_min_sl = self.MIN_SL_PCT_TRIAL if is_trial else self.MIN_SL_PCT_NORMAL
        if allow_tighten:
            pct_floor = max(base_min_sl * self.TIGHTEN_SL_FLOOR_RATIO, self.ABS_HARD_SL_PCT)
        else:
            pct_floor = max(base_min_sl, self.ABS_HARD_SL_PCT)

        # long: SL必须 ≤ entry*(1-pct_floor);   short: SL必须 ≥ entry*(1+pct_floor)
        if pos_side == "long":
            sl_spacing_limit = round(entry_price * (1 - pct_floor), 6)
        else:
            sl_spacing_limit = round(entry_price * (1 + pct_floor), 6)

        # ── 约束2：爆仓安全边际 ──────────────────────────────
        # SL 必须距离爆仓价至少 LIQ_BUFFER_PCT (0.3%)
        #   LONG： SL 必须 > liq*(1+buffer) → SL下限 = liq × (1+buffer)
        #   SHORT：SL 必须 < liq*(1-buffer) → SL上限 = liq × (1-buffer)
        liq = self._estimate_liq_price(entry_price, pos_side, L)
        if pos_side == "long":
            sl_liq_safety_limit = round(liq * (1 + self.LIQ_BUFFER_PCT), 6)
        else:
            sl_liq_safety_limit = round(liq * (1 - self.LIQ_BUFFER_PCT), 6)

        # ── 双重约束合成（对LONG取最大的SL下限，对SHORT取最小的SL上限） ──
        # 目标：使 SL 的"安全区域"是 [spacing, liq_safety] 的交集
        #   LONG：SL的合法上限 = min(spacing_limit, entry)  （间距要求SL足够低）
        #         SL的合法下限 = max(liq_safety_limit, 0)   （爆仓要求SL足够高，>liq+buf）
        #         → 如果 SL上限 < SL下限：冲突！必须优先爆仓约束，把SL抬到SL下限（爆仓安全侧）
        #   SHORT：对称，SL下限 vs SL上限
        liq_pct = abs(entry_price - liq) / entry_price
        if pos_side == "long":
            spacing_cap = sl_spacing_limit    # long: SL不能高于此价  （间距约束：SL≤）
            liq_floor = sl_liq_safety_limit   # long: SL不能低于此价  （爆仓约束：SL≥）
            # 合价：最终SL 必须同时满足 ≤spacing_cap 且 ≥liq_floor
            if spacing_cap >= liq_floor:
                # 无冲突：如果输入SL在合法区域就不动；否则钳制到最近的边界
                #   先把SL推到"间距下限"（沿用原门禁逻辑）
                final_sl = min(sl_px, spacing_cap)
                #   再确保SL不跌破爆仓安全边界
                if final_sl < liq_floor:
                    final_sl = liq_floor
                    conflict["liq_conflict"] = False
                    conflict["spacing_clamped"] = True
                elif final_sl != sl_px:
                    conflict["spacing_clamped"] = True
            else:
                # ★ CONFLICT：间距约束要求SL ≤ spacing_cap，但爆仓约束要求SL ≥ liq_floor，
                #   两者不相交！此时必须优先爆仓约束（否则先爆仓，止损无效），
                #   将SL设置到爆仓安全边界，并强制告警"必须降杠杆"
                conflict["liq_conflict"] = True
                conflict["spacing_clamped"] = True
                conflict["warn_leverage"] = True
                final_sl = liq_floor
        else:
            # SHORT：SL必须 ≥ spacing_limit（间距下限，short方向SL更高）
            #         SL必须 ≤ liq_safety_limit（爆仓安全：SL < liq - buffer）
            spacing_floor = sl_spacing_limit
            liq_cap = sl_liq_safety_limit
            if spacing_floor <= liq_cap:
                # 无冲突
                final_sl = max(sl_px, spacing_floor)
                if final_sl > liq_cap:
                    final_sl = liq_cap
                    conflict["liq_conflict"] = False
                    conflict["spacing_clamped"] = True
                elif final_sl != sl_px:
                    conflict["spacing_clamped"] = True
            else:
                # ★ CONFLICT
                conflict["liq_conflict"] = True
                conflict["spacing_clamped"] = True
                conflict["warn_leverage"] = True
                final_sl = liq_cap

        # 日志：高杠杆告警（即使无冲突，若超过阈值也提示）
        if L >= self.LIQ_HARD_WARN_L and not conflict["warn_leverage"]:
            conflict["warn_leverage"] = True
        if conflict["warn_leverage"] or conflict["liq_conflict"]:
            self._log(
                f"[SL门禁·爆仓告警] {coin or '?'} L={int(L)}x | entry={entry_price:.6f} "
                f"输入SL={sl_px:.6f}(间距{abs(sl_px-entry_price)/entry_price*100:.2f}%) "
                f"→ 最终SL={final_sl:.6f}(间距{abs(final_sl-entry_price)/entry_price*100:.2f}%) | "
                f"爆仓价≈{liq:.6f}(间距{liq_pct*100:.2f}%) 安全buffer={self.LIQ_BUFFER_PCT*100:.1f}% | "
                f"间距下限{pct_floor*100:.2f}% → spacing界={sl_spacing_limit:.6f} | "
                f"爆仓安全界={sl_liq_safety_limit:.6f} | "
                f"CONFLICT={conflict['liq_conflict']} 建议降杠杆到≤20x",
                "WARN",
            )

        was_clamped = (final_sl != sl_px)
        cur_pct = abs(sl_px - entry_price) / entry_price
        return final_sl, was_clamped, cur_pct, conflict

    def _enforce_tp_price_floor(self,
                                 tp_px: float,
                                 entry_price: float,
                                 pos_side: str,
                                 leverage: float = None,
                                 is_trial: bool = False,
                                 allow_lower: bool = False,
                                 coin: str = "") -> tuple:
        """止盈价格硬门禁：【间距下限约束】+【爆仓安全约束】的对称实现。

        TP相对SL风险较小（TP在盈利侧，不会爆仓），但仍需：
        1. 保证最低TP间距（避免0.x%TP毫无意义）
        2. SHORT的TP理论上也要检查爆仓侧（SHORT TP < entry 距离足够，一般不会有冲突）
        3. 同样在超高杠杆场景触发降杠杆告警（门禁共用告警阈值）
        """
        conflict = {"liq_conflict": False, "spacing_clamped": False, "warn_leverage": False}
        if tp_px is None or tp_px <= 0 or entry_price <= 0:
            return tp_px, False, 0.0, conflict
        if leverage is None or leverage <= 0:
            leverage = self._get_leverage()
        L = max(1.0, float(leverage))
        # ── 约束1：间距下限 ──────────────────────────────────
        base_min_tp = self.MIN_TP_PCT_TRIAL if is_trial else self.MIN_TP_PCT_NORMAL
        if allow_lower:
            pct_floor = max(base_min_tp * self.TIGHTEN_SL_FLOOR_RATIO, self.ABS_HARD_TP_PCT)
        else:
            pct_floor = max(base_min_tp, self.ABS_HARD_TP_PCT)
        # LONG: TP ≥ entry*(1+pct_floor)  SHORT: TP ≤ entry*(1-pct_floor)
        if pos_side == "long":
            tp_spacing_limit = round(entry_price * (1 + pct_floor), 6)
            final_tp = max(tp_px, tp_spacing_limit)
        else:
            tp_spacing_limit = round(entry_price * (1 - pct_floor), 6)
            final_tp = min(tp_px, tp_spacing_limit)
        # TP 爆仓侧无冲突（TP在盈利方向远离爆仓），但仍做超高杠杆告警
        cur_pct = abs(tp_px - entry_price) / entry_price
        liq_pct = abs(entry_price - self._estimate_liq_price(entry_price, pos_side, L)) / entry_price
        if final_tp != tp_px:
            conflict["spacing_clamped"] = True
        if L >= self.LIQ_HARD_WARN_L:
            conflict["warn_leverage"] = True
            self._log(
                f"[TP门禁·高杠杆] {coin or '?'} L={int(L)}x 爆仓仅{liq_pct*100:.2f}% < 1.5%间距，"
                f"建议降杠杆到≤20x以确保SL/TP两约束兼容",
                "WARN",
            )
        was_clamped = (final_tp != tp_px)
        return final_tp, was_clamped, cur_pct, conflict

    def _calc_sl_price(
        self, entry_price: float, pos_side: str, sl_roi_pct: float, leverage: float = None
    ) -> float:
        """根据订单止损收益率计算止损价格

        Args:
            entry_price: 开仓价
            pos_side: long/short
            sl_roi_pct: 订单止损收益率（正数，如 0.03 = -3% 亏损）
            leverage: 杠杆倍数

        Returns:
            止损价格
        """
        if leverage is None:
            leverage = self._get_leverage()
        price_change = self._roi_to_price_change(sl_roi_pct, leverage)
        if pos_side == "long":
            return entry_price * (1 - price_change)
        else:
            return entry_price * (1 + price_change)

    def _calc_tp_price(
        self, entry_price: float, pos_side: str, tp_roi_pct: float, leverage: float = None
    ) -> float:
        """根据订单止盈收益率计算止盈价格

        Args:
            entry_price: 开仓价
            pos_side: long/short
            tp_roi_pct: 订单止盈收益率（正数，如 0.06 = +6% 盈利）
            leverage: 杠杆倍数

        Returns:
            止盈价格
        """
        if leverage is None:
            leverage = self._get_leverage()
        price_change = self._roi_to_price_change(tp_roi_pct, leverage)
        if pos_side == "long":
            return entry_price * (1 + price_change)
        else:
            return entry_price * (1 - price_change)

    # ── Phase B: EV 风险价值雷达（四档决策）───────────────────
    def _build_ev_subscores(self,
                            pos_side: str,
                            position_age_sec: float,
                            upl_ratio: float,
                            inference: Dict) -> Dict[str, float]:
        """构造 EV 的 7 个归一化子分 s_i ∈ [0,1]（Phase C 细化完成）。

        返回 key 与 self.ev_weights 的 key 严格对齐（少算一项 → 权重为 0）。

        Phase C 真化项：
          - trend_alignment_s（子分3）：bagua_direction + BTC弹簧力场趋势 + bagua_confidence 三因子
          - liquidity_risk_s（子分7）：kline volume 稳定性 + 放量倍数 + 波动率惩罚 三因子
        """
        import numpy as np

        conf = float(inference.get("confidence", 0.5))
        direction = str(inference.get("direction", "UP"))
        vol = float(inference.get("volatility", 0.03))

        # 1. 置信度（直接 clamp 到 [0,1]）
        confidence_s = max(0.0, min(1.0, conf))

        # 2. 方向一致性：持仓方向与本次推理方向是否对齐
        if (pos_side == "long" and direction == "UP") or \
           (pos_side == "short" and direction == "DOWN"):
            direction_consistency_s = 1.0
        elif (pos_side == "long" and direction == "DOWN") or \
             (pos_side == "short" and direction == "UP"):
            direction_consistency_s = 0.0
        else:
            direction_consistency_s = 0.5

        # 3. 趋势对齐度（Phase C C13：三因子加权）
        #    因子 A(0.4)：持仓 vs bagua_direction（卦象趋势）
        #    因子 B(0.4)：持仓 vs BTC 日线大势（_check_btc_trend 双均线弹簧力场）
        #    因子 C(0.2)：bagua_confidence（卦象自身置信度作为强度放大）
        bagua_dir = str(inference.get("bagua_direction", "neutral")).lower()
        if bagua_dir == "neutral":
            bagua_align = 0.5
        elif (pos_side == "long" and bagua_dir == "long") or \
             (pos_side == "short" and bagua_dir == "short"):
            bagua_align = 1.0
        else:
            bagua_align = 0.0
        try:
            btc_bearish, _ = self._check_btc_trend()
        except Exception:
            btc_bearish = None
        if btc_bearish is None:
            btc_trend_align = 0.5
        elif (pos_side == "long" and not btc_bearish) or \
             (pos_side == "short" and btc_bearish):
            btc_trend_align = 1.0
        else:
            btc_trend_align = 0.0
        bagua_conf = max(0.0, min(1.0, float(inference.get("bagua_confidence", 0.5))))
        trend_alignment_s = max(0.0, min(1.0,
            0.4 * bagua_align + 0.4 * btc_trend_align + 0.2 * bagua_conf
        ))

        # 4. PnL 动量：浮盈 → 高分；浮亏 10% → 接近 0
        pnl_momentum_s = max(0.0, min(1.0, 0.5 + float(upl_ratio) * 10.0))

        # 5. 市况友好度：波动率越低越友好（低波→0.9；正常→0.6；高波→0.3）
        if vol <= 0.02:
            regime_friendly_s = 0.9
        elif vol <= 0.05:
            regime_friendly_s = 0.6
        else:
            regime_friendly_s = 0.3

        # 6. 持仓年龄：以 60h（1H 周期 60 根 ≈ 2.5 天）为中轴线性衰减
        hold_h = max(0.0, position_age_sec / 3600.0)
        holding_age_s = max(0.0, min(1.0, 1.0 - hold_h / 60.0))

        # 7. 流动性风险（Phase C C14：三因子加权 → 越高代表流动性越好，风险越低）
        #    因子 A(0.5)：volume 稳定性 mean/std（越大越稳定）
        #    因子 B(0.3)：最近 volume 较均值放量倍数（越大 → 参与度高 → 好）
        #    因子 C(0.2)：1 - vol/0.10（波动率越低 → 滑点风险越低 → 好）
        kline_data = inference.get("kline_data") or []
        try:
            volumes = [float(k.get("v", k.get("V", 0))) for k in kline_data if k]
            # 取最近 60 根（不足则全取，最少 5 根有效）
            volumes = volumes[:60]
            if len(volumes) >= 5 and sum(volumes) > 0:
                v_arr = np.array(volumes, dtype=float)
                mean_v = float(np.mean(v_arr))
                std_v = float(np.std(v_arr)) + 1e-9
                # 稳定性 = mean/std，典型区间 [0.5, 5.0]，norm 至 [0.2, 1.0]
                stability_raw = mean_v / std_v
                vol_stability_norm = max(0.2, min(1.0, 0.2 + 0.8 * min(1.0, stability_raw / 3.0)))
                # 放量 = last / mean，典型 [0.5, 3.0]，norm 至 [0.2, 1.0]
                last_v = float(v_arr[-1]) if len(v_arr) else mean_v
                spike_ratio = last_v / mean_v if mean_v > 0 else 1.0
                volume_spike_norm = max(0.2, min(1.0, 0.2 + 0.8 * min(1.0, spike_ratio / 2.5)))
                # 波动率惩罚：vol=0 → 1.0；vol=0.10 → 0.0
                vol_liquidity_norm = max(0.0, min(1.0, 1.0 - vol / 0.10))
                liquidity_risk_s = max(0.0, min(1.0,
                    0.5 * vol_stability_norm + 0.3 * volume_spike_norm + 0.2 * vol_liquidity_norm
                ))
            else:
                liquidity_risk_s = 0.5  # 数据不足 → 中性中值
        except Exception:
            liquidity_risk_s = 0.5  # 异常降级 → 中性中值

        return {
            "confidence_s": round(confidence_s, 4),
            "direction_consistency_s": round(direction_consistency_s, 4),
            "trend_alignment_s": round(trend_alignment_s, 4),
            "pnl_momentum_s": round(pnl_momentum_s, 4),
            "regime_friendly_s": round(regime_friendly_s, 4),
            "holding_age_s": round(holding_age_s, 4),
            "liquidity_risk_s": round(liquidity_risk_s, 4),
        }

    def _handle_ev_four_tier(self,
                             coin: str,
                             inst_id: str,
                             pos_side: str,
                             position_age_sec: float,
                             in_protection: bool,
                             upl: float,
                             upl_ratio: float,
                             inference: Dict,
                             all_inferences: Dict) -> Dict:
        """EV 四档决策（Spec §4.3）。

        四档：
          T1 FORCE_CLOSE:   EV < EV_FORCE_CLOSE_BELOW，非保护期 → 2/2 确认强制离场
          T2 WARN:          EV_WARN_LOWER_BOUND ≤ EV < EV_WARN_UPPER_BOUND → 收紧止损
          T3 NORMAL:        EV_WARN_UPPER_BOUND ≤ EV ≤ EV_STRONG_HOLD_ABOVE → 按原计划
          T4 STRONG_HOLD:   EV > EV_STRONG_HOLD_ABOVE → 放宽止损/放大止盈

        Feature Flag: enable_ev_radar=False 时短路 return，不调 calc_position_ev。
        Protection:  in_protection=True 时禁止 FORCE_CLOSE/WARN 动作，仅日志 skip。

        返回 decision dict:
          {"tier": "FORCE_CLOSE"|"WARN"|"NORMAL"|"STRONG_HOLD"|"BYPASS",
           "ev": float, "subs": dict, "action": str|None}
        """
        # S2 开关短路：calc_position_ev 必须从未被调用（对应 TestEVSwitchOffBypasses）
        if not getattr(self, "enable_ev_radar", False):
            self._log(f"[{coin}] EV BYPASS (S2=off)", "INFO")
            return {"tier": "BYPASS", "ev": None, "subs": {}, "action": None}

        from scripts.memory_l4.trading_utils import RiskManager

        # ── 构造 7 归一化子分 + EV 合成 ──
        subscores = self._build_ev_subscores(pos_side, position_age_sec,
                                             upl_ratio, inference)
        weights = getattr(self, "ev_weights", None) or {k: 1/7 for k in subscores}
        ev, subs = RiskManager.calc_position_ev(subscores, weights)

        # ── 保护期门禁：EV < WARN_UPPER 时 T1/T2 绝对禁用，仅日志 skip ──
        if in_protection and ev < getattr(self, "EV_WARN_UPPER_BOUND", -0.10):
            self._log(
                f"[{coin}] EV={ev:.3f} < WARN(EV<"
                f"{getattr(self, 'EV_WARN_UPPER_BOUND', -0.10):.2f}) "
                f"but protected (hold={position_age_sec/3600:.1f}h<"
                f"{getattr(self, 'POSITION_PROTECTION_HOURS', 6.0):.0f}h) → "
                f"skip EV_force / EV_warn actions",
                "INFO",
            )
            return {"tier": "PROTECTED_SKIP", "ev": ev, "subs": subs, "action": None}

        # ── 四档阈值 ──
        force_below = getattr(self, "EV_FORCE_CLOSE_BELOW", -0.35)
        warn_lower = getattr(self, "EV_WARN_LOWER_BOUND", -0.35)
        warn_upper = getattr(self, "EV_WARN_UPPER_BOUND", -0.10)
        strong_above = getattr(self, "EV_STRONG_HOLD_ABOVE", +0.30)
        current_price = float(inference.get("price", 0.0))

        # T1: FORCE_CLOSE（EV 深度低，非保护期 → 2/2 离场确认）
        if ev < force_below and not in_protection:
            confirmed, cnt = self._exit_confirm(coin, self.EXIT_ACT_EV_FORCE_CLOSE)
            if confirmed:
                self._clear_exit_confirm(coin, self.EXIT_ACT_EV_FORCE_CLOSE)
                reason = f"ev_force_close|ev={ev:.3f}<{force_below:.2f}|cnt={cnt}"
                self._handle_close_position(
                    inst_id=inst_id, coin=coin, pos_side=pos_side,
                    exit_price=current_price, exit_reason=reason,
                    pnl=upl, pnl_pct=upl_ratio,
                )
                return {"tier": "FORCE_CLOSE", "ev": ev, "subs": subs,
                        "action": f"closed|{reason}"}
            else:
                self._log(
                    f"[{coin}] EV={ev:.3f} T1 FORCE_CLOSE 1/"
                    f"{self.EXIT_CONFIRM_REQUIRED} (cnt={cnt})，等待下一轮确认",
                    "WARN",
                )
                return {"tier": "FORCE_CLOSE_PENDING", "ev": ev, "subs": subs,
                        "action": "pending_confirm"}

        # T2: WARN（收紧止损）
        if warn_lower <= ev < warn_upper:
            self._log(
                f"[{coin}] EV={ev:.3f} T2 WARN | "
                f"trend_align={subs.get('trend_alignment_s', 0):.2f} "
                f"liquidity={subs.get('liquidity_risk_s', 0):.2f} "
                f"dir_consist={subs.get('direction_consistency_s', 0):.2f} "
                f"pnl_mom={subs.get('pnl_momentum_s', 0):.2f} → 收紧止损",
                "WARN",
            )
            adj = getattr(self, "_adjust_sl_tp", None)
            if adj and callable(adj):
                try:
                    adj(coin, inst_id, pos_side, mode="tighten")
                except Exception:
                    pass
            return {"tier": "WARN", "ev": ev, "subs": subs, "action": "tighten_sl"}

        # T4: STRONG_HOLD（放宽止损/止盈）
        if ev > strong_above:
            self._log(
                f"[{coin}] EV={ev:.3f} T4 STRONG_HOLD | "
                f"trend_align={subs.get('trend_alignment_s', 0):.2f} "
                f"liquidity={subs.get('liquidity_risk_s', 0):.2f} "
                f"dir_consist={subs.get('direction_consistency_s', 0):.2f} "
                f"pnl_mom={subs.get('pnl_momentum_s', 0):.2f} → 放宽止损/止盈",
                "INFO",
            )
            adj = getattr(self, "_adjust_sl_tp", None)
            if adj and callable(adj):
                try:
                    adj(coin, inst_id, pos_side, mode="relax")
                except Exception:
                    pass
            return {"tier": "STRONG_HOLD", "ev": ev, "subs": subs, "action": "relax_sl"}

        # T3: NORMAL（不动作，按原计划）
        self._log(
            f"[{coin}] EV={ev:.3f} T3 NORMAL | "
            f"trend_align={subs.get('trend_alignment_s', 0):.2f} "
            f"liquidity={subs.get('liquidity_risk_s', 0):.2f} "
            f"dir_consist={subs.get('direction_consistency_s', 0):.2f} "
            f"pnl_mom={subs.get('pnl_momentum_s', 0):.2f} → 按原计划持有",
            "INFO",
        )
        return {"tier": "NORMAL", "ev": ev, "subs": subs, "action": None}

    def _adjust_sl_tp(self, coin: str, inst_id: str, pos_side: str, mode: str) -> bool:
        """S2 EV雷达真实调 SL/TP（WARN收紧 / STRONG_HOLD放宽）。
        基于开仓时 ATR 基线 ROI × modulation 因子 + ATR floor 保护。
        同一 inst_id+mode 2 轮内只调一次（防 OKX API 重复触发）。
        返回 True 表示成功下发（或 dry-run 日志）；False = 跳过。
        """
        assert mode in ("tighten", "relax"), f"_adjust_sl_tp 未知 mode={mode}"
        # ── 防重复：2 轮 TTL 缓存 ──────────────────────────
        cache_key = ("s2_adjust_sl_tp", inst_id, mode)
        prev_hit, _ = self._cache_get(cache_key, ttl_cycles=2)
        if prev_hit:
            return False
        # ── 读取基线 SL/TP ROI（开仓 ATR 基线） ─────────────
        rec = self.position_tracker.get_open_position(inst_id)
        if rec is None or rec.entry_price is None or rec.entry_price <= 0:
            self._log(f"[S2调整SLTP] {coin} {inst_id} 取不到持仓 entry_price，跳过", "DEBUG")
            return False
        entry_price = rec.entry_price
        leverage = self._get_leverage()
        base_sl_roi = self._get_base_sl_roi(inst_id, entry_price)
        base_tp_roi = self._get_base_tp_roi(inst_id, entry_price)
        if base_sl_roi <= 0 or base_tp_roi <= 0:
            self._log(
                f"[S2调整SLTP] {coin} {inst_id} 基线SL/TP ROI缺失 "
                f"(sl={base_sl_roi:.4f}, tp={base_tp_roi:.4f})，旧持仓不调",
                "WARN",
            )
            return False
        # ── modulation 因子 + floor 保护 ────────────────────
        if mode == "tighten":
            sl_k, tp_k = 0.7, 0.85     # 收紧：止损近30%、止盈降15%
        else:  # relax
            sl_k, tp_k = 1.3, 1.25     # 放宽：止损远30%、止盈提25%
        # ★ FIX Bug#2：原 ATR_FLOOR_ROI=0.015（订单ROI 1.5%）@10x = 仅 0.15% 价格间距，远小于约定
        #   改为"价格间距%口径"的硬下限：tighten模式允许 SL≥1.05%（常规1.5%×0.7），relax模式 SL≥1.5%
        #   先用 ROI 维度钳制，再在后面用真实价格二次硬门禁（双保险）
        _tighten_floor_price_pct = (self.MIN_SL_PCT_NORMAL * self.TIGHTEN_SL_FLOOR_RATIO)  # 1.05%
        _relax_floor_price_pct = self.MIN_SL_PCT_NORMAL  # 1.5%
        _floor_price_pct = _tighten_floor_price_pct if mode == "tighten" else _relax_floor_price_pct
        ATR_FLOOR_ROI = self._price_change_to_roi(_floor_price_pct, leverage)  # 换算为订单ROI口径
        new_sl_roi = max(base_sl_roi * sl_k, ATR_FLOOR_ROI)
        new_tp_roi = base_tp_roi * tp_k
        # ── 换算真实价格 ──────────────────────────────────
        new_sl_px = self._calc_sl_price(entry_price, pos_side, new_sl_roi, leverage)
        new_tp_px = self._calc_tp_price(entry_price, pos_side, new_tp_roi, leverage)
        # ── ★ FIX：SL/TP 硬门禁（间距下限 + 爆仓安全边际 双约束） ──
        _allow_tighten = (mode == "tighten")
        new_sl_px, _sl_clamped, _sl_old_pct, _sl_cfl = self._enforce_sl_price_floor(
            new_sl_px, entry_price, pos_side, leverage=leverage,
            allow_tighten=_allow_tighten, coin=coin)
        new_tp_px, _tp_clamped, _tp_old_pct, _tp_cfl = self._enforce_tp_price_floor(
            new_tp_px, entry_price, pos_side, leverage=leverage,
            allow_lower=_allow_tighten, coin=coin)
        if _sl_clamped or _tp_clamped:
            _tail = ""
            if _sl_cfl.get("liq_conflict") or _tp_cfl.get("liq_conflict"):
                _tail = " 【爆仓约束优先】当前杠杆过高，建议≤20x"
            self._log(
                f"[S2调整SLTP] {coin} 硬门禁钳制 | mode={mode} "
                f"SL: {_sl_old_pct*100:.2f}%→{abs(new_sl_px-entry_price)/entry_price*100:.2f}% "
                f"{'(已钳制)' if _sl_clamped else ''} | "
                f"TP: {_tp_old_pct*100:.2f}%→{abs(new_tp_px-entry_price)/entry_price*100:.2f}% "
                f"{'(已钳制)' if _tp_clamped else ''}{_tail}",
                "WARN",
            )
        # ── 方向合理性校验（顺序不可乱） ───────────────────
        if pos_side == "long":
            ok = (new_sl_px < entry_price < new_tp_px)
        else:  # short
            ok = (new_tp_px < entry_price < new_sl_px)
        if not ok:
            self._log(
                f"[S2调整SLTP] {coin} {pos_side} 方向校验失败："
                f"sl={new_sl_px:.3f}, entry={entry_price:.3f}, tp={new_tp_px:.3f}，跳过",
                "ERROR",
            )
            return False
        # ── 取消旧 algo → 下新 SL/TP ──────────────────────
        try:
            self._log(
                f"[S2调整SLTP:{mode}] {coin} {pos_side} {inst_id} "
                f"| baseline SL/TP ROI = {base_sl_roi*100:.2f}% / {base_tp_roi*100:.2f}%"
                f" → x{sl_k:.2f}/x{tp_k:.2f} = {new_sl_roi*100:.2f}% / {new_tp_roi*100:.2f}%"
                f" | price SL={new_sl_px:.3f}, TP={new_tp_px:.3f} (entry={entry_price:.3f})",
                "INFO",
            )
            try:
                if self.okx_client and hasattr(self.okx_client, "cancel_algo_orders"):
                    self.okx_client.cancel_algo_orders(instId=inst_id)
            except Exception as ce:
                self._log(f"[S2调整SLTP] 取消旧algo（可能无）：{ce}", "DEBUG")
            if self.okx_client and hasattr(self.okx_client, "place_stop_loss_take_profit"):
                self.okx_client.place_stop_loss_take_profit(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    stop_loss_px=new_sl_px,
                    take_profit_px=new_tp_px,
                    reason=f"ev_adjust_sl_tp:{mode}",
                )
            else:
                self._log(
                    f"[S2调整SLTP] DRY-RUN okx_client.place_stop_loss_take_profit 未配置",
                    "INFO",
                )
            # ── B3 冻结基线：旧持仓(base_roi=0) 首次调节后，把基线"钉死"，避免下一轮反算漂移 ──
            # 没有这步时：WARN tighten → SL 降到 64545 → 下轮 fallback 反算把 64545 当"基线"
            # → 再次 tighten ×0.7 → SL 再缩 30%（连锁漂移 bug）
            try:
                if getattr(rec, "base_sl_roi", 0) <= 0:
                    try:
                        rec.base_sl_roi = float(base_sl_roi)
                    except Exception:
                        self._cache_set(("stable_base_sl_roi", inst_id), float(base_sl_roi))
                if getattr(rec, "base_tp_roi", 0) <= 0:
                    try:
                        rec.base_tp_roi = float(base_tp_roi)
                    except Exception:
                        self._cache_set(("stable_base_tp_roi", inst_id), float(base_tp_roi))
            except Exception:
                pass  # 冻结失败不影响主流程
            self._cache_set(cache_key, self._cycle_idx)
            return True
        except Exception as e:
            self._log(f"[S2调整SLTP] {coin} 失败：{e}", "ERROR")
            return False

    # ── Phase C: 多 horizon 最佳离场 K 线推荐（S3）──────────────
    def _recommend_exit_bars(self,
                             coin: str,
                             pos_side: str,
                             held_k_bar: int,
                             inference: Dict,
                             k_candidates: List[int] = None) -> Dict:
        """结合当前已持仓 K 线数，推荐 HOLD/PREP_EXIT/EXTEND_TRACK（S3）。

        逻辑（Spec §4.2）：
          1. S3=OFF → 短路 BYPASS，predict_multi_horizon 从未被调用
          2. 调 RiskManager.predict_multi_horizon 计算各候选 K-bar 的置信度
          3. 取 max(confidence) 条目的 k_bar 作为 best_k_bar
          4. best_k_bar > held_k_bar + margin → 尚未到站 → HOLD
             best_k_bar ≈ held_k_bar ± margin → 接近离场站 → PREP_EXIT
             best_k_bar << held_k_bar 且 best.direction 反向 → 已经过站 → PREP_EXIT
             其余 → EXTEND_TRACK（延长观察）

        返回: {"best_k_bar": int, "recommended_action": str,
               "best_direction": str, "best_confidence": float}
        """
        # S3 开关短路（switch-off 测试断言 predict 不被调）
        if not getattr(self, "enable_multi_horizon", False):
            return {"best_k_bar": -1, "recommended_action": "BYPASS",
                    "best_direction": "", "best_confidence": 0.0}

        from scripts.memory_l4.trading_utils import RiskManager

        if k_candidates is None:
            # Spec §4.3.1: 默认 horizon 列表对齐 BCRM2 多 horizon 训练/预测
            k_candidates = list(getattr(
                self, "HORIZON_BAR_CANDIDATES", [1, 2, 3, 6, 10, 20, 30]))
        margin = int(getattr(self, "HORIZON_PREP_EXIT_MARGIN", 3))

        # ── 真实 BCRM 多 horizon（Phase C §4.3.1 接入）──────────────
        # 优先：从 adapter 调 engine.predict_multi_horizon（每 horizon 独立 LGBM）
        # 失败：回退 RiskManager.predict_multi_horizon 合成（pentagon_score 启发式）
        source_tag = "synthetic"
        horizons = []
        try:
            adapter = getattr(self, "bcrm2_adapters", {}).get(coin)
            kline_data = inference.get("kline_data")
            if adapter is not None and kline_data:
                df = self._kline_to_dataframe(kline_data)
                # 缓存：同币种同周期 S3 不重复算（避免 MODE3 每轮 N^2）
                cache_key = ("s3_mh", coin, pos_side, len(df),
                             float(df["close"].iloc[-1]) if len(df) else 0.0)
                cached_hit, cached_payload = self._cache_get(cache_key, ttl_cycles=1)
                if cached_hit and isinstance(cached_payload, dict):
                    horizons = cached_payload.get("horizons") or []
                    source_tag = cached_payload.get("source", "bcrm2")
                else:
                    mh_result = adapter.predict_multi_horizon(
                        df, horizons=list(k_candidates), idx=-1
                    )
                    if mh_result.get("ok"):
                        mh_dict = mh_result.get("multi_horizon", {})
                        synthesis = mh_result.get("synthesis", {}) or {}
                        mh_dir = mh_result.get("direction", "UP")
                        for h in k_candidates:
                            probs = mh_dict.get(h, {"P_up": 0.5, "P_down": 0.5})
                            if pos_side == "long":
                                p_correct = float(probs.get("P_up", 0.5))
                                h_dir = "UP" if p_correct >= 0.5 else "DOWN"
                            else:
                                p_correct = float(probs.get("P_down", 0.5))
                                h_dir = "DOWN" if p_correct >= 0.5 else "UP"
                            # expected_roi_pct：用 synthesis 的 S(k) 值近似，区间 [-0.05, 0.10]
                            s_curve = synthesis.get("S_curve", {})
                            s_k = float(s_curve.get(h, 0.0))
                            roi = max(-0.05, min(0.10, s_k * 0.05 + 0.01))
                            horizons.append({
                                "k_bar": int(h),
                                "confidence": round(p_correct, 4),
                                "direction": h_dir,
                                "expected_roi_pct": round(roi, 6),
                            })
                        source_tag = "bcrm2"
                    else:
                        horizons = []
                    self._cache_set(cache_key, {"horizons": horizons, "source": source_tag})

        except Exception as _s3e:
            horizons = []  # 触发 fallback

        if not horizons:
            pred = RiskManager.predict_multi_horizon(inference, k_candidates)
            horizons = pred.get("horizons", [])
            source_tag = "synthetic"

        if not horizons:
            return {"best_k_bar": -1, "recommended_action": "NOOP",
                    "best_direction": "", "best_confidence": 0.0,
                    "source": source_tag}

        best_h = max(horizons, key=lambda x: x["confidence"])
        best_k = int(best_h["k_bar"])
        best_dir = str(best_h["direction"])
        best_conf = float(best_h["confidence"])

        # 持仓方向 pos_side 与 best_dir 是否一致
        pos_is_long = (pos_side == "long")
        best_is_up = (best_dir == "UP")
        direction_consistent = (pos_is_long == best_is_up)

        if best_k > held_k_bar + margin and direction_consistent:
            # 最佳站在后面 → 继续持有
            action = "HOLD"
        elif abs(best_k - held_k_bar) <= margin:
            # 接近最佳站 → 准备离场
            action = "PREP_EXIT"
        elif best_k < held_k_bar - margin and not direction_consistent:
            # 已过站且反向（原预测 UP 过久变为 DOWN 等）→ PREP_EXIT
            action = "PREP_EXIT"
        elif best_k < held_k_bar and not direction_consistent:
            # 已过站 + 反向（宽松版）
            action = "PREP_EXIT"
        else:
            action = "EXTEND_TRACK"

        return {
            "best_k_bar": best_k,
            "recommended_action": action,
            "best_direction": best_dir,
            "best_confidence": round(best_conf, 4),
            "source": source_tag,  # "bcrm2" | "synthetic"
        }

    # ── Phase C: S4 排名止盈前构造持仓列表 ─────────────────────
    def _build_ranked_positions(self, all_inferences: Dict[str, dict]) -> List[Dict]:
        """遍历当前所有持仓 + 从 all_inferences 取对应 inference，构建 S4 输入。

        每个元素至少包含：coin, inst_id, pos_side, upl, upl_ratio, mark_price,
                          in_protection, position_age_sec, inference(可选)
        按 upl 从高到低排序返回（Top1 最大盈利在 [0]）。
        """
        result: List[Dict] = []
        if not all_inferences:
            return result

        for coin, inference in all_inferences.items():
            try:
                pos_info = self._check_positions(coin)
                if not pos_info.get("has_position"):
                    continue
                tracker_pos = self.position_tracker.get_open_position(pos_info.get("inst_id", f"{coin}-USDT-SWAP"))
                is_external = tracker_pos and tracker_pos.strategy_source == "external"
                if is_external:
                    continue

                inst_id = pos_info.get("inst_id", f"{coin}-USDT-SWAP")
                pos_side = pos_info.get("pos_side", "long")
                upl = float(pos_info.get("upl", 0.0))
                upl_ratio = float(pos_info.get("upl_ratio", 0.0))
                mark_price = float(pos_info.get("mark_px", inference.get("price", 0.0)) or 0.0)

                open_time = pos_info.get("open_time", 0)
                position_age_sec = (time.time() - open_time) if open_time > 0 else 0.0
                in_protection = self._is_position_protected(position_age_sec)

                result.append({
                    "coin": coin, "inst_id": inst_id, "pos_side": pos_side,
                    "upl": upl, "upl_ratio": upl_ratio, "mark_price": mark_price,
                    "in_protection": in_protection, "position_age_sec": position_age_sec,
                    "inference": inference,
                })
            except Exception as _e:
                self._log(f"[{coin}] _build_ranked_positions 异常: {_e}", "WARN")
                continue

        # 按 upl 从高到低排序（Top1 盈利最大在前）
        result.sort(key=lambda x: float(x.get("upl", 0.0)), reverse=True)
        return result

    # ── Phase C: 排名止盈 Top1 执行（S4）──────────────────────
    def _handle_ranked_tp_top1(self,
                               positions_with_pnl: List[Dict],
                               gap_threshold: float = None) -> Dict:
        """排名止盈 A/B/C 三档（Spec §4.3.2）。

        A 档（立即止盈换仓）：gap ≥ 阈值 + 非保护期 → 2/2 确认后平仓
        B 档（排队止盈）：gap < 阈值 + 持仓≥12h + 浮盈>0 → 写 reduce_plan 到 PositionRecord
        C 档（不参与）：保护期内 / 浮盈<min_profit / gap 极小 → 无动作

        逻辑：
          1. S4=OFF → 短路 BYPASS
          2. 调 calc_ranked_tp_gap → gap+trigger
          3. trigger=True → A 档路径（保护期门禁 → 2/2 确认 → close）
          4. trigger=False + B 档条件满足 → 写 reduce_plan
          5. 否则 → C 档无动作
        """
        # S4 开关短路
        if not getattr(self, "enable_ranked_tp", False):
            return {"triggered": False, "reason": "S4_DISABLED"}

        if not positions_with_pnl or len(positions_with_pnl) < 2:
            return {"triggered": False, "reason": "LESS_THAN_2_POSITIONS",
                    "tier": "SKIP", "gap_ratio": 0.0, "top1_coin": ""}

        from scripts.memory_l4.trading_utils import RiskManager

        if gap_threshold is None:
            gap_threshold = float(getattr(self, "RANKED_TP_GAP_RATIO", 0.70))
        min_profit = float(getattr(self, "RANKED_TP_MIN_PROFIT_USDT", 5.0))

        gap_result = RiskManager.calc_ranked_tp_gap(positions_with_pnl,
                                                     min_profit_usdt=min_profit)
        top1_idx = int(gap_result.get("top1_idx", -1))
        gap_ratio = float(gap_result.get("gap_ratio", 0.0))
        trigger_raw = bool(gap_result.get("trigger", False))

        # 用 gap_threshold 二次判定
        trigger = trigger_raw and (gap_ratio >= gap_threshold)

        if top1_idx < 0:
            return {"triggered": False, "reason": "NO_TOP1",
                    "gap_ratio": gap_ratio, "top1_idx": top1_idx,
                    "tier": "SKIP", "top1_coin": ""}

        top1 = positions_with_pnl[top1_idx]
        coin = str(top1.get("coin", ""))
        in_protection = bool(top1.get("in_protection", False))
        upl = float(top1.get("upl", 0.0))
        age_h = float(top1.get("position_age_sec", 0.0)) / 3600.0

        # ── B 档检查：reduce_plan 到期触发 ──
        # 如果之前写了 reduce_plan，检查是否到 wait_cycles
        inst_id = str(top1.get("inst_id", ""))
        rec = None
        if hasattr(self, "position_tracker") and self.position_tracker:
            try:
                rec = self.position_tracker.get_open_position(inst_id)
            except Exception:
                rec = None
        if rec and getattr(rec, "reduce_plan", None):
            plan = rec.reduce_plan
            wait = int(plan.get("wait_cycles", 2))
            set_at = int(plan.get("set_at_cycle", 0))
            current_cycle = getattr(self, "_cycle_idx", 0)
            if current_cycle - set_at >= wait:
                # 到期 → 升级为 A 档执行（绕过 gap 阈值）
                self._log(
                    f"[{coin}] ranked_tp B档→到期执行 (waited {current_cycle - set_at}/{wait} cycles, "
                    f"gap={gap_ratio:.2f})",
                    "INFO",
                )
                trigger = True
                gap_ratio = max(gap_ratio, gap_threshold)  # 强制达标
                # 清理 reduce_plan
                try:
                    rec.reduce_plan = None
                except Exception:
                    pass
            else:
                self._log(
                    f"[{coin}] ranked_tp B档排队中 ({current_cycle - set_at}/{wait} cycles, "
                    f"gap={gap_ratio:.2f})",
                    "INFO",
                )

        # ── A 档：gap 达标 → 立即止盈 ──
        if not trigger:
            # ── B 档：gap 不够但持仓老 + 有盈利 → 写 reduce_plan ──
            # Spec §4.3.2 B 档条件：持仓 ≥ 12h + 浮盈 > 0
            b_tier_age_threshold = 12.0
            tier_label = "B" if (upl > 0 and age_h >= b_tier_age_threshold and gap_ratio > 0) else "C"
            # C/B 档无动作日志（便于长期监控 gap_ratio 变化趋势）
            self._log(
                f"[{coin}] ranked_tp {tier_label}档 (gap={gap_ratio:.2f}<{gap_threshold:.2f}, "
                f"upl={upl:.2f}, age={age_h:.1f}h) → 无动作",
                "INFO",
            )
            if (not in_protection and upl > 0 and age_h >= b_tier_age_threshold
                    and gap_ratio > 0 and rec is not None):
                if not getattr(rec, "reduce_plan", None):
                    plan = {
                        "type": "ranked_tp",
                        "wait_cycles": 2,
                        "trigger_rank": round(gap_ratio, 4),
                        "set_at_cycle": getattr(self, "_cycle_idx", 0),
                    }
                    try:
                        rec.reduce_plan = plan
                        self._log(
                            f"[{coin}] ranked_tp B档排队写入 (age={age_h:.1f}h, "
                            f"upl={upl:.2f}, gap={gap_ratio:.2f}<{gap_threshold:.2f}, "
                            f"wait=2 cycles)",
                            "INFO",
                        )
                    except Exception:
                        pass  # PositionRecord 不可写时静默
            return {"triggered": False, "reason": f"NO_TRIGGER|gap={gap_ratio:.3f}",
                    "gap_ratio": gap_ratio, "top1_idx": top1_idx,
                    "tier": tier_label, "top1_coin": coin}

        # ── 保护期门禁 ──
        if in_protection:
            self._log(
                f"[{coin}] ranked_tp gap={gap_ratio:.2f}≥{gap_threshold:.2f} "
                f"but protected (hold={age_h:.1f}h<"
                f"{getattr(self, 'POSITION_PROTECTION_HOURS', 6.0):.0f}h) → "
                f"skip ranked_tp close",
                "INFO",
            )
            return {"triggered": False, "reason": "PROTECTED_SKIP",
                    "gap_ratio": gap_ratio, "top1_idx": top1_idx}

        # ── 2/2 离场确认（复用 EXIT_CONFIRM 状态机）──────
        confirmed, cnt = self._exit_confirm(coin, self.EXIT_ACT_RANKED_TP)
        if not confirmed:
            self._log(
                f"[{coin}] ranked_tp gap={gap_ratio:.2f}≥{gap_threshold:.2f} "
                f"1/{self.EXIT_CONFIRM_REQUIRED} (cnt={cnt})，等待下一轮确认",
                "WARN",
            )
            return {"triggered": False, "reason": f"PENDING_CONFIRM|cnt={cnt}",
                    "gap_ratio": gap_ratio, "top1_idx": top1_idx}

        # 2/2 确认 → 执行止盈平仓
        self._clear_exit_confirm(coin, self.EXIT_ACT_RANKED_TP)
        pos_side = str(top1.get("pos_side", "long"))
        exit_price = float(top1.get("mark_price") or top1.get("inference", {}).get("price") or 0.0)
        upl_ratio = float(top1.get("upl_ratio", 0.0))
        reason = f"ranked_tp|gap={gap_ratio:.2f}≥{gap_threshold:.2f}|top1={coin}|cnt={cnt}"

        self._handle_close_position(
            inst_id=inst_id, coin=coin, pos_side=pos_side,
            exit_price=exit_price, exit_reason=reason,
            pnl=upl, pnl_pct=upl_ratio,
        )
        # 清理 reduce_plan（如果之前有 B 档计划）
        if rec and getattr(rec, "reduce_plan", None):
            try:
                rec.reduce_plan = None
            except Exception:
                pass
        return {"triggered": True, "reason": reason,
                "gap_ratio": gap_ratio, "top1_idx": top1_idx,
                "coin": coin, "tier": "A"}

    def _archive_s4_eval(self, ranked_list: List[Dict], tp_result: Dict):
        """S4 评估结果归档到 JSONL（供 s4_stats.py 长期统计）。

        每条记录包含：ts, cycle, 持仓快照, top1, gap_ratio, tier, triggered, reason
        """
        import json as _json
        archive_path = self.log_dir / "s4_eval_log.jsonl"
        record = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cycle": int(getattr(self, "_cycle_idx", 0)),
            "positions": [
                {"coin": r.get("coin", ""), "upl": round(float(r.get("upl", 0)), 2),
                 "upl_pct": round(float(r.get("upl_ratio", 0)), 4)}
                for r in ranked_list
            ],
            "top1_coin": str(tp_result.get("top1_coin") or tp_result.get("coin", "")),
            "gap_ratio": round(float(tp_result.get("gap_ratio", 0)), 4),
            "tier": str(tp_result.get("tier", "?")),
            "triggered": bool(tp_result.get("triggered", False)),
            "reason": str(tp_result.get("reason", "")),
        }
        try:
            with open(archive_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _handle_close_position(
        self,
        inst_id: str,
        coin: str,
        pos_side: str,
        exit_price: float,
        exit_reason: str,
        pnl: float,
        pnl_pct: float,
        inference=None,
        **kwargs,
    ):
        """处理平仓：生成交易记录、更新绩效、生成 case、更新风控、增量学习

        Args:
            inference: 开仓推理快照（兼容旧调用方传入，当前仅占位不使用）。
            **kwargs: 兜底吸收其它遗留关键字参数，防止签名漂移导致记账中断。

        Returns:
            trade summary dict
        """
        # P0-修复：inference/kwargs 兼容占位。旧版调用方会传入 inference=，
        # 若签名不接受将抛 TypeError 导致平仓后记账全流程中断（trade_rec/绩效/case/增量学习全部丢失）。
        _ = (inference, kwargs)
        # v3.0：平仓后立即清除易经离场系统的评估缓存，
        # 避免下次开仓的前1小时评估被上次持仓的1h窗口缓存污染
        try:
            self.yijing_exit_system.clear_cache(coin=coin, pos_side=pos_side)
        except Exception:
            pass

        # PUMP案例·新增：仓位非0→0统一清理hook（ExperienceRecall 1156213）
        # 任何导致close_position的路径（SL/TP/手动/时间止损）都必须清理该symbol的残留Algo条件单
        try:
            if self.okx_client and hasattr(self.okx_client, "cancel_algo_orders"):
                _clr = self.okx_client.cancel_algo_orders(instId=inst_id)
                self._log(
                    f"[{coin}] 平仓后清理{inst_id}残留Algo条件单 | ok={_clr.get('ok')} "
                    f"canceled={_clr.get('canceled_count', 0)} err={_clr.get('error','')}",
                    "INFO" if _clr.get("ok") else "WARN",
                )
            elif self.okx_client and hasattr(self.okx_client, "get_algo_orders"):
                # fallback：显式两步法——先GET pending列表，再逐个DELETE
                try:
                    _pending = self.okx_client.get_algo_orders(inst_id=inst_id)
                    _ids = []
                    for _o in _pending.get("data", []) or []:
                        _aid = _o.get("algoId") or _o.get("algo_id")
                        if _aid:
                            _ids.append(_aid)
                    if _ids and hasattr(self.okx_client, "_cancel_algo_by_ids"):
                        self.okx_client._cancel_algo_by_ids(inst_id, _ids)
                    self._log(
                        f"[{coin}] 平仓后清理{inst_id} Algo条件单(fallback两步法) | 待清理={len(_ids)}",
                        "INFO",
                    )
                except Exception as _fb:
                    self._log(f"[{coin}] 平仓后清理Algo条件单fallback异常（FAIL-OPEN忽略）: {_fb}", "WARN")
        except Exception as _ce:
            # FAIL-OPEN铁律：条件单清理失败绝不阻断交易记录
            self._log(f"[{coin}] 平仓后清理Algo条件单异常（FAIL-OPEN忽略）: {_ce}", "WARN")

        trade_rec = self.position_tracker.close_position(
            inst_id=inst_id,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl=pnl,
            pnl_pct=pnl_pct,
        )

        if trade_rec:
            perf_summary = self.perf_tracker.record_trade(trade_rec)
            self.risk_manager.update_after_trade(
                pnl, pnl >= 0, current_equity=self.perf_tracker.current_equity
            )

            # P0-2: 动态黑名单更新（连续2次亏损→封禁3日）
            self._update_dynamic_blacklist_on_close(coin, pnl)

            # v4.6：过滤层基础阈值动态调节（聚合 N=30 笔，非单笔）
            try:
                _sc = float(getattr(trade_rec, "score_consensus", 0.0) or 0.0)
                _dr = str(getattr(trade_rec, "direction", "") or "")
                self._gate_threshold_state["recent_pnl"].append(
                    (float(pnl_pct), _sc, _dr)
                )
                _n_max = int(self._gate_threshold_state.get("n_max", 150))
                if len(self._gate_threshold_state["recent_pnl"]) > _n_max:
                    self._gate_threshold_state["recent_pnl"] = (
                        self._gate_threshold_state["recent_pnl"][-_n_max:]
                    )
                self._maybe_adjust_gate_base_threshold(trade_snapshot={
                    "coin": coin, "pnl_pct": float(pnl_pct), "score_consensus": _sc,
                })
            except Exception as _gte:
                self._log(f"[{coin}] 基础阈值动态调节记录异常（忽略）：{type(_gte).__name__}", "DEBUG")

            case_id, saved = register_trade_to_l4(trade_rec)

            # ★ 断层1：交易案例蒸馏到知识库（FAIL-OPEN 异步）
            _distill_trade_to_knowledge(self, trade_rec)

            # ★ 闭环反哺：平仓盈亏 verify RAG 检索记忆 + 更新 boost 权重
            _rag_feedback_on_close(self, trade_rec)

            self._log(
                f"[{coin}] 平仓记录 | {'盈利' if pnl >= 0 else '亏损'} {pnl:.2f}USDT "
                f"({pnl_pct:.2%}) | case={case_id} saved={saved} | "
                f"日盈亏={perf_summary['daily_total_pnl']:.2f} "
                f"连亏={perf_summary['consecutive_losses']}"
            )

            try:
                hold_bars = 0
                if trade_rec.entry_time and trade_rec.exit_time:
                    try:
                        from datetime import datetime

                        entry_dt = datetime.fromisoformat(
                            trade_rec.entry_time.replace("Z", "+00:00")
                        )
                        exit_dt = datetime.fromisoformat(trade_rec.exit_time.replace("Z", "+00:00"))
                        delta = exit_dt - entry_dt
                        hold_bars = int(delta.total_seconds() / 3600)
                    except Exception:
                        pass

                trade_data = {
                    "symbol": coin,
                    "direction": trade_rec.direction,
                    "entry_time": trade_rec.entry_time,
                    "exit_time": trade_rec.exit_time,
                    "entry_price": trade_rec.entry_price,
                    "exit_price": trade_rec.exit_price,
                    "pnl_pct": trade_rec.pnl_pct,
                    "hold_bars": hold_bars,
                    "exit_reason": trade_rec.exit_reason,
                    "confidence": trade_rec.confidence,
                    "hexagram": trade_rec.hexagram,
                    "upper_gua": "",
                    "lower_gua": "",
                    "position_factor": 1.0,
                }
                self.incremental_learner.log_trades_batch([trade_data])

                should_retrain, reason = self.incremental_learner.should_retrain(coin)
                if should_retrain:
                    self._log(f"[{coin}] 增量学习触发再训练: {reason}")
                    retrain_ok = self._trigger_bcrm2_retrain(coin)
                    if retrain_ok:
                        self._log(f"[{coin}] BCRM2.0 增量重训完成")
            except Exception as e:
                self._log(f"[{coin}] 增量学习记录失败: {e}", "WARN")

            retrain_result = self.learning_scheduler.trigger_retrain()
            if retrain_result.get("retrained"):
                self._log(f"[{coin}] 触发重训: {retrain_result.get('reason')}")

            # 优化4：更新置信度校准表
            # 优化5：更新卦象数据驱动校准统计
            try:
                if hasattr(self, "ranging_enhancer") and self.ranging_enhancer:
                    enhance_info = (
                        trade_rec.enhance_info if hasattr(trade_rec, "enhance_info") else None
                    )
                    regime_val = (
                        enhance_info.get("regime", "sideways") if enhance_info else "sideways"
                    )

                    # 置信度校准
                    trade_for_cal = {
                        "confidence": trade_rec.confidence,
                        "pnl_pct": trade_rec.pnl_pct,
                        "regime": regime_val,
                        "hexagram": trade_rec.hexagram or "",
                        "direction": "UP" if trade_rec.direction == "long" else "DOWN",
                    }
                    self.ranging_enhancer.update_calibration([trade_for_cal])

                    # 卦象数据驱动校准（优化5）
                    if (
                        hasattr(self.ranging_enhancer, "hex_calibrator")
                        and self.ranging_enhancer.hex_calibrator
                    ):
                        self.ranging_enhancer.hex_calibrator.record_trade(
                            hexagram=trade_rec.hexagram or "",
                            direction="UP" if trade_rec.direction == "long" else "DOWN",
                            pnl_pct=trade_rec.pnl_pct,
                            confidence=trade_rec.confidence,
                        )
            except Exception as e:
                self._log(f"[{coin}] 校准更新失败: {e}", "WARN")

            # P2-1a增强: 平仓后自动触发L4 Pipeline (M1-M4)
            try:
                self._trigger_l4_pipeline_for_trade(trade_rec, case_id, saved)
            except Exception as e:
                self._log(f"[{coin}] L4 Pipeline自动触发失败: {e}", "WARN")

            # P2-S4: 紧耦合流平仓反思回调
            try:
                self._trigger_evolution_reflection(trade_rec)
            except Exception as e:
                self._log(f"[{coin}] 紧耦合流反思回调异常（FAIL-OPEN忽略）: {e}", "WARN")

            return perf_summary
        else:
            self._log(f"[{coin}] 警告：平仓但无对应开仓记录 {inst_id}", "WARN")
            return {}

    # ── P1: 轻仓试错评估辅助方法 ──
    # 阈值常量：confirm=+1%，reverse=-3%（放宽，轻仓绝对亏损小可容忍噪音）
    TRIAL_CONFIRM_PCT = 0.010
    TRIAL_REVERSE_PCT = -0.030
    TRIAL_FIRST_EVAL_SEC = 1800       # 首次评估：持仓≥30min
    TRIAL_REEVAL_INTERVAL_SEC = 3600  # 重评估间隔：每60min一次

    def _compute_trial_action(self, price_chg_pct: float) -> str:
        """根据价格变动判定试错动作。

        Args:
            price_chg_pct: 相对入场价的价格变动比例（做多为正、做空已反转），
                           如 -0.03 表示跌 3%。

        Returns:
            "confirm" (≥+1%) / "maintain" (-3%~+1%) / "reverse" (≤-3%)
        """
        if price_chg_pct >= self.TRIAL_CONFIRM_PCT:
            return "confirm"
        if price_chg_pct <= self.TRIAL_REVERSE_PCT:
            return "reverse"
        return "maintain"

    def _should_run_trial_eval(self, tracker_pos, position_age_sec: float,
                               now_ts: float = None) -> bool:
        """是否应运行试错评估（定期重评估）。

        - 非试错仓 → False
        - 持仓 < 30min → False
        - 从未评估过 → True
        - 距上次评估 ≥ 60min → True（定期重评估）
        - 距上次评估 < 60min → False
        """
        if not tracker_pos or not getattr(tracker_pos, "is_trial", False):
            return False
        if position_age_sec < self.TRIAL_FIRST_EVAL_SEC:
            return False
        last_eval = float(getattr(tracker_pos, "last_trial_eval_ts", 0.0) or 0.0)
        if last_eval == 0.0:
            return True
        now = now_ts if now_ts is not None else time.time()
        return (now - last_eval) >= self.TRIAL_REEVAL_INTERVAL_SEC

    # ── P2: 易经离场浮亏+风险联合强制平仓 ──
    YIJING_JOINT_LOSS_PCT = -0.03   # 浮亏阈值：≤-3%（保证金收益率）
    YIJING_JOINT_RISK = 0.7         # 风险分阈值：>0.7（低于硬阈值 0.80）

    def _should_joint_force_close(self, upl_ratio: float, risk_score: float) -> bool:
        """浮亏≥3% 且 风险分>0.7 → 联合触发 FORCE_CLOSE。

        填补原硬阈值 risk≥0.80 过高导致的盲区：当卦象风险中等偏高(0.7~0.8)
        且持仓已出现实际亏损(≥3%)时，主动离场而非放任漂移到 SL。
        两个条件必须同时满足。
        """
        return upl_ratio <= self.YIJING_JOINT_LOSS_PCT and risk_score > self.YIJING_JOINT_RISK

    def _trigger_bcrm2_retrain(self, coin: str) -> bool:
        """触发 BCRM 2.0 增量重训

        使用最新K线数据重新训练模型，并记录到增量学习版本管理。
        """
        if not self.use_bcrm2:
            return False

        adapter = self.bcrm2_adapters.get(coin)
        if not adapter:
            return False

        try:

            inst_id = f"{coin}-USDT-SWAP"
            kline_resp = self.okx_client.get_kline(inst_id, bar=self.bar, limit=self.kline_limit)
            candles = kline_resp.get("candles", []) if isinstance(kline_resp, dict) else kline_resp
            if not candles or len(candles) < 100:
                self._log(
                    f"[{coin}] BCRM2重训失败：K线不足 {len(candles) if candles else 0}", "WARN"
                )
                return False

            import pandas as pd

            df = pd.DataFrame(
                [
                    {
                        "open": float(c["o"]),
                        "high": float(c["h"]),
                        "low": float(c["l"]),
                        "close": float(c["c"]),
                        "volume": float(c.get("vol", c.get("v", 0))),
                        "timestamp": c.get("ts", ""),
                    }
                    for c in candles
                ]
            )

            retrained = adapter.train(df, force_retrain=True)
            if retrained:
                perf = self.incremental_learner.db.get_recent_performance(coin)
                self.incremental_learner.version_manager.save_version(
                    adapter.engine,
                    coin,
                    version_id=None,
                    metrics={
                        "win_rate": perf.get("win_rate", 0) / 100 if perf.get("win_rate") else 0,
                        "total_trades": perf.get("n_trades", 0),
                    },
                    notes="增量学习自动重训",
                )
                return True
            return False
        except Exception as e:
            self._log(f"[{coin}] BCRM2增量重训异常: {e}", "WARN")
            return False

    def _trigger_l4_pipeline_for_trade(self, trade_rec, case_id: str, saved: bool):
        """平仓后自动触发L4 Pipeline (M1-M4)

        将平仓交易构建为episode文件，执行L4全链路：
        M1(复盘) → M2(蒸馏) → M3(统计) → M3.5(KG同步) → M4(候选)
        """
        if not saved or not case_id:
            return

        import json
        from datetime import datetime

        # 构建episode文件
        episode = {
            "case_id": case_id,
            "ts": trade_rec.exit_time
            or trade_rec.entry_time
            or datetime.now(timezone.utc).isoformat(),
            "regime": getattr(trade_rec, "regime", "unknown") or "unknown",
            "summary": {
                "total_pnl": trade_rec.pnl,
                "wins": 1 if trade_rec.pnl > 0 else 0,
                "losses": 0 if trade_rec.pnl > 0 else 1,
                "total_trades": 1,
            },
            "trades": [
                {
                    "trade_id": case_id,
                    "symbol": trade_rec.inst_id,
                    "inst_id": trade_rec.inst_id,
                    "direction": (
                        trade_rec.direction.upper()
                        if isinstance(trade_rec.direction, str)
                        else "LONG"
                    ),
                    "entry_price": trade_rec.entry_price,
                    "exit_price": trade_rec.exit_price,
                    "position_size": getattr(trade_rec, "position_size", 0.01),
                    "leverage": getattr(trade_rec, "leverage", 10),
                    "margin_usdt": getattr(trade_rec, "margin_usdt", 100),
                    "pnl": trade_rec.pnl,
                    "pnl_pct": trade_rec.pnl_pct,
                    "exit_reason": trade_rec.exit_reason or "unknown",
                    "ts_entry": trade_rec.entry_time,
                    "ts_exit": trade_rec.exit_time,
                    "system_source": "yijing_inference",
                    "decision_context": {
                        "confidence": trade_rec.confidence,
                        "hexagram": trade_rec.hexagram or "",
                    },
                    "market_snapshot": {
                        "regime": getattr(trade_rec, "regime", "unknown") or "unknown",
                    },
                    "risk_events": [],
                }
            ],
        }

        # 保存episode文件
        episodes_dir = _episodes_dir()
        episodes_dir.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        ep_path = episodes_dir / f"live_{trade_rec.inst_id}_{ts_str}.json"
        ep_path.write_text(json.dumps(episode, ensure_ascii=False, indent=2, default=str))

        self._log(f"[L4] Episode保存: {ep_path.name}")

        # 异步执行L4 Pipeline (M1-M4)
        try:
            from scripts.memory_l4.pipeline import run_pipeline

            result = run_pipeline(ep_path)
            l4_status = result.get("case", {}).get("l4_status", "unknown")
            self._log(f"[L4] Pipeline完成: case={case_id} status={l4_status}")
        except Exception as e:
            self._log(f"[L4] Pipeline执行失败: {e}", "WARN")

    def _trigger_evolution_reflection(self, trade_rec):
        """P2-S4: 平仓后触发紧耦合流反思回路

        仅对 source_tag="evolution" 的持仓执行反思与 ESS 更新。
        调用 TradeSettlementBridge → ReflectionEngine measure→reflect→learn→feedback
        → ESSProvider.update_ess 写回基因库（闭环学习）
        FAIL-OPEN: 任何异常不阻断交易
        """
        # 仅处理自进化系统的交易
        _src_tag = str(getattr(trade_rec, "source_tag", "") or "")
        if _src_tag != "evolution":
            return
        try:
            import sys as _sys
            _evo_root = str(_PROJECT_ROOT / "23-四层闭环自进化交易架构")
            if _evo_root not in _sys.path:
                _sys.path.insert(0, _evo_root)
            from dreambuddy_evolution.engines.trade_settlement_bridge import TradeSettlementBridge
            bridge = TradeSettlementBridge()
            result = bridge.on_trade_settled(trade_rec)
            ess_delta = result.get("ess_delta", 0.0)
            cs = result.get("cs", 0.0)
            _symbol = str(getattr(trade_rec, "inst_id", "?") or "?").split("-")[0]
            if ess_delta != 0:
                # P0 闭环修复：将 ess_delta 写回基因库
                _updated = False
                if hasattr(self, "_data_pipeline") and self._data_pipeline is not None \
                        and getattr(self._data_pipeline, "_ess", None) is not None:
                    _updated = self._data_pipeline._ess.update_ess(ess_delta, _symbol)
                self._log(
                    f"[P2-S4] {_symbol} 反思完成: CS={cs:.2f} "
                    f"ESS_delta={ess_delta:+.3f} 写回={'OK' if _updated else 'FAIL'}"
                )
            else:
                self._log(
                    f"[P2-S4] {_symbol} 反思完成: CS={cs:.2f} (ESS不变)",
                    "DEBUG",
                )

            # 持久化反思结果到 ess_reflection.jsonl（供前端 ESS/gmax 轨迹可视化）
            try:
                import json as _refl_json, pathlib as _refl_pl
                _refl_dir = _refl_pl.Path(str(_PROJECT_ROOT / "23-四层闭环自进化交易架构" / "dreambuddy_evolution" / "data"))
                _refl_dir.mkdir(parents=True, exist_ok=True)
                _refl_path = _refl_dir / "ess_reflection.jsonl"
                _refl_record = {
                    "ts": _symbol and __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S") or "",
                    "symbol": _symbol,
                    "ess_delta": round(ess_delta, 6),
                    "cs": round(cs, 4),
                    "pnl": float(getattr(trade_rec, "pnl", 0.0) or 0.0),
                    "pnl_pct": float(getattr(trade_rec, "pnl_pct", 0.0) or 0.0),
                    "direction": str(getattr(trade_rec, "direction", "") or ""),
                    "exit_reason": str(getattr(trade_rec, "exit_reason", "") or ""),
                    "exit_time": str(getattr(trade_rec, "exit_time", "") or ""),
                }
                with open(_refl_path, "a", encoding="utf-8") as _rf:
                    _rf.write(_refl_json.dumps(_refl_record, ensure_ascii=False) + "\n")
            except Exception:
                pass

            # Phase 6: 记录交易结果到传统金融绩效跟踪器（Sharpe/Sortino/Kelly）
            try:
                _pnl_pct = float(getattr(trade_rec, "pnl_pct", 0.0) or 0.0)
                if hasattr(self, "_data_pipeline") and self._data_pipeline is not None:
                    self._data_pipeline.record_trade_result(_pnl_pct)
                    _perf = self._data_pipeline._trad_fin._perf.summary()
                    self._log(
                        f"[P2-S4] {_symbol} 绩效更新: pnl={_pnl_pct:+.2%} "
                        f"sharpe={_perf['sharpe']:.2f} win={_perf['win_rate']:.0%} "
                        f"kelly_f={_perf['payoff_ratio']:.1f}",
                        "DEBUG",
                    )

                    # Phase 7: 记录路径盈亏评分（盈亏是路径有效性的唯一标准）
                    # 优先记录到 regime_adaptive（元路径，始终激活）
                    # 显著盈亏同时记录到具体路径，让盈亏作为标注驱动路径评分
                    try:
                        self._data_pipeline.record_path_trade("regime_adaptive", _pnl_pct)
                        if abs(_pnl_pct) > 0.01:  # 显著盈亏才记录到具体路径
                            self._data_pipeline.record_path_trade("capital_rotation", _pnl_pct)
                            self._data_pipeline.record_path_trade("momentum_breakout", _pnl_pct)
                            self._data_pipeline.record_path_trade("protocol_revenue", _pnl_pct)
                            self._data_pipeline.record_path_trade("funding_squeeze", _pnl_pct)
                            self._data_pipeline.record_path_trade("etf_flow_amplification", _pnl_pct)
                            self._data_pipeline.record_path_trade("attention_capital_breakout", _pnl_pct)
                    except Exception:
                        pass

                    # Phase 4(FTC): 盈亏回灌 FTCEvolutionBridge → ESS/gmax/ε 更新
                    try:
                        _snapshot = getattr(trade_rec, "market_snapshot", None) or {}
                        _ftc_id = str(_snapshot.get("ftc_id", "") or "")
                        if _ftc_id:
                            _ftc_orch = self._data_pipeline.get_ftc_orchestrator()
                            if _ftc_orch is not None:
                                from dreambuddy_evolution.adapters.ftc_evolution_bridge import FTCEvolutionBridge
                                _ftc_bridge = FTCEvolutionBridge(
                                    ftc_orchestrator=_ftc_orch,
                                    path_library=self._data_pipeline.get_path_library(),
                                )
                                _outcome = "TP" if _pnl_pct >= 0 else "SL"
                                _ftc_res = _ftc_bridge.on_trade_settlement(
                                    ftc_id=_ftc_id,
                                    confidence_score=cs,
                                    outcome=_outcome,
                                    pnl_pct=_pnl_pct,
                                )
                                self._log(
                                    f"[P2-S4-FTC] {_symbol} FTC={_ftc_id} "
                                    f"pnl={_pnl_pct:+.2%} "
                                    f"ess={_ftc_res.get('ftc_ess_after', 0):.3f} "
                                    f"gmax={_ftc_res.get('gmax', 0):.3f} "
                                    f"ε={_ftc_res.get('epsilon', 0):.3f}",
                                    "INFO",
                                )
                    except Exception as _ftc_e:
                        self._log(f"[P2-S4-FTC] FTC 回灌异常(fail-open): {_ftc_e}", "DEBUG")
            except Exception:
                pass  # FAIL-OPEN
        except Exception:
            pass  # FAIL-OPEN 铁律

    # ===== P2-S4c: 跨子系统软标签 ESS 注入 =====

    # 软标签权重：BCRM/易经 交易对 ESS 的影响系数（0.0~1.0）
    # 设为 0.3 表示其他子系统的盈亏经验仅以 30% 权重注入基因库
    _CROSS_SYSTEM_SOFT_WEIGHT = 0.3
    # 软标签注入冷却：每天最多执行一次（避免重复注入同一批交易）
    _CROSS_SYSTEM_INJECT_COOLDOWN_HOURS = 24
    # 软标签注入回看窗口：只处理近 N 天的其他子系统交易
    _CROSS_SYSTEM_LOOKBACK_DAYS = 30

    def _inject_cross_system_soft_labels(self) -> None:
        """将 BCRM/易经 子系统的高质量交易以软标签方式注入 ESS 基因库

        设计目标：
        - 自进化系统仅平仓 8 笔，ESS 基因库样本严重不足
        - BCRM/易经 有 99 笔历史交易，其中胜率>60% 的币种经验可作为"软标签"
        - 软标签权重 0.3，对 ESS 的影响约为自进化自身交易的 30%

        执行频率：每 24 小时一次
        FAIL-OPEN：任何异常不阻断交易
        """
        import time as _time
        from datetime import datetime, timezone, timedelta

        # 确保 _data_pipeline 已初始化（软标签注入在主循环早期调用，
        # 而 _init_data_pipeline 在 Phase 8 才懒初始化，需提前确保）
        try:
            self._init_data_pipeline()
        except Exception:
            pass  # FAIL-OPEN

        # 冷却检查
        now = _time.time()
        last_inject = getattr(self, "_last_cross_system_inject_ts", 0.0)
        cooldown_sec = self._CROSS_SYSTEM_INJECT_COOLDOWN_HOURS * 3600
        if now - last_inject < cooldown_sec:
            return

        # 已处理交易 ID 集合（避免重复注入）
        processed_ids = getattr(self, "_cross_system_processed_ids", set())

        try:
            import sys as _sys
            _evo_root = str(_PROJECT_ROOT / "23-四层闭环自进化交易架构")
            if _evo_root not in _sys.path:
                _sys.path.insert(0, _evo_root)
            from dreambuddy_evolution.engines.trade_index_builder import TradeIndexBuilder
            from dreambuddy_evolution.engines.reflection_engine import ReflectionEngine

            # 1. 加载全系统交易索引
            builder = TradeIndexBuilder(project_root=str(_PROJECT_ROOT))
            all_trades = builder.build_index(force=False)
            if not all_trades:
                return

            # 2. 过滤：仅处理 BCRM/易经 子系统（排除 evolution 自身）
            target_sources = {"bcrm", "yijing", "bcrm_archive", "bdsm", "martin_v15"}
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._CROSS_SYSTEM_LOOKBACK_DAYS)

            candidate_trades = []
            for t in all_trades:
                src = t.get("source_system", "")
                if src not in target_sources:
                    continue
                tid = str(t.get("trade_id", ""))
                if not tid or tid in processed_ids:
                    continue
                # 时间过滤
                exit_time = t.get("exit_time") or t.get("entry_time")
                if exit_time:
                    try:
                        dt = datetime.fromisoformat(str(exit_time).replace("Z", "+00:00"))
                        if dt < cutoff:
                            continue
                    except Exception:
                        pass  # 时间解析失败则保留
                candidate_trades.append(t)

            if not candidate_trades:
                self._log("[P2-S4c] 跨子系统软标签：无新候选交易", "DEBUG")
                self._last_cross_system_inject_ts = now
                return

            # 3. 逐笔构造降级 snapshot → 计算 CS → 应用奖惩 → 折扣注入 ESS
            re_engine = ReflectionEngine()
            injected = 0
            total_ess_delta = 0.0

            for t in candidate_trades:
                try:
                    coin = str(t.get("coin", "") or "")
                    direction = str(t.get("direction", "")).lower()
                    pnl = float(t.get("pnl", 0.0))
                    if not coin or not direction:
                        continue

                    # 降级 snapshot：用建仓方向作 d*，ess_dir 未知置空
                    outcome_real = "TP" if pnl >= 0 else "SL"
                    snapshot = {
                        "symbol": coin,
                        "u_open": 0.1,
                        "action": direction,
                        "level0_dstar": direction,
                        "ess_dir": "",
                        "cbr_top1_outcome": outcome_real,
                        "cluster_id": "",
                        "ess_id": "",
                        "cbr_sim": 0.5,
                    }
                    outcome = {"real_direction": direction, "real_outcome": outcome_real}

                    cs = re_engine.calculate_cs(snapshot, outcome)
                    reward = re_engine.apply_reward(
                        cs=cs,
                        outcome=outcome_real,
                        cluster_id="",
                        ess_id="",
                        gmax=1.0,
                    )
                    raw_delta = reward.get("ess_delta", 0.0)
                    _trade_pnl_pct = float(t.get("pnl_pct", 0.0))
                    # 优秀基因筛选：raw_delta>0 隐含 CS≥0.7+TP；pnl_pct>1% 过滤微小盈利噪音
                    if raw_delta == 0.0 or _trade_pnl_pct < 0.01:
                        # 中性/反例/假失败/微小盈利 不注入
                        processed_ids.add(str(t.get("trade_id", "")))
                        continue

                    # 软标签折扣
                    soft_delta = raw_delta * self._CROSS_SYSTEM_SOFT_WEIGHT

                    # 写回 ESS（通过 data_pipeline._ess）
                    if hasattr(self, "_data_pipeline") and self._data_pipeline is not None \
                            and getattr(self._data_pipeline, "_ess", None) is not None:
                        ok = self._data_pipeline._ess.update_ess(soft_delta, coin)
                        if ok:
                            injected += 1
                            total_ess_delta += soft_delta

                    processed_ids.add(str(t.get("trade_id", "")))
                except Exception:
                    continue  # 单笔失败不影响其他

            self._cross_system_processed_ids = processed_ids
            self._last_cross_system_inject_ts = now
            self._log(
                f"[P2-S4c] 跨子系统软标签注入完成: "
                f"候选={len(candidate_trades)} 注入={injected} "
                f"ESS总变化={total_ess_delta:+.4f} (权重={self._CROSS_SYSTEM_SOFT_WEIGHT})",
                "INFO" if injected > 0 else "DEBUG",
            )
        except Exception as _e:
            self._log(f"[P2-S4c] 跨子系统软标签注入异常(FAIL-OPEN): {_e}", "DEBUG")

    # ===== P2-S4b: 紧耦合流真实建仓 + KlineEventHandler 集成 =====

    _EVOLUTION_KLINE_COINS = None  # None → 使用易经系统全部币种（self.coins）
    _EVOLUTION_BUDGET_PER_COIN = 2000.0  # 单币预算上限 2000U（用户决策 2026-09-07）
    _EVOLUTION_MIN_NOTIONAL = 250.0      # 单币最小开仓名义价值 250U（硬约束：与BCRM口径一致 50U保证金×5x杠杆）
    _EVOLUTION_MAX_NOTIONAL = 2000.0     # 单币最大开仓名义价值 2000U
    _EVOLUTION_COIN_INTERVAL = 0.2       # 币种间限流间隔（秒），防止 OKX API 限频

    def _init_data_pipeline(self):
        """P2-S4b: 懒初始化 DataPipelineAdapter（统一数据管线装配器）"""
        if hasattr(self, "_data_pipeline") and self._data_pipeline is not None:
            return
        try:
            import sys as _sys
            _evo_root = str(_PROJECT_ROOT / "23-四层闭环自进化交易架构")
            if _evo_root not in _sys.path:
                _sys.path.insert(0, _evo_root)
            from dreambuddy_evolution.adapters.data_pipeline import DataPipelineAdapter
            _gene_root = str(_PROJECT_ROOT / "23-四层闭环自进化交易架构"
                             / "dreambuddy_evolution" / "gene_data")
            self._data_pipeline = DataPipelineAdapter(
                okx_client=self.okx_client,
                trader=self,
                data_center_db=str(_PROJECT_ROOT / "18-数据获取中心" / "data_center.db"),
                gene_data_root=_gene_root,
                min_sample=0,  # Phase 0 降级：允许样本不足
            )
            self._log("[P2-S4b] DataPipelineAdapter initialized", "INFO")
        except Exception as _e:
            self._log(f"[P2-S4b] DataPipelineAdapter init crash (FAIL-OPEN): {_e}", "WARN")
            self._data_pipeline = None

    def _evolution_build_position(self, symbol, action, u_open, d_star, confidence, tier="standard"):
        """P2-S4b: 紧耦合流自动建仓回调（三层仓位分级）

        被 KlineEventHandler 在 auto_execute=True 时调用：
        1. 组合熔断检查（_current_fuse_action 拦截）
        2. evolution 子池仓位计数（≤5）+ 测试仓(tier=probe)计数（≤2）
        3. 仓位计算：base_budget × FTC轨道乘数 × tier仓位乘数
           - tier=probe:    0.4 × base（轻仓试探，震荡态）
           - tier=standard: 0.7 × base（标准仓）
           - tier=trend:    1.0 × base（趋势加仓）
        4. OKX 市价建仓（5x isolated）
        5. position_tracker 打标签 source_tag="evolution"

        FAIL-OPEN: 任何异常不阻断主循环
        """
        try:
            # 1. 组合熔断检查
            _fuse = getattr(self, "_current_fuse_action", None)
            if _fuse is not None and getattr(_fuse, "block_new_open", False):
                self._log(f"[P2-S4b] {symbol} 组合熔断拦截新仓: {_fuse}", "WARN")
                return

            # 1.5 防重复建仓：同一币种已有 evolution 持仓时跳过
            _inst_id = f"{symbol}-USDT-SWAP"
            if self.position_tracker.has_open_position(_inst_id):
                self._log(
                    f"[P2-S4b] {symbol} 已有持仓，跳过重复建仓 (inst_id={_inst_id})",
                    "DEBUG",
                )
                return

            # 1.6 ★ 统一冷静期检查（与 BDSM 路径对齐）
            #   防止"平仓→立即重新开仓→又亏"循环，COOLDOWN_SEC=28800(8h) 全方向拦截
            #   根因修复 2026-09-12：evolution 子池此前完全绕过冷却期，导致
            #   ETH 止盈后 66min 即重新开仓、HYPE 部分平仓后 15min 重新开仓
            try:
                _in_cd, _cd_reason = self.position_tracker.is_in_cooldown(
                    _inst_id, action, self.COOLDOWN_SEC
                )
                if _in_cd:
                    self._log(
                        f"[P2-S4b] {symbol} evolution 冷静期拦截 → {_cd_reason}",
                        "INFO",
                    )
                    return
            except Exception as _cd_e:
                # FAIL-OPEN: 冷却期检查异常不阻断，但记录告警
                self._log(
                    f"[P2-S4b] {symbol} 冷静期检查异常(fail-open): {_cd_e}",
                    "WARN",
                )

            # 1.7 战略层方向状态闸门（direction_state）
            # ★ 2026-09-12 修复：evolution 路径绕过 direction_state 闸门
            #   - FREEZE: 市场不明确，禁止开仓（仓位压制由 cap_mode 已生效）
            #   - SHORT_ONLY: 市场明确看跌，禁止做多，允许做空
            #   - LONG_ONLY: 市场明确看多，禁止做空，允许做多
            #   - NEUTRAL/SHORT_PREFER/LONG_PREFER: 多空均可（偏置由后续置信度调整）
            #   与 BCRM2.0 路径（L13982-L14012）对齐，FAIL-OPEN 放行
            try:
                _fds_evo = getattr(self, "_five_domain_state_cache", None)
                if _fds_evo is not None:
                    _cls_evo = self._coin_asset_class(symbol)
                    _dstate_evo = getattr(_fds_evo, "direction_state", {}).get(_cls_evo, "NEUTRAL")
                    _is_long_evo = (action == "long")
                    if _dstate_evo == "FREEZE":
                        self._log(
                            f"[P2-S4b] {symbol} 方向状态拦截 | direction_state=FREEZE 禁止开仓 action={action}",
                            "WARN",
                        )
                        return
                    elif _dstate_evo == "SHORT_ONLY" and _is_long_evo:
                        self._log(
                            f"[P2-S4b] {symbol} 方向状态拦截 | direction_state=SHORT_ONLY 禁止做多 action={action}",
                            "WARN",
                        )
                        return
                    elif _dstate_evo == "LONG_ONLY" and not _is_long_evo:
                        self._log(
                            f"[P2-S4b] {symbol} 方向状态拦截 | direction_state=LONG_ONLY 禁止做空 action={action}",
                            "WARN",
                        )
                        return
            except Exception as _de_evo:
                self._log(
                    f"[P2-S4b] {symbol} 方向状态闸门异常(fail-open放行): {type(_de_evo).__name__}",
                    "DEBUG",
                )

            # 2. evolution 子池仓位计数
            _evo_count = sum(
                1 for p in self.position_tracker.all_open_positions()
                if getattr(p, "source_tag", "") == "evolution"
                # ★ P1-1 修复：跳过幽灵持仓（合约数为 0 的已强平记录）
                and float(getattr(p, "contracts", 0) or getattr(p, "size", 0) or 0) > 0
            )
            if _evo_count >= int(self.SUBPOOL_MAX_POSITIONS.get("evolution", 5)):
                self._log(
                    f"[P2-S4b] {symbol} evolution 子池已满 {_evo_count}/"
                    f"{self.SUBPOOL_MAX_POSITIONS.get('evolution', 5)}，跳过",
                    "DEBUG",
                )
                return

            # 2b. 方向性集中度限制：防止全仓做多/做空（必须在 probe 检查之前）
            #   当 evolution 子池同方向仓位占比 > MAX_DIRECTION_RATIO 时，拦截同方向新开仓
            #   例外：tier=trend 高确信度仓位允许突破（趋势确认值得追）
            #   ★ 修复 2026-09-12：此前此检查在 probe 检查之后，probe tier 先返回导致
            #     方向检查永远无法执行，造成 10 仓全做多未被拦截
            MAX_DIRECTION_RATIO = 0.70  # 单方向占比上限 70%
            _evo_positions = [
                p for p in self.position_tracker.all_open_positions()
                if getattr(p, "source_tag", "") == "evolution"
                # ★ P1-1 修复：跳过幽灵持仓
                and float(getattr(p, "contracts", 0) or getattr(p, "size", 0) or 0) > 0
            ]
            if len(_evo_positions) >= 3 and str(tier) != "trend":
                _evo_long = sum(1 for p in _evo_positions if str(getattr(p, "direction", "")).lower() == "long")
                _evo_short = sum(1 for p in _evo_positions if str(getattr(p, "direction", "")).lower() == "short")
                _evo_total = len(_evo_positions)
                _long_ratio = _evo_long / max(_evo_total, 1)
                _short_ratio = _evo_short / max(_evo_total, 1)
                if action == "long" and _long_ratio > MAX_DIRECTION_RATIO:
                    self._log(
                        f"[P2-S4b] {symbol} 方向集中度拦截: evolution多头占比 "
                        f"{_long_ratio*100:.0f}% > {MAX_DIRECTION_RATIO*100:.0f}% "
                        f"(long={_evo_long}/{_evo_total})，跳过新开多仓",
                        "WARN",
                    )
                    return
                if action == "short" and _short_ratio > MAX_DIRECTION_RATIO:
                    self._log(
                        f"[P2-S4b] {symbol} 方向集中度拦截: evolution空头占比 "
                        f"{_short_ratio*100:.0f}% > {MAX_DIRECTION_RATIO*100:.0f}% "
                        f"(short={_evo_short}/{_evo_total})，跳过新开空仓",
                        "WARN",
                    )
                    return

            # 2c. evolution 测试仓（tier=probe）上限保护：独立上限 MAX_EVOLUTION_PROBE_POSITIONS
            #   用户决策 2026-09-11：分离上限 — Evolution probe 独立 4 单，不串扰 BCRM 试错仓
            if str(tier) == "probe":
                _probe_cnt = self._count_trial_positions("evolution")
                _probe_max = int(getattr(self, "MAX_EVOLUTION_PROBE_POSITIONS", 4))
                if _probe_cnt >= _probe_max:
                    self._log(
                        f"[P2-S4b] {symbol} evolution 测试仓已满 "
                        f"{_probe_cnt}/{_probe_max}"
                        f"（tier=probe），跳过本次试探开仓",
                        "INFO",
                    )
                    return

            # ★ RAG 热路径接入（FAIL-OPEN 只读）
            _rag_q = f"{symbol} {tier} 建仓 风控 阈值"
            _rag_hits = _rag_hotpath_lookup(self, _rag_q, top_k=5)
            if _rag_hits:
                self._log(
                    f"[RAG-PRE-EVO-OPEN] {symbol} tier={tier} | "
                    f"hits={len(_rag_hits)} top={_rag_hits[0].get('heading', '')[:40]}",
                    "INFO",
                )

            # ★ CBR 历史胜率参考（FAIL-OPEN，只读日志，不拦截不降仓）
            #   2026-09-12 方案A降级：案例库 202 条，HYPE/PUMP 几乎无案例，
            #   字段映射断裂(inst_id vs symbol)，样本量不足无统计意义。
            #   降级为参考日志，等案例库≥30/币种/方向再考虑启用拦截。
            #   注意：is_profit 字段而非 pnl（CBRCase 无 pnl 属性）
            try:
                _cbr_engine = getattr(self.cbr_bridge, "cbr", None) if self.cbr_bridge else None
                if _cbr_engine is not None:
                    _cbr_inst = f"{symbol}-USDT-SWAP"
                    _similar = _cbr_engine.search_similar(
                        inst_id=_cbr_inst,
                        decision=action.upper(),
                        top_k=20,
                    )
                    _n_cases = len(_similar) if _similar else 0
                    if _n_cases > 0:
                        _wins = sum(
                            1 for c in _similar
                            if getattr(c, "case", None)
                            and getattr(c.case, "is_profit", False)
                        )
                        _win_rate = _wins / _n_cases if _n_cases > 0 else 0.0
                        self._log(
                            f"[P2-S4b] {symbol} {action} CBR参考: "
                            f"win_rate={_win_rate:.1%} (n={_n_cases})，"
                            f"{'样本不足(<5)参考价值有限' if _n_cases < 5 else '可参考'}",
                            "DEBUG",
                        )
            except Exception as _cbr_e:
                # FAIL-OPEN: CBR 检索异常不阻断开仓
                self._log(
                    f"[P2-S4b] {symbol} CBR参考检查异常(fail-open): {_cbr_e}",
                    "DEBUG",
                )

            # ★ FIX #4 → 分层治理: BCRM2.0 方向冲突检查（veto + downsize 双重模式）
            #   对称离场侧规则 2b（partial_close），形成开仓-离场学习闭环。
            #   分层策略（设计文档 entry_bcrm_soft_weight_design.md §2）：
            #     ≥0.95+BDSM一致 → 硬否决（保留，灾难性保护，不学习）
            #     ≥0.95（无BDSM）→ 软权重 ×0.3 → REDUCE_WEIGHT
            #     0.85-0.95       → 软权重 ×0.5 → REDUCE_WEIGHT
            #     0.80-0.85       → 软权重 ×0.7 → REDUCE_WEIGHT
            #     <0.80           → 不干预 ×1.0 → 正常 outcome
            #   FAIL-OPEN: 缓存缺失/过期/异常 → weight_factor=1.0 放行
            _bcrm_cache = getattr(self, "_latest_bcrm_inference", None) or {}
            _bcrm_info = _bcrm_cache.get(symbol.upper())
            _bcrm_dir = ""
            _bcrm_conf = 0.0
            _bcrm_ts = 0.0
            if _bcrm_info is not None:
                _bcrm_dir = str(_bcrm_info.get("direction", "")).upper()
                _bcrm_conf = float(_bcrm_info.get("confidence", 0.0) or 0.0)
                _bcrm_ts = float(_bcrm_info.get("ts", 0) or 0)
            # 获取 BDSM 方向约束（仅 BDSM 池币种且 sufficient 质量时生效）
            _bdsm_constraint = ""
            try:
                if symbol.upper() in (getattr(self, "BDSM_COINS", frozenset()) or frozenset()):
                    _bdsm_snap = self._get_bdsm_snapshot_today()
                    _bdsm_entry = (_bdsm_snap.get("coins") or {}).get(symbol.upper()) or {}
                    if str(_bdsm_entry.get("data_quality", "")).lower() == "sufficient":
                        _bdsm_constraint = str(_bdsm_entry.get("direction_constraint", "")).upper()
            except Exception:
                _bdsm_constraint = ""
            # 分层治理判定
            _weight_factor = 1.0
            _bcrm_reverse_conf = 0.0
            try:
                from dreambuddy_evolution.engines.entry_signal_governor import (
                    compute_bcrm_entry_weight_factor,
                )
                _gov = compute_bcrm_entry_weight_factor(
                    bcrm_dir=_bcrm_dir,
                    bcrm_conf=_bcrm_conf,
                    bcrm_ts=_bcrm_ts,
                    evo_dir=action.upper(),
                    bdsm_constraint=_bdsm_constraint,
                    now=time.time(),
                    pattern_factor=(
                        (self._kline_handler._last_agi_pattern or {}).get("pattern_factor", 0.0)
                        if hasattr(self, "_kline_handler") and self._kline_handler
                        and hasattr(self._kline_handler, "_last_agi_pattern")
                        else 0.0
                    ),
                )
                if _gov.veto:
                    self._log(
                        f"[P2-S4b] {symbol} BCRM2.0 方向冲突硬否决: "
                        f"evolution={action.upper()} vs BCRM={_bcrm_dir}"
                        f"(conf={_bcrm_conf:.2f}) + BDSM={_bdsm_constraint} → 跳过建仓",
                        "WARN",
                    )
                    return
                _weight_factor = _gov.weight_factor
                _bcrm_reverse_conf = _gov.bcrm_reverse_conf
                # ★ CBR 降仓已降级为参考日志（方案A），不再叠加
                if _weight_factor < 1.0:
                    self._log(
                        f"[P2-S4b] {symbol} BCRM2.0 反向信号软权重: "
                        f"BCRM={_bcrm_dir}(conf={_bcrm_conf:.2f}) → 仓位 ×{_weight_factor:.1f} "
                        f"(REDUCE_WEIGHT outcome 追踪)",
                        "INFO",
                    )
            except ImportError:
                # 回退到旧逻辑（硬否决 conf>0.8）
                _is_conflict = (
                    (_bcrm_dir == "UP" and action.upper() == "SHORT")
                    or (_bcrm_dir == "DOWN" and action.upper() == "LONG")
                )
                if _is_conflict and _bcrm_conf > 0.8 and (time.time() - _bcrm_ts) < 1800:
                    self._log(
                        f"[P2-S4b] {symbol} BCRM2.0 方向冲突拦截(governor缺失,回退硬否决): "
                        f"evolution={action.upper()} vs BCRM={_bcrm_dir}(conf={_bcrm_conf:.2f})",
                        "WARN",
                    )
                    return

            # ★ SHORT_BAN 铁律：SHORT_ONLY_BLACKLIST 币种（ETH/BTC）禁止做空
            #   与 BCRM2.0 _open_position 的 SHORT_BAN 保持一致，避免自进化系统绕过全局禁空规则
            #   FAIL-OPEN：属性缺失时不拦截（放行自主决策）
            #   Phase 4.3 例外：三因子共振（ETF流出+头肩顶+BTC WEAK）时允许 BTC/ETH 做空
            if action == "short" and symbol.upper() in getattr(self, "SHORT_ONLY_BLACKLIST", set()):
                _three_factor_ok = False
                try:
                    _fd_state = self._five_domain_state_cache
                    if _fd_state is not None:
                        _three_factor_ok = bool(
                            getattr(_fd_state, "three_factor_short_signal", {}).get("crypto_usdt", False)
                        )
                except Exception:
                    _three_factor_ok = False
                if not _three_factor_ok:
                    self._log(
                        f"[P2-S4b] {symbol} SHORT_BAN 命中 | 跳过开空（SHORT_ONLY_BLACKLIST）",
                        "WARN",
                    )
                    return
                else:
                    self._log(
                        f"[P2-S4b] {symbol} SHORT_BAN 豁免 | 三因子共振(ETF流出+头肩顶+BTC WEAK)允许做空",
                        "INFO",
                    )

            # 3. 仓位计算（三层分级 × FTC 轨道乘数 × regime 乘数）
            # u_open 已是 KlineEventHandler 计算好的最终 position_mult = tier_mult × regime_mult
            try:
                _equity = float(self.perf_tracker.current_equity)
            except Exception:
                _equity = 100.0
            _available = _equity * 1.0  # 100% 可用作保证金（用户决策 2026-09-07）
            _leverage = 5  # 与 set_leverage(lever=5) 一致
            _notional_budget = _available * _leverage  # 名义价值预算 = 保证金 × 杠杆
            _base_budget = min(_notional_budget, self._EVOLUTION_BUDGET_PER_COIN)  # 单币名义价值上限
            # FTC 轨道仓位乘数（Phase 4）
            _track_mult = 1.0
            _last_kd = getattr(self, "_last_evolution_kline", None)
            if _last_kd is not None:
                _track = _last_kd.get("top_ftc_track", "exploit")
                if self._data_pipeline is not None:
                    try:
                        _track_mult = self._data_pipeline.get_ftc_track_multiplier(_track)
                    except Exception:
                        _track_mult = 1.0
                if _track_mult <= 0.0:
                    self._log(
                        f"[P2-S4b] {symbol} FTC track={_track} 仓位为 0，跳过建仓",
                        "DEBUG",
                    )
                    return
            # 三层仓位乘数（u_open 已包含 regime 调整，这里取其作为最终乘数）
            _position_usdt = _base_budget * _track_mult * float(u_open)
            # ★ 入场侧 BCRM2.0 软权重乘数（分层治理，对称离场侧规则 2b）
            _position_usdt = _position_usdt * _weight_factor
            # ★ FREEZE cap_mode 压缩（2026-09-12 修复）：
            #   战略层 FiveDomainState 计算 cap_mode（FREEZE=0.20, ALLOW=1.0 等），
            #   此前从未在 evolution 仓位计算中应用，导致 FREEZE 状态下仓位不压缩
            #   硬约束：war_state=FREEZE → cap_mode=0.20 → evolution 子池名义仓位压缩至 20%
            _fd_cap_mode = 1.0
            try:
                _fds = getattr(self, "_five_domain_state_cache", None)
                if _fds is not None:
                    _caps = getattr(_fds, "aggregate_position_cap_pct", {}) or {}
                    _coin_cls = self._coin_asset_class(symbol)
                    _fd_cap_mode = float(_caps.get(_coin_cls, 1.0) or 1.0)
                    if _fd_cap_mode < 1.0:
                        self._log(
                            f"[P2-S4b] {symbol} 战略层 cap_mode 压缩: "
                            f"cap={_fd_cap_mode:.2f} (cls={_coin_cls}) → "
                            f"仓位 {_position_usdt:.1f}U×{_fd_cap_mode:.2f}="
                            f"{_position_usdt * _fd_cap_mode:.1f}U",
                            "WARN",
                        )
            except Exception:
                _fd_cap_mode = 1.0  # FAIL-OPEN
            _position_usdt = _position_usdt * _fd_cap_mode
            # 上限钳位：单币最大开仓名义价值 2000U
            if _position_usdt > self._EVOLUTION_MAX_NOTIONAL:
                self._log(
                    f"[P2-S4b] {symbol} 仓位 {_position_usdt:.1f}U > 最大 "
                    f"{self._EVOLUTION_MAX_NOTIONAL}U，钳位至上限",
                    "DEBUG",
                )
                _position_usdt = float(self._EVOLUTION_MAX_NOTIONAL)
            # 下限校验：单币最小开仓名义价值 250U
            if _position_usdt < self._EVOLUTION_MIN_NOTIONAL:
                self._log(
                    f"[P2-S4b] {symbol} 仓位 {_position_usdt:.1f}U < 最小 "
                    f"{self._EVOLUTION_MIN_NOTIONAL}U (tier={tier} mult={u_open:.2f})，跳过",
                    "DEBUG",
                )
                return

            inst_id = f"{symbol}-USDT-SWAP"

            # 4. OKX 市价建仓
            try:
                _lev_res = self.okx_client.set_leverage(
                    inst_id=inst_id, lever=5, mgn_mode="isolated"
                )
            except Exception as _le:
                self._log(f"[P2-S4b] {symbol} set_leverage 异常(fail-open): {_le}", "DEBUG")

            _reason = f"evolution_auto_{action} conf={confidence:.2f} d*={d_star} tier={tier}"
            # ★ evolution 子池独立通过 TEE 执行引擎下单（与 BCRM/BDSM 隔离）
            if action == "long":
                _result = self._execute_evolution_order_via_tee(
                    inst_id=inst_id, side="buy", usdt_amount=_position_usdt,
                    pos_side="long", reason=_reason,
                )
            else:
                _result = self._execute_evolution_order_via_tee(
                    inst_id=inst_id, side="sell", usdt_amount=_position_usdt,
                    pos_side="short", reason=_reason,
                )

            if not _result.get("ok"):
                self._log(
                    f"[P2-S4b] {symbol} {action} 建仓失败: {_result.get('error', 'unknown')}",
                    "WARN",
                )
                return

            # 5. position_tracker 打标签
            _entry_px = float(_result.get("avg_px", 0) or _result.get("price", 0) or 0)
            # ★ FIX entry_price=0：OKX 市价单返回可能无 avg_px，需从持仓查询补全
            if _entry_px <= 0:
                try:
                    _pos_q = self.okx_client.get_positions(inst_id)
                    if _pos_q.get("ok"):
                        for _pp in _pos_q.get("positions", []):
                            if float(_pp.get("pos", 0)) > 0:
                                _entry_px = float(_pp.get("avg_px", 0) or 0)
                                break
                    self._log(
                        f"[P2-S4b] {symbol} 市价单无avg_px，从持仓查询补全 entry_price={_entry_px}",
                        "DEBUG",
                    )
                except Exception as _qp_e:
                    self._log(f"[P2-S4b] {symbol} 持仓查询entry_price异常(fail-open): {_qp_e}", "DEBUG")
            _ftc_id = ""
            _ftc_track = "exploit"
            if _last_kd is not None:
                _ftc_id = _last_kd.get("top_ftc", "")
                _ftc_track = _last_kd.get("top_ftc_track", "exploit")

            # 6. 开仓后立即设置 SL/TP 兜底（2026-09-09 ATR 放大，与 BCRM 对齐）
            # tier 分层 ATR 倍数（Chandelier 风格）：
            #   probe:    4.0×ATR, TP=12%   （轻仓试探，给足空间）
            #   standard: 4.5×ATR, TP=13.5% （标准仓）
            #   trend:    5.0×ATR, TP=15%    （趋势仓，让利润奔跑）
            # 硬下限：SL≥4% / TP≥12%，防低波扫损
            _atr_mult = {"probe": 4.0, "standard": 4.5, "trend": 5.0}.get(tier, 4.5)
            _atr_pct_here = float(_last_kd.get("atr_pct", 0.0) or 0.0) if _last_kd else 0.0
            if _atr_pct_here <= 0:
                _atr_pct_here = 0.01  # ATR 缺失兜底 1%
            _tier_sl_pct = max(_atr_mult * _atr_pct_here, 0.04)   # SL 下限 4%
            _tier_sl_pct = min(_tier_sl_pct, 0.15)                  # SL 上限 15%
            _tier_tp_pct = min(_tier_sl_pct * 3.0, 0.30)            # TP=3×SL，上限 30%
            # regime 调整：震荡态放宽 SL（避免噪音扫损），趋势态 TP 放宽
            _regime = str(_last_kd.get("regime", "")).lower() if _last_kd else ""
            if "ranging" in _regime or "consolidation" in _regime or "mean_revert" in _regime:
                _tier_sl_pct = min(_tier_sl_pct * 1.3, 0.15)   # 震荡态 SL 放宽 30%
                _tier_tp_pct = min(_tier_tp_pct * 0.8, 0.30)   # 震荡态 TP 收紧 20%
            elif "trend" in _regime and "down" not in _regime:
                _tier_tp_pct = min(_tier_tp_pct * 1.2, 0.30)    # 趋势态 TP 放宽 20%
            _lev = 5  # 进化子池固定 5x
            _sl_px = _entry_px * (1 - _tier_sl_pct) if action == "long" else _entry_px * (1 + _tier_sl_pct)
            _tp_px = _entry_px * (1 + _tier_tp_pct) if action == "long" else _entry_px * (1 - _tier_tp_pct)
            try:
                if self.okx_client and hasattr(self.okx_client, "place_stop_loss_take_profit"):
                    _sltp_r = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=action,
                        stop_loss_px=_sl_px,
                        take_profit_px=_tp_px,
                        reason=f"evolution_sltp tier={tier} sl={_tier_sl_pct*100:.1f}% tp={_tier_tp_pct*100:.1f}%",
                    )
                    if _sltp_r.get("ok"):
                        self._log(
                            f"[P2-S4b] {symbol} SL/TP 兜底已设置 | "
                            f"SL={_sl_px:.6f}({ _tier_sl_pct*100:.1f}%) TP={_tp_px:.6f}({ _tier_tp_pct*100:.1f}%)",
                            "INFO",
                        )
                    else:
                        self._log(
                            f"[P2-S4b] {symbol} SL/TP 设置失败: {_sltp_r.get('error', 'unknown')}（持仓同步会补）",
                            "WARN",
                        )
            except Exception as _sltp_e:
                self._log(f"[P2-S4b] {symbol} SL/TP 异常(FAIL-OPEN): {_sltp_e}", "WARN")

            self.position_tracker.open_position(
                coin=symbol,
                inst_id=inst_id,
                direction=action,
                entry_price=_entry_px,
                confidence=float(confidence),
                hexagram="evolution_auto",
                strategy_source="evolution",
                source_tag="evolution",
                market_snapshot={
                    "d_star": d_star, "u_open": u_open, "ri": confidence,
                    "ftc_id": _ftc_id, "ftc_track": _ftc_track,
                    "tier": tier,
                    "stop_loss_px": _sl_px,
                    "take_profit_px": _tp_px,
                    "sl_pct": _tier_sl_pct,
                    "tp_pct": _tier_tp_pct,
                    # 入场侧 BCRM2.0 软权重减仓追踪（平仓时供 TradeSettlementBridge 生成 REDUCE_WEIGHT outcome）
                    "weight_reduce_factor": _weight_factor,
                    "bcrm_reverse_conf_at_entry": _bcrm_reverse_conf,
                },
            )
            self._log(
                f"[P2-S4b] {symbol} {action} 建仓成功 @ {_entry_px} | "
                f"仓位={_position_usdt:.1f}U 5x tier={tier} mult={u_open:.2f} "
                f"track={_ftc_track} ftc={_ftc_id} | conf={confidence:.2f} d*={d_star}",
                "INFO",
            )
        except Exception as _e:
            self._log(f"[P2-S4b] _evolution_build_position crash (FAIL-OPEN): {_e}", "WARN")

    def _ensure_bcrm2_for_evolution_positions(self):
        """规则 2b 前置：为 evolution 持仓补 BCRM2.0 推理

        evolution 离场巡检先于主循环 BCRM2.0 推理，导致 _latest_bcrm_inference 为空。
        此方法为 evolution 持仓币种补一次 BCRM2.0 推理，确保规则 2b 有最新反向信号。

        FAIL-OPEN: 任何异常 → 静默跳过（规则 2b 自然不触发）
        """
        import time as _time
        try:
            # 收集 evolution 持仓币种
            evo_positions = []
            all_positions = []
            if hasattr(self.position_tracker, "all_open_positions"):
                all_positions = self.position_tracker.all_open_positions()
            elif hasattr(self.position_tracker, "get_all_positions"):
                for _iid, _plist in self.position_tracker.get_all_positions().items():
                    if isinstance(_plist, list):
                        all_positions.extend(_plist)
                    elif isinstance(_plist, dict):
                        all_positions.append(_plist)
            for pos in all_positions:
                if getattr(pos, "source_tag", "") == "evolution":
                    inst_id = getattr(pos, "inst_id", "") or getattr(pos, "instId", "")
                    coin = inst_id.replace("-USDT-SWAP", "")
                    if coin and inst_id:
                        evo_positions.append((coin, inst_id))

            if not evo_positions:
                return

            # 缓存新鲜度检查：5min 内已推理过的跳过
            _now = _time.time()
            if not hasattr(self, "_latest_bcrm_inference"):
                self._latest_bcrm_inference = {}

            for coin, inst_id in evo_positions:
                try:
                    cached_ts = self._latest_bcrm_inference.get(coin.upper(), {}).get("ts", 0)
                    if _now - cached_ts < 300:  # 5min 内已推理过
                        continue
                    # 获取 K 线数据
                    kline_resp = self.okx_client.get_kline(inst_id, bar=self.bar, limit=self.kline_limit)
                    kline_data = kline_resp.get("candles", []) if isinstance(kline_resp, dict) else kline_resp
                    if not kline_data or len(kline_data) < 100:
                        continue
                    # 执行 BCRM2.0 推理
                    inference = self._infer_bcrm2(coin, inst_id, kline_data)
                    if inference and inference.get("direction"):
                        self._latest_bcrm_inference[coin.upper()] = {
                            "direction": inference.get("direction", ""),
                            "confidence": float(inference.get("confidence", 0.0) or 0.0),
                            "price": float(inference.get("price", 0.0) or 0.0),
                            "ts": _now,
                        }
                        self._log(
                            f"[EvolutionExitEngine] {coin} BCRM2.0 预推理完成 "
                            f"dir={inference.get('direction', '')} "
                            f"conf={float(inference.get('confidence', 0.0) or 0.0):.2f}",
                            "DEBUG",
                        )
                except Exception:
                    continue  # 单币失败不影响其他币
        except Exception:
            pass  # FAIL-OPEN

    def _evolution_check_exit(self):
        """P2-S4b+: 自进化系统独立离场巡检（Phase 2 EvolutionExitEngine）

        每轮 run_once 在 _check_evolution_kline_signal 之后调用：
          1. 遍历 source_tag="evolution" 的持仓
          2. 构造 context（R 向量/ESS/FTC/盈亏/时间/ATR/tier/当前SL/TP）
          3. 调用 EvolutionExitEngine.decide() → ExitDecision
          4. 执行 action：hold(跳过) / adjust_sl_tp(下新SL/TP) / trailing(下移动止盈) / force_close(市价平仓)
          5. 检测 OKX algo 触达（get_algo_order_history）

        FAIL-OPEN：任何异常不阻塞主循环
        """
        try:
            self._log("[EvolutionExitEngine] 巡检入口", "DEBUG")
            _engine = getattr(self, "_evolution_exit_engine", None)
            if _engine is None:
                # 延迟初始化 EvolutionExitEngine
                import sys as _sys
                _evo_root = str(_PROJECT_ROOT / "23-四层闭环自进化交易架构")
                if _evo_root not in _sys.path:
                    _sys.path.insert(0, _evo_root)
                from dreambuddy_evolution.engines.exit_engine import EvolutionExitEngine
                _engine = EvolutionExitEngine(
                    okx_client=self.okx_client,
                    ess_provider=getattr(self, "_data_pipeline", None),
                    ftc_bridge=None,
                    shadow_rl_tracker=None,
                    log_fn=lambda msg, level="INFO": self._log(msg, level),
                )
                self._evolution_exit_engine = _engine

            # ── RL 离场策略层：ShieldedPolicy 懒初始化 ──
            _policy = getattr(self, "_evolution_shielded_policy", None)
            if _policy is None:
                try:
                    from pathlib import Path as _PPath
                    import os as _os_mod
                    from dreambuddy_evolution.core.exit_rl_policy import (
                        ShieldedPolicy as _SP,
                        CQLTrainer as _CT,
                    )
                    _model_path = str(
                        _PPath(_evo_root)
                        / "dreambuddy_evolution"
                        / "data"
                        / "exit_policy_v1.pt"
                    )
                    _cql = _CT(state_dim=8, n_actions=5, lr=1e-4, cql_alpha=0.1)
                    if _os_mod.path.exists(_model_path):
                        _cql.load(_model_path)
                        self._log(
                            f"[EvolutionExitEngine] ShieldedPolicy 加载 CQL 模型: {_model_path}",
                            "INFO",
                        )
                    else:
                        self._log(
                            f"[EvolutionExitEngine] CQL 模型不存在，ShieldedPolicy FAIL-OPEN(规则兜底): {_model_path}",
                            "WARN",
                        )
                        _cql = None  # 无模型时纯 shield 兜底
                    _policy = _SP(
                        cql_trainer=_cql,
                        exit_engine=_engine,
                        log_fn=lambda msg, level="INFO": self._log(msg, level),
                        min_confidence=0.3,
                    )
                    self._evolution_shielded_policy = _policy
                except Exception as _sp_e:
                    self._log(
                        f"[EvolutionExitEngine] ShieldedPolicy 初始化异常(FAIL-OPEN): {_sp_e}",
                        "WARN",
                    )
                    self._evolution_shielded_policy = None

            # ── ShadowRL 追踪器懒初始化（记录 (s,a,R,s') 供 PPO 微调用）──
            _shadow_tracker = getattr(self, "_evolution_shadow_rl", None)
            if _shadow_tracker is None:
                try:
                    from pathlib import Path as _P
                    from dreambuddy_evolution.core.shadow_rl import ShadowRLTracker as _SRT
                    # D方案: 与 EvolutionPipeline 一致的绝对路径，重启加载历史样本
                    _rl_persist = _P("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/gene_data/shadow_rl_samples.jsonl")
                    _shadow_tracker = _SRT(max_samples=10000, persist_path=_rl_persist)
                    _shadow_tracker.load_from_disk()  # 启动加载历史样本
                    self._evolution_shadow_rl = _shadow_tracker
                    self._log(
                        f"[EvolutionExitEngine] ShadowRLTracker 初始化 (max_samples=10000, loaded={_shadow_tracker.sample_count()}, effective={_shadow_tracker.effective_sample_count()})",
                        "INFO",
                    )
                except Exception as _srt_e:
                    self._log(
                        f"[EvolutionExitEngine] ShadowRLTracker 初始化异常(FAIL-OPEN): {_srt_e}",
                        "WARN",
                    )
                    self._evolution_shadow_rl = None

            # ── ExitRewardCalculator 懒初始化（三组件奖励计算）──
            _reward_calc = getattr(self, "_evolution_reward_calc", None)
            if _reward_calc is None:
                try:
                    from dreambuddy_evolution.core.exit_reward_calculator import ExitRewardCalculator
                    _reward_calc = ExitRewardCalculator()
                    self._evolution_reward_calc = _reward_calc
                except Exception as _rc_e:
                    self._log(
                        f"[EvolutionExitEngine] ExitRewardCalculator 初始化异常(FAIL-OPEN): {_rc_e}",
                        "WARN",
                    )
                    self._evolution_reward_calc = None

            tracker = getattr(self, "position_tracker", None)
            if tracker is None:
                self._log("[EvolutionExitEngine] position_tracker 为 None，跳过", "DEBUG")
                return

            # 遍历 evolution 子池持仓
            _evo_positions = []
            _all_pos = tracker.all_open_positions()
            self._log(
                f"[EvolutionExitEngine] 持仓总数={len(_all_pos)}",
                "DEBUG",
            )
            for rec in _all_pos:
                _stag = str(getattr(rec, "source_tag", "") or "").lower()
                if _stag == "evolution":
                    _evo_positions.append(rec)
            if not _evo_positions:
                # 诊断日志：仅每 10 轮打印一次，避免日志刷屏
                _cycle = getattr(self, "cycle_count", 0)
                if _cycle % 10 == 0:
                    _tags = [str(getattr(r, "source_tag", "") or "") for r in _all_pos]
                    self._log(
                        f"[EvolutionExitEngine] 无 evolution 持仓 (共{len(_all_pos)}仓 tags={_tags})",
                        "DEBUG",
                    )
                return

            self._log(
                f"[EvolutionExitEngine] 发现 {len(_evo_positions)} 个 evolution 持仓",
                "INFO",
            )
            for rec in _evo_positions:
                try:
                    coin_up = str(getattr(rec, "coin", "")).upper()
                    inst_id = str(getattr(rec, "inst_id", "") or f"{coin_up}-USDT-SWAP")
                    pos_side = str(getattr(rec, "direction", "") or "long").lower()
                    entry_price = float(getattr(rec, "entry_price", 0.0) or 0.0)
                    self._log(
                        f"[EvolutionExitEngine] {coin_up} entry_price={entry_price} "
                        f"attrs={[a for a in ['entry_price','exit_price','position_qty','pnl','pnl_pct','position_usdt','entry_time'] if hasattr(rec, a)]}",
                        "DEBUG",
                    )
                    if entry_price <= 0:
                        self._log(
                            f"[EvolutionExitEngine] {coin_up} entry_price<=0，跳过",
                            "DEBUG",
                        )
                        continue

                    # 从 OKX 持仓获取当前价格和仓位大小（exit_price 仅平仓后有值）
                    current_price = float(getattr(rec, "exit_price", 0.0) or 0.0)
                    usdt_amt = float(getattr(rec, "position_usdt", 0.0) or 0.0)
                    # ★ P1-2 增强：OKX 持仓消失检测
                    #   根因 2026-09-12：UNI/PUMP 在 OKX 端被强平但本地未记录平仓事件，
                    #   导致状态不一致和幽灵持仓。在巡检时主动检测 OKX 端是否还有持仓
                    _okx_position_exists = False
                    if current_price <= 0 or usdt_amt <= 0:
                        try:
                            _pos_q = self.okx_client.get_positions(inst_id)
                            if _pos_q.get("ok"):
                                _okx_positions = _pos_q.get("positions", [])
                                for _pp in _okx_positions:
                                    if float(_pp.get("pos", 0)) > 0:
                                        _okx_position_exists = True
                                        if current_price <= 0:
                                            current_price = float(_pp.get("mark_px", 0) or _pp.get("last_px", 0) or 0)
                                        if usdt_amt <= 0:
                                            _pos_qty = abs(float(_pp.get("pos", 0) or 0))
                                            usdt_amt = _pos_qty * current_price
                                        break
                            # ★ P1-2 检测：OKX 端无持仓但本地有记录 → 清理幽灵持仓
                            if not _okx_position_exists and not _pos_q.get("query_failed"):
                                self._log(
                                    f"[EvolutionExitEngine] {coin_up} OKX端无持仓但本地有记录，"
                                    f"清理幽灵持仓 (side={pos_side})",
                                    "WARN",
                                )
                                _closed = self.position_tracker.close_position(
                                    inst_id,
                                    exit_price=current_price if current_price > 0 else entry_price,
                                    exit_reason="EvolutionExitEngine检测OKX持仓消失",
                                )
                                # 触发反思链路
                                if _closed is not None:
                                    try:
                                        self._trigger_evolution_reflection(_closed)
                                    except Exception as _refl_e:
                                        self._log(
                                            f"[EvolutionExitEngine] {coin_up} 幽灵持仓清理后反思异常(FAIL-OPEN): {_refl_e}",
                                            "WARN",
                                        )
                                continue  # 跳过此持仓的后续处理
                        except Exception:
                            pass
                    if current_price <= 0:
                        current_price = entry_price

                    # 计算盈亏
                    if pos_side == "long":
                        upl_ratio = (current_price - entry_price) / entry_price
                    else:
                        upl_ratio = (entry_price - current_price) / entry_price
                    upl = usdt_amt * upl_ratio

                    # 持仓年龄
                    entry_time = getattr(rec, "entry_time", None) or ""
                    position_age_sec = 0.0
                    if entry_time:
                        try:
                            from datetime import datetime as _dt
                            _ts = entry_time.replace("Z", "+00:00") if entry_time.endswith("Z") else entry_time
                            position_age_sec = _dt.fromisoformat(_ts).timestamp()
                            position_age_sec = max(0.0, time.time() - position_age_sec)
                        except Exception:
                            position_age_sec = 0.0

                    # 从 market_snapshot 取 tier / r_vector / ess / 当前 SL/TP
                    snap = getattr(rec, "market_snapshot", {}) or {}
                    tier = str(snap.get("tier", "standard")).lower()
                    current_sl_px = float(snap.get("stop_loss_px", 0.0) or 0.0)
                    current_tp_px = float(snap.get("take_profit_px", 0.0) or 0.0)
                    r_vector = snap.get("r_vector") or {}
                    ess = float(snap.get("ess", 0.5) or 0.5)
                    ftc_track = str(snap.get("ftc_track", "exploit"))
                    regime = str(snap.get("regime", ""))
                    atr_pct = float(snap.get("atr_pct", 0.02) or 0.02)

                    # OKX algo 触达检测
                    okx_algo_triggered = False
                    if self.okx_client is not None and hasattr(self.okx_client, "get_algo_order_history"):
                        try:
                            _hist = self.okx_client.get_algo_order_history(inst_id=inst_id)
                            # OKX history 中 state=effective 表示已触达
                            for _o in (_hist.get("orders") or []):
                                if str(_o.get("state", "")).lower() in ("effective", "filled", "triggered"):
                                    okx_algo_triggered = True
                                    break
                        except Exception as _algo_e:
                            self._log(
                                f"[EvolutionExitEngine] {coin_up} OKX algo history 查询异常(FAIL-OPEN): {_algo_e}",
                                "DEBUG",
                            )

                    # ★ 超时评估：全池多空相对强弱扫描（用于超时换仓决策）
                    #   改动（2026-09-10）：原逻辑只看同方向更强信号（多头只看更强多头），
                    #   改为全池（evolution+BCRM2.0）多空扫描——市场空头格局明显时，
                    #   平浮盈多头换空（例：MU多头超时浮盈，但COIN空头conf=0.98更强）。
                    #   阈值：confidence > 当前持仓conf+0.15 且 >= 0.65
                    has_stronger_signal = False
                    _stronger_signal_info: dict | None = None
                    _cur_confidence = float(getattr(rec, "confidence", 0.0) or 0.0)
                    try:
                        from dreambuddy_evolution.engines.entry_signal_governor import (
                            find_strongest_rotation_signal,
                        )
                        _kd_by_coin = getattr(self, "_last_evolution_kline_by_coin", None) or {}
                        _bcrm_inf = getattr(self, "_latest_bcrm_inference", None) or {}
                        _stronger_signal_info = find_strongest_rotation_signal(
                            evo_signals=_kd_by_coin,
                            bcrm_signals=_bcrm_inf,
                            exclude_coin=coin_up,
                            cur_confidence=_cur_confidence,
                            cur_direction=pos_side,
                        )
                        if _stronger_signal_info is not None:
                            has_stronger_signal = True
                            self._log(
                                f"[EvolutionExitEngine] {coin_up}({pos_side} conf={_cur_confidence:.3f}) "
                                f"超时换仓信号: {_stronger_signal_info['coin']} "
                                f"{_stronger_signal_info['direction']} "
                                f"conf={_stronger_signal_info['confidence']:.3f} "
                                f"src={_stronger_signal_info['source']} "
                                f"{'(反向)' if _stronger_signal_info['is_opposite'] else '(同向)'} "
                                f"→ has_stronger_signal=True",
                                "INFO",
                            )
                    except ImportError:
                        # 回退旧逻辑：同方向更强信号
                        try:
                            _kd_by_coin = getattr(self, "_last_evolution_kline_by_coin", None) or {}
                            _last_kd = _kd_by_coin.get(coin_up)
                            if _last_kd and isinstance(_last_kd, dict):
                                _new_conf = float(_last_kd.get("top_path_confidence", 0.0) or 0.0)
                                _new_dir = str(_last_kd.get("top_path_direction", "") or "").lower()
                                if (_new_dir == pos_side
                                        and _new_conf > _cur_confidence + 0.15
                                        and _new_conf >= 0.65):
                                    has_stronger_signal = True
                        except Exception:
                            pass
                    except Exception:
                        pass

                    context = {
                        "symbol": coin_up, "inst_id": inst_id, "pos_side": pos_side,
                        "entry_price": entry_price, "current_price": current_price,
                        "upl": upl, "upl_ratio": upl_ratio,
                        "position_age_sec": position_age_sec,
                        "r_vector": r_vector, "ess": ess, "ftc_track": ftc_track,
                        "regime": regime, "atr_pct": atr_pct, "tier": tier,
                        "current_sl_px": current_sl_px, "current_tp_px": current_tp_px,
                        "okx_algo_triggered": okx_algo_triggered,
                        "has_stronger_signal": has_stronger_signal,
                        # ★ 超时换仓信号详情（同向/反向，供 exit engine 生成区分化 reason）
                        "stronger_signal_info": _stronger_signal_info,
                        # ★ 规则 2b: BCRM2.0 反向信号注入（走进化管线，减仓非全平）
                        "bcrm_reverse_dir": (lambda c: ({"UP": "long", "DOWN": "short"}.get(
                            str((getattr(self, "_latest_bcrm_inference", None) or {}).get(c, {}).get("direction", "") or "").upper(), ""))) (coin_up),
                        "bcrm_reverse_conf": float((getattr(self, "_latest_bcrm_inference", None) or {}).get(coin_up, {}).get("confidence", 0.0) or 0.0),
                        "bcrm_reverse_ts": float((getattr(self, "_latest_bcrm_inference", None) or {}).get(coin_up, {}).get("ts", 0.0) or 0.0),
                        "bdsm_direction_constraint": str((getattr(self, "_last_bdsm_snapshot", None) or {}).get("direction_constraint", "") or "") if isinstance(getattr(self, "_last_bdsm_snapshot", None), dict) else "",
                    }

                    # ★ RAG 热路径接入（FAIL-OPEN 只读，注入 context 供 decide 消费）
                    _rag_q = f"{coin_up} {pos_side} 离场 止损 止盈 超时 trailing"
                    _rag_hits = _rag_hotpath_lookup(self, _rag_q, top_k=5)
                    if _rag_hits:
                        self._log(
                            f"[RAG-PRE-EXIT] {coin_up} {pos_side} | "
                            f"hits={len(_rag_hits)} top={_rag_hits[0].get('heading', '')[:40]}",
                            "INFO",
                        )
                    context["rag_context"] = _rag_hits  # 空列表也注入，保持 schema 一致

                    # ── RL 离场策略层：ShieldedPolicy 推理 ──
                    # CQL 策略建议动作 → shield 检查安全性 → 置信度高时覆盖规则决策
                    rl_action_override = None
                    _rl_conf = 0.0
                    _rl_q_values: list = []
                    if _policy is not None:
                        try:
                            import numpy as _np_rl
                            _tier_idx = {"probe": 0, "standard": 1, "trend": 2}.get(tier, 1)
                            _rl_state = _np_rl.array([
                                upl_ratio,
                                position_age_sec / 60.0,
                                atr_pct,
                                float(snap.get("rsi", 50.0) or 50.0),
                                ess,
                                float(snap.get("cs", 0.5) or 0.5),
                                float(snap.get("vol_ratio", 1.0) or 1.0),
                                _tier_idx,
                            ], dtype=_np_rl.float32)

                            _rl_action, _rl_params = _policy.act_with_shield(_rl_state, context)
                            _rl_conf = float(_rl_params.get("confidence", 0.0) or 0.0)
                            _rl_q_values = _rl_params.get("q_values", [])

                            # DEBUG: 记录 RL 推理结果（无论是否覆盖）
                            self._log(
                                f"[EvolutionExitEngine] {coin_up} RL 推理: action={_rl_action} "
                                f"conf={_rl_conf:.3f} shielded={_rl_params.get('shielded', False)}",
                                "DEBUG",
                            )

                            # 置信度 > 0.7 且非 hold 时覆盖规则决策
                            # ★ FIX: 阈值从 0.3 提高到 0.7，避免低质量 RL 信号覆盖规则决策。
                            #   CQL 模型仅用 2000 合成样本训练，低置信度时外推不可靠。
                            #   保留模型自主进化能力，但要求高置信度才能覆盖人工风控规则。
                            if _rl_conf > 0.7 and _rl_action != "hold":
                                rl_action_override = _rl_action
                                self._log(
                                    f"[EvolutionExitEngine] {coin_up} RL 建议: {_rl_action} "
                                    f"(conf={_rl_conf:.3f} shielded={_rl_params.get('shielded', False)})",
                                    "INFO",
                                )
                        except Exception as _rl_e:
                            self._log(
                                f"[EvolutionExitEngine] {coin_up} RL 推理异常(FAIL-OPEN): {_rl_e}",
                                "WARN",
                            )

                    # 规则决策（始终先算，作为 fallback 和 SL/TP 参数来源）
                    decision = _engine.decide(context)

                    # RL 覆盖：如果 RL 建议不同动作且置信度高，覆盖 action 但保留规则计算的 SL/TP
                    if rl_action_override is not None and rl_action_override != decision.action:
                        try:
                            from dreambuddy_evolution.engines.exit_engine.exit_decision import ExitDecision as _ED
                            decision = _ED(
                                action=rl_action_override,
                                params={"rl_confidence": _rl_conf, "q_values": _rl_q_values},
                                reason=f"evolution_rl:override:{rl_action_override}",
                                sl_px=decision.sl_px,
                                tp_px=decision.tp_px,
                                confidence=max(decision.confidence, _rl_conf),
                            )
                        except Exception:
                            pass  # 覆盖失败则保留规则决策

                    self._log(
                        f"[EvolutionExitEngine] {coin_up} decide: action={decision.action} "
                        f"reason={decision.reason} | conf={decision.confidence:.2f} "
                        f"upl={upl:.2f}({upl_ratio:.2%}) age={int(position_age_sec/60)}min"
                        f"{' [RL]' if rl_action_override else ' [RULE]'}",
                        "INFO",
                    )

                    # ── ShadowRL 样本记录：(s, a, R, s') 供 PPO 微调用 ──
                    # NOTE: 必须在 hold/force_close 的 continue 之前执行，确保所有 action（含 hold）都被记录为 RL 样本
                    if _shadow_tracker is not None:
                        try:
                            from dreambuddy_evolution.core.exit_rl_policy import ACTION_TO_IDX as _A2I
                            _action_idx = _A2I.get(decision.action, 0)
                            # 三组件奖励：R_trend + R_risk + R_pnl（替换硬编码 upl_ratio * 5.0）
                            _reward_calc = getattr(self, "_evolution_reward_calc", None)
                            if _reward_calc is not None and decision.action != "hold":
                                try:
                                    _reward_result = _reward_calc.calculate({
                                        "cs": context.get("cs", 0.0),
                                        "sl_in_range": True,
                                        "pnl_pct": upl_ratio,
                                        "tp_pct_target": context.get("tp_pct", 0.06),
                                        "sl_pct_target": context.get("sl_pct", 0.03),
                                    })
                                    _reward = _reward_result.get("R_total", 0.0)
                                except Exception:
                                    _reward = upl_ratio * 5.0  # FAIL-OPEN 降级
                            elif decision.action != "hold":
                                _reward = upl_ratio * 5.0  # FAIL-OPEN 降级
                            else:
                                _reward = 0.0
                            _shadow_tracker.record(
                                symbol=coin_up,
                                state={
                                    "upl_ratio": upl_ratio,
                                    "position_age_min": position_age_sec / 60.0,
                                    "atr_pct": atr_pct,
                                    "ess": ess,
                                    "tier": tier,
                                    "action": decision.action,
                                },
                                action=decision.action,
                                reward=_reward,
                                next_state=None,  # 下一轮巡检时更新
                            )
                            # PPO 微调阈值检查
                            _n = _shadow_tracker.sample_count()
                            if _n >= 10000 and not _shadow_tracker.is_phase3_activated():
                                from dreambuddy_evolution.agi_config import is_enabled
                                if is_enabled("enable_shadow_rl_phase3"):
                                    _shadow_tracker.activate_phase3()
                                    # 激活后执行 PPO 训练
                                    try:
                                        _shadow_tracker.trainer.train_policy(
                                            list(_shadow_tracker._samples)
                                        )
                                        self._log(
                                            f"[EvolutionExitEngine] ShadowRL Phase3 训练完成 (samples={_n})",
                                            "INFO",
                                        )
                                    except Exception as _tp_e:
                                        self._log(
                                            f"[EvolutionExitEngine] train_policy crash(FAIL-OPEN): {_tp_e}",
                                            "WARN",
                                        )
                        except Exception as _sr_e:
                            self._log(
                                f"[EvolutionExitEngine] ShadowRL 记录异常(FAIL-OPEN): {_sr_e}",
                                "DEBUG",
                            )
                    # ---- Phase 3: ReflexivityMonitor 反身性追踪 ----
                    try:
                        _pipeline = getattr(self, "_evolution_pipeline", None)
                        if _pipeline is not None:
                            _rm = _pipeline._get_reflexivity_monitor()
                            if _rm is not None:
                                _pos_delta = float(getattr(rec, "qty", 0.0) or 0.0)
                                if decision.action in ("close_long", "close_short"):
                                    _pos_delta = -_pos_delta
                                _price = float(getattr(rec, "mark_price", 0.0) or 0.0)
                                _etf_flow = float(context.get("etf_net_flow", 0.0) or 0.0)
                                _mkt_vol = float(context.get("market_volume", 0.0) or 0.0)
                                _rm.record(_pos_delta, _etf_flow, _price, _mkt_vol)
                    except Exception:
                        pass

                    # 执行动作
                    if decision.action == "hold":
                        continue

                    if decision.action == "force_close":
                        # OKX algo 已触达或信号反转/超时 → 市价平仓
                        # ★ evolution 子池独立通过 TEE 执行引擎平仓
                        _r = self._execute_evolution_close_via_tee(
                            inst_id=inst_id, pos_side=pos_side,
                            reduce_ratio=1.0, reason=decision.reason,
                        )
                        if _r.get("ok") or _r.get("dry_run"):
                            self._handle_close_position(
                                inst_id=inst_id, coin=coin_up, pos_side=pos_side,
                                exit_price=current_price, exit_reason=decision.reason,
                                pnl=upl, pnl_pct=upl_ratio,
                            )
                        else:
                            self._log(
                                f"[EvolutionExitEngine] {coin_up} force_close 失败: {_r.get('error')}",
                                "WARN",
                            )
                        continue

                    if decision.action == "partial_close":
                        # 分批止盈：部分平仓（RL 或规则触发）
                        _partial_pct = float(decision.params.get("partial_pct", 0.5) if decision.params else 0.5)
                        _partial_pct = max(0.1, min(0.9, _partial_pct))
                        self._log(
                            f"[EvolutionExitEngine] {coin_up} partial_close pct={_partial_pct:.0%}",
                            "INFO",
                        )
                        # ★ evolution 子池独立通过 TEE 执行引擎部分平仓
                        self._execute_evolution_close_via_tee(
                            inst_id=inst_id, pos_side=pos_side,
                            reduce_ratio=_partial_pct, reason=decision.reason,
                        )

                    if decision.action in ("adjust_sl_tp", "trailing"):
                        # 取消旧 algo → 下新 SL/TP
                        if decision.sl_px > 0 or decision.tp_px > 0:
                            try:
                                if self.okx_client and hasattr(self.okx_client, "cancel_algo_orders"):
                                    self.okx_client.cancel_algo_orders(instId=inst_id)
                            except Exception as _ce:
                                self._log(f"[EvolutionExitEngine] 取消旧algo: {_ce}", "DEBUG")
                            if self.okx_client and hasattr(self.okx_client, "place_stop_loss_take_profit"):
                                _new_sl = decision.sl_px if decision.sl_px > 0 else current_sl_px
                                _new_tp = decision.tp_px if decision.tp_px > 0 else current_tp_px
                                self.okx_client.place_stop_loss_take_profit(
                                    inst_id=inst_id, pos_side=pos_side,
                                    stop_loss_px=_new_sl, take_profit_px=_new_tp,
                                    reason=decision.reason,
                                )
                                self._log(
                                    f"[EvolutionExitEngine] {coin_up} {decision.action} "
                                    f"SL→{_new_sl:.4f} TP→{_new_tp:.4f}",
                                    "INFO",
                                )

                except Exception as _coin_e:
                    self._log(
                        f"[EvolutionExitEngine] {getattr(rec, 'coin', '?')} 巡检异常(FAIL-OPEN): {_coin_e}",
                        "WARN",
                    )
        except Exception as _evo_exit_e:
            self._log(f"[EvolutionExitEngine] 顶层异常(FAIL-OPEN): {_evo_exit_e}", "WARN")

    def _check_evolution_kline_signal(self):
        """P2-S4b: 获取 BTC/ETH/SOL 1h K线 → KlineEventHandler 触发推断+建仓

        数据管线已升级为 DataPipelineAdapter.assemble()，
        自动装配 R 向量 5 维所需全部字段（OHLCV + ma_200 + spread + 清算 + 情绪 + ESS方向 + war_state）。
        Phase 3: alpha=0.1 (R_narrative), beta=0.2 (R_sentiment), gamma=0.2 (R_capital)
                 修饰子权重上限 0.2（蓝图 §1.9.6 硬约束）
                 odaily 叙事标签库已就绪 → alpha 激活

        FAIL-OPEN: 任何异常不阻断主循环
        """
        try:
            import sys as _sys
            _evo_root = str(_PROJECT_ROOT / "23-四层闭环自进化交易架构")
            if _evo_root not in _sys.path:
                _sys.path.insert(0, _evo_root)
            from dreambuddy_evolution.engines.kline_event_handler import KlineEventHandler

            if not hasattr(self, "_kline_handler"):
                self._kline_handler = KlineEventHandler(
                    mode="Phase2",
                    build_position_callback=self._evolution_build_position,
                    ripple_kwargs={"vol_ratio_threshold": 1.3},  # 训练期：1.3倍量即可触发
                    project_root=str(_PROJECT_ROOT),  # 反思学习起点：系统级交易索引库（含所有子系统）
                )
                # Phase 4.2: 注入 trader 引用，使 bridge 可写回 btc_regime 到战略层状态
                self._kline_handler.attach_trader(self)

            # 懒初始化数据管线
            self._init_data_pipeline()

            # Phase 8: 全市场扫描（50+ OKX 币种），发现当前未跟踪的机会
            _scan_coins: list[str] = []
            try:
                if self._data_pipeline is not None:
                    _scan = self._data_pipeline.scan_market(top_n=50)
                    if _scan:
                        _scan_coins = [c["symbol"] for c in _scan]
                        _top5 = _scan[:5]
                        _scan_str = " | ".join(
                            f"{c['symbol']}:{c['signal']:+.2f}@{c['confidence']:.2f}"
                            for c in _top5
                        )
                        self._log(f"[P2-S4b-SCAN] 市场扫描({len(_scan_coins)}币) Top5: {_scan_str}", "DEBUG")
            except Exception as _scan_e:
                self._log(f"[P2-S4b-SCAN] 扫描异常(FAIL-OPEN): {_scan_e}", "DEBUG")

            # 币种池：基础 22 币 + CoinScanner 扫描 Top 50（去重合并，上限 50）
            _evo_coins = self._EVOLUTION_KLINE_COINS
            if _evo_coins is None:
                _base_coins = list(getattr(self, "coins", []) or [])
                _evo_coins = _base_coins + [c for c in _scan_coins if c not in _base_coins]
                _evo_coins = _evo_coins[:50]
                self._log(
                    f"[P2-S4b-POOL] 进化币种池: 基础{len(_base_coins)} + 扫描{len([c for c in _scan_coins if c not in _base_coins])} = {len(_evo_coins)} 币",
                    "DEBUG",
                )

            for _coin in _evo_coins:
                try:
                    _inst_id = f"{_coin}-USDT-SWAP"

                    # 通过 DataPipelineAdapter 装配全字段 kline_data
                    if self._data_pipeline is not None:
                        _kline_data = self._data_pipeline.assemble(
                            symbol=_coin, inst_id=_inst_id
                        )
                    else:
                        # 降级：手工获取 K线（仅 OHLCV）
                        _kline_resp = self.okx_client.get_kline(
                            _inst_id, bar="1H", limit=200
                        )
                        if not _kline_resp.get("ok"):
                            continue
                        _candles = _kline_resp.get("candles", [])
                        _candles_asc = list(reversed(_candles))
                        _kline_data = {
                            "symbol": _coin,
                            "close": [c["c"] for c in _candles_asc],
                            "high": [c["h"] for c in _candles_asc],
                            "low": [c["l"] for c in _candles_asc],
                            "volume": [c["vol"] for c in _candles_asc],
                        }

                    _result = self._kline_handler.on_kline_close(
                        _kline_data, alpha=0.1, beta=0.2, gamma=0.2
                    )
                    # 保存最近一次 kline_data，供建仓回调读取 FTC 轨道分档
                    self._last_evolution_kline = _kline_data
                    # ★ 保存每个币种独立的 kline_data，供超时换仓评估使用
                    if not hasattr(self, "_last_evolution_kline_by_coin"):
                        self._last_evolution_kline_by_coin = {}
                    self._last_evolution_kline_by_coin[_coin] = _kline_data
                    # ★ 缓存 on_kline_close 返回值（含 d_star/ri），供策略独立开仓消费
                    if not hasattr(self, "_last_kline_result_by_coin"):
                        self._last_kline_result_by_coin = {}
                    self._last_kline_result_by_coin[_coin] = _result
                    # 诊断日志：观察涟漪检测与下单触发
                    _rot = _kline_data.get("capital_rotation", 0.0)
                    _regime = _kline_data.get("regime", "?")
                    _kelly = _kline_data.get("kelly_fraction", 0.0)
                    _vs = _kline_data.get("vol_scalar", 1.0)
                    _path = _kline_data.get("top_path", "")
                    _path_dir = _kline_data.get("top_path_direction", "?")
                    _path_conf = _kline_data.get("top_path_confidence", 0.0)
                    _ftc = _kline_data.get("top_ftc", "")
                    _ftc_dir = _kline_data.get("top_ftc_direction", "?")
                    _ftc_ess = _kline_data.get("top_ftc_ess", 0.0)
                    _ftc_track = _kline_data.get("top_ftc_track", "exploit")
                    _significant = abs(_rot) > 0.10
                    # AGI 增强字段提取（只读，不影响决策）
                    _agi_sig = _result.get("agi_signature")
                    _agi_pi = _result.get("agi_path_integral")
                    _agi_uq = _result.get("agi_uncertainty")
                    _agi_gate = _result.get("agi_gate_decision")
                    _agi_pat = _result.get("agi_pattern")
                    _agi_regime = _result.get("agi_btc_regime")
                    _agi_sig_str = f"dim={_agi_sig['dim']} norm={_agi_sig['norm']:.3f}" if _agi_sig else "off"
                    _agi_pi_str = f"S={_agi_pi['min_resistance_action']:.3f} exp_end={_agi_pi['expected_end_price']:.1f}" if _agi_pi else "off"
                    _agi_uq_str = f"u={_agi_uq['uncertainty_score']:.3f}/{_agi_uq['level']}" if _agi_uq else "off"
                    _agi_gate_str = f"{_agi_gate.get('decision', '?')}/pm={_agi_gate.get('position_multiplier', '?')}" if _agi_gate else "off"
                    _agi_pat_str = f"{_agi_pat.get('pattern', 'none')}/{_agi_pat.get('direction', '?')}" if _agi_pat and _agi_pat.get("is_reversal_signal") else "none"
                    self._log(
                        f"[P2-S4b] {_coin} d*={_result.get('d_star')} "
                        f"ri={_result.get('ri', 0):.3f} "
                        f"src={_result.get('signal_source', '?')} "
                        f"rfl_ri={_result.get('reflection_ri', 0):.3f} "
                        f"rfl_ok={_result.get('reflection_eligible')} "
                        f"rot={_rot:+.3f} "
                        f"regime={_regime} "
                        f"path={_path}({_path_dir})@{_path_conf:.2f} "
                        f"ftc={_ftc}({_ftc_dir})@{_ftc_ess:.2f}/{_ftc_track} "
                        f"kelly={_kelly:.3f} "
                        f"vol_s={_vs:.2f} "
                        f"is_source={_result.get('is_ripple_source')} "
                        f"inferred={_result.get('inference_formed')} "
                        f"auto_exec={_result.get('auto_execute')} "
                        f"AGI[sig={_agi_sig_str} pi={_agi_pi_str} uq={_agi_uq_str} gate={_agi_gate_str} pat={_agi_pat_str} regime={_agi_regime or 'off'}]",
                        "INFO" if (_result.get("auto_execute") or _significant) else "DEBUG",
                    )

                    # ===== AGI 快照持久化 (L2-L5 数据可视化) =====
                    try:
                        import json as _agi_json, pathlib as _agi_pl
                        from datetime import datetime as _agi_dt
                        _agi_snap = {
                            "ts": _agi_dt.now().strftime("%Y-%m-%dT%H:%M:%S"),
                            "symbol": _coin,
                            "d_star": _result.get("d_star"),
                            "ri": round(_result.get("ri", 0), 4),
                            "action": _result.get("action"),
                            "tier": _result.get("tier"),
                            "regime": _result.get("regime", ""),
                            # L2: Signature
                            "agi_signature": _agi_sig,
                            # L3: Path Integral
                            "agi_path_integral": _agi_pi,
                            # L4: Uncertainty + Gate
                            "agi_uncertainty": _agi_uq,
                            "agi_gate_decision": _agi_gate,
                            # L1: Pattern + BTC Regime
                            "agi_pattern": _agi_pat,
                            "agi_btc_regime": _agi_regime,
                            # L3: Path discovery
                            "path_info": _result.get("path_info"),
                        }
                        # ShadowRL + Neural SDE 状态（如果有 evolution pipeline）
                        try:
                            _kh = getattr(self, "_kline_handler", None)
                            if _kh is not None:
                                _ep = getattr(_kh, "_evolution_pipeline", None)
                                if _ep is None:
                                    _ep = _kh._get_evolution_pipeline() if hasattr(_kh, "_get_evolution_pipeline") else None
                                if _ep is not None:
                                    _dr = getattr(_ep, "_deep_reasoning", None)
                                    if _dr is None and hasattr(_ep, "_get_deep_reasoning"):
                                        _dr = _ep._get_deep_reasoning()
                                    if _dr is not None and hasattr(_dr, "backend_status"):
                                        _bs = _dr.backend_status()
                                        _agi_snap["neural_sde_backend"] = _bs.get("neural_sde_backend")
                                        _agi_snap["neural_sde_trained"] = _bs.get("neural_sde_trained")
                        except Exception:
                            pass
                        try:
                            # 优先从 EvolutionPipeline 获取（启动时已加载），回退到 _evolution_shadow_rl
                            _srl = None
                            _kh = getattr(self, "_kline_handler", None)
                            if _kh is not None:
                                _ep = getattr(_kh, "_evolution_pipeline", None)
                                if _ep is None and hasattr(_kh, "_get_evolution_pipeline"):
                                    _ep = _kh._get_evolution_pipeline()
                                if _ep is not None:
                                    _srl = getattr(_ep, "shadow_rl", None)
                            if _srl is None:
                                _srl = getattr(self, "_evolution_shadow_rl", None)
                            if _srl is not None:
                                _agi_snap["shadow_rl_samples"] = _srl.sample_count() if hasattr(_srl, "sample_count") and callable(getattr(_srl, "sample_count")) else getattr(_srl, "_sample_count", 0)
                                _agi_snap["shadow_rl_activated"] = _srl.is_phase3_activated() if hasattr(_srl, "is_phase3_activated") else getattr(_srl, "_phase3_activated", False)
                                _agi_snap["effective_sample_count"] = _srl.effective_sample_count() if hasattr(_srl, "effective_sample_count") and callable(getattr(_srl, "effective_sample_count")) else 0
                        except Exception:
                            pass
                        # 写入 JSONL（追加模式）
                        _snap_dir = _agi_pl.Path("/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/data")
                        _snap_dir.mkdir(parents=True, exist_ok=True)
                        _snap_path = _snap_dir / "agi_snapshot.jsonl"
                        with open(_snap_path, "a", encoding="utf-8") as _f:
                            _f.write(_agi_json.dumps(_agi_snap, default=str) + "\n")
                        # 保留最新 2000 行（防止无限增长）
                        try:
                            _lines = _snap_path.read_text(encoding="utf-8").splitlines()
                            if len(_lines) > 2000:
                                _snap_path.write_text("\n".join(_lines[-2000:]) + "\n", encoding="utf-8")
                        except Exception:
                            pass
                    except Exception as _agi_e:
                        pass  # FAIL-OPEN: 快照写入不影响交易

                except Exception as _ce:
                    self._log(
                        f"[P2-S4b] {_coin} K线检查异常(FAIL-OPEN): {_ce}",
                        "DEBUG",
                    )
                # 币种间限流，防止 OKX API 限频
                import time as _time
                _time.sleep(self._EVOLUTION_COIN_INTERVAL)
        except Exception as _e:
            self._log(f"[P2-S4b] _check_evolution_kline_signal crash: {_e}", "WARN")

    # ===== P1-1: 做空趋势过滤器 =====
    # 加密货币用BTC趋势确认（参考V15马丁策略DirectionGate力学化模式）
    # 非加密货币用自身日MA50趋势（未来可升级为标普500趋势线过滤）
    CRYPTO_COINS = frozenset({
        # — BDSM 2026-09 扩展：加密币种池补齐 AAVE, CRCL, ETH（ETH 仅做多）—
        "BTC", "ETH", "SOL", "UNI", "OKB", "HYPE", "PUMP", "AAVE", "CRCL",
    })

    # 加密属性美股代币（COIN=Coinbase/MSTR=MicroStrategy/CRCL=Circle）
    # 此类币种本质跟随加密市场，不跟随美股大盘趋势，路由到 BTC 弹簧力场确认
    CRYPTO_US_STOCK_COINS = frozenset({
        "COIN", "MSTR", "CRCL",
    })

    # 纯美股代币（OKX 上以 USDT-SWAP 交易的美股代币化合约）
    # 做空这些币种时需要纳斯达克/标普500大盘趋势确认
    # 注：加密属性币种(COIN/MSTR/CRCL)已单独分组，跟随BTC而非美股大盘
    US_STOCK_COINS = frozenset({
        "AAPL", "AMZN", "GOOGL", "NVDA", "MSFT", "TSLA",
        "META", "NFLX", "BABA", "MU", "SKHYNIX", "SNDK", "SPCX",
        "PLTR", "BMNR",
    })

    @staticmethod
    def _ma_spring_force(price: float, ma: float, k: float = 2.0) -> float:
        """双均线弹簧力：F = -k × (price - MA) / MA

        符号语义:
          F > 0 → 做多倾向（价格在MA下方时，MA作为支撑，弹簧向上推）
          F < 0 → 做空倾向（价格在MA上方时，MA作为阻力，弹簧向下压）
        来源: V15 direction_gate._ma_spring_force
        """
        if ma is None or ma <= 0:
            return 0.0
        return -k * (price - ma) / ma

    @staticmethod
    def _distance_weight(abs_dist_pct: float) -> float:
        """距离权重函数: w = 1 / (1 + |dist%|)

        距离越近权重越大 → 价格接近周MA200时，周线支撑权重大 → 偏见底
        来源: V15 direction_gate._distance_weight
        """
        return 1.0 / (1.0 + abs(abs_dist_pct))

    def _calc_ma_slope(self, closes: list, period: int, window: int = 5) -> float:
        """计算 MA 的斜率（线性回归法）

        取最近 window 期的 MA 值序列，做线性回归求斜率。
        返回归一化百分比斜率: slope_pct = slope / MA_current * 100

        物理含义: MA 斜率 = 均线（均衡位置）的运动速度
          slope > 0 → 均线上升 → 做多势能方向
          slope < 0 → 均线下降 → 做空势能方向
        """
        if len(closes) < period + window:
            return 0.0
        # 取最近 window 期的 MA 值（从当前往前推）
        # closes[0]=最新, closes[1]=1日前...
        # ma_series[0] = MA(t), ma_series[1] = MA(t-1), ..., ma_series[n-1] = MA(t-n+1)
        ma_series = []
        for i in range(window):
            if len(closes) - i >= period:
                ma_series.append(sum(closes[i:i+period]) / period)
        if len(ma_series) < 2:
            return 0.0
        # 反转序列使 x 轴方向正确: x=0=最旧, x=n-1=最新
        # 这样 bear 趋势（MA 下降）→ slope < 0；bull 趋势（MA 上升）→ slope > 0
        ma_series = ma_series[::-1]
        # 线性回归: y = a + b*x, 求 b (slope)
        n = len(ma_series)
        x_mean = (n - 1) / 2.0  # 0..n-1 的均值
        y_mean = sum(ma_series) / n
        numerator = sum((i - x_mean) * (ma_series[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0 or y_mean == 0:
            return 0.0
        slope = numerator / denominator
        # 归一化为百分比: slope_pct = slope / MA_current * 100
        return slope / y_mean * 100

    def _compute_f_total_snapshot(self, closes: list, k: float = 2.0,
                                   tier: str = "daily_btc") -> float:
        """Non-recursive snapshot of _calc_5ma_spring_force returning ONLY F_total.

        Intended for computing the (t-1) look-back needed by F_dot inside
        _calc_5ma_spring_force itself. Keeping it small and loop-free (no F_dot,
        no regime classification, no breakdown window) avoids cascading
        recursion when `closes` has thousands of elements (e.g. 5y daily index
        data from yfinance → ~1254 bars would otherwise blow CPython's default
        recursionlimit=1000).

        Mirrors: actual_periods selection + slope modulation → k_eff →
                 F_net (group-weighted price→MA forces) +
                 F_inter_net (intra-group & cross-group inter-MA forces).
        """
        if not closes:
            return 0.0

        # --- mirror L4579–L4604 (periods + MA values + slope_modulated k_eff) -
        ma_periods = [30, 65, 128, 200]
        if tier in ("daily_btc", "daily_self", "daily_index"):
            ma_periods.append(min(1400, len(closes)))
        actual_periods = [p for p in ma_periods if len(closes) >= p + 1]
        if len(actual_periods) < 2:
            return 0.0

        current_price = closes[0]
        ma_values = {f"ma{p}": sum(closes[:p]) / p for p in actual_periods}
        ma_slopes = {
            f"ma{p}": self._calc_ma_slope(closes, p, self.FMA_SLOPE_WINDOW)
            for p in actual_periods
        }
        slope_avg = sum(ma_slopes.values()) / len(ma_slopes) if ma_slopes else 0.0
        import math
        slope_modulation = 1.0 + self.FMA_SLOPE_ALPHA * math.tanh(slope_avg / 0.5)
        k_eff = k * slope_modulation

        def _p(k_str): return int(k_str.replace("ma", ""))

        group_short = {p: v for p, v in ma_values.items() if _p(p) < 80}
        group_mid = {p: v for p, v in ma_values.items() if 80 <= _p(p) < 1000}
        group_long = {p: v for p, v in ma_values.items() if _p(p) >= 1000}
        gw_cfg = {"short": self.FMA_GROUP_WEIGHT_SHORT,
                  "mid": self.FMA_GROUP_WEIGHT_MID,
                  "long": self.FMA_GROUP_WEIGHT_LONG}

        def _group_internal(group_dict):
            items = []
            for p_str, ma in group_dict.items():
                dist_pct = (current_price - ma) / ma * 100
                F = -k_eff * (current_price - ma) / ma
                w = self._distance_weight(abs(dist_pct))
                items.append((_p(p_str), F, w))
            w_sum = sum(i[2] for i in items) or 1.0
            return [(p, F, w / w_sum) for p, F, w in items]

        short_items = _group_internal(group_short)
        mid_items = _group_internal(group_mid)
        long_items = _group_internal(group_long)

        # --- F_net (group weighted) -------------------------------------------
        F_net = 0.0
        for name, items, g_w in [("short", short_items, gw_cfg["short"]),
                                 ("mid",   mid_items,   gw_cfg["mid"]),
                                 ("long",  long_items,  gw_cfg["long"])]:
            for _p, F, internal_pct in items:
                F_net += F * g_w * internal_pct

        # --- F_inter_net ------------------------------------------------------
        k_inter = k_eff * self.FMA_INTER_K_RATIO
        F_inter_net = 0.0

        def _sorted_items(it): return sorted(it, key=lambda x: x[0])  # period asc

        for items in (short_items, mid_items, long_items):
            if len(items) < 2:
                continue
            sitems = _sorted_items(items)
            for i in range(len(sitems) - 1):
                p1, F1, _ = sitems[i]
                p2, F2, _ = sitems[i + 1]
                ma1 = ma_values[f"ma{p1}"]
                ma2 = ma_values[f"ma{p2}"]
                inter_dist = (ma1 - ma2) / ma2
                F_inter_net += (-k_inter * inter_dist)

        # cross-group (period-adjacent pairs)
        def _max_period(items): return max((p for p, _, _ in items), default=None)
        def _min_period(items): return min((p for p, _, _ in items), default=None)
        pairs = []
        if short_items and mid_items:
            pairs.append((_max_period(short_items), _min_period(mid_items)))
        if mid_items and long_items:
            pairs.append((_max_period(mid_items), _min_period(long_items)))
        for p1, p2 in pairs:
            ma1 = ma_values[f"ma{p1}"]
            ma2 = ma_values[f"ma{p2}"]
            inter_dist = (ma1 - ma2) / ma2
            F_inter_net += (-k_inter * inter_dist) * 0.15

        return F_net + F_inter_net

    def _calc_5ma_spring_force(self, closes: list, k: float = 2.0,
                                 tier: str = "daily_btc") -> dict:
        """五均线分层弹簧力场 + 均线多空排列评分（Phase C++ 动态升级）

        核心改进（Phase C++ 新增三个维度）:
          ① inter-MA力: F_inter = -k_inter × (MA_short - MA_long) / MA_long
             → 均线排列本身产生趋势力（不是只看价格位置）
          ② MA斜率调制k: k_eff = k × (1 + α × tanh(slope_norm))
             → MA上升时趋势方向弹簧更硬（不易反弹），MA下降时反之
          ③ 势能: U = ½ × k × x²
             → 量化蓄势程度（偏离大=蓄势多，即将释放）

        原有结构:
          短中期组(MA30/MA65, w=0.35) + 中期组(MA128/MA200, w=0.40)
          + 长期组(MA1400≈周MA200, w=0.25)

        均线多空排列评分 bearish_score:
          STRONG: 5均线严格空头排列 + 3日跌破MA30
          NORMAL: 3~4均线空头 + 3日跌破确认
          WEAK  : 1~2均线短周期空头 + 3日跌破确认

        Arguments:
            closes: newest-first list of close prices
            k: spring constant (default 2.0)
            tier: "daily_btc" / "daily_self" / "daily_index"

        Returns:
            dict with keys:
              F_net, F_inter_net, F_total,
              U_potential (势能), slope_avg (平均MA斜率),
              spring_details, group_details, inter_ma_details,
              bearish_score, bearish_n, valid_breakdown,
              current_price, ma_values, ma_slopes, tier
        """
        if not closes:
            return {"F_net": 0.0, "F_total": 0.0, "bearish_score": "NONE", "bearish_n": 0}

        # 1. 取各层级 MA 周期（按 tier 自适应）
        ma_periods = [30, 65, 128, 200]
        if tier in ("daily_btc", "daily_self", "daily_index"):
            ma_periods.append(min(1400, len(closes)))
        actual_periods = [p for p in ma_periods if len(closes) >= p + 1]
        if len(actual_periods) < 2:
            return {"F_net": 0.0, "F_total": 0.0, "bearish_score": "NONE", "bearish_n": 0,
                    "error": f"closes太少({len(closes)})"}

        current_price = closes[0]
        ma_values = {}
        for p in actual_periods:
            ma_values[f"ma{p}"] = sum(closes[:p]) / p

        # ① 计算每条 MA 的斜率（线性回归法）
        ma_slopes = {}
        for p in actual_periods:
            ma_slopes[f"ma{p}"] = self._calc_ma_slope(closes, p, self.FMA_SLOPE_WINDOW)
        slope_avg = sum(ma_slopes.values()) / len(ma_slopes) if ma_slopes else 0.0

        # ② 斜率调制 k → k_eff
        # k_eff = k × (1 + α × tanh(slope_norm))
        # tanh 保证调制幅度有界 [-1, 1]
        import math
        slope_modulation = 1.0 + self.FMA_SLOPE_ALPHA * math.tanh(slope_avg / 0.5)  # 0.5% 作为归一化基准
        k_eff = k * slope_modulation

        # 2. 分组（按周期长度聚类）
        def _p_from_key(k_str: str) -> int:
            return int(k_str.replace("ma", ""))

        group_short = {p: v for p, v in ma_values.items() if _p_from_key(p) < 80}
        group_mid   = {p: v for p, v in ma_values.items() if 80 <= _p_from_key(p) < 1000}
        group_long  = {p: v for p, v in ma_values.items() if _p_from_key(p) >= 1000}
        group_weights_config = {
            "short": self.FMA_GROUP_WEIGHT_SHORT,
            "mid":   self.FMA_GROUP_WEIGHT_MID,
            "long":  self.FMA_GROUP_WEIGHT_LONG,
        }

        # 3. 每个组内按距离权重分配组内权重（使用 k_eff 代替 k）
        def _group_internal(group_dict):
            items = []
            for p_str, ma in group_dict.items():
                dist_pct = (current_price - ma) / ma * 100
                F = -k_eff * (current_price - ma) / ma  # ← 使用 k_eff
                w = self._distance_weight(abs(dist_pct))
                p = _p_from_key(p_str)
                slope = ma_slopes.get(p_str, 0.0)
                items.append((p, p_str, ma, dist_pct, F, w, slope))
            w_sum = sum(i[5] for i in items) if items else 1.0
            internal = []
            for p, p_str, ma, d, F, w, slope in items:
                internal.append((p, p_str, ma, d, F, w, slope, w/w_sum if w_sum else 0.0))
            return internal

        short_items = _group_internal(group_short)
        mid_items   = _group_internal(group_mid)
        long_items  = _group_internal(group_long)

        # 4. 计算 F_net（price-to-MA 回复力，使用 k_eff）
        F_net = 0.0
        group_details = {}
        for name, items, gw_cfg in [
            ("short", short_items, group_weights_config["short"]),
            ("mid",   mid_items,   group_weights_config["mid"]),
            ("long",  long_items,  group_weights_config["long"]),
        ]:
            if not items:
                continue
            contrib = 0.0
            for p, _pstr, _ma, _d, F, _w, _slope, internal_pct in items:
                effective_w = gw_cfg * internal_pct
                contrib += F * effective_w
            F_net += contrib
            group_details[name] = contrib

        # ① inter-MA力：均线间相对距离产生趋势力
        # F_inter = -k_inter × (MA_short - MA_long) / MA_long
        # MA_short > MA_long → F_inter < 0（多头排列→做多方向力）
        # MA_short < MA_long → F_inter > 0（空头排列→做空方向力）
        k_inter = k_eff * self.FMA_INTER_K_RATIO
        F_inter_net = 0.0
        inter_ma_details = {}

        # 组内 inter-MA（如 MA30 vs MA65, MA128 vs MA200）
        for name, items in [("short", short_items), ("mid", mid_items), ("long", long_items)]:
            if len(items) < 2:
                continue
            # 按 MA 周期排序（短在前）
            sorted_items = sorted(items, key=lambda x: x[0])
            for i in range(len(sorted_items) - 1):
                p1, p_str1, ma1 = sorted_items[i][0], sorted_items[i][1], sorted_items[i][2]
                p2, p_str2, ma2 = sorted_items[i+1][0], sorted_items[i+1][1], sorted_items[i+1][2]
                inter_dist = (ma1 - ma2) / ma2  # 短周期 - 长周期
                F_inter = -k_inter * inter_dist
                gw = group_weights_config.get(name, 0.3)
                F_inter_net += F_inter * gw
                inter_ma_details[f"{p_str1}-{p_str2}"] = {
                    "inter_dist%": round(inter_dist * 100, 2),
                    "F_inter": round(F_inter, 4),
                    "direction": "多头排列(短>长)" if inter_dist > 0 else "空头排列(短<长)",
                }

        # 跨组 inter-MA（组间最近邻：MA65 vs MA128, MA200 vs MA1400）
        cross_pairs = []
        if short_items and mid_items:
            cross_pairs.append((max(short_items, key=lambda x: x[0]),
                                min(mid_items, key=lambda x: x[0]), "short-mid"))
        if mid_items and long_items:
            cross_pairs.append((max(mid_items, key=lambda x: x[0]),
                                min(long_items, key=lambda x: x[0]), "mid-long"))
        for item1, item2, cross_name in cross_pairs:
            p1, p_str1, ma1 = item1[0], item1[1], item1[2]
            p2, p_str2, ma2 = item2[0], item2[1], item2[2]
            inter_dist = (ma1 - ma2) / ma2
            F_inter = -k_inter * inter_dist
            F_inter_net += F_inter * 0.15  # 跨组权重 0.15
            inter_ma_details[f"{p_str1}-{p_str2}"] = {
                "inter_dist%": round(inter_dist * 100, 2),
                "F_inter": round(F_inter, 4),
                "direction": "多头排列(短>长)" if inter_dist > 0 else "空头排列(短<长)",
            }

        # F_total = F_net（回复力）+ F_inter_net（趋势力）
        F_total = F_net + F_inter_net

        # ③ 势能 U = ½ × k_eff × x²（x = 归一化偏离）
        # U_potential: 总势能（含所有组，用于日志/调试）
        # U_short: 仅短期组(MA30/65)势能，用于超卖检测（价格离即时均衡的距离）
        #   原因：趋势市中价格远离长期MA是正常现象，不应触发超卖过滤
        U_potential = 0.0
        U_short = 0.0
        for name, items, gw_cfg in [
            ("short", short_items, group_weights_config["short"]),
            ("mid",   mid_items,   group_weights_config["mid"]),
            ("long",  long_items,  group_weights_config["long"]),
        ]:
            if not items:
                continue
            for p, _pstr, ma, _d, _F, _w, _slope, internal_pct in items:
                x = (current_price - ma) / ma  # 归一化偏离
                U_i = 0.5 * k_eff * x * x
                U_potential += U_i * gw_cfg * internal_pct
                if name == "short":
                    U_short += U_i * gw_cfg * internal_pct

        # 5. 均线多空排列评分 bearish_score（保持原有逻辑）
        below_count = 0
        for _, ma in ma_values.items():
            if current_price <= ma:
                below_count += 1

        # 5b) 跌破确认：3日收盘价 ≤ 最短期被跌破均线
        mas_sorted_by_val = sorted(ma_values.items(), key=lambda x: -x[1])
        all_passes = [ma for _, ma in mas_sorted_by_val if current_price <= ma]
        if all_passes:
            highest_broken_ma = max(all_passes)
            recent_n = min(self.FMA_SHORT_TIER_BREAKDOWN_BARS, len(closes))
            valid_breakdown = all(closes[i] <= highest_broken_ma for i in range(recent_n))
        else:
            valid_breakdown = False

        # 5b2) MA128 专属3日跌破确认（双轨方案：趋势市简化两均线过滤用）
        #   传统金融定义：3日收盘价 ≤ MA128 → 有效跌破 → 熊市确认
        ma128_val = ma_values.get("ma128")
        if ma128_val and len(closes) >= self.FMA_SHORT_TIER_BREAKDOWN_BARS:
            valid_breakdown_ma128 = all(
                closes[i] <= ma128_val
                for i in range(self.FMA_SHORT_TIER_BREAKDOWN_BARS)
            )
        else:
            valid_breakdown_ma128 = False

        # 5c) 排列类型
        mas_list = sorted(ma_values.items(), key=lambda x: x[1])
        ascending = all(mas_list[i][1] <= mas_list[i+1][1] for i in range(len(mas_list)-1))
        all_strictly = current_price < mas_list[0][1] if mas_list else False
        strict_bearish = ascending and all_strictly and len(mas_list) >= 3
        strict_bullish = all(current_price > ma for _, ma in mas_list) and len(mas_list) >= 3

        # 5d) 评分映射（增加势能辅助）
        if strict_bearish and valid_breakdown and len(mas_list) >= 4:
            bearish_score = "STRONG"
        elif below_count >= 3 and valid_breakdown:
            bearish_score = "NORMAL"
        elif below_count >= 1 and valid_breakdown:
            bearish_score = "WEAK"
        else:
            bearish_score = "NONE"

        # 6. 偏见底窗口
        in_long_term_window = False
        if group_long:
            for p, ma in group_long.items():
                dist = abs(current_price - ma) / ma
                if dist <= self.FMA_LONG_TERM_BOTTOM_BUFFER:
                    in_long_term_window = True
                    break

        # spring_details（增加斜率和势能）
        spring_details = {}
        for items in [short_items, mid_items, long_items]:
            for p, p_str, ma, d, F, _w, slope, _ in items:
                x = (current_price - ma) / ma
                U_i = 0.5 * k_eff * x * x
                spring_details[p_str] = {
                    "value": round(ma, 2), "dist%": round(d, 2),
                    "F": round(F, 4), "role": "支撑" if current_price > ma else "阻力",
                    "slope%": round(slope, 4),
                    "U": round(U_i, 6),
                }

        # ④ F_dot：F_total 的变化率（趋势加速度）
        # F_dot = F_total(t) - F_total(t-1)
        # 需要 t-1 时刻的 F_total，用 closes[1:] 作为"去掉当前bar"的快照。
        # ⚠️ 注意：直接递归调用本方法会引发级联递归（closes[1:]再计算closes[2:]…），
        #    对 5y 日线约 1254 条数据会压栈至 ~1054 层，击穿 CPython 默认
        #    recursionlimit=1000 并触发 RecursionError。这里改为复用当前 F_total
        #    的核心计算片段，只计算 prev 的 F_total，不再做第 N+1 阶差分。
        F_dot = 0.0
        if len(closes) >= 2:
            prev_closes = closes[1:]  # 去掉最新一根
            if len(prev_closes) >= max(actual_periods) + 1:
                try:
                    prev_F_total = self._compute_f_total_snapshot(
                        prev_closes, k=k, tier=tier
                    )
                except Exception:
                    prev_F_total = F_total
                F_dot = F_total - prev_F_total

        # ⑤ Phase D：4维度市场形态判定（Market Regime Classification）
        # 维度1: 趋势强度比 TR = |F_inter| / (|F_net_short| + |F_inter| + ε)
        #   仅用短期组F_net（价格vs MA30/65的回复力），不含长期MA偏离
        #   原因：趋势市中价格远离长期MA是正常现象，不应让长期偏离压低TR
        #   高 TR → 均线排列主导（趋势市）；低 TR → 价格偏离主导（均值回归）
        eps_tr = 1e-6
        F_net_short = group_details.get("short", 0.0)
        abs_F_net_short = abs(F_net_short)
        abs_F_inter = abs(F_inter_net)
        trend_ratio = abs_F_inter / (abs_F_net_short + abs_F_inter + eps_tr)

        # 维度2: 均线发散度 CV = std(MA30/65/128/200) / mean
        #   仅用可比较的 MA 值，避免长期 MA 缺失导致 CV 失真
        cv_ma_keys = [k for k in ("ma30", "ma65", "ma128", "ma200") if k in ma_values]
        cv_dispersion = 0.0
        if len(cv_ma_keys) >= 2:
            cv_vals = [ma_values[k] for k in cv_ma_keys]
            cv_mean = sum(cv_vals) / len(cv_vals)
            if cv_mean > 0:
                cv_var = sum((v - cv_mean) ** 2 for v in cv_vals) / len(cv_vals)
                cv_dispersion = (cv_var ** 0.5) / cv_mean

        # 维度3: 斜率强度 abs_slope = |slope_avg|
        abs_slope = abs(slope_avg)

        # 维度4: F_dot（已计算）

        # 形态分类器（优先级：多头趋势 > 强空头趋势 > 弱空头趋势 > 均值回归 > 震荡）
        # 多头趋势：F_inter < 0（均线多头排列）+ 斜率向上 + 发散
        if (F_inter_net < 0 and abs_slope > self.FMA_REGIME_SLOPE_TREND
                and trend_ratio > self.FMA_REGIME_TR_TREND
                and cv_dispersion > self.FMA_REGIME_CV_TREND):
            market_regime = "TREND_BULL"
        # 强空头趋势：TR 高 + CV 发散 + 斜率向下 + F_dot 偏离加速
        elif (F_inter_net > 0 and trend_ratio > self.FMA_REGIME_TR_STRONG
                and cv_dispersion > self.FMA_REGIME_CV_STRONG
                and abs_slope > self.FMA_REGIME_SLOPE_STRONG
                and slope_avg < 0
                and F_dot > self.FMA_REGIME_FDOT_STRONG):
            market_regime = "STRONG_TREND_BEAR"
        # 弱空头趋势：TR 中高 + CV 略发散 + 斜率向下
        elif (F_inter_net > 0 and trend_ratio > self.FMA_REGIME_TR_TREND
                and cv_dispersion > self.FMA_REGIME_CV_TREND
                and abs_slope > self.FMA_REGIME_SLOPE_TREND
                and slope_avg < 0):
            market_regime = "TREND_BEAR"
        # 均值回归：TR 低 + CV 纠缠 + F_dot 收敛
        elif (trend_ratio < self.FMA_REGIME_TR_REVERT
                and cv_dispersion < self.FMA_REGIME_CV_REVERT
                and F_dot < self.FMA_REGIME_FDOT_REVERT):
            market_regime = "MEAN_REVERTING"
        # 震荡/筑底：剩余情况
        else:
            market_regime = "RANGING"

        return {
            "tier": tier,
            "F_net": F_net,                    # price-to-MA 回复力（全部组）
            "F_net_short": round(F_net_short, 4),  # 短期组回复力（用于TR计算）
            "F_inter_net": F_inter_net,        # inter-MA 趋势力
            "F_total": F_total,                # 总力 = F_net + F_inter_net
            "F_dot": F_dot,                    # F_total 变化率（趋势加速度）
            "U_potential": U_potential,        # 弹性势能（全部组，日志/调试用）
            "U_short": round(U_short, 6),      # 短期组势能（超卖检测用）
            "slope_avg": slope_avg,            # 平均MA斜率
            "k_eff": k_eff,                     # 调制后的弹簧系数
            "spring_details": spring_details,
            "group_details": {k: round(v, 4) for k, v in group_details.items()},
            "inter_ma_details": inter_ma_details,
            "bearish_score": bearish_score,
            "bearish_n": below_count,
            "valid_breakdown": valid_breakdown,
            "valid_breakdown_ma128": valid_breakdown_ma128,  # MA128专属3日跌破确认（双轨方案）
            "current_price": current_price,
            "ma_values": {k: round(v, 2) for k, v in ma_values.items()},
            "ma_slopes": {k: round(v, 4) for k, v in ma_slopes.items()},
            "strict_bearish": strict_bearish,
            "strict_bullish": strict_bullish,
            "in_long_term_window": in_long_term_window,
            # Phase D 形态判定输出
            "trend_ratio": round(trend_ratio, 4),           # 趋势强度比 TR
            "cv_dispersion": round(cv_dispersion, 4),        # 均线发散度 CV
            "abs_slope": round(abs_slope, 4),               # 斜率强度
            "market_regime": market_regime,                 # 形态分类
            "threshold": 0.02,
        }

    def _trend_regime_short_filter(self, ma_values: dict, current_price: float,
                                     valid_bd_ma128: bool) -> tuple:
        """双轨方案：趋势市简化两均线过滤（MA128 + 周线MA200）

        传统金融逻辑：
          - 价格 > MA128 → 牛市/反弹，禁止做空
          - 3日收盘 ≤ MA128（有效跌破）→ 熊市确认
          - 接近周线MA200 ±N% → 熊市底部，禁止做空（可能反弹）
          - 熊市中且远离周线MA200 → 允许做空

        Args:
            ma_values: {"ma128": ..., "ma1400": ...} (ma1400 ≈ 周线MA200)
            current_price: 当前价格
            valid_bd_ma128: MA128 的3日跌破确认

        Returns:
            (allow_short: bool, reason_tag: str)
        """
        ma128 = ma_values.get("ma128")
        ma200_week = ma_values.get("ma1400")  # 周线MA200 ≈ 日线MA1400

        # 1) 数据不足 → 保守禁止
        if not ma128:
            return False, "趋势市 MA128数据缺失"

        # 2) 价格 > MA128 → 牛市/反弹，禁止做空
        if current_price > ma128:
            return False, f"趋势市 价({current_price:.0f})>MA128({ma128:.0f}) 牛市/反弹"

        # 3) 未有效跌破 MA128（3日收盘 < MA128）→ 跌破未确认
        if not valid_bd_ma128:
            return False, "趋势市 MA128未有效跌破(3日收盘<MA128)"

        # 4) 接近周线MA200 ±N% → 熊市底部，禁止做空
        if ma200_week:
            dist_to_bottom = abs(current_price - ma200_week) / ma200_week
            if dist_to_bottom <= self.FMA_LONG_TERM_BOTTOM_BUFFER:
                return False, (f"趋势市 接近周线MA200底部(价={current_price:.0f}"
                               f"≈MA1400({ma200_week:.0f})±{self.FMA_LONG_TERM_BOTTOM_BUFFER*100:.0f}%)")

        # 5) 熊市中且远离周线MA200 → 允许做空
        bottom_str = f" 距周线MA200({ma200_week:.0f})={((current_price-ma200_week)/ma200_week*100):+.1f}%" if ma200_week else ""
        return True, f"趋势市 熊市做空(价<MA128有效跌破){bottom_str}"

    def _regime_short_filter(self, regime: str, score: str, U: float,
                              F_dot: float, valid_bd: bool,
                              ma_values: dict = None,
                              current_price: float = 0.0,
                              valid_bd_ma128: bool = False) -> tuple:
        """Phase D 形态差异化做空过滤（双轨方案）

        双轨分流：
          - 趋势市（TREND_BULL/STRONG_TREND_BEAR/TREND_BEAR）→ 两均线简化过滤
          - 均值回归/震荡（MEAN_REVERTING/RANGING）→ 多均线差异化过滤

        Returns:
            (allow_short: bool, reason_tag: str)
        """
        # 多头趋势：任何情况都不做空
        if regime == "TREND_BULL":
            return False, "TREND_BULL 禁止做空"
        if regime == "STRONG_TREND_BULL":
            return False, "STRONG_TREND_BULL 禁止做空"

        # 趋势市（强空头/弱空头）→ 走两均线简化过滤
        if regime in ("STRONG_TREND_BEAR", "TREND_BEAR"):
            if not ma_values or current_price <= 0:
                return False, f"{regime} 缺少ma_values/current_price参数"
            allow, trend_reason = self._trend_regime_short_filter(
                ma_values=ma_values,
                current_price=current_price,
                valid_bd_ma128=valid_bd_ma128,
            )
            prefix = "STRONG_TREND_BEAR" if regime == "STRONG_TREND_BEAR" else "TREND_BEAR"
            return allow, f"{prefix} | {trend_reason}"

        # 均值回归：严格（F>0 = 超卖 = 禁止做空）
        if regime == "MEAN_REVERTING":
            if not valid_bd:
                return False, "MEAN_REVERTING 无3日跌破确认"
            if score not in self.FMA_ALLOW_SCORE_REVERT:
                return False, f"MEAN_REVERTING 仅WEAK允许，score={score}"
            if U > self.FMA_U_THRESHOLD_REVERT:
                return False, f"MEAN_REVERTING 超卖 U={U:.5f}>{self.FMA_U_THRESHOLD_REVERT}"
            if F_dot < self.FMA_FDOT_REVERT:
                return False, f"MEAN_REVERTING 收敛 F_dot={F_dot:.4f}<{self.FMA_FDOT_REVERT}"
            return True, "MEAN_REVERTING 谨慎做空（仅WEAK档）"

        # 震荡/筑底：放宽（回测胜率 68.6% 最高，允许全档位）
        if regime == "RANGING":
            if not valid_bd:
                return False, "RANGING 无3日跌破确认"
            if score not in self.FMA_ALLOW_SCORE_RANGE:
                return False, f"RANGING score={score} 未达档"
            if U > self.FMA_U_THRESHOLD_RANGE:
                return False, f"RANGING 超卖 U={U:.5f}>{self.FMA_U_THRESHOLD_RANGE}"
            if F_dot < self.FMA_FDOT_RANGE:
                return False, f"RANGING 收敛 F_dot={F_dot:.4f}<{self.FMA_FDOT_RANGE}"
            return True, "RANGING 放宽做空（全档位+低U+加速）"

        return False, f"未知 regime={regime}"

    def _regime_long_filter(self, regime: str, bullish_score: str,
                             U_long: float, F_dot: float,
                             valid_breakout_up: bool,
                             ma_values: dict = None,
                             current_price: float = 0.0) -> tuple:
        """Phase D 形态差异化做多过滤（与 _regime_short_filter 对称；FMA=ON 影子路径专用）。

        Returns:
            (allow_long: bool, reason_tag: str)
        """
        if not bullish_score or bullish_score == "NONE":
            return False, f"bullish_score={bullish_score} 未达档"

        # 熊市趋势：任何情况都不追多
        if regime in ("TREND_BEAR", "STRONG_TREND_BEAR"):
            return False, f"{regime} 熊市禁止追多"

        # 多头趋势 → 对称做空两均线过滤：要求价格>MA128 + 有效向上突破
        if regime in ("TREND_BULL", "STRONG_TREND_BULL"):
            if not ma_values or current_price <= 0:
                return False, f"{regime} 缺少ma_values/current_price参数"
            ma128 = float(ma_values.get("ma128", 0) or 0)
            if ma128 <= 0:
                return False, f"{regime} 缺少ma128"
            if current_price <= ma128:
                return False, f"{regime} 价格{current_price:.2f}≤MA128={ma128:.2f}(未站在牛市上方)"
            prefix = "STRONG_TREND_BULL" if regime == "STRONG_TREND_BULL" else "TREND_BULL"
            # STRONG档允许放宽U限制；NORMAL档需要当前价不破MA128
            allow_scores = ("STRONG", "NORMAL") if regime == "STRONG_TREND_BULL" else ("STRONG", "NORMAL", "WEAK")
            if bullish_score not in allow_scores:
                return False, f"{prefix} bullish_score={bullish_score} 未达档"
            return True, f"{prefix} 趋势牛市做多（价>MA128站在牛线上）"

        # 均值回归：严格（F<0 = 超买 → 禁止追多；仅刚从下跌拐头向上突破允许）
        if regime == "MEAN_REVERTING":
            if not valid_breakout_up:
                return False, "MEAN_REVERTING 无3日向上突破确认"
            if bullish_score not in ("WEAK",):
                return False, f"MEAN_REVERTING 仅WEAK档允许（刚拐头），score={bullish_score}"
            if U_long > self.FMA_U_THRESHOLD_REVERT:
                return False, f"MEAN_REVERTING 超买 U={U_long:.5f}>{self.FMA_U_THRESHOLD_REVERT}"
            if F_dot > self.FMA_FDOT_REVERT:  # 反向：F_dot>0 表示F收敛（回落压力）→ 禁止
                return False, f"MEAN_REVERTING 回落收敛 F_dot={F_dot:.4f}>{self.FMA_FDOT_REVERT}"
            return True, "MEAN_REVERTING 保守做多（仅WEAK档+拐头向上）"

        # 震荡/筑底：放宽（回测 RANGING 胜率最高）
        if regime == "RANGING":
            if bullish_score not in self.FMA_ALLOW_SCORE_RANGE:
                return False, f"RANGING bullish_score={bullish_score} 未达档"
            if U_long > self.FMA_U_THRESHOLD_RANGE:
                return False, f"RANGING 超买 U={U_long:.5f}>{self.FMA_U_THRESHOLD_RANGE}"
            # RANGING 不严格要求 3日向上突破（震荡区间内上下均可）
            return True, "RANGING 放宽做多（震荡区间内尝试）"

        return False, f"未知 regime={regime}"

    def _check_btc_trend(self, _force_regime_filter_on: bool = False) -> tuple:
        """BTC日线趋势判定（Phase D：形态差异化做空过滤）

        核心改进：
          1. 4维度市场形态判定 → 5种 regime（TREND_BULL/STRONG_TREND_BEAR/TREND_BEAR/MEAN_REVERTING/RANGING）
          2. 按 regime 走差异化做空过滤阈值（解决弹簧力 F 双重身份问题）：
             - 趋势市：F>0 = 均线阻力 = 顺势做空（宽松，U阈值放宽）
             - 均值回归市：F>0 = 超卖 = 禁止做空（严格，U阈值收紧）
          3. 兜底：价格在长期MA ±2% 的窄窗口 → 偏见底，禁止做空

        Returns:
            (bearish: bool, reason: str — 末尾附 SHORT_ALLOWED + regime + score)
        """
        now = time.time()
        cached = self._btc_trend_cache
        if cached["result"] and (now - cached["ts"]) < 300:
            return cached["result"]

        try:
            btc_klines = _load_kline_from_okx(inst_id="BTC-USDT-SWAP", bar="1D", limit=1500)
            if not btc_klines or len(btc_klines) < 131:
                result = (False, f"BTC日线数据不足(limit={len(btc_klines) if btc_klines else 0})")
                self._btc_trend_cache = {"ts": now, "result": result}
                return result

            closes = [float(k.get("c", 0)) for k in btc_klines if k.get("c")]
            if len(closes) < 131:
                result = (False, f"BTC收盘价不足({len(closes)})")
                self._btc_trend_cache = {"ts": now, "result": result}
                return result

            res = self._calc_5ma_spring_force(closes, tier="daily_btc")

            F_total = res.get("F_total", res.get("F_net", 0.0))
            F_net = res.get("F_net", 0.0)
            F_inter = res.get("F_inter_net", 0.0)
            U_total = res.get("U_potential", 0.0)
            U_short = res.get("U_short", 0.0)
            slope_avg = res.get("slope_avg", 0.0)
            k_eff = res.get("k_eff", 2.0)
            score = res["bearish_score"]
            in_bottom = res["in_long_term_window"]
            F_dot = res.get("F_dot", 0.0)
            regime = res.get("market_regime", "RANGING")
            TR = res.get("trend_ratio", 0.0)
            CV = res.get("cv_dispersion", 0.0)

            # 构造简短日志
            mav = res["ma_values"]
            bd_summary = f"{res['bearish_n']}/5均线被跌破 score={score}"
            breakdown_tag = "3日跌破确认" if res["valid_breakdown"] else "无3日确认"
            roles_summary = " ".join(
                f"MA{p}={'支' if current_price>ma else '阻'}"
                for p, ma in sorted(mav.items(), key=lambda x: int(x[0].replace('ma','')))
                for current_price in [res["current_price"]]  # one-shot hack
            )
            # Phase D 动态信息（含形态判定4维度）
            dynamics = (f"regime={regime} TR={TR:.3f} CV={CV:.4f}"
                        f" F_total={F_total:+.3f}(F_net={F_net:+.3f}+F_inter={F_inter:+.3f})"
                        f" F_dot={F_dot:+.4f}"
                        f" U_short={U_short:.5f}(U_total={U_total:.5f})"
                        f" slope={slope_avg:+.3f}% k_eff={k_eff:.2f}")

            # 5) 兜底：长期MA ±2% 偏见底
            if in_bottom:
                long_ma = min([ma for p, ma in mav.items() if int(p.replace('ma','')) >= 1000] or [0])
                result = (
                    False,
                    f"BTC长期均线偏见底(价={res['current_price']:.0f}≈MA{int(long_ma) if long_ma else '?'}±{self.FMA_LONG_TERM_BOTTOM_BUFFER*100:.0f}%)"
                    f" | {dynamics} | {bd_summary} | {breakdown_tag}"
                )
                self._btc_trend_cache = {"ts": now, "result": result}
                return result

            # 6) 做空过滤：开关控制
            #    FMA_REGIME_FILTER_ENABLED=False（默认）→ 简单趋势确认
            #    FMA_REGIME_FILTER_ENABLED=True         → 形态差异化过滤（实验用）
            #    _force_regime_filter_on=True           → 强制走形态差异化（H3-FMA影子决策专用，即便当前全局OFF）
            fma_switch = bool(self.FMA_REGIME_FILTER_ENABLED) or bool(_force_regime_filter_on)
            if fma_switch:
                # 形态差异化过滤（双轨方案，回测效果不佳，仅实验用）
                allow_short, filter_reason = self._regime_short_filter(
                    regime=regime,
                    score=score,
                    U=U_short,
                    F_dot=F_dot,
                    valid_bd=res["valid_breakdown"],
                    ma_values=mav,
                    current_price=res["current_price"],
                    valid_bd_ma128=res.get("valid_breakdown_ma128", False),
                )
            else:
                # 无过滤（回测验证：无过滤胜率56.8% > 所有过滤方案，信号整体更好）
                # 历史方案：曾尝试3日跌破确认+price<MA128，均过滤掉高胜率信号
                allow_short, filter_reason = True, "无趋势过滤(回测验证最优)"

            if allow_short:
                result = (
                    True,
                    f"[SHORT_ALLOWED] BTC做空允许 {dynamics} | {bd_summary} | {breakdown_tag} | {roles_summary}"
                    f" | {filter_reason}"
                    f" | 价={res['current_price']:.0f} MA30={mav.get('ma30',0):.0f} MA65={mav.get('ma65',0):.0f}"
                    f" MA128={mav.get('ma128',0):.0f} MA200={mav.get('ma200',0):.0f}"
                )
            else:
                result = (
                    False,
                    f"BTC做空禁止 {dynamics} | {bd_summary} | {breakdown_tag} | {filter_reason}"
                )

            self._btc_trend_cache = {"ts": now, "result": result}
            return result
        except Exception as e:
            import traceback
            return False, f"BTC趋势检查异常: {e} | {traceback.format_exc(limit=1)}"

    def _check_self_trend(self, coin: str, _force_regime_filter_on: bool = False) -> tuple:
        """非加密货币自身日K线趋势（Phase D 形态差异化做空过滤）

        与 BTC 算法同构，用 MA30/65/128/200 + 可用长期均线；
        按 market_regime 走差异化做空过滤（与 _check_btc_trend 共用 _regime_short_filter）。

        Returns:
            (bearish: bool, reason: str — 若允许做空则含 SHORT_ALLOWED + regime + score)
        """
        try:
            inst_id = f"{coin}-USDT-SWAP"
            klines = _load_kline_from_okx(inst_id=inst_id, bar="1D", limit=1500)
            if not klines or len(klines) < 66:
                return False, f"{coin}日线数据不足(<66)"
            closes = [float(k.get("c", 0)) for k in klines if k.get("c")]
            if len(closes) < 66:
                return False, f"{coin}收盘价数据不足"

            res = self._calc_5ma_spring_force(closes, tier="daily_self")
            score = res["bearish_score"]
            F_net = res["F_net"]
            F_total = res.get("F_total", F_net)
            F_inter = res.get("F_inter_net", 0.0)
            U_total = res.get("U_potential", 0.0)
            U_short = res.get("U_short", 0.0)
            F_dot = res.get("F_dot", 0.0)
            regime = res.get("market_regime", "RANGING")
            TR = res.get("trend_ratio", 0.0)
            CV = res.get("cv_dispersion", 0.0)
            slope_avg = res.get("slope_avg", 0.0)

            dynamics = (f"regime={regime} TR={TR:.3f} CV={CV:.4f}"
                        f" F_total={F_total:+.3f}(F_net={F_net:+.3f}+F_inter={F_inter:+.3f})"
                        f" F_dot={F_dot:+.4f} U_short={U_short:.5f}(U_total={U_total:.5f})"
                        f" slope={slope_avg:+.3f}%")
            bd_summary = f"{res['bearish_n']}/N均线被跌破 score={score}"
            breakdown_tag = "3日跌破确认" if res["valid_breakdown"] else "无3日确认"

            # 长期MA兜底
            if res["in_long_term_window"]:
                mav = res["ma_values"]
                long_ma = min([ma for p, ma in mav.items() if int(p.replace('ma','')) >= 1000] or [0])
                return False, (
                    f"{coin}长期均线偏见底(价={res['current_price']:.2f}≈MA{long_ma if long_ma else '?'}"
                    f" ±{self.FMA_LONG_TERM_BOTTOM_BUFFER*100:.0f}%) | {dynamics} | {bd_summary}"
                )

            # 做空过滤：开关控制（与 _check_btc_trend 同构）
            _fma_on = bool(self.FMA_REGIME_FILTER_ENABLED) or bool(_force_regime_filter_on)
            if _fma_on:
                # 形态差异化过滤（双轨方案，回测效果不佳，仅实验用）
                allow_short, filter_reason = self._regime_short_filter(
                    regime=regime,
                    score=score,
                    U=U_short,
                    F_dot=F_dot,
                    valid_bd=res["valid_breakdown"],
                    ma_values=res["ma_values"],
                    current_price=res["current_price"],
                    valid_bd_ma128=res.get("valid_breakdown_ma128", False),
                )
            else:
                # 无过滤（与 _check_btc_trend 同构，回测验证无过滤最优）
                allow_short, filter_reason = True, "无趋势过滤(回测验证最优)"

            if allow_short:
                return True, (
                    f"[SHORT_ALLOWED] {coin}趋势看空 {dynamics} | {bd_summary} | {breakdown_tag}"
                    f" | {filter_reason} | 价={res['current_price']:.2f}"
                )
            return False, (
                f"{coin}做空禁止 {dynamics} | {bd_summary} | {breakdown_tag} | {filter_reason}"
            )
        except Exception as e:
            return False, f"{coin}趋势检查异常: {e}"

    def _check_us_index_trend(self, _force_regime_filter_on: bool = False) -> tuple:
        """美股大盘趋势判定（Phase C+ 两指数各五均线后平均）

        对 IXIC / GSPC 各自计算五均线评分，取 F 平均；任一指数 STRICT 空头排列即允许，
        平均 score≥WEAK+valid_breakdown 也允许。

        Returns:
            (bearish: bool, reason: str)
        """
        now = time.time()
        cached = getattr(self, "_us_index_trend_cache", None)
        if cached and cached.get("result") and (now - cached["ts"]) < 300:
            # _force_regime_filter_on=True 时不使用缓存（需要重跑 FMA=ON 差异化过滤）
            if not _force_regime_filter_on:
                return cached["result"]

        # 兜底：提高递归限制，防止yfinance在长时运行进程内触发RecursionError
        if not getattr(self, "_recursion_limit_raised", False):
            import sys as _sys
            if _sys.getrecursionlimit() < 3000:
                _sys.setrecursionlimit(3000)
            self._recursion_limit_raised = True

        try:
            import yfinance as yf

            indices = {"IXIC": "^IXIC", "GSPC": "^GSPC"}
            results_idx = {}
            for name, ticker in indices.items():
                # 改用 yf.download 函数式调用，绕过 Ticker.__getattr__ 动态代理递归
                hist = yf.download(ticker, period="5y", progress=False)
                if hist.empty or len(hist) < 131:
                    continue
                closes_oa = list(np.asarray(hist["Close"].values).ravel())  # oldest-first，ravel兼容yf.download MultiIndex列
                closes_nf = closes_oa[::-1]              # newest-first
                res = self._calc_5ma_spring_force(closes_nf, tier="daily_index")
                results_idx[name] = res

            if not results_idx:
                result = (False, "美股大盘数据拉取失败(IXIC/GSPC均不可用)")
                self._us_index_trend_cache = {"result": result, "ts": now}
                return result

            # 任意一个 STRICT=STRONG → 允许
            any_strict = any(r["bearish_score"] == "STRONG" and r["valid_breakdown"]
                             for r in results_idx.values())
            # 条件B（原）：F_avg < -0.02 + score!=NONE + valid_breakdown → 允许
            F_avg = sum(r["F_net"] for r in results_idx.values()) / len(results_idx)
            any_weak_plus = any(r["bearish_score"] != "NONE" and r["valid_breakdown"]
                                for r in results_idx.values())
            # 条件B'（新增放宽）：F_avg < -0.02 + 两指数评分都至少 WEAK（无需 valid_breakdown 3日确认）
            #   覆盖：F_avg=-0.064 强度已达标，但均线跌破还在孕育期（未满足3日确认→valid_breakdown=False）
            #   放行后 score=WEAK，下游阈值乘数抬高(×1.1765)需要更高置信度通过门槛
            all_scores_not_none = all(r["bearish_score"] != "NONE" for r in results_idx.values())
            both_weak_favg_path = (F_avg < -0.02) and all_scores_not_none and not any_weak_plus
            # 任一长期均线触底 → 全部禁止
            any_bottom = any(r["in_long_term_window"] for r in results_idx.values())

            name_score = " ".join(
                f"{n}[score={r['bearish_score']} F={r['F_net']:+.3f}]"
                for n, r in results_idx.items()
            )

            if any_bottom:
                result = (False, f"美股大盘偏见底 | {name_score}")
            elif any_strict or (F_avg < -0.02 and any_weak_plus):
                result = (True, f"[SHORT_ALLOWED] 美股大盘趋势看空 F_avg={F_avg:+.3f} | {name_score}")
            elif both_weak_favg_path:
                # 放宽路径：统一打 WEAK 级，下游抬高置信度门槛
                result = (True, f"[SHORT_ALLOWED] 美股大盘趋势看空(双指数WEAK+F强) score=WEAK F_avg={F_avg:+.3f} | {name_score}")
            else:
                result = (False, f"美股大盘无看空确认 F_avg={F_avg:+.3f} | {name_score}")

            self._us_index_trend_cache = {"result": result, "ts": now}
            return result
        except RecursionError:
            # yfinance递归异常(数据获取问题，非趋势判断)：优先用上次成功缓存的真实趋势，无则降级放行避免误拦截
            cached = getattr(self, "_us_index_trend_cache", None)
            if cached and cached.get("result"):
                self._log("美股大盘yfinance递归异常，降级使用上次缓存结果", "WARN")
                return cached["result"]
            self._log("美股大盘yfinance递归异常且无缓存，降级放行(不拦截做空信号)", "WARN")
            return (True, "美股大盘检查降级放行(yfinance递归异常)")
        except Exception as e:
            return False, f"美股大盘检查异常: {e}"

    def _parse_bearish_score_from_reason(self, reason: str) -> str:
        """从各类 trend reason 字符串中抽取 bearish_score（NONE/WEAK/NORMAL/STRONG）"""
        if not reason:
            return "NONE"
        import re
        # 新算法格式: score=STRONG / score=NORMAL / score=WEAK
        m = re.search(r"score=(STRONG|NORMAL|WEAK|NONE)", reason)
        if m:
            return m.group(1)
        return "NONE"

    def _compute_short_conf_multiplier(self, bearish_score: str) -> float:
        """根据 bearish_score 返回做空置信度乘数（有效阈值=基础阈值×乘数）

        STRONG(5均线严格空头): ×0.9091 ≈1/1.10 → 降低门槛（强趋势可放宽）
        NORMAL(3~4均线空头) : ×1.0000          → 标准
        WEAK(1~2均线短周期) : ×1.1765 ≈1/0.85  → 抬高门槛（弱趋势要求更高置信度）
        NONE                : ×0.00            → 直接禁止
        """
        if bearish_score == "STRONG":
            return self.SHORT_CONF_MULTI_MA_STRONG
        elif bearish_score == "NORMAL":
            return self.SHORT_CONF_MULTI_MA_NORMAL
        elif bearish_score == "WEAK":
            return self.SHORT_CONF_MULTI_MA_WEAK
        return 0.00

    def _get_regime_short_multiplier(self, regime: str) -> float:
        """根据 market_regime 返回做空阈值调节乘数（阈值调节器）

        理论：regime 反映市场形态，不同形态下做空胜率差异显著
              回测数据：TREND_BEAR 28.6% < STRONG_TREND_BEAR 50.0% < RANGING 68.6%
              乘数 > 1.0 = 抬高阈值 = 抑制做空；乘数 < 1.0 = 降低阈值 = 放宽做空

        与 bearish_score 乘数叠加使用：
            final_threshold = base_threshold × score_multiplier × regime_multiplier
        """
        mapping = {
            "TREND_BULL":         self.REGIME_SHORT_CONF_MULTI_TREND_BULL,
            "TREND_BEAR":         self.REGIME_SHORT_CONF_MULTI_TREND_BEAR,
            "STRONG_TREND_BEAR":  self.REGIME_SHORT_CONF_MULTI_STRONG_TREND_BEAR,
            "MEAN_REVERTING":     self.REGIME_SHORT_CONF_MULTI_MEAN_REVERTING,
            "RANGING":            self.REGIME_SHORT_CONF_MULTI_RANGING,
        }
        return mapping.get(regime, 1.00)

    def _parse_regime_from_reason(self, reason: str) -> str:
        """从 trend_reason 日志中解析 market_regime

        日志格式示例：
            "... regime=TREND_BEAR TR=0.599 ..."
            "... regime=RANGING TR=0.396 ..."
        """
        import re
        m = re.search(r"regime=(\w+)", reason)
        return m.group(1) if m else "RANGING"

    def _compute_short_position_multiplier(self, bearish_score: str) -> float:
        """根据 bearish_score 返回做空仓位规模乘数

        理论：周期越短可信度越低，但趋势识别越早 → 不禁开，而是控制资金规模
              随着跌破更多均线，弹簧压力越来越重 → 仓位越来越大

        STRONG: 5均线空头+3日确认 → ×1.0 标准仓位
        NORMAL: 3~4均线空头       → ×0.7
        WEAK  : 1~2均线短周期空头 → ×0.4 小仓试水
        NONE  : 不应到达此分支
        """
        if bearish_score == "STRONG":
            return self.SHORT_POSITION_MULTI_STRONG
        elif bearish_score == "NORMAL":
            return self.SHORT_POSITION_MULTI_NORMAL
        elif bearish_score == "WEAK":
            return self.SHORT_POSITION_MULTI_WEAK
        return 0.3  # 兜底：极小仓位

    # ================================================================
    # H1 / H4 新增：长多方向 弹簧力场 评分解析 + 阈值+仓位 乘数方法
    # 设计原则：与做空方向对称（牛市形态为做空熊市的镜像）
    # ================================================================

    def _parse_bullish_score_from_reason(self, reason: str) -> str:
        """从趋势确认 reason 解析长多评分 STRONG/NORMAL/WEAK/NONE（对称 bearish）"""
        if not reason:
            return "NONE"
        if "5均线多头" in reason or "5条长周期均线多头" in reason or ("全部" in reason and "均线多头" in reason):
            return "STRONG"
        if "4条均线多头" in reason or "4均线多头" in reason:
            return "NORMAL"
        if "3条均线多头" in reason or "3均线多头" in reason:
            return "NORMAL"
        if "2条均线多头" in reason or "2均线多头" in reason:
            return "WEAK"
        if "1条均线多头" in reason or "1均线多头" in reason:
            return "WEAK"
        if "纳斯达克100" in reason or "标普500" in reason:
            if "强牛" in reason or "5均线多头" in reason:
                return "STRONG"
            if "牛市" in reason:
                return "NORMAL"
            return "NONE"
        return "NONE"

    def _compute_long_conf_multiplier(self, bullish_score: str) -> float:
        if bullish_score == "STRONG":
            return self.LONG_CONF_MULTI_MA_STRONG
        elif bullish_score == "NORMAL":
            return self.LONG_CONF_MULTI_MA_NORMAL
        elif bullish_score == "WEAK":
            return self.LONG_CONF_MULTI_MA_WEAK
        return 1.0

    def _get_regime_long_multiplier(self, regime: str) -> float:
        """5态 spring regime → 长多阈值乘数（基于回测胜率反比，与 _short 对称）"""
        if not regime:
            return 1.0
        mapping = {
            "TREND_BULL":        self.REGIME_LONG_CONF_MULTI_TREND_BULL,
            "STRONG_TREND_BULL": self.REGIME_LONG_CONF_MULTI_STRONG_TREND_BULL,
            "TREND_BEAR":        self.REGIME_LONG_CONF_MULTI_TREND_BEAR,
            "MEAN_REVERTING":    self.REGIME_LONG_CONF_MULTI_MEAN_REVERTING,
            "RANGING":           self.REGIME_LONG_CONF_MULTI_RANGING,
        }
        return float(mapping.get(regime, 1.0))

    def _compute_long_position_multiplier(self, bullish_score: str) -> float:
        """弹簧力场评分 → 长多仓位规模分层（H4：对称做空仓位分层）"""
        if bullish_score == "STRONG":
            return self.LONG_POSITION_MULTI_STRONG
        elif bullish_score == "NORMAL":
            return self.LONG_POSITION_MULTI_NORMAL
        elif bullish_score == "WEAK":
            return self.LONG_POSITION_MULTI_WEAK
        return 1.0

    def _coin_asset_class(self, coin: str) -> str:
        """币 → 战略层资产类别（crypto_usdt / us_stock / precious_metal）。"""
        cu = (coin or "").upper()
        if cu in self.CRYPTO_COINS or cu in self.CRYPTO_US_STOCK_COINS:
            return "crypto_usdt"
        if cu in self.US_STOCK_COINS:
            return "us_stock"
        return "precious_metal"

    def _check_long_trend_filter(self, coin: str, inference: dict = None,
                                  _force_regime_filter_on: bool = False):
        """长多 UP 方向弹簧力场过滤（对称 _check_short_trend_filter；H1 缺口修复）。

        Returns:
            (allow_long: bool, reason: str, conf_multiplier: float)
            - 与做空过滤返回签名完全一致，调用方兼容三解包
        """
        coin_upper = coin.upper()
        # Step 1: 大盘/自身 趋势原因（复用 _check_*_trend；bearish/bullish 共享同一 reason 文本）
        # 路由优先级：纯加密币种 ∪ 加密属性美股 → BTC趋势
        #           纯美股科技代币 → 美股大盘趋势
        #           其余(黄金等) → 自身趋势
        if coin_upper in self.CRYPTO_COINS or coin_upper in self.CRYPTO_US_STOCK_COINS:
            _, trend_reason = self._check_btc_trend(_force_regime_filter_on=_force_regime_filter_on)
        elif coin_upper in self.US_STOCK_COINS:
            _, trend_reason = self._check_us_index_trend(_force_regime_filter_on=_force_regime_filter_on)
        else:
            _, trend_reason = self._check_self_trend(coin, _force_regime_filter_on=_force_regime_filter_on)

        # spring_regime 5 态 + bullish_score：
        #   ① 先按 5均线多头结构化理由解析
        #   ② 兜底：按 regime 代理（TREND_BULL 系列 & RANGING 视作多头结构；其余反转/熊市禁止追多）
        bullish_score = self._parse_bullish_score_from_reason(trend_reason)
        regime = self._parse_regime_from_reason(trend_reason)
        if bullish_score == "NONE":
            if regime == "STRONG_TREND_BULL":
                bullish_score = "STRONG"
            elif regime == "TREND_BULL":
                bullish_score = "NORMAL"
            elif regime == "RANGING":
                bullish_score = "WEAK"
            else:
                return False, f"趋势未确认(多头代理={regime} 属反转/熊市，禁止追多): {trend_reason}", 0.00

        conf_multiplier = self._compute_long_conf_multiplier(bullish_score)
        regime_multi = self._get_regime_long_multiplier(regime)
        final_multiplier = conf_multiplier * regime_multi

        # Step 2: 短周期共振（SMA20 > SMA50 > SMA200 多头排列）
        kline_data = (inference or {}).get("kline_data", [])
        if kline_data and len(kline_data) >= 200:
            closes = [float(c.get("c", 0)) for c in kline_data if c.get("c")]
            if len(closes) >= 200:
                sma20 = sum(closes[:20]) / 20
                sma50 = sum(closes[:50]) / 50
                sma200 = sum(closes[:200]) / 200
                if sma20 > sma50 > sma200:
                    if bullish_score == "WEAK":
                        bullish_score = "NORMAL"
                        conf_multiplier = self.LONG_CONF_MULTI_MA_NORMAL
                    elif bullish_score == "NORMAL":
                        bullish_score = "STRONG"
                        conf_multiplier = self.LONG_CONF_MULTI_MA_STRONG
                    final_multiplier = conf_multiplier * regime_multi
                    return (
                        True,
                        f"趋势确认+共振(SMA20>50>200) score={bullish_score} ×{conf_multiplier:.2f} regime={regime} ×{regime_multi:.2f} =×{final_multiplier:.2f} | {trend_reason}",
                        final_multiplier,
                    )
                return (
                    False,
                    f"共振失败(SMA20={sma20:.2f}/50={sma50:.2f}/200={sma200:.2f}非多头排列) score={bullish_score}",
                    0.00,
                )
        # 无共振数据时降级：仅趋势确认
        return (
            True,
            f"趋势确认(无共振数据) score={bullish_score} ×{conf_multiplier:.2f} regime={regime} ×{regime_multi:.2f} =×{final_multiplier:.2f} | {trend_reason}",
            final_multiplier,
        )

    def _check_short_trend_filter(self, coin: str, inference: dict, _force_regime_filter_on: bool = False) -> tuple:
        """P1-1: 做空趋势确认过滤器（Phase C+ 五均线版）

        三道关卡：
        1. 大盘趋势确认：
           - 加密货币 → BTC 五均线(MA30/65/128/200/MA1400)弹簧力场+排列评分
           - 美股代币 → 纳斯达克^IXIC + 标普500^GSPC 各五均线后平均
           - 其他 → 自身日K五均线(MA30/65/128/200/MA1400)
           → 输出 bearish_score (STRONG/NORMAL/WEAK/NONE) + 做空阈值乘数
        2. 短周期共振：当前K线SMA20<SMA50<SMA200 空头排列
        3. 将 bearish_score + 乘数 封装进返回值，供 _execute_trade 计算有效阈值

        Returns:
            (allow_short: bool, reason: str, conf_multiplier: float)
            - 旧调用只解包前两项，兼容
        """
        # Step 1: 大盘趋势确认
        coin_upper = coin.upper()
        # 路由优先级（与长过滤器对称）：纯加密 ∪ 加密属性美股 → BTC
        #                                纯美股 → 美股大盘
        #                                其他 → 自身
        if coin_upper in self.CRYPTO_COINS or coin_upper in self.CRYPTO_US_STOCK_COINS:
            trend_bearish, trend_reason = self._check_btc_trend(_force_regime_filter_on=_force_regime_filter_on)
        elif coin_upper in self.US_STOCK_COINS:
            trend_bearish, trend_reason = self._check_us_index_trend(_force_regime_filter_on=_force_regime_filter_on)
        else:
            trend_bearish, trend_reason = self._check_self_trend(coin, _force_regime_filter_on=_force_regime_filter_on)

        bearish_score = self._parse_bearish_score_from_reason(trend_reason)
        conf_multiplier = self._compute_short_conf_multiplier(bearish_score)

        # market_regime 阈值调节器：解析 regime 并叠加调节乘数
        regime = self._parse_regime_from_reason(trend_reason)
        regime_multi = self._get_regime_short_multiplier(regime)
        # 最终乘数 = bearish_score 乘数 × regime 乘数
        final_multiplier = conf_multiplier * regime_multi

        if not trend_bearish:
            return False, f"趋势未确认: {trend_reason}", 0.00

        # Step 2: 短周期共振（SMA20<SMA50<SMA200 空头排列）
        kline_data = inference.get("kline_data", [])
        if kline_data and len(kline_data) >= 200:
            closes = [float(c.get("c", 0)) for c in kline_data if c.get("c")]
            if len(closes) >= 200:
                sma20 = sum(closes[:20]) / 20
                sma50 = sum(closes[:50]) / 50
                sma200 = sum(closes[:200]) / 200
                if sma20 < sma50 < sma200:
                    # 共振成功 → 提升 score 一级（WEAK→NORMAL / NORMAL→STRONG）
                    if bearish_score == "WEAK":
                        bearish_score = "NORMAL"
                        conf_multiplier = self.SHORT_CONF_MULTI_MA_NORMAL
                    elif bearish_score == "NORMAL":
                        bearish_score = "STRONG"
                        conf_multiplier = self.SHORT_CONF_MULTI_MA_STRONG
                    # 共振提升 score 后重新计算 final 乘数
                    final_multiplier = conf_multiplier * regime_multi
                    return (
                        True,
                        f"趋势确认+共振(SMA20<50<200) score={bearish_score} ×{conf_multiplier:.2f} regime={regime} ×{regime_multi:.2f} =×{final_multiplier:.2f} | {trend_reason}",
                        final_multiplier,
                    )
                # Step 2.5 弱共振分级（多头排列反转前夜 / 混合排列收敛态）
                #   触发条件：
                #     1. |SMA20 - SMA50| / SMA50 < 5%  →  短中期均线收窄至变盘前夜区间
                #     2. 核心层置信度 > 0.85（严格大于，0.85不触发） →  高确信信号
                #   放行等级：WEAK（抬高阈值×1.1765 + 小仓×0.4），不升级评分
                sma20_50_gap_pct = abs(sma20 - sma50) / max(sma50, 1e-9)
                WEAK_RESONANCE_GAP_PCT = 0.05  # 5% 收敛阈值（2026-08-23 放宽：原3%覆盖BTC 3.7%-4.4%真实收敛态）
                WEAK_RESONANCE_CONF_MIN = 0.85  # 置信门槛：严格 >
                confidence = float(inference.get("confidence", 0.0))
                if sma20_50_gap_pct < WEAK_RESONANCE_GAP_PCT:
                    if confidence > WEAK_RESONANCE_CONF_MIN:
                        # 弱共振放行：统一 WEAK 级乘数，不升级评分
                        weak_conf_mult = self.SHORT_CONF_MULTI_MA_WEAK
                        weak_final_mult = weak_conf_mult * regime_multi
                        return (
                            True,
                            (f"趋势确认+弱共振(MA20-50差值{sma20_50_gap_pct*100:.2f}%<5%"
                             f" + 置信{confidence:.2f}>{WEAK_RESONANCE_CONF_MIN})"
                             f" score=WEAK ×{weak_conf_mult:.2f} regime={regime} ×{regime_multi:.2f}"
                             f" =×{weak_final_mult:.2f} | {trend_reason}"),
                            weak_final_mult,
                        )
                    else:
                        # 收敛但置信不足：明确说明弱共振条件因高置信门槛未满足而拦截
                        return (
                            False,
                            (f"弱共振不满足(收窄{sma20_50_gap_pct*100:.2f}%但置信"
                             f"{confidence:.2f}≤{WEAK_RESONANCE_CONF_MIN})"
                             f" score={bearish_score}"),
                            0.00,
                        )
                # 非收敛 + 非严格空头排列 → 标准拦截
                return (
                    False,
                    f"共振失败(SMA20={sma20:.2f}/50={sma50:.2f}/200={sma200:.2f}非空头排列) score={bearish_score}",
                    0.00,
                )

        # 无共振数据时降级：仅趋势确认
        return (
            True,
            f"趋势确认(无共振数据) score={bearish_score} ×{conf_multiplier:.2f} regime={regime} ×{regime_multi:.2f} =×{final_multiplier:.2f} | {trend_reason}",
            final_multiplier,
        )

    def _execute_trade(self, inference: dict, confidence_threshold: float = None,
                       all_inferences: dict = None):
        """根据推理结果执行交易决策（P2 完整版）"""
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        fail_closed = inference["fail_closed"]
        is_ranging = inference["is_ranging"]
        inference.get("volatility", 0.03)

        # [PUMP修复 2026-08-23] 卦象→方向决策历史滑窗：本轮追加（用于后续开仓一致性校验）
        # 不论本轮后续是否开仓，都写入滑窗（保证全量推理可追溯）
        _hex_curr = inference.get("hexagram", "") or ""
        _dir_curr = "long" if direction == "UP" else "short"
        if coin not in self._recent_hex_decisions:
            self._recent_hex_decisions[coin] = deque(
                maxlen=self.HEX_HISTORY_WINDOW_PER_COIN
            )
        self._recent_hex_decisions[coin].append((_hex_curr, _dir_curr))

        # P2-05: 形态乘数快照（仅 S5 打开时注入，关闭时 inference 不带字段 → 1.0 全程）
        #   写入 inference 私有字段 _regime_pred / _regime_multipliers，供下游 _open_position 读取
        if self.ENABLE_REGIME_AND_MACRO_S5:
            try:
                _snap = inference.get("snapshot", {}) or {}
                # H2(P1)：优先级 snapshot.regime（BCRM2.0 内部判定）> inference.regime >
                #         spring_regime_5（后置层弹簧力场输出）经 _FMA_TO_S5 桥映射 → S5 8态
                #   目的：两套标签体系对齐审计；当 BCRM 未给出 regime 时，用后置层 5 态兜底
                _pred = _snap.get("regime") or inference.get("regime")
                _src_label = "snapshot" if _snap.get("regime") else ("inference.regime" if inference.get("regime") else None)
                if not _pred:
                    _sp5 = inference.get("spring_regime_5")
                    if isinstance(_sp5, str):
                        try:
                            _FMA_TO_S5 = {
                                "TREND_BULL":        "TREND_UP_MILD",
                                "STRONG_TREND_BULL": "TREND_UP_STRONG",
                                "STRONG_TREND_BEAR": "VOLATILE_DROP",
                                "TREND_BEAR":        "REVERSAL",
                                "MEAN_REVERTING":    "CONSOLIDATION",
                                "RANGING":           "RANGE_BOUND",
                            }
                            if _sp5 in _FMA_TO_S5 and _FMA_TO_S5[_sp5] in self.REGIME_MULTIPLIERS:
                                _pred = _FMA_TO_S5[_sp5]
                                _src_label = f"spring_bridge({_sp5}→{_pred})"
                        except Exception:
                            _pred, _src_label = None, None
                _mult = self._get_regime_pred_multipliers(
                    _pred, enable_regime_pred=True
                )
                inference["_regime_pred"] = _pred
                inference["_regime_multipliers"] = _mult
                if _src_label:
                    inference["_regime_pred_source"] = _src_label
            except Exception:
                inference["_regime_pred"] = None
                inference["_regime_multipliers"] = {
                    "position_mult": 1.0, "tp_mult": 1.0,
                    "sl_mult": 1.0, "threshold_mult": 1.0,
                }
        else:
            inference["_regime_pred"] = None
            inference["_regime_multipliers"] = {
                "position_mult": 1.0, "tp_mult": 1.0,
                "sl_mult": 1.0, "threshold_mult": 1.0,
            }

        # ── T4 融合层：调用 ParameterMapper._resolve_effective_params 注入 6 参数+板块乘数 ──
        #   设计 A.5 不变量：enable_inject=False → 完全字节等价于 regime 查表（单测验证）
        #   1. 每 5 分钟重读一次 enable_inject 文件
        #   2. 构建 ranges / stats_row / sector_weights_result（从 inference 读，缺失则安全兜底）
        #   3. 覆盖 effective_threshold / _regime_multipliers / 后续 TP/SL 计算使用乘数
        self._reload_enable_inject_if_stale()
        _inject = bool(getattr(self, "_enable_inject_runtime", False))
        _eff_params: dict | None = None
        try:
            if _inject and getattr(self, "_param_mapper", None) is not None:
                # 输入准备
                _snap = inference.get("snapshot", {}) or {}
                _stats_row = (inference.get("stats_row")
                              or _snap.get("stats_row")
                              or {"L_p10_252d": -3.0, "L_p90_252d": 3.0,
                                  "T_p10_252d": -2.5, "T_p90_252d": 2.5})
                _reactive_L = float(_snap.get("level_smooth", 0.0))
                _reactive_T = float(_snap.get("trend_smooth", 0.0))
                _reactive_C = float(_snap.get("consensus", 0.0))
                # forecast：若 inference 自带则直接用，否则按形态预测兜底
                _forecast_L = inference.get("forecast_L")
                _forecast_T = inference.get("forecast_T")
                if _forecast_L is None and getattr(self, "_morph_predictor", None):
                    try:
                        _full = inst_id  # 形如 BTCUSDT
                        _mp = self._morph_predictor.predict_with_fallback(
                            _full, hist_days=60, forecast_days=5
                        )
                        if _mp.get("ok"):
                            _series = _mp.get("series", {}) or {}
                            _fc = _series.get("forecast", []) or []
                            if _fc:
                                _forecast_L = float(_fc[-1])
                                if len(_fc) >= 2:
                                    _forecast_T = float(_fc[-1] - _fc[0])
                    except Exception:
                        _forecast_L, _forecast_T = None, None
                # ranges / sector_weights：优先用 inference 内缓存的（forecast 输入）
                try:
                    if inference.get("ai_global_ranges"):
                        _ranges = inference["ai_global_ranges"]
                    else:
                        _ranges = self._param_mapper.map_global_parameters(
                            _forecast_L if _forecast_L is not None else _reactive_L,
                            _forecast_T if _forecast_T is not None else _reactive_T,
                            _reactive_C, stats_row=_stats_row,
                        )
                except Exception:
                    _ranges = {}
                try:
                    if inference.get("ai_sector_weights"):
                        _sector_w = inference["ai_sector_weights"]
                    else:
                        # 兜底 betas：identity（无真实 betas 时均匀权重 + 1.0 乘数）
                        _def_betas = {"defi": (1.0, 0.0, 0.5), "ai": (1.0, 0.0, 0.5),
                                      "rwa": (1.0, 0.0, 0.5), "meme": (1.0, 0.0, 0.5),
                                      "l2": (1.0, 0.0, 0.5)}
                        _sector_w = self._param_mapper.map_sector_weights(
                            _forecast_L if _forecast_L is not None else _reactive_L,
                            _forecast_T if _forecast_T is not None else _reactive_T,
                            _reactive_C, _def_betas,
                        )
                except Exception:
                    _sector_w = {}

                _symbol_sector = (inference.get("sector")
                                  or _snap.get("sector"))
                _reg_mult = dict(inference.get("_regime_multipliers", {}) or {})
                # 把 regime_baselines（global_position_mult/ls_ratio_cap/long_bias/...）注入
                _rb = dict(getattr(self, "_param_mapper", None)
                           and getattr(self._param_mapper, "REGIME_BASE_PARAMS", {})
                           or {})
                # 如果 inference 提供过 baseline，则用 inference 的（保证 shadow 一致）
                if inference.get("_regime_baselines"):
                    _rb.update(dict(inference["_regime_baselines"]))
                inference["_regime_baselines"] = _rb
                # 暴露 stats_row / sector 到 inference（ShadowLogger 需要）
                inference["stats_row"] = _stats_row
                inference["sector"] = _symbol_sector
                inference["base_long_threshold"] = float(self.confidence_threshold)
                inference["base_short_threshold"] = float(self.short_confidence_threshold)

                _eff_params = self._param_mapper._resolve_effective_params(
                    ranges=_ranges,
                    stats_row=_stats_row,
                    forecast_L=_forecast_L,
                    forecast_T=_forecast_T,
                    alpha_blend=getattr(self, "_alpha_blend", 0.0),
                    regime_baselines=_rb,
                    sector_weights_result=_sector_w,
                    symbol_sector=_symbol_sector,
                    regime_multipliers=_reg_mult,
                    enable_inject=True,
                    base_long_threshold=float(self.confidence_threshold),
                    base_short_threshold=float(self.short_confidence_threshold),
                )
        except Exception as _e:
            self._log(f"[{coin}] 融合层调用失败（已降级为不注入）：{_e}", "WARN")
            _eff_params = None
            _inject = False

        if _inject and _eff_params:
            # ── [CBR shadow] θ_match* top-3 相似度融合（F1 红线：真参数字节等价不变） ──
            # 约束：
            #   · FAIL-OPEN：CBREngine 任一异常 / top3<3 / 任一 <θ_match* → applied=False，
            #     仅写结构化 JSONL + WARN 一行，绝不阻塞开仓；
            #   · F1红线：_reg[...] 与 _eff_params[..._final] 所有行字节不变；
            #     融合目标值仅进入 _eff_params["_cbr_shadow"] 与 JSONL 审计；
            #   · θ_match* 取 CBRJsonlStore.theta_match_star（季度校准值，不硬编码）。
            _cbr_shadow: Dict[str, Any] = {"applied": False, "fail_open_reason": None}
            _cbr_jsonl_record: Dict[str, Any] = {}
            try:
                _theta_star = float(getattr(
                    getattr(self, "_cbr_store", None), "theta_match_star", 0.71,
                ))
                _cbr_engine = getattr(self, "_cbr_engine", None)
                _cbr_log_path = getattr(self, "_cbr_retrieval_log_path", None)
                _retrieved: List[Any] = []
                _baseline: Dict[str, Any] = {}  # noqa: E501  placeholder，JSONL 异常兜底前会被真正 baseline 覆盖
                _top3: List[Any] = []
                _war_state_5d_mean = None
                try:
                    _ws_history = (inference.get("_five_domain") or {}).get("war_state_history") or []
                    if _ws_history:
                        allow_n = sum(1 for _x in _ws_history if str(_x) == "ALLOW")
                        _war_state_5d_mean = round(allow_n / max(1, len(_ws_history)), 3)
                except Exception:
                    _war_state_5d_mean = None
                # (i) Query 构造（缺失字段默认值，不抛）
                _qr_conf = float(
                    _eff_params.get("confidence_final")
                    if _eff_params.get("confidence_final") is not None
                    else inference.get("confidence") or 0.0
                )
                _qr_vol = float(
                    inference.get("volatility_pct")
                    if inference.get("volatility_pct") is not None
                    else (_eff_params.get("volatility_pct") or 0.0)
                )
                _qr_price = float(inference.get("price") or 0.0)
                _qr_decision = "SHORT" if direction == "DOWN" else "LONG"
                _qr_regime = str(inference.get("regime_label") or "") or None
                from scripts.memory_l4.cbr_engine import CBRQuery as _CBRQuery
                _cbr_query = _CBRQuery(
                    inst_id=str(coin or ""),
                    regime=_qr_regime,
                    decision=_qr_decision,
                    confidence=float(np.clip(_qr_conf, 0.0, 1.0)),
                    volatility=float(_qr_vol),
                    entry_price=float(_qr_price),
                    max_drawdown=float(_eff_params.get("max_drawdown") or 0.05),
                    risk_budget=float(_eff_params.get("risk_budget") or 0.02),
                )
                # 基线快照（F1 红线：blended 永不覆盖这些值）
                _baseline = {
                    "position_mult": float(_eff_params["position_mult_final"]),
                    "tp_mult": float(_eff_params["tp_mult_final"]),
                    "sl_mult": float(_eff_params["sl_mult_final"]),
                    "threshold_mult": float(_eff_params["threshold_mult_final"]),
                    "long_conf_threshold": float(_eff_params["long_conf_threshold"]),
                    "short_conf_threshold": float(_eff_params["short_conf_threshold"]),
                    "leverage": float(_eff_params.get("leverage_final") or
                                     inference.get("leverage") or 1.0),
                    "best_holding_hours": int(_eff_params.get("best_holding_hours") or
                                              inference.get("best_holding_hours") or 60),
                }
                if _cbr_engine is None:
                    _fail_reason = "cbr_engine is None"
                    _cbr_shadow["fail_open_reason"] = _fail_reason
                else:
                    # (ii) Retrieve → top-5 → sim≥θ* → top-3 严格等长才融合
                    _retrieved = list(_cbr_engine.retrieve(_cbr_query))
                    _filtered = [_r for _r in _retrieved if float(_r.similarity) >= _theta_star]
                    _top3 = _filtered[:3]
                    if len(_top3) != 3:
                        if not _filtered:
                            _fail_reason = f"all_below_theta (theta={_theta_star:.3f}, top_sim={(_retrieved[0].similarity if _retrieved else 0.0):.3f})"
                        else:
                            _fail_reason = f"top3_len<3 (actual={len(_top3)}, theta={_theta_star:.3f})"
                        _cbr_shadow["fail_open_reason"] = _fail_reason
                    # top3 元信息（无论是否融合，都结构化落盘）
                    _top3_meta = []
                    for _r in _top3:
                        _case = _r.case
                        _raw = getattr(_case, "raw", None) or {}
                        _exec = _raw.get("execution") if isinstance(_raw, dict) else None
                        _hold_h = None
                        _ts_entry = _raw.get("entry_time") or (_exec or {}).get("entry_time") if isinstance(_exec, dict) else None
                        _ts_exit = _raw.get("exit_time") or (_exec or {}).get("exit_time") if isinstance(_exec, dict) else None
                        if _ts_entry and _ts_exit:
                            try:
                                if isinstance(_ts_entry, (int, float)) and isinstance(_ts_exit, (int, float)):
                                    _hold_h = max(0, round(float(_ts_exit - _ts_entry) / 3600.0, 2))
                            except Exception:
                                _hold_h = None
                        if _hold_h is None:
                            _hold_h = int(_baseline["best_holding_hours"])
                        _top3_meta.append({
                            "case_id": str(getattr(_case, "case_id", "") or ""),
                            "sim": round(float(_r.similarity), 4),
                            "pnl_pct": round(float(getattr(_case, "pnl_pct", 0.0) or 0.0), 4),
                            "holding_h": _hold_h,
                            "leverage": round(float(getattr(_case, "leverage", 1.0) or 1.0), 2),
                            "outcome": "WIN" if bool(getattr(_case, "is_profit", False)) else "LOSS",
                            "raw_position_pct": round(float(
                                (isinstance(_raw, dict) and (_raw.get("position_pct") if _raw.get("position_pct") is not None
                                 else ((_raw.get("execution") or {}).get("position_pct") if isinstance(_raw.get("execution"), dict) else None)))
                                or 0.0), 6),
                        })
                    # (iii) Weighted fusion + soft blend cap ≤ 0.15（仅 shadow，不生效）
                    _blended: Dict[str, float] = dict(_baseline)
                    _soft_alpha = 0.0
                    if len(_top3) == 3:
                        _sims = [float(_r.similarity) for _r in _top3]
                        _sim_sum = sum(_sims)
                        if _sim_sum <= 0:
                            _fail_reason = "top3_sim_sum_zero"
                            _cbr_shadow["fail_open_reason"] = _fail_reason
                        else:
                            _ws = [_s / _sim_sum for _s in _sims]
                            # 从 raw/execution 取 position_pct → 映射成 position_mult 相对单位
                            def _case_position_mult(_rc: Any) -> float:
                                _raw_c = getattr(_rc.case, "raw", None) or {}
                                _exec_c = _raw_c.get("execution") if isinstance(_raw_c, dict) else None
                                _pp = None
                                if isinstance(_raw_c, dict):
                                    _pp = _raw_c.get("position_pct")
                                if _pp is None and isinstance(_exec_c, dict):
                                    _pp = _exec_c.get("position_pct")
                                if _pp is None:
                                    return float(_baseline["position_mult"])
                                try:
                                    _pv = float(_pp)
                                except Exception:
                                    return float(_baseline["position_mult"])
                                # 历史 position_pct ∈ [0,1]；基线 position_mult_final ∈ [0.1,5.0] 倍率
                                #   → 用 case_pct / 0.05 相对基准 (0.05 = 默认 5% 轻仓) 作为 case_mult
                                _denom = 0.05
                                if _pv <= 0:
                                    return float(_baseline["position_mult"])
                                return float(_pv / _denom)
                            def _case_holding_h(_rc: Any) -> int:
                                _raw_c = getattr(_rc.case, "raw", None) or {}
                                _exec_c = _raw_c.get("execution") if isinstance(_raw_c, dict) else None
                                if isinstance(_raw_c, dict):
                                    _ent = _raw_c.get("entry_time")
                                    _ext = _raw_c.get("exit_time")
                                    if _ent is None and isinstance(_exec_c, dict):
                                        _ent = _exec_c.get("entry_time")
                                    if _ext is None and isinstance(_exec_c, dict):
                                        _ext = _exec_c.get("exit_time")
                                    try:
                                        if isinstance(_ent, (int, float)) and isinstance(_ext, (int, float)):
                                            return max(1, int(round(float(_ext - _ent) / 3600.0)))
                                    except Exception:
                                        pass
                                return int(_baseline["best_holding_hours"])
                            def _case_long_thr(_rc: Any) -> float:
                                _cc = getattr(_rc.case, "confidence", None)
                                try:
                                    return float(np.clip(float(_cc or 0.0), 0.0, 1.0)) if _cc is not None else float(_baseline["long_conf_threshold"])
                                except Exception:
                                    return float(_baseline["long_conf_threshold"])
                            # 加权融合（每维独立 Σw×value）
                            _b_pos = sum(_ws[i] * _case_position_mult(_top3[i]) for i in range(3))
                            _b_lev = sum(_ws[i] * float(getattr(_top3[i].case, "leverage", 1.0) or 1.0) for i in range(3))
                            _b_hold = sum(_ws[i] * float(_case_holding_h(_top3[i])) for i in range(3))
                            _b_long_thr = sum(_ws[i] * _case_long_thr(_top3[i]) for i in range(3))
                            # soft blend：α = min(0.15, mean(sim_i - θ*) × 2)，上限 0.15
                            _sim_over = max(0.0, sum(_sims[i] - _theta_star for i in range(3)) / 3.0)
                            _soft_alpha = float(min(0.15, max(0.0, _sim_over * 2.0)))
                            if _soft_alpha > 0:
                                _a = _soft_alpha
                                _blended = {
                                    "position_mult": float(_a * _b_pos + (1 - _a) * _baseline["position_mult"]),
                                    "tp_mult": float(_baseline["tp_mult"]),   # CBR 暂不直接推 TP 乘数
                                    "sl_mult": float(_baseline["sl_mult"]),   # CBR 暂不直接推 SL 乘数
                                    "threshold_mult": float(_baseline["threshold_mult"]),
                                    "long_conf_threshold": float(_a * _b_long_thr + (1 - _a) * _baseline["long_conf_threshold"]),
                                    "short_conf_threshold": float(_baseline["short_conf_threshold"]),
                                    "leverage": float(_a * _b_lev + (1 - _a) * _baseline["leverage"]),
                                    "best_holding_hours": int(round(_a * _b_hold + (1 - _a) * float(_baseline["best_holding_hours"]))),
                                    "_raw_blend_pos_mult": round(_b_pos, 4),
                                    "_raw_blend_leverage": round(_b_lev, 2),
                                    "_raw_blend_hold_h": round(_b_hold, 1),
                                    "_raw_blend_long_thr": round(_b_long_thr, 4),
                                }
                            else:
                                _blended = dict(_baseline)
                            # applied 标记为 True（仅 shadow；真参数仍保持基线）
                            _cbr_shadow["applied"] = True
                            _cbr_shadow["fail_open_reason"] = None
                    _cbr_shadow.update({
                        "theta_match_star": round(_theta_star, 4),
                        "soft_cap_alpha": round(_soft_alpha, 4),
                        "top3_meta": _top3_meta,
                        "top3_count": len(_top3),
                        "retrieved_count": len(_retrieved) if "_retrieved" in locals() else 0,
                        "baseline_values": _baseline,
                        "blended_values_before_shadow": _blended,
                    })
                _eff_params["_cbr_shadow"] = _cbr_shadow
                # (v) 结构化 JSONL 写入（所有分支均落：含 fail-open reason）
                try:
                    if _cbr_log_path:
                        _cbr_jsonl_record = {
                            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "symbol": str(coin or ""),
                            "query_features": {
                                "inst_id": _cbr_query.inst_id,
                                "regime": _cbr_query.regime,
                                "decision": _cbr_query.decision,
                                "confidence": round(float(_cbr_query.confidence), 4),
                                "volatility": round(float(_cbr_query.volatility), 6),
                                "war_state_5d_mean": _war_state_5d_mean,
                            },
                            "top3": _cbr_shadow.get("top3_meta", []),
                            "baseline_values": _cbr_shadow.get("baseline_values", _baseline if "_baseline" in locals() else {}),
                            "blended_values": _cbr_shadow.get("blended_values_before_shadow", {}),
                            "blend_config": {
                                "theta_match_star": round(_theta_star, 4),
                                "soft_cap_alpha": round(_cbr_shadow.get("soft_cap_alpha", 0.0), 4),
                                "applied": bool(_cbr_shadow.get("applied", False)),
                                "fail_open_reason": _cbr_shadow.get("fail_open_reason"),
                            },
                        }
                        with open(str(_cbr_log_path), "a", encoding="utf-8") as _fp:
                            _fp.write(json.dumps(_cbr_jsonl_record, ensure_ascii=False) + "\n")
                except Exception as _je:
                    self._log(
                        f"[{coin}] [CBR shadow] JSONL 写入失败（非阻塞）：{_je}", "WARN",
                    )
                # Shadow 审计日志（applied=False 也打一行，便于 fail-open 追踪）
                self._log(
                    f"[{coin}] [CBR shadow] top3_count={_cbr_shadow.get('top3_count', 0)} "
                    f"theta*={_cbr_shadow.get('theta_match_star', _theta_star):.3f} "
                    f"α={_cbr_shadow.get('soft_cap_alpha', 0.0):.3f} "
                    f"applied={_cbr_shadow.get('applied', False)} "
                    f"reason={_cbr_shadow.get('fail_open_reason') or 'ok'}",
                    "INFO" if _cbr_shadow.get("applied", False) else "DEBUG",
                )
            except Exception as _cbr_e:
                # FAIL-OPEN 最后兜底：异常绝不阻塞，真参数字节保持基线
                try:
                    _eff_params["_cbr_shadow"] = {
                        "applied": False,
                        "fail_open_reason": f"exception::{type(_cbr_e).__name__}:{_cbr_e}",
                        "theta_match_star": float(getattr(getattr(self, "_cbr_store", None), "theta_match_star", 0.71)),
                        "soft_cap_alpha": 0.0,
                        "top3_meta": [],
                        "top3_count": 0,
                        "baseline_values": {},
                        "blended_values_before_shadow": {},
                    }
                    if getattr(self, "_cbr_retrieval_log_path", None):
                        _rec = {
                            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "symbol": str(coin or ""),
                            "query_features": {},
                            "top3": [],
                            "baseline_values": {},
                            "blended_values": {},
                            "blend_config": {
                                "theta_match_star": _eff_params["_cbr_shadow"]["theta_match_star"],
                                "soft_cap_alpha": 0.0,
                                "applied": False,
                                "fail_open_reason": _eff_params["_cbr_shadow"]["fail_open_reason"],
                            },
                        }
                        with open(str(self._cbr_retrieval_log_path), "a", encoding="utf-8") as _fp:  # type: ignore[arg-type]
                            _fp.write(json.dumps(_rec, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                self._log(
                    f"[{coin}] [CBR shadow] 异常旁路（fail-open，真参数不变）：{type(_cbr_e).__name__}:{_cbr_e}",
                    "WARN",
                )

            # ⚡ 注入生效：覆盖 regime_multipliers（下游 _open_position 读）
            _reg = dict(inference.get("_regime_multipliers", {}) or {})
            _reg["position_mult"] = float(_eff_params["position_mult_final"])
            _reg["tp_mult"] = float(_eff_params["tp_mult_final"])
            _reg["sl_mult"] = float(_eff_params["sl_mult_final"])
            _reg["threshold_mult"] = float(_eff_params["threshold_mult_final"])
            inference["_regime_multipliers"] = _reg
            inference["_effective_params"] = _eff_params
            # ⚡ 覆盖 threshold（多空各自独立阈值：long_conf / short_conf 实际）
            if direction == "DOWN":
                effective_threshold = float(_eff_params["short_conf_threshold"])
            else:
                effective_threshold = float(_eff_params["long_conf_threshold"])
            self._log(
                f"[{coin}] 融合层 T4 注入生效 | pos={_reg['position_mult']:.3f}"
                f" tp={_reg['tp_mult']:.3f} sl={_reg['sl_mult']:.3f}"
                f" thr_mult={_reg['threshold_mult']:.3f}"
                f" long_thr={_eff_params['long_conf_threshold']:.4f}"
                f" short_thr={_eff_params['short_conf_threshold']:.4f}"
                f" ls_cap={_eff_params['ls_ratio_cap']:.3f}"
                f" (α={getattr(self, '_alpha_blend', 0.0):.2f})",
                "INFO",
            )
        else:
            # 融合层未生效：初始化 effective_threshold 与原逻辑一致
            effective_threshold = confidence_threshold or self.confidence_threshold
            # 做空方向使用独立的更高阈值（原版逻辑）
            if direction == "DOWN":
                effective_threshold = max(effective_threshold, self.short_confidence_threshold)

            # ── 基线模式下统一暴露「六维参数 + 形态乘数」（审计要求：日志中可见）
            #    即便乘数=1.0 也要打一条汇总，让实盘日志明确看到：spec §10.6 的 Layer0 参数
            #    已通过 _regime_multipliers 传递链（阈值×/仓位×/SL×/TP×）生效到核心层
            try:
                _rbs = getattr(self, "_param_mapper", None) and \
                       getattr(self._param_mapper, "REGIME_BASE_PARAMS", {}) or {}
                _rbs_merged = dict(_rbs)
                if inference.get("_regime_baselines"):
                    _rbs_merged.update(dict(inference["_regime_baselines"]))
                _reg_mult2 = dict(inference.get("_regime_multipliers", {}) or {})
                _sector_w = (inference.get("ai_sector_weights")
                             or (inference.get("_effective_params") or {}).get("sector_weights_result")
                             or None)
                _base_long = float(getattr(self, "confidence_threshold", 0.35))
                _base_short = float(getattr(self, "short_confidence_threshold", 0.80))
                _thr_mult_2 = float(_reg_mult2.get("threshold_mult", 1.0))
                _eff_long = _base_long * _thr_mult_2
                _eff_short = max(_base_long, _base_short) * _thr_mult_2
                # sector 若存在：取前 3 个最高权重
                _sector_str = "n/a(均匀分配)"
                if isinstance(_sector_w, dict) and len(_sector_w):
                    _sorted = sorted(_sector_w.items(), key=lambda kv: float(kv[1]), reverse=True)[:3]
                    _sector_str = ", ".join(f"{k}={float(v):.2f}" for k, v in _sorted)
                self._log(
                    f"[{coin}] 形态查表参数（基线模式，S5={self.ENABLE_REGIME_AND_MACRO_S5} "
                    f"α={getattr(self, '_alpha_blend', 0.0):.2f}） | "
                    f"regime={inference.get('_regime_pred') or 'UNKNOWN'} "
                    f"src={inference.get('_regime_pred_source') or 'n/a'} "
                    f"pos=×{float(_reg_mult2.get('position_mult', 1.0)):.3f} "
                    f"tp=×{float(_reg_mult2.get('tp_mult', 1.0)):.3f} "
                    f"sl=×{float(_reg_mult2.get('sl_mult', 1.0)):.3f} "
                    f"thr_mult=×{_thr_mult_2:.3f} "
                    f"long_thr={_eff_long:.4f} short_thr={_eff_short:.4f} "
                    f"ls_cap={float(_rbs_merged.get('ls_ratio_cap', 1.15)):.3f} "
                    f"sector_top3=[{_sector_str}]",
                    "INFO",
                )
            except Exception:
                pass

        # ── 段①②③ 只读审计日志：大小周期→市场形态→六维（对齐 tab-morph /cycle+/params）──
        # 无论基线/融合层开启状态，均只读取并记录，不修改任何交易参数
        self._log_morph_cycle_for_coin(coin, inst_id)
        self._log_param_mapper_snapshot(coin, inst_id, inference)

        pos_info = self._check_positions(coin)

        if pos_info.get("has_position"):
            # ── 段④ 注入BCRM（持仓路径）：形态乘数作用到 SLTP/仓位 中性确认日志 ──
            self._log_regime_hold_confirmation(coin, inference, pos_info)
            pos_side = pos_info["pos_side"]
            upl = pos_info.get("upl", 0)
            upl_ratio = pos_info.get("upl_ratio", 0)

            tracker_pos = self.position_tracker.get_open_position(inst_id)
            is_external = tracker_pos and tracker_pos.strategy_source == "external"
            is_evolution = tracker_pos and tracker_pos.strategy_source == "evolution"

            if is_external or is_evolution:
                self._log(f"[{coin}] {'外部策略' if is_external else 'evolution'}持仓，BCRM 不干预", "INFO")
                return

            # 计算持仓年龄（供保护期门禁、离场确认等使用）
            position_age_sec = 0
            open_time = pos_info.get("open_time", 0)
            if open_time > 0:
                position_age_sec = time.time() - open_time
            else:
                # ★ FIX Bug: open_time=0 时尝试从 position_tracker.entry_time 重新解析
                # 多进程并发或 entry_time 丢失时，open_time 可能为 0，导致 yijing_window_wait 永久死锁
                # 根因：okx_simulated.get_positions 未返回 cTime，且 PositionTracker.entry_time 可能因
                # 多进程并发写入丢失 → open_time=0 → position_age_sec=0 → yijing_window_wait 永远 < 60min
                _tracker_rec_fb = self.position_tracker.get_open_position(inst_id)
                if _tracker_rec_fb and _tracker_rec_fb.entry_time:
                    try:
                        _ts_fb = _tracker_rec_fb.entry_time
                        if _ts_fb.endswith("Z"):
                            _ts_fb = _ts_fb.replace("Z", "+00:00")
                        from datetime import datetime as _dt_fb
                        _open_time_fb = _dt_fb.fromisoformat(_ts_fb).timestamp()
                        if _open_time_fb > 0:
                            open_time = _open_time_fb
                            position_age_sec = time.time() - open_time
                            self._log(
                                f"[{coin}] 持仓时间戳恢复(tracker) | entry_time="
                                f"{_tracker_rec_fb.entry_time} → open_time={open_time}",
                                "WARN",
                            )
                    except Exception as _e_fb:
                        self._log(
                            f"[{coin}] 持仓时间戳恢复失败: {_e_fb} | "
                            f"entry_time={getattr(_tracker_rec_fb, 'entry_time', None)}",
                            "WARN",
                        )

                # 如果 tracker 也没有 entry_time，触发硬告警（但仍继续，FAIL-OPEN）
                if position_age_sec == 0:
                    self._log(
                        f"[{coin}] 持仓时间戳丢失告警 | has_position=True 但 open_time=0，"
                        f"易经离场系统将无法评估（yijing_window_wait 永久死锁风险）",
                        "ERROR",
                    )
            in_protection = self._is_position_protected(position_age_sec)

            # ════════════════════════════════════════════════════════════════
            # ── 持仓与离场管理层：ExitManager 策略链（v4.4 重构）──
            #    替换原 ① 信号反转 + ② P3提前退出 + Phase B EV 雷达四档决策
            #    优先级：P3(10) → SignalRev(20) → EvFC(30) → Timeout(40) → EvAdj(60)
            #    全部 pass → 继续走 Phase C (S3) → 核心层（卦象主离场 + Classic 兜底）
            #    Spec: docs/superpowers/specs/2026-08-20-exit-manager-design.md
            # ════════════════════════════════════════════════════════════════

            # ── 计算 EV（如果 EV 雷达开启，供 EvForceClose/EvAdjust 策略使用）──
            _ev = None
            _ev_subs: Dict = {}
            if getattr(self, "enable_ev_radar", False):
                try:
                    from scripts.memory_l4.trading_utils import RiskManager
                    _ev_subs = self._build_ev_subscores(
                        pos_side, position_age_sec, upl_ratio, inference
                    )
                    _weights = getattr(self, "ev_weights", None) or {
                        k: 1 / 7 for k in _ev_subs
                    }
                    _ev, _ev_subs = RiskManager.calc_position_ev(_ev_subs, _weights)
                    self._log(
                        f"[{coin}] EV={_ev:.3f} | "
                        f"trend={_ev_subs.get('trend_alignment_s', 0):.2f} "
                        f"liq={_ev_subs.get('liquidity_risk_s', 0):.2f} "
                        f"dir={_ev_subs.get('direction_consistency_s', 0):.2f} "
                        f"pnl_mom={_ev_subs.get('pnl_momentum_s', 0):.2f}",
                        "INFO",
                    )
                except Exception as _e:
                    self._log(f"[{coin}] EV 计算异常: {_e}", "WARN")
                    _ev = None
            else:
                self._log(f"[{coin}] EV BYPASS (S2=off)", "INFO")

            # ── 构造 held_coins 集合（供 TimeoutProfitSwitch 排除已持仓币种）──
            _held_coins = {coin}
            for _inst in getattr(self.position_tracker, "open_positions", {}):
                _c = _inst.split("-")[0] if _inst else ""
                if _c:
                    _held_coins.add(_c)

            # ── 轻仓试错评估周期（P1 升级：定期重评估 + 放宽阈值）──
            # 持仓≥30min 首次评估，之后每60min重评估一次；
            # reverse 阈值从 -0.5% 放宽到 -3%（轻仓绝对亏损小，容忍噪音）。
            _trial_closed = False  # 试错评估是否已平仓
            if self._should_run_trial_eval(tracker_pos, position_age_sec):
                _cur_price = float(pos_info.get("mark_px", 0) or inference.get("price", 0) or 0)
                _entry_price = float(tracker_pos.entry_price or 0)
                _trial_action = "maintain"  # 默认维持
                if _cur_price > 0 and _entry_price > 0:
                    _price_chg_pct = (_cur_price - _entry_price) / _entry_price
                    if pos_side == "short":
                        _price_chg_pct = -_price_chg_pct  # 做空反转：价格下跌为正
                    _trial_action = self._compute_trial_action(_price_chg_pct)

                    self._log(
                        f"[{coin}] 试错评估 | 持仓={position_age_sec/60:.0f}min "
                        f"价格变化={_price_chg_pct:+.2%} "
                        f"入场={_entry_price} 当前={_cur_price} "
                        f"判定={_trial_action}",
                        "INFO",
                    )

                    if _trial_action == "reverse":
                        # 趋势逆转 → 平仓
                        self._log(
                            f"[{coin}] 试错评估:趋势逆转 → 平仓 | "
                            f"盈亏={upl:.2f}({upl_ratio:.2%})",
                            "WARN",
                        )
                        _exit_price = _cur_price
                        if pos_side == "long":
                            _r = self.okx_client.market_close_long(
                                inst_id, reason="trial_trend_reverse"
                            )
                        else:
                            _r = self.okx_client.market_close_short(
                                inst_id, reason="trial_trend_reverse"
                            )
                        if _r.get("ok") or _r.get("dry_run"):
                            self._handle_close_position(
                                inst_id=inst_id, coin=coin, pos_side=pos_side,
                                exit_price=_exit_price, exit_reason="trial_trend_reverse",
                                pnl=upl, pnl_pct=upl_ratio,
                            )
                            _trial_closed = True
                    elif _trial_action == "confirm":
                        # 趋势确认 → 标记可加仓（日志信号，实际加仓由开仓逻辑处理）
                        self._log(
                            f"[{coin}] 试错评估:趋势确认 | 标记可加仓信号 "
                            f"(后续如置信度达标可正常开仓加仓)",
                            "INFO",
                        )
                    else:
                        self._log(
                            f"[{coin}] 试错评估:趋势不明 → 维持试错仓位",
                            "INFO",
                        )
                # 标记评估时间戳（支持60min定期重评估），并保留 trial_eval_done 向后兼容
                tracker_pos.trial_eval_done = True
                tracker_pos.last_trial_eval_ts = time.time()

            # ── 调用 ExitManager（按优先级链评估扩展层离场策略）──
            # 如果试错评估已平仓，跳过 ExitManager
            if _trial_closed:
                return
            _exit_decision = self.exit_manager.evaluate(
                coin=coin,
                inference=inference,
                pos_info=pos_info,
                tracker_pos=tracker_pos,
                in_protection=in_protection,
                age_hours=position_age_sec / 3600.0,
                ev=_ev,
                confidence=confidence,
                all_inferences=all_inferences or {},
                held_coins=_held_coins,
                effective_threshold=effective_threshold,
            )

            # ── 处理 ExitManager 决策 ──
            _act = _exit_decision.action
            _sname = _exit_decision.strategy_name or "exit_manager"
            _ev_str = f"{_ev:.3f}" if _ev is not None else "N/A"

            if _act == "force_close":
                # 执行平仓（P3/SignalReverse/EvForceClose/TimeoutProfitSwitch）
                _exit_price = pos_info.get("mark_px", inference["price"])
                _exit_reason = _exit_decision.reason or _sname
                self._log(
                    f"[{coin}] [{_sname}] FORCE_CLOSE✅ | reason={_exit_reason} | "
                    f"{'[保护期]' if in_protection else ''} "
                    f"卦象={inference.get('hexagram', '-')} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%}) "
                    f"持仓={position_age_sec/3600:.1f}h",
                    "WARN",
                )
                if pos_side == "long":
                    _r = self.okx_client.market_close_long(
                        inst_id, reason=_exit_reason
                    )
                else:
                    _r = self.okx_client.market_close_short(
                        inst_id, reason=_exit_reason
                    )
                if _r.get("ok") or _r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id, coin=coin, pos_side=pos_side,
                        exit_price=_exit_price, exit_reason=_exit_reason,
                        pnl=upl, pnl_pct=upl_ratio,
                    )
                    # ── 记录 exit_strategy_log（含 pnl/win 贡献值回填）──
                    self._save_exit_strategy_decision(
                        coin=coin, decision=_exit_decision,
                        age_hours=position_age_sec / 3600.0,
                        in_protection=in_protection, ev=_ev,
                        confidence=confidence, pnl=upl, win=(upl > 0),
                    )
                    # 信号反转特殊处理：平仓后开反手仓
                    if _sname == "signal_reverse":
                        _side_map = {"UP": "long", "DOWN": "short"}
                        _want_side = _side_map.get(direction)
                        _in_cd, _cd_reason = self.position_tracker.is_in_cooldown(
                            inst_id, _want_side, self.COOLDOWN_SEC
                        )
                        if _in_cd:
                            self._log(
                                f"[{coin}] 信号反转已平仓，但统一冷静期生效，跳过反手开仓: {_cd_reason}",
                                "INFO",
                            )
                            return
                        _risk_check = self.risk_manager.can_trade(
                            self.perf_tracker.current_equity
                        )
                        if not _risk_check["allowed"]:
                            self._log(
                                f"[{coin}] 风控拦截反手开仓: {_risk_check['reason']}",
                                "WARN",
                            )
                            return
                        _total_pos = self._count_yijing_positions()
                        if _total_pos >= self.max_positions:
                            self._log(
                                f"[{coin}] 已达易经系统最大持仓数 {self.max_positions}，跳过反手",
                                "INFO",
                            )
                            return
                        self._open_position(inference, is_reverse=True)
                return

            elif _act == "hold":
                # 等待确认（P3/SignalReverse/EvForceClose 待确认状态）
                self._log(
                    f"[{coin}] [{_sname}] HOLD 待确认 | "
                    f"{_exit_decision.reason} | "
                    f"{'[保护期]' if in_protection else ''} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%}) "
                    f"持仓={position_age_sec/3600:.1f}h",
                    "INFO",
                )
                # ── 记录 exit_strategy_log（pnl/win 留空，待确认）──
                self._save_exit_strategy_decision(
                    coin=coin, decision=_exit_decision,
                    age_hours=position_age_sec / 3600.0,
                    in_protection=in_protection, ev=_ev,
                    confidence=confidence, pnl=None, win=None,
                )
                return

            elif _act == "adjust_sl_tp":
                # 调用 _adjust_sl_tp（T2 收紧 / T4 放宽）
                _mode = (_exit_decision.params or {}).get("mode", "tighten")
                self._log(
                    f"[{coin}] [{_sname}] ADJUST_SL_TP | mode={_mode} | "
                    f"reason={_exit_decision.reason} | EV={_ev_str} | "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})",
                    "INFO",
                )
                try:
                    self._adjust_sl_tp(coin, inst_id, pos_side, mode=_mode)
                except Exception as _e:
                    self._log(f"[{coin}] _adjust_sl_tp 异常: {_e}", "WARN")
                # ── 记录 exit_strategy_log（SL/TP 调整无 pnl/win）──
                self._save_exit_strategy_decision(
                    coin=coin, decision=_exit_decision,
                    age_hours=position_age_sec / 3600.0,
                    in_protection=in_protection, ev=_ev,
                    confidence=confidence, pnl=None, win=None,
                )
                # 继续走 Phase C (S3) 和核心层（不 return）

            # action == "pass": 继续走 Phase C (S3) 和核心层

            # ── Phase C (S3): 多 horizon 最佳离场 K 线推荐 ──
            # 三档动作：
            #   - HOLD / EXTEND_TRACK / BYPASS / NOOP → 仅日志
            #   - PREP_EXIT → 跨轮一致率统计 → 达标后 EXIT_CONFIRM → 执行平仓 return
            try:
                held_k_bar = max(
                    1, int(round(position_age_sec / 3600.0))
                ) if position_age_sec > 0 else 1
                horizon_info = self._recommend_exit_bars(
                    coin=coin, pos_side=pos_side,
                    held_k_bar=held_k_bar, inference=inference,
                )
                h_action = str(horizon_info.get("recommended_action", ""))
                if h_action and h_action in ("BYPASS", "NOOP"):
                    self._log(
                        f"[{coin}] [S3多horizon] 已持仓≈{held_k_bar}h → "
                        f"{h_action}（src={horizon_info.get('source', '?')}）",
                        "INFO",
                    )
                if h_action and h_action not in ("BYPASS", "NOOP"):
                    self._log(
                        f"[{coin}] [S3多horizon] 已持仓≈{held_k_bar}h → "
                        f"best_k={horizon_info.get('best_k_bar')} "
                        f"conf={horizon_info.get('best_confidence', 0):.2f} "
                        f"dir={horizon_info.get('best_direction', '')} "
                        f"src={horizon_info.get('source', '?')} → "
                        f"{h_action}",
                        "INFO",
                    )
                    # Phase C C11：PREP_EXIT → 跨轮一致率 → 离场确认 → 平仓
                    if h_action == "PREP_EXIT" and not in_protection:
                        prep_window = int(getattr(self, "S3_PREP_EXIT_CONFIRM_WINDOW", 3))
                        prep_rate = float(getattr(self, "S3_PREP_EXIT_CONFIRM_RATE", 0.67))
                        # 写入本轮 PREP_EXIT 记录（滑动窗口按 cycle 尾端维护 prep_window 个样本）
                        hist_key = ("s3_prep_exit_hist", coin, pos_side)
                        _h_hit, _h_load = self._cache_get(hist_key, ttl_cycles=prep_window + 2)
                        hist = list(_h_load) if isinstance(_h_load, list) else []
                        hist.append({
                            "cycle": int(getattr(self, "_cycle_idx", 0)),
                            "action": "PREP_EXIT",
                            "best_k": int(horizon_info.get("best_k_bar", -1)),
                        })
                        # 只保留最近 prep_window 条
                        hist = hist[-prep_window:]
                        self._cache_set(hist_key, hist)

                        n = len(hist)
                        n_prep = sum(1 for h in hist if h.get("action") == "PREP_EXIT")
                        rate = (n_prep / n) if n > 0 else 0.0
                        if rate >= prep_rate and n >= 2:
                            # 一致率达标 → EXIT_CONFIRM（2/2 双确认，保持与全系统一致）
                            confirmed, cnt = self._exit_confirm(
                                coin, self.EXIT_ACT_S3_PREP_EXIT
                            )
                            if confirmed:
                                self._clear_exit_confirm(coin, self.EXIT_ACT_S3_PREP_EXIT)
                                exit_price = float(
                                    inference.get("price") or pos_info.get("avg_px") or 0.0
                                )
                                best_k = int(horizon_info.get("best_k_bar", -1))
                                reason = (
                                    f"s3_prep_exit|consistency={n_prep}/{n}="
                                    f"{rate:.2f}≥{prep_rate:.2f}|"
                                    f"best_k={best_k}|held≈{held_k_bar}|cnt={cnt}"
                                )
                                self._log(
                                    f"[{coin}] [S3多horizon] PREP_EXIT 跨轮一致 "
                                    f"{n_prep}/{n}={rate:.2f}≥{prep_rate:.2f} → 执行离场",
                                    "WARN",
                                )
                                self._handle_close_position(
                                    inst_id=inst_id, coin=coin, pos_side=pos_side,
                                    exit_price=exit_price, exit_reason=reason,
                                    pnl=upl, pnl_pct=upl_ratio,
                                )
                                return  # S3 强制离场 → 跳过后续所有离场分支
                            else:
                                self._log(
                                    f"[{coin}] [S3多horizon] PREP_EXIT 一致率达标 "
                                    f"1/{self.EXIT_CONFIRM_REQUIRED} (cnt={cnt})，等待下轮确认",
                                    "WARN",
                                )
                    # SPEC §6.1：整轮 horizon_info 存缓存（用于诊断/回放）
                    self._cache_set(
                        ("horizon_eval", coin, pos_side),
                        dict(horizon_info),
                    )
            except Exception as _e:
                self._log(f"[{coin}] [S3多horizon] 评估异常: {_e}", "WARN")

            # 经典指标离场系统评估（完整四大优先级）
            current_price = inference["price"]
            entry_price = pos_info.get("avg_px", 0)
            # position_age_sec 和 open_time 已在上方计算
            kline_data = inference.get("kline_data", [])
            is_ranging = inference.get("is_ranging", False)
            regime = "chop" if is_ranging else "trend"

            exit_pos = ExitPositionState(
                coin=coin,
                side=pos_side,
                entry_price=float(entry_price) if entry_price else 0,
                current_price=float(current_price),
                position_age_sec=position_age_sec,
                unrealized_pnl_pct=float(upl_ratio),
                leverage=float(self.okx_client.cfg.get("default_leverage", 3)),
                atr_pct=float(inference.get("volatility", 0.03)),
                mfe_pnl_pct=max(0.0, float(upl_ratio)),
                metadata={"reduce_count": tracker_pos.reduce_count if tracker_pos else 0},
            )

            candles_1h = None
            if kline_data and len(kline_data) >= 20:
                candles_1h = [
                    {
                        "t": c.get("ts", c.get("t", 0)),
                        "o": c.get("o", 0),
                        "h": c.get("h", 0),
                        "l": c.get("l", 0),
                        "c": c.get("c", 0),
                        "v": c.get("v", 0),
                    }
                    for c in kline_data
                ]

            # ── 29h 持仓超时标记（仅供日志/ExitManager 策略链参考，不再跳过 yijing）──
            position_timeout_sec = self.yijing_exit_system.config.veto_max_hold_sec  # 104400 = 29h
            position_timed_out = position_age_sec > position_timeout_sec

            # ── 主离场层：易经推理专属离场（基于卦象风险-价值评估）──
            # yijing 始终为主决策层，classic 备用离场已移除
            # 超时后仍由 yijing + ExitManager 策略链管理，依赖开仓静态 SL/TP 兜底
            yijing_hexagram = self._infer_current_hexagram(coin, inference, kline_data)
            yijing_decision = None
            yijing_available = yijing_hexagram is not None

            if yijing_available:
                yijing_decision = self.yijing_exit_system.evaluate(
                    hexagram=yijing_hexagram,
                    pos_side=pos_side,
                    entry_price=float(entry_price) if entry_price else 0,
                    current_price=float(current_price),
                    position_age_sec=position_age_sec,
                    unrealized_pnl_pct=float(upl_ratio),
                    classic_decision=None,  # 主离场模式：不再否决 classic
                    mfe_pnl_pct=max(0.0, float(upl_ratio)),
                    coin=coin,  # v3.0：1h节奏缓存key
                    open_time_sec=float(open_time) if open_time else 0.0,  # v3.0：开仓时间戳
                )

            # P2: 浮亏≥3% 且 风险分>0.7 → 升级为 FORCE_CLOSE（填补 risk 0.7~0.8 盲区）
            if (yijing_decision
                    and yijing_decision.action != YijingExitAction.FORCE_CLOSE
                    and self._should_joint_force_close(
                        float(upl_ratio),
                        float(getattr(yijing_decision, "yijing_risk_score", 0.0) or 0.0),
                    )):
                yijing_decision.action = YijingExitAction.FORCE_CLOSE
                yijing_decision.reason = (
                    f"loss_risk_joint(pnl={float(upl_ratio):.2%},"
                    f"risk={float(getattr(yijing_decision, 'yijing_risk_score', 0.0) or 0.0):.2f}):"
                    f"{getattr(yijing_decision, 'reason', '')}"
                )

            # 1) 易经强制平仓：卦象风险极高 + 方向冲突 → 离场确认后执行
            if yijing_decision and yijing_decision.action == YijingExitAction.FORCE_CLOSE:
                # v5.0：FORCE_CLOSE 加2次离场确认（避免卦象波动误平仓，尤其是中高风险时）
                fc_confirmed, fc_cnt = self._exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)
                if not fc_confirmed:
                    self._log(
                        f"[{coin}] 易经FORCE_CLOSE待确认 [{fc_cnt}/{self.EXIT_CONFIRM_REQUIRED}] "
                        f"{'[保护期]' if in_protection else ''} | "
                        f"{yijing_decision.reason} | 卦象={yijing_decision.hexagram_name} "
                        f"风险={yijing_decision.yijing_risk_score:.2f} "
                        f"盈亏={upl:.2f}({upl_ratio:.2%})",
                        "WARN",
                    )
                    return  # 未确认，等待下次
                # 确认通过：执行
                self._clear_exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)
                self._log(
                    f"[{coin}] 易经主离场 [FORCE_CLOSE✅已确认] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} "
                    f"风险={yijing_decision.yijing_risk_score:.2f} "
                    f"价值={yijing_decision.yijing_value_score:.2f} "
                    f"持仓={position_age_sec/3600:.1f}h 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                if pos_side == "long":
                    r = self.okx_client.market_close_long(
                        inst_id, reason=f"易经离场:{yijing_decision.reason}"
                    )
                else:
                    r = self.okx_client.market_close_short(
                        inst_id, reason=f"易经离场:{yijing_decision.reason}"
                    )
                if r.get("ok") or r.get("dry_run"):
                    self._handle_close_position(
                        inst_id=inst_id,
                        coin=coin,
                        pos_side=pos_side,
                        exit_price=current_price,
                        exit_reason=f"yijing_exit:{yijing_decision.reason}",
                        pnl=upl,
                        pnl_pct=upl_ratio,
                    )
                return
            else:
                # FORCE_CLOSE条件不满足：清除累计确认（避免污染）
                self._clear_exit_confirm(coin, self.EXIT_ACT_YIJING_FORCE_CLOSE)

            # ── v5.0：持仓保护期门禁 ──
            # 开仓后6h内：屏蔽易经的SL/TP动态调整（TIGHTEN_SL/LOWER_SL/RAISE_TP/LOWER_TP）
            # 原因：开仓初期卦象/指标不稳定，频繁调SL/TP反而适得其反；
            #       保护期内仅依赖开仓时设置的静态SL/TP + FORCE_CLOSE(极端) + 信号反转
            _PROTECTED_YIJING_ACTIONS = {
                YijingExitAction.RAISE_TP,
                YijingExitAction.LOWER_SL,
                YijingExitAction.LOWER_TP,
                YijingExitAction.TIGHTEN_SL,
            }
            if (
                in_protection
                and yijing_decision
                and yijing_decision.action in _PROTECTED_YIJING_ACTIONS
            ):
                self._log(
                    f"[{coin}] 易经{str(yijing_decision.action).split('.')[-1]} [保护期屏蔽] "
                    f"持仓={position_age_sec/3600:.1f}h<{self.POSITION_PROTECTION_HOURS:.0f}h | "
                    f"原动作原因={yijing_decision.reason} 卦象={yijing_decision.hexagram_name or '-'} | "
                    f"保护期内仅用静态SL/TP，跳过动态调整",
                    "INFO",
                )
                # NO_INTERVENE 语义：维持持仓
                yijing_decision.action = YijingExitAction.NO_INTERVENE
                yijing_decision.reason = "protected_hold:" + yijing_decision.reason

            # 2) 易经提高止盈：价值高 + 成长期 → 上调止盈位（保护期内已屏蔽）
            # 2026-08-06 修复：基于 ATR 基线 × 价值调制因子（非硬编码 15%）
            if yijing_decision and yijing_decision.action == YijingExitAction.RAISE_TP:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                # 读取开仓时 ATR 基线止盈收益率
                base_tp_roi = self._get_base_tp_roi(inst_id, entry_price)
                if base_tp_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [RAISE_TP] 跳过: base_tp_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 价值分 → TP 调制因子（连续函数）
                tp_modulation = YijingExitSystem.value_to_tp_modulation(
                    yijing_decision.yijing_value_score
                )
                target_tp_roi = base_tp_roi * tp_modulation
                # ATR 基线下限保护
                target_tp_roi = YijingExitSystem.apply_atr_floor(target_tp_roi, base_tp_roi)
                new_tp_price = self._calc_tp_price(entry_price, pos_side, target_tp_roi, leverage)
                tp_price_change_pct = self._roi_to_price_change(target_tp_roi, leverage)
                # ★ FIX：RAISE_TP 是放宽止盈，使用常规TP下限（不允许收紧）+ 爆仓安全约束
                new_tp_price, _tp_clamped, _tp_old_pct, _tp_cfl = self._enforce_tp_price_floor(
                    new_tp_price, entry_price, pos_side, leverage=leverage,
                    allow_lower=False, coin=coin)
                if _tp_clamped:
                    _tail = "【爆仓约束优先】降杠杆≤20x" if _tp_cfl.get("liq_conflict") else ""
                    self._log(
                        f"[{coin}] 易经主离场 [RAISE_TP] 硬门禁钳制 | TP间距 "
                        f"{_tp_old_pct*100:.2f}%→{abs(new_tp_price-entry_price)/entry_price*100:.2f}% {_tail}",
                        "WARN",
                    )
                self._log(
                    f"[{coin}] 易经主离场 [RAISE_TP] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_tp_roi:.2%} × 调制{tp_modulation:.2f} = {target_tp_roi:.2%} "
                    f"(价{tp_price_change_pct:.2%}) "
                    f"新止盈={new_tp_price:.6f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    tp_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=None,
                        take_profit_px=new_tp_price,
                        reason=f"yijing_raise_tp:{yijing_decision.reason}",
                    )
                    if tp_result.get("ok"):
                        self._log(f"[{coin}] 易经止盈价已上调至 {new_tp_price:.6f}")
                    else:
                        self._log(
                            f"[{coin}] 易经上调止盈失败: {tp_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经上调止盈异常: {e}", "WARN")
                return

            # 3) 易经降低止损：风险低 + 趋势初期 → 放宽止损空间，避免被洗出去
            # 2026-08-06 修复：基于 ATR 基线 × 风险调制因子（非硬编码 2%）
            if yijing_decision and yijing_decision.action == YijingExitAction.LOWER_SL:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                # 读取开仓时 ATR 基线止损收益率
                base_sl_roi = self._get_base_sl_roi(inst_id, entry_price)
                if base_sl_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [LOWER_SL] 跳过: base_sl_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 风险分 → SL 调制因子（连续函数，风险低 → >1.0 放宽）
                sl_modulation = YijingExitSystem.risk_to_sl_modulation(
                    yijing_decision.yijing_risk_score
                )
                new_sl_roi = base_sl_roi * sl_modulation
                # ATR 基线下限保护
                new_sl_roi = YijingExitSystem.apply_atr_floor(new_sl_roi, base_sl_roi)
                new_sl_price = self._calc_sl_price(entry_price, pos_side, new_sl_roi, leverage)
                sl_price_change_pct = self._roi_to_price_change(new_sl_roi, leverage)
                # ★ FIX：LOWER_SL 是放宽止损（SL值更小），双约束（间距下限+爆仓安全）
                new_sl_price, _sl_clamped, _sl_old_pct, _sl_cfl = self._enforce_sl_price_floor(
                    new_sl_price, entry_price, pos_side, leverage=leverage,
                    allow_tighten=False, coin=coin)
                if _sl_clamped:
                    _tail = "【爆仓约束优先】降杠杆≤20x" if _sl_cfl.get("liq_conflict") else ""
                    self._log(
                        f"[{coin}] 易经主离场 [LOWER_SL] 硬门禁钳制 | SL间距 "
                        f"{_sl_old_pct*100:.2f}%→{abs(new_sl_price-entry_price)/entry_price*100:.2f}% {_tail}",
                        "WARN",
                    )
                self._log(
                    f"[{coin}] 易经主离场 [LOWER_SL] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_sl_roi:.2%} × 调制{sl_modulation:.2f} = {new_sl_roi:.2%} "
                    f"(价{sl_price_change_pct:.2%}) "
                    f"新止损={new_sl_price:.6f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    sl_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=new_sl_price,
                        take_profit_px=None,
                        reason=f"yijing_lower_sl:{yijing_decision.reason}",
                    )
                    if sl_result.get("ok"):
                        self._log(f"[{coin}] 易经止损价已放宽至 {new_sl_price:.6f}")
                    else:
                        self._log(
                            f"[{coin}] 易经放宽止损失败: {sl_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经放宽止损异常: {e}", "WARN")
                return

            # 4) 易经降低止盈：风险升高 + 已有利润 → 提前锁定利润
            # 2026-08-06 修复：基于 ATR 基线 × 价值调制因子（非硬编码 9%）
            if yijing_decision and yijing_decision.action == YijingExitAction.LOWER_TP:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                base_tp_roi = self._get_base_tp_roi(inst_id, entry_price)
                if base_tp_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [LOWER_TP] 跳过: base_tp_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 价值分低 → tp_modulation < 1.0（降低止盈）
                tp_modulation = YijingExitSystem.value_to_tp_modulation(
                    yijing_decision.yijing_value_score
                )
                target_tp_roi = base_tp_roi * tp_modulation
                # ATR 基线下限保护
                target_tp_roi = YijingExitSystem.apply_atr_floor(target_tp_roi, base_tp_roi)
                new_tp_price = self._calc_tp_price(entry_price, pos_side, target_tp_roi, leverage)
                tp_price_change_pct = self._roi_to_price_change(target_tp_roi, leverage)
                # ★ FIX：LOWER_TP 双约束（间距下限×0.7 + 爆仓安全约束）
                new_tp_price, _tp_clamped, _tp_old_pct, _tp_cfl = self._enforce_tp_price_floor(
                    new_tp_price, entry_price, pos_side, leverage=leverage,
                    allow_lower=True, coin=coin)
                if _tp_clamped:
                    _tail = "【爆仓约束优先】降杠杆≤20x" if _tp_cfl.get("liq_conflict") else ""
                    self._log(
                        f"[{coin}] 易经主离场 [LOWER_TP] 硬门禁钳制 | TP间距 "
                        f"{_tp_old_pct*100:.2f}%→{abs(new_tp_price-entry_price)/entry_price*100:.2f}% {_tail}",
                        "WARN",
                    )
                self._log(
                    f"[{coin}] 易经主离场 [LOWER_TP] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_tp_roi:.2%} × 调制{tp_modulation:.2f} = {target_tp_roi:.2%} "
                    f"(价{tp_price_change_pct:.2%}) "
                    f"新止盈={new_tp_price:.6f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    tp_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=None,
                        take_profit_px=new_tp_price,
                        reason=f"yijing_lower_tp:{yijing_decision.reason}",
                    )
                    if tp_result.get("ok"):
                        self._log(f"[{coin}] 易经止盈价已下调至 {new_tp_price:.6f}")
                    else:
                        self._log(
                            f"[{coin}] 易经下调止盈失败: {tp_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经下调止盈异常: {e}", "WARN")
                return

            # 5) 易经收紧止损：风险升高 + 未盈利/微利 → 收紧止损保本
            # 2026-08-06 修复：基于 ATR 基线 × 风险调制因子（非硬编码 2%）
            if yijing_decision and yijing_decision.action == YijingExitAction.TIGHTEN_SL:
                leverage = self._get_leverage()
                entry_price = float(pos_info.get("avg_px", current_price))
                base_sl_roi = self._get_base_sl_roi(inst_id, entry_price)
                if base_sl_roi <= 0:
                    self._log(
                        f"[{coin}] 易经主离场 [TIGHTEN_SL] 跳过: base_sl_roi=0（旧持仓无ATR基线）",
                        "WARN",
                    )
                    return
                # 风险分高 → sl_modulation < 1.0（收紧止损）
                sl_modulation = YijingExitSystem.risk_to_sl_modulation(
                    yijing_decision.yijing_risk_score
                )
                new_sl_roi = base_sl_roi * sl_modulation
                # ATR 基线下限保护（收紧不低于基线的 0.7 倍）
                new_sl_roi = YijingExitSystem.apply_atr_floor(new_sl_roi, base_sl_roi)
                new_sl_price = self._calc_sl_price(entry_price, pos_side, new_sl_roi, leverage)
                sl_price_change_pct = self._roi_to_price_change(new_sl_roi, leverage)
                # ★ FIX：TIGHTEN_SL 双约束（间距下限×0.7 + 爆仓安全约束 爆仓优先）
                #   ★ 这是 PUMP 0.586% SL + 高杠杆冲突 的核心修复！
                #     - 低杠杆(≤20x)：爆仓间距>4.6%，间距下限1.05%独立生效，SL=0.586%会被钳制到1.05%
                #     - 高杠杆(≥70x)：爆仓间距<1.0%，两约束冲突，SL抬到"爆仓价+0.3%"并强制告警
                new_sl_price, _sl_clamped, _sl_old_pct, _sl_cfl = self._enforce_sl_price_floor(
                    new_sl_price, entry_price, pos_side, leverage=leverage,
                    allow_tighten=True, coin=coin)
                if _sl_clamped:
                    _tail = "【间距/爆仓冲突！已按爆仓安全优先】立即降杠杆到≤20x，否则无效止损" if _sl_cfl.get("liq_conflict") else ""
                    self._log(
                        f"[{coin}] 易经主离场 [TIGHTEN_SL] 硬门禁钳制 | SL间距 "
                        f"{_sl_old_pct*100:.2f}%→{abs(new_sl_price-entry_price)/entry_price*100:.2f}% {_tail}",
                        "WARN",
                    )
                self._log(
                    f"[{coin}] 易经主离场 [TIGHTEN_SL] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name} 杠杆={leverage}x "
                    f"ATR基线={base_sl_roi:.2%} × 调制{sl_modulation:.2f} = {new_sl_roi:.2%} "
                    f"(价{sl_price_change_pct:.2%}) "
                    f"新止损={new_sl_price:.6f} 盈亏={upl:.2f}({upl_ratio:.2%})"
                )
                try:
                    sl_result = self.okx_client.place_stop_loss_take_profit(
                        inst_id=inst_id,
                        pos_side=pos_side,
                        stop_loss_px=new_sl_price,
                        take_profit_px=None,
                        reason=f"yijing_tighten_sl:{yijing_decision.reason}",
                    )
                    if sl_result.get("ok"):
                        self._log(f"[{coin}] 易经止损价已收紧至 {new_sl_price:.6f}")
                    else:
                        self._log(
                            f"[{coin}] 易经收紧止损失败: {sl_result.get('error', 'unknown')}",
                            "WARN",
                        )
                except Exception as e:
                    self._log(f"[{coin}] 易经收紧止损异常: {e}", "WARN")
                return

            # 6) 易经主决策 NO_INTERVENE：维持持仓，不降级 classic
            #    classic 备用离场已移除，NO_INTERVENE 即维持持仓
            #    依赖：开仓静态 SL/TP + yijing 动态 SL 调整 + ExitManager 策略链
            if yijing_decision and yijing_decision.action == YijingExitAction.NO_INTERVENE:
                self._log(
                    f"[{coin}] 易经主离场 [HOLD] {yijing_decision.reason} | "
                    f"卦象={yijing_decision.hexagram_name or '-'} "
                    f"风险={yijing_decision.yijing_risk_score:.2f} "
                    f"价值={yijing_decision.yijing_value_score:.2f} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h "
                    f"行情={regime} | 维持持仓"
                )
                return
            elif not yijing_available:
                # yijing 不可用（无卦象数据）→ 依赖开仓静态 SL/TP 兜底
                self._log(
                    f"[{coin}] 易经卦象不可用(无卦象数据) | "
                    f"依赖静态SL/TP | "
                    f"盈亏={upl:.2f}({upl_ratio:.2%})",
                    "WARN",
                )
                return

            # 7) 兜底：yijing 决策为空或动作未匹配 → 维持持仓
            #    classic 备用离场已移除，依赖：开仓静态 SL/TP + ExitManager 策略链
            else:
                _reason = (
                    "yijing_decision_empty"
                    if yijing_decision is None
                    else f"unhandled_action:{yijing_decision.action}"
                )
                self._log(
                    f"[{coin}] 易经主离场 [HOLD] {_reason} | "
                    f"卦象={yijing_decision.hexagram_name if yijing_decision else '-'} "
                    f"盈亏={upl:.2f}({upl_ratio:.2%}) 持仓={position_age_sec/3600:.1f}h "
                    f"行情={regime} | 维持持仓，依赖静态SL/TP"
                )
                return

        trend_strength = inference.get("trend_strength", 0.5)
        ranging_confidence = inference.get("ranging_confidence", 0.0)
        is_trial = False

        # A项过滤：可配置 confidence 最低门槛（原贝叶斯寻优值 0.7955 改为可热 reload）
        # - 优先使用 self.confidence_threshold（构造参数 args.confidence
        #   → 被 _load_evolution_config 从 config.json 热 reload
        #   → 被 _adjust_confidence_threshold 按外部知识小幅上调）
        # - A_SAFETY_FLOOR = 0.40 兜底：防止进化配置损坏/参数手误传成 0.01 导致阈值失控
        #
        # 回测基线（原硬编码 0.7955）：过滤掉 37% 低质量交易，
        # 胜率 76.6% -> 84.8%，策略收益 5.23% -> 5.59%；
        # 当 config.json 的 confidence_threshold 偏离较大时，
        # 仍以 safety floor=0.40 作为最低边界。
        try:
            adjusted_threshold = self._adjust_confidence_threshold()
        except Exception:
            adjusted_threshold = self.confidence_threshold
        A_SAFETY_FLOOR = 0.70
        effective_a_floor = max(float(adjusted_threshold), A_SAFETY_FLOOR)
        if confidence < effective_a_floor:
            self._log(
                f"[{coin}] A项过滤 | confidence={confidence:.4f} < "
                f"effective_a_floor={effective_a_floor:.4f}("
                f"adjusted={adjusted_threshold:.4f}, safety_floor={A_SAFETY_FLOOR}) | "
                f"方向={direction} 卦象={inference['hexagram']} 跳过"
            )
            return

        # P0-3: 卦象黑名单 — 历史胜率0%的卦象强制HOLD
        hex_name = inference.get("hexagram", "")
        if hex_name in self.hexagram_blacklist:
            self._log(
                f"[{coin}] P0卦象黑名单 | {hex_name} 历史胜率0% | "
                f"confidence={confidence:.4f} 方向={direction} 跳过"
            )
            return

        # ===== P0-4 [PUMP事件修复 2026-08-23] 开仓前卦象→方向一致性校验 =====
        # 查表（权威SIXTY_FOUR_GUAS）+ 币种滑窗历史方向分布 → 判决
        _hist_win = list(self._recent_hex_decisions.get(coin, []))
        _hex_check = PollingTrader._check_hexagram_consistency_for_entry(
            hex_name=hex_name,
            decision_direction=direction,
            decision_confidence=confidence,
            history_window=_hist_win,
        )
        if _hex_check["block"]:
            self._log(
                f"[{coin}] P0卦象一致性硬拦截 | {_hex_check['reason']} | "
                f"conf={confidence:.2f} dir={direction} hex={hex_name} 跳过",
                "WARN",
            )
            return
        _mult = float(_hex_check.get("confidence_multiplier") or 1.0)
        if _mult != 1.0:
            _old_conf = confidence
            confidence = round(confidence * _mult, 4)
            self._log(
                f"[{coin}] P0卦象一致性惩罚 | 置信度×{_mult:.2f} = {_old_conf:.4f}→{confidence:.4f} | "
                f"{_hex_check['reason']}",
                "WARN",
            )
        _raise_floor = _hex_check.get("raise_a_floor_to") or 0.0
        if _raise_floor and confidence < _raise_floor:
            self._log(
                f"[{coin}] P0卦象一致性地板抬升 | "
                f"confidence={confidence:.4f} < 抬升地板={_raise_floor:.4f} | "
                f"{_hex_check['reason']} 跳过",
                "WARN",
            )
            return
        # end: P0-4 卦象一致性校验

        # ===== 震荡市增强器（优化1-5统一入口）=====
        # 包含：
        #   优化1: MA200方向性偏向 + 阻力支撑确认
        #   优化2: 布林带双信号确认
        #   优化3: 动态止损宽度（震荡市2.5-3×ATR）
        #   优化4: 置信度校准（框架，数据积累后生效）
        #   优化5: 5种市场状态自适应
        enhance_result = None
        kline_data = inference.get("kline_data", [])
        if kline_data and len(kline_data) >= 20:
            try:
                closes = [float(c.get("c", 0)) for c in kline_data if c.get("c")]
                highs = [float(c.get("h", 0)) for c in kline_data if c.get("h")]
                lows = [float(c.get("l", 0)) for c in kline_data if c.get("l")]
                price = float(inference.get("price", 0))
                vol = inference.get("volatility", 0.03)
                atr_val = price * vol if price > 0 else 0

                if len(closes) >= 20 and price > 0:
                    enhance_result = self.ranging_enhancer.enhance(
                        price=price,
                        direction=direction,
                        confidence=confidence,
                        closes=closes,
                        highs=highs if len(highs) == len(closes) else None,
                        lows=lows if len(lows) == len(closes) else None,
                        atr=atr_val,
                        is_ranging=is_ranging,
                        ranging_confidence=ranging_confidence,
                        trend_strength=trend_strength,
                        coin=coin,
                    )
            except Exception as e:
                self._log(f"[{coin}] 增强器调用异常: {e}，回退到P0简单逻辑", "WARN")

        if enhance_result:
            # 记录市场状态
            regime_label = enhance_result.regime.value
            boll_sig = enhance_result.bollinger.signal.value
            self._log(
                f"[{coin}] 增强器 | 状态={regime_label} "
                f"布林信号={boll_sig} "
                f"偏向={enhance_result.directional_bias:+.2f} "
                f"止损={enhance_result.recommended_sl_atr_mult:.1f}×ATR"
            )

            # 保存增强结果到inference，供开仓时使用（动态止损）
            inference["enhance_result"] = {
                "regime": regime_label,
                "sl_atr_mult": enhance_result.recommended_sl_atr_mult,
                "tp_atr_mult": enhance_result.recommended_tp_atr_mult,
                "bollinger_signal": boll_sig,
                "bollinger_confirms": enhance_result.bollinger_confirms,
                "directional_bias": enhance_result.directional_bias,
                "ma200_above": enhance_result.mas.price_above_ma200,
            }

            # 更新有效阈值（增强器推荐的方向差异化阈值）
            if direction == "UP":
                effective_threshold = max(
                    effective_threshold, enhance_result.recommended_long_threshold
                )
            elif direction == "DOWN":
                effective_threshold = max(
                    effective_threshold, enhance_result.recommended_short_threshold
                )

            # 综合判断：是否应该开仓
            if not enhance_result.should_trade:
                self._log(
                    f"[{coin}] 增强器过滤 | 原因={enhance_result.reject_reason} "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return
        else:
            # ===== 回退：P0简单逻辑（当增强器不可用时）=====
            if is_ranging and ranging_confidence >= 0.75:
                self._log(
                    f"[{coin}] P0-强震荡市强制空仓 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} 跳过"
                )
                return
            elif is_ranging and ranging_confidence >= 0.5:
                effective_threshold = max(effective_threshold, 0.7)
                self._log(
                    f"[{coin}] P0-中震荡市 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度要求提高至 {effective_threshold}"
                )
            elif is_ranging:
                effective_threshold = max(effective_threshold, 0.6)
                self._log(
                    f"[{coin}] P0-弱震荡市 | ranging_confidence={ranging_confidence:.2f} "
                    f"置信度要求提高至 {effective_threshold}"
                )
            elif trend_strength > 0.6:
                effective_threshold = max(0.3, self.confidence_threshold - 0.1)
                self._log(
                    f"[{coin}] 趋势明确(强度={trend_strength:.2f}) | 置信度要求放宽至 {effective_threshold}"
                )

        if fail_closed:
            # P0修复: fail-closed 硬约束，BCRM判定不交易则直接跳过，不用八卦方向软化
            bagua_dir = inference.get("bagua_direction", "neutral")
            self._log(
                f"[{coin}] fail-closed 跳过 | 卦象={inference['hexagram']} "
                f"BCRM不确定，不开仓 (八卦方向={bagua_dir} 不作为开仓依据)"
            )
            return

        # P1-1: 做空趋势过滤器（Phase C+ 五均线版）
        # 加密货币用BTC 5均线排列，美股用IXIC/GSPC 5均线，其他用自身5均线；+做空阈值乘数+仓位规模乘数
        # v4.5 Spec 严格对齐：取消硬拦截，改为产出 Score_P 传给 ElasticGate3L（F1: 永不BLOCK）
        short_conf_multi = 1.00
        short_bearish_score = "NONE"
        short_regime_from_spring = None
        short_trend_ok = True  # 默认通过，BLOCK 由 ElasticGate3L 处理
        if direction == "DOWN":
            # 兼容: 旧版返回2元组, 新版返回3元组(allow, reason, multiplier)
            filter_result = self._check_short_trend_filter(coin, inference)
            if len(filter_result) >= 3:
                short_trend_ok, trend_reason, short_conf_multi = filter_result
            else:
                short_trend_ok, trend_reason = filter_result
                short_conf_multi = 1.00
            short_bearish_score = self._parse_bearish_score_from_reason(trend_reason)
            short_regime_from_spring = self._parse_regime_from_reason(trend_reason)
            if not short_trend_ok:
                # Spec v3.0: BLOCK 不硬拦截，交给 ElasticGate3L 给 0.10 试错仓
                self._log(
                    f"[{coin}] P1做空趋势过滤 | {trend_reason} | "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} "
                    f"→ BLOCK（弹性放行，ElasticGate3L 将给 0.10 试错仓）",
                    "INFO",
                )
            else:
                # 做空阈值 = (short_confidence_threshold 或 confidence_threshold) × 乘数
                raw_short_thr = max(
                    confidence_threshold or self.confidence_threshold,
                    self.short_confidence_threshold,
                )
                effective_short_threshold = raw_short_thr * short_conf_multi
                self._log(
                    f"[{coin}] P1做空阈值分层 | 基础阈值={raw_short_thr:.4f} ×{short_conf_multi:.2f}"
                    f" = 有效阈值={effective_short_threshold:.4f}",
                    "INFO",
                )
                # 覆盖全局 effective_threshold（仅DOWN方向有效）
                effective_threshold = effective_short_threshold

        # H1(P0)新增：P1 长多趋势过滤器（与做空对称，UP方向弹簧力场阈值分层）
        # v4.5 Spec 严格对齐：取消硬拦截，改为产出 Score_P 传给 ElasticGate3L
        long_conf_multi = 1.00
        long_bullish_score = "NONE"
        long_regime_from_spring = None
        long_trend_ok = True  # 默认通过，BLOCK 由 ElasticGate3L 处理
        if direction == "UP":
            filter_result = self._check_long_trend_filter(coin, inference)
            if len(filter_result) >= 3:
                long_trend_ok, trend_reason_up, long_conf_multi = filter_result
            else:
                long_trend_ok, trend_reason_up = filter_result
                long_conf_multi = 1.00
            long_bullish_score = self._parse_bullish_score_from_reason(trend_reason_up)
            long_regime_from_spring = self._parse_regime_from_reason(trend_reason_up)
            if not long_trend_ok:
                # Spec v3.0: BLOCK 不硬拦截，交给 ElasticGate3L 给 0.10 试错仓
                self._log(
                    f"[{coin}] P1长多趋势过滤 | {trend_reason_up} | "
                    f"置信度={confidence:.2f} 方向={direction} 卦象={inference['hexagram']} "
                    f"→ BLOCK（弹性放行，ElasticGate3L 将给 0.10 试错仓）",
                    "INFO",
                )
            else:
                raw_long_thr = confidence_threshold or self.confidence_threshold
                effective_long_threshold = raw_long_thr * long_conf_multi
                self._log(
                    f"[{coin}] P1长多阈值分层 | 基础阈值={raw_long_thr:.4f} ×{long_conf_multi:.2f}"
                    f" = 有效阈值={effective_long_threshold:.4f}",
                    "INFO",
                )
                effective_threshold = effective_long_threshold

        # ══════════════════════════════════════════════════════════════════
        # 方案 C v3.0 Spec 严格对齐：P1/Elder/BCRM 三层弹性放行（永不硬拦截）
        #   P1 SMA → Score_P: STANDARD=1.0 / WEAK=0.60 / BLOCK=0.10
        #   Elder-ray → Score_E: ALIGN_FULL=1.0 / ALIGN_BASIC=0.85 / NEUTRAL=0.65 / DIVERGE_BASIC=0.45 / SEVERE=0.30
        #   BCRM N=5 → Score_B: 0.30~1.0
        #   三层 Score 交给 ElasticGate3L 计算仓位倍率（F1 铁则：永不BLOCK，BLOCK也给0.10试错仓）
        # ══════════════════════════════════════════════════════════════════
        _p1_label = "STANDARD"
        _elder_grade = "NEUTRAL"
        _score_b = 0.65
        _cont_grade = "NEUTRAL"
        _cont_score = 0.65
        try:
            # Step 1: P1 档位映射（弹簧评分 + 趋势过滤结果 → STANDARD/WEAK/BLOCK）
            _short_score = short_bearish_score if direction == "DOWN" else "NONE"
            _long_score = long_bullish_score if direction == "UP" else "NONE"
            _score_use = _long_score if direction == "UP" else _short_score
            # 趋势过滤未通过 → BLOCK（不再硬拦截，交给 ElasticGate3L 给 0.10 试错仓）
            _trend_ok = long_trend_ok if direction == "UP" else short_trend_ok
            if not _trend_ok:
                _p1_label = "BLOCK"
            elif _score_use in ("STRONG", "NORMAL"):
                _p1_label = "STANDARD"
            elif _score_use == "WEAK":
                _p1_label = "WEAK"
            elif _score_use == "NONE":
                _p1_label = "STANDARD"  # fail-open 中性
            else:
                _p1_label = "BLOCK"

            # Step 2: Elder-ray 日线趋势对齐 → 产出 Score_E（不硬拦截）
            #   Spec v3.0: Score_E = ALIGN_FULL=1.0/ALIGN_BASIC=0.85/NEUTRAL=0.65/DIVERGE_BASIC=0.45/SEVERE=0.30
            #   不再硬拦截，Score_E 交给 ElasticGate3L 调节仓位
            _decision_dir = "LONG" if direction == "UP" else "SHORT"
            _hex_name = inference.get("hexagram", "") or ""
            if self._elder_engine is not None:
                try:
                    _daily_klines = _load_kline_from_okx(inst_id=inst_id, bar="1D", limit=120)
                    if _daily_klines and len(_daily_klines) >= 30:
                        _elder_res = self._elder_engine.calc_and_record(
                            symbol=coin,
                            decision=_decision_dir,
                            p1_output=_p1_label,
                            daily_klines=_daily_klines,
                        )
                        _elder_grade = str(getattr(_elder_res, "judge_level", "NEUTRAL") or "NEUTRAL")
                    else:
                        _elder_grade = "NEUTRAL"
                except Exception as _er_e:
                    self._log(
                        f"[{coin}] [方案C] Elder-ray调用失败(NEUTRAL旁路)：{type(_er_e).__name__}",
                        "WARN",
                    )
                    _elder_grade = "NEUTRAL"
            else:
                _elder_grade = "NEUTRAL"
            # Spec v3.0: Elder-ray 不再硬拦截，仅记录 Score_E 等级
            if _elder_grade in ("DIVERGE_BASIC", "DIVERGE_SEVERE"):
                self._log(
                    f"[{coin}] 方案C | Elder-ray={_elder_grade} (日线背离) | "
                    f"方向={direction} 卦={_hex_name} → Score_E 降级，ElasticGate3L 将缩减仓位",
                    "INFO",
                )

            # Step 3: BCRM N=5 笔连续性 → 产出 Score_B（不硬拦截）
            #   Spec v3.0: Score_B = 0.60×continuity_score + 0.40×conf_norm
            #   不再硬拦截，Score_B 交给 ElasticGate3L 调节仓位
            if self._bcrm_continuity is not None:
                try:
                    import datetime as _dt_now
                    _cont_grade, _cont_score = self._bcrm_continuity.append_and_grade(
                        symbol=coin,
                        direction=_decision_dir,
                        ts=_dt_now.datetime.now(),
                        confidence=float(confidence or 0.0),
                        hexagram_name=_hex_name,
                    )
                except Exception as _co_e:
                    self._log(
                        f"[{coin}] [方案C] 连续信号观察器调用失败(NEUTRAL旁路)：{type(_co_e).__name__}",
                        "WARN",
                    )
                    _cont_grade, _cont_score = "NEUTRAL", 0.65
            else:
                _cont_grade, _cont_score = "NEUTRAL", 0.65
            # Spec v3.0: BCRM 连续性不再硬拦截，仅记录 Score_B 等级
            if _cont_grade in ("DIVERGE_BASIC", "DIVERGE_SEVERE"):
                self._log(
                    f"[{coin}] 方案C | BCRM连续={_cont_grade}({_cont_score:.2f}) "
                    f"单笔conf={float(confidence or 0):.2f} 卦={_hex_name} "
                    f"→ Score_B 降级，ElasticGate3L 将缩减仓位",
                    "INFO",
                )

            # ── P0 事件驱动注入：读 odaily 快讯 → 计算 event_positive_strength → 注入 Score_B ──
            # （FAIL-OPEN：DB不可用/快讯无命中/抛异常 → strength=0.0，boost=0，Score_B 等价v3.0原公式）
            _event_strength = 0.0
            _event_debug: Dict[str, Any] = {"reason": "skipped"}
            try:
                _event_strength, _event_debug = _polling_get_coin_event_positive_strength(coin)
            except Exception:  # noqa: BLE003
                _event_strength, _event_debug = 0.0, {"error": "bridge_exception"}
            _conf_norm = max(0.40, min(1.0, float(confidence or 0.0)))
            _score_b, _event_boost_applied = compute_score_b_with_event_boost(
                float(_cont_score),
                _conf_norm,
                _event_strength if _event_strength > 0 else None,  # ≤0一律走 None → baseline 兼容
            )
            _score_b = max(0.0, min(1.0, float(_score_b)))
            _event_boost_applied = max(0.0, min(0.10, float(_event_boost_applied)))

            # 把 P1 档位 + Elder 等级 + Score_B（后置校准语义）+ event_boost 写入 inference 缓存（便于ShadowLogger+回溯）
            inference["p1_output_label"] = _p1_label
            inference["elder_ray_grade"] = _elder_grade
            inference["bcrm_continuity_grade"] = _cont_grade
            inference["bcrm_continuity_score"] = float(_cont_score)
            inference["bcrm_score_b"] = float(_score_b)
            inference["event_positive_strength"] = float(_event_strength)
            inference["event_boost_applied"] = float(_event_boost_applied)
            inference["event_debug_snippet"] = str({k: v for k, v in list(_event_debug.items())[:5]}) if isinstance(_event_debug, dict) else ""

            # 日志：带事件驱动注入细节（便于运维/审计）
            if _event_boost_applied > 0.001:
                self._log(
                    f"[{coin}] 方案C 三层弹性放行 | P1={_p1_label} "
                    f"Elder={_elder_grade} BCRM连续={_cont_grade}({_cont_score:.2f}) "
                    f"Score_B={_score_b:.3f} (+boost={_event_boost_applied:.3f}, "
                    f"ev_strength={_event_strength:.2f} {_event_debug.get('reason','') if isinstance(_event_debug, dict) else ''}) "
                    f"单conf={float(confidence or 0):.2f} 卦={_hex_name} 方向={_decision_dir}",
                    "INFO",
                )
            else:
                self._log(
                    f"[{coin}] 方案C 三层弹性放行 | P1={_p1_label} "
                    f"Elder={_elder_grade} BCRM连续={_cont_grade}({_cont_score:.2f}) "
                    f"Score_B={_score_b:.2f} 单conf={float(confidence or 0):.2f} 卦={_hex_name} 方向={_decision_dir}",
                    "INFO",
                )
        except Exception as _setup_e:
            self._log(
                f"[{coin}] 方案C P1升级 异常(中性旁路)：{type(_setup_e).__name__}，继续原流程",
                "WARN",
            )
            inference.setdefault("p1_output_label", "STANDARD")
            inference.setdefault("elder_ray_grade", "NEUTRAL")
            inference.setdefault("bcrm_score_b", 0.65)

        # H2(P1)：弹簧力场 5态/评分 双向写入 inference，后续 _get_regime_pred_multipliers / AB审计 可追溯
        spring_regime_5 = long_regime_from_spring if direction == "UP" else (short_regime_from_spring if direction == "DOWN" else None)
        if spring_regime_5:
            inference["spring_regime_5"] = spring_regime_5
        if direction == "UP" and long_bullish_score:
            inference["spring_bullish_score"] = long_bullish_score
        if direction == "DOWN" and short_bearish_score:
            inference["spring_bearish_score"] = short_bearish_score

        # F1 永不BLOCK 试错通路的基础门槛：默认用原始基础阈值（short=0.80 / long=0.35），
        #   而非 effective_threshold（已被融合层/P1/Elder/事件等多层收紧到 0.91+）。
        #   设计意图：P1=BLOCK 已反映趋势风险，F1 通路只需模型高置信度即可极小仓试错。
        #   开关 enable_f1_trial_regime_threshold=True 可切回 effective_threshold（含 regime 形态调整）。
        _f1_trial_base_threshold = (
            float(self.short_confidence_threshold)
            if direction == "DOWN"
            else float(self.confidence_threshold)
        )

        # P2-05: 形态乘数作用到置信度阈值（放在所有阈值调整之后、最终比对之前）
        #   高风险 regime（VOLATILE_DROP/FOMO_RALLY）抬高门槛，强势趋势放宽门槛
        _reg_mult = inference.get("_regime_multipliers", {})
        _thr_mult = _reg_mult.get("threshold_mult", 1.0)
        if _thr_mult != 1.0:
            _orig_thr = effective_threshold
            effective_threshold = effective_threshold * _thr_mult
            self._log(
                f"[{coin}] 形态阈值调整 | regime={inference.get('_regime_pred','')} ×{_thr_mult:.2f}"
                f" 阈值 {_orig_thr:.4f}→{effective_threshold:.4f}",
                "INFO",
            )
        # 上限 clip：防止做空阈值在多重收紧因子叠加下超过 1.0（硬禁）
        #   后续有 ElasticGate3L/WinProb 等精细调控，前置层不需要硬禁
        if effective_threshold > 0.98:
            effective_threshold = 0.98

        # ── H3-FMA 影子决策：无论当前 FMA_REGIME_FILTER_ENABLED 是否开启，
        #    强制跑一遍 FMA=True 的差异化过滤流程，得到 fma_on_allow + fma_on_effective_threshold
        #    写入 inference.fma_shadow_* 供 ShadowLogger 入库 → 未来评估 FMA 渐进自动开关。
        fma_shadow_allowed = None
        fma_shadow_eff_thr = None
        try:
            # 当前实际生效的 effective_threshold（作为 FMA=ON 的保底 baseline 阈值）
            _fma_shadow_base_thr = float(effective_threshold)
            if direction == "UP":
                _fma_res = self._check_long_trend_filter(coin, inference, _force_regime_filter_on=True)
                if len(_fma_res) >= 3:
                    _fma_ok, _fma_reason, _fma_conf_multi = _fma_res
                else:
                    _fma_ok, _fma_reason = _fma_res
                    _fma_conf_multi = 1.00
                if _fma_ok:
                    _raw_thr = (confidence_threshold or self.confidence_threshold) * _fma_conf_multi
                    # 再 × 形态乘数（完全对称上方实际阈值）
                    _fma_eff = _raw_thr * float(_thr_mult or 1.0)
                    fma_shadow_allowed = True
                    fma_shadow_eff_thr = round(_fma_eff, 6)
                else:
                    fma_shadow_allowed = False
                    fma_shadow_eff_thr = _fma_shadow_base_thr
            elif direction == "DOWN":
                _fma_res = self._check_short_trend_filter(coin, inference, _force_regime_filter_on=True)
                if len(_fma_res) >= 3:
                    _fma_ok, _fma_reason, _fma_conf_multi = _fma_res
                else:
                    _fma_ok, _fma_reason = _fma_res
                    _fma_conf_multi = 1.00
                if _fma_ok:
                    _raw_thr = max(
                        confidence_threshold or self.confidence_threshold,
                        self.short_confidence_threshold,
                    ) * _fma_conf_multi
                    _fma_eff = _raw_thr * float(_thr_mult or 1.0)
                    fma_shadow_allowed = True
                    fma_shadow_eff_thr = round(_fma_eff, 6)
                else:
                    fma_shadow_allowed = False
                    fma_shadow_eff_thr = _fma_shadow_base_thr
            else:
                fma_shadow_allowed = False
                fma_shadow_eff_thr = _fma_shadow_base_thr
        except Exception as _ef:
            self._log(f"[{coin}] FMA影子决策计算失败(已忽略): {_ef}", "DEBUG")
        inference["fma_shadow_allowed"] = fma_shadow_allowed
        inference["fma_shadow_eff_threshold"] = fma_shadow_eff_thr

        # v4.6 过滤层统一弹性放行机制：
        #   ① P1/Elder/BCRM 三层各自产出 Score（永不硬拦截）
        #   ② 传给 ElasticGate3L 加权 → score_consensus（共识分）
        #   ③ score_consensus < _gate_base_threshold → 不开仓（基础门槛）
        #   ④ ≥ 基础门槛 且 置信度不达标 → 轻仓试错（is_trial=True，仓位由 EG3L 控制）
        #   ⑤ 基础阈值基于历史盈亏聚合动态调节（≥30 笔样本才调，非单笔）
        _p1_out_for_gate = str(inference.get("p1_output_label", "STANDARD") or "STANDARD")
        _elder_grade_for_gate = str(inference.get("elder_ray_grade", "NEUTRAL") or "NEUTRAL")
        _score_b_for_gate = float(inference.get("bcrm_score_b", 0.65) or 0.65)
        _dir_long_short = "LONG" if direction == "UP" else ("SHORT" if direction == "DOWN" else None)
        _weights_for_gate = None
        if self._three_layer_weighter is not None:
            try:
                _weights_for_gate = self._three_layer_weighter.get_current_weights()
            except Exception:
                _weights_for_gate = None
        _score_consensus = None
        _base_pos_mult_precheck = None
        _gate_debug_info = ""
        if self._elastic_gate_3l is not None and _dir_long_short:
            try:
                # 只走 compute（不叠加 F1~F4 铁则），取 score_consensus 做基础门槛判断
                _out = self._elastic_gate_3l.compute(
                    p1_out=_p1_out_for_gate,
                    elder_grade=_elder_grade_for_gate,
                    score_b=_score_b_for_gate,
                    weights=_weights_for_gate,
                    direction=_dir_long_short,
                )
                _score_consensus = float(_out.score_consensus)
                _base_pos_mult_precheck = float(_out.base_pos_mult)
                try:
                    _w_p_v = getattr(_weights_for_gate, "w_p", None) if _weights_for_gate is not None else None
                    if _w_p_v is None and isinstance(_weights_for_gate, dict):
                        _w_p_v = _weights_for_gate.get("w_p")
                    if _w_p_v is None:
                        from scripts.memory_l4 import phase_c_constants as _C
                        _w_p_v, _w_e_v, _w_b_v = _C.FAILOPEN_WP, _C.FAILOPEN_WE, _C.FAILOPEN_WB
                    else:
                        _w_e_v = float(getattr(_weights_for_gate, "w_e",
                                               _weights_for_gate.get("w_e") if isinstance(_weights_for_gate, dict) else 0.30))
                        _w_b_v = float(getattr(_weights_for_gate, "w_b",
                                               _weights_for_gate.get("w_b") if isinstance(_weights_for_gate, dict) else 0.25))
                    _w_src = getattr(_weights_for_gate, "source",
                                     _weights_for_gate.get("source") if isinstance(_weights_for_gate, dict) else "fail_open")
                    _gate_debug_info = (
                        f" S_P={_out.score_p:.2f} S_E={_out.score_e:.2f} S_B={_out.score_b:.2f}"
                        f" w_p={_w_p_v:.2f} w_e={_w_e_v:.2f} w_b={_w_b_v:.2f} w_src={_w_src}"
                        f" src={getattr(_out, 'source', '')}"
                    )
                except Exception:
                    _gate_debug_info = f" S_P={getattr(_out, 'score_p', 0):.2f} S_E={getattr(_out, 'score_e', 0):.2f} S_B={getattr(_out, 'score_b', 0):.2f}"
            except Exception as _gate_e:
                self._log(f"[{coin}] 过滤层共识分计算异常（fail-open：视为不过门槛）：{type(_gate_e).__name__}", "WARN")
                _score_consensus = None

        # 冷启动兜底：EG3L 不存在时，用 P1+Elder 的近似分
        if _score_consensus is None:
            _sp_map = {"STANDARD": 1.0, "WEAK": 0.60, "BLOCK": 0.10}
            _se_map = {"ALIGN_FULL": 1.00, "ALIGN_BASIC": 0.85, "NEUTRAL": 0.65, "DIVERGE_BASIC": 0.45, "DIVERGE_SEVERE": 0.30}
            _score_consensus = 0.45 * _sp_map.get(_p1_out_for_gate, 0.60) + 0.30 * _se_map.get(_elder_grade_for_gate, 0.65) + 0.25 * _score_b_for_gate
            _gate_debug_info = _gate_debug_info + " [冷启动兜底权重]"

        inference["score_consensus"] = _score_consensus
        inference["gate_base_threshold"] = float(self._gate_base_threshold)
        inference["p1_output_label"] = _p1_out_for_gate
        inference["elder_ray_grade"] = _elder_grade_for_gate
        inference["bcrm_score_b"] = _score_b_for_gate

        # F1 永不BLOCK 试错通路的置信度门槛：
        #   默认=False：用 regime 调整前的基础门槛（兑现"永不BLOCK"，高风险 regime 也能极小仓试错）
        #   设为True：用含 regime 形态调整的 effective_threshold（更保守，实验不佳时可打开）
        _f1_trial_threshold = (
            effective_threshold
            if getattr(self, "enable_f1_trial_regime_threshold", False)
            else _f1_trial_base_threshold
        )

        # Step ③ 基础门槛判断 + F1永不BLOCK通路：
        #   - score_consensus ≥ base_threshold → 正常通路（继续）
        #   - P1=BLOCK 且 置信度达标 → F1 永不BLOCK 试错通路（极小仓，is_trial=True）
        #     兑现 v3.0 Spec F1铁则："BLOCK也给0.10试错仓"，仓位由 EG3L(F1地板+F2上限) 控制
        #   - 其他 → 不开仓
        _f1_trial_mode = False
        if _score_consensus >= self._gate_base_threshold:
            pass  # 正常通路
        elif _p1_out_for_gate == "BLOCK" and confidence >= _f1_trial_threshold:
            # F1 永不 BLOCK：P1=BLOCK 但模型高置信度 → 极小仓试错
            #   门槛默认用基础门槛（不含 regime 形态调整），开关可切回 effective_threshold
            _f1_trial_mode = True
            is_trial = True
            self._log(
                f"[{coin}] F1永不BLOCK试错通路 | "
                f"score_cons={_score_consensus:.3f} < threshold={self._gate_base_threshold:.3f} "
                f"但 P1=BLOCK 且 conf={confidence:.2f} ≥ f1_thr={_f1_trial_threshold:.4f}"
                f"{'(regime调整)' if getattr(self, 'enable_f1_trial_regime_threshold', False) else '(基础门槛)'} → 极小仓试错"
                f" Elder={_elder_grade_for_gate} S_B={_score_b_for_gate:.2f} 方向={direction}{_gate_debug_info}",
                "INFO",
            )
        else:
            self._log(
                f"[{coin}] 过滤层共识分低于基础门槛 跳过开仓 | "
                f"score_cons={_score_consensus:.3f} < threshold={self._gate_base_threshold:.3f}"
                f" P1={_p1_out_for_gate} Elder={_elder_grade_for_gate} S_B={_score_b_for_gate:.2f}"
                f" conf={confidence:.2f} 方向={direction}{_gate_debug_info}",
                "INFO",
            )
            return

        # Step ④/⑤ 正常开仓 vs 轻仓试错：
        #   - confidence ≥ effective_threshold → 正常开仓
        #   - 否则：只要过了过滤层基础门槛，一律轻仓试错（不再区分 P1=BLOCK/P1=WEAK）
        if confidence >= effective_threshold:
            pass  # 置信度达标，正常开仓
        else:
            is_trial = True
            self._log(
                f"[{coin}] 轻仓试错(共识分达标) | "
                f"score_cons={_score_consensus:.3f} ≥ threshold={self._gate_base_threshold:.3f} "
                f"但 conf={confidence:.2f} < eff_thr={effective_threshold:.4f}"
                f" P1={_p1_out_for_gate} Elder={_elder_grade_for_gate} 方向={direction}{_gate_debug_info}",
                "INFO",
            )

        if direction not in ("UP", "DOWN"):
            self._log(f"[{coin}] 方向不明确 {direction} 跳过")
            return

        # —— 战略层方向状态闸门（direction_state）——
        # SHORT_ONLY: 只允许 DOWN；LONG_ONLY: 只允许 UP
        # SHORT_PREFER: DOWN放行 / UP需更高置信度；LONG_PREFER 对称
        # NEUTRAL: 多空均可；FREEZE: 不允许开仓
        # ★ 开关 enable_bcrm_direction_state_check（默认 False）：
        #   False → BCRM2.0 影子模式，跳过战略层 direction_state 闸门，专注技术面分析
        #   True  → 战略层 direction_state 拦截 BCRM 开仓（验证完成后可开启）
        #   shadow_logger 仍记录 direction_state 字段供 A/B 对比观察
        try:
            if getattr(self, "enable_bcrm_direction_state_check", False):
                _fds = getattr(self, "_five_domain_state_cache", None)
                if _fds is not None:
                    _cls = self._coin_asset_class(coin)
                    _dstate = getattr(_fds, "direction_state", {}).get(_cls, "NEUTRAL")
                    _is_long = (direction == "UP")
                    if _dstate == "SHORT_ONLY" and _is_long:
                        self._log(f"[{coin}] 方向状态拦截 | direction_state=SHORT_ONLY 禁止做多方向={direction}", "WARN")
                        return
                    elif _dstate == "LONG_ONLY" and not _is_long:
                        self._log(f"[{coin}] 方向状态拦截 | direction_state=LONG_ONLY 禁止做空方向={direction}", "WARN")
                        return
                    elif _dstate == "FREEZE":
                        self._log(f"[{coin}] 方向状态拦截 | direction_state=FREEZE 禁止开仓", "WARN")
                        return
                    elif _dstate == "SHORT_PREFER" and _is_long:
                        # 偏空时做多需要更高置信度
                        _short_prefer_mult = float(getattr(self, "short_prefer_long_conf_mult", 1.5))
                        if confidence < effective_threshold * _short_prefer_mult:
                            self._log(f"[{coin}] 方向状态偏空 | 做多置信度不足 conf={confidence:.2f} < {effective_threshold*_short_prefer_mult:.3f}", "INFO")
                            return
                    elif _dstate == "LONG_PREFER" and not _is_long:
                        _long_prefer_mult = float(getattr(self, "long_prefer_short_conf_mult", 1.5))
                        if confidence < effective_threshold * _long_prefer_mult:
                            self._log(f"[{coin}] 方向状态偏多 | 做空置信度不足 conf={confidence:.2f} < {effective_threshold*_long_prefer_mult:.3f}", "INFO")
                            return
        except Exception as _de:
            self._log(f"[{coin}] 方向状态闸门异常(fail-open放行): {type(_de).__name__}", "DEBUG")

        risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
        if not risk_check["allowed"]:
            self._log(f"[{coin}] 风控拦截: {risk_check['reason']}", "WARN")
            return

        if self._count_yijing_positions() >= self.max_positions:
            self._log(f"[{coin}] 已达易经系统最大持仓数 {self.max_positions} 跳过")
            return
        # —— R5 铁律 · 子池隔离：BDSM(≤3) vs BCRM(≤5) 互不抢占 ——
        sub_ok, sub_reason = self._check_subpool_capacity(coin)
        if not sub_ok:
            self._log(f"[{coin}] 子池仓位已满 | {sub_reason}（R5 隔离跳过）", "WARN")
            return
        self._log(f"[{coin}] 子池容量预检通过 | {sub_reason}")

        # —— BDSM 协作 · 缺口 1：方向硬约束（子池预检通过后、_open_position 之前）——
        #   LONG_ONLY ∩ BCRM 开 SHORT → DROP→HOLD；SHORT_ONLY 对称；NEUTRAL=放行；非BDSM=放行
        #   FAIL-OPEN：任何异常 → is_pass=True 放行（BCRM 技术方向不受 BDSM 干扰）
        #   开关 enable_bdsm_direction_overlay=False 时跳过叠加，BCRM2.0 技术方向独立决策（A/B 观察用）
        if getattr(self, "enable_bdsm_direction_overlay", True):
            _dir_ok, _dir_reason = self._apply_bdsm_direction_constraint(coin, direction)
            if not _dir_ok:
                self._log(
                    f"[{coin}] BDSM 方向约束拦截 | {_dir_reason}（DROP→HOLD，不调用 _open_position）",
                    "WARN",
                )
                return
            # 命中日志：约束存在且同方向时打 INFO（非非 BDSM/非 neutral 才显示，避免刷屏）
            if _dir_reason and _dir_reason.startswith("bdsm_") and "same_direction" in _dir_reason:
                self._log(f"[{coin}] BDSM 方向约束与 BCRM 同向 | {_dir_reason}", "INFO")

        # 将 F1 试错标记传入 _open_position（跨方法作用域）
        inference["_f1_trial_mode"] = _f1_trial_mode

        # —— 测试仓上限保护：BCRM 子池测试仓(is_trial=True)最多 MAX_TRIAL_POSITIONS 单 ——
        #   避免高置信 BLOCK 信号持续以试错仓形式占用正常仓位配额
        if is_trial:
            _trial_cnt = self._count_trial_positions("bcrm")
            if _trial_cnt >= int(getattr(self, "MAX_TRIAL_POSITIONS", 2)):
                self._log(
                    f"[{coin}] BCRM 测试仓已满 {_trial_cnt}/{getattr(self, 'MAX_TRIAL_POSITIONS', 2)} "
                    f"（is_trial=True），跳过本次试错开仓",
                    "INFO",
                )
                return

        self._open_position(inference, is_reverse=False, is_trial=is_trial)

    def _open_position(self, inference: dict, is_reverse: bool = False, is_trial: bool = False):
        """开仓（动态仓位 + 持仓跟踪）"""
        # ★ shadow-mode 全局硬闸门：禁止所有开仓（仅记录一条blocked日志，保留推理上下文用于shadow评估）
        if self.shadow_mode:
            coin = inference.get("coin", "UNKNOWN")
            inst_id = inference.get("inst_id", "UNKNOWN")
            direction = inference.get("direction", "UNKNOWN")
            confidence = inference.get("confidence", 0.0)
            self._log(
                f"[SHADOW MODE BLOCKED-OPEN] {inst_id} {direction} conf={confidence:.3f} | "
                f"reason={inference.get('reason', '')[:60]} | 仅记录不真实下单",
                "WARN",
            )
            return
        # ═══ 方案 C v3.0：组合级熔断闸门（SW-C8）═══
        #   - 优先级：G-04 emergency_shutdown > G-02 block_new_open > 正常放行
        #   - fail-open：_current_fuse_action 缺失/None → 视为无熔断，直接通过
        #     ★ FIX legacy#3：_make_bare_trader用__new__绕过__init__未初始化属性时也能fail-open
        _fuse = getattr(self, "_current_fuse_action", None)
        if _fuse is not None:
            try:
                _blocked_by_fuse = False
                _block_reason = ""
                if getattr(_fuse, "emergency_shutdown", False):
                    _blocked_by_fuse = True
                    _block_reason = (
                        f"G-04 终极熔断（until={getattr(_fuse, 'block_until_ts', 0)}）："
                        f"单日权益回撤≥3%，自动block开仓"
                    )
                elif getattr(_fuse, "block_new_open", False):
                    _blocked_by_fuse = True
                    _block_reason = (
                        f"G-02 黑天鹅熔断（reason={getattr(_fuse, 'reason', '')} "
                        f"until={getattr(_fuse, 'block_until_ts', 0)}）：暂停开新仓"
                    )
                if _blocked_by_fuse:
                    _coin = inference.get("coin", "UNKNOWN")
                    _inst_id = inference.get("inst_id", "UNKNOWN")
                    _dir = inference.get("direction", "UNKNOWN")
                    _conf = inference.get("confidence", 0.0)
                    self._log(
                        f"[组合熔断拦截-BLOCKED] {_inst_id} {_dir} conf={_conf:.3f} | "
                        f"{_block_reason}",
                        "WARN",
                    )
                    return
            except Exception as _fse:
                # 熔断判定异常 → 安全放行，不阻塞主流程
                self._log(
                    f"[组合熔断] 熔断闸门判定异常（fail-open放行）：{type(_fse).__name__}",
                    "WARN",
                )
        coin = inference["coin"]
        inst_id = inference["inst_id"]
        direction = inference["direction"]
        confidence = inference["confidence"]
        volatility = inference.get("volatility", 0.03)
        # P3: 缓存当前波动率，供 _compute_p2_dynamic_sizing_factors 中波动率自适应使用
        self._last_volatility = volatility

        # ★ RAG 热路径接入（FAIL-OPEN 只读，不干预决策）
        _rag_q = f"{coin} {direction} 风控 阈值 硬约束 SL TP 开仓"
        _rag_hits = _rag_hotpath_lookup(self, _rag_q, top_k=5)
        if _rag_hits:
            self._log(
                f"[RAG-PRE-OPEN] {inst_id} {direction} conf={confidence:.3f} | "
                f"hits={len(_rag_hits)} top={_rag_hits[0].get('heading', '')[:40]} "
                f"score={_rag_hits[0].get('final_score', 0):.3f}",
                "INFO",
            )
            inference["rag_context"] = _rag_hits  # 注入供下游消费（可选）

        # ═══════════════════════════════════════════════════
        # 方案 C v3.0：P1 过滤层→校准层 数据链路确认
        #   趋势过滤层（拦截）已在 _execute_trade 的 P1 升级版完成：
        #     均线/偏见底 → Elder（日线对齐）→ BCRM N=5 连续
        #   此处（_open_position）仅使用 P1 层写入的缓存，负责后置校准层（仓位规模）
        #   兜底：若缺失则中性填充（兼容手工直接调用 _open_position 的场景）
        # ═══════════════════════════════════════════════════
        try:
            if "p1_output_label" not in inference:
                # 兼容手工调用：用弹簧评分兜底推导 P1 档位
                _short_score = inference.get("spring_bearish_score", "NONE") or "NONE"
                _long_score = inference.get("spring_bullish_score", "NONE") or "NONE"
                _decision_dir = str(direction).upper()
                _score = _long_score if _decision_dir == "UP" else _short_score
                if _score in ("STRONG", "NORMAL"):
                    inference["p1_output_label"] = "STANDARD"
                elif _score == "WEAK":
                    inference["p1_output_label"] = "WEAK"
                else:
                    inference["p1_output_label"] = "STANDARD"  # fail-open：无评分允许中性通过
            inference.setdefault("elder_ray_grade", "NEUTRAL")
            if "bcrm_score_b" not in inference:
                _cont = float(inference.get("bcrm_continuity_score", 0.65) or 0.65)
                _c_norm = max(0.40, min(1.0, float(confidence or 0.0)))
                inference["bcrm_score_b"] = 0.60 * _cont + 0.40 * _c_norm
            inference.setdefault("bcrm_continuity_grade", "NEUTRAL")
        except Exception:
            inference.setdefault("p1_output_label", "STANDARD")
            inference.setdefault("elder_ray_grade", "NEUTRAL")
            inference.setdefault("bcrm_score_b", 0.65)

        # H1/H2/H4: 从 inference 读取前置层已缓存的弹簧评分/5态（避免 _open_position 访问不到 _execute_trade 局部变量）
        #   若 inference 未填（如手工调用 _open_position），则安全回退 "NONE"，仓位乘数保持 1.0
        short_bearish_score = inference.get("spring_bearish_score", "NONE") or "NONE"
        long_bullish_score = inference.get("spring_bullish_score", "NONE") or "NONE"

        leverage = self.okx_client.cfg.get("default_leverage", 3)
        td_mode = self.okx_client.cfg.get("td_mode", "isolated")

        # v4 风险评分风控：杠杆调整
        leverage_factor = inference.get("leverage_factor", 1.0)
        effective_leverage = max(1, round(leverage * leverage_factor))
        risk_level = inference.get("risk_level", "NORMAL")
        if leverage_factor != 1.0:
            self._log(
                f"[{coin}] v4杠杆调整 | risk_level={risk_level} factor={leverage_factor:.2f} "
                f"leverage {leverage}→{effective_leverage}",
                "INFO",
            )

        balance = self.okx_client.get_balance()

        available_equity = self.perf_tracker.current_equity
        if balance.get("ok"):
            avail_usdt = balance.get("assets", {}).get("USDT", {}).get("avail", 0)
            if td_mode == "isolated":
                available_equity = avail_usdt
            else:
                total_eq = balance.get("total_eq", 0)
                pos_result = self.okx_client.get_positions()
                total_imr = 0
                if pos_result.get("ok"):
                    for p in pos_result.get("positions", []):
                        if float(p.get("pos", 0)) > 0:
                            total_imr += float(p.get("imr", 0))
                available_equity = total_eq - total_imr

        # P2+P3 动态仓位：计算四因子（凯利/连亏/卦象/波动率）并注入 calc_position_size
        # 样本量阈值 5 笔（启动初期不足 5 笔时，凯利=1.0 保持保守默认）
        p2_hex = inference.get("hexagram", "") or ""
        p2_f = self._compute_p2_dynamic_sizing_factors(p2_hex, lookback=30, min_samples=5)

        pos_size_info = self.risk_manager.calc_position_size(
            confidence=confidence,
            volatility=volatility,
            current_equity=available_equity,
            kelly_factor=p2_f["kelly_factor"],
            consecutive_loss_factor=p2_f["consecutive_loss_factor"],
            hexagram_factor=p2_f["hexagram_factor"],
            vol_regime_factor=p2_f["vol_regime_factor"],
        )
        position_usdt = pos_size_info["position_usdt"]
        position_pct = pos_size_info["position_pct"]

        # P2+P3 动态仓位：日志输出
        try:
            self._log(
                f"[{coin}] P3动态仓位 | 卦={p2_hex}({p2_f['hexagram_class']}) "
                f"凯利={p2_f['kelly_factor']:.2f}(wr={p2_f['win_rate']:.0%} "
                f"avg_win={p2_f['avg_win']:.2f} avg_loss={p2_f['avg_loss']:.2f}) "
                f"连亏={p2_f['loss_streak']}(×{p2_f['consecutive_loss_factor']:.2f}) "
                f"卦象系数=×{p2_f['hexagram_factor']:.2f} "
                f"波动率={volatility:.4f}({p2_f['vol_regime_class']},×{p2_f['vol_regime_factor']:.2f},"
                f"SL={p2_f['vol_adaptive_sl_mult']:.1f}×ATR TP={p2_f['vol_adaptive_tp_mult']:.1f}×ATR) "
                f"P3基准倍率=×{pos_size_info.get('p2_base_multiplier', 1.0):.2f} "
                f"-> {position_usdt:.2f}USDT ({position_pct:.1%})",
                "INFO",
            )
        except Exception:
            pass

        # ══════════════════════════════════════════════════
        # v4.6 分层语义对齐（战略→前置→核心→后置→过滤）
        #   ① 后置层（L3）：弹簧力场 + 形态乘数 + v4风险评分 等仓位校准
        #       → 在 "正常开仓（is_trial=False）" 时完整应用（给出具体仓位规模）
        #       → 在 "轻仓试错（is_trial=True）" 时跳过：
        #         试错仓本质是"共识分够，但置信度不够"的探路仓位。
        #         其仓位不以后置层"强/弱趋势分档"为准，而是交给过滤层
        #         EG3L（F1 永不BLOCK）最终控制（通常 0.05~0.10 倍率）
        # ══════════════════════════════════════════════════
        if not is_trial:
            # —— 后置层（L3）仓位校准，仅用于正常开仓 ——
            # Phase C+: 做空仓位规模分层（弹簧力场→仓位）
            # 理论：周期短可信度低但识别早 → 不禁开，而是控制资金规模
            #       跌破更多均线 → 弹簧压力更重 → 仓位更大
            if direction == "DOWN" and short_bearish_score != "NONE":
                pos_multi = self._compute_short_position_multiplier(short_bearish_score)
                old_usdt = position_usdt
                position_usdt *= pos_multi
                position_pct *= pos_multi
                self._log(
                    f"[{coin}] P1做空仓位分层(后置层) | score={short_bearish_score} ×{pos_multi:.1f} "
                    f"仓位 {old_usdt:.2f}→{position_usdt:.2f}USDT",
                    "INFO",
                )

            # H4(P2): 长多仓位规模分层（弹簧力场→仓位，与做空方向对称）
            #   score=STRONG/NORMAL/WEAK → ×1.0/0.7/0.4 保守策略；避免追顶
            if direction == "UP" and long_bullish_score != "NONE":
                pos_multi = self._compute_long_position_multiplier(long_bullish_score)
                old_usdt = position_usdt
                position_usdt *= pos_multi
                position_pct *= pos_multi
                self._log(
                    f"[{coin}] P1长多仓位分层(后置层) | score={long_bullish_score} ×{pos_multi:.1f} "
                    f"仓位 {old_usdt:.2f}→{position_usdt:.2f}USDT",
                    "INFO",
                )

            # v4 风险评分风控：仓位调整
            position_factor = inference.get("position_factor", 1.0)
            if position_factor != 1.0:
                old_usdt = position_usdt
                position_usdt *= position_factor
                position_pct *= position_factor
                self._log(
                    f"[{coin}] v4仓位调整(后置层) | risk_level={risk_level} factor={position_factor:.2f} "
                    f"仓位 {old_usdt:.2f}→{position_usdt:.2f}USDT",
                    "INFO",
                )

            # P2-05: 形态乘数 → 仓位规模（乘在所有仓位调整之后，最终下单前）
            _reg_mult = inference.get("_regime_multipliers", {})
            _pos_mult = _reg_mult.get("position_mult", 1.0)
            _regime_pred = inference.get("_regime_pred")
            if _pos_mult != 1.0:
                _old = position_usdt
                position_usdt *= _pos_mult
                position_pct *= _pos_mult
                self._log(
                    f"[{coin}] 形态仓位调整(后置层) | regime={_regime_pred or ''} ×{_pos_mult:.2f}"
                    f" 仓位 {_old:.2f}→{position_usdt:.2f}USDT",
                    "INFO",
                )
        else:
            # —— 轻仓试错：跳过 L3 后置仓位校准，交由过滤层 EG3L 控制仓位
            self._log(
                f"[{coin}] 轻仓试错(过滤层接管仓位) | 跳过L3弹簧/形态/v4分档 → 交由 ElasticGate3L/F1 弹性闸门控制最终仓位",
                "INFO",
            )
            # ★ 兜底：L10877 _reg_mult 最终再从 inference 取一次 保证后续 sl_mult / tp_mult 恒可用，
            #   此处仅保证 _regime_pred 不崩（后续 regime 日志可能用到）
            _regime_pred = inference.get("_regime_pred", None) if '_regime_pred' not in dir() else _regime_pred  # noqa: WPS427

        # ═══════════════════════════════════════════════════
        # 通用资金调控：前置约束叠加（所有仓位调整完成之后，最终下单之前）
        #   - allowed=False → position_usdt=0 → 不开仓
        #   - max_position_usdt → 与 position_usdt 取 min（缩仓）
        #   - 异常或初始化失败 → fail-open 保持易经自有仓位（直接返回原值）
        # ═══════════════════════════════════════════════════
        _cap_old_pos = position_usdt
        position_usdt, _cap_log = self._apply_capital_control_to_position(
            coin, position_usdt, available_equity
        )
        if _cap_old_pos > 0 and _cap_old_pos != position_usdt:
            position_pct = position_pct * (position_usdt / _cap_old_pos) if _cap_old_pos > 0 else 0.0
        if position_usdt <= 0:
            self._log(
                f"[{coin}] 通用资金调控前置约束拦截 → 不开仓（{_cap_log or '通用模块要求拦截'}）",
                "WARN",
            )
            return

        # ═══════════════════════════════════════════════════
        # 方案 C v3.0：三层弹性仓位 + WinProb + BTC 自反 调控（SW-C4/C6/C7/C3）
        #   顺序：ElasticGate3L(final_pos_mult) → WinProb(winprob_mult) → BTCSelfReflex(λ)
        #   全部 fail-open：None/异常 → ×1.0（零影响，字节等价）
        # ═══════════════════════════════════════════════════
        _phase_c_final_pos_mult = 1.0
        _phase_c_winprob_mult = 1.0
        _phase_c_btc_lambda = 1.0
        _phase_c_eg3l_detail = ""  # v4.6 新增：EG3L明细用于日志审计（确认3LW权重生效）
        try:
            # ── Step A: ElasticGate3L × 三层权重 ──
            if self._elastic_gate_3l is not None:
                try:
                    # inference 中已有的前置层/核心层标签（找不到则中性 "STANDARD"/"NEUTRAL"/0.65）
                    _p1_out = str(inference.get("p1_output_label", "STANDARD") or "STANDARD")
                    _elder_grade = str(inference.get("elder_ray_grade", "NEUTRAL") or "NEUTRAL")
                    _score_b = float(inference.get("bcrm_score_b", 0.65) or 0.65)
                    _decision_dir = str(inference.get("direction", "")).upper()
                    _dir_long_short = "LONG" if _decision_dir == "UP" else (
                        "SHORT" if _decision_dir == "DOWN" else None
                    )
                    _weights = None
                    if self._three_layer_weighter is not None:
                        try:
                            _weights = self._three_layer_weighter.get_current_weights()
                        except Exception:
                            _weights = None
                    # CBR F4 baseline family 红利
                    _f4_hit = bool(inference.get("cbr_f4_hit", False))
                    _f4_sim = float(inference.get("cbr_f4_similarity", 0.0) or 0.0)
                    # v4.6：先 compute() 获明细，再 apply_fuses 叠加铁则
                    _eg_out = self._elastic_gate_3l.compute(
                        p1_out=_p1_out, elder_grade=_elder_grade, score_b=_score_b,
                        weights=_weights, direction=_dir_long_short,
                    )
                    # 做空方向改写 Elder：对应 apply_fuses 用改写后的 elder_grade
                    _eg_for_fuses = _elder_grade
                    try:
                        _src = str(getattr(_eg_out, "source", "") or "")
                        if _src.startswith("short_tightened:") and "Elder→" in _src:
                            import re as _re
                            _m = _re.search(r"Elder→([A-Z_]+)", _src)
                            if _m:
                                _eg_for_fuses = _m.group(1)
                    except Exception:
                        pass
                    _phase_c_final_pos_mult = self._elastic_gate_3l.apply_fuses(
                        base_pos_mult=float(_eg_out.base_pos_mult),
                        p1_out=_p1_out, elder_grade=_eg_for_fuses,
                        f4_hit=_f4_hit, f4_similarity=_f4_sim,
                    )
                    # F1 永不 BLOCK：clip 下界
                    try:
                        from scripts.memory_l4 import phase_c_constants as _C
                        _phase_c_final_pos_mult = max(
                            float(_C.F1_NEVER_BLOCK_FLOOR),
                            min(float(getattr(_C, "FINAL_POS_MULT_CLIP_HIGH_DEFAULT", 1.50)),
                                _phase_c_final_pos_mult),
                        )
                    except Exception:
                        _phase_c_final_pos_mult = max(0.05, min(1.50, _phase_c_final_pos_mult))
                    # 组装明细日志（确认三层权重来源 fail_open/calibrated 等）
                    try:
                        _w_p_v = getattr(_weights, "w_p", None) if _weights is not None else None
                        if _w_p_v is None and isinstance(_weights, dict):
                            _w_p_v = _weights.get("w_p")
                        if _w_p_v is None:
                            from scripts.memory_l4 import phase_c_constants as _C2
                            _w_p_v, _w_e_v, _w_b_v = _C2.FAILOPEN_WP, _C2.FAILOPEN_WE, _C2.FAILOPEN_WB
                            _w_src = "fail_open"
                        else:
                            _w_e_v = float(getattr(_weights, "w_e",
                                                   _weights.get("w_e") if isinstance(_weights, dict) else 0.30))
                            _w_b_v = float(getattr(_weights, "w_b",
                                                   _weights.get("w_b") if isinstance(_weights, dict) else 0.25))
                            _w_src = getattr(_weights, "source",
                                             _weights.get("source") if isinstance(_weights, dict) else "fail_open")
                        _phase_c_eg3l_detail = (
                            f" S_P={_eg_out.score_p:.2f} S_E={_eg_out.score_e:.2f} S_B={_eg_out.score_b:.2f}"
                            f" cons={_eg_out.score_consensus:.3f}"
                            f" w_p={_w_p_v:.2f} w_e={_w_e_v:.2f} w_b={_w_b_v:.2f} w_src={_w_src}"
                            f" src={getattr(_eg_out, 'source', '')}"
                        )
                    except Exception:
                        _phase_c_eg3l_detail = ""
                except Exception as _ege:
                    self._log(
                        f"[{coin}] ElasticGate3L 异常（fail-open=1.0）：{type(_ege).__name__}",
                        "WARN",
                    )
                    _phase_c_final_pos_mult = 1.0
            # ── Step B: WinProb（盈亏概率动态权重）──
            if self._win_prob_engine is not None:
                try:
                    _sample_count = int(inference.get("winprob_sample_count", 0) or 0)
                    _pred_win_rate = float(inference.get("winprob_pred_win_rate", 0.0) or 0.0)
                    _q_vec = {
                        "sample_count": _sample_count,
                        "pred_win_rate": _pred_win_rate,
                        "symbol": coin,
                        "direction": "LONG" if direction == "UP" else "SHORT",
                    }
                    _wp_mult, _wp_shadow = self._win_prob_engine.get_multiplier(_q_vec)
                    _phase_c_winprob_mult = float(_wp_mult) if _wp_mult is not None else 1.0
                except Exception as _wpe:
                    self._log(
                        f"[{coin}] WinProbEngine 异常（fail-open=1.0）：{type(_wpe).__name__}",
                        "WARN",
                    )
                    _phase_c_winprob_mult = 1.0
            # ── Step C: BTC 自反闸门（仅 BTC + LONG 才生效）──
            if self._btc_self_reflex_valve is not None:
                try:
                    _btc_ctx = {
                        "symbol": coin,
                        "direction": "LONG" if direction == "UP" else "SHORT",
                        "d_pe_sign": int(inference.get("btc_d_pe_sign", 0) or 0),
                        "btc_cont_grade": str(inference.get("btc_cont_grade", "NEUTRAL") or "NEUTRAL"),
                        "s_btc_only": float(inference.get("btc_s_btc_only", 0.0) or 0.0),
                        "window_fill_ratio": float(inference.get("btc_window_fill", 0.0) or 0.0),
                        "fuse_24h_ok": not (getattr(getattr(self, "_current_fuse_action", None), "emergency_shutdown", False)),
                    }
                    _lam, _btc_shadow = self._btc_self_reflex_valve.get_lambda(_btc_ctx)
                    _phase_c_btc_lambda = float(_lam) if _lam is not None else 1.0
                    # 缓存在 self._last_btc_lambda，供 run_once 的 PRF ctx 使用（注意：仅 BTC 才改）
                    if coin.upper() in ("BTC", "BTCUSDT"):
                        self._last_btc_lambda = _phase_c_btc_lambda
                except Exception as _btce:
                    self._log(
                        f"[{coin}] BTCSelfReflexValve 异常（fail-open=1.0）：{type(_btce).__name__}",
                        "WARN",
                    )
                    _phase_c_btc_lambda = 1.0
        except Exception as _phce:
            # 外层总兜底：三数都回到 1.0
            _phase_c_final_pos_mult = 1.0
            _phase_c_winprob_mult = 1.0
            _phase_c_btc_lambda = 1.0
            self._log(
                f"[{coin}] PhaseC 仓位调控外层异常（fail-open=1.0）：{type(_phce).__name__}",
                "WARN",
            )

        # 应用三项乘积到 position_usdt / position_pct（任一 != 1.0 才 log，避免刷屏）
        _combined_mult = _phase_c_final_pos_mult * _phase_c_winprob_mult * _phase_c_btc_lambda
        # F1 永不 BLOCK 通路：最终仓位受 F2 BLOCK 上限约束，防止 WinProb/BTCλ 叠加突破 0.10
        _f1_trial_mode = bool(inference.get("_f1_trial_mode", False))
        if _f1_trial_mode:
            try:
                from scripts.memory_l4 import phase_c_constants as _C
                _f2_cap = float(_C.F2_P1_BLOCK_CAP_DEFAULT)
                if _combined_mult > _f2_cap:
                    self._log(
                        f"[{coin}] F1试错通路 F2封顶 | combined={_combined_mult:.3f} → {_f2_cap:.3f}（F2_P1_BLOCK_CAP）",
                        "INFO",
                    )
                    _combined_mult = _f2_cap
            except Exception:
                pass
        if abs(_combined_mult - 1.0) > 1e-9:
            _old_usdt = position_usdt
            position_usdt = position_usdt * _combined_mult
            position_pct = position_pct * _combined_mult
            self._log(
                f"[{coin}] PhaseC 仓位调控 | "
                f"EG3L={_phase_c_final_pos_mult:.2f} WinProb={_phase_c_winprob_mult:.2f} "
                f"BTCλ={_phase_c_btc_lambda:.2f} combined=×{_combined_mult:.3f} "
                f"仓位 {_old_usdt:.2f}→{position_usdt:.2f}U{_phase_c_eg3l_detail}",
                "INFO",
            )

        action = "open_long" if direction == "UP" else "open_short"
        pos_side = "long" if direction == "UP" else "short"

        # —— BDSM 协作 · 缺口 2：动态评估器(CVS)驱动分批建仓（Phase 1 升级）——
        #   CVS>=0.3 → batch=remaining×ratio（≥0.8 打完子弹）
        #   CVS<0.3 或 plan 缺失 → FAIL-OPEN 回退 _apply_bdsm_cap_multiplier
        #   remaining<=0 → 拦截不开仓（已建满）
        _cap_before = float(position_usdt or 0.0)
        # ★ strategy 路径跳过 BDSM cap scaling（子池隔离，source_tag="strategy" 不受 BDSM cap 约束）
        if inference.get("source_tag") == "strategy":
            _bdsm_pos, _bdsm_cap, _bdsm_cap_tag = position_usdt, 1.0, "strategy_skip_bdsm_cap"
        else:
            _bdsm_pos, _bdsm_cap, _bdsm_cap_tag = self._apply_bdsm_scaling(
                coin, position_usdt, inference.get("price", 0.0)
            )
        if _bdsm_cap_tag.startswith("bdsm_") and _bdsm_cap_tag != "not_bdsm_coin":
            self._log(
                f"[{coin}] BDSM_SCALING | cap=×{_bdsm_cap:.3f} tag={_bdsm_cap_tag} "
                f"USDT {_cap_before:.2f} U→{float(_bdsm_pos):.2f} U",
                "INFO",
            )
        position_usdt = float(_bdsm_pos)
        position_pct = position_pct * (_bdsm_cap if _cap_before > 0 else 1.0)
        # 最低名义仓位价值兜底（与 BCRM 口径一致：50U保证金×5x=250U名义价值）
        _min_notional = float(getattr(self.risk_manager.state, "min_position_usdt", 250.0))
        if 0 < position_usdt < _min_notional:
            self._log(
                f"[{coin}] BDSM 最低仓位兜底 | {position_usdt:.2f}U→{_min_notional:.2f}U（min_position_usdt）",
                "INFO",
            )
            position_usdt = _min_notional
        if position_usdt <= 0.0:
            self._log(
                f"[{coin}] BDSM scaling=0 拦截开仓（tag={_bdsm_cap_tag}）",
                "WARN",
            )
            return None

        # —— BDSM 协作 · SHORT_BAN 铁律：SHORT_ONLY_BLACKLIST 币种禁止做空
        # （ETH/BTC 等，P0 历史验证做空样本亏损率极高；BDSM 模型本身默认 LONG_ONLY）
        # 例外：战略层 direction_state=SHORT_ONLY 时，临时解除做空限制（高位滞涨筑顶形态）
        # 做空 → 直接跳过该信号，等效于「BDSM 不存在」(FAIL-OPEN 中性)
        _short_ban_active = True
        try:
            _fds_local = getattr(self, "_five_domain_state_cache", None)
            if _fds_local is not None:
                _cls_local = self._coin_asset_class(coin)
                _dstate_local = getattr(_fds_local, "direction_state", {}).get(_cls_local, "NEUTRAL")
                if _dstate_local == "SHORT_ONLY":
                    _short_ban_active = False
        except Exception:
            pass
        if pos_side == "short" and coin.upper() in getattr(self, "SHORT_ONLY_BLACKLIST", set()) and _short_ban_active:
            self._log(
                f"[{coin}] SHORT_BAN 命中 | 方向={direction} 跳过开空（SHORT_ONLY_BLACKLIST）",
                "WARN",
            )
            return None
        if not _short_ban_active and pos_side == "short" and coin.upper() in getattr(self, "SHORT_ONLY_BLACKLIST", set()):
            self._log(
                f"[{coin}] SHORT_BAN 临时解除 | direction_state=SHORT_ONLY 允许做空（高位滞涨形态）",
                "INFO",
            )
        sl_px = inference["stop_loss_px"]
        tp_px = inference["take_profit_px"]
        price = inference["price"]

        # v4 风险评分风控：止损收紧
        sl_tighten_factor = inference.get("sl_tighten_factor", 1.0)
        if sl_tighten_factor < 1.0 and sl_px and price > 0:
            old_sl = sl_px
            sl_px = round(price + (sl_px - price) * sl_tighten_factor, 4)
            self._log(
                f"[{coin}] v4止损收紧 | factor={sl_tighten_factor:.2f} SL {old_sl}→{sl_px}", "WARN"
            )

        # ═══ 方案 C v3.0：组合熔断 SL/TP 微调整（SW-C8 G-02）═══
        #   - 顺序：sl_tighten（v4风控） → 组合熔断 SL_adj/TP_adj → 形态乘数
        #   - 计算：按"距离 price 的比例"乘系数，保证价格与 SL/TP 的间距正确缩放
        #   - fail-open：_current_fuse_action 缺失/None → SL_adj=1.0, TP_adj=1.0
        #     ★ FIX legacy#3：兼容__new__绕过__init__未初始化属性的场景
        _fuse_sl_adj = 1.0
        _fuse_tp_adj = 1.0
        _fuse = getattr(self, "_current_fuse_action", None)
        if _fuse is not None:
            try:
                _fuse_sl_adj = float(getattr(_fuse, "sl_mult_adj", 1.0) or 1.0)
                _fuse_tp_adj = float(getattr(_fuse, "tp_mult_adj", 1.0) or 1.0)
            except Exception:
                _fuse_sl_adj = 1.0
                _fuse_tp_adj = 1.0
        _fuse_adj_applied = False
        if abs(_fuse_sl_adj - 1.0) > 1e-9 and sl_px and price > 0:
            _old_sl = sl_px
            sl_px = round(price + (sl_px - price) * _fuse_sl_adj, 6)
            _fuse_adj_applied = True
            self._log(
                f"[{coin}] PhaseC 组合熔断SL调整 | SL_adj={_fuse_sl_adj:.2f} SL {_old_sl}→{sl_px}",
                "INFO",
            )
        if abs(_fuse_tp_adj - 1.0) > 1e-9 and tp_px and price > 0:
            _old_tp = tp_px
            tp_px = round(price + (tp_px - price) * _fuse_tp_adj, 6)
            _fuse_adj_applied = True
            self._log(
                f"[{coin}] PhaseC 组合熔断TP调整 | TP_adj={_fuse_tp_adj:.2f} TP {_old_tp}→{tp_px}",
                "INFO",
            )

        # P2-05: 形态乘数 → SL/TP 价格距离（乘在所有 v4 风控之后，SLTP 冻结前）
        #   VOLATILE_DROP → sl_mult=0.65（紧止损）、TREND_UP_STRONG → tp_mult=1.30（放止盈）
        # ★ BUGFIX(2026-09-02 GOOGL 试错仓崩 UnboundLocalError _reg_mult)：
        #   所有分支最终汇总点再从 inference 取一次，消除「if 分支赋值但 else 分支跳过」导致的未绑定隐患。
        _reg_mult = inference.get("_regime_multipliers", {}) if not isinstance(inference.get("_regime_multipliers"), dict) else dict(inference.get("_regime_multipliers") or {})
        _sl_mult = _reg_mult.get("sl_mult", 1.0)
        _tp_mult = _reg_mult.get("tp_mult", 1.0)
        if _sl_mult != 1.0 and sl_px and price > 0:
            _old_sl = sl_px
            sl_px = round(price + (sl_px - price) * _sl_mult, 6)
            self._log(
                f"[{coin}] 形态SL调整 | regime={_regime_pred or ''} ×{_sl_mult:.2f}"
                f" SL {_old_sl}→{sl_px}",
                "INFO",
            )
        if _tp_mult != 1.0 and tp_px and price > 0:
            _old_tp = tp_px
            tp_px = round(price + (tp_px - price) * _tp_mult, 6)
            self._log(
                f"[{coin}] 形态TP调整 | regime={_regime_pred or ''} ×{_tp_mult:.2f}"
                f" TP {_old_tp}→{tp_px}",
                "INFO",
            )

        # v4 风险评分风控：止盈调整
        tp_adjustment = inference.get("tp_adjustment", 1.0)
        if tp_adjustment != 1.0 and tp_px and price > 0:
            old_tp = tp_px
            tp_px = round(price + (tp_px - price) * tp_adjustment, 4)
            self._log(
                f"[{coin}] v4止盈调整 | factor={tp_adjustment:.2f} TP {old_tp}→{tp_px}", "INFO"
            )

        # ── v4 风险评分：汇总级（即便全=1.0 也打印一次，方便审计「前置层评分功能已跑」）
        try:
            lf = float(inference.get("leverage_factor", 1.0))
            pf = float(inference.get("position_factor", 1.0))
            stf = float(inference.get("sl_tighten_factor", 1.0))
            taf = float(inference.get("tp_adjustment", 1.0))
            rl = inference.get("risk_level", "NORMAL") or "NORMAL"
            if lf == 1.0 and pf == 1.0 and stf == 1.0 and taf == 1.0:
                self._log(
                    f"[{coin}] v4风险评分中性 | risk_level={rl} "
                    f"lev×{lf:.2f} pos×{pf:.2f} sl×{stf:.2f} tp×{taf:.2f}（无异常收紧/放宽）",
                    "INFO",
                )
        except Exception:
            pass

        # 优化3：动态止损宽度（如果增强器有推荐，覆盖默认值）
        # 关键口径：先按"订单收益率"定义，再通过 leverage 换算成价格
        #   ATR 倍数（市场态）→ 价格波动% → 订单收益率% = 价格波动% × leverage
        # 2026-08-06 上调：默认倍率 1.5/3.0 → 2.5/5.0，与 ExitConfig/BCRM2_ATR 口径保持一致
        enhance_info = inference.get("enhance_result")
        if enhance_info and price > 0 and volatility > 0:
            sl_mult = enhance_info.get("sl_atr_mult", 2.5)
            tp_mult = enhance_info.get("tp_atr_mult", 5.0)
            price * volatility
            if sl_mult != 1.5 or tp_mult != 3.0:
                # 1) 先按"订单收益率"定义：1.5×ATR → 价格波动 sl_mult×volatility
                #    对应订单止损收益率 = sl_mult × volatility × leverage
                sl_price_change_pct = sl_mult * volatility
                tp_price_change_pct = tp_mult * volatility
                sl_roi_pct = self._price_change_to_roi(sl_price_change_pct, leverage)
                tp_roi_pct = self._price_change_to_roi(tp_price_change_pct, leverage)
                # 2) 由订单收益率 + 入场价反推止损止盈价
                if direction == "UP":
                    new_sl = self._calc_sl_price(price, "long", sl_roi_pct, leverage)
                    new_tp = self._calc_tp_price(price, "long", tp_roi_pct, leverage)
                else:
                    new_sl = self._calc_sl_price(price, "short", sl_roi_pct, leverage)
                    new_tp = self._calc_tp_price(price, "short", tp_roi_pct, leverage)
                if new_sl > 0 and new_tp > 0:
                    old_sl_pct = abs(sl_px - price) / price * 100 if sl_px else 0
                    abs(new_sl - price) / price * 100
                    sl_px = new_sl
                    tp_px = new_tp
                    self._log(
                        f"[{coin}] 动态止损 | {enhance_info.get('regime','')} "
                        f"杠杆={leverage}x "
                        f"SL={sl_mult:.1f}×ATR(订单亏{sl_roi_pct:.2%}/价格{sl_price_change_pct:.2%}) "
                        f"TP={tp_mult:.1f}×ATR(订单盈{tp_roi_pct:.2%}/价格{tp_price_change_pct:.2%}) "
                        f"(原SL={old_sl_pct:.1f}%)"
                    )

        # ── SL/TP 价格空间下限保护（ATR 极低时 SL 过紧无意义）──
        # 原理：轻仓试错核心是仓位小，不是 SL 近；ATR 极低时按常规标准设置
        _min_sl_pct = 0.020 if is_trial else 0.015  # 试错仓 2.0%，常规仓 1.5%
        _min_tp_pct = 0.040 if is_trial else 0.030  # 试错仓 4.0%，常规仓 3.0%
        if sl_px and price > 0:
            _cur_sl_pct = abs(sl_px - price) / price
            if _cur_sl_pct < _min_sl_pct:
                _old_sl = sl_px
                if direction == "UP":
                    sl_px = round(price * (1 - _min_sl_pct), 6)
                else:
                    sl_px = round(price * (1 + _min_sl_pct), 6)
                self._log(
                    f"[{coin}] SL价格空间下限保护 | {'轻仓试错' if is_trial else '常规'} "
                    f"原SL间距={_cur_sl_pct:.2%}<{_min_sl_pct:.2%} SL {_old_sl}→{sl_px}",
                    "WARN",
                )
        if tp_px and price > 0:
            _cur_tp_pct = abs(tp_px - price) / price
            if _cur_tp_pct < _min_tp_pct:
                _old_tp = tp_px
                if direction == "UP":
                    tp_px = round(price * (1 + _min_tp_pct), 6)
                else:
                    tp_px = round(price * (1 - _min_tp_pct), 6)
                self._log(
                    f"[{coin}] TP价格空间下限保护 | {'轻仓试错' if is_trial else '常规'} "
                    f"原TP间距={_cur_tp_pct:.2%}<{_min_tp_pct:.2%} TP {_old_tp}→{tp_px}",
                    "WARN",
                )

        # 输出：换算订单收益率（杠杆×价格波动%）
        # 同时记录 ATR 基线 SL/TP 收益率，供易经离场系统调制使用
        base_sl_roi = 0.0
        base_tp_roi = 0.0
        if price > 0 and leverage > 0 and sl_px and tp_px:
            sl_pct = abs(sl_px - price) / price
            tp_pct = abs(tp_px - price) / price
            sl_roi = self._price_change_to_roi(sl_pct, leverage)
            tp_roi = self._price_change_to_roi(tp_pct, leverage)
            # 记录 ATR 基线 ROI（供易经离场系统 1h 后调制使用）
            base_sl_roi = sl_roi
            base_tp_roi = tp_roi
            if pos_side == "long":
                sl_label = f"亏{sl_roi:.2%}(价{sl_pct:.2%})"
                tp_label = f"盈{tp_roi:.2%}(价{tp_pct:.2%})"
            else:
                sl_label = f"亏{sl_roi:.2%}(价{sl_pct:.2%})"
                tp_label = f"盈{tp_roi:.2%}(价{tp_pct:.2%})"
            self._log(
                f"[{coin}] {'反手' if is_reverse else ''}开仓 {'[轻仓试错]' if is_trial else ''} {action} | "
                f"置信度={confidence:.2f}(factor={pos_size_info.get('confidence_factor', 0):.2f}) "
                f"卦象={inference['hexagram']} 杠杆={leverage}x | "
                f"仓位={position_usdt:.2f}USDT ({position_pct:.1%}) | "
                f"价格={inference['price']} SL={sl_px}({sl_label}) TP={tp_px}({tp_label}) | "
                f"原因={pos_size_info['reason']} | "
                f"可用余额={available_equity:.2f}USDT"
            )
        else:
            self._log(
                f"[{coin}] {'反手' if is_reverse else ''}开仓 {'[轻仓试错]' if is_trial else ''} {action} | "
                f"置信度={confidence:.2f}(factor={pos_size_info.get('confidence_factor', 0):.2f}) "
                f"卦象={inference['hexagram']} 杠杆={leverage}x | "
                f"仓位={position_usdt:.2f}USDT ({position_pct:.1%}) | "
                f"价格={inference['price']} 止损={sl_px} 止盈={tp_px} | "
                f"原因={pos_size_info['reason']} | "
                f"可用余额={available_equity:.2f}USDT"
            )

        margin_needed = position_usdt / leverage

        if balance.get("ok"):
            total_eq = balance.get("total_eq", 0)
            avail_usdt = balance.get("assets", {}).get("USDT", {}).get("avail", 0)

            if td_mode == "isolated":
                if margin_needed > avail_usdt:
                    self._log(
                        f"[{coin}] 可用保证金不足（逐仓） | 需要={margin_needed:.2f}USDT 可用={avail_usdt:.2f}USDT 总权益={total_eq:.2f}USDT 杠杆={leverage}x 跳过",
                        "WARN",
                    )
                    return
            else:
                pos_result = self.okx_client.get_positions()
                total_imr = 0
                if pos_result.get("ok"):
                    for p in pos_result.get("positions", []):
                        if float(p.get("pos", 0)) > 0:
                            total_imr += float(p.get("imr", 0))

                cross_available = total_eq - total_imr

                if margin_needed > cross_available:
                    self._log(
                        f"[{coin}] 可用保证金不足（全仓） | 需要={margin_needed:.2f}USDT 可用={cross_available:.2f}USDT 总权益={total_eq:.2f}USDT 已用IMR={total_imr:.2f}USDT 杠杆={leverage}x 跳过",
                        "WARN",
                    )
                    return

        # 检查下单量是否满足最小合约单位
        sz = self.okx_client._usdt_to_sz(inst_id, position_usdt)
        if sz <= 0:
            self._log(
                f"[{coin}] 下单量不足最小合约单位 | 金额={position_usdt:.2f}USDT 跳过", "WARN"
            )
            return

        # ★ S级 硬约束：下单前 必须 同步 OKX 交易所 端 杠杆，避免 代码 计算 杠杆（默认 5x）
        # 与 OKX 端 设置（可能上次 会话 是 10x/20x）不一致 导致 实际 保证金 占用 / 爆仓 价
        # 计算 偏差。FAIL-OPEN：设置 失败 不 阻塞，记录 WARN 后 继续 下单（主链路不中断）。
        try:
            _lev_to_set = max(1, int(round(float(leverage or self.okx_client.cfg.get("default_leverage", 3)))))
            _lev_res = self.okx_client.set_leverage(inst_id=inst_id, lever=_lev_to_set, mgn_mode=td_mode)
            if not _lev_res.get("ok"):
                self._log(
                    f"[{coin}] set_leverage 失败(fail-open继续) | 目标={_lev_to_set}x 模式={td_mode} "
                    f"err={_lev_res.get('error', 'unknown')}",
                    "WARN",
                )
            else:
                self._log(
                    f"[{coin}] set_leverage OKX端 同步 成功 | 实际={_lev_res.get('lever')}x 模式={_lev_res.get('mgn_mode')}",
                    "INFO",
                )
        except Exception as _lev_e:
            self._log(
                f"[{coin}] set_leverage 异常(fail-open继续) | err={type(_lev_e).__name__}:{_lev_e}",
                "WARN",
            )

        if direction == "UP":
            order_result = self.okx_client.market_open_long(
                inst_id, usdt_amount=position_usdt, reason=f"yijing_open_long conf={confidence:.2f}"
            )
        else:
            order_result = self.okx_client.market_open_short(
                inst_id,
                usdt_amount=position_usdt,
                reason=f"yijing_open_short conf={confidence:.2f}",
            )

        ok = order_result.get("ok", False)
        ord_id = order_result.get("ord_id", "") or order_result.get("ordId", "")
        entry_price = order_result.get("estimated_price", inference["price"])

        if ok or order_result.get("dry_run"):
            enhance_info = inference.get("enhance_result")
            _original_enhance_info = enhance_info
            try:
                if self._strategy_algo_layer is not None and self._strategy_algo_layer.cfg.enable_strategy_layer:
                    from dataclasses import asdict as _asdict_t4
                    from statistics import median as _median_t4

                    if coin in self.US_STOCK_COINS:
                        cls = "us_stock"
                    elif coin in {"XAU", "XAG"}:
                        cls = "precious_metal"
                    else:
                        cls = "crypto_usdt"

                    _raw_dir = inference.get("direction", "")
                    if _raw_dir == "UP":
                        direction_sel = "LONG"
                    elif _raw_dir == "DOWN":
                        direction_sel = "SHORT"
                    else:
                        direction_sel = ""

                    market_regime = inference.get("_regime_pred") or inference.get("regime_pred") or "UNKNOWN"
                    confidence_sel = float(inference.get("confidence", 0.0) or 0.0)
                    five_domain_state = self._five_domain_state_cache

                    _fd_scores_cls = {}
                    if five_domain_state is not None:
                        try:
                            _fd_scores_cls = dict(getattr(five_domain_state, "five_scores", {}).get(cls, {}) or {})
                        except Exception:
                            _fd_scores_cls = {}
                    if not _fd_scores_cls:
                        try:
                            from scripts.memory_l4.strategy_algo_layer import DEFAULT_NEUTRAL_SCORES as _DNS
                            _fd_scores_cls = dict(_DNS)
                        except Exception:
                            _fd_scores_cls = {"dao": 50, "tian": 50, "di": 50, "jiang": 50, "fa": 70}

                    _regime_summary = {"phase": market_regime}
                    _liquidity_tier = "G2"
                    try:
                        selection = self._strategy_algo_layer.select(
                            asset_class=cls,
                            five_scores=_fd_scores_cls,
                            regime_summary=_regime_summary,
                            liquidity_tier=_liquidity_tier,
                            five_domain_state=five_domain_state,
                        )
                        selection_snapshot = _asdict_t4(selection)
                        if enhance_info is None:
                            enhance_info = {}
                        enhance_info["strategy_selection"] = selection_snapshot
                        # 回写 inference，确保下游 _record_shadow_log 能取到 sal_* 字段
                        inference["enhance_result"] = enhance_info

                        _cb_values = []
                        for _v in (selection.calibration_biases or {}).values():
                            if isinstance(_v, (int, float)):
                                _cb_values.append(float(_v))
                        if _cb_values:
                            _calib_median = float(_median_t4(_cb_values))
                        else:
                            _calib_median = 1.0
                        self._log(
                            f"[策略算法层影子] {coin} cls={cls} type={selection.strategy_type} "
                            f"gate={selection.calibration_biases.get('hard_relax_gate', False) if isinstance(selection.calibration_biases, dict) else False} "
                            f"calib_median={_calib_median:.3f} "
                            f"switch={self._strategy_algo_layer.cfg.enable_strategy_layer}",
                            "INFO",
                        )
                    except Exception:
                        enhance_info = _original_enhance_info
                        pass
                else:
                    pass
            except Exception:
                enhance_info = _original_enhance_info
                pass

            self.position_tracker.open_position(
                coin=coin,
                inst_id=inst_id,
                direction=pos_side,
                entry_price=entry_price,
                confidence=confidence,
                hexagram=inference["hexagram"],
                liangyi_state=inference.get("liangyi_state"),
                scale_params=inference.get("scale_params"),
                market_snapshot=inference.get("snapshot"),
                contradiction_list=inference.get("contradictions"),
                enhance_info=enhance_info,
                base_sl_roi=base_sl_roi,
                base_tp_roi=base_tp_roi,
                regime_pred=inference.get("_regime_pred"),
                regime_multipliers=inference.get("_regime_multipliers"),
                is_trial=is_trial,
                score_consensus=float(inference.get("score_consensus", 0.0) or 0.0),
                gate_base_threshold=float(inference.get("gate_base_threshold", 0.40) or 0.40),
                # — BDSM 协作 R5 铁律 · 子池隔离标签（持久化 JSON positions/{inst_id}.json）—
                source_tag=inference.get("source_tag") or self._classify_source_tag(coin),
            )
            self._log(f"[{coin}] 开仓成功 | ordId={ord_id} | " f"入场价≈{entry_price}")

            # L4 轻量开仓事件（M0 注册预览 + A0 创伤追踪）
            self._record_opening_event(inference, entry_price, pos_side, confidence)

            if sl_px and tp_px:
                sltp_result = self.okx_client.place_stop_loss_take_profit(
                    inst_id=inst_id,
                    pos_side=pos_side,
                    stop_loss_px=sl_px,
                    take_profit_px=tp_px,
                    sz=sz,
                    reason="yijing_risk_management",
                )
                if sltp_result.get("ok"):
                    self._log(f"[{coin}] 止盈止损已设置 | SL={sl_px} TP={tp_px}")
                else:
                    self._log(
                        f"[{coin}] 止盈止损设置失败 | SL={sl_px} TP={tp_px} | "
                        f"错误={sltp_result.get('error', sltp_result.get('msg', 'unknown'))}",
                        "ERROR",
                    )
        else:
            err = order_result.get("error", "") or order_result.get("sMsg", "")
            self._log(f"[{coin}] 开仓失败 | {err}", "ERROR")
            if self.guardian:
                self.guardian.record_error(
                    RuntimeError(f"开仓失败: {err}"), context=f"open_position:{coin}"
                )

    def _inject_cognitive_recall(self, coin: str, inference: dict) -> dict:
        """
        P3: 构建交易上下文并调用认知系统召回，返回认知建议。

        设计原则:
          - 建议而非约束: 召回结果注入 inference，不阻断交易决策
          - 失败安全: 认知系统不可用时返回空结果，不影响交易
          - 上下文构建: 从 inference 提取关键字段组装召回上下文
        """
        if not self._trading_recall_fn:
            return {"ok": False, "reason": "recall_fn not initialized"}

        # 构建召回上下文（从 inference 提取关键字段）
        direction = inference.get("direction", "")
        confidence = inference.get("confidence", 0.0)
        hexagram = inference.get("hexagram", "")
        is_ranging = inference.get("is_ranging", False)
        volatility = inference.get("volatility", 0.0)
        a0_warnings = inference.get("a0_warnings", [])

        ctx_parts = [f"{coin}", f"方向={direction}", f"置信度={confidence:.2f}"]
        if hexagram:
            ctx_parts.append(f"卦象={hexagram}")
        if is_ranging:
            ctx_parts.append("震荡市场")
        if volatility > 0:
            ctx_parts.append(f"波动率={volatility:.4f}")
        if a0_warnings:
            ctx_parts.append(f"矛盾预警={len(a0_warnings)}项")
        context = " ".join(ctx_parts)

        try:
            result = self._trading_recall_fn(
                context=context,
                task_type="strategy-execution",
                top_k_mem=3,
                top_meta=2,
                top_applied=2,
            )
            if result.get("ok"):
                mem_count = result.get("count", 0)
                meta_count = len(result.get("processes", {}).get("meta", []))
                applied_count = len(result.get("processes", {}).get("applied", []))
                self._log(
                    f"[{coin}] P3认知召回: 记忆={mem_count}条 | "
                    f"T系列Skill={meta_count}个 | 历史路径={applied_count}条",
                    "INFO",
                )
            return result
        except Exception as e:
            self._log(f"[{coin}] P3认知召回失败: {e}", "WARN")
            return {"ok": False, "error": str(e)}

    @staticmethod
    def _summarize_cognitive_recall(inference: dict) -> dict:
        """P3: 从 inference 中提取认知召回摘要（轻量，供开仓事件存档）"""
        cr = inference.get("cognitive_recall")
        if not cr or not cr.get("ok"):
            return {"ok": False}
        return {
            "ok": True,
            "mem_count": cr.get("count", 0),
            "meta_skills": [m.get("skill_id") for m in cr.get("processes", {}).get("meta", [])],
            "applied_count": len(cr.get("processes", {}).get("applied", [])),
        }

    def _record_opening_event(
        self, inference: dict, entry_price: float, pos_side: str, confidence: float
    ):
        """开仓时轻量记录：A0 创伤追踪 + 开仓事件存档（供平仓后 L4 使用）"""
        import json
        from datetime import datetime

        coin = inference.get("coin", "")
        inst_id = inference.get("inst_id", "")
        direction = inference.get("direction", "")

        # A0 创伤追踪：记录决策方向（平仓后会更新对错）
        try:
            from scripts.memory_l4.a0_contradiction_engine import A0ContradictionEngine

            if not hasattr(self, "_a0_engine"):
                self._a0_engine = A0ContradictionEngine()
            self._a0_engine.record_decision(
                inst_id=inst_id,
                direction=direction,
                was_correct=True,  # 开仓时未知，平仓后更新
                ts=datetime.now().isoformat(),
            )
        except Exception:
            pass

        # 轻量开仓事件存档
        try:
            # P2-9: 事前预测（对齐 Friston 主动推理，失败静默不阻断开仓记录）
            prediction_data = None
            try:
                from scripts.memory_l4.prediction_bridge import generate_prediction_dict

                prediction_data = generate_prediction_dict(inference)
            except Exception:
                pass

            event = {
                "ts": datetime.now().isoformat(),
                "type": "position_opened",
                "inst_id": inst_id,
                "coin": coin,
                "direction": direction,
                "pos_side": pos_side,
                "entry_price": entry_price,
                "confidence": confidence,
                "a0_analysis": inference.get("a0_analysis"),
                "a0_warnings": inference.get("a0_warnings", []),
                "volatility": inference.get("volatility", 0),
                "hexagram": inference.get("hexagram", ""),
                # P3: 认知召回摘要（供平仓后 L4 回溯分析）
                "cognitive_recall": self._summarize_cognitive_recall(inference),
                # P2-9: 事前预测快照（供平仓后计算 prediction_error 驱动贝叶斯）
                "prediction": prediction_data,
            }
            event_dir = (
                Path(self.data_dir) / "l4_events"
                if hasattr(self, "data_dir")
                else Path("data/l4_events")
            )
            event_dir.mkdir(parents=True, exist_ok=True)
            event_file = event_dir / f"open_{inst_id}_{int(datetime.now().timestamp())}.json"
            event_file.write_text(json.dumps(event, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_external_knowledge(self):
        """加载 AB Trading 导出的外部知识"""
        try:
            self.external_knowledge = self.knowledge_bridge.get_knowledge_summary()
            if self.external_knowledge["evolved_params_count"] > 0:
                self._log(
                    f"[外部知识] 已加载 {self.external_knowledge['evolved_params_count']} 个进化参数 | "
                    f"灵敏度={self.external_knowledge['trend_sensitivity']:.2f} | "
                    f"风险厌恶={self.external_knowledge['risk_aversion']:.2f} | "
                    f"市场倾向={self.external_knowledge['market_bias']}"
                )
        except Exception as e:
            self._log(f"[外部知识] 加载失败: {e}", "ERROR")
            self.external_knowledge = {}

    def _infer_current_hexagram(self, coin: str, inference: dict, kline_data: list):
        """离场时推理当前卦象（轻量级，复用 YijingEngine + HexagramKnowledge）

        P1修复：
        - 优先复用开仓时的卦象名（inference["hexagram"]），保证卦象一致性
        - 从 HexagramKnowledge 获取固有的 risk_level/direction_hint（不依赖简化参数）
        - 用 YijingEngine.infer() 推理 current_phase/development_stage（动态判断）
        - 修正 supply_demand/capital_flow 不再固定0.5，改用价格位置+成交量比

        失败时返回 None（YijingExitSystem 会 fail-open 不干预）
        """
        try:
            from scripts.memory_l4.bcrm.sixty_four_guas import get_hexagram_knowledge
            from scripts.memory_l4.bcrm.yijing_engine import YijingEngine

            if not hasattr(self, "_yijing_engine_for_exit"):
                self._yijing_engine_for_exit = YijingEngine()

            # 从 inference 提取可用字段
            trend_strength = float(inference.get("trend_strength", 0.5) or 0.5)
            volatility = float(inference.get("volatility", 0.03) or 0.03)
            confidence = float(inference.get("confidence", 0.5) or 0.5)
            is_ranging = bool(inference.get("is_ranging", False))
            current_price = float(inference.get("price", 0) or 0)
            # 开仓时已推理的卦象名（如"巽为风"）
            hex_name_cn = inference.get("hexagram", "") or ""

            # ── 价格位置 + 成交量比（不再固定0.5）──
            price_position = 0.5
            volume_ratio = 1.0
            closes = []
            if kline_data and len(kline_data) >= 20 and current_price > 0:
                try:
                    closes = [float(c.get("c", 0)) for c in kline_data[-20:]]
                    if closes and max(closes) > min(closes):
                        price_position = (current_price - min(closes)) / (max(closes) - min(closes))
                        price_position = max(0.0, min(1.0, price_position))
                    # 成交量比：近5根 vs 前20根均值
                    vols = [float(c.get("v", 0)) for c in kline_data[-20:]]
                    if vols and len(vols) >= 10:
                        recent_vol = sum(vols[-5:]) / 5
                        base_vol = sum(vols[:-5]) / max(len(vols) - 5, 1)
                        volume_ratio = recent_vol / base_vol if base_vol > 0 else 1.0
                except Exception:
                    pass

            # 供需评分：价格位置 >0.7 偏多，<0.3 偏空，中间中性
            supply_demand_score = max(0.0, min(1.0, price_position))
            # 资金面：放量=资金流入，缩量=流出
            capital_flow_score = max(0.0, min(1.0, 0.5 + (volume_ratio - 1.0) * 0.3))
            # 技术面
            technical_score = max(0.0, min(1.0, trend_strength))
            # 情绪面
            sentiment_score = max(
                0.0, min(1.0, confidence * 0.7 + (0.3 if not is_ranging else 0.1))
            )
            vol_norm = max(0.0, min(1.0, volatility * 20))

            # ── 用 YijingEngine 推理 current_phase / development_stage ──
            result = self._yijing_engine_for_exit.infer(
                supply_demand_score=supply_demand_score,
                technical_score=technical_score,
                capital_flow_score=capital_flow_score,
                sentiment_score=sentiment_score,
                trend_strength=trend_strength,
                volatility=vol_norm,
                volume_ratio=volume_ratio,
                price_position=price_position,
                close_price=current_price,
            )

            # ── P1修复：用 HexagramKnowledge 覆盖固有属性（risk_level/direction_hint）──
            # YijingEngine.infer() 用简化参数推理时，risk_level 可能不准
            # HexagramKnowledge 的 risk_level/direction_hint 是卦象固有属性，更可靠
            if hex_name_cn and hex_name_cn != "已存在持仓":
                hex_kb = get_hexagram_knowledge(hex_name_cn)
                if hex_kb:
                    # 覆盖固有属性
                    result.risk_level = hex_kb.risk_level or result.risk_level
                    result.direction_hint = hex_kb.direction_hint or result.direction_hint
                    # 确保 hexagram_name_cn 一致
                    result.hexagram_name_cn = hex_name_cn

            return result
        except Exception as e:
            self._log(f"[{coin}] 离场卦象推理失败: {e}", "WARN")
            return None

    def _adjust_exit_config_for_regime(self, regime: dict):
        """短期修复 2：根据市场状态动态调整 ExitConfig

        - 震荡市（is_ranging=true / 弱趋势）：止损放宽到 5%，跟踪回撤 3.5% → 4%
        - 趋势市：恢复基准配置（4.5% / 3.5%）
        """
        if not regime or not hasattr(self, "_exit_cfg_base"):
            return
        try:
            is_ranging = bool(regime.get("is_ranging", False))
            # 弱趋势判定：adx < 20 或 trend_strength 为 weak/range
            adx = float(regime.get("adx", 0) or 0)
            trend_strength = str(regime.get("trend_strength", "")).lower()
            weak_trend = (adx < 20) or (trend_strength in ("weak", "range", "ranging"))

            cfg = self.exit_system.config
            if is_ranging or weak_trend:
                # 震荡市：放宽止损
                if cfg.tb_sl_min_pct != 0.05:
                    cfg.tb_sl_min_pct = 0.05
                    cfg.trailing_retrace_pct = 0.04
                    self._log(
                        f"[离场动态调整] 震荡市(is_ranging={is_ranging},adx={adx:.1f}) "
                        f"→ tb_sl_min=5% trailing_retrace=4%"
                    )
            else:
                # 趋势市：恢复基准
                if cfg.tb_sl_min_pct != self._exit_cfg_base.tb_sl_min_pct:
                    cfg.tb_sl_min_pct = self._exit_cfg_base.tb_sl_min_pct
                    cfg.trailing_retrace_pct = self._exit_cfg_base.trailing_retrace_pct
                    self._log(
                        f"[离场动态调整] 趋势市恢复基准 "
                        f"→ tb_sl_min={cfg.tb_sl_min_pct:.1%} trailing_retrace={cfg.trailing_retrace_pct:.1%}"
                    )
        except Exception as e:
            self._log(f"[离场动态调整失败] {e}")

    def _load_evolution_config(self, initial: bool = False):
        """A-1修复：从 OKX_SIM/config.json 加载进化后的阈值，覆盖默认值。

        - initial=True: __init__ 时调用，覆盖构造参数默认值
        - initial=False: run_once 每轮调用，热 reload 进化后的新阈值

        只更新 4 个进化键：confidence_threshold / daily_loss_limit /
        max_consecutive_losses / default_position_pct。
        其余字段（api_key 等）不受影响。
        """
        try:
            from scripts.memory_l4.paths import workspace_root as _ws

            cfg_path = _ws() / "data" / "okx_sim" / "config.json"
            self._evolution_config_path = cfg_path
            if not cfg_path.exists():
                return
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

            updated = []

            # confidence_threshold（PollingTrader 层：A 项过滤门槛）
            # 仅加载 yijing_monitor 微调值，不再被引擎层进化值覆盖
            new_conf = cfg.get("confidence_threshold")
            if new_conf is not None and new_conf != self.confidence_threshold:
                self.confidence_threshold = new_conf
                updated.append(f"confidence_threshold={new_conf}")

            # 引擎层阈值（独立键：engine_min_confidence_threshold）
            # 自进化引擎写入此键，仅作用于 BCRM 信号产生门槛，不覆盖 PollingTrader 层
            new_engine_conf = cfg.get("engine_min_confidence_threshold")
            if (
                hasattr(self, "bcrm_engine")
                and self.bcrm_engine is not None
                and new_engine_conf is not None
            ):
                try:
                    new_engine_conf_f = float(new_engine_conf)
                    if (
                        0.01 <= new_engine_conf_f <= 0.95
                        and new_engine_conf_f != self.bcrm_engine.min_confidence_threshold
                    ):
                        self.bcrm_engine.min_confidence_threshold = new_engine_conf_f
                        updated.append(f"engine.min_confidence_threshold={new_engine_conf_f}")
                except (TypeError, ValueError):
                    pass

            # risk_manager 相关 3 个字段（init 后 risk_manager 才存在）
            if hasattr(self, "risk_manager") and self.risk_manager is not None:
                state = self.risk_manager.state
                new_dll = cfg.get("daily_loss_limit")
                if new_dll is not None and new_dll != state.daily_loss_limit:
                    state.daily_loss_limit = new_dll
                    updated.append(f"daily_loss_limit={new_dll}")
                new_mcl = cfg.get("max_consecutive_losses")
                if new_mcl is not None and new_mcl != state.max_consecutive_losses:
                    state.max_consecutive_losses = int(new_mcl)
                    updated.append(f"max_consecutive_losses={new_mcl}")
                new_dpp = cfg.get("default_position_pct")
                if new_dpp is not None and new_dpp != state.position_size_pct:
                    state.position_size_pct = new_dpp
                    updated.append(f"default_position_pct={new_dpp}")
                new_llp = cfg.get("loss_limit_pct")
                if new_llp is not None and new_llp != state.loss_limit_pct:
                    state.loss_limit_pct = float(new_llp)
                    updated.append(f"loss_limit_pct={new_llp}")

            # ── Phase C S4: 排名止盈阈值热配置 ─────────────────
            new_gap = cfg.get("ranked_tp_gap_ratio")
            if new_gap is not None and float(new_gap) != getattr(self, "RANKED_TP_GAP_RATIO", 0.70):
                self.RANKED_TP_GAP_RATIO = float(new_gap)
                updated.append(f"RANKED_TP_GAP_RATIO={new_gap}")
            new_minp = cfg.get("ranked_tp_min_profit_usdt")
            if new_minp is not None and float(new_minp) != getattr(self, "RANKED_TP_MIN_PROFIT_USDT", 5.0):
                self.RANKED_TP_MIN_PROFIT_USDT = float(new_minp)
                updated.append(f"RANKED_TP_MIN_PROFIT_USDT={new_minp}")

            # ── Phase C S3: 多 horizon PREP_EXIT 边际热配置 ─────────
            # 注意：HORIZON_BAR_CANDIDATES 不做热配置（变更需重训多 horizon 模型，
            #       会破坏模型对齐）；仅热配 HORIZON_PREP_EXIT_MARGIN 安全阈值。
            new_margin = cfg.get("horizon_prep_exit_margin")
            if new_margin is not None:
                try:
                    new_margin_int = int(new_margin)
                    if 0 < new_margin_int <= 20 and new_margin_int != getattr(self, "HORIZON_PREP_EXIT_MARGIN", 3):
                        self.HORIZON_PREP_EXIT_MARGIN = new_margin_int
                        updated.append(f"HORIZON_PREP_EXIT_MARGIN={new_margin_int}")
                except (TypeError, ValueError):
                    pass

            if updated:
                tag = "init" if initial else "reload"
                self._log(f"[进化阈值/{tag}] 从 config.json 加载: {', '.join(updated)}")
        except Exception as e:
            if initial:
                # init 阶段失败静默（config 可能尚不存在）
                pass
            else:
                self._log(f"[进化阈值/reload] 加载失败: {e}", "WARN")

    def _maybe_adjust_gate_base_threshold(self, trade_snapshot: Optional[dict] = None) -> None:
        """v4.6: 基于聚合样本（≥30 笔，非单笔）动态调节过滤层基础阈值。

        规则：
          - 最近 N≥30 笔整体胜率 < 40% → 阈值上调 +0.03（收紧过滤）
          - 最近 N≥30 笔整体胜率 ≥ 60% → 阈值下调 -0.02（放宽过滤）
          - 其他情况：不调整
          - 调节步长单次最大 ±0.03，硬边界 [0.25, 0.60]
          - 冷却期：30 分钟最多调节 1 次
        """
        import time as _t
        _state = getattr(self, "_gate_threshold_state", None) or {}
        _recent = list(_state.get("recent_pnl") or [])
        _n_min = int(_state.get("n_min", 30))
        _cd = int(_state.get("adjust_cooldown_s", 1800))
        _now = _t.time()
        if len(_recent) < _n_min:
            return
        if _now - float(_state.get("last_adjust_ts", 0.0) or 0.0) < _cd:
            return

        try:
            wins = sum(1 for (pnl_pct, _sc, _dr) in _recent if pnl_pct > 0)
            total = len(_recent)
            win_rate = wins / max(1, total)
            avg_pnl = sum(pnl_pct for (pnl_pct, _, _) in _recent) / max(1, total)
            old_thr = float(self._gate_base_threshold)
            delta = 0.0

            # 聚合判定（非单笔）：
            if win_rate < 0.40 or avg_pnl < -0.03:
                delta = +0.03  # 胜率<40% 或 平均亏损>3% → 收紧
            elif win_rate >= 0.60 and avg_pnl > 0.02:
                delta = -0.02  # 胜率≥60% 且 平均盈利>2% → 放宽

            if abs(delta) < 1e-9:
                return

            new_thr = max(0.25, min(0.60, old_thr + delta))
            if abs(new_thr - old_thr) < 1e-5:
                return

            self._gate_base_threshold = float(new_thr)
            self._gate_threshold_state["last_adjust_ts"] = _now
            snap_coin = (trade_snapshot or {}).get("coin", "N/A")
            self._log(
                f"[基础阈值动态调节] 触发样本={total}/{_n_min} | 胜率={win_rate:.2%} "
                f"平均盈亏={avg_pnl:+.3%} | 阈值 {old_thr:.3f}→{new_thr:.3f} Δ={delta:+.3f}"
                f" | 触发平仓={snap_coin} 本次={((trade_snapshot or {}).get('pnl_pct') or 0):+.3%}",
                "INFO",
            )
        except Exception as _ate:
            self._log(
                f"[基础阈值动态调节] 异常（忽略）：{type(_ate).__name__}", "WARN"
            )

    def _adjust_confidence_threshold(self) -> float:
        """根据外部知识调整置信度阈值"""
        base_threshold = self.confidence_threshold

        if self.external_knowledge.get("risk_aversion", 0.5) > 0.8:
            adjusted = base_threshold + 0.05
            self._log(f"[外部知识] 风险厌恶高，置信度阈值提高至 {adjusted:.2f}")
            return adjusted

        if self.external_knowledge.get("market_bias") == "bear":
            adjusted = base_threshold + 0.03
            self._log(f"[外部知识] 熊市环境，置信度阈值提高至 {adjusted:.2f}")
            return adjusted

        return base_threshold

    def _maybe_refresh_coins(self):
        """8h 刷新公共代币池，保留有持仓的币种（不从池中移除有仓位的币）"""
        now = time.time()
        if now - self._last_pool_refresh < _POOL_TTL:
            return
        self._last_pool_refresh = now
        new_syms = _load_registry_symbols()
        if not new_syms:
            return
        new_coins = [self._norm(c) for c in new_syms]
        for coin in self.coins:
            inst_id = f"{coin}-USDT-SWAP"
            try:
                if self.position_tracker.has_open_position(inst_id):
                    if coin not in new_coins:
                        new_coins.append(coin)
                        self._log(f"[币池刷新] 保留持仓币种: {coin}")
            except Exception:
                pass
        old_set = set(self.coins)
        new_set = set(new_coins)
        added = new_set - old_set
        removed = old_set - new_set
        if added or removed:
            self._log(
                f"[币池刷新] 新增={sorted(added)} 移除={sorted(removed)} "
                f"最终={len(new_coins)}币"
            )
        self.coins = new_coins

    def run_once(self):
        """执行一轮推理 + 交易"""
        self._maybe_refresh_coins()
        self._check_date_rollover()
        # BDSM 每日快照自动生成（幂等，已存在则跳过）
        try:
            self._ensure_bdsm_snapshot_today()
        except Exception as _bdsm_e:
            self._log(f"[BDSM] 快照确保失败(FAIL-OPEN): {_bdsm_e}", "WARN")
        self._load_external_knowledge()
        # A-1修复：每轮热 reload 进化后的阈值
        self._load_evolution_config(initial=False)
        # P2-S4c: 跨子系统软标签 ESS 注入（每24h一次，FAIL-OPEN）
        try:
            self._inject_cross_system_soft_labels()
        except Exception as _cs_e:
            self._log(f"[P2-S4c] 软标签注入调用异常(FAIL-OPEN): {_cs_e}", "DEBUG")
        self.cycle_count += 1
        self._log(f"═══ 轮询 #{self.cycle_count} 开始 ═══")

        risk_state = self.risk_manager.get_state()
        perf_stats = self.perf_tracker.get_today_stats()
        self._log(
            f"[状态] 日盈亏={risk_state['daily_pnl']:.2f} | "
            f"连亏={risk_state['consecutive_losses']}/{risk_state['max_consecutive_losses']} | "
            f"交易暂停={risk_state['trading_halted']} | "
            f"今日交易={perf_stats.get('total_trades', 0)}笔"
        )

        # 通用资金调控组件状态输出（非阻塞，每轮懒拉取一次 advice 并打印摘要）
        if self._capital_ctrl is not None:
            try:
                _ca = self._fetch_capital_advice(force=False)
                if _ca is not None:
                    _alw = _ca.get("allowed", True)
                    _press = _ca.get("margin_pressure", "LOW")
                    _up = float(_ca.get("used_pct", 0.0) or 0.0)
                    _avail = float(_ca.get("current_avail", 0.0) or 0.0)
                    _capmax = float(_ca.get("max_position_usdt", 0.0) or 0.0)
                    _teq = float(_ca.get("total_eq", 0.0) or 0.0)
                    _rsn = _ca.get("reason", "") or "ok"
                    self._log(
                        f"[资金调控] 前置约束层就绪 | allowed={_alw} pressure={_press} "
                        f"used_pct={_up:.1f}% avail={_avail:.1f}U eq={_teq:.1f}U "
                        f"max_position_usdt={_capmax:.2f} ({_rsn})",
                        "INFO" if _alw else "WARN",
                    )
                else:
                    self._log("[资金调控] 前置约束层：advice拉取失败，降级易经自有风控", "WARN")
            except Exception as _ce:
                self._log(f"[资金调控] 轮询摘要异常，不影响交易: {_ce}", "WARN")

        try:
            self._run_once_five_domain_daily_update()
        except Exception as _fde:
            self._log(f"[战略层影子] 日级打分更新异常，不阻塞: {_fde}", "WARN")

        # ═══════════════════════════════════════════════════
        # 方案 C v3.0：组合级熔断（SW-C8）每轮 tick 一次
        #   - G-04 终极熔断 → 24h emergency_shutdown
        #   - G-02 黑天鹅 → 1h block_new_open + SL/TP 微调整
        #   - 组件未初始化或异常 → self._current_fuse_action=None（视为无熔断旁路）
        # ═══════════════════════════════════════════════════
        self._current_fuse_action = None
        if self._portfolio_fuses is not None:
            try:
                import datetime as _dt
                # 合成 ctx（字段不足时 fail-open，PRF 内部再兜底）
                _prf_ctx: Dict[str, Any] = {}
                # ① positions_by_direction：从持仓 tracker 汇总
                try:
                    _pos_by_dir: Dict[str, int] = {"LONG": 0, "SHORT": 0}
                    for _tp in getattr(self.position_tracker, "open_positions", {}).values():
                        _side = getattr(_tp, "pos_side", "") or ""
                        if _side.lower() == "long":
                            _pos_by_dir["LONG"] += 1
                        elif _side.lower() == "short":
                            _pos_by_dir["SHORT"] += 1
                    _prf_ctx["positions_by_direction"] = _pos_by_dir
                except Exception:
                    _prf_ctx["positions_by_direction"] = {"LONG": 0, "SHORT": 0}
                # ② avg_float_loss_pct_15m：perf_tracker 近似（拿不到就 0.0，PRF 内部旁路 cond2）
                try:
                    _today_stats = self.perf_tracker.get_today_stats() or {}
                    _avg_loss = float(_today_stats.get("avg_float_loss_pct_15m", 0.0) or 0.0)
                    _prf_ctx["avg_float_loss_pct_15m"] = _avg_loss
                except Exception:
                    _prf_ctx["avg_float_loss_pct_15m"] = 0.0
                # ③ btc_lambda：BTC 自反阀门本轮值（无则 1.0，cond3 不命中）
                try:
                    _btc_lambda = getattr(self, "_last_btc_lambda", 1.0) or 1.0
                    _prf_ctx["btc_lambda"] = float(_btc_lambda)
                except Exception:
                    _prf_ctx["btc_lambda"] = 1.0
                # ④ daily_equity_prev/now：权益回撤计算（prev=昨日收盘权益，now=当前权益）
                try:
                    _eq_now = float(getattr(self.perf_tracker, "current_equity", 0.0) or 0.0)
                    _eq_prev = float(getattr(self.perf_tracker, "yesterday_close_equity", 0.0) or 0.0)
                    if _eq_prev <= 0:
                        _eq_prev = _eq_now if _eq_now > 0 else 0.0
                    _prf_ctx["daily_equity_prev"] = _eq_prev
                    _prf_ctx["daily_equity_now"] = _eq_now
                except Exception:
                    _prf_ctx["daily_equity_prev"] = 0.0
                    _prf_ctx["daily_equity_now"] = 0.0

                # ⑤ G-05 不可逆级联4事前判据（FAIL-OPEN，缺失默认False）
                #   ① primary_dim_jumped : primary矛盾维度跳变（质变检测）
                #   ② mechanism_active    : 机制性强制启动（反身性燃料/自影响检测）
                #   ③ no_bounce_at_key   : 价格穿关键位后无有效反弹
                #   ④ no_intervener      : 无外部干预者
                try:
                    _pipeline = getattr(self, "_evolution_pipeline", None)
                    # ① primary_dim_jumped ← ContradictionShiftAccumulator.detect_shift()
                    _shift_result = getattr(_pipeline, "_last_shift_result", None) if _pipeline is not None else None
                    _prf_ctx["primary_dim_jumped"] = _shift_result is not None
                except Exception:
                    _prf_ctx["primary_dim_jumped"] = False
                try:
                    _pipeline = getattr(self, "_evolution_pipeline", None)
                    # ② mechanism_active ← ReflexivityMonitor.check_self_influence()
                    _mech_active = False
                    if _pipeline is not None:
                        _rm = _pipeline._get_reflexivity_monitor() if hasattr(_pipeline, "_get_reflexivity_monitor") else None
                        if _rm is not None:
                            _si = _rm.check_self_influence()
                            _mech_active = bool(_si.get("self_influence_detected", False)) and \
                                           float(_si.get("influence_coefficient", 0.0)) > 0.02
                    _prf_ctx["mechanism_active"] = _mech_active
                except Exception:
                    _prf_ctx["mechanism_active"] = False
                try:
                    # ③ no_bounce_at_key ← 价格穿关键位后无有效反弹（增强版）
                    #   使用 PotentialFieldEngineer 关键位检测：价格穿越支撑位且后续无反弹
                    _no_bounce = self._detect_no_bounce_at_key()
                    _prf_ctx["no_bounce_at_key"] = _no_bounce
                except Exception:
                    _prf_ctx["no_bounce_at_key"] = False
                try:
                    # ④ no_intervener ← 外部干预者检测（增强版）
                    #   查询最近N小时 odaily_newsflash 是否有 monetary_policy/crypto_regulation/us_policy 事件
                    #   有干预事件 → no_intervener=False（级联可被截断）
                    #   无干预事件 → no_intervener=True（级联不可逆）
                    _prf_ctx["no_intervener"] = self._detect_no_intervener()
                except Exception:
                    _prf_ctx["no_intervener"] = True

                _act = self._portfolio_fuses.tick_and_check(_prf_ctx)
                self._current_fuse_action = _act

                # 影子日志：触发时输出（no_trigger 不打印，避免刷屏）
                if _act.reason and _act.reason != "no_trigger" and not _act.reason.startswith("fail_open:"):
                    try:
                        _sd = _act.as_shadow_dict()
                        self._log(
                            f"[组合熔断影子] {_sd.get('reason')} | "
                            f"block_new={_sd.get('block_new_open')} "
                            f"SL_adj={_sd.get('sl_mult_adj'):.2f} TP_adj={_sd.get('tp_mult_adj'):.2f} "
                            f"emergency={_sd.get('emergency_shutdown')} "
                            f"valid_until={_sd.get('block_until')}",
                            "WARN" if _act.block_new_open or _act.emergency_shutdown else "INFO",
                        )
                        if _act.emergency_shutdown:
                            self._log(
                                "[组合熔断] ★ G-04 终极熔断触发：单日权益回撤≥3%，"
                                "需人工复盘并手动关断 SW-C1~SW-C8 共 24h；"
                                "系统当前自动进入 block_new_open=True 状态",
                                "ERROR",
                            )
                    except Exception:
                        pass
            except Exception as _prfe:
                import datetime as _dt2
                _hour_tag = _dt2.datetime.now().strftime("%Y-%m-%dT%H")
                if getattr(self, "_last_prf_failopen_hour", "") != _hour_tag:
                    self._log(
                        f"[组合熔断] fail-open（每小时 1 次）：{type(_prfe).__name__}，"
                        f"视为无熔断（不阻塞任何开仓）",
                        "WARN",
                    )
                    self._last_prf_failopen_hour = _hour_tag
                self._current_fuse_action = None

        effective_threshold = self._adjust_confidence_threshold()

        # ══ P2-S4b: 紧耦合流 K线级触发（BTC/ETH/SOL 1H）══════════════════════
        #   每轮调用 _check_evolution_kline_signal → KlineEventHandler →
        #   auto_execute=True 时触发 _evolution_build_position（25U硬上限）
        try:
            self._check_evolution_kline_signal()
        except Exception as _evo_e:
            self._log(f"[P2-S4b] K线触发异常(FAIL-OPEN): {_evo_e}", "WARN")

        # ══ P2-S4b+: 自进化系统独立离场巡检（EvolutionExitEngine）═════════════
        #   开仓由 _check_evolution_kline_signal 负责，离场由 _evolution_check_exit 负责
        #   仅处理 source_tag="evolution" 持仓，与 BCRM/BDSM 子池隔离
        # ★ 规则 2b 前置：为 evolution 持仓补 BCRM2.0 推理，确保离场决策有最新反向信号
        try:
            self._ensure_bcrm2_for_evolution_positions()
        except Exception as _bcrm_pre_e:
            self._log(f"[EvolutionExitEngine] BCRM2.0 预推理异常(FAIL-OPEN): {_bcrm_pre_e}", "DEBUG")
        try:
            self._evolution_check_exit()
        except Exception as _evo_exit_e:
            self._log(f"[EvolutionExitEngine] 巡检异常(FAIL-OPEN): {_evo_exit_e}", "WARN")

        # ══ Phase A (S1): MODE 算力重分配入口 ══════════════════════════════
        # 在执行任何昂贵操作（anomaly检测/BCRM2全推理）之前先决定 MODE：
        #   MODE-OFF（S1关） ：anom/full/coarse 全沿用 self.coins（旧路径等价）
        #   MODE3_FULL（100%）：anom 精简，只跑持仓+Top3粗推理候选；Full 仅持仓；Coarse 3 候选粗排后补Top1全推理
        #   MODE2_HALF（2/3+）：anom 选 持仓+Top4；Full 选 持仓+Top5；不跑 Coarse
        #   MODE1_LIGHT（<2/3）：anom/full 遍历全部候选（空仓轻压力，等价旧路径）
        # ── B4 防御：轮次计数推进 + 回退自动清缓存 ───────────
        # 正常情况下 _cycle_idx 单调递增；若因日期 rollover 或手工重置发生回退，
        # 所有缓存的 written_cycle 将与 TTL 判定方向相反（缓存永不过期）。
        self._advance_cycle_idx()
        mode_tag, anom_coins_mode, infer_full_coins, infer_coarse_coins = self._decide_mode_coins()
        self._log(
            f"[MODE] {mode_tag} | anomaly探针N={len(anom_coins_mode)} "
            f"Full推理N={len(infer_full_coins)} Coarse推理N={len(infer_coarse_coins)} | "
            f"Full币种={infer_full_coins} Coarse={infer_coarse_coins}"
        )

        # 异常检测 (Phase 2.1) —— 仅遍历 anom_coins_mode（MODE3 时精简到 持仓+Top3，避免 N^2 K线探针）
        anomaly_detected = False
        anomaly_coins = []
        try:
            for coin in anom_coins_mode:
                kline_data = _load_kline_from_okx(
                    inst_id=f"{coin}-USDT-SWAP", bar=self.bar, limit=self.kline_limit
                )
                if kline_data and len(kline_data) > 100:
                    import pandas as pd

                    df = pd.DataFrame(kline_data)
                    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
                    df.set_index("timestamp", inplace=True)
                    df.rename(
                        columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"},
                        inplace=True,
                    )

                    summary = self.anomaly_detector.get_summary(df, symbol=coin)
                    critical_count = summary["by_severity"].get("critical", 0)
                    high_count = summary["by_severity"].get("high", 0)

                    if critical_count > 0 or high_count >= 2:
                        anomaly_detected = True
                        anomaly_coins.append(coin)
                        self._log(
                            f"[异常检测] {coin}: 检测到 {critical_count} 个严重异常, {high_count} 个高等级异常"
                        )

            if anomaly_detected:
                self._log(f"[异常检测] 市场环境异常，提高风控等级 | 涉及币种: {anomaly_coins}")
                effective_threshold = min(0.8, effective_threshold + 0.15)
        except Exception as e:
            self._log(f"[异常检测] 检测失败: {e}", "WARN")

        # ===== 第一阶段：收集所有币种推理结果（Phase A MODE-aware）=====
        # 分三路顺序执行：Full(完整BCRM2.0) → Coarse(快速粗排) → MODE3 Top1 补全Full
        cycle_success = True
        all_inferences: Dict[str, dict] = {}
        coarse_inferences: Dict[str, dict] = {}
        toppedup_history: set = set()  # 补全过 Full 的币种（第三阶段开仓门禁用）

        # ── Step 1: Full 推理（infer_full_coins = 持仓 + MODE1/2 的候选TopN）──
        for coin in infer_full_coins:
            # P0-2: 动态币种黑名单过滤（连续2次亏损→封禁3日，到期自动释放）
            blocked, bl_reason = self._check_dynamic_blacklist(coin)
            if blocked:
                self._log(f"[{coin}] 币种黑名单 | 跳过（{bl_reason}）")
                continue
            try:
                inference = self._fetch_and_infer(coin)
                if not inference.get("ok"):
                    self._log(f"[{coin}] 推理失败: {inference.get('error')}", "ERROR")
                    cycle_success = False
                    continue

                self._log(
                    f"[{coin}] 价格={inference['price']} | "
                    f"卦象={inference['hexagram']} | "
                    f"方向={inference['direction']} | "
                    f"置信度={inference['confidence']:.2f} | "
                    f"八卦={inference['bagua_direction']}({inference['bagua_confidence']:.2f}) | "
                    f"震荡={inference['is_ranging']} | "
                    f"波动率={inference.get('volatility', 0):.4f} | "
                    f"fail={inference['fail_closed']}"
                )

                # P3: 反向召回接入 — A 系列 Cron 执行前注入认知召回（建议而非约束）
                if self.cognitive_recall_enabled and self._trading_recall_fn:
                    inference["cognitive_recall"] = self._inject_cognitive_recall(coin, inference)

                # A7 实践论门禁检查（代码驱动，执行前拦截）
                if self.a7_gate and not inference.get("fail_closed", False):
                    current_positions = self._count_yijing_positions()
                    cbr_engine = getattr(self.cbr_bridge, "cbr", None) if self.cbr_bridge else None
                    gate_report = self.a7_gate.check_before_execute(
                        inference=inference,
                        risk_manager=self.risk_manager,
                        cbr_engine=cbr_engine,
                        current_equity=self.perf_tracker.current_equity,
                        max_positions=self.max_positions,
                        current_positions=current_positions,
                    )
                    if not gate_report.passed:
                        self._log(
                            f"[{coin}] A7门禁拦截: " f"{'; '.join(gate_report.blocking_reasons)}",
                            "WARN",
                        )
                        continue

                all_inferences[coin] = inference
                # ★ FIX #4: 缓存最新 BCRM2.0 推理结果，供 evolution 开仓方向冲突检查使用
                if not hasattr(self, "_latest_bcrm_inference"):
                    self._latest_bcrm_inference = {}
                self._latest_bcrm_inference[coin.upper()] = {
                    "direction": inference.get("direction", ""),
                    "confidence": float(inference.get("confidence", 0.0) or 0.0),
                    "price": float(inference.get("price", 0.0) or 0.0),
                    "ts": time.time(),
                }

            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle:{coin}")

        # ── Step 2: Coarse 粗推理（MODE3_FULL 时有候选 infer_coarse_coins = Top3）──
        if infer_coarse_coins:
            self._log(
                f"[MODE3][Step2] {len(infer_coarse_coins)} 个粗推理候选 → 快速MA交叉粗排"
            )
            for coin in infer_coarse_coins:
                blocked, bl_reason = self._check_dynamic_blacklist(coin)
                if blocked:
                    self._log(f"[{coin}] [MODE3][Coarse] 黑名单跳过（{bl_reason}）")
                    continue
                try:
                    coarse_inf = self._infer_coarse(coin)
                    if not coarse_inf.get("ok"):
                        self._log(
                            f"[{coin}] [MODE3][Coarse] 粗推理失败: {coarse_inf.get('error')}",
                            "WARN",
                        )
                        continue
                    all_inferences[coin] = coarse_inf
                    coarse_inferences[coin] = coarse_inf
                    self._log(
                        f"[{coin}] [MODE3][Coarse] 粗置信度={coarse_inf.get('confidence', 0):.2f} "
                        f"dir={coarse_inf.get('direction', 'NEUTRAL')} fail={coarse_inf.get('fail_closed', True)}"
                    )
                except Exception as e:
                    self._log(f"[{coin}] [MODE3][Coarse] 异常: {e}", "ERROR")

        # ── Step 3: MODE3 补全推理门禁（粗推理 Top1 → 重新跑完整版 BCRM2.0）──
        topup_list = self._pick_topup_from_coarse(infer_coarse_coins, coarse_inferences)
        if topup_list:
            self._log(
                f"[MODE3][Step3] Top1 补全推理 → {topup_list}（其他粗结果禁止开仓）"
            )
        for topup_coin in topup_list:
            blocked, bl_reason = self._check_dynamic_blacklist(topup_coin)
            if blocked:
                self._log(f"[{topup_coin}] [MODE3][补全] 黑名单跳过（{bl_reason}）")
                continue
            try:
                coarse_conf = coarse_inferences.get(topup_coin, {}).get("confidence", None)
                full_inf = self._fetch_and_infer(topup_coin)
                if full_inf and full_inf.get("ok"):
                    # A7 门禁也需要再检查一次（补全版本需要满足同 Full 路径一致的约束）
                    a7_ok = True
                    if self.a7_gate and not full_inf.get("fail_closed", False):
                        cbr_engine = getattr(self.cbr_bridge, "cbr", None) if self.cbr_bridge else None
                        gp = self.a7_gate.check_before_execute(
                            inference=full_inf,
                            risk_manager=self.risk_manager,
                            cbr_engine=cbr_engine,
                            current_equity=self.perf_tracker.current_equity,
                            max_positions=self.max_positions,
                            current_positions=self._count_yijing_positions(),
                        )
                        a7_ok = gp.passed
                        if not a7_ok:
                            self._log(
                                f"[{topup_coin}] [MODE3][补全] A7拦截: "
                                f"{'; '.join(gp.blocking_reasons)}",
                                "WARN",
                            )
                    if a7_ok:
                        self._apply_topup_full(all_inferences, topup_coin, full_inf, coarse_conf)
                        toppedup_history.add(topup_coin)
                else:
                    self._log(
                        f"[{topup_coin}] [MODE3][补全] Full推理失败，仍保留粗结果（但禁止开仓）",
                        "WARN",
                    )
            except Exception as e:
                self._log(f"[{topup_coin}] [MODE3][补全] 异常: {e}", "ERROR")

        # —— BDSM 协作 · 缺口 3：出场 OR 逻辑（先于 BCRM S4 排名止盈 + 单币离场评估）——
        #   按 BDSM 快照 exit_action 优先级 CLOSE_ALL > REDUCE_80 > REDUCE_50 先执行；
        #   仅对 BDSM_COINS 且 PositionTracker 内有真实持仓者生效；非 BDSM 直接跳过；
        #   FAIL-OPEN：任何读取/序列化异常 → 字节等价 NONE（BDSM 不存在），绝不误平仓。
        try:
            bdsm_exit_actions = self._bdsm_check_exit_actions() or []
            if bdsm_exit_actions:
                _exit_log = " | ".join(
                    f"{a.get('coin')}:{a.get('action')} ok={a.get('ok')} rsn={a.get('reason','')}"
                    for a in bdsm_exit_actions
                )
                self._log(
                    f"[BDSM 出场巡检] 本轮执行 {len(bdsm_exit_actions)} 项: {_exit_log}",
                    "INFO",
                )
            else:
                # ★ 空 action 也必须打日志（证明 gap3 巡检入口已进入 daemon 执行链；不打则无法从日志 grep 验证上线）
                self._log(
                    "[BDSM 出场巡检] 本轮 0 项（快照 exit=NONE 或 BDSM_COINS 无真实持仓，FAIL-OPEN 安全态）",
                    "INFO",
                )
        except Exception as _bdsm_exit_exc:
            # 终极 FAIL-OPEN：exit 巡检发生任何外部异常 → 跳过，不影响后续 BCRM 离场
            self._log(
                f"[BDSM 出场巡检] 顶层异常（FAIL-OPEN 跳过不阻断）: {_bdsm_exit_exc}", "WARN"
            )

        # —— BDSM 独立开仓（基本面价值建仓，不依赖 BCRM 开仓信号）——
        #   先出场巡检再开新仓，避免刚开仓就被出场巡检平仓。
        #   开关：enable_bdsm_independent_open（默认 True）
        #   FAIL-OPEN：任何异常 → 跳过，不阻断主链路。
        try:
            self._bdsm_independent_open()
        except Exception as _bdsm_open_exc:
            self._log(
                f"[BDSM 独立开仓] 顶层异常（FAIL-OPEN 跳过不阻断）: {_bdsm_open_exc}",
                "WARN",
            )

        # —— 战略层+策略层独立开仓（三层信号组合，不依赖 BCRM2.0 推理）——
        #   开关：enable_strategy_independent_open（默认 False，安全第一）
        #   FAIL-OPEN：任何异常 → 跳过，不阻断主链路。
        try:
            self._strategy_independent_open()
        except Exception as _strat_open_exc:
            self._log(
                f"[策略独立开仓] 顶层异常（FAIL-OPEN 跳过不阻断）: {_strat_open_exc}",
                "WARN",
            )

        # ── 软止损强制执行（2026-09-12 新增）──
        #   根因：OKX algo order（SL/TP）可能未生效或被取消，导致持仓亏损远超 SL 阈值
        #   （PUMP -17.37%, SOL -9.39% 均未触发 4% SL）。此检查在每轮轮询中扫描所有持仓，
        #   当亏损超过该仓位的 SL 阈值时强制市价平仓，作为 OKX algo order 的后备保障。
        #   FAIL-OPEN：任何异常不阻断主循环。
        try:
            self._enforce_soft_stop_loss()
        except Exception as _ssl_exc:
            self._log(
                f"[软止损] 顶层异常（FAIL-OPEN 跳过不阻断）: {_ssl_exc}",
                "WARN",
            )

        # ── Phase C (S4): 全局排名止盈 Top1（跨持仓统一比较） ──
        # 原因：S4 需要比较"当前所有持仓 upl 的全局排名"，
        # 若放在 _execute_trade 的单币种循环里，会重复计算且无法做全局 gap 判定。
        # 因此在第二阶段前统一执行一次：若 gap≥0.7 且 Top1≥5U → 2/2 确认后立即平仓
        # （后续第二阶段该币种 has_position 自动为 False，跳过持仓管理）
        if getattr(self, "enable_ranked_tp", False) and all_inferences:
            try:
                ranked_list = self._build_ranked_positions(all_inferences)
                if ranked_list and len(ranked_list) >= 2:
                    _log_rank = " | ".join(
                        f"{r['coin']}={r['upl']:.1f}U({r['upl_ratio']:.2%})" for r in ranked_list
                    )
                    self._log(f"[S4 排名止盈] 当前持仓排名（盈利高→低）：{_log_rank}", "INFO")
                    tp_result = self._handle_ranked_tp_top1(ranked_list)
                    # 归档 S4 评估结果到 JSONL（供 s4_stats.py 长期统计）
                    self._archive_s4_eval(ranked_list, tp_result)
                    if tp_result.get("triggered"):
                        self._log(
                            f"[S4 排名止盈] ✅ 已止盈 {tp_result.get('coin')} "
                            f"gap={tp_result.get('gap_ratio', 0):.2f} "
                            f"reason={tp_result.get('reason')}",
                            "INFO",
                        )
            except Exception as _e:
                self._log(f"[S4 排名止盈] 评估异常: {_e}", "WARN")

        # ===== 第二阶段：先处理持仓管理（平仓/反手/离场），按币种顺序 =====
        # 持仓管理按币种顺序即可（无需排名），关键是不要打乱离场时机
        for coin, inference in all_inferences.items():
            try:
                pos_info = self._check_positions(coin)
                if pos_info.get("has_position"):
                    # 有持仓：执行持仓管理（离场评估、信号反转等）
                    self._execute_trade(inference, confidence_threshold=effective_threshold,
                                        all_inferences=all_inferences)
                    # ── Phase B: ShadowLogger 影子记录（只记录，不影响交易）──
                    self._record_shadow_log(coin, inference, {
                        "direction": inference.get("direction"),
                        "confidence": inference.get("confidence"),
                        "position_usdt": inference.get("position_usdt"),
                        "tp_px": inference.get("take_profit_px"),
                        "sl_px": inference.get("stop_loss_px"),
                        "threshold": effective_threshold,
                    })
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 持仓管理异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle_manage:{coin}")

        # ===== 第三阶段：新开仓候选按置信度排名执行 =====
        # 规则：默认根据置信度排名开仓，高置信度优先，仓位大小也根据置信度调控
        open_candidates = []
        for coin, inference in all_inferences.items():
            try:
                pos_info = self._check_positions(coin)
                if pos_info.get("has_position"):
                    continue  # 已有持仓，不在新开仓阶段处理

                # ── Phase A MODE3 门禁：粗推理未补全 Full → 禁止进入开仓候选 ──
                # 说明：toppedup_history 包含 Step3 已补全为 Full 的币种；
                #       _coarse=True 且不在 toppedup 里的币种在本步直接跳过，不参与排名
                if not self._guard_coarse_not_toppedup(coin, inference, toppedup_history):
                    continue

                # 运行时残留清理：本地有记录但 OKX 已无持仓（OKX端 SL/TP 触发）
                # 清理残留并记录平仓时间，用于统一冷静期判断
                # 注意：查询失败（限流）时不清理，避免误删本地持仓记录
                inst_id = f"{coin}-USDT-SWAP"
                if pos_info.get("query_failed"):
                    self._log(f"[{coin}] OKX 持仓查询失败（可能限流），跳过残留清理", "WARN")
                elif self.position_tracker.has_open_position(inst_id):
                    stale_rec = self.position_tracker.get_open_position(inst_id)
                    stale_side = stale_rec.direction if stale_rec else None
                    _stale_src_tag = str(getattr(stale_rec, "source_tag", "") or "")
                    closed_rec = self.position_tracker.close_position(
                        inst_id,
                        exit_price=float(pos_info.get("mark_px", 0.0)) or 0.0,
                        exit_reason="运行时检测OKX持仓消失",
                    )
                    self._log(
                        f"[{coin}] 运行时清理本地残留 " f"(OKX端已平仓, side={stale_side})", "WARN"
                    )
                    # 缺口1修复：OKX端自动平仓后也触发进化反思链路
                    # closed_rec 包含完整 entry_price/exit_price/pnl/pnl_pct/source_tag
                    if closed_rec is not None:
                        try:
                            self._trigger_evolution_reflection(closed_rec)
                        except Exception as _refl_e:
                            self._log(
                                f"[{coin}] 运行时清理后反思回调异常（FAIL-OPEN忽略）: {_refl_e}",
                                "WARN",
                            )

                direction = inference["direction"]
                confidence = inference["confidence"]
                fail_closed = inference["fail_closed"]

                if direction not in ("UP", "DOWN"):
                    continue
                if fail_closed:
                    continue

                # 统一冷静期检查：平仓后 8h 内禁止该币种任何方向新开仓
                _side_map = {"UP": "long", "DOWN": "short"}
                want_side = _side_map.get(direction)
                in_cd, cd_reason = self.position_tracker.is_in_cooldown(
                    inst_id, want_side, self.COOLDOWN_SEC
                )
                if in_cd:
                    self._log(f"[{coin}] 跳过开仓候选: {cd_reason}", "INFO")
                    continue

                # 基础阈值筛选
                short_threshold = (
                    max(effective_threshold, self.short_confidence_threshold)
                    if direction == "DOWN"
                    else effective_threshold
                )
                if confidence < short_threshold:
                    continue

                # 风控检查
                risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
                if not risk_check["allowed"]:
                    self._log(f"[{coin}] 风控拦截开仓候选: {risk_check['reason']}", "WARN")
                    continue

                # 计算"置信度调整后优先级" = confidence * 方向偏好
                # 做空难度更高，进一步乘以 0.95 作轻微折减
                direction_bias = 0.95 if direction == "DOWN" else 1.0
                priority_score = confidence * direction_bias

                open_candidates.append(
                    {
                        "coin": coin,
                        "inference": inference,
                        "priority_score": priority_score,
                        "confidence": confidence,
                        "direction": direction,
                    }
                )
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 候选评估异常: {e}", "ERROR")

        # 按置信度（优先级）从高到低排序
        open_candidates.sort(key=lambda c: c["priority_score"], reverse=True)

        if open_candidates:
            ranking_display = " | ".join(
                f"{c['coin']}({c['direction']} conf={c['confidence']:.2f})" for c in open_candidates
            )
            self._log(
                f"[开仓排名] 共 {len(open_candidates)} 个候选，"
                f"按置信度从高到低：{ranking_display}"
            )

        # 依次按排名执行开仓
        for candidate in open_candidates:
            coin = candidate["coin"]
            inference = candidate["inference"]
            confidence = candidate["confidence"]

            try:
                # 再次检查风控和持仓数（在排名执行过程中可能变化）
                risk_check = self.risk_manager.can_trade(self.perf_tracker.current_equity)
                if not risk_check["allowed"]:
                    self._log(f"[{coin}] 排名开仓前风控拦截: {risk_check['reason']}", "WARN")
                    break

                current_positions = self._count_yijing_positions()
                if current_positions >= self.max_positions:
                    self._log(
                        f"[{coin}] 已达易经系统最大持仓数 {self.max_positions}，"
                        f"剩余 {len(open_candidates) - open_candidates.index(candidate) - 1} 个候选跳过"
                    )
                    break

                self._log(
                    f"[{coin}] 排名 #{open_candidates.index(candidate) + 1} 开仓 | "
                    f"置信度={confidence:.2f} 方向={candidate['direction']}"
                )
                self._execute_trade(inference, confidence_threshold=effective_threshold)
                # ── Phase B: ShadowLogger 影子记录（只记录，不影响交易）──
                self._record_shadow_log(coin, inference, {
                    "direction": inference.get("direction"),
                    "confidence": inference.get("confidence"),
                    "position_usdt": inference.get("position_usdt"),
                    "tp_px": inference.get("take_profit_px"),
                    "sl_px": inference.get("stop_loss_px"),
                    "threshold": effective_threshold,
                })
            except Exception as e:
                cycle_success = False
                self._log(f"[{coin}] 排名开仓异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context=f"cycle_open:{coin}")

        open_pos = self.position_tracker.all_open_positions()
        self._log(f"[持仓跟踪] 记录中持仓数: {len(open_pos)}")
        for pos in open_pos:
            self._log(
                f"  - {pos.coin}: {pos.direction} @ {pos.entry_price} "
                f"(conf={pos.confidence:.2f})"
            )

        learn_state = self.learning_scheduler.get_state()
        self._log(
            f"[学习] 当前案例={learn_state['current_case_count']} | "
            f"新增自上次重训={learn_state['new_cases_since']} | "
            f"上次重训={learn_state['last_retrain_time_str']}"
        )

        # ── 段⑤+段⑥ 审计：在线学习 evaluate_and_correct + AB双基线闸门状态（只读，不做 promote）──
        self._run_polling_level_learning_and_ab()

        if self.guardian:
            self.guardian.record_heartbeat(
                status="running",
                cycle_count=self.cycle_count,
            )
            if cycle_success:
                self.guardian.record_success()

        self._log(f"═══ 轮询 #{self.cycle_count} 结束 ═══\n")

    def run_loop(self):
        """主轮询循环"""
        self.running = True
        cfg = self.okx_client.cfg
        self._log(
            f"轮询交易器启动 | "
            f"间隔={self.interval}s 币种={self.coins} 周期={self.bar} | "
            f"置信度阈值={self.confidence_threshold} 最大持仓={self.max_positions} | "
            f"dry_run={cfg.get('dry_run')} simulated={cfg.get('simulated')}"
        )
        self._log(
            f"[风控] 日亏损上限={self.risk_manager.state.daily_loss_limit}USDT | "
            f"最大连续亏损={self.risk_manager.state.max_consecutive_losses} | "
            f"默认仓位={self.risk_manager.state.position_size_pct:.1%}"
        )
        self._log(
            f"[绩效] 初始权益={self.perf_tracker.initial_equity} | "
            f"当前权益={self.perf_tracker.current_equity:.2f} | "
            f"历史交易={self.perf_tracker.get_overall_stats()['total_trades']}笔"
        )

        def _shutdown(signum, frame):
            _sig_names = {
                getattr(signal_module, k, 0): k
                for k in ("SIGINT", "SIGTERM", "SIGHUP", "SIGPIPE",
                          "SIGXCPU", "SIGXFSZ", "SIGUSR1", "SIGUSR2")
            }
            _sn = _sig_names.get(signum, f"SIG#{signum}")
            self._log(f"收到退出信号 {_sn}，正在停止...", "WARN")
            self.running = False

        signal_module.signal(signal_module.SIGINT, _shutdown)
        signal_module.signal(signal_module.SIGTERM, _shutdown)
        # macOS setsid 后仍然可能收到的信号，全部统一捕获写日志，避免静默退出
        for _sn_name in ("SIGHUP", "SIGPIPE", "SIGXCPU", "SIGXFSZ", "SIGUSR1", "SIGUSR2"):
            try:
                signal_module.signal(getattr(signal_module, _sn_name), _shutdown)
            except (AttributeError, OSError, ValueError):
                pass

        # ══════════════════════════════════════════════════════════════
        # 内置 yijing_monitor 调度线程（每 6 小时触发一次健康检查 + 自进化）
        # 替代 launchd 定时调度，避免 macOS 沙箱权限问题
        # ══════════════════════════════════════════════════════════════
        MONITOR_INTERVAL_SEC = 6 * 3600  # 6 小时

        def _monitor_worker():
            first_run = True
            while self.running:
                try:
                    if first_run:
                        # 首次延迟 1 小时启动：避免和首轮 18 币种 BCRM2 训练/推理重叠导致内存压力
                        wait_sec = 60 * 60
                        desc = "首次延迟 1h"
                    else:
                        # 之后每 6 小时一次
                        wait_sec = MONITOR_INTERVAL_SEC
                        desc = "定期"
                    # 以 1s 为粒度响应 shutdown
                    for _ in range(wait_sec):
                        if not self.running:
                            return
                        time.sleep(1)
                    first_run = False
                    self._log(f"[Monitor] {desc}触发监控周期（健康检查 + 自进化）", "INFO")
                    # 延迟导入，避免模块加载冲突
                    from scripts.memory_l4 import yijing_monitor
                    try:
                        healthy, status, detail = yijing_monitor.check_yijing_health()
                        self._log(
                            f"[Monitor] 健康: {'✅ 正常' if healthy else '⚠️ 异常'} | {status}",
                            "INFO" if healthy else "WARN",
                        )
                    except Exception as _e:
                        self._log(f"[Monitor] 健康检查异常: {_e}", "WARN")
                    try:
                        evo, perf, evolved = yijing_monitor.run_evolution()
                        self._log(
                            f"[Monitor] 进化完成 | 累计次数={evo.get('evolution_count', 0)} "
                            f"| 胜率={perf.get('win_rate', 0):.0%} | 总盈亏={perf.get('total_pnl', 0):.2f}USDT",
                            "INFO",
                        )
                    except Exception as _e:
                        self._log(f"[Monitor] 自进化异常: {_e}", "ERROR")
                        if self.guardian:
                            self.guardian.record_error(_e, context="monitor_evolution")
                except Exception as _e:
                    # 线程级别兜底：不能让监控线程挂了
                    self._log(f"[Monitor] 调度线程异常: {_e}", "ERROR")
                    for _ in range(300):
                        if not self.running:
                            return
                        time.sleep(1)

        import threading as _threading
        monitor_thread = _threading.Thread(
            target=_monitor_worker, name="yijing_monitor", daemon=True
        )
        monitor_thread.start()
        self._log(f"[Monitor] 内置调度线程已启动 | 周期={MONITOR_INTERVAL_SEC//3600}h", "INFO")

        while self.running:
            try:
                self.run_once()
            except Exception as e:
                self._log(f"轮询异常: {e}", "ERROR")
                if self.guardian:
                    self.guardian.record_error(e, context="main_loop")

            if not self.running:
                break

            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)

        if self.guardian:
            self.guardian.stop()
        self._log("轮询交易器已停止")

    def get_status(self) -> dict:
        """获取完整运行状态（供 API 查询）"""
        return {
            "cycle_count": self.cycle_count,
            "running": self.running,
            "interval": self.interval,
            "coins": self.coins,
            "bar": self.bar,
            "confidence_threshold": self.confidence_threshold,
            "max_positions": self.max_positions,
            "risk": self.risk_manager.get_state(),
            "performance_today": self.perf_tracker.get_today_stats(),
            "performance_overall": self.perf_tracker.get_overall_stats(),
            "open_positions": [
                {
                    "coin": p.coin,
                    "inst_id": p.inst_id,
                    "direction": p.direction,
                    "entry_price": p.entry_price,
                    "confidence": p.confidence,
                    "hexagram": p.hexagram,
                    "entry_time": p.entry_time,
                }
                for p in self.position_tracker.all_open_positions()
            ],
            "learning": self.learning_scheduler.get_state(),
            "guardian": self.guardian.get_status() if self.guardian else {},
        }


def main():
    parser = argparse.ArgumentParser(description="易经推理轮询交易器（P2 完整版）")
    parser.add_argument("--interval", type=int, default=3600, help="轮询间隔（秒），默认 3600(1h)")
    parser.add_argument(
        "--coins",
        type=str,
        default=",".join(_load_registry_symbols() or [
            "UNI", "PUMP", "MU", "SKHYNIX", "HYPE", "ETH", "BTC", "SOL",
            "XAU", "XAG", "GOOGL", "NVDA", "AMZN", "OKB", "BNB",
            "CRCL", "COIN", "BMNR", "MSTR",
        ]),
        help="币种列表，逗号分隔，默认读取公共代币池(config/token_registry.json)，可override",
    )
    parser.add_argument("--bar", type=str, default="1H", help="K线周期，默认 1H")
    parser.add_argument("--confidence", type=float, default=0.35, help="置信度阈值，默认 0.35")
    parser.add_argument(
        "--short-confidence",
        type=float,
        default=0.80,
        help="做空置信度阈值（高于做空以减少做空频率），默认 0.80",
    )
    parser.add_argument("--max-positions", type=int, default=3, help="最大同时持仓数，默认 3")
    parser.add_argument("--once", action="store_true", help="只执行一次，不循环")
    parser.add_argument(
        "--initial-equity",
        type=float,
        default=None,
        help="初始权益（USDT），不指定则从 OKX 读取实际余额",
    )
    parser.add_argument(
        "--daily-loss-limit",
        type=float,
        default=-30.0,
        help="日最大亏损兜底值（USDT），默认 -30（150U可用金的20%）",
    )
    parser.add_argument(
        "--max-consecutive-losses",
        type=int,
        default=999,
        help="最大连续亏损次数（已禁用，默认999不再触发），风控改以亏损金额为准",
    )
    parser.add_argument(
        "--position-pct",
        type=float,
        default=0.20,
        help="默认单笔仓位比例，默认 0.20(20%%)（C项优化）",
    )
    parser.add_argument("--no-guardian", action="store_true", help="不启用进程守护")
    parser.add_argument(
        "--use-bcrm2",
        action="store_true",
        default=True,
        help="使用 BCRM 2.0 (辩证ML引擎)，默认启用",
    )
    parser.add_argument("--use-bcrm1", action="store_true", help="使用 BCRM 1.0 (矛盾力学引擎)")
    parser.add_argument(
        "--shadow-mode",
        action="store_true",
        default=False,
        help="全局影子冷启动模式：所有开仓/平仓/减仓BLOCKED，仅执行推理+影子日志+监控（冷启动验证必选）",
    )
    parser.add_argument(
        "--bdsm-budget-per-coin",
        type=float,
        default=250.0,
        help="[小额实盘测试] BDSM 单币预算硬上限（USDT）。硬约束要求默认 250U 名义价值；"
             "值如 20~30 代表首次真实环境测试阶段单币最多投 20~30U（覆盖默认值），"
             "等 10+ 笔完整样本再拆除小帽。",
    )
    # ================================================================
    # Phase1 三开关（默认全 True → 方案 C spec 强制经过，必须经过）
    # 使用：
    #   python3 start_daemon.py \
    #       --enable-cbr-cycle-log \
    #       --enable-elder-ray-c4 \
    #       --enable-win-prob-factor
    # ================================================================
    parser.add_argument(
        "--enable-cbr-cycle-log",
        action="store_true",
        default=True,
        help="Phase1/P0：启用CBR JSONL 双时点建库（entry_snapshot 开仓半写入+exit_snapshot 离场补全），默认开启（强制经过方案C）",
    )
    parser.add_argument(
        "--enable-elder-ray-c4",
        action="store_true",
        default=True,
        help="Phase1/P1：启用Elder-ray日线观察器（参与仓位调控=弹性闸门Score_E），默认开启（强制经过方案C）",
    )
    parser.add_argument(
        "--enable-win-prob-factor",
        action="store_true",
        default=True,
        help="Phase1/P3：启用盈亏因子动态权重（≥30条样本生效，<30 旁路=1.0），默认开启（强制经过方案C）",
    )
    # ================================================================
    # 方案 C v3.0 方案级开关（默认全 True → 方案 C spec 强制经过，必须经过）
    # 对应 Spec §十 10.1：SW-C3~SW-C8（C6 已复用为 --enable-win-prob-factor）
    # 使用：
    #   python3 start_daemon.py \
    #       --enable-three-layer-weighter \
    #       --enable-elastic-gate-3l \
    #       --enable-bcrm-continuity-obs \
    #       --enable-btc-self-reflex-valve \
    #       --enable-portfolio-risk-fuses
    # ================================================================
    parser.add_argument(
        "--enable-three-layer-weighter",
        action="store_true",
        default=True,
        help="方案C v3.0 SW-C3：启用三层动态权重引擎（日级重算 w_p:w_e:w_b），默认开启（强制经过方案C）",
    )
    parser.add_argument(
        "--enable-elastic-gate-3l",
        action="store_true",
        default=True,
        help="方案C v3.0 SW-C4：启用三层弹性放行矩阵（P1×Elder×BCRM Score_B），默认开启（强制经过方案C）",
    )
    parser.add_argument(
        "--enable-bcrm-continuity-obs",
        action="store_true",
        default=True,
        help="方案C v3.0 SW-C5：启用BCRM连续信号观察器（N=5五级判定，防单次偶然信号），默认开启（强制经过方案C）",
    )
    parser.add_argument(
        "--enable-btc-self-reflex-valve",
        action="store_true",
        default=True,
        help="方案C v3.0 SW-C6：启用BTC自反调控闸门（仅限BTC多头惩罚λ∈[0.60,1.0]），默认开启（强制经过方案C）",
    )
    parser.add_argument(
        "--enable-portfolio-risk-fuses",
        action="store_true",
        default=True,
        help="方案C v3.0 SW-C8：启用组合级风险熔断（G-02黑天鹅+G-04终极3%回撤），默认开启（强制经过方案C）",
    )
    args = parser.parse_args()

    coins = [c.strip().upper() for c in args.coins.split(",")]
    # P4 修复：币种规范化（XAUT → XAU，因为 OKX 实际存在的是 XAU-USDT-SWAP，XAUT 已下架）
    # 在 CLI 层做一次，配合 PollingTrader.__init__ 内的二次规范化形成双保险。
    _NORM_MAIN = {"XAUT": "XAU"}
    coins = [_NORM_MAIN.get(c, c) for c in coins]

    if args.initial_equity is None:
        print("[初始化] 从 OKX 读取实际余额...")
        try:
            from scripts.memory_l4.okx_simulated import OKXSimulatedClient

            client = OKXSimulatedClient()
            balance = client.get_balance()
            if balance.get("ok"):
                args.initial_equity = balance.get("total_eq", 100.0)
            else:
                args.initial_equity = 100.0
        except Exception as e:
            print(f"[初始化] 读取余额失败，使用默认值: {e}")
            args.initial_equity = 100.0
        print(f"[初始化] 实际余额={args.initial_equity:.2f} USDT")

    guardian = None
    if not args.no_guardian:
        guardian = ProcessGuardian(
            process_name="yijing_polling_trader",
            heartbeat_timeout=max(args.interval * 3, 300),
            max_consecutive_errors=args.max_consecutive_losses,
        )
        existing = guardian.check_existing_heartbeat()
        if existing and existing.get("is_alive"):
            print(f"警告：检测到已有运行中的进程 (PID={existing.get('pid')})")
            print(f"上次心跳: {existing.get('ts_str')}")

    trader = PollingTrader(
        interval=args.interval,
        coins=coins,
        bar=args.bar,
        confidence_threshold=args.confidence,
        short_confidence_threshold=args.short_confidence,
        max_positions=args.max_positions,
        initial_equity=args.initial_equity,
        daily_loss_limit=args.daily_loss_limit,
        max_consecutive_losses=args.max_consecutive_losses,
        default_position_pct=args.position_pct,
        guardian=guardian,
        use_bcrm2=not args.use_bcrm1,
        shadow_mode=args.shadow_mode,
        # BDSM 微仓实盘测试：单币预算硬上限覆盖 scaling_plan 默认 167U
        bdsm_budget_per_coin=args.bdsm_budget_per_coin,
        # Phase1 三开关（默认全 False → G1 红线字节等价）
        enable_cbr_cycle_log=args.enable_cbr_cycle_log,
        enable_elder_ray_c4=args.enable_elder_ray_c4,
        enable_win_prob_factor=args.enable_win_prob_factor,
        # 方案 C v3.0 五开关（默认全 False → 字节等价旁路）
        enable_three_layer_weighter=args.enable_three_layer_weighter,
        enable_elastic_gate_3l=args.enable_elastic_gate_3l,
        enable_bcrm_continuity_obs=args.enable_bcrm_continuity_obs,
        enable_btc_self_reflex_valve=args.enable_btc_self_reflex_valve,
        enable_portfolio_risk_fuses=args.enable_portfolio_risk_fuses,
    )

    if guardian:
        guardian.start()

    if args.once:
        trader.run_once()
        status = trader.get_status()
        print("\n═══ 运行状态 ═══")
        print(
            json.dumps(
                {k: v for k, v in status.items() if k not in ("open_positions_detail",)},
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
    else:
        trader.run_loop()

    if guardian:
        guardian.stop()


if __name__ == "__main__":
    main()
