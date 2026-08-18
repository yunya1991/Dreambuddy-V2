# Screen 2 Order Plan — 20260526-BTC-SCREEN2-v2

**Date**: 2026-05-26  
**Symbol**: BTC-USDT-SWAP  
**Direction**: SHORT (futures_martingale)  
**Data Source**: Tavily Real-time  
**Screen1 Basis**: $76,981, Score 72  

---

## Market Context

| Factor | Value | Signal |
|--------|-------|--------|
| BTC Current Price | ~$76,750 (May 24) | Below resistance band |
| Funding Rate | -6% (3-month low) | Short Squeeze Risk: 40% |
| ETF 7-day Flow | -$1.42B | BEAR - institutional exit |
| Recent Low | $74,344 | Key support |
| Resistance Band | $77K-$80K | Former support → now resistance |
| CME Gap | $79K-$84K | Magnetic pull risk |

---

## Entry Plan (Scenario S1 — Default, 45%)

**Entry Trigger**: Wait for price to bounce to $77,500–$78,500, confirm 1h rejection candle (bearish engulfing, upper shadow), volume declining.

| Level | Action | Price | Size | Condition |
|-------|--------|-------|------|-----------|
| L0 | Open SHORT | $77,500 | 30% | 1h rejection at resistance band lower |
| L1 | Add SHORT | $79,000 | 40% | Price pumps to CME gap lower bound |
| L2 | Add SHORT | $80,500 | 30% | Near CME gap middle — final add |
| **SL** | Close ALL | **$81,500** | 100% | Hard stop — no exceptions |
| TP1 | Close 60% | $74,500 | 60% | Recent low support |
| TP2 | Close 40% | $72,000 | 40% | Structural target |

**Risk/Reward (L0)**: Entry $77,500 → SL $81,500 = -5.2% | TP1 $74,500 = +3.9% → **RR 0.75:1 per unit** (but martingale averages improve overall)

---

## Adaptive Plan (Scenario S2 — Short Squeeze, 35%)

**Trigger**: Price breaks $78,500 with volume > 120% average → switch to S2.

| Level | Action | Price | Size | Condition |
|-------|--------|-------|------|-----------|
| L0 | Open SHORT | $79,000 | 25% | Post-squeeze, 1h bearish divergence |
| L1 | Add SHORT | $80,500 | 40% | CME gap mid — squeeze likely exhausted |
| L2 | Add SHORT | $81,200 | 35% | Final add near hard stop |
| **SL** | Close ALL | **$81,800** | 100% | Tight stop for post-squeeze entries |
| TP1 | Close 60% | $75,000 | 60% | Conservative target |
| TP2 | Close 40% | $72,000 | 40% | Main target |

---

## Stop Loss Protocol (Scenario S3 — Bull Reversal, 20%)

- Daily close > $81,000 → trigger S3 protocol
- Execute hard stop at $81,500 on ALL positions
- No new short positions
- Await Screen 1 re-score before re-entry

---

## Risk Management

- **Total max exposure**: 30% of capital across all levels
- **Funding cost**: -6% rate → ~0.18%/day at 30% position (budget 3-5 days max)
- **DO NOT** add positions above $81,500
- **Composite confidence**: 64/100 (lower than Screen1 due to -6% funding risk)

---

## A7 Gate Pre-Check

- [x] Screen1 direction (SHORT) confirmed valid (< 14 days)
- [x] Entry zone defined ($77,000–$79,000)
- [x] Stop loss set ($81,500, structure-based)
- [x] Risk/reward assessed (TP1 = +3.9% vs SL = -5.2% from L0)
- [ ] A4 validation pending (requires Team B execution confirmation)
