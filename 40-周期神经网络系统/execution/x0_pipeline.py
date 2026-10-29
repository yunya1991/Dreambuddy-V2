#!/usr/bin/env python3
"""X0 执行层骨架：信号接收 + 白名单过滤 + 风控检查 + 意图流落盘（不下单）。

SPEC: docs/SPEC_execution_layer.md v0.2 第六章 X0
- 通过标准：意图流全量落盘 >= 2 周
- 信号源：real（40 主链路产出物）/ proxy（12 系统信号池），config.json 切换，零代码改动
- 红线：X0 不下单；代理信号仅验证管道，不出具任何验证指标
- fail-open：本脚本任何异常不影响 40 主链路产出
"""
import json
import os
import sys
import traceback
from datetime import datetime, timezone, date

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
CONFIG_PATH = os.path.join(BASE, "config.json")
ALERT_MODULE_DIR = "/home/luke/dreambuddy/15-监控告警系统"  # 15 系统统一飞书告警模块


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def load_config():
    cfg = load_json(CONFIG_PATH)
    limits = cfg["risk_limits"]
    if limits.get("frozen"):
        # 预注册冻结校验：与 SPEC 第三章终审值一致，运行时禁止放宽
        expected = {
            "max_notional_per_order": 100,
            "max_total_notional": 300,
            "max_daily_loss": 50,
            "max_concurrent_positions": 3,
        }
        for k, v in expected.items():
            if limits.get(k) != v:
                raise ValueError(f"风控红线 {k}={limits.get(k)} 与预注册冻结值 {v} 不符，禁止运行")
    return cfg


def receive_real_signal(cfg):
    """真实信号源：读 40 主链路产出物，生成验证交易意图。"""
    paths = cfg["signal_sources"]["real"]["paths"]
    cycle = load_json(paths["cycle_state"])
    rotation = load_json(paths["asset_rotation"])
    snapshot = {
        "source": "40_main",
        "cycle_state": cycle,
        "asset_rotation": rotation,
    }
    ta = cycle.get("technical_anchor", {}).get("assets", {})
    quadrant = rotation.get("merrill_clock", {}).get("quadrant")
    quadrant_conf = rotation.get("merrill_clock", {}).get("confidence")
    intents = []
    for symbol in cfg["whitelist"]:
        a = ta.get(symbol)
        if not a:
            continue
        # 方向判别：MA200 锚点 above/below（日线级别）
        direction = "UP" if a.get("above") else "DOWN"
        conf = 0.6 if quadrant_conf == "high" else (0.5 if quadrant_conf == "medium" else 0.4)
        intents.append({
            "symbol": symbol,
            "direction": direction,
            "confidence": conf,
            "timeframe": "1d",
            "holding_period_days": cfg["holding_period_days"],
            "notional_usdt": cfg["intent_notional_usdt"],
            "leverage": cfg["leverage"],
        })
    return snapshot, intents


def receive_proxy_signal(cfg):
    """代理信号源：12 系统信号池，仅验证管道（不出验证指标）。"""
    path = cfg["signal_sources"]["proxy"]["path"]
    pool = load_json(path)
    snapshot = {"source": "12_proxy", "pool": pool}
    intents = []
    for symbol in cfg["whitelist"]:
        base = symbol.split("/")[0]
        entry = pool.get(base, {}).get("4h", {})
        sig = entry.get("signal", "HOLD")
        direction = {"BUY": "UP", "SELL": "DOWN"}.get(sig, "NEUTRAL")
        intents.append({
            "symbol": symbol,
            "direction": direction,
            "confidence": entry.get("confidence", 0),
            "timeframe": "4h",
            "holding_period_days": cfg["holding_period_days"],
            "notional_usdt": cfg["intent_notional_usdt"],
            "leverage": cfg["leverage"],
        })
    return snapshot, intents


def whitelist_filter(intents, cfg):
    wl = set(cfg["whitelist"])
    return [i for i in intents if i["symbol"] in wl]


