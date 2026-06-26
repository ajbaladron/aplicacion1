"""
EMA Crossover strategy detector.
Fires on fresh fast/slow EMA crossover (within last 2 candles).
Immediate market entry.
"""
import pandas as pd
import numpy as np
from typing import Optional

from config import EMA_FAST, EMA_SLOW, ATR_PERIOD, ATR_MULTIPLIER_SL, ATR_MULTIPLIER_TP


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def detect(df: pd.DataFrame) -> Optional[dict]:
    """
    df: OHLCV DataFrame, at least EMA_SLOW + 5 rows.
    Returns signal dict or None.
    """
    if len(df) < EMA_SLOW + 5:
        return None

    df = df.copy()
    df["ema_fast"] = _ema(df["close"], EMA_FAST)
    df["ema_slow"] = _ema(df["close"], EMA_SLOW)
    df["atr"]      = _atr(df, ATR_PERIOD)
    df["rsi"]      = _rsi(df["close"])

    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    price = last["close"]
    atr   = last["atr"]
    rsi   = last["rsi"]

    if pd.isna(atr) or atr == 0 or pd.isna(rsi):
        return None

    # Bullish crossover: fast crossed above slow
    crossed_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
    if crossed_up:
        # Avoid overbought entries
        if rsi > 75:
            return None
        sl = round(price - ATR_MULTIPLIER_SL * atr, 6)
        tp = round(price + ATR_MULTIPLIER_TP * atr, 6)
        return {
            "direction":  "LONG",
            "entry_type": "market",
            "tp":         tp,
            "sl":         sl,
            "atr":        round(atr, 6),
            "rsi":        round(rsi, 2),
            "score":      _score(df, "LONG", atr, rsi),
            "reason":     f"EMA{EMA_FAST} cruzó por encima de EMA{EMA_SLOW}. RSI={rsi:.1f}",
        }

    # Bearish crossover: fast crossed below slow
    crossed_down = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]
    if crossed_down:
        if rsi < 25:
            return None
        sl = round(price + ATR_MULTIPLIER_SL * atr, 6)
        tp = round(price - ATR_MULTIPLIER_TP * atr, 6)
        return {
            "direction":  "SHORT",
            "entry_type": "market",
            "tp":         tp,
            "sl":         sl,
            "atr":        round(atr, 6),
            "rsi":        round(rsi, 2),
            "score":      _score(df, "SHORT", atr, rsi),
            "reason":     f"EMA{EMA_FAST} cruzó por debajo de EMA{EMA_SLOW}. RSI={rsi:.1f}",
        }

    return None


def _score(df: pd.DataFrame, direction: str, atr: float, rsi: float) -> int:
    score = 50
    # RSI sweet spot
    if direction == "LONG" and 45 <= rsi <= 65:
        score += 20
    elif direction == "SHORT" and 35 <= rsi <= 55:
        score += 20
    # EMA separation (trend strength)
    last = df.iloc[-1]
    separation = abs(last["ema_fast"] - last["ema_slow"])
    ratio = min(separation / atr, 2) / 2
    score += int(ratio * 20)
    # Volume
    if len(df) >= 20:
        avg_vol = df["volume"].iloc[-20:].mean()
        if df["volume"].iloc[-1] > avg_vol * 1.2:
            score += 10
    return min(score, 100)
