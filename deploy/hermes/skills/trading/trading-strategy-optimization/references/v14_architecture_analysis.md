# V14 Architecture Analysis

## Design Philosophy: "牛市更积极，熊市不动，ETH给予波动率空间"

V14 = V13 + 4 targeted changes, all in 2 files (strategy.py + engine_main.py).

## Change Summary

| # | What | Where | Trigger |
|---|------|-------|---------|
| A1 | signal_score +8 | Screen2, before clamp | STRONG_BULL + LONG + RSI[50,75] |
| A2 | position x 0.5 | Screen2, after sizing | STRONG_BULL + LONG + RSI>75 |
| B1 | ETH vol_mult 1.30→1.50 | _STATIC_REGIME_VOL_MULT | All ETH scenarios |
| B2 | ETH L2c SHORT 1.20→1.25 | check_exit_signals | ETH + SHORT + Level>=1 |

## A1/A2 Mechanism

RSI=65 (healthy bull): score 73→81, MEDIUM→STRONG, position 10.5%→15%
RSI=55 (mid-range): score 73→81, MEDIUM→STRONG, position 10.5%→15%  <- KEY conversion
RSI=78 (overbought): A1 skipped (RSI>75), A2 halves position to 5.25%

Net effect: bigger wins in healthy bull, smaller losses when chasing tops.

## B1/B2 Mechanism

ETH vol_mult 1.30→1.50: addon gap 10.4%→12%, TP 5.2%→6%
ETH L2c SHORT 1.20→1.25: chain survives ETH noise without premature stop

Example ($2000 SHORT):
V13: L1=$1,792, L2c stop=$2,150 (needs 13.3% reversal)
V14: L1=$1,760, L2c stop=$2,200 (needs 25% reversal)

## Boundary: What V14 does NOT change

| Scenario | A1 | A2 | B1 | B2 |
|----------|----|----|----|-----|
| STRONG_BULL + LONG + RSI[50,75] | YES | - | YES(ETH) | YES(ETH SHORT) |
| STRONG_BULL + LONG + RSI>75 | - | YES | YES(ETH) | YES(ETH SHORT) |
| WEAK_BULL any RSI | - | - | YES(ETH) | YES(ETH SHORT) |
| CONSOLIDATION | - | - | YES(ETH) | YES(ETH SHORT) |
| STRONG_BEAR | - | - | YES(ETH) | YES(ETH SHORT) |
| BTC/SOL non-BULL | - | - | - | - |

SOL is completely unchanged. BTC unchanged in bear/consolidation.

## Complete Decision Tree

Screen1 (Weekly)
  -> direction (LONG/SHORT/WAIT)
  -> regime (STRONG_BULL/WEAK_BULL/CONSOLIDATION/WEAK_BEAR/STRONG_BEAR)
  -> vol_mult (dynamic HV-based)
  -> position_limit_pct (60/40/20)

Screen2 (Daily)
  -> signal_score (4-dim: EMA trend + MACD + RSI + volume)
    -> A1: +8 bonus (STRONG_BULL+LONG+RSI healthy)
  -> MA zone (ABOVE_ALL/BELOW_ALL/IN_ZONE)
    -> ABOVE_ALL/BELOW_ALL: martin, no ma_zone_opened
    -> IN_ZONE: single-layer reversal, ma_zone_opened=True
  -> position = limit x strength_mult x regime_mult / 4
    -> A2: x0.5 (STRONG_BULL+LONG+RSI>75)
  -> addon_levels: compound 8% x vol_mult
  -> tp_target: 4% x vol_mult

Engine
  -> Open: direction valid + signal sufficient
  -> Add-on: equal size, max 3, signal>=50
  -> Close: L1a(TP)/L1b(Level3 SL)/L2(reversal)/L2b(regime)/L2c(avg x 1.20)/L4(20% DD)
    -> B2: ETH SHORT L2c -> avg x 1.25

## Upgrade Criteria

| Coin | Period | V13 Sharpe | V13 MaxDD | Target |
|------|--------|-----------|-----------|--------|
| BTC | Bull | 0.85 | 1.06% | Sharpe up, MaxDD stable |
| BTC | Bear | 1.50 | 0.82% | Unchanged |
| SOL | All | - | - | Completely unchanged |
| ETH | Long | -0.42 | 18.43% | Return up, MaxDD down |
