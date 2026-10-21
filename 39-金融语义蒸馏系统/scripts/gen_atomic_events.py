# -*- coding: utf-8 -*-
"""39-金融语义蒸馏系统 · P1a 原子事件采集（SPEC §8.1 原子层，零 token）

从 18-数据获取中心数据库采集数据值变化事件（变化驱动模式：
越线/转正负/显著变动才记录，非全量取值记录，控制数据量）。

产出: atomic_events.jsonl（持续追加流，供 P1b 聚合层与 P3 复杂语义消费）

运行模式:
  --backfill  回填模式：扫描历史 records，生成历史原子事件
  --live      增量模式：只处理上次运行后的新增记录

变化检测规则（按数据类别）:
  - crypto_fear_greed / fear_greed_enhanced: 恐惧贪婪指数越过 25/50/75 分界线
  - funding_rate: 资金费率转正/转负
  - long_short_ratio: 多空比越过 1.0 平衡线 ±10%
  - tether_current / usdc_current: 稳定币市值日环比变动 >1%
  - social_volume: 社交量较前值变动 >30%
  - 其他类别: 数值型指标较前值变动 >5%（通用规则）
"""
import argparse
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SYS_DIR = os.path.dirname(_THIS_DIR)
sys.path.insert(0, _THIS_DIR)
import dc_pg  # PostgreSQL 辅助模块（38 方案4 迁移后替代 SQLite）
OUT_PATH = os.path.join(_SYS_DIR, "atomic_events.jsonl")
STATE_PATH = os.path.join(_SYS_DIR, ".atomic_events_state.json")

# 分界线配置（越线检测）
THRESHOLDS = {
    "crypto_fear_greed": [25.0, 50.0, 75.0],
    "fear_greed_enhanced": [25.0, 50.0, 75.0],
}
# 转正负检测
SIGN_FLIP = {"funding_rate"}
# 平衡线检测（多空比 1.0±10%）
BALANCE_LINE = {"long_short_ratio": (1.0, 0.1)}
# 显著变动检测（相对前值）
BIG_MOVE = {"tether_current": 0.01, "usdc_current": 0.01, "social_volume": 0.30}
GENERIC_MOVE = 0.05  # 通用规则：变动 >5%

# ── 五维量变扩展（SPEC v1.4 §9.8 第一批）──────────────────
# 量维：交易量/持仓量类数据的显著变化（放量/缩量，阈值 10%）
VOLUME_CATEGORIES = {"btc_basics", "btc_onchain", "btc_metrics", "options", "stablecoins_top_10"}
VOLUME_MOVE = 0.10
# 情维：恐惧贪婪极值区间（<25 极度恐慌 / >75 极度贪婪）持续检测
EXTREME_LOW, EXTREME_HIGH = 25.0, 75.0
# 极值持续状态缓存 {category.metric: (极值方向, 进入时间, 持续采样数)}
_extreme_state = {}


def _load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_record_id": 0}


def _save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def _zone(value, thresholds):
    """返回值所在区间编号（用于越线检测）。"""
    zone = 0
    for t in thresholds:
        if value >= t:
            zone += 1
    return zone


def _extract_metrics(metrics_json):
    """从 metrics 提取数值型指标 {key: value}。

    PostgreSQL jsonb 经 psycopg2 查询后已是 dict；兼容旧的 JSON 字符串输入。
    """
    if isinstance(metrics_json, dict):
        data = metrics_json
    else:
        try:
            data = json.loads(metrics_json) if metrics_json else {}
        except Exception:
            return {}
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = float(v)
    return out


