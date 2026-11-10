"""快讯极性 → NEWS 维 — SPEC-D1-MULTIDIM-STATE §2.8（P3-b）。

为什么用快讯而不是文章：文章事后解释（滞后 1-3 天），快讯是事件时点的实时
力量记录。极性口径三源优先级（预注册冻结，不用文章反推）：

  ① od_attention_type   risk_on / policy_easing → +1；risk_off / policy_tightening → -1
  ② 标题+描述多空词典    利好词命中 - 利空词命中，取符号
  ③ od_event_type 先验   仅无歧义类：security_incident → -1；其余歧义类留 0

日度序列：score(day) = Σ w·s / Σ w（w = 重要度 × 24h 半衰期衰减到日末）。
窗口口径（时效对齐）：pre_24h / pre_72h / post_24h / post_72h。

FAIL-OPEN：任何异常返回空结果，不抛。
"""

from __future__ import annotations

import bisect
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("data_center.processing.news_polarity")

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_NEWSFLASH = _REPO / "18-数据获取中心" / "backfill" / "newsflash_history.jsonl"

HALF_LIFE_HOURS = 24.0
IMPORTANT_WEIGHT = 1.5
DAY_SECONDS = 86400

# ── ① 平台注意力标签（仅 DB 33 天有，词典/event_type 之前优先）──
ATTENTION_POLARITY = {
    "market_risk_on": 1,
    "policy_easing": 1,
    "market_risk_off": -1,
    "policy_tightening": -1,
}

# ── ③ 事件类型固定极性（仅无歧义类；歧义类必须留 0，不得猜）──
EVENT_TYPE_POLARITY = {
    "security_incident": -1,
}

# ── ② 多空词典（预注册，中英双语）──────────────────────────
BULLISH_WORDS = (
    "上涨",
    "涨超",
    "涨幅",
    "大涨",
    "飙升",
    "反弹",
    "拉升",
    "突破",
    "新高",
    "创历史新高",
    "创新高",
    "增持",
    "买入",
    "加仓",
    "增仓",
    "净流入",
    "流入",
    "批准",
    "获批",
    "通过",
    "降息",
    "宽松",
    "放水",
    "利好",
    "刺激",
    "回购",
    "销毁",
    "锁仓",
    "减半",
    "质押",
    "上线",
    "首发",
    "合作",
    "接入",
    "采用",
    "接受",
    "支持",
    "推出",
    "恢复",
    "和解",
    "撤销",
    "下调利率",
    "超预期",
    "增长",
    "盈利",
    "融资",
    "资助",
    "投资",
    "看涨",
    "多头",
    "牛市",
    "surge",
    "soar",
    "rally",
    "jump",
    "gain",
    "rise",
    "record high",
    "all-time high",
    "breakout",
    "approve",
    "approval",
    "approved",
    "bullish",
    "inflow",
    "accumulate",
    "upgrade",
    "partnership",
    "adopt",
    "launch",
    "buyback",
    "halving",
    "rate cut",
    "easing",
    "stimulus",
    "beat",
    "outperform",
    "upbeat",
    "positive",
)

BEARISH_WORDS = (
    "下跌",
    "跌超",
    "跌幅",
    "大跌",
    "暴跌",
    "跳水",
    "重挫",
    "崩盘",
    "新低",
    "减持",
    "卖出",
    "减仓",
    "净流出",
    "流出",
    "抛售",
    "砸盘",
    "驳回",
    "拒绝",
    "禁止",
    "封禁",
    "下架",
    "退市",
    "加息",
    "收紧",
    "利空",
    "被盗",
    "黑客",
    "攻击",
    "漏洞",
    "清算",
    "爆仓",
    "解锁",
    "诉讼",
    "起诉",
    "罚款",
    "处罚",
    "破产",
    "跑路",
    "裁员",
    "关闭",
    "暂停",
    "调查",
    "指控",
    "欺诈",
    "违规",
    "低于预期",
    "亏损",
    "下调",
    "降级",
    "警告",
    "风险",
    "看跌",
    "空头",
    "熊市",
    "plunge",
    "crash",
    "slump",
    "drop",
    "fall",
    "tumble",
    "sink",
    "sell-off",
    "selloff",
    "bearish",
    "outflow",
    "sell",
    "dump",
    "downgrade",
    "hack",
    "hacked",
    "exploit",
    "breach",
    "lawsuit",
    "sue",
    "fine",
    "penalty",
    "bankrupt",
    "delist",
    "suspend",
    "halt",
    "ban",
    "reject",
    "rejected",
    "rate hike",
    "tightening",
    "miss",
    "weak",
    "warning",
    "liquidat",
)

