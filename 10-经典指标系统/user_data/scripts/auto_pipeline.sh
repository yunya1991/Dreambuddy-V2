#!/bin/bash

# Exit on error
set -e

# Navigate to project root (where docker-compose.yml should be)
# Script is in user_data/scripts/, so go up 2 levels
cd "$(dirname "$0")/../.."

echo "==========================================="
echo "   Auto-Optimization Pipeline Started"
echo "==========================================="

# 1. Download Data
# Uncomment the line below to enable automatic data download
# echo "[1/5] Downloading Data..."
# docker compose run --rm freqtrade download-data --exchange gate --days 30 -t 5m

# 2. Classify Volatility
echo "[2/5] Classifying Pairs by Volatility..."
# We assume the container mounts user_data to /freqtrade/user_data
docker compose run --rm freqtrade python /freqtrade/user_data/scripts/classify_volatility.py

# 3. Hyperopt - Low Volatility
echo "[3/5] Optimizing Low Volatility Pairs..."
docker compose run --rm freqtrade hyperopt \
    --strategy OptimizationStrategy \
    --config /freqtrade/user_data/config_vol_low.json \
    --epochs 50 \
    --spaces buy sell roi stoploss \
    --export-json /freqtrade/user_data/temp_low.json

docker compose run --rm freqtrade python /freqtrade/user_data/scripts/extract_params.py \
    /freqtrade/user_data/temp_low.json \
    /freqtrade/user_data/strategies/params_low.json \
    low

# 4. Hyperopt - Mid Volatility
echo "[4/5] Optimizing Mid Volatility Pairs..."
docker compose run --rm freqtrade hyperopt \
    --strategy OptimizationStrategy \
    --config /freqtrade/user_data/config_vol_mid.json \
    --epochs 50 \
    --spaces buy sell roi stoploss \
    --export-json /freqtrade/user_data/temp_mid.json

docker compose run --rm freqtrade python /freqtrade/user_data/scripts/extract_params.py \
    /freqtrade/user_data/temp_mid.json \
    /freqtrade/user_data/strategies/params_mid.json \
    mid

# 5. Hyperopt - High Volatility
echo "[5/5] Optimizing High Volatility Pairs..."
docker compose run --rm freqtrade hyperopt \
    --strategy OptimizationStrategy \
    --config /freqtrade/user_data/config_vol_high.json \
    --epochs 50 \
    --spaces buy sell roi stoploss \
    --export-json /freqtrade/user_data/temp_high.json

docker compose run --rm freqtrade python /freqtrade/user_data/scripts/extract_params.py \
    /freqtrade/user_data/temp_high.json \
    /freqtrade/user_data/strategies/params_high.json \
    high

# Cleanup
rm user_data/temp_low.json user_data/temp_mid.json user_data/temp_high.json

echo "==========================================="
echo "   Pipeline Completed Successfully"
echo "==========================================="
