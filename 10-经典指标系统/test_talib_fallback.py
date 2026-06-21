import pandas as pd


def test_talib_abstract_fallback_basics():
    import talib.abstract as ta

    df = pd.DataFrame(
        {
            "open": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "high": [2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
            "low": [0.5, 1.5, 2.5, 3.0, 4.0, 5.0, 6.2, 7.1, 8.2, 9.1],
            "close": [1.2, 2.2, 3.3, 4.2, 5.1, 6.0, 6.8, 7.9, 8.7, 9.8],
            "volume": [10, 12, 11, 15, 14, 16, 15, 13, 18, 20],
        }
    )
    rsi = ta.RSI(df, timeperiod=5)
    assert len(rsi) == len(df)
    macd = ta.MACD(df)
    assert set(macd.keys()) == {"macd", "macdsignal", "macdhist"}
    bb = ta.BBANDS(df, timeperiod=5)
    assert set(bb.keys()) == {"upperband", "middleband", "lowerband"}
