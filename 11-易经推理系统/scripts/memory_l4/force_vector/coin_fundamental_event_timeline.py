"""事件时间线真实查询 — EventTimeline (F2)。

从 data_center.db records 表查 odaily newsflash 记录，
提取目标代币的里程碑事件（mainnet_launch / upgrade / partnership），
按发布时间判断 pending（<7天，预期未落地）/ landed（>=7天，已落地），
供阶段识别器 phase_classifier 使用。

数据源：odaily newsflash（source=odaily_newsflash, category=news,
  sub_category=newsflash_{id}）
  - metrics.od_event_type      = "token_milestone"（9 大类中的代币里程碑）
  - metrics.od_tickers_hit_csl = "CRCL,UNI"（逗号分隔的命中代币）
  - events[0].published_ms      = 发布时间戳（毫秒）
  - raw.title                  = 快讯标题（用于细分事件类型）

FAIL-OPEN：任何异常（db 不存在/表缺失/JSON 畸形/数据不足）→ 返回空 list，
不阻塞阶段识别（phase_classifier 收到空 list 走默认规则）。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from typing import Any, Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# data_center.db 默认路径：dreambuddy-v2/18-数据获取中心/data_center.db
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
DEFAULT_DB_PATH = os.path.join(_REPO, "18-数据获取中心", "data_center.db")

# 7 天阈值（毫秒）：<7天 → pending（预期未落地），>=7天 → landed（已落地）
_SEVEN_DAYS_MS = 7 * 24 * 3600 * 1000

# ===========================================================================
# 关键词映射：从标题细分 token_milestone 子类型
# ===========================================================================
# 注意：mainnet_launch 关键词必须用精确词组（如"主网上线"），不能包含单独的
# "主网"，否则"主网升级"会被误判为 mainnet_launch。
_MAINNET_LAUNCH_KEYWORDS: List[str] = [
    "主网上线", "上线主网", "主网启动", "主网迁移", "跨链迁移",
    "主网公测", "发布主网", "主网 beta", "主网beta", "主网正式上线",
    "主网公测", "主网启动",
]
_UPGRADE_KEYWORDS: List[str] = [
    "主网升级", "版本升级", "协议升级", "升级", "主链升级",
]
_PARTNERSHIP_KEYWORDS: List[str] = [
    "战略合作", "生态合作", "集成至", "合作发布", "合作",
    "伙伴关系", "集成", "生态基金",
]


# ===========================================================================
# 纯函数：事件类型细分
# ===========================================================================

def _classify_event_type_from_title(title: str) -> str:
    """从快讯标题关键词细分事件类型。

    优先级顺序：mainnet_launch → upgrade → partnership → unknown
      - mainnet_launch 用精确词组匹配（"主网上线"/"上线主网"等），
        不含单独"主网"以避免与"主网升级"冲突。
      - upgrade 匹配"升级"类关键词（"主网升级"/"版本升级"/"升级"）。
      - partnership 匹配"合作"/"集成"类关键词。
      - 无匹配 → "unknown"（调用方过滤掉）。

    边界用例：
      "AAVE 主网升级完成" → upgrade（含"主网升级"，不含"主网上线"）
      "CRCL 主网上线在即" → mainnet_launch（含"主网上线"）
      "CRCL 上线主网"     → mainnet_launch（含"上线主网"）
    """
    if not title or not isinstance(title, str):
        return "unknown"
    # 优先级 1：主网上线（精确词组）
    for kw in _MAINNET_LAUNCH_KEYWORDS:
        if kw in title:
            return "mainnet_launch"
    # 优先级 2：升级
    for kw in _UPGRADE_KEYWORDS:
        if kw in title:
            return "upgrade"
    # 优先级 3：合作/集成
    for kw in _PARTNERSHIP_KEYWORDS:
        if kw in title:
            return "partnership"
    return "unknown"


# ===========================================================================
# 纯函数：状态判断（pending/landed）
# ===========================================================================

def _compute_status_from_age(published_ms: int, now_ms: Optional[int] = None) -> str:
    """根据发布时间距今判断事件状态。

    规则：
      - published_ms <= 0（缺失/无效）→ pending（保守，不丢事件）
      - 距今 < 0（未来时间）→ pending（保守，可能是时区或时钟偏差）
      - 距今 < 7天 → pending（预期未落地，仍在发酵期）
      - 距今 >= 7天 → landed（已落地，进入盈收验证期）
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    try:
        published_ms = int(published_ms or 0)
    except (TypeError, ValueError):
        return "pending"
    if published_ms <= 0:
        return "pending"
    age_ms = now_ms - published_ms
    if age_ms < 0:
        # 未来时间（时钟偏差/时区）→ 保守 pending
        return "pending"
    if age_ms >= _SEVEN_DAYS_MS:
        return "landed"
    return "pending"


