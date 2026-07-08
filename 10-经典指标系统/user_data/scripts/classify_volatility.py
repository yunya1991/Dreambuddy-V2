import os
import json
import pandas as pd
import glob
import sys

# Paths
# We try to detect if we are in docker or local
USER_DATA_DIR = '/freqtrade/user_data'
if not os.path.exists(USER_DATA_DIR):
    # Fallback: assume script is in user_data/scripts/
    USER_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Adjust exchange name if needed. The user has 'gate' in the ls output.
DATA_DIR = os.path.join(USER_DATA_DIR, 'data', 'gate')
OUTPUT_DIR = USER_DATA_DIR

def load_data(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
    # Freqtrade JSON data is list of lists
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['close'] = df['close'].astype(float)
    return df

def calculate_volatility(df):
    # Standard deviation of percentage returns
    return df['close'].pct_change().std()

def main():
    print(f"Scanning data in {DATA_DIR}...")
    # Pattern matches standard Freqtrade naming for 5m data
    files = glob.glob(os.path.join(DATA_DIR, '*5m.json'))
    
    if not files:
        print(f"No data files found in {DATA_DIR}!")
        sys.exit(1)
        
    volatilities = []
    for filepath in files:
        # Filename example: BTC_USDT-5m.json -> Pair: BTC/USDT
        filename = os.path.basename(filepath)
        pair_name = filename.replace('-5m.json', '').replace('_', '/')
        
        try:
            df = load_data(filepath)
            if len(df) > 200: # Ensure enough data points
                vol = calculate_volatility(df)
                volatilities.append((pair_name, vol))
        except Exception as e:
            print(f"Error processing {filepath}: {e}")
            
    if not volatilities:
        print("No valid data processed.")
        sys.exit(1)
        
    # Sort by volatility (Low to High)
    volatilities.sort(key=lambda x: x[1])
    
    total = len(volatilities)
    chunk_size = total // 3
    
    # Split into 3 buckets
    low_vol = volatilities[:chunk_size]
    mid_vol = volatilities[chunk_size:2*chunk_size]
    high_vol = volatilities[2*chunk_size:]
    
    # Handle remainder (add to high vol)
    if total % 3 != 0:
        # The slicing above handles it, but let's be explicit about remaining items
        # actually slice logic [2*chunk_size:] takes all the rest, so it's fine.
        pass
    
    print(f"Classified {total} pairs: {len(low_vol)} Low, {len(mid_vol)} Mid, {len(high_vol)} High.")
    
    # Helper to save config
    def save_config(pairs, filename):
        config = {
            "exchange": {
                "pair_whitelist": [p[0] for p in pairs]
            }
        }
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, 'w') as f:
            json.dump(config, f, indent=4)
        print(f"Saved {path}")

    save_config(low_vol, 'config_vol_low.json')
    save_config(mid_vol, 'config_vol_mid.json')
    save_config(high_vol, 'config_vol_high.json')

if __name__ == "__main__":
    main()
