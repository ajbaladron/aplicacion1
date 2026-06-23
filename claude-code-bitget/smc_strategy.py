"""
SMC Strategy Engine — Smart Money Concepts multi-timeframe analysis.
Exchange: Pionex Perpetual Futures
Simbolos: BTC_USDT, ETH_USDT, SOL_USDT, XRP_USDT, ADA_USDT, XLM_USDT
          (formato Pionex: guion_bajo, sin guion)
"""
from __future__ import annotations

import requests
from dataclasses import dataclass
from typing import Optional

# ── Global symbol — cambiar antes de llamar fetch_candles ─────────────────────
SYMBOL = "BTC_USDT"

BASE_URL = "https://api.pionex.com"

# Pionex granularidades para futuros perpetuos
_TF_MAP = {
    "1m":  "1M",
    "3m":  "3M",
    "5m":  "5M",
    "15m": "15M",
    "30m": "30M",
    "1h":  "1H",
    "2h":  "2H",
    "4h":  "4H",
    "6h":  "6H",
    "12h": "12H",
    "1d":  "1D",
    "1w":  "1W",
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
    kind: str   # 'high' o 'low'


@dataclass
class OrderBlock:
    idx: int
    top: float
    bot: float
    kind: str        # 'bullish' o 'bearish'
    mitigated: bool = False


@dataclass
class FVG:
    top: float
    bot: float
    kind: str   # 'bull' o 'bear'
    idx: int


# ── Candle fetch ──────────────────────────────────────────────────────────────

def fetch_candles(timeframe: str, limit: int = 100) -> list[Candle]:
    """
    Obtiene velas del endpoint publico de Pionex.
    Respuesta esperada:
      { "result": true, "data": { "klines": [[ts, o, h, l, c, v], ...] } }
    """
    tf = _TF_MAP.get(timeframe, timeframe.upper())
    url = f"{BASE_URL}/api/v1/market/klines"
    params = {
        "symbol": SYMBOL,
        "interval": tf,
        "limit": str(limit),
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()

    rows = []
    if isinstance(data, dict):
        inner = data.get("data", {})
        if isinstance(inner, dict):
            rows = inner.get("klines", [])
        elif isinstance(inner, list):
            rows = inner
    elif isinstance(data, list):
        rows = data

    candles = []
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
    Retorna (trend, choch_level).
    trend: 'bullish', 'bearish' o 'ranging'
    """
    highs = [s for s in swings if s.kind == "high"]
    lows  = [s for s in swings if s.kind == "low"]

    if len(highs) < 2 or len(lows) < 2:
        return "ranging", None

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

    choch_level: Optional[float] = None
    if trend == "bullish":
        choch_level = highs[-2].price
    elif trend == "bearish":
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
            for j in range(i, max(i - 5, 0), -1):
                if candles[j].c > candles[j].o:
                    obs.append(OrderBlock(
                        idx=j, top=candles[j].h, bot=candles[j].o, kind="bearish"
                    ))
                    break

        elif swing.kind == "low" and trend in ("bullish", "ranging"):
            for j in range(i, max(i - 5, 0), -1):
                if candles[j].c < candles[j].o:
                    obs.append(OrderBlock(
                        idx=j, top=candles[j].o, bot=candles[j].l, kind="bullish"
                    ))
                    break

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
        prev = candles[i - 1]
        nxt  = candles[i + 1]

        if nxt.l > prev.h:
            fvgs.append(FVG(top=nxt.l, bot=prev.h, kind="bull", idx=i))

        if nxt.h < prev.l:
            fvgs.append(FVG(top=prev.l, bot=nxt.h, kind="bear", idx=i))

    return fvgs


# ── Liquidity levels ──────────────────────────────────────────────────────────

def find_liquidity(swings: list[Swing]) -> tuple[list[float], list[float]]:
    """
    Retorna (bsl_levels, ssl_levels).
    BSL: highs donde estan los stops de compradores.
    SSL: lows donde estan los stops de vendedores.
    """
    highs = sorted([s.price for s in swings if s.kind == "high"])
    lows  = sorted([s.price for s in swings if s.kind == "low"])

    def cluster(levels: list[float], pct: float = 0.0015) -> list[float]:
        if not levels:
            return []
        result = [levels[0]]
        for lvl in levels[1:]:
            if abs(lvl - result[-1]) / result[-1] > pct:
                result.append(lvl)
        return result

    bsl = cluster(list(reversed(highs)))
    ssl = cluster(lows)
    return bsl, ssl


# ── CHoCH en 15M ─────────────────────────────────────────────────────────────

def detect_choch_15m(
    candles_15m: list[Candle], higher_tf_trend: str
) -> Optional[dict]:
    """
    Detecta Change of Character en 15M alineado con el trend de mayor TF.
    Retorna dict(kind, level, candle_idx) o None.
    """
    swings = find_swings(candles_15m, left=3, right=3)
    if not swings:
        return None

    highs = [s for s in swings if s.kind == "high"]
    lows  = [s for s in swings if s.kind == "low"]

    if higher_tf_trend == "bearish" and len(lows) >= 2:
        recent_lows = sorted(lows, key=lambda s: s.idx)
        for i in range(len(recent_lows) - 1, 0, -1):
            if recent_lows[i].price < recent_lows[i - 1].price:
                return {
                    "kind": "bearish",
                    "level": recent_lows[i].price,
                    "candle_idx": recent_lows[i].idx,
                }

    if higher_tf_trend == "bullish" and len(highs) >= 2:
        recent_highs = sorted(highs, key=lambda s: s.idx)
        for i in range(len(recent_highs) - 1, 0, -1):
            if recent_highs[i].price > recent_highs[i - 1].price:
                return {
                    "kind": "bullish",
                    "level": recent_highs[i].price,
                    "candle_idx": recent_highs[i].idx,
                }

    return None
