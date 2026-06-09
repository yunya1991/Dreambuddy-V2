# V0 Signal System Specification (Daily Adaptation)

Source: `6-TRADING/baselines/v0-crypto-signal-bot-20260526/crypto_backtest.py`
Original: 1H timeframe, adapted to 1D for v15.0 integration.

## Signal Architecture

8 conditions, symmetric LONG/SHORT, each weighted 1-2 points.
Max score = 14 (2+2+1+2+2+2+2+1).

## Conditions (Daily Adaptation)

| # | Condition | Weight | LONG trigger | SHORT trigger | Daily proxy |
|---|-----------|--------|-------------|---------------|-------------|
| 1 | MACD golden/death cross | 2 | prev MACD<Signal, curr MACD>Signal | prev MACD>Signal, curr MACD<Signal | MACD from indicators |
| 2 | MACD vs Signal line | 2 | MACD > Signal | MACD < Signal | MACD from indicators |
| 3 | MACD vs zero | 1 | MACD > 0 | MACD < 0 | MACD from indicators |
| 4 | RSI healthy zone | 2 | 35 <= RSI < 70 | 30 < RSI <= 65 | RSI14 from indicators |
| 5 | RSI extreme | 2 | RSI < 35 | RSI > 65 | RSI14 from indicators |
| 6 | Price vs BB midline | 2 | Price > SMA20 | Price < SMA20 | SMA20 computed on-the-fly |
| 7 | Fast vs Slow MA | 2 | SMA7 > SMA25 | SMA7 < SMA25 | SMA7/SMA25 computed on-the-fly |
| 8 | Volume spike | 1 | vol_ratio > 1.5 | vol_ratio > 1.5 | vol_ratio from indicators |

## Threshold Logic

Normal: threshold = ceil(14 x 0.57) = 8
RSI extreme (>90 or <10): threshold = ceil(10 x 0.50) = 5

## Signal Classification

STRONG if score/max >= 0.75
MEDIUM if score/max >= 0.57
WEAK otherwise (direction != WAIT)

## V0 1H Baseline Results (reference only)

| Metric | BTC | SOL | ETH |
|--------|-----|-----|-----|
| 6-month return | +8.78% | +68.68% | -8.67% |
| MaxDD | 18.25% | 17.60% | 32.91% |
| Sharpe | 0.715 | 3.022 | -0.336 |
| Win rate | 51.2% | 57.2% | 46.1% |
| Total trades | 573 | 538 | 558 |

Daily adaptation results: UNKNOWN (v15.0 not yet backtested).
