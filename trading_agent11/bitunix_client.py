"""
Bitunix Futures REST API client.
Only reads market data (candles, tickers, price).
Order placement is handled by portfolio.py (paper mode).
"""
import hashlib
import hmac
import time
import logging
from typing import Optional

import requests
import pandas as pd

from config import (
    API_KEY, API_SECRET, BITUNIX_BASE_URL,
    REQUEST_TIMEOUT, MAX_RETRIES, VOLUME_THRESHOLD, MAX_PAIRS, EXCLUDED_PAIRS,
)

log = logging.getLogger(__name__)


class BitunixClient:
    def __init__(self):
        self.base    = BITUNIX_BASE_URL
        self.api_key = API_KEY
        self.secret  = API_SECRET
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "api-key":      self.api_key,
        })

    def _sign(self, query_str: str) -> str:
        return hmac.new(
            self.secret.encode(), query_str.encode(), hashlib.sha256
        ).hexdigest()

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base}{path}"
        for attempt in range(MAX_RETRIES):
            try:
                r = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait = 2 ** attempt
                log.warning(f"BitunixClient GET {path} intento {attempt+1} falló: {e}. Reintento en {wait}s")
                time.sleep(wait)
        return {}

    # ── Candles ─────────────────────────────────────────────────────────────
    def get_klines(self, symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
        """
        interval: "1m", "5m", "15m", "1h", "4h", "1d"
        Returns DataFrame [open_time, open, high, low, close, volume] sorted ascending.
        """
        data = self._get("/api/v1/futures/market/kline", params={
            "symbol":   symbol,
            "interval": interval,
            "limit":    limit,
        })
        rows = data.get("data", {})
        # Accept both list-of-lists and {"list": [...]} formats
        if isinstance(rows, dict):
            rows = rows.get("list", [])
        if not rows:
            return pd.DataFrame(columns=["open_time", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
        df.sort_values("open_time", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    # ── Ticker / price ───────────────────────────────────────────────────────
    def get_price(self, symbol: str) -> Optional[float]:
        try:
            data   = self._get("/api/v1/futures/market/ticker", params={"symbol": symbol})
            ticker = data.get("data", {})
            if isinstance(ticker, list):
                ticker = ticker[0] if ticker else {}
            price  = ticker.get("lastPrice") or ticker.get("last") or ticker.get("close")
            return float(price) if price is not None else None
        except Exception as e:
            log.error(f"get_price {symbol}: {e}")
            return None

    def get_prices_bulk(self, symbols: list[str]) -> dict[str, float]:
        """Fetch all tickers at once and return {symbol: price}."""
        try:
            data    = self._get("/api/v1/futures/market/tickers")
            tickers = data.get("data", [])
            result  = {}
            for t in tickers:
                sym   = t.get("symbol", "")
                price = t.get("lastPrice") or t.get("last") or t.get("close")
                if sym in symbols and price:
                    result[sym] = float(price)
            return result
        except Exception as e:
            log.error(f"get_prices_bulk: {e}")
            return {}

    # ── Dynamic pair selection ────────────────────────────────────────────────
    def get_top_pairs(self) -> list[str]:
        """
        Return top USDT-margined futures pairs by 24 h USDT volume,
        filtered by VOLUME_THRESHOLD and excluding stablecoins.
        """
        try:
            data    = self._get("/api/v1/futures/market/tickers")
            tickers = data.get("data", [])
        except Exception as e:
            log.error(f"get_top_pairs: {e}")
            return []

        pairs = []
        for t in tickers:
            sym = t.get("symbol", "")
            if not sym.endswith("USDT"):
                continue
            if sym in EXCLUDED_PAIRS:
                continue
            vol_usd = float(t.get("volUsd", 0) or t.get("quoteVolume", 0) or 0)
            if vol_usd < VOLUME_THRESHOLD:
                continue
            pairs.append((sym, vol_usd))

        pairs.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in pairs[:MAX_PAIRS]]

    # ── Market context ────────────────────────────────────────────────────────
    def get_market_context(self, symbol: str) -> dict:
        """
        Return context dict with 4H trend, RSI, ATR, price, volume_ratio.
        """
        try:
            df_15m = self.get_klines(symbol, "15m", 100)
            df_4h  = self.get_klines(symbol, "4h",  60)

            if df_15m.empty or df_4h.empty:
                return {}

            # Current price
            price = float(df_15m["close"].iloc[-1])

            # 4H trend via EMA50
            ema50_4h = df_4h["close"].ewm(span=50, adjust=False).mean().iloc[-1]
            if df_4h["close"].iloc[-1] > ema50_4h * 1.002:
                trend = "bullish"
            elif df_4h["close"].iloc[-1] < ema50_4h * 0.998:
                trend = "bearish"
            else:
                trend = "sideways"

            # RSI on 15m
            delta  = df_15m["close"].diff()
            gain   = delta.clip(lower=0).rolling(14).mean()
            loss   = (-delta.clip(upper=0)).rolling(14).mean()
            rs     = gain / loss.replace(0, float("nan"))
            rsi    = float((100 - 100 / (1 + rs)).iloc[-1])

            # ATR on 15m
            prev_c = df_15m["close"].shift(1)
            tr     = pd.concat([
                df_15m["high"] - df_15m["low"],
                (df_15m["high"] - prev_c).abs(),
                (df_15m["low"]  - prev_c).abs(),
            ], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().iloc[-1])

            # Volume ratio (last candle vs 20-candle avg)
            avg_vol      = float(df_15m["volume"].iloc[-20:].mean())
            last_vol     = float(df_15m["volume"].iloc[-1])
            volume_ratio = round(last_vol / avg_vol, 2) if avg_vol > 0 else 1.0

            return {
                "pair":         symbol,
                "price":        round(price, 6),
                "4h_trend":     trend,
                "rsi_14":       round(rsi, 2),
                "atr":          round(atr, 6),
                "volume_ratio": volume_ratio,
                "ema50_4h":     round(float(ema50_4h), 6),
            }
        except Exception as e:
            log.error(f"get_market_context {symbol}: {e}")
            return {}
