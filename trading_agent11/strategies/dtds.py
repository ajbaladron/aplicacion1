"""
DTDS – Dynamic Trend Detection System
Entry logic: price pulls back to EMA21 while EMA9 > EMA21 > EMA50 (or inverse for shorts).
Uses "on-touch" entry: returns a touch_price level rather than immediate market entry.
"""
import pandas as pd
import numpy as np
from typing import Optional

from config import (
    DTDS_EMA_FAST, DTDS_EMA_MID, DTDS_EMA_SLOW, DTDS_EMA_TREND,
    ATR_PERIOD, ATR_MULTIPLIER_SL, ATR_MULTIPLIER_TP,
)


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


def detect(df: pd.DataFrame) -> Optional[dict]:
    """
    df: OHLCV DataFrame with columns [open, high, low, close, volume],
        at least 210 rows (15 M candles recommended).
    Returns signal dict or None.
    """
    if len(df) < DTDS_EMA_TREND + 10:
        return None

    df = df.copy()
    df["ema_fast"]  = _ema(df["close"], DTDS_EMA_FAST)
    df["ema_mid"]   = _ema(df["close"], DTDS_EMA_MID)
    df["ema_slow"]  = _ema(df["close"], DTDS_EMA_SLOW)
    df["ema_trend"] = _ema(df["close"], DTDS_EMA_TREND)
    df["atr"]       = _atr(df, ATR_PERIOD)

    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    price = last["close"]
    atr   = last["atr"]

    if pd.isna(atr) or atr == 0:
        return None

    # ── Bullish setup ──────────────────────────────────────────────────────────
    # Trend alignment: ema_fast > ema_mid > ema_slow > ema_trend
    # Touch condition: price dipped to within 0.5*ATR of ema_mid and bounced
    bullish_trend = (
        last["ema_fast"]  > last["ema_mid"] and
        last["ema_mid"]   > last["ema_slow"] and
        last["ema_slow"]  > last["ema_trend"]
    )
    if bullish_trend:
        touch_zone_hi = last["ema_mid"] + 0.5 * atr
        touch_zone_lo = last["ema_mid"] - 0.5 * atr
        touched = prev["low"] <= touch_zone_hi and prev["low"] >= touch_zone_lo
        bounced = last["close"] > last["ema_mid"]
        if touched and bounced:
            sl = last["ema_slow"] - 0.2 * atr
            tp = price + ATR_MULTIPLIER_TP * atr
            score = _score(df, "LONG")
            return {
                "direction":   "LONG",
                "entry_type":  "on_touch",
                "touch_price": round(last["ema_mid"], 6),
                "tp":          round(tp, 6),
                "sl":          round(sl, 6),
                "atr":         round(atr, 6),
                "score":       score,
                "reason":      f"DTDS LONG: precio tocó EMA{DTDS_EMA_MID} ({last['ema_mid']:.4f}) en tendencia alcista",
            }

    # ── Bearish setup ──────────────────────────────────────────────────────────
    bearish_trend = (
        last["ema_fast"]  < last["ema_mid"] and
        last["ema_mid"]   < last["ema_slow"] and
        last["ema_slow"]  < last["ema_trend"]
    )
    if bearish_trend:
        touch_zone_hi = last["ema_mid"] + 0.5 * atr
        touch_zone_lo = last["ema_mid"] - 0.5 * atr
        touched = prev["high"] >= touch_zone_lo and prev["high"] <= touch_zone_hi
        bounced = last["close"] < last["ema_mid"]
        if touched and bounced:
            sl = last["ema_slow"] + 0.2 * atr
            tp = price - ATR_MULTIPLIER_TP * atr
            score = _score(df, "SHORT")
            return {
                "direction":   "SHORT",
                "entry_type":  "on_touch",
                "touch_price": round(last["ema_mid"], 6),
                "tp":          round(tp, 6),
                "sl":          round(sl, 6),
                "atr":         round(atr, 6),
                "score":       score,
                "reason":      f"DTDS SHORT: precio tocó EMA{DTDS_EMA_MID} ({last['ema_mid']:.4f}) en tendencia bajista",
            }

    return None


def _score(df: pd.DataFrame, direction: str) -> int:
    """Fixed scoring: 0-100 based on trend clarity."""
    last = df.iloc[-1]
    score = 50
    spread = abs(last["ema_fast"] - last["ema_trend"])
    atr = last["atr"] if last["atr"] > 0 else 1
    clarity = min(spread / atr, 4) / 4  # 0-1
    score += int(clarity * 30)
    # Volume confirmation
    if len(df) >= 20:
        avg_vol = df["volume"].iloc[-20:].mean()
        if df["volume"].iloc[-1] > avg_vol * 1.2:
            score += 10
    # RSI confirmation
    rsi = _rsi(df["close"], 14).iloc[-1]
    if direction == "LONG" and 40 < rsi < 70:
        score += 10
    elif direction == "SHORT" and 30 < rsi < 60:
        score += 10
    return min(score, 100)


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))