# ── 时效窗口（小时，相对文章发布时刻 T）────────────────────
WINDOWS = {
    "pre_24h": (-24, 0),
    "pre_72h": (-72, 0),
    "post_24h": (0, 24),
    "post_72h": (0, 72),
}

# ── P3-b2 词-收益关联校准（SPEC §4.4 / §7 P3-b2）────────────
# 训练窗严格早于 500 篇文章起点（2026-05-30），避免前视与文章反推。
CALIB_CUTOFF = "2026-05-29"
MIN_WORD_N = 30
SHRINK_K = 100.0
_WORD_WEIGHT_CACHE: dict[str, dict] = {}


@dataclass(frozen=True)
class FlashScore:
    ts: int
    sign: int
    important: bool
    source: str
    value: float = 0.0  # 校准后的连续分（朴素口径 = sign）


# ── 极性判定 ───────────────────────────────────────────────


def _count_hits(text: str, words: tuple[str, ...]) -> int:
    return sum(1 for w in words if w in text)


def flash_polarity(rec: Any) -> tuple[int, str]:
    """单条快讯 → (sign ∈ {-1,0,1}, 来源标签)。FAIL-OPEN → (0, "none")。"""
    try:
        if not isinstance(rec, dict):
            return 0, "none"
        att = str(rec.get("od_attention_type") or "")
        if att in ATTENTION_POLARITY:
            return ATTENTION_POLARITY[att], "attention"
        text = f"{rec.get('title') or ''} {rec.get('description') or ''}".lower()
        bull = _count_hits(text, BULLISH_WORDS)
        bear = _count_hits(text, BEARISH_WORDS)
        if bull != bear:
            return (1 if bull > bear else -1), "lexicon"
        et = str(rec.get("od_event_type") or "")
        if et in EVENT_TYPE_POLARITY:
            return EVENT_TYPE_POLARITY[et], "event_prior"
        return 0, "none"
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] flash_polarity 异常 %s: %s", type(e).__name__, str(e)[:120])
        return 0, "none"


# ── 加载（缓存）────────────────────────────────────────────

_FLASH_CACHE: dict[str, tuple[FlashScore, ...]] = {}
_TS_CACHE: dict[str, tuple[int, ...]] = {}


def load_flashes(path: Any = None) -> tuple[FlashScore, ...]:
    """读 newsflash_history.jsonl → 按时间排序的 FlashScore。FAIL-OPEN → ()。"""
    p = str(path or DEFAULT_NEWSFLASH)
    if p in _FLASH_CACHE:
        return _FLASH_CACHE[p]
    out: list[FlashScore] = []
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    ts = int(rec.get("published_ms") or 0) // 1000
                except (TypeError, ValueError):
                    continue
                if ts <= 0:
                    continue
                sign, src = flash_polarity(rec)
                imp = rec.get("is_important")
                out.append(
                    FlashScore(
                        ts=ts,
                        sign=sign,
                        important=bool(imp is True or str(imp).lower() == "true"),
                        source=src,
                    )
                )
        out.sort(key=lambda x: x.ts)
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] load_flashes %s: %s", type(e).__name__, str(e)[:120])
    res = tuple(out)
    _FLASH_CACHE[p] = res
    return res


# ── 窗口聚合 ───────────────────────────────────────────────


def _weighted(flashes: tuple[FlashScore, ...], ref_ts: int) -> tuple[float, float, int, int]:
    """→ (num, den, n_total, n_polar)；权重 = 重要度 × 24h 半衰期衰减。"""
    num = 0.0
    den = 0.0
    n_polar = 0
    for f in flashes:
        hours_before = max(0.0, (ref_ts - f.ts) / 3600.0)
        w = (IMPORTANT_WEIGHT if f.important else 1.0) * (0.5 ** (hours_before / HALF_LIFE_HOURS))
        den += w
        v = f.value if f.value else f.sign
        if v:
            num += w * v
            n_polar += 1
    return num, den, len(flashes), n_polar


