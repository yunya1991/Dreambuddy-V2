---
name: trading-strategy-optimization
description: End-to-end workflow for optimizing 6-TRADING backtest strategies. Covers code archaeology, root-cause diagnosis, proposal design within V9 constraints, implementation, and backtest execution. Used when user asks to improve strategy metrics (Sharpe, MaxDD, returns) for specific coins or market regimes.
category: trading
---

# Trading Strategy Optimization Skill

## Trigger Conditions
- User asks to "improve Sharpe", "reduce MaxDD", "fix underperformance" for 6-TRADING
- User asks to "设计优化方案" or "分析根因" for backtest results
- User says "based on these baselines, design an improvement" or similar
- Any request involving modifying backtest_strategy.py or backtest_engine_main.py
- **User asks to design architectural/system-level trading logic** (e.g., "架构6-Trading", "第一屏策略", "牛熊多空方向", "市场形态", "交易标的", "调研传统金融指标")
- User asks to compare indicator timing/effectiveness across asset classes or timeframes

## Core Constraint: V9 Rules Are Sacred

The V9 martin rules are the user's empirical baseline and MUST NOT be modified:

| Rule | Value | Meaning |
|------|-------|---------|
| addon_gap_pct | 8% × vol_mult | Compound addon interval |
| tp_pct | 4% × vol_mult | Single full-position take profit |
| max addon levels | 3 | Initial + 3 addons (Level 0→1→2→3) |
| Fixed stop loss | None | Removed in v8.0 |

All optimizations must **layer on top** of these rules, not replace them. You CAN change:
- vol_mult (already dynamic via HV calculation)
- Signal scoring weights and bonuses
- Position sizing multipliers (regime-aware)
- Exit thresholds (L2c multipliers, regime triggers)
- Regime detection parameters
- MEC thresholds

## Step-by-Step Workflow

### Step 1: Code Archaeology
Read the three core files in this order:
1. `backtest_strategy.py` — The strategy brain (Screen1, Screen2, check_exit_signals, all version history in docstring)
2. `backtest_engine_main.py` — The backtest engine (position management, stats, how strategy functions are called)
3. `backtest_data_fetcher.py` — Data source and indicator calculations

Also read:
4. V13 baseline: `6-TRADING/baselines/v9-six-trading-20260601/BASELINE_SUMMARY.md`
5. V12 baseline: `6-TRADING/baselines/v8-six-trading-20260601/BASELINE_SUMMARY.md`

The docstring at the top of backtest_strategy.py contains the COMPLETE version history (v3→v13), which is essential for understanding what was tried before and why.

### Step 2: Root Cause Diagnosis
For each underperforming metric, trace through the exact code path:

**Example: BTC Bull Sharpe 0.85**
- Trace: Screen2 score calculation (L827-875) → signal_strength → position sizing (L921-931)
- Discovery: RSI>70 subtracts 10 from score in STRONG_BULL → MEDIUM signal → smaller position
- Root cause: No directional premium for bull vs bear entries

**Example: ETH Long-term -3.88%**
- Trace: vol_mult=1.30 → addon_gap=10.4% → L2c at avg×1.20
- Discovery: Gap too tight for ETH's actual volatility → frequent addon triggers → L2c stops chains
- Root cause: Static vol_mult floor (1.30) doesn't reflect ETH's real volatility profile

Always verify: "Does this change affect the V9 core rules?" If yes, redesign.

### Step 3: Design Proposals
Present proposals in a structured format:

```
### 方案 X: [Name]

| # | 改动 | 当前值 | 新值 | 逻辑 |
|---|------|--------|------|------|
| X1 | ... | old | new | Why this works |

Critical design principles:
- Each change must have a clear trigger condition (regime + direction + indicator state)
- Changes should be gated by coin (inst_id check) when coin-specific
- BTC/SOL that aren't targeted should be completely unaffected
- Every change must answer: "What happens in the OTHER regime?"

Include an "upgrade criteria" table comparing V13 baseline vs expected v14.0.
```

### Step 4: Get Approval
Present both proposals to the user. Do NOT implement until explicitly approved.
The user will say "认可" or "通过" or request modifications.

### Step 5: Implement Changes
Make targeted patches to the minimum files needed:

