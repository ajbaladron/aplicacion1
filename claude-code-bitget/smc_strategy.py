"""
SMC Strategy Engine — Smart Money Concepts multi-timeframe analysis.
Supports: BTC-USDT, ETH-USDT, SOL-USDT, XRP-USDT, ADA-USDT, XLM-USDT
"""
from __future__ import annotations

import requests
from dataclasses import dataclass, field
from typing import Optional

# ── Global symbol (caller must set before calling fetch_candles) ──────────────
SYMBOL = "BTC-USDT"

BASE_URL = "https://api.bitget.com"

_TF_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
    "1d": "1D", "1w": "1W",
}


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Candle:
    t: int    # timestamp ms
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass
class Swing:
    idx: int
    price: float
    kind: str   # 'high' or 'low'


@dataclass
class OrderBlock:
    idx: int
    top: float
    bot: float
    kind: str   # 'bullish' or 'bearish'
    mitigated: bool = False


@dataclass
class FVG:
    top: float
    bot: float
    kind: str   # 'bull' or 'bear'
    idx: int    # index of the gap candle


# ── Candle fetch ──────────────────────────────────────────────────────────────

def fetch_candles(timeframe: str, limit: int = 100) -> list[Candle]:
    tf = _TF_MAP.get(timeframe, timeframe)
    url = f"{BASE_URL}/api/v2/mix/market/candles"
    params = {
        "symbol": SYMBOL,
        "granularity": tf,
        "limit": str(limit),
        "productType": "USDT-FUTURES",
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    candles = []
    if isinstance(data, dict):
        rows = data.get("data", [])
    else:
        rows = data
    for row in rows:
        candles.append(Candle(
            t=int(row[0]),
            o=float(row[1]),
            h=float(row[2]),
            l=float(row[3]),
            c=float(row[4]),
            v=float(row[5]),
        ))
    candles.sort(key=lambda c: c.t)
    return candles


# ── Swing detection ───────────────────────────────────────────────────────────

def find_swings(candles: list[Candle], left: int = 3, right: int = 3) -> list[Swing]:
    swings: list[Swing] = []
    n = len(candles)
    for i in range(left, n - right):
        window_h = [candles[j].h for j in range(i - left, i + right + 1)]
        window_l = [candles[j].l for j in range(i - left, i + right + 1)]
        if candles[i].h == max(window_h):
            swings.append(Swing(idx=i, price=candles[i].h, kind="high"))
        if candles[i].l == min(window_l):
            swings.append(Swing(idx=i, price=candles[i].l, kind="low"))
    return swings


# ── Market structure ──────────────────────────────────────────────────────────

def detect_structure(
    candles: list[Candle], swings: list[Swing]
) -> tuple[str, Optional[float]]:
    """
    Returns (trend, choch_level).
    trend: 'bullish', 'bearish', or 'ranging'
    choch_level: price of last CHoCH if found, else None
    """
    highs = [s for s in swings if s.kind == "high"]
    lows  = [s for s in swings if s.kind == "low"]

    if len(highs) < 2 or len(lows) < 2:
        return "ranging", None

    # Last two highs and lows
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price  > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price  < lows[-2].price

    if hh and hl:
        trend = "bullish"
    elif lh and ll:
        trend = "bearish"
    else:
        trend = "ranging"

    # CHoCH: last swing that broke the previous structure
    choch_level: Optional[float] = None
    if trend == "bullish" and len(highs) >= 2:
        choch_level = highs[-2].price
    elif trend == "bearish" and len(lows) >= 2:
        choch_level = lows[-2].price

    return trend, choch_level


# ── Order Blocks ──────────────────────────────────────────────────────────────

def find_order_blocks(
    candles: list[Candle], swings: list[Swing], trend: str, lookback: int = 30
) -> list[OrderBlock]:
    obs: list[OrderBlock] = []
    n = len(candles)
    start = max(0, n - lookback)

    for swing in swings:
        i = swing.idx
        if i < start or i >= n - 1:
            continue

        if swing.kind == "high" and trend in ("bearish", "ranging"):
            # Bearish OB: last bullish candle before a swing high
            for j in range(i, max(i - 5, 0), -1):
                if candles[j].c > candles[j].o:  # bullish candle
                    ob = OrderBlock(
                        idx=j,
                        top=candles[j].h,
                        bot=candles[j].o,
                        kind="bearish",
                    )
                    obs.append(ob)
                    break

        elif swing.kind == "low" and trend in ("bullish", "ranging"):
            # Bullish OB: last bearish candle before a swing low
            for j in range(i, max(i - 5, 0), -1):
                if candles[j].c < candles[j].o:  # bearish candle
                    ob = OrderBlock(
                        idx=j,
                        top=candles[j].o,
                        bot=candles[j].l,
                        kind="bullish",
                    )
                    obs.append(ob)
                    break

    # Mark mitigated OBs (price already traded through them)
    last_price = candles[-1].c
    for ob in obs:
        if ob.kind == "bearish" and last_price > ob.top:
            ob.mitigated = True
        elif ob.kind == "bullish" and last_price < ob.bot:
            ob.mitigated = True

    return obs


# ── Fair Value Gaps ───────────────────────────────────────────────────────────

def find_fvgs(candles: list[Candle], lookback: int = 40) -> list[FVG]:
    fvgs: list[FVG] = []
    n = len(candles)
    start = max(0, n - lookback)

    for i in range(start + 1, n - 1):
        prev  = candles[i - 1]
        curr  = candles[i]
        nxt   = candles[i + 1]

        # Bullish FVG: gap between prev.high and next.low (price moved up)
        if nxt.l > prev.h:
            fvgs.append(FVG(top=nxt.l, bot=prev.h, kind="bull", idx=i))

        # Bearish FVG: gap between prev.low and next.high (price moved down)
        if nxt.h < prev.l:
            fvgs.append(FVG(top=prev.l, bot=nxt.h, kind="bear", idx=i))

    return fvgs


# ── Liquidity levels ──────────────────────────────────────────────────────────

def find_liquidity(swings: list[Swing]) -> tuple[list[float], list[float]]:
    """
    Returns (bsl_levels, ssl_levels).
    BSL: Buy-Side Liquidity — equal/swing highs targeted for stops above.
    SSL: Sell-Side Liquidity — equal/swing lows targeted for stops below.
    """
    highs = sorted([s.price for s in swings if s.kind == "high"])
    lows  = sorted([s.price for s in swings if s.kind == "low"])

    # Group near-equal levels (within 0.15%)
    def cluster(levels: list[float], pct: float = 0.0015) -> list[float]:
        if not levels:
            return []
        result = [levels[0]]
        for lvl in levels[1:]:
            if abs(lvl - result[-1]) / result[-1] > pct:
                result.append(lvl)
        return result

    bsl = cluster(list(reversed(highs)))  # highest first
    ssl = cluster(lows)                   # lowest first

    return bsl, ssl


# ── CHoCH detection on 15M ────────────────────────────────────────────────────

def detect_choch_15m(
    candles_15m: list[Candle], higher_tf_trend: str
) -> Optional[dict]:
    """
    Detect a Change of Character on 15M that aligns with a potential reversal.
    Returns dict with keys: kind ('bullish'/'bearish'), level, candle_idx
    or None if no CHoCH found.
    """
    swings = find_swings(candles_15m, left=3, right=3)
    if not swings:
        return None

    highs = [s for s in swings if s.kind == "high"]
    lows  = [s for s in swings if s.kind == "low"]

    # Bearish CHoCH: price was making HH/HL, then broke below a HL
    # Bullish CHoCH: price was making LL/LH, then broke above a LH
    last_price = candles_15m[-1].c

    if higher_tf_trend == "bearish" and len(lows) >= 2:
        # Look for price breaking below the most recent higher low
        recent_lows = sorted(lows, key=lambda s: s.idx)
        for i in range(len(recent_lows) - 1, 0, -1):
            if recent_lows[i].price < recent_lows[i - 1].price:
                # Lower low formed — bearish CHoCH
                return {
                    "kind": "bearish",
                    "level": recent_lows[i].price,
                    "candle_idx": recent_lows[i].idx,
                }

    if higher_tf_trend == "bullish" and len(highs) >= 2:
        # Look for price breaking above the most recent lower high
        recent_highs = sorted(highs, key=lambda s: s.idx)
        for i in range(len(recent_highs) - 1, 0, -1):
            if recent_highs[i].price > recent_highs[i - 1].price:
                # Higher high formed — bullish CHoCH
                return {
                    "kind": "bullish",
                    "level": recent_highs[i].price,
                    "candle_idx": recent_highs[i].idx,
                }

    return None
