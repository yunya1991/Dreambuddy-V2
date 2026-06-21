import os
import sys
from pathlib import Path
import json

# Add project root to path
sys.path.append(os.getcwd())

from ml_trade_service import _find_pair_file, _get_pair_cache, _data_dirs, _build_data_index, DATA_INDEX

print("Data dirs:", _data_dirs())

_build_data_index()
print(f"Data index size: {len(DATA_INDEX)}")
if len(DATA_INDEX) > 0:
    print(f"Sample key: {list(DATA_INDEX.keys())[0]}")
    print(f"Sample path: {list(DATA_INDEX.values())[0]}")

pair = "BTCUSDT"
p = _find_pair_file(pair)
print(f"File for {pair}: {p}")

if p:
    try:
        with open(p, "r") as f:
            data = json.load(f)
            print(f"Read {len(data)} rows from file")
            if len(data) > 0:
                print(f"First row: {data[0]}")
    except Exception as e:
        print(f"Error reading file: {e}")

    c = _get_pair_cache(pair)
    print(f"Cache keys: {list(c.keys())}")
    print(f"Hourly len: {len(c.get('hourly', []))}")
else:
    print("File not found via _find_pair_file")