**Typical change locations:**
| Change type | File | Target section |
|-------------|------|----------------|
| Signal scoring | backtest_strategy.py | run_screen2(), before score clamping |
| Position sizing | backtest_strategy.py | run_screen2(), after single_layer_pct calc |
| vol_mult tuning | backtest_strategy.py | _STATIC_REGIME_VOL_MULT dict |
| Exit thresholds | backtest_strategy.py | check_exit_signals(), L2c section |
| Engine wiring | backtest_engine_main.py | check_exit_signals call site |

After each patch, verify with `patch` tool's diff output. Add `# v14.0-XX:` comment markers on every changed line for traceability.

### Step 6: Verify Syntax
Run a quick import check before running backtests:
```bash
python3 -c "from backtest_strategy import *; print('OK')"
python3 -c "from backtest_engine_main import BacktestEngine; print('OK')"
```

### Step 7: Run Backtests
The standard test matrix is 3 coins × 3 periods = 9 runs:

| Period | Start | End | Purpose |
|--------|-------|-----|---------|
| Bull | 2024-11-01 | 2025-05-31 | Test LONG-dominant regime |
| Bear | 2025-11-27 | 2026-05-26 | Test SHORT-dominant regime |
| Long | 2023-01-01 | 2026-05-26 | Full cycle validation |

Use `--output <path>.json` to save each result, then run a Python summary script to compare all 9 results against V13 baseline.
The reference batch script is at `references/run_backtest_batch.sh`.

### Optimization Pattern A: Parameter Tuning (v14.0 style)
Layer regime-aware adjustments on top of existing Screen2 scoring:
- Signal score bonuses (e.g., +8 in STRONG_BULL+LONG+healthy RSI)
- Position sizing multipliers (e.g., ×0.5 when RSI>75 in STRONG_BULL)
- vol_mult floor adjustments (e.g., ETH 1.30→1.50)
- Exit threshold tuning (e.g., ETH L2c SHORT 1.20→1.25)

Gate everything with explicit `screen1.regime == "STRONG_BULL"` and `inst_id == "ETH-USDT-SWAP"` checks. Coins not targeted must be completely unaffected.

### Optimization Pattern B: Signal Engine Replacement (v15.0 style)
Replace the ENTIRE signal scoring engine while keeping V9 martin + L2b/L2c + MA zones intact.

