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
from datetime import date, datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
CONFIG_PATH = os.path.join(BASE, "config.json")
# R-42-04/P1-03：DREAMBUDDY_ROOT 环境变量统一模块根路径；未设置时按 __file__ 推导（仓库内模块同级布局）
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(ROOT)
ALERT_MODULE_DIR = os.path.join(_DREAMBUDDY_ROOT, "15-监控告警系统")  # 15 系统统一飞书告警模块


def _resolve_cfg_paths(cfg):
    """config.json 中的信号源路径支持相对 DREAMBUDDY_ROOT（R-42-04/P1-03）；相对路径就地展开为绝对路径。"""
    for src in (cfg.get("signal_sources") or {}).values():
        paths = src.get("paths")
        if paths:
            for k, v in paths.items():
                if v and not os.path.isabs(v):
                    paths[k] = os.path.join(_DREAMBUDDY_ROOT, v)
        p = src.get("path")
        if p and not os.path.isabs(p):
            src["path"] = os.path.join(_DREAMBUDDY_ROOT, p)
    return cfg


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    """解析 ISO-8601（容忍 Z 结尾）；失败返回 None。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _base_asset(symbol):
    """标的归一化：BTC/USDT、BTC-USDT-SWAP → BTC。

    无法识别后缀的复合符号（如 50 的 BTC-PROFILE-DEFAULT / BTC-REGIME-TREND 等
    非交易载荷键）返回 None，避免把调试/诊断条目当作真实决策回写（DEC-BCL-06 路径 B）。
    """
    s = str(symbol or "").upper().replace("/", "-")
    for suffix in ("-USDT-SWAP", "-USDT-PERP", "-USDT", "-SWAP", "-PERP"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    else:
        if "-" in s:
            return None
    return s.split("-")[0] or None


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def append_jsonl(path, obj):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def load_decision_index(cfg):
    """读取 50 决策流，按 base asset 建索引（同标的多条取最新）。

    DEC-BCL-06 路径 B：40 执行记录回写来源决策的 decision_id。
    只做映射不做推断：过期、符号不可解析、无 signal_id 的决策一律不入索引；
    读取失败 fail-open 返回空表（记录 decision_id=null，不伪造）。
    """
    src = cfg.get("decision_source") or {}
    path = src.get("path")
    if not path:
        return {}
    if not os.path.isabs(path):
        path = os.path.join(_DREAMBUDDY_ROOT, path)
    if not os.path.exists(path):
        return {}
    max_age = float(src.get("max_age_hours") or 24)
    now = datetime.now(timezone.utc)
    index = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                did = d.get("signal_id") or d.get("decision_id")
                base = _base_asset(d.get("symbol"))
                ts = _parse_iso(d.get("ts"))
                if not did or not base or ts is None:
                    continue
                if (now - ts).total_seconds() > max_age * 3600:
                    continue
                prev = index.get(base)
                if prev is None or ts > prev["ts"]:
                    index[base] = {"ts": ts, "decision_id": did, "mode": d.get("mode")}
    except OSError:
        return {}
    return index


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
    return _resolve_cfg_paths(cfg)


def paper_universe(cfg):
    """纸面验证场标的（DEC-BCL-07）：从 40/asset_classes.VALIDATION_UNIVERSE 派生。

    40 只产出意图（X0），成交由 22 执行层产生。纸面验证场覆盖多板块龙头，
    与 X2 实盘白名单互不影响——扩标不放松实盘门禁。
    """
    try:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from asset_classes import VALIDATION_UNIVERSE, class_of

        out = []
        for sym in VALIDATION_UNIVERSE:
            key = f"{sym}/USDT" if class_of(sym) == "crypto" else sym
            if key not in out:
                out.append(key)
        return out
    except Exception:
        return []


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
    quadrant = rotation.get("merrill_clock", {}).get("quadrant")  # noqa: F841
    quadrant_conf = rotation.get("merrill_clock", {}).get("confidence")
    live_whitelist = set(cfg["whitelist"])
    universe = list(cfg["whitelist"]) + [s for s in paper_universe(cfg) if s not in live_whitelist]
    intents = []
    for symbol in universe:
        a = ta.get(symbol)
        if not a:
            continue
        # 方向判别：MA200 锚点 above/below（日线级别）
        direction = "UP" if a.get("above") else "DOWN"
        conf = 0.6 if quadrant_conf == "high" else (0.5 if quadrant_conf == "medium" else 0.4)
        intents.append(
            {
                "symbol": symbol,
                "direction": direction,
                "confidence": conf,
                "timeframe": "1d",
                "holding_period_days": cfg["holding_period_days"],
                "notional_usdt": cfg["intent_notional_usdt"],
                "leverage": cfg["leverage"],
                "execution_scope": "x2_live_gated" if symbol in live_whitelist else "paper_only",
            }
        )
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
        intents.append(
            {
                "symbol": symbol,
                "direction": direction,
                "confidence": entry.get("confidence", 0),
                "timeframe": "4h",
                "holding_period_days": cfg["holding_period_days"],
                "notional_usdt": cfg["intent_notional_usdt"],
                "leverage": cfg["leverage"],
            }
        )
    return snapshot, intents


def universe_filter(intents, cfg):
    """保留白名单（X2 实盘门禁）+ 纸面验证场（paper_only）两类意图。"""
    allowed = set(cfg["whitelist"]) | set(paper_universe(cfg))
    return [i for i in intents if i["symbol"] in allowed]


def notify_violation(violation, violations_path):
    """15 系统告警通知（SPEC 第七章接口：风控红线违规通知）。fail-open：推送失败仅记录，不阻断主流程。"""
    try:
        if ALERT_MODULE_DIR not in sys.path:
            sys.path.insert(0, ALERT_MODULE_DIR)
        from feishu_alert import send_alert

        send_alert(
            "trading",
            "warning",
            "40意图流风控红线违规: " + str(violation.get("symbol")),
            {"reasons": violation.get("reasons"), "ts": violation.get("ts")},
            system="40_execution_layer",
        )
    except Exception as e:
        append_jsonl(
            violations_path,
            {"ts": now_iso(), "type": "alert_failed", "error": str(e), "violation": violation},
        )


def risk_check(intents, cfg, state, violations_path):
    """风控红线检查：X0 无持仓，检查单笔上限/白名单/杠杆；violation 落盘。"""
    limits = cfg["risk_limits"]
    passed = []
    for i in intents:
        reasons = []
        scope = i.get("execution_scope") or "x2_live_gated"
        if i["notional_usdt"] > limits["max_notional_per_order"]:
            reasons.append(
                f"单笔名义 {i['notional_usdt']} > 上限 {limits['max_notional_per_order']}"
            )
        if i["leverage"] != "1x":
            reasons.append(f"杠杆 {i['leverage']} 违规（禁用杠杆）")
        # 白名单只约束实盘门禁标；paper_only 标的允许进入纸面验证场（DEC-BCL-07）
        if scope != "paper_only" and i["symbol"] not in cfg["whitelist"]:
            reasons.append(f"{i['symbol']} 不在白名单")
        if reasons:
            violation = {
                "ts": now_iso(),
                "type": "risk_limit",
                "symbol": i["symbol"],
                "execution_scope": scope,
                "reasons": reasons,
                "intent": i,
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
                keys.add(
                    (
                        r.get("intent_date"),
                        r.get("symbol"),
                        (r.get("signal_snapshot") or {}).get("source"),
                    )
                )
            except json.JSONDecodeError:
                continue
    return keys


def backfill_decision_links(trades_path, decision_index, today):
    """回填当日已落盘意图的 decision_id（只映射，不推断）。

    X0 以 (intent_date, symbol, source) 去重，已落盘意图不会重写；50 补齐
    per-symbol 决策后，历史行仍需回填 decision_id 才能形成"决策→意图"审计链。
    """
    if not os.path.exists(trades_path) or not decision_index:
        return 0
    rows = []
    changed = 0
    with open(trades_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                rows.append(line.rstrip("\n"))
                continue
            if record.get("intent_date") == today and not record.get("decision_id"):
                hit = decision_index.get(_base_asset(record.get("symbol"))) or {}
                if hit.get("decision_id"):
                    record["decision_id"] = hit["decision_id"]
                    record["decision_ts"] = hit["ts"].isoformat() if hit.get("ts") else None
                    changed += 1
            rows.append(json.dumps(record, ensure_ascii=False))
    if changed:
        tmp_path = trades_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            for line in rows:
                f.write(line + "\n")
        os.replace(tmp_path, trades_path)
    return changed


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

    intents = universe_filter(intents, cfg)
    intents = risk_check(intents, cfg, None, violations_path)
    decision_index = load_decision_index(cfg)

    today = date.today().isoformat()
    backfilled = backfill_decision_links(trades_path, decision_index, today)
    seen = existing_intent_keys(trades_path)
    written = 0
    for i in intents:
        key = (today, i["symbol"], snapshot["source"])
        if key in seen:
            continue
        hit = decision_index.get(_base_asset(i["symbol"])) or {}
        record = {
            "ts": now_iso(),
            "intent_date": today,
            "symbol": i["symbol"],
            "decision_id": hit.get("decision_id"),
            "decision_ts": hit["ts"].isoformat() if hit.get("ts") else None,
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
        "stage": "X0",
        "signal_source": src,
        "intents_today": len(intents),
        "written_today": written,
        "decision_backfilled_today": backfilled,
        "decision_linked_today": sum(
            1
            for i in intents
            if (decision_index.get(_base_asset(i["symbol"])) or {}).get("decision_id")
        ),
        "trades_path": trades_path,
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    # DEC-BCL-06 路径 C：组合级执行记录（fail-open，不影响意图流落盘）
    try:
        if BASE not in sys.path:
            sys.path.insert(0, BASE)
        from portfolio_execution import aggregate_day

        portfolio = aggregate_day(
            date_str=today,
            trades_path=trades_path,
            out_path=os.path.join(
                out_dir, cfg["output"].get("portfolio_executions", "portfolio_executions.jsonl")
            ),
            decisions_path=(cfg.get("decision_source") or {}).get("path"),
        )
        state["portfolio_batches"] = portfolio.get("written", 0)
    except Exception as e:  # noqa: BLE001 — 组合级记录失败不阻断 X0
        append_jsonl(
            os.path.join(ROOT, "execution_errors.jsonl"),
            {"ts": now_iso(), "type": "portfolio_execution_failed", "error": str(e)},
        )
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
