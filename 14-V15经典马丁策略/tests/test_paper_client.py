#!/usr/bin/env python3
"""
test_paper_client.py — V15 Paper 执行客户端单元测试（离线，mock 价格）
PROP-20260816C 模块2 验证（2026-08-16）

运行: python3 tests/test_paper_client.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def make_client(tmp_path, price_map):
    """构造带 mock 价格的 paper 客户端（不触网）"""
    from v15_paper_client import V15PaperClient
    c = V15PaperClient(ledger_path=os.path.join(tmp_path, "ledger.json"))
    c._mid = lambda coin: price_map.get(coin)  # mock 行情
    return c


def main():
    print("=== T1: 市价开多 + 手续费 ===")
    with tempfile.TemporaryDirectory() as tmp:
        prices = {"BTC": 100000.0}
        c = make_client(tmp, prices)
        r = c.place_order("BTC-USDT-SWAP", "buy", sz=0.01, pos_side="long",
                          reason="t1_open")
        check("开仓 ok", r.get("ok") is True, str(r))
        check("成交价含滑点", abs(r["avg_px"] - 100050.0) < 1e-6, str(r.get("avg_px")))
        pos = c.get_all_positions()["positions"]
        check("持仓存在", "BTC" in pos and abs(pos["BTC"]["pos"] - 0.01) < 1e-12)
        led = c._load_ledger()
        check("手续费已扣", led["fee_paid_usdt"] > 0, str(led["fee_paid_usdt"]))
        check("余额=初始-手续费", abs(led["balance_usdt"] - (260 - led["fee_paid_usdt"])) < 1e-9)

    print("=== T2: 限价加仓网格穿越成交（马丁核心机制）===")
    with tempfile.TemporaryDirectory() as tmp:
        prices = {"ETH": 3000.0}
        c = make_client(tmp, prices)
        r = c.place_order("ETH-USDT-SWAP", side="buy", ord_type="limit", sz=0.1,
                          px=2880.0, pos_side="long", tag="v15addongrid",
                          reason="t2_grid")
        check("挂单 ok", r.get("ok") is True and r.get("state") == "live", str(r))
        pend = c.get_pending_orders("ETH-USDT-SWAP")
        check("挂单在列", pend["count"] == 1, str(pend))
        # 价格未穿越 → 不成交
        check("未穿越不成交", c.get_order("ETH-USDT-SWAP", r["ord_id"])["state"] == "live")
        # 价格穿越 → 成交
        prices["ETH"] = 2870.0
        o = c.get_order("ETH-USDT-SWAP", r["ord_id"])
        check("穿越后 filled", o["state"] == "filled", str(o))
        check("按限价成交", abs(o["avg_px"] - 2880.0) < 1e-9, str(o["avg_px"]))
        pos = c.get_all_positions()["positions"]
        check("持仓已建立", "ETH" in pos and abs(pos["ETH"]["pos"] - 0.1) < 1e-12)
        check("成交后出 pending 列表", c.get_pending_orders("ETH-USDT-SWAP")["count"] == 0)

    print("=== T3: 加仓均价加权 ===")
    with tempfile.TemporaryDirectory() as tmp:
        prices = {"SOL": 100.0}
        c = make_client(tmp, prices)
        c.place_order("SOL-USDT-SWAP", "buy", sz=1.0, pos_side="long", reason="t3_1")
        px1 = 100.0 * 1.0005
        prices["SOL"] = 92.0
        c.place_order("SOL-USDT-SWAP", "buy", sz=1.0, pos_side="long", reason="t3_2")
        px2 = 92.0 * 1.0005
        pos = c.get_all_positions()["positions"]["SOL"]
        expect = (1.0 * px1 + 1.0 * px2) / 2.0
        check("持仓合并 2 SOL", abs(pos["pos"] - 2.0) < 1e-12, str(pos["pos"]))
        check("加权均价正确", abs(pos["avg_px"] - expect) < 1e-6,
              f'{pos["avg_px"]} vs {expect}')

    print("=== T4: 平仓已实现盈亏 ===")
    with tempfile.TemporaryDirectory() as tmp:
        prices = {"OP": 2.0}
        c = make_client(tmp, prices)
        c.place_order("OP-USDT-SWAP", "buy", sz=100.0, pos_side="long", reason="t4_open")
        entry = 2.0 * 1.0005
        prices["OP"] = 2.2
        r = c.place_order("OP-USDT-SWAP", "sell", sz=100.0, pos_side="long",
                          reason="t4_close")
        check("平仓 ok", r.get("ok") is True, str(r))
        exit_px = 2.2 * 0.9995
        led = c._load_ledger()
        check("持仓清空", c.get_all_positions()["count"] == 0)
        check("已实现盈亏入账", led["realized_pnl_usdt"] > 0,
              str(led["realized_pnl_usdt"]))
        expect_pnl = (exit_px - entry) * 100.0
        check("盈亏数值正确", abs(led["realized_pnl_usdt"] - expect_pnl) < 1e-6,
              f'{led["realized_pnl_usdt"]} vs {expect_pnl}')
        check("平仓记录在案", len(led["closed_trades"]) == 1)

    print("=== T5: OCO 止盈止损记录与撤销 ===")
    with tempfile.TemporaryDirectory() as tmp:
        prices = {"ARB": 1.0}
        c = make_client(tmp, prices)
        c.place_order("ARB-USDT-SWAP", "buy", sz=50.0, pos_side="long", reason="t5")
        r = c.place_stop_loss_take_profit(
            inst_id="ARB-USDT-SWAP", pos_side="long",
            stop_loss_px=0.9, take_profit_px=1.1, sz=50.0, reason="t5_oco")
        check("OCO ok", r.get("ok") is True and r["orders"][0]["type"] == "oco", str(r)[:200])
        check("algo 在列", c.get_algo_orders("ARB-USDT-SWAP")["count"] == 1)
        cr = c.cancel_algo_orders("ARB-USDT-SWAP")
        check("撤销 ok", cr.get("ok") is True and cr["cancelled"] == 1, str(cr))
        check("撤销后清空", c.get_algo_orders("ARB-USDT-SWAP")["count"] == 0)
        # 仅止盈 → conditional
        r2 = c.place_stop_loss_take_profit(
            inst_id="ARB-USDT-SWAP", pos_side="long", take_profit_px=1.1,
            sz=50.0, reason="t5_tp_only")
        check("仅止盈 conditional", r2.get("ok") is True and r2["orders"][0]["type"] == "conditional")

    print("=== T6: 撤单 + instruments 端点兼容 ===")
    with tempfile.TemporaryDirectory() as tmp:
        prices = {"UNI": 10.0}
        c = make_client(tmp, prices)
        r = c.place_order("UNI-USDT-SWAP", side="buy", ord_type="limit", sz=5.0,
                          px=8.0, pos_side="long", tag="v15addongrid", reason="t6")
        cr = c.cancel_order("UNI-USDT-SWAP", r["ord_id"])
        check("撤单 ok", cr.get("ok") is True, str(cr))
        check("撤后 get_order=canceled",
              c.get_order("UNI-USDT-SWAP", r["ord_id"])["state"] == "canceled")
        ig = c._get("/api/v5/public/instruments",
                    {"instId": "BTC-USDT-SWAP", "instType": "SWAP"}, auth=False)
        check("instruments 端点 code=0", ig.get("code") == "0", str(ig))
        check("ctVal=1.0", float(ig["data"][0]["ctVal"]) == 1.0)
        check("lotSz>0", float(ig["data"][0]["lotSz"]) > 0, str(ig["data"][0]))

    print("=== T7: 做空开平 ===")
    with tempfile.TemporaryDirectory() as tmp:
        prices = {"BTC": 100000.0}
        c = make_client(tmp, prices)
        r = c.place_order("BTC-USDT-SWAP", "sell", sz=0.01, pos_side="short",
                          reason="t7_short_open")
        check("开空 ok", r.get("ok") is True, str(r))
        pos = c.get_all_positions()["positions"]["BTC"]
        check("空头持仓", pos["pos_side"] == "short", str(pos))
        prices["BTC"] = 95000.0
        c.place_order("BTC-USDT-SWAP", "buy", sz=0.01, pos_side="short",
                      reason="t7_short_close")
        led = c._load_ledger()
        check("空头盈利入账", led["realized_pnl_usdt"] > 0,
              str(led["realized_pnl_usdt"]))
        check("持仓清空", c.get_all_positions()["count"] == 0)

    print()
    print(f"结果: {PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