**When to use**: When the existing Screen2 scoring (4 ad-hoc dimensions) is fundamentally suboptimal compared to a cleaner signal system (e.g., V0's 8-condition symmetric scoring).

**How to implement**:
1. Study the replacement signal system thoroughly (V0's calc_signal_at from `crypto_backtest.py`)
2. Adapt it to daily candles: V0 originally used 1H candles + SMA7/25 + BB, daily adaptation uses SMA7/25 + SMA20 as BB midline proxy
3. Replace the entire Screen2 scoring block (L834-886 in current code) with the new signal logic
4. The new signal generates its OWN direction (v0_direction), independent of Screen1
5. Pipe v0_direction through: Screen2Output → engine's _open_position → effective_direction for TP/addon calculations
6. Fix all downstream references that assume Screen1 direction (BELOW_ALL_BLOCKED check, A2 RSI overheat, position sizing)

**Key wiring checklist**:
- Add `v0_direction` field to `Screen2Output` dataclass
- Set `v0_direction` in `run_screen2` return statement
- Engine: check `screen2.v0_direction is not None` in open-position gate
- Engine: use `screen2.v0_direction` for open_dir in log output
- `effective_direction` calculation: MA signal > V0 signal > Screen1
- `total_limit` calculation: use V0 signal_strength mapping (STRONG→0.60, MEDIUM→0.40, WEAK→0.20)
- `BELOW_ALL_BLOCKED` gate: check `effective_screen1_direction` not `screen1.direction`
- A2 RSI overheat: check `effective_screen1_direction`, not `screen1.regime` or `screen1.direction`

**V0 signal spec (daily adaptation)**:
- 8 conditions, symmetric LONG/SHORT, each 1-2 points, max_score=14
- Threshold: ceil(max_score × 0.57) = 8 (or ceil((max-4)×0.50) when RSI extreme)
- STRONG if score/max ≥ 0.75
- Uses SMA7/25 computed on-the-fly from close prices
- Uses SMA20 as Bollinger midline proxy
- MACD/RSI/Volume from existing indicators
The reference batch script is at `references/run_backtest_batch.sh`.

### Step 8: Compare vs Baseline
Create a comparison table:

| Coin | Period | Metric | V13 | v14.0 | Δ | Pass? |
|------|--------|--------|-----|-------|---|-------|
| BTC | Bull | Sharpe | 0.85 | ? | ? | ? |

Success criteria from the user:
- BTC bull Sharpe must improve (target: >0.85, ideally 1.5+)
- ETH long-term must trend toward positive
- Unchanged coins/periods must remain stable
- MaxDD must not degrade significantly

## Key Files Reference

| File | Path | Role |
|------|------|------|
| Strategy | `C:/tmp/backtest_strategy.py` | All strategy logic, Screen1/2/exit |
| Engine | `C:/tmp/backtest_engine_main.py` | Backtest loop, stats, CLI |
| Data | `C:/tmp/backtest_data_fetcher.py` | OKX API, indicators, caching |
| V13 Baseline | GitHub: `6-TRADING/baselines/v9-six-trading-20260601/` | Current baseline numbers |
| V12 Baseline | GitHub: `6-TRADING/baselines/v8-six-trading-20260601/` | Previous baseline for comparison |

## Pitfalls

### PITFALL: Changing vol_mult globally without checking Regime impact
vol_mult affects multiple systems: addon gap, TP target, Regime thresholds (STRONG_BEAR detection uses 20×vol_mult), MEC proximity thresholds. When raising vol_mult for one purpose (wider gaps), verify it doesn't break Regime classification. For ETH specifically: raising vol_mult 1.30→1.50 means STRONG_BEAR triggers at -30% instead of -26% — this could reclassify bearish periods as CONSOLIDATION, inadvertently allowing more LONG entries.

### PITFALL: Forgetting to wire new parameters through the engine
When adding a parameter to a strategy function (e.g., inst_id to check_exit_signals), you MUST also update the engine's call site (backtest_engine_main.py). The strategy functions don't auto-receive config — they only get what the engine passes.

### PITFALL: Not checking "what about the other regime?"
Every bullish optimization must answer: "What happens in BEAR?" Every bearish optimization must answer: "What happens in BULL?" Gate all regime-specific changes with explicit `screen1.regime == "STRONG_BULL"` checks.

### PITFALL: Network restrictions preventing backtest execution
Exchange APIs (OKX, Binance) may be blocked in some environments. Tavily API usually works. If backtests can't run:
1. Check for cached CSV data in `data/backtest/`
2. If none exists, provide the user with a self-contained bash script (`run_v14_backtest.sh`) and instructions to run locally
3. Do NOT spend more than 2 attempts trying alternative APIs — fall back to the script approach

### PITFALL: Windows CRLF line endings break patch tool
The `backtest_strategy.py` and `backtest_engine_main.py` files use Windows CRLF (`\r\n`) line endings (visible with `cat -A`). The `patch` tool sometimes fails with "Escape-drift detected" when old_string contains escaped quotes mixed with CRLF. Fix: use `read_file` to inspect the exact bytes, then construct old_string with the matching CRLF endings. If a patch rejects with "Escape-drift", re-read the target lines and match the exact content character-for-character.

### PITFALL: Git push hangs without error = auth OK, network slow
If `git push` shows "Pushing to https://github.com/..." and hangs (no 403, no error, just timeout), the authentication SUCCEEDED but the transfer is slow. The repo may be large or the network to GitHub is congested. Fall back to GitHub Contents API for small file sets (≤5 files). The API is faster because it transfers only the changed files, not the entire repo.

### PITFALL: GitHub token auth — fine-grained vs classic PAT
`github_pat_` = fine-grained (needs explicit Contents:Write for API PUT; git HTTPS push always fails). `ghp_` = classic (works everywhere). See `references/github-api-upload.md` for diagnostic API call and fallback chain.

### PITFALL: `git add` in a dirty repo stages ALL deletions
The Dreambuddy-V2 repo often has hundreds of unstaged deletions (from previous worktree operations). A bare `git add file1 file2` will also stage all tracked deletions. Always:
```bash
git reset HEAD .           # unstage everything first
git add file1 file2 ...    # then stage only target files
git status --short | head  # verify before commit
```

### PITFALL: Signal framework timeframe mismatch (V0 daily degradation)
V0's 8-condition symmetric scoring (MACD golden cross, RSI extremes, SMA7/25 cross, BB midline, volume spike) works for 1H candles because conditions correlate frequently. On DAILY candles, these correlations break down:

- SMA7/25 crosses happen months apart on daily, not hours
- RSI extreme conditions (RSI>90 or <10) occur on <0.1% of daily candles vs 5% of hourly
- 5+ conditions triggering simultaneously on daily is rare → 57% threshold (8/14) almost never met
- Result: near-zero signals, or signals so lagged they enter at the worst possible time

**The rule**: Signal frameworks tuned for one timeframe do NOT translate to another. When porting a signal system, always verify that the trigger frequency is appropriate for the new timeframe. A 500-trade/6mo system on 1H can become a 5-trade/6mo system on 1D.

**What worked instead**: The V14 approach — keep the existing Screen1/Screen2 hierarchy (weekly direction + daily timing), and layer targeted regime-aware bonuses (A1: +8 in healthy bull, A2: ×0.5 position in overbought). No signal engine replacement, just parameter tuning within the proven framework.

### PITFALL: Using MA200 crossover as the primary bull/bear signal — it's the slowest indicator
MA200 Golden/Death Cross lags actual tops/bottoms by 3-4 months on average. The indicator hierarchy from fastest to slowest:

| Indicator | Avg Lag After Top | Avg Lag After Bottom | Role |
|-----------|-------------------|---------------------|------|
| Monthly RSI (>70) | **-1 month** (leads!) | ~0 months | Early warning |
| Monthly MACD | +1.6 months | +1.6 months | Trend confirmation |
| MA200 Golden/Death Cross | +3.2 months | +4.0 months | Structural baseline |
| Coppock Curve | +6.8 months | +7.0 months | Too slow, exclude |

**Correct Screen1 architecture**: MA200 is the structural "last resort" (weight 15). Monthly RSI + MACD are the early detection engine (weight 25 combined). The Coppock Curve (designed for 11-14mo stock "mourning periods") is excluded entirely — on crypto's fast cycles it fires after the move is over.

**When user asks about Screen1 design**: refer to `references/screen1_architecture.md` for the complete 7-dimension framework, including BTC halving cycles, miner economics, on-chain MVRV/NUPL/Puell, Fed+ETF macro, Merrill Lynch clock, and tokenized stock trading targets.

### PITFALL: GitHub token auth — fine-grained vs classic PAT
Two token types behave differently. Diagnose first:

**Is it fine-grained?** `github_pat_` prefix → fine-grained. `ghp_` prefix → classic.

**Diagnostic API call (works for both):**
```python
resp = requests.get("https://api.github.com/user", headers={"Authorization": "Bearer TOKEN"})
# Check: resp.headers.get("X-OAuth-Scopes") → "NONE" = fine-grained, "repo,user" = classic
# Check permissions: GET /repos/{owner}/{repo} → resp.json()["permissions"]
```

**Fine-grained PAT quirks:**
- `X-OAuth-Scopes` header returns "NONE" even with full admin permissions — normal
- GET requests work, but PUT/POST returns 403 "Resource not accessible" when `Contents` scope is Read-only
- git HTTPS push ALWAYS fails with fine-grained tokens, even with push permission
- Solution: tell user to open token settings → Repository permissions → Contents → "Read and write"

**Classic PAT:** `ghp_` prefix, works with both git HTTPS push and API PUT.

**Fallback chain for code delivery:**
1. Classic `ghp_` token → use `git push`
2. Fine-grained token with Contents:Write → use GitHub Contents API (`PUT /repos/{owner}/{repo}/contents/{path}`)
3. Neither works → commit locally, list file paths, ask user to push manually
4. Do NOT attempt `apt-get install gh` — requires root and downloads are slow

## Reference Files
- `references/run_backtest_batch.sh` — Batch runner for 9-test matrix
- `references/v14_changelog_template.md` — Template for version changelogs
- `references/v14_architecture_analysis.md` — V14 complete architecture: decision tree, A1/A2/B1/B2 mechanisms, boundaries
- `references/v0_signal_spec.md` — V0 8-condition symmetric scoring spec (for v15.0-style signal engine replacement)
- `references/screen1_architecture.md` — **Screen1 七维牛熊评分架构**: MA200基线、经典TA早警(月线RSI+MACD)、减半周期、矿工经济、链上估值(MVRZ/NUPL/Puell)、宏观金融(Fed+ETF)、美林时钟跨市场、代币化美股三层标的体系、指标时序对比研究