def notify_violation(violation, violations_path):
    """15 系统告警通知（SPEC 第七章接口：风控红线违规通知）。fail-open：推送失败仅记录，不阻断主流程。"""
    try:
        if ALERT_MODULE_DIR not in sys.path:
            sys.path.insert(0, ALERT_MODULE_DIR)
        from feishu_alert import send_alert
        send_alert(
            "trading", "warning",
            "40执行层风控红线违规: " + str(violation.get("symbol")),
            {"reasons": violation.get("reasons"), "ts": violation.get("ts")},
            system="40_execution_layer",
        )
    except Exception as e:
        append_jsonl(violations_path, {"ts": now_iso(), "type": "alert_failed", "error": str(e), "violation": violation})


def risk_check(intents, cfg, state, violations_path):
    """风控红线检查：X0 无持仓，检查单笔上限/白名单/杠杆；violation 落盘。"""
    limits = cfg["risk_limits"]
    passed = []
    for i in intents:
        reasons = []
        if i["notional_usdt"] > limits["max_notional_per_order"]:
            reasons.append(f"单笔名义 {i['notional_usdt']} > 上限 {limits['max_notional_per_order']}")
        if i["leverage"] != "1x":
            reasons.append(f"杠杆 {i['leverage']} 违规（禁用杠杆）")
        if i["symbol"] not in cfg["whitelist"]:
            reasons.append(f"{i['symbol']} 不在白名单")
        if reasons:
            violation = {
                "ts": now_iso(), "type": "risk_limit", "symbol": i["symbol"],
                "reasons": reasons, "intent": i,
            }
            append_jsonl(violations_path, violation)
            notify_violation(violation, violations_path)
        else:
            passed.append(i)
    return passed


def existing_intent_keys(trades_path):
    keys = set()
    if not os.path.exists(trades_path):
        return keys
    with open(trades_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                keys.add((r.get("intent_date"), r.get("symbol"), (r.get("signal_snapshot") or {}).get("source")))
            except json.JSONDecodeError:
                continue
    return keys


def main():
    cfg = load_config()
    out_dir = ROOT
    trades_path = os.path.join(out_dir, cfg["output"]["trades"])
    violations_path = os.path.join(out_dir, cfg["output"]["violations"])
    state_path = os.path.join(out_dir, cfg["output"]["state"])

    src = cfg["signal_source"]
    if src == "real":
        snapshot, intents = receive_real_signal(cfg)
    elif src == "proxy":
        snapshot, intents = receive_proxy_signal(cfg)
    else:
        raise ValueError(f"未知信号源 {src}（仅支持 real/proxy 配置切换）")

    intents = whitelist_filter(intents, cfg)
    intents = risk_check(intents, cfg, None, violations_path)

    today = date.today().isoformat()
    seen = existing_intent_keys(trades_path)
    written = 0
    for i in intents:
        key = (today, i["symbol"], snapshot["source"])
        if key in seen:
            continue
        record = {
            "ts": now_iso(),
            "intent_date": today,
            "symbol": i["symbol"],
            "signal_snapshot": snapshot,
            "intent": i,
            "fill": None,
            "exit": None,
            "pnl": None,
            "validation_tag": None,
            "stage": "X0",
            "order_placed": False,
        }
        append_jsonl(trades_path, record)
        written += 1

    state = {
        "updated_at": now_iso(),
        "stage": "X0", "signal_source": src,
        "intents_today": len(intents), "written_today": written,
        "trades_path": trades_path,
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # fail-open：执行层故障不影响 40 主链路，仅记录错误
        err_path = os.path.join(ROOT, "execution_errors.jsonl")
        append_jsonl(err_path, {"ts": now_iso(), "error": traceback.format_exc()})
        print(f"X0 pipeline failed (fail-open, 40 主链路不受影响), see {err_path}", file=sys.stderr)
        sys.exit(1)
