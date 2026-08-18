import json
import math
from pathlib import Path

import pandas as pd

from user_data.strategies.TurtleTradingStrategy import TurtleTradingStrategy
from user_data.strategies.BollingerBandMeanReversionStrategy import BollingerBandMeanReversionStrategy
from user_data.strategies.RsiMeanReversionStrategy import RsiMeanReversionStrategy
from user_data.strategies.MacdTrendFollowingStrategy import MacdTrendFollowingStrategy
from user_data.strategies.IchimokuCloudTrendStrategy import IchimokuCloudTrendStrategy
from user_data.strategies.ParabolicSarTrendStrategy import ParabolicSarTrendStrategy
from user_data.strategies.KeltnerChannelBreakoutStrategy import KeltnerChannelBreakoutStrategy
from user_data.strategies.AroonTrendSystemStrategy import AroonTrendSystemStrategy
from user_data.strategies.Nr7VolatilityContractionBreakoutStrategy import Nr7VolatilityContractionBreakoutStrategy
from user_data.strategies.StochasticOscillatorReversalStrategy import StochasticOscillatorReversalStrategy


STRATEGIES = [
    TurtleTradingStrategy,
    BollingerBandMeanReversionStrategy,
    RsiMeanReversionStrategy,
    MacdTrendFollowingStrategy,
    IchimokuCloudTrendStrategy,
    ParabolicSarTrendStrategy,
    KeltnerChannelBreakoutStrategy,
    AroonTrendSystemStrategy,
    Nr7VolatilityContractionBreakoutStrategy,
    StochasticOscillatorReversalStrategy,
]


PAIR_FILES = {
    "BTC/USDT:USDT": Path("user_data/data/gate/futures/BTC_USDT_USDT-1h-futures.json"),
    "ETH/USDT:USDT": Path("user_data/data/gate/futures/ETH_USDT_USDT-1h-futures.json"),
    "SOL/USDT:USDT": Path("user_data/data/gate/futures/SOL_USDT_USDT-1h-futures.json"),
}


def load_ohlcv(path: Path) -> pd.DataFrame:
    raw = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop(columns=["ts"]).set_index("date").sort_index()


def simulate(df: pd.DataFrame, fee_per_side: float, periods_per_year: int) -> dict:
    pos = 0
    positions = []
    trade_count = 0

    for _, row in df.iterrows():
        enter_long = int(row.get("enter_long", 0) or 0)
        enter_short = int(row.get("enter_short", 0) or 0)
        exit_long = int(row.get("exit_long", 0) or 0)
        exit_short = int(row.get("exit_short", 0) or 0)

        if pos > 0 and exit_long == 1:
            pos = 0
        elif pos < 0 and exit_short == 1:
            pos = 0

        if pos == 0:
            if enter_long == 1 and enter_short != 1:
                pos = 1
                trade_count += 1
            elif enter_short == 1 and enter_long != 1:
                pos = -1
                trade_count += 1

        positions.append(pos)

    s = pd.Series(positions, index=df.index, name="position")
    ret = df["close"].pct_change().fillna(0.0)
    strat_ret = s.shift(1).fillna(0.0) * ret

    delta = s.diff().fillna(s)
    costs = (delta.abs() > 0).astype(float) * float(fee_per_side)
    strat_ret = strat_ret - costs

    equity = (1.0 + strat_ret).cumprod()
    total_return = float(equity.iloc[-1] - 1.0)
    peak = equity.cummax()
    dd = float((equity / peak - 1.0).min())
    vol = float(strat_ret.std())
    sharpe = float(strat_ret.mean() / vol * math.sqrt(int(periods_per_year))) if vol > 0 else 0.0

    return {
        "return_pct": total_return * 100.0,
        "max_drawdown_pct": dd * 100.0,
        "sharpe": sharpe,
        "trades": int(trade_count),
    }


def main() -> int:
    timerange_start = pd.Timestamp("2025-10-01T00:00:00Z")
    timerange_end = pd.Timestamp("2026-01-24T12:00:00Z")
    fee = 0.0004
    periods_per_year = 24 * 365

    rows = []
    for pair, path in PAIR_FILES.items():
        if not path.exists():
            raise FileNotFoundError(str(path))
        base = load_ohlcv(path)
        base = base.loc[(base.index >= timerange_start) & (base.index <= timerange_end)].copy()
        for Strat in STRATEGIES:
            st = Strat({})
            d = base.copy()
            d = st.populate_indicators(d, {})
            d = st.populate_entry_trend(d, {})
            d = st.populate_exit_trend(d, {})
            m = simulate(d, fee_per_side=fee, periods_per_year=periods_per_year)
            rows.append({"pair": pair, "strategy": Strat.__name__, **m})

    out = pd.DataFrame(rows)
    avg = (
        out.groupby("strategy")[["return_pct", "max_drawdown_pct", "sharpe", "trades"]]
        .mean(numeric_only=True)
        .reset_index()
        .sort_values("return_pct", ascending=False)
    )

    payload = {
        "timerange": {"start": str(timerange_start), "end": str(timerange_end)},
        "fee_per_side": fee,
        "pairs": list(PAIR_FILES.keys()),
        "per_pair": out.to_dict(orient="records"),
        "average": avg.to_dict(orient="records"),
    }

    out_dir = Path("user_data/backtest_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "offline_backtest_summary_10_strategies.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    top = avg.head(10).copy()
    top["return_pct"] = top["return_pct"].map(lambda x: round(float(x), 2))
    top["max_drawdown_pct"] = top["max_drawdown_pct"].map(lambda x: round(float(x), 2))
    top["sharpe"] = top["sharpe"].map(lambda x: round(float(x), 2))
    top["trades"] = top["trades"].map(lambda x: int(round(float(x))))
    print("summary_file=", str(out_path))
    print(top.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