# ===========================================================================
# 辅助：安全 JSON 解析（兼容双重编码）
# ===========================================================================

def _safe_json_loads(s: Any, default: Any) -> Any:
    """安全解析 JSON 字符串，兼容双重编码。

    场景：某些测试或异常写入可能产生双重编码（json.dumps 对已是字符串的值再编码）。
    处理：
      1. 非 str → 返回 default
      2. 第一次 json.loads 失败 → 返回 default
      3. 第一次解析得到 str → 尝试第二次解析（双重编码场景）
      4. 第二次失败 → 返回 default
    """
    if not isinstance(s, str) or not s:
        return default
    try:
        v = json.loads(s)
    except Exception:
        return default
    # 双重编码：第一次解析得到字符串，尝试再解析
    if isinstance(v, str):
        try:
            v2 = json.loads(v)
            return v2
        except Exception:
            return default
    return v


# ===========================================================================
# DB 查询：事件时间线
# ===========================================================================

def query_event_timeline(coin: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """从 data_center.db 查询指定代币的里程碑事件时间线。

    流程：
      1. 查 records 表 source='odaily_newsflash' AND category='news'
      2. 过滤 metrics.od_event_type == 'token_milestone'
      3. 过滤 metrics.od_tickers_hit_csl 包含目标 coin（逗号分隔，大小写不敏感）
      4. 从 raw.title 细分事件类型（mainnet_launch/upgrade/partnership）
      5. 过滤掉 type='unknown'（无匹配关键词）
      6. 从 events[0].published_ms 或 raw.publishTimestamp 获取发布时间
      7. 调用 _compute_status_from_age 判断 pending/landed
      8. 按 published_ms 倒序排序（最新在前）

    返回格式：
      [
        {"type": "mainnet_launch", "status": "pending", "published_ms": 123, "title": "..."},
        ...
      ]

    FAIL-OPEN：任何异常（db 不存在/表缺失/JSON 畸形/数据不足）→ 返回空 list，
    phase_classifier 收到空 list 走默认规则，不阻塞主信号。
    """
    try:
        coin_up = (coin or "").strip().upper()
        if not coin_up:
            return []

        if not db_path:
            db_path = DEFAULT_DB_PATH
        if not os.path.exists(db_path):
            return []

        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT metrics, events, raw FROM records "
                "WHERE source='odaily_newsflash' AND category='news'"
            )
            rows = cursor.fetchall()
        finally:
            conn.close()

        now_ms = int(time.time() * 1000)
        events_out: List[Dict[str, Any]] = []

        for metrics_str, events_str, raw_str in rows:
            # 解析 metrics（兼容双重编码）
            metrics = _safe_json_loads(metrics_str, {})
            if not isinstance(metrics, dict):
                metrics = {}

            # 过滤：od_event_type 必须是 token_milestone
            evt_type_raw = str(metrics.get("od_event_type", "") or "")
            if evt_type_raw != "token_milestone":
                continue

            # 过滤：od_tickers_hit_csl 必须包含目标 coin
            tickers_csl = str(metrics.get("od_tickers_hit_csl", "") or "")
            tickers = [
                t.strip().upper()
                for t in tickers_csl.split(",")
                if t and t.strip()
            ]
            if coin_up not in tickers:
                continue

            # 解析 raw 获取 title
            raw = _safe_json_loads(raw_str, {})
            if not isinstance(raw, dict):
                raw = {}
            title = str(raw.get("title", "") or "")

            # 细分事件类型
            sub_type = _classify_event_type_from_title(title)
            if sub_type == "unknown":
                continue

            # 解析 events 获取 published_ms（兼容畸形/双重编码）
            published_ms = 0
            evs = _safe_json_loads(events_str, [])
            if isinstance(evs, list) and evs and isinstance(evs[0], dict):
                try:
                    published_ms = int(evs[0].get("published_ms", 0) or 0)
                except (TypeError, ValueError):
                    published_ms = 0
            # 回退：从 raw.publishTimestamp 获取
            if published_ms <= 0 and isinstance(raw, dict):
                try:
                    published_ms = int(raw.get("publishTimestamp", 0) or 0)
                except (TypeError, ValueError):
                    published_ms = 0

            status = _compute_status_from_age(published_ms, now_ms)
            events_out.append({
                "type": sub_type,
                "status": status,
                "published_ms": published_ms,
                "title": title,
            })

        # 按时间倒序排序（最新在前）
        events_out.sort(key=lambda e: e.get("published_ms", 0), reverse=True)
        return events_out
    except Exception:
        # FAIL-OPEN：任何异常 → 空 list，不阻塞阶段识别
        return []
