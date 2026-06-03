# Screen1 A1→A2→A3 Synthesis Flow

How to execute the Phase-2 synthesis chain when annotation files are ready.
This reference documents the procedure learned from the 2026-06-02 Screen1 execution.

## Inputs (must exist before starting)
- `screen1_cycle_annotation.json`
- `screen1_miner_annotation.json`
- `screen1_onchain_annotation.json`
- `screen1_macro_annotation.json`
- `screen1_cross_market_annotation.json`
- Current BTC price (one Tavily/web_search query)

## A1 — 矛盾论深度研究 (Contradiction Analysis)

**Goal**: Identify the primary contradiction between bullish and bearish signals across all
dimensions, and surface cognitive biases.

**Structure**:
```
Bull case (list top 3-5 arguments with data):
  - Which dimensions score BULL? What's their strongest evidence?
  - Example: Onchain RHODL=4.5 → only 3 occurrences in history, all major bottoms

Bear case (list top 3-5 arguments with data):
  - Which dimensions score BEAR? What's their strongest evidence?
  - Example: Technical MA200 below + monthly MACD death cross

Key contradiction:
  - Which dimensions disagree most strongly?
  - Is this a genuine contradiction or a known pattern (e.g., ETF-era onchain-leading-technical)?

Cognitive bias check (mandatory, 3 items):
  - Anchoring: Is prior direction anchoring current assessment?
  - Availability: Is recent price action biasing probability estimates?
  - Representativeness: Is the current market stage being compared to the wrong historical analog?
```

## A2 — 第一性原理 (First Principles)

**Goal**: Derive minimum resistance path from supply/demand fundamentals, independent of
indicator signals.

**Structure**:
```
Supply side:
  - Daily issuance (post-halving)
  - Miner selling pressure (MPI)
  - LTH supply lockup (RHODL)
  - ETF holdings (locked supply)
  → Net floating supply assessment

Demand side:
  - ETF flows (weekly, institutional)
  - M2 growth → demand conduction lag
  - 10Y yield → institutional opportunity cost
  - Retail sentiment (NUPL/Fear&Greed)
  → Net demand trajectory

Minimum resistance path: Short-term vs medium-term vs long-term
```

## A3 — 沙盘推演 + 贝叶斯校准 (Scenario Analysis)

**Goal**: Three scenarios with probabilities, triggers, and a calibrated composite score.

### Scenarios
```
S1 (Bull case, probability X%):
  Trigger conditions, BTC target, score contribution
S2 (Base case, probability Y%):
  Trigger conditions, BTC target, score contribution
S3 (Bear case, probability Z%):
  Trigger conditions, BTC target, score contribution
```
Probabilities must sum to 100%.

### Red Team Challenge
Two counter-arguments to the dominant scenario, with rebuttals.

### Bayesian Calibration
```
Prior: Previous screen1_direction and score
Evidence weighting:
  - Onchain dimension score × 0.15
  - Macro dimension score × 0.10
  - Cross-market score × 0.05
  - Miner dimension score × 0.15
  - Cycle dimension score × 0.15
  - Technical (estimated) × 0.40

Weighted sum → raw_score (negative=bear, positive=bull)
Convert to 0-100 scale: screen1_score = raw_score + 50, clamped [0,100]
Bayesian update: if onchain+macro signals converge strongly in one direction,
  adjust ±3-5 points toward convergence direction
```

### Output
- `screen1_direction`: SHORT|LONG (anchored by MA200 3-day confirmation)
- `screen1_score`: 0-100 (0=extreme bear, 50=neutral, 100=extreme bull)
- `red_team_flag`: true|false
- `adjusted_score`: final score after Bayesian update

## Pitfalls

### PITFALL: Treating Stage 6 as mid-cycle bear
Stage 6 (去库存期, days 720-1080) is the LATE phase of the bear market — historically
the period when accumulation begins and bottom structure forms. Don't treat it the same
as Stage 5 (熊市确认, days 540-720) which is the early crash phase. The latter half of
Stage 6 often shows strong onchain bottom signals.

### PITFALL: Overweighting technical when onchain is unanimous
When all 4 onchain indicators (MVRV Z, NUPL, RHODL, STH-MVRV) agree on a bottom signal,
and this conflicts with technical (MA200 below), the onchain signal carries more weight
for medium-term direction because onchain leads technical by 2-4 months. The Screen1
direction stays SHORT (MA200 anchor rule) but the score should reflect weakening conviction.

### PITFALL: Not checking annotation freshness before synthesis
If any annotation has `generated_at` older than `freshness_days`, the synthesis should
either re-run that dimension or reduce confidence weighting for it.

## Session State Fields to Update After Synthesis

```
screen1_direction        ← MA200 anchor
screen1_score            ← adjusted_score from A3
screen1_btc_price_basis  ← current BTC price
screen1_valid_until      ← today + 7 days
screen1_session_id       ← YYYYMMDD-BTC-SCREEN1
screen1_gate_level       ← FULL/PARTIAL/BASELINE
screen1_clock_stage      ← from cross_market annotation
screen1_skill_regime     ← WEAK_BEAR/WEAK_BULL/STRONG_BEAR/STRONG_BULL/CONSOLIDATION
screen1_red_team_flag    ← from A3
last_screen1_date        ← today
```