def scan(start_id=0):
    """从指定 id 扫描 records（PostgreSQL），生成原子事件。"""
    events = []
    last_id = start_id
    # 每类数据的上一状态缓存 {category: {key: (value, zone/sign)}}
    prev_state = {}
    # PostgreSQL 增量查询（全 sub_category，按 id 升序）
    rows = dc_pg.fetch_records_since("%", start_id, limit=50000)
    for row in rows:
        rid = row["id"]
        sub_cat = row["sub_category"]
        ts = row["timestamp"]
        last_id = rid
        vals = _extract_metrics(row["metrics"])
        if not vals:
            continue
        cat_state = prev_state.setdefault(sub_cat, {})
        for key, value in vals.items():
            pk = f"{sub_cat}.{key}"
            old = cat_state.get(key)
            reasons = []
            # 1) 越线检测
            if sub_cat in THRESHOLDS:
                z_new = _zone(value, THRESHOLDS[sub_cat])
                z_old = _zone(old, THRESHOLDS[sub_cat]) if old is not None else z_new
                if z_new != z_old:
                    reasons.append(f"zone_shift:{z_old}->{z_new}")
            # 2) 转正负检测
            if sub_cat in SIGN_FLIP and old is not None:
                if old != 0 and value != 0 and (old > 0) != (value > 0):
                    reasons.append("sign_flip")
            # 3) 平衡线检测
            if sub_cat in BALANCE_LINE and old is not None:
                center, band = BALANCE_LINE[sub_cat]
                in_now = abs(value - center) > band * center
                in_old = abs(old - center) > band * center
                if in_now != in_old:
                    reasons.append("balance_break" if in_now else "balance_return")
            # 4) 显著变动检测
            if old is not None and old != 0:
                move_ratio = abs(value - old) / abs(old)
                threshold = BIG_MOVE.get(sub_cat, GENERIC_MOVE)
                if move_ratio >= threshold:
                    reasons.append(f"big_move:{move_ratio:.1%}")
            # 5) 量维：交易量/持仓量类显著变化（放量/缩量，SPEC §9.8 第一批）
            if sub_cat in VOLUME_CATEGORIES and old is not None and old != 0:
                vol_move = (value - old) / abs(old)
                if abs(vol_move) >= VOLUME_MOVE:
                    reasons.append(f"volume_surge:+{vol_move:.1%}" if vol_move > 0 else f"volume_shrink:{vol_move:.1%}")
            # 6) 情维：恐惧贪婪极值区间持续检测（SPEC §9.8 第一批）
            if sub_cat in THRESHOLDS and 0 <= value <= 100:
                ek = f"{sub_cat}.{key}"
                if value < EXTREME_LOW:
                    direction = "extreme_fear"
                elif value > EXTREME_HIGH:
                    direction = "extreme_greed"
                else:
                    direction = None
                prev = _extreme_state.get(ek)
                if direction is not None:
                    if prev and prev[0] == direction:
                        _extreme_state[ek] = (direction, prev[1], prev[2] + 1)
                        if _extreme_state[ek][2] >= 2:  # 连续 2 个采样以上记录持续事件
                            reasons.append(f"extreme_persist:{direction}:n={_extreme_state[ek][2]}")
                    else:
                        _extreme_state[ek] = (direction, ts, 1)
                        reasons.append(f"extreme_enter:{direction}")
                elif prev:
                    reasons.append(f"extreme_exit:{prev[0]}:lasted={prev[2]}")
                    _extreme_state.pop(ek, None)
            cat_state[key] = value
            if reasons:
                events.append({
                    "layer": "atomic",
                    "category": sub_cat,
                    "metric": key,
                    "timestamp": ts,
                    "value": value,
                    "prev_value": old,
                    "reasons": reasons,
                    "source": "data_center_pg",
                })
    return events, last_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    if args.backfill:
        start = 0
    elif args.live:
        start = _load_state().get("last_record_id", 0)
    else:
        parser.error("需指定 --backfill 或 --live")

    events, last_id = scan(start)
    if events:
        with open(OUT_PATH, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    _save_state({"last_record_id": last_id})

    print(f"[OK] 模式={'backfill' if args.backfill else 'live'} "
          f"扫描至 id={last_id}, 产出 {len(events)} 条原子事件 → {OUT_PATH}")
    if events:
        by_cat = {}
        for e in events:
            by_cat[e["category"]] = by_cat.get(e["category"], 0) + 1
        for c, n in sorted(by_cat.items(), key=lambda kv: -kv[1])[:8]:
            print(f"     {c}: {n} 条")


if __name__ == "__main__":
    main()
