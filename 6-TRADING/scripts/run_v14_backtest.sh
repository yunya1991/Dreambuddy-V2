#!/bin/bash
# v14.0 全量回测脚本
# 用法: bash run_v14_backtest.sh
set -e

OUTDIR="/mnt/c/tmp/v14_results"
mkdir -p "$OUTDIR"

echo "============================================"
echo " 6-TRADING v14.0 全量回测"
echo " 方案A: BTC牛市信号增强 (涨分+过热减仓)"
echo " 方案B: ETH波动率自适应 (vol_mult↑ + L2c↑)"
echo "============================================"
echo ""

declare -A PERIODS
PERIODS["bear"]="2025-11-27 2026-05-26"
PERIODS["bull"]="2024-11-01 2025-05-31"
PERIODS["long"]="2023-01-01 2026-05-26"

COINS=("BTC-USDT-SWAP" "SOL-USDT-SWAP" "ETH-USDT-SWAP")

run_one() {
    local coin=$1 period=$2 from=$3 to=$4
    local out="$OUTDIR/${coin//-/_}_${period}.json"
    echo "  [$coin] $period ($from ~ $to) ..."
    python3 backtest_engine_main.py \
        --inst "$coin" --from "$from" --to "$to" --capital 200 \
        --output "$out" 2>&1 | tail -5
}

for coin in "${COINS[@]}"; do
    echo "=== $coin ==="
    for period in bear bull long; do
        read from to <<< "${PERIODS[$period]}"
        run_one "$coin" "$period" "$from" "$to"
    done
    echo ""
done

echo ""
echo "============================================"
echo " 回测完成! 结果目录: $OUTDIR"
echo "============================================"

# 汇总
python3 -c "
import json, os, glob

print()
print(f'{'币种':<10} {'周期':<6} {'收益率':>8} {'MaxDD':>8} {'Sharpe':>8} {'胜率':>8} {'交易':>6}')
print('-' * 60)

for f in sorted(glob.glob('$OUTDIR/*.json')):
    d = json.load(open(f))
    name = os.path.basename(f).replace('.json','').replace('_','-',1)
    parts = name.rsplit('_',1)
    coin = parts[0].replace('_','-')
    period = parts[1]
    print(f'{coin:<10} {period:<6} {d[\"total_return\"]:>+7.2f}% {d[\"max_drawdown\"]:>7.2f}% {d[\"sharpe_ratio\"]:>7.2f} {d[\"win_rate\"]:>7.1f}% {d[\"total_trades\"]:>5}')
"