def score_window(
    ref_ts: Any, window: str = "pre_72h", *, flashes: Any = None, path: Any = None
) -> dict:
    """文章发布时刻 ref_ts 的窗口聚合。

    → {window, score, n_total, n_polar, coverage}；coverage = 有极性条数 / 总条数。
    """
    out = {"window": window, "score": 0.0, "n_total": 0, "n_polar": 0, "coverage": 0.0}
    try:
        if window not in WINDOWS:
            return out
        t = int(ref_ts)
        start_h, end_h = WINDOWS[window]
        lo = t + start_h * 3600
        hi = t + end_h * 3600
        all_f = flashes if isinstance(flashes, tuple) else load_flashes(path)
        sel = tuple(f for f in all_f if lo < f.ts <= hi)
        num, den, n_total, n_polar = _weighted(sel, hi)
        out.update(
            score=round(num / den, 4) if den else 0.0,
            n_total=n_total,
            n_polar=n_polar,
            coverage=round(n_polar / n_total, 4) if n_total else 0.0,
        )
        return out
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] score_window 异常 %s: %s", type(e).__name__, str(e)[:120])
        return out


def all_window_scores(
    ref_ts: Any, *, path: Any = None, calibrated: bool = False
) -> dict[str, dict]:
    """四个时效窗口一次算完（pre_* 用于一致率，post_* 用于 lead/lag）。

    用 bisect 定位窗口（193k 条 × 500 篇才不会退化成 O(n²)）。
    """
    try:
        flashes = load_calibrated_flashes(path=path) if calibrated else load_flashes(path)
        key = ("calib:" if calibrated else "") + str(path or DEFAULT_NEWSFLASH)
        if key not in _TS_CACHE:
            _TS_CACHE[key] = tuple(f.ts for f in flashes)
        ts_list = _TS_CACHE[key]
        t = int(ref_ts)
        out: dict[str, dict] = {}
        for w, (start_h, end_h) in WINDOWS.items():
            lo = t + start_h * 3600
            hi = t + end_h * 3600
            i = bisect.bisect_right(ts_list, lo)
            j = bisect.bisect_right(ts_list, hi)
            sel = flashes[i:j]
            num, den, n_total, n_polar = _weighted(sel, hi)
            out[w] = {
                "window": w,
                "score": round(num / den, 4) if den else 0.0,
                "n_total": n_total,
                "n_polar": n_polar,
                "coverage": round(n_polar / n_total, 4) if n_total else 0.0,
            }
        return out
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] all_window_scores 异常 %s: %s", type(e).__name__, str(e)[:120])
        return {w: score_window(ref_ts, w, path=path) for w in WINDOWS}


def lead_lag(pre: dict, post: dict, claim_direction: str) -> str:
    """文章相对快讯的时效位置。

    lead        文章方向在 T 之后才被快讯确认（文章领先）
    lag         文章方向在 T 之前快讯已确立（文章滞后复述）
    coincident  两者同时成立
    undetermined 都不成立
    """
    try:
        sign = 1 if claim_direction == "bullish" else -1 if claim_direction == "bearish" else 0
        if sign == 0:
            return "undetermined"
        pre_hit = pre["score"] * sign >= 0.05
        post_hit = post["score"] * sign >= 0.05
        if pre_hit and post_hit:
            return "coincident"
        if post_hit:
            return "lead"
        if pre_hit:
            return "lag"
        return "undetermined"
    except Exception:  # noqa: BLE003  FAIL-OPEN
        return "undetermined"


# ── 日度序列（供 DimensionContext）─────────────────────────


