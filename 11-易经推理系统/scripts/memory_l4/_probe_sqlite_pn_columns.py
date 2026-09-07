"""Probe: FiveDomainSqliteReader real pn_* column list + nonnull counts + sample values.

Purpose: Identify whether the 3 missing features (btc_etf_flow_3d, stablecoin_minus_rwa,
whale_netflow_pulse) are caused by column name mismatch (can fix by adding tuple fallback
today) or by truly missing data (need dispatcher launchd persist 1-2 weeks).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from five_domain_sqlite_reader import FiveDomainSqliteReader, DEFAULT_DB_PATH

print('== SQLite Column Probe for 13 macro-ext features ==')
print('DEFAULT_DB_PATH      =', DEFAULT_DB_PATH, '  exists=', os.path.exists(DEFAULT_DB_PATH))
print()

reader = FiveDomainSqliteReader(db_path=DEFAULT_DB_PATH)
macro_df = reader.read_macro_from_sqlite(category='crypto_usdt')
print(f'macro_df shape = {macro_df.shape}')
if len(macro_df):
    print(f'  index min = {macro_df.index.min()}')
    print(f'  index max = {macro_df.index.max()}')
print()

cols_all = list(macro_df.columns)

# ---- Part A: keyword based fuzzy hits ----
keywords = ['btc_etf', 'etf_flow', 'whale', 'netflow',
            'stablecoin', 'global_market', 'market_cap', 'mcap']
print('[A] Fuzzy keyword hits (btc_etf / whale / stablecoin / market_cap / mcap / netflow):')
hits = []
for c in cols_all:
    lc = c.lower()
    if any(k in lc for k in keywords):
        hits.append(c)
for c in sorted(set(hits)):
    nn = int(macro_df[c].notna().sum())
    sample_vals = macro_df[c].dropna().tail(4).tolist()
    print(f'  {c:<60} nonnull={nn:<6} tail4={sample_vals[:4]}')
print(f'  ({len(set(hits))} columns hit)')
print()

# ---- Part B: Exact candidate list from MacroFeatures.compute _has_data fallback tuples ----
print('[B] Exact 13-feature candidate column probe (check each _has_data fallback name):')
candidates = {
    'vix_zone':               ['pn_us_vix'],
    'us_macro_regime':        ['pn_us_fedfunds','pn_us_cpi_yoy'],
    'sp500_7d_break':         ['pn_us_sp500_chg_pct','pn_us_sp500'],
    'dxy_strength':           ['pn_us_dollar_index'],
    'btc_etf_flow_3d__MISSING':
        ['pn_btc_etf_daily_flow_usd_millions','pn_btc_etf_daily_flow_usd','pn_btc_etf_flow_norm',
         'pn_etf_btc_daily_flow_usd','pn_btc_etf_usd_flow','pn_etf_flow_btc','pn_btc_etf_inflow_usd',
         'pn_etf_netflow_btc','pn_btc_etf_netflow','pn_etf_holdings_btc'],
    'rwa_liquidity_pulse':    ['pn_rwa_change7d_pct','pn_rwa_tvl_usd_billions','pn_rwa_tvl_usd'],
    'treasury_balance_delta': ['pn_treasury_total_btc_holdings','pn_treasury_btc_total','pn_holdings_treasury_btc'],
    'stablecoin_minus_rwa__MISSING':
        ['stablecoin_supply','pn_global_market_cap_usd',
         'pn_stablecoin_total_supply','pn_global_mcap_usd',
         'pn_stablecoin_mcap','pn_stablecoin_market_cap',
         'pn_global_marketcap','pn_total_stablecoin_supply',
         'pn_stable_supply','pn_usdt_supply','pn_stablecoin_total'],
    'whale_netflow_pulse__MISSING':
        ['pn_whale_netflow_cap_pct','pn_netflow_whale','pn_whale_netflow_7d',
         'pn_whale_flow_cap_pct','pn_whale_inflow_cap','pn_whale_netflow',
         'pn_netflow_cap_pct','pn_netflow_7d_whale','pn_whale_change_cap_pct',
         'pn_whale_accumulation_cap','pn_big_player_netflow_cap_pct'],
    'exchange_btc_30d':       ['pn_ex_bal_BTC_chg30d_pct','pn_ex_bal_btc_chg30d_pct'],
    'defi_breadth':           ['defi_breadth_currentRange','bb_defi_range_tag',
                               'blockbeats_signal_overall','pn_cycle_sentiment_norm'],
    'oi_liq_pressure':        ['fut_liq_long_24h_usd_millions','fut_open_interest_usd_billions',
                               'pn_liq_atr_percentile_proxy','pn_fut_liquidation_24h_usd',
                               'pn_fut_open_interest_usd','pn_fut_long_liq_ratio',
                               'pn_leverage_ratio_oi_cap'],
    'btc_dom_delta':          ['pn_btc_dominance_pct'],
}
for feat, cols in candidates.items():
    hit_lines = []
    for c in cols:
        if c in macro_df.columns:
            nn = int(macro_df[c].notna().sum())
            sample_vals = macro_df[c].dropna().tail(4).tolist()
            hit_lines.append((c, nn, sample_vals))
    if hit_lines:
        print(f'  [{feat}]  hit {len(hit_lines)}/{len(cols)}:')
        for c, nn, sv in hit_lines:
            print(f'     OK {c:<60} nonnull={nn:<6} tail4={sv[:4]}')
    else:
        print(f'  [{feat}]  hit 0/{len(cols)}')
print()

# ---- Part C: extended fuzzy variants for the 3 explicitly MISSING groups ----
print('[C] Extended fuzzy probe for the 3 MISSING groups:')
groups = [
    ('ETF / BTC-ETF 相关',  ['etf']),
    ('巨鲸/净流入 相关',    ['whale', 'netflow']),
    ('稳定币/总市值 相关',  ['stablecoin', 'mcap', 'market_cap', 'supply', 'usdt_']),
]
for desc, subs in groups:
    found = []
    for c in cols_all:
        lc = c.lower()
        if any(s.lower() in lc for s in subs):
            nn = int(macro_df[c].notna().sum())
            sample_vals = macro_df[c].dropna().tail(4).tolist()
            found.append((c, nn, sample_vals))
    print(f'  {desc}: {len(found)} columns')
    for c, nn, sv in found:
        print(f'     · {c:<60} nonnull={nn:<6} tail4={sv[:4]}')
    print()
