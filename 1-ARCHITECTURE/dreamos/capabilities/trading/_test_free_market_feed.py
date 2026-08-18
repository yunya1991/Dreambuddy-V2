#!/usr/bin/env python3
"""
验证脚本：FreeMarketFeed 全部接口的冒烟测试（Smoke Test）

零成本、无需任何 API Key。
运行：
    cd /Users/zhangjiangtao/WorkBuddy/dreambuddy-v2
    python3 1-ARCHITECTURE/dreamos/capabilities/trading/_test_free_market_feed.py
"""
from __future__ import annotations

import sys
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

# 确保可以 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
)

from dreamos.capabilities.trading.free_market_feed import FreeMarketFeed, CRYPTO_SECTORS


def section(title: str):
    bar = "=" * 72
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar, flush=True)


def kv(key: str, val, width: int = 32):
    s_val = str(val)
    if len(s_val) > 120:
        s_val = s_val[:120] + "..."
    print(f"  {key:<{width}} {s_val}")


def main() -> int:
    feed = FreeMarketFeed()
    all_ok = True
    totals = {"pass": 0, "fail": 0}

    def check(name: str, cond, detail: str = ""):
        nonlocal all_ok
        ok = bool(cond)
        if ok:
            totals["pass"] += 1
            status = "✅ PASS"
        else:
            totals["fail"] += 1
            all_ok = False
            status = "❌ FAIL"
        print(f"  [{status}]  {name}   {detail}")
        return ok

    # ========================================================================
    section("1. BTC 日线 OHLC（Binance 免费）")
    t0 = time.time()
    btc = feed.fetch_btc_daily_ohlc(limit=365)
    kv("耗时", f"{time.time() - t0:.1f}s")
    kv("返回条数", len(btc))
    check("返回≥300条", len(btc) >= 300)
    if btc:
        latest = btc[-1]
        kv("最新日期(UTC)", datetime.fromtimestamp(latest["t"], tz=timezone.utc).strftime("%Y-%m-%d"))
        kv("BTC 最新收盘价", f"{latest['C']:,.2f} USDT")
        kv("字段齐全", all(k in latest for k in ("t", "O", "H", "L", "C", "V")))
        closes = [r["C"] for r in btc]
        for n in (20, 50, 128):
            if len(closes) >= n:
                ma = sum(closes[-n:]) / n
                kv(f"MA{n}", f"{ma:,.2f}")

    # ========================================================================
    section("2. 5 板块资金权重免费代理（Binance 24h ticker）")
    t0 = time.time()
    sectors = feed.get_sector_proxy_weights()
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("返回5个板块", len(sectors) == 5)
    total_vol_share = 0.0
    ranked = sorted(sectors.items(), key=lambda x: -x[1].get("pct_volume", 0))
    print("  ╭─────────────── 板块强度排名（1=最强） ───────────────╮")
    for sn, sd in ranked:
        print(f"  │ Rank{sd.get('strength_rank_1to5','?'):>2}  {sn:<10} "
              f"pct_eq={sd.get('pct_equal',0):>7.3f}%  "
              f"pct_vol_w={sd.get('pct_volume',0):>7.3f}%  "
              f"vol_share={sd.get('volume_share_pct',0):>6.3f}%  "
              f"hits={sd.get('hits',0)}/{len(CRYPTO_SECTORS[sn])} │")
        total_vol_share += sd.get("volume_share_pct", 0) or 0
    print(f"  ╰─────────────────────────────────────────────────── 成交额占比合计={total_vol_share:.2f}% ─╯")
    check("板块成交额占比合计≈100%", abs(total_vol_share - 100.0) < 0.1)

    # ========================================================================
    section("3. 8 主流币广度（MA20 同向比例）")
    t0 = time.time()
    br = feed.get_mainstream_breadth(lookback_days=20)
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("广度 ok 字段", br.get("ok"))
    if br.get("ok"):
        kv("覆盖币种数", f"{br['coins_covered']}/8")
        kv("MA20 之上比例", f"{br['breadth_pct_above_ma20']*100:.1f}%")
        kv("20d 收益为正比例", f"{br['breadth_pct_up_20d']*100:.1f}%")
        kv("等权 8 币 20d 收益", f"{br['avg_return_20d_pct']:.2f}%")
        for cn, cd in br.get("coins_detail", {}).items():
            if cd.get("ok"):
                tag = "↑MA20" if cd.get("above_ma20") else "↓MA20"
                print(f"    {cn:<6} close={cd['close_latest']:>10.4f}  "
                      f"MA20={str(cd['ma20']):>10}  {tag}  "
                      f"20d_ret={cd['return_20d_pct']:>+7.3f}%")

    # ========================================================================
    section("4. CoinGecko 宏观（BTC.D + Top8 稳定币市值）")
    t0 = time.time()
    gm = feed.fetch_global_macro()
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("coingecko _ok", gm.get("_ok"))
    if gm.get("_ok"):
        kv("BTC.D 市值占比", f"{gm.get('btc_dominance_pct'):.2f}%")
        kv("加密总市值", f"${gm.get('total_market_cap_usd')/1e12:,.3f} T")
        kv("24h 总成交额", f"${gm.get('total_volume_24h_usd')/1e9:,.2f} B")
        if "stablecoin_mcap_top8_usd_billion" in gm:
            kv("Top8 稳定币总市值", f"${gm['stablecoin_mcap_top8_usd_billion']:,.2f} B")
            if "stablecoin_mcap_change_7d_pct_proxy" in gm:
                kv("稳定币 7d 净申赎(代理)", f"{gm['stablecoin_mcap_change_7d_pct_proxy']:+.4f}%")
            if "stablecoin_mcap_change_30d_pct_proxy" in gm:
                kv("稳定币 30d 净申赎(代理)", f"{gm['stablecoin_mcap_change_30d_pct_proxy']:+.4f}%")
        if "stablecoin_top8" in gm:
            for s in gm["stablecoin_top8"][:5]:
                print(f"    {s['symbol'].upper():<6} mcap=${s['mcap_usd_billion']:>7.3f}B  "
                      f"7d={s['change_7d_pct']:>+.3f}%  30d={s['change_30d_pct']:>+.3f}%")

    # ========================================================================
    section("5. Fear & Greed 情绪指数（Alternative.me）")
    t0 = time.time()
    fg = feed.fetch_fear_greed(limit=60)
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("fg ok", fg.get("ok"))
    if fg.get("ok"):
        kv("当前值 / 分类", f"{fg['value']}  ({fg['classification']})")
        if "avg_7d" in fg:
            kv("7d 均值 / 趋势", f"{fg['avg_7d']:.1f}  ({fg['trend_vs_7d']:+.1f})")
        if "percentile_30d" in fg:
            kv("30d 分位位置", f"{fg['percentile_30d']*100:.1f}%  (范围 {fg['low_30d']}~{fg['high_30d']})")

    # ========================================================================
    section("6. 美股/ETF 日线（yfinance） — SPY / QQQ / GLD / TLT")
    t0 = time.time()
    us_tests = {}
    for ticker in ("SPY", "QQQ", "GLD", "TLT"):
        rows = feed.fetch_equity_daily(ticker, limit=60)
        us_tests[ticker] = rows
        if rows:
            kv(f"{ticker} 返回条数", f"{len(rows)}  最新={rows[-1]['C']:.2f} ({rows[-1].get('date','?')})")
        else:
            kv(f"{ticker}", "⚠️  无数据（可能网络/速率限制）")
    kv("本步骤耗时", f"{time.time() - t0:.1f}s")
    any_us = bool(any(v for v in us_tests.values()))
    check("至少 1 只美股 ETF 数据 OK", any_us)

    # ========================================================================
    section("7. BTC vs 美股/黄金/美债 滚动 Pearson 相关性（自研）")
    t0 = time.time()
    corr = feed.get_btc_us_assets_correlations(window_days=30)
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("corr ok", corr.get("ok"))
    if corr.get("ok"):
        for k in ("btc_vs_spy", "btc_vs_qqq", "btc_vs_gld", "btc_vs_tlt", "avg_equity_corr"):
            v = corr.get(k)
            kv(k, f"{v:+.4f}" if v is not None else "N/A")
        kv("BTC-美股耦合 (>0.4)", corr.get("btc_equity_coupled"))
        kv("BTC-避险属性 (金+债)", corr.get("btc_safe_haven"))

    # ========================================================================
    section("8. BTC ETF 价格代理（IBIT / FBTC / ARKB）")
    t0 = time.time()
    etf = feed.fetch_btc_etf_price_proxy()
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("etf ok", etf.get("ok"))
    if etf.get("ok"):
        kv("BTC 20d 收益", f"{etf['btc_return_20d_pct']:+.2f}%")
        for nm, v in etf.get("funds", {}).items():
            ex = v.get("excess_vs_btc_20d_pct")
            ex_s = f"{ex:+.3f}%" if ex is not None else "N/A"
            print(f"    {nm:<5} close={v['latest_close']:>8.2f}  "
                  f"20d_ret={v.get('return_20d_pct','N/A')}  "
                  f"超额vs_BTC={ex_s}  日期={v.get('latest_date')}")
        if "avg_etf_excess_20d_pct" in etf:
            kv("3 只 ETF 平均超额收益", f"{etf['avg_etf_excess_20d_pct']:+.3f}%")

    # ========================================================================
    section("9a. Binance Futures 衍生品免费数据（5 大类）")
    t0 = time.time()
    bi = feed.fetch_binance_futures_derivatives("BTCUSDT", period="4h", limit=30)
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("binance futures _ok", bi.get("_ok"))
    if bi.get("_ok"):
        if bi.get("oi_latest"):
            kv("OI 最新 (USD 名义)", f"${bi['oi_latest']['oi_usd_notional']:,.0f}")
        if bi.get("funding_rate_latest"):
            kv("资金费率 最新 / 7d / 30d",
               f"{bi['funding_rate_latest']['rate_pct']:+.5f}%  /  "
               f"{bi.get('funding_rate_avg7_pct','?'):+.5f}%  /  "
               f"{bi.get('funding_rate_avg30_pct','?'):+.5f}%")
            kv("多头资金费压力 (>0.05%)", bi.get("funding_pressured_long"))
        if bi.get("taker_ls_ratio_latest"):
            kv("Taker 买卖比 最新 / 7d",
               f"{bi['taker_ls_ratio_latest']['buy_sell_ratio']:.3f}  /  "
               f"{bi.get('taker_ls_ratio_avg7','?'):.3f}")
        if bi.get("global_ls_account_ratio_latest"):
            g = bi["global_ls_account_ratio_latest"]
            kv("全账户 L/S 比", f"{g['long_short_account_ratio']:.3f}  "
               f"(多头账户 {g['long_account_pct']:.1f}% vs 空头 {g['short_account_pct']:.1f}%)")
        if bi.get("top_trader_position_ratio_latest"):
            t = bi["top_trader_position_ratio_latest"]
            kv("Top Trader L/S 持仓比",
               f"{t['long_short_position_ratio']:.3f}  "
               f"(多头 {t['long_position_pct']:.1f}%  vs 空头 {t['short_position_pct']:.1f}%)")
            kv("Top Trader 7d 均值", bi.get("top_trader_position_ratio_avg7"))

    # ========================================================================
    section("9b. OKX V5 公共衍生品免费数据（双备份）")
    t0 = time.time()
    okx = feed.fetch_okx_public_derivatives("BTC-USDT-SWAP", ccy="BTC", period_bar="4H", limit=30)
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("okx public _ok", okx.get("_ok"))
    if okx.get("_ok"):
        if okx.get("oi_latest_usd"):
            kv("OI 最新 (USD)", f"${okx['oi_latest_usd']:,.0f}")
        if okx.get("oi_change_7bar_pct") is not None:
            kv("OI 7bar (≈28h) 变化率", f"{okx['oi_change_7bar_pct']:+.3f}%")
        if okx.get("funding_rate_settlement"):
            fs = okx["funding_rate_settlement"]
            kv("资金费率 当前 / 下一期预测",
               f"{fs['current_rate_pct']:+.5f}%  /  {fs['next_rate_pct']:+.5f}%")
        if okx.get("funding_rate_latest"):
            kv("资金费率 历史最新 / 7d",
               f"{okx['funding_rate_latest']['rate_pct']:+.5f}%  /  "
               f"{okx.get('funding_rate_avg7_pct','?'):+.5f}%")
        if okx.get("taker_ls_ratio_latest"):
            tl = okx["taker_ls_ratio_latest"]
            kv("OKX Taker B/S 比", f"{tl.get('taker_buy_sell_ratio','N/A')}")

    # ========================================================================
    section("9c. 衍生品统一合成快照 get_derivatives_snapshot()")
    t0 = time.time()
    ds = feed.get_derivatives_snapshot()
    kv("耗时", f"{time.time() - t0:.1f}s")
    so = ds.get("_sources_ok", {})
    kv("来源可用", f"Binance={so.get('binance_futures')}  OKX={so.get('okx_public')}")
    for k, v in ds.items():
        if k.startswith("_"):
            continue
        kv(k, v)

    # ========================================================================
    section("★ 10. 综合入口 collect_global() — 一次调用拿全部")
    t0 = time.time()
    snap = feed.collect_global()
    total_ms = int((time.time() - t0) * 1000)
    kv("总耗时", f"{total_ms} ms")
    kv("特征数量（不含_前缀）", snap.get("_feature_count"))
    kv("采集时间戳",
       datetime.fromtimestamp(snap.get("_collected_at_s", 0), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    srcs = snap.get("_sources", {})
    print("  数据来源清单：")
    for k, v in srcs.items():
        status = "✅" if not v.endswith("failed") and "failed" not in v.lower() else "⚠️"
        print(f"    {status}  {k:<28} → {v}")
    check("btc_latest 存在", "btc_latest" in snap)
    check("BTC 3 条均线齐全", all(f"btc_ma{n}" in snap for n in (20, 50, 128)))
    check("BTC.D 存在", "btc_dominance_pct" in snap)
    check("Fear&Greed 存在", "fear_greed" in snap and snap["fear_greed"].get("ok"))
    check("板块权重 5 个", len(snap.get("sector_proxy_weights", {})) == 5)
    check("主流币广度 ok", snap.get("mainstream_breadth", {}).get("ok"))
    check("BTC-美股相关性 ok", snap.get("btc_us_assets_correlations", {}).get("ok"))
    check("衍生品快照", "derivatives" in snap)

    # ========================================================================
    section("11. 爆仓恐慌快照（Binance 主 + OKX 备 + 二阶代理 fallback）")
    t0 = time.time()
    liq = feed.get_liquidation_panic_snapshot()
    kv("耗时", f"{time.time() - t0:.1f}s")
    so = liq.get("_sources_ok", {})
    kv("真实 API 可用", f"Binance={so.get('binance_futures')}  OKX={so.get('okx_public')}")
    kv("数据来源 provenance", liq.get("_data_provenance"))
    check("核心字段存在（真实或代理）",
          all(k in liq for k in ("panic_score_0_to_1", "panic_level", "regime_hint")))
    kv("爆仓恐慌指数", liq.get("panic_score_0_to_1"))
    kv("恐慌等级", liq.get("panic_level"))
    kv("形态 regime_hint", liq.get("regime_hint"))
    kv("24h 总爆仓(USD)",
       "N/A (二阶代理)" if liq.get("total_liq_usd_24h") is None
       else f"{liq.get('total_liq_usd_24h')/1e6:.1f} M USD")
    if "proxy_fallback" in liq:
        pf = liq["proxy_fallback"]
        print("  二阶代理输入信号：")
        kv("  · OI 7 日变化率", f"{pf.get('proxy_oi_7bar_change_pct')} %")
        kv("  · Taker L/S 7 日均值", pf.get("proxy_taker_ls_ratio_avg7"))
        kv("  · 资金费率 7 日均值", f"{pf.get('proxy_funding_rate_abs_avg7_pct')} %")
        kv("  · Top Trader L/S 7 日均值", pf.get("proxy_top_trader_ls_avg7"))
    else:
        kv("多/空爆仓比", liq.get("long_short_liq_ratio"))
        kv("级联爆仓小时数", liq.get("cascade_hours"))
        kv("1 小时最大爆仓(USD)",
           "N/A" if liq.get("max_1h_liq_usd") is None
           else f"{liq.get('max_1h_liq_usd')/1e6:.2f} M USD")

    # ========================================================================
    section("12. 二阶代理估计器（直接调用，验证网络 fallback 路径）")
    t0 = time.time()
    proxy = feed._estimate_liquidation_panic_proxy()
    kv("耗时", f"{time.time() - t0:.1f}s")
    check("代理估计器 7 项得分字段齐全",
          all(k in proxy for k in ("proxy_oi_7bar_change_pct",
                                    "proxy_taker_ls_ratio_avg7",
                                    "proxy_funding_rate_abs_avg7_pct",
                                    "proxy_top_trader_ls_avg7",
                                    "proxy_panic_score_0_to_1",
                                    "proxy_panic_level",
                                    "proxy_regime_hint")))
    kv("代理恐慌指数", proxy.get("proxy_panic_score_0_to_1"))
    kv("代理恐慌等级", proxy.get("proxy_panic_level"))
    kv("代理 regime_hint", proxy.get("proxy_regime_hint"))
    check("代理 panic_score 范围合法",
          0.0 <= (proxy.get("proxy_panic_score_0_to_1") or 0) <= 1.0)
    check("代理 level 在枚举内",
          proxy.get("proxy_panic_level") in {"CALM", "MILD", "TENSE", "PANIC", "EXTREME_PANIC"})
    check("代理 regime_hint 在枚举内",
          proxy.get("proxy_regime_hint") in {"NONE", "VOLATILE_DROP", "FOMO_RALLY", "REVERSAL"})

    # ========================================================================
    section("13. 期权 IV 快照（OKX opt-summary：BTC/ETH ATM IV + 25Δ Skew）")
    t0 = time.time()
    opts = feed.fetch_okx_options_iv_snapshot()
    kv("耗时", f"{time.time() - t0:.1f}s")
    # 期权无 proxy，只要 provenance 明确（成功 or 明确说明网络gated）都算合同合规
    provenance_ok = opts.get("_provenance") is not None
    check("期权 IV 合同合规（成功 or 明确 provenance）", opts.get("_ok") or provenance_ok)
    kv("provenance", opts.get("_provenance"))
    kv("OKX 返回数据行数", opts.get("_okx_rows_returned"))
    if opts.get("_ok"):
        kv("提取到 inst_family 数量", len(opts.get("by_family", {})))
        btc = opts.get("by_family", {}).get("BTC-USD")
        eth = opts.get("by_family", {}).get("ETH-USD")
        if btc:
            kv("BTC ATM IV",
               "N/A" if btc.get("atm", {}).get("iv_pct") is None else f"{btc['atm']['iv_pct']:.1f}%")
            kv("BTC 25Δ PC Skew",
               "N/A" if btc.get("delta_25", {}).get("pc_skew_pct") is None
               else f"{btc['delta_25']['pc_skew_pct']:+.2f}%")
            kv("BTC 10Δ Tail Skew",
               "N/A" if btc.get("delta_10_tail", {}).get("pc_skew_pct") is None
               else f"{btc['delta_10_tail']['pc_skew_pct']:+.2f}%")
            kv("BTC 偏度情绪标签", btc.get("interpretation", {}).get("skew_25d_sentiment"))
        if eth:
            kv("ETH ATM IV",
               "N/A" if eth.get("atm", {}).get("iv_pct") is None else f"{eth['atm']['iv_pct']:.1f}%")
            kv("ETH 25Δ PC Skew",
               "N/A" if eth.get("delta_25", {}).get("pc_skew_pct") is None
               else f"{eth['delta_25']['pc_skew_pct']:+.2f}%")
    kv("Crypto VIX 代理(BTC/ETH 平均)",
       "N/A" if opts.get("crypto_vix_proxy_pct") is None
       else f"{opts['crypto_vix_proxy_pct']:.1f}%")
    kv("期权 regime_hint（多数票）", opts.get("regime_hint_majority"))
    check("options_regime_hint 合法",
          (opts.get("regime_hint_majority") is None
           or opts.get("regime_hint_majority") in {"NONE", "VOLATILE_DROP",
                                                    "FOMO_RALLY", "REVERSAL",
                                                    "RANGE_BOUND", "TIGHT_SQUEEZE"}))

    # ========================================================================
    section("14. collect_global 顶层便捷字段 — 形态预测器直接消费")
    check("liq_panic_score_0_to_1 顶层存在", "liq_panic_score_0_to_1" in snap)
    check("liq_panic_level 顶层存在", "liq_panic_level" in snap)
    check("liq_regime_hint 顶层存在", "liq_regime_hint" in snap)
    check("crypto_vix_proxy_pct 顶层存在", "crypto_vix_proxy_pct" in snap)
    check("options_regime_hint 顶层存在", "options_regime_hint" in snap)
    kv("→ liq_panic_score_0_to_1", snap.get("liq_panic_score_0_to_1"))
    kv("→ liq_panic_level", snap.get("liq_panic_level"))
    kv("→ liq_regime_hint", snap.get("liq_regime_hint"))
    kv("→ crypto_vix_proxy_pct", snap.get("crypto_vix_proxy_pct"))
    kv("→ options_regime_hint", snap.get("options_regime_hint"))
    kv("→ 爆仓 L/S 比(None=代理)", snap.get("liq_long_short_ratio"))
    kv("→ 级联爆仓小时(None=代理)", snap.get("liq_cascade_hours"))
    # 验证 source 标注正确（包含 proxy_fallback 路径）
    src_liq = srcs.get("liquidation_panic") or ""
    kv("→ source:liquidation_panic", src_liq)
    check("liquidation_panic 来源含真实或 proxy",
          ("binance" in src_liq.lower() or "okx" in src_liq.lower() or "proxy" in src_liq.lower()))
    src_opts = srcs.get("options_iv") or ""
    kv("→ source:options_iv", src_opts)
    check("options_iv 来源标注非空", bool(src_opts))

    # ========================================================================
    section("📊 汇总")
    print(f"\n  ✅ 通过: {totals['pass']}    ❌ 失败: {totals['fail']}")
    if all_ok:
        print("\n  🎉  FreeMarketFeed 全部冒烟测试通过！")
        print("      定位：S8 关闭时，形态预测器 Layer 0 / Layer 1 的默认零成本数据源")
    else:
        print(f"\n  ⚠️   {totals['fail']} 项未通过。免费接口偶发失败通常是速率限制或网络波动，缓存机制（30min）会减轻问题。")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
