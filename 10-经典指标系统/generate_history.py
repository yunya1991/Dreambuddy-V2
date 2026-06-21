import os
import sys
import random
import time
import json
import logging
import math
from datetime import datetime, timedelta

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOG = logging.getLogger("import_history")

# Add project root to path to import ml_trade_service utils if needed
sys.path.append(os.getcwd())

COINS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "TRX", "DOT",
    "LINK", "MATIC", "LTC", "SHIB", "UNI", "BCH", "ATOM", "XLM", "NEAR", "ICP",
    "FIL", "HBAR", "APT", "VET", "LDO", "ARB", "OP", "RNDR", "INJ", "GRT",
    "MKR", "STX", "AAVE", "IMX", "SNX", "EGLD", "THETA", "SAND", "EOS", "AXS",
    "APE", "MANA", "FLOW", "FTM", "XTZ", "ALGO", "KAVA", "MINA", "CHZ", "QNT"
]

DATA_DIR = "user_data/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def generate_5m_data(coin, n_days=60):
    # Generate 60 days of 5m data to ensure we have enough history for 7d turnover and indicators
    n_candles = n_days * 24 * 12 
    now = int(time.time() * 1000)
    # Align to nearest 5m
    now = (now // (5 * 60 * 1000)) * (5 * 60 * 1000)
    
    candles = []
    
    # Base price random
    price = 100.0
    if coin == "BTC": price = 40000.0
    elif coin == "ETH": price = 2200.0
    elif coin == "SOL": price = 90.0
    else: price = random.uniform(0.5, 50.0)
    
    start_ts = now - (n_candles * 5 * 60 * 1000)
    
    # 5m Volume base (Hourly 1M -> 5m is 1M/12 approx 83k)
    vol_base_usd = 1000000.0 / 12.0
    vol_base_coin = vol_base_usd / price
    
    # Add some trend/seasonality
    trend = random.choice([-1, 0, 1]) * 0.00005
    
    current_price = price
    
    for i in range(n_candles):
        ts = start_ts + (i * 5 * 60 * 1000)
        
        # Random walk
        # 5m volatility is lower than hourly
        ret = random.gauss(trend, 0.005) # 0.5% volatility per 5m
        
        open_px = current_price
        close_px = current_price * (1 + ret)
        
        # High/Low
        high_px = max(open_px, close_px) * (1 + abs(random.gauss(0, 0.002)))
        low_px = min(open_px, close_px) * (1 - abs(random.gauss(0, 0.002)))
        
        # Volume spikes
        vol_mult = 1.0
        if random.random() < 0.01: vol_mult = 5.0 # Spike
        if random.random() < 0.2: vol_mult = 0.5 # Low activity
        
        vol = vol_base_coin * vol_mult * random.uniform(0.8, 1.2)
        
        # Update volume base as price moves (to keep USD volume roughly constant)
        vol_base_coin = vol_base_usd / close_px
        
        # [ts, open, high, low, close, volume]
        candle = [ts, open_px, high_px, low_px, close_px, vol]
        candles.append(candle)
        
        current_price = close_px
        
    return candles

def save_to_data_dir(coin, candles):
    # Freqtrade format: BTC_USDT-5m.json
    # Content: list of lists
    pair = f"{coin}_USDT"
    fn = os.path.join(DATA_DIR, f"{pair}-5m.json")
    
    with open(fn, "w") as f:
        json.dump(candles, f)
    
    LOG.info(f"Saved {len(candles)} candles for {pair} to {fn}")

def main():
    LOG.info(f"Generating history for {len(COINS)} coins in {DATA_DIR}...")
    for coin in COINS:
        candles = generate_5m_data(coin)
        save_to_data_dir(coin, candles)
    LOG.info("Done.")

if __name__ == "__main__":
    main()
