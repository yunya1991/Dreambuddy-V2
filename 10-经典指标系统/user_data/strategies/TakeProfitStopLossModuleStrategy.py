import pandas as pd
from pandas import DataFrame
from typing import Optional, List, Union, Dict
from datetime import datetime, timezone

from freqtrade.strategy import IntParameter, DecimalParameter, BooleanParameter
from freqtrade.persistence import Trade


class TakeProfitStopLossMixin:
    """止盈止损模块（可混入任意 Freqtrade 策略类）"""

    trailing_stop_pct = DecimalParameter(0.005, 0.05, default=0.01, space="protection")
    trailing_activation_offset = DecimalParameter(0.02, 0.10, default=0.05, space="protection")

    atr_multiplier = DecimalParameter(1.0, 3.0, default=1.5, space="protection")
    atr_period = IntParameter(10, 30, default=14, space="protection")

    volatility_adjust_enabled = BooleanParameter(default=True, space="protection")
    volatility_threshold_high = DecimalParameter(0.03, 0.08, default=0.04, space="protection")
    volatility_threshold_low = DecimalParameter(0.01, 0.03, default=0.02, space="protection")

    break_even_enabled = BooleanParameter(default=True, space="protection")
    break_even_profit_threshold = DecimalParameter(0.005, 0.06, default=0.02, space="protection")
    break_even_offset = DecimalParameter(-0.01, 0.01, default=0.0, space="protection")

    chandelier_enabled = BooleanParameter(default=True, space="protection")
    chandelier_atr_multiplier = DecimalParameter(1.0, 6.0, default=3.0, space="protection")

    time_stop_1h = DecimalParameter(-0.10, -0.01, default=-0.05, space="protection")
    time_stop_4h = DecimalParameter(-0.15, -0.03, default=-0.08, space="protection")
    time_stop_12h = DecimalParameter(-0.20, -0.05, default=-0.12, space="protection")

    time_exit_hours = IntParameter(24, 240, default=72, space="sell")
    quick_take_profit_1 = DecimalParameter(0.05, 0.40, default=0.20, space="sell")
    quick_take_profit_2 = DecimalParameter(0.03, 0.30, default=0.10, space="sell")
    emergency_stop_profit = DecimalParameter(-0.30, -0.05, default=-0.10, space="sell")

    def __init__(self, config: dict) -> None:
        if not hasattr(self, "_current_volatility"):
            self._current_volatility: Dict[str, float] = {}
        if not hasattr(self, "_trade_stats"):
            self._trade_stats: Dict[str, Dict[str, float]] = {}

    def _utc_dt(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _ensure_utc_index(self, dataframe: DataFrame) -> DataFrame:
        try:
            if getattr(dataframe.index, "tz", None) is None:
                dataframe.index = dataframe.index.tz_localize("UTC")
            else:
                dataframe.index = dataframe.index.tz_convert("UTC")
        except Exception:
            pass
        return dataframe

    def _stoploss_pct_from_price(self, is_short: bool, stop_price: float, current_rate: float) -> Optional[float]:
        if stop_price <= 0 or current_rate <= 0:
            return None
        if is_short:
            return (current_rate - stop_price) / current_rate
        return (stop_price - current_rate) / current_rate

    def _get_volatility_factor(self, volatility: float) -> float:
        if not self.volatility_adjust_enabled.value:
            return 1.0
        if volatility > self.volatility_threshold_high.value:
            return 1.5
        if volatility < self.volatility_threshold_low.value:
            return 0.7
        return 1.0

    def _entry_atr(self, dataframe: DataFrame, entry_date_utc: datetime) -> Optional[float]:
        try:
            df = self._ensure_utc_index(dataframe.copy())
            mask = df.index <= entry_date_utc
            if not mask.any():
                return None
            atr = df.loc[mask].iloc[-1].get("atr", None)
            if atr is None or pd.isna(atr):
                return None
            atr_f = float(atr)
            if atr_f <= 0:
                return None
            return atr_f
        except Exception:
            return None

    def _get_current_volatility(self, pair: str, dataframe: Optional[DataFrame] = None) -> float:
        if pair in self._current_volatility:
            return self._current_volatility[pair]

        try:
            if dataframe is None and hasattr(self, "dp") and self.dp is not None:
                dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is not None and len(dataframe) > 0 and "atr_pct" in dataframe.columns:
                atr_pct = dataframe["atr_pct"].iloc[-1]
                if not pd.isna(atr_pct):
                    self._current_volatility[pair] = float(atr_pct)
                    return float(atr_pct)
        except Exception:
            pass

        return 0.02

    def _time_stop(self, hold_hours: float, base_stop: float) -> float:
        if hold_hours < 1:
            return float(self.time_stop_1h.value)
        if hold_hours < 4:
            return float(self.time_stop_4h.value)
        if hold_hours < 12:
            return float(self.time_stop_12h.value)
        return base_stop

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        current_time_utc = self._utc_dt(current_time)
        open_date_utc = self._utc_dt(trade.open_date_utc)
        hold_hours = (current_time_utc - open_date_utc).total_seconds() / 3600

        base_stop = float(self.stoploss)
        stops: List[float] = [base_stop]

        time_stop = self._time_stop(hold_hours, base_stop)
        stops.append(time_stop)

        dataframe: Optional[DataFrame] = None
        try:
            if hasattr(self, "dp") and self.dp is not None:
                dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        except Exception:
            dataframe = None

        volatility = self._get_current_volatility(pair, dataframe)
        volatility_factor = self._get_volatility_factor(volatility)
        stops.append(time_stop * volatility_factor)

        df_ok = dataframe is not None and len(dataframe) > 0
        if df_ok:
            dataframe = self._ensure_utc_index(dataframe)

        current_atr: Optional[float] = None
        if df_ok and "atr" in dataframe.columns:
            try:
                atr_val = dataframe["atr"].iloc[-1]
                if atr_val is not None and not pd.isna(atr_val) and float(atr_val) > 0:
                    current_atr = float(atr_val)
            except Exception:
                current_atr = None

        entry_atr = self._entry_atr(dataframe, open_date_utc) if df_ok else None

        if entry_atr is not None and current_rate > 0 and float(trade.open_rate) > 0:
            atr_mult = float(self.atr_multiplier.value) * volatility_factor
            if trade.is_short:
                stop_price = float(trade.open_rate) + (entry_atr * atr_mult)
                stop_price = max(stop_price, float(current_rate) * 1.000001)
            else:
                stop_price = float(trade.open_rate) - (entry_atr * atr_mult)
                stop_price = min(stop_price, float(current_rate) * 0.999999)
            sl = self._stoploss_pct_from_price(trade.is_short, stop_price, float(current_rate))
            if sl is not None:
                stops.append(sl)

        if current_atr is not None and current_rate > 0:
            atr_mult = float(self.atr_multiplier.value) * volatility_factor
            if trade.is_short:
                stop_price = float(current_rate) + (current_atr * atr_mult)
            else:
                stop_price = float(current_rate) - (current_atr * atr_mult)
            sl = self._stoploss_pct_from_price(trade.is_short, stop_price, float(current_rate))
            if sl is not None:
                stops.append(sl)

        if (
            self.break_even_enabled.value
            and current_profit > float(self.break_even_profit_threshold.value)
            and current_rate > 0
            and float(trade.open_rate) > 0
        ):
            be_offset = float(self.break_even_offset.value)
            if trade.is_short:
                stop_price = float(trade.open_rate) * (1.0 - be_offset)
                stop_price = max(stop_price, float(current_rate) * 1.000001)
            else:
                stop_price = float(trade.open_rate) * (1.0 + be_offset)
                stop_price = min(stop_price, float(current_rate) * 0.999999)
            sl = self._stoploss_pct_from_price(trade.is_short, stop_price, float(current_rate))
            if sl is not None:
                stops.append(sl)

        if current_profit > float(self.trailing_activation_offset.value) and current_rate > 0:
            trailing_stop_pct = float(self.trailing_stop_pct.value)
            if trade.is_short:
                if hasattr(trade, "min_rate") and trade.min_rate is not None and trade.min_rate > 0:
                    stop_price = float(trade.min_rate) * (1.0 + trailing_stop_pct)
                    stop_price = max(stop_price, float(current_rate) * 1.000001)
                    sl = self._stoploss_pct_from_price(True, stop_price, float(current_rate))
                    if sl is not None:
                        stops.append(sl)
            else:
                if hasattr(trade, "max_rate") and trade.max_rate is not None and trade.max_rate > 0:
                    stop_price = float(trade.max_rate) * (1.0 - trailing_stop_pct)
                    stop_price = min(stop_price, float(current_rate) * 0.999999)
                    sl = self._stoploss_pct_from_price(False, stop_price, float(current_rate))
                    if sl is not None:
                        stops.append(sl)

        if (
            self.chandelier_enabled.value
            and current_profit > 0
            and current_atr is not None
            and current_rate > 0
        ):
            ch_mult = float(self.chandelier_atr_multiplier.value) * volatility_factor
            if trade.is_short:
                if hasattr(trade, "min_rate") and trade.min_rate is not None and trade.min_rate > 0:
                    stop_price = float(trade.min_rate) + (current_atr * ch_mult)
                    stop_price = max(stop_price, float(current_rate) * 1.000001)
                    sl = self._stoploss_pct_from_price(True, stop_price, float(current_rate))
                    if sl is not None:
                        stops.append(sl)
            else:
                if hasattr(trade, "max_rate") and trade.max_rate is not None and trade.max_rate > 0:
                    stop_price = float(trade.max_rate) - (current_atr * ch_mult)
                    stop_price = min(stop_price, float(current_rate) * 0.999999)
                    sl = self._stoploss_pct_from_price(False, stop_price, float(current_rate))
                    if sl is not None:
                        stops.append(sl)

        valid_stops = [s for s in stops if s is not None and s <= 0]
        combined_stop = max(valid_stops) if valid_stops else base_stop
        final_stop = max(base_stop, combined_stop)

        if dataframe is not None and len(dataframe) > 0 and "atr_pct" in dataframe.columns:
            try:
                self._current_volatility[pair] = float(dataframe["atr_pct"].iloc[-1])
            except Exception:
                pass

        return final_stop

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[Union[str, bool]]:
        current_time_utc = self._utc_dt(current_time)
        open_date_utc = self._utc_dt(trade.open_date_utc)
        hold_hours = (current_time_utc - open_date_utc).total_seconds() / 3600

        if hold_hours > int(self.time_exit_hours.value):
            return "time_exit"

        if current_profit > float(self.quick_take_profit_1.value):
            return "quick_take_profit_1"
        if current_profit > float(self.quick_take_profit_2.value):
            return "quick_take_profit_2"

        if current_profit < float(self.emergency_stop_profit.value):
            return "emergency_stop_loss"

        return None