def daily_news_series(
    *, path: Any = None, calibrated: bool = False, kline_db: Any = None
) -> tuple[tuple[str, float], ...]:
    """UTC 日 → 当日 score ∈ [-1,1]（calibrated=True 时为校准连续分）。FAIL-OPEN → ()。"""
    try:
        flashes = (
            load_calibrated_flashes(path=path, kline_db=kline_db)
            if calibrated
            else load_flashes(path)
        )
        if not flashes:
            return ()
        buckets: dict[str, list[FlashScore]] = {}
        for f in flashes:
            d = datetime.fromtimestamp(f.ts, tz=timezone.utc).strftime("%Y-%m-%d")
            buckets.setdefault(d, []).append(f)
        out: list[tuple[str, float]] = []
        for d in sorted(buckets):
            day_end = int(
                (
                    datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    + timedelta(days=1)
                ).timestamp()
            )
            num, den, _, _ = _weighted(tuple(buckets[d]), day_end)
            out.append((d, round(num / den, 6) if den else 0.0))
        return tuple(out)
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] daily_news_series 异常 %s: %s", type(e).__name__, str(e)[:120])
        return ()


# ── 辅助强度特征：快讯密度（SPEC §4.4 P3-b2 裁决保留）───────
# 唯一残留的弱信号：当日快讯条数与次日 |return| 相关 +0.092（重要快讯 +0.081）。
# 无方向、不进主判据，只作 NEWS 维的强度辅助。


def news_density(ref_ts: Any, *, path: Any = None) -> dict:
    """ref_ts 所在 UTC 日的快讯密度 → {date, n_total, n_important}。

    FAIL-OPEN → 全 0。
    """
    out = {"date": "", "n_total": 0, "n_important": 0}
    try:
        t = int(ref_ts)
        day = datetime.fromtimestamp(t, tz=timezone.utc)
        day_start = int(day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        day_end = day_start + DAY_SECONDS
        flashes = load_flashes(path)
        key = str(path or DEFAULT_NEWSFLASH)
        if key not in _TS_CACHE:
            _TS_CACHE[key] = tuple(f.ts for f in flashes)
        ts_list = _TS_CACHE[key]
        i = bisect.bisect_left(ts_list, day_start)
        j = bisect.bisect_left(ts_list, day_end)
        sel = flashes[i:j]
        out.update(
            date=day.strftime("%Y-%m-%d"),
            n_total=len(sel),
            n_important=sum(1 for f in sel if f.important),
        )
        return out
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] news_density 异常 %s: %s", type(e).__name__, str(e)[:120])
        return out


# ── P3-b2 词-收益关联校准（SPEC §2.8 / §7 P3-b2）─────────────
# 朴素词典的多头偏置（bull_share 76.8%）来自"词表本身偏多"，而非市场真实力量。
# 校准做法：用训练窗内每条快讯之后的 BTC 次日收益作为标签，学习每个词的
# 标准化效应量（已减去 μ0，天然去掉基准率），再做收缩。

ALL_LEXICON_WORDS = BULLISH_WORDS + BEARISH_WORDS


def _iter_flash_texts(path: Any = None):
    """流式产出 (ts, text, is_important)。FAIL-OPEN → 无产出。"""
    p = Path(path or DEFAULT_NEWSFLASH)
    try:
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    ts = int(rec.get("published_ms") or 0) // 1000
                except (TypeError, ValueError):
                    continue
                if ts <= 0:
                    continue
                text = f"{rec.get('title') or ''} {rec.get('description') or ''}".lower()
                flag = rec.get("is_important")
                imp = flag is True or str(flag).lower() == "true"
                yield ts, text, imp
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] _iter_flash_texts 异常 %s: %s", type(e).__name__, str(e)[:120])


def _btc_next_day_returns(kline_db: Any = None) -> dict[str, float]:
    """date → 次日收益（close_{t+1}/close_t - 1）。FAIL-OPEN → {}。"""
    try:
        from data_center.processing.dimension_context import DEFAULT_KLINE_DB, _load_kline

        kline = _load_kline(kline_db or DEFAULT_KLINE_DB)
        out: dict[str, float] = {}
        for i in range(len(kline) - 1):
            d, c = kline[i]
            c2 = kline[i + 1][1]
            if c and c > 0:
                out[str(d)[:10]] = c2 / c - 1.0
        return out
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning(
            "[FAIL-OPEN] _btc_next_day_returns 异常 %s: %s", type(e).__name__, str(e)[:120]
        )
        return {}


