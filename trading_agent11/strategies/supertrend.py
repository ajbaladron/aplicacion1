"""
SuperTrend strategy detector.
Returns immediate market-entry signal; trailing stop is the SuperTrend line itself.
"""
import pandas as pd
import numpy as np
from typing import Optional

from config import ST_PERIOD, ST_MULTIPLIER, ATR_PERIOD, ATR_MULTIPLIER_TP


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _supertrend(df: pd.DataFrame, period: int, multiplier: float):
    """Return (supertrend_series, direction_series) where direction 1=bullish, -1=bearish."""
    atr  = _atr(df, period)
    hl2  = (df["high"] + df["low"]) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    st        = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    for i in range(1, len(df)):
        if pd.isna(atr.iloc[i]):
            st.iloc[i]        = np.nan
            direction.iloc[i] = 1
            continue

        prev_st  = st.iloc[i - 1]
        prev_dir = direction.iloc[i - 1] if not pd.isna(direction.iloc[i - 1]) else 1
        close    = df["close"].iloc[i]

        # Upper band finalisation
        final_upper = upper_band.iloc[i]
        if upper_band.iloc[i] < (prev_st if prev_dir == -1 else upper_band.iloc[i - 1]):
            final_upper = upper_band.iloc[i]
        else:
            final_upper = upper_band.iloc[i - 1] if not pd.isna(prev_st) else upper_band.iloc[i]

        # Lower band finalisation
        final_lower = lower_band.iloc[i]
        if lower_band.iloc[i] > (prev_st if prev_dir == 1 else lower_band.iloc[i - 1]):
            final_lower = lower_band.iloc[i]
        else:
            final_lower = lower_band.iloc[i - 1] if not pd.isna(prev_st) else lower_band.iloc[i]

        if prev_dir == 1:
            if close < final_lower:
                direction.iloc[i] = -1
                st.iloc[i]        = final_upper
            else:
                direction.iloc[i] = 1
                st.iloc[i]        = final_lower
        else:
            if close > final_upper:
                direction.iloc[i] = 1
                st.iloc[i]        = final_lower
            else:
                direction.iloc[i] = -1
                st.iloc[i]        = final_upper

    return st, direction


def detect(df: pd.DataFrame) -> Optional[dict]:
    """
    df: OHLCV DataFrame, at least ST_PERIOD + 5 rows.
    Returns signal dict or None.
    Signal fires only on direction change (last 1 candle).
    """
    if len(df) < ST_PERIOD + 5:
        return None

    df = df.copy().reset_index(drop=True)
    st, direction = _supertrend(df, ST_PERIOD, ST_MULTIPLIER)

    last_dir  = direction.iloc[-1]
    prev_dir  = direction.iloc[-2]
    st_line   = st.iloc[-1]
    price     = df["close"].iloc[-1]
    atr_val   = _atr(df, ATR_PERIOD).iloc[-1]

    if pd.isna(st_line) or pd.isna(atr_val) or atr_val == 0:
        return None

    # Signal only on crossover (direction change)
    if last_dir == prev_dir:
        return None

    if last_dir == 1:  # flipped bullish
        sl = round(st_line, 6)
        tp = round(price + ATR_MULTIPLIER_TP * atr_val, 6)
        return {
            "direction":      "LONG",
            "entry_type":     "market",
            "tp":             tp,
            "sl":             sl,
            "trailing_stop":  True,
            "trailing_value": sl,
            "atr":            round(atr_val, 6),
            "score":          _score(df, "LONG", atr_val),
            "reason":         f"SuperTrend cruzó alcista. ST={st_line:.4f}",
        }
    else:  # flipped bearish
        sl = round(st_line, 6)
        tp = round(price - ATR_MULTIPLIER_TP * atr_val, 6)
        return {
            "direction":      "SHORT",
            "entry_type":     "market",
            "tp":             tp,
            "sl":             sl,
            "trailing_stop":  True,
            "trailing_value": sl,
            "atr":            round(atr_val, 6),
            "score":          _score(df, "SHORT", atr_val),
            "reason":         f"SuperTrend cruzó bajista. ST={st_line:.4f}",
        }


def get_trailing_sl(df: pd.DataFrame) -> Optional[float]:
    """Return the current SuperTrend line to use as trailing stop."""
    if len(df) < ST_PERIOD + 5:
        return None
    df = df.copy().reset_index(drop=True)
    st, _ = _supertrend(df, ST_PERIOD, ST_MULTIPLIER)
    val = st.iloc[-1]
    return float(val) if not pd.isna(val) else None


def _score(df: pd.DataFrame, direction: str, atr: float) -> int:
    score = 55
    # Candle strength
    last = df.iloc[-1]
    body = abs(last["close"] - last["open"])
    if direction == "LONG" and last["close"] > last["open"] and body > 0.5 * atr:
        score += 15
    elif direction == "SHORT" and last["close"] < last["open"] and body > 0.5 * atr:
        score += 15
    # Volume
    if len(df) >= 20:
        avg_vol = df["volume"].iloc[-20:].mean()
        if df["volume"].iloc[-1] > avg_vol * 1.3:
            score += 15
    # Momentum: 3-candle move
    move = abs(df["close"].iloc[-1] - df["close"].iloc[-4])
    if move > atr:
        score += 15
    return min(score, 100)
