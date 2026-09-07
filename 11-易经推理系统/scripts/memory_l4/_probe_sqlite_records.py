"""Direct SQLite probe: records table per source -> metrics JSON keys.

Goal: find the real column names stored in SQLite for:
- ETF / BTC-ETF data  →  (currently btc_etf_flow_3d _has_data all False)
- Whale netflow data →  (whale_netflow_pulse _has_data all False)
- Stablecoin / global market cap data → (stablecoin_minus_rwa _has_data all False)
"""
import sqlite3, json, os
import sys

DATA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data'))
DB = os.path.join(DATA_ROOT, 'data_center.db')
# fallback per DEFAULT_DB_PATH calc in five_domain_sqlite_reader
if not os.path.exists(DB):
    # try default project-level data dir
    DB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'memory_l4', 'data_center.db'))
if not os.path.exists(DB):
    # final try module DEFAULT_DB_PATH
    sys.path.insert(0, os.path.dirname(__file__))
    import five_domain_sqlite_reader as fdr
    DB = fdr.DEFAULT_DB_PATH

print('DB =', DB, 'exists =', os.path.exists(DB))
conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT source, sub_category, metrics, timestamp, id "
    "FROM records ORDER BY id DESC"
).fetchall()
conn.close()
print(f'Total records rows: {len(rows)}')
print()

# Group by (source, sub_category) keep latest id
latest = {}
for r in rows:
    key = (r['source'], r['sub_category'])
    if key not in latest:
        latest[key] = r
print(f'Distinct (source, sub_category) pairs: {len(latest)}')
print()

def _load_metrics(m):
    try:
        return json.loads(m) if m else {}
    except Exception:
        try:
            return dict(m) or {}
        except Exception:
            return {}

print('== [1] All source/sub_category latest record + top-level metrics keys ==')
sources_of_interest = ['panewslab', 'stablecoin_transparency', 'theblockbeats_dataview', 'defillama', 'yfinance', 'fred', 'ccxt', 'etherscan', 'tavily']
for (src, sub), r in sorted(latest.items(), key=lambda x: (x[0][0], x[0][1] or '')):
    metrics = _load_metrics(r['metrics'])
    keys_count = len(metrics) if isinstance(metrics, dict) else 0
    show_keys = list(metrics.keys())[:40] if isinstance(metrics, dict) else []
    mark = '  ⭐️' if src in ('panewslab','stablecoin_transparency','theblockbeats_dataview') else '    '
    ts = r['timestamp']
    print(f'{mark}[{src:<25} {str(sub):<35}] id={r["id"]:<6} ts={ts}  n_keys={keys_count}')
    if isinstance(metrics, dict):
        for k in sorted(metrics.keys())[:40]:
            v = metrics[k]
            if isinstance(v, (int, float)):
                sv = f'{v}'
            elif isinstance(v, str):
                sv = v[:60]
            elif isinstance(v, (dict, list)):
                sv = f'<{type(v).__name__} len={len(v)}>'
            else:
                sv = str(type(v).__name__)
            print(f'         · {k:<55} = {sv}')
    print()

# Dedicated targeted print
print()
print('== [2] Targeted deep-dive for the 3 missing feature groups ==')
print()

# Group 1: stablecoin
if ('stablecoin_transparency', 'tether_current') in latest:
    print('[GROUP 1A: stablecoin_transparency/tether_current]')
    m = _load_metrics(latest[('stablecoin_transparency', 'tether_current')]['metrics'])
    for k, v in m.items():
        print(f'  {k}: {v}')
    print()
if ('stablecoin_transparency', 'usdc_current') in latest:
    print('[GROUP 1B: stablecoin_transparency/usdc_current]')
    m = _load_metrics(latest[('stablecoin_transparency', 'usdc_current')]['metrics'])
    for k, v in m.items():
        print(f'  {k}: {v}')
    print()

# Group 2: panewslab - list sub_categories
panewslab_items = [(s, r) for (s, _), r in latest.items() if s == 'panewslab']
print(f'[GROUP 2: panewslab] distinct sub_category count = {len(panewslab_items)}')
for (s, r) in panewslab_items:
    sub = r['sub_category']
    ts = r['timestamp']
    metrics = _load_metrics(r['metrics'])
    keys = sorted(list(metrics.keys()))
    print(f'  sub_category = {repr(sub)}  ts={ts}  n_keys={len(keys)}')
    for k in keys[:100]:
        v = metrics[k]
        if isinstance(v, (int, float)):
            sv = f'{v}'
        elif isinstance(v, str):
            sv = v[:80]
        elif isinstance(v, (dict, list)):
            sv = f'<{type(v).__name__} len={len(v)}>'
        else:
            sv = type(v).__name__
        print(f'     · {k:<60} = {sv}')
    print()

# Group 3: theblockbeats_dataview - list sub_categories
blockbeats_items = [(s, r) for (s, _), r in latest.items() if s == 'theblockbeats_dataview']
print(f'[GROUP 3: theblockbeats_dataview] distinct sub_category count = {len(blockbeats_items)}')
for (s, r) in blockbeats_items:
    sub = r['sub_category']
    ts = r['timestamp']
    metrics = _load_metrics(r['metrics'])
    keys = sorted(list(metrics.keys()))
    print(f'  sub_category = {repr(sub)}  ts={ts}  n_keys={len(keys)}')
    for k in keys[:100]:
        v = metrics[k]
        if isinstance(v, (int, float)):
            sv = f'{v}'
        elif isinstance(v, str):
            sv = v[:80]
        elif isinstance(v, (dict, list)):
            sv = f'<{type(v).__name__} len={len(v)}>'
        else:
            sv = type(v).__name__
        print(f'     · {k:<60} = {sv}')
    print()
