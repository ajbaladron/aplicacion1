"""
VWAP Structure strategy detector.
Long: price bounces off VWAP support from below.
Short: price rejects from VWAP resistance from above.
Immediate market entry.
"""
import pandas as pd
import numpy as np
from typing import Optional

from config import VWAP_STD_MULT, ATR_PERIOD, ATR_MULTIPLIER_SL, ATR_MULTIPLIER_TP


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _vwap(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (vwap, upper_band, lower_band) using session volume."""
    tp          = (df["high"] + df["low"] + df["close"]) / 3
    cum_tvp     = (tp * df["volume"]).cumsum()
    cum_vol     = df["volume"].cumsum()
    vwap        = cum_tvp / cum_vol.replace(0, np.nan)

    # Standard deviation of price around VWAP
    dev         = (tp - vwap) ** 2
    cum_dev_vol = (dev * df["volume"]).cumsum()
    variance    = cum_dev_vol / cum_vol.replace(0, np.nan)
    std         = np.sqrt(variance)

    upper = vwap + VWAP_STD_MULT * std
    lower = vwap - VWAP_STD_MULT * std
    return vwap, upper, lower


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def detect(df: pd.DataFrame) -> Optional[dict]:
    """
    df: OHLCV DataFrame.  Ideally starts at session open (00:00 UTC)
        so that VWAP resets properly.  At minimum 50 rows.
    """
    if len(df) < 50:
        return None

    df = df.copy()
    df["atr"] = _atr(df, ATR_PERIOD)
    df["rsi"] = _rsi(df["close"])

    vwap, upper, lower = _vwap(df)
    df["vwap"]  = vwap
    df["upper"] = upper
    df["lower"] = lower

    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    price = last["close"]
    atr   = last["atr"]
    rsi   = last["rsi"]

    if any(pd.isna([atr, rsi, last["vwap"], last["upper"], last["lower"]])):
        return None
    if atr == 0:
        return None

    vwap_now  = last["vwap"]
    upper_now = last["upper"]
    lower_now = last["lower"]

    # ── LONG: price was below VWAP and is now crossing back above ────────────
    bounce_up = prev["close"] < prev["vwap"] and price > vwap_now
    if bounce_up and rsi < 65:
        sl = round(lower_now - 0.2 * atr, 6)
        tp = round(upper_now, 6)
        return {
            "direction":  "LONG",
            "entry_type": "market",
            "tp":         tp,
            "sl":         sl,
            "atr":        round(atr, 6),
            "vwap":       round(vwap_now, 6),
            "rsi":        round(rsi, 2),
            "score":      _score(df, "LONG", atr, rsi, price, vwap_now),
            "reason":     f"VWAP LONG: precio cruzó por encima de VWAP ({vwap_now:.4f}). RSI={rsi:.1f}",
        }

    # ── SHORT: price was above VWAP and is now crossing back below ───────────
    reject_down = prev["close"] > prev["vwap"] and price < vwap_now
    if reject_down and rsi > 35:
        sl = round(upper_now + 0.2 * atr, 6)
        tp = round(lower_now, 6)
        return {
            "direction":  "SHORT",
            "entry_type": "market",
            "tp":         tp,
            "sl":         sl,
            "atr":        round(atr, 6),
            "vwap":       round(vwap_now, 6),
            "rsi":        round(rsi, 2),
            "score":      _score(df, "SHORT", atr, rsi, price, vwap_now),
            "reason":     f"VWAP SHORT: precio cruzó por debajo de VWAP ({vwap_now:.4f}). RSI={rsi:.1f}",
        }

    return None


def _score(df, direction, atr, rsi, price, vwap):
    score = 50
    # Distance from VWAP (closer = more reliable)
    dist = abs(price - vwap)
    if dist < 0.5 * atr:
        score += 20
    elif dist < atr:
        score += 10
    # RSI neutrality around crossover
    if 40 <= rsi <= 60:
        score += 15
    # Volume
    if len(df) >= 20:
        avg_vol = df["volume"].iloc[-20:].mean()
        if df["volume"].iloc[-1] > avg_vol * 1.2:
            score += 15
    return min(score, 100)