def learn_word_weights(
    *,
    path: Any = None,
    kline_db: Any = None,
    cutoff: str = CALIB_CUTOFF,
    min_n: int = MIN_WORD_N,
    shrink: float = SHRINK_K,
) -> dict:
    """训练窗内学习词 → 次日收益的标准化效应量（收缩后）。

    → {weights, mu0, sd, n_train, trained_until, usable}
    usable=False 表示训练样本不足或收益序列缺失，调用方应回落到朴素口径。
    """
    key = f"{path or DEFAULT_NEWSFLASH}|{kline_db}|{cutoff}"
    if key in _WORD_WEIGHT_CACHE:
        return _WORD_WEIGHT_CACHE[key]

    empty = {
        "weights": {},
        "mu0": 0.0,
        "sd": 0.0,
        "n_train": 0,
        "trained_until": cutoff,
        "usable": False,
    }
    try:
        rets = _btc_next_day_returns(kline_db)
        if not rets:
            return empty
        cutoff_ts = (
            int(datetime.strptime(cutoff, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
            + 86399
        )
        sums = dict.fromkeys(ALL_LEXICON_WORDS, 0.0)
        counts = dict.fromkeys(ALL_LEXICON_WORDS, 0)
        vals: list[float] = []
        for ts, text, _imp in _iter_flash_texts(path):
            if ts > cutoff_ts:
                continue
            d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            r = rets.get(d)
            if r is None:
                continue
            vals.append(r)
            for w in ALL_LEXICON_WORDS:
                if w in text:
                    sums[w] += r
                    counts[w] += 1
        if len(vals) < 100:
            return empty
        mu0 = sum(vals) / len(vals)
        var = sum((v - mu0) ** 2 for v in vals) / len(vals)
        sd = math.sqrt(var) if var > 0 else 0.0
        if sd <= 0:
            return empty
        weights = {
            w: ((sums[w] / counts[w]) - mu0) / sd * counts[w] / (counts[w] + shrink)
            for w in ALL_LEXICON_WORDS
            if counts[w] >= min_n
        }
        res = {
            "weights": weights,
            "mu0": round(mu0, 6),
            "sd": round(sd, 6),
            "n_train": len(vals),
            "trained_until": cutoff,
            "usable": bool(weights),
        }
        _WORD_WEIGHT_CACHE[key] = res
        return res
    except Exception as e:  # noqa: BLE003  FAIL-OPEN
        logger.warning("[FAIL-OPEN] learn_word_weights 异常 %s: %s", type(e).__name__, str(e)[:120])
        return empty


def calibrated_flash_score(text: Any, weights: dict) -> float:
    """快讯文本 → 校准分（命中词权重之和）。FAIL-OPEN → 0.0。"""
    try:
        if not isinstance(text, str) or not weights:
            return 0.0
        low = text.lower()
        return sum(v for w, v in weights.items() if w in low)
    except Exception:  # noqa: BLE003  FAIL-OPEN
        return 0.0


def load_calibrated_flashes(
    *, path: Any = None, kline_db: Any = None, cutoff: str = CALIB_CUTOFF
) -> tuple[FlashScore, ...]:
    """校准口径快讯序列（两遍：先学权重再打分）。不可用时回落朴素口径。"""
    p = str(path or DEFAULT_NEWSFLASH)
    key = f"calib:{p}|{kline_db}|{cutoff}"
    if key in _FLASH_CACHE:
        return _FLASH_CACHE[key]
    info = learn_word_weights(path=path, kline_db=kline_db, cutoff=cutoff)
    if not info["usable"]:
        res = load_flashes(path)
        _FLASH_CACHE[key] = res
        return res
    weights = info["weights"]
    out: list[FlashScore] = []
    for ts, text, imp in _iter_flash_texts(path):
        score = calibrated_flash_score(text, weights)
        sign = 1 if score > 0 else -1 if score < 0 else 0
        out.append(FlashScore(ts=ts, sign=sign, important=imp, source="calibrated", value=score))
    out.sort(key=lambda x: x.ts)
    res = tuple(out)
    _FLASH_CACHE[key] = res
    _TS_CACHE[key] = tuple(f.ts for f in res)
    return res
