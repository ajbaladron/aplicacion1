"""
Virtual portfolio manager for paper trading.
Tracks equity, open positions, and simulates order fills at current prices.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import (
    PORTFOLIO_FILE, INITIAL_CAPITAL, RISK_PER_TRADE,
    MAX_POSITIONS, MAX_LEVERAGE, ATR_MULTIPLIER_SL,
)

log = logging.getLogger(__name__)

POSITION_FIELDS = [
    "id", "pair", "direction", "strategy",
    "entry_price", "current_price", "qty", "notional",
    "tp", "sl", "trailing_stop", "trailing_value",
    "entry_time", "entry_type", "touch_price",
    "unrealized_pnl", "unrealized_pnl_pct",
    "available_strategies",
]


class VirtualPortfolio:
    def __init__(self):
        self.path = Path(PORTFOLIO_FILE)
        self._state: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path) as f:
                    self._state = json.load(f)
                return
            except Exception as e:
                log.warning(f"portfolio: no se pudo leer {self.path}: {e}")
        self._state = {
            "equity":      INITIAL_CAPITAL,
            "cash":        INITIAL_CAPITAL,
            "positions":   {},
            "total_trades": 0,
            "created_at":  datetime.utcnow().isoformat(),
        }
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._state, f, indent=2, default=str)

    # ── Helpers ──────────────────────────────────────────────────────────────
    @property
    def equity(self) -> float:
        return self._state["equity"]

    @property
    def cash(self) -> float:
        return self._state["cash"]

    @property
    def positions(self) -> dict:
        return self._state["positions"]

    def open_count(self) -> int:
        return len(self._state["positions"])

    def has_position(self, pair: str) -> bool:
        return pair in self._state["positions"]

    # ── ATR-based position sizing ─────────────────────────────────────────────
    def calc_size(self, price: float, sl: float, direction: str) -> float:
        """
        Risk 1% of equity per trade.
        qty = (equity * risk) / (|price - sl|)
        Capped by MAX_LEVERAGE on notional.
        """
        risk_amount = self.equity * RISK_PER_TRADE
        stop_dist   = abs(price - sl)
        if stop_dist == 0:
            return 0.0
        qty = risk_amount / stop_dist
        # Leverage cap
        notional    = qty * price
        max_notional = self.equity * MAX_LEVERAGE
        if notional > max_notional:
            qty = max_notional / price
        return round(qty, 6)

    # ── Open position ─────────────────────────────────────────────────────────
    def open_position(
        self,
        pair: str,
        direction: str,
        entry_price: float,
        tp: float,
        sl: float,
        strategy: str,
        atr: float,
        entry_type: str = "market",
        touch_price: Optional[float] = None,
        trailing_stop: bool = False,
        trailing_value: Optional[float] = None,
        available_strategies: Optional[list] = None,
    ) -> Optional[dict]:
        if self.open_count() >= MAX_POSITIONS:
            log.info(f"portfolio: máximo de posiciones alcanzado ({MAX_POSITIONS})")
            return None
        if self.has_position(pair):
            log.info(f"portfolio: ya existe posición en {pair}")
            return None

        qty = self.calc_size(entry_price, sl, direction)
        if qty <= 0:
            log.warning(f"portfolio: qty=0 para {pair}")
            return None

        notional = round(qty * entry_price, 4)
        pos_id   = f"{pair}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        position = {
            "id":                    pos_id,
            "pair":                  pair,
            "direction":             direction,
            "strategy":              strategy,
            "entry_price":           entry_price,
            "current_price":         entry_price,
            "qty":                   qty,
            "notional":              notional,
            "tp":                    tp,
            "sl":                    sl,
            "trailing_stop":         trailing_stop,
            "trailing_value":        trailing_value or sl,
            "entry_time":            datetime.utcnow().isoformat(),
            "entry_type":            entry_type,
            "touch_price":           touch_price,
            "unrealized_pnl":        0.0,
            "unrealized_pnl_pct":    0.0,
            "available_strategies":  available_strategies or [strategy],
        }

        self._state["positions"][pair] = position
        self._save()
        log.info(f"portfolio: ABIERTA {direction} {pair} @ {entry_price} qty={qty} "
                 f"tp={tp} sl={sl} [{strategy}]")
        return position

    # ── Update prices ─────────────────────────────────────────────────────────
    def update_position_price(self, pair: str, current_price: float):
        pos = self._state["positions"].get(pair)
        if not pos:
            return
        pos["current_price"] = current_price
        entry = pos["entry_price"]
        qty   = pos["qty"]
        if pos["direction"] == "LONG":
            pnl = (current_price - entry) * qty
        else:
            pnl = (entry - current_price) * qty
        pos["unrealized_pnl"]     = round(pnl, 4)
        pos["unrealized_pnl_pct"] = round(pnl / (entry * qty) * 100, 4)

    def update_trailing_sl(self, pair: str, new_sl: float):
        """Update trailing stop if the new SL is more favorable."""
        pos = self._state["positions"].get(pair)
        if not pos or not pos.get("trailing_stop"):
            return
        if pos["direction"] == "LONG" and new_sl > pos["trailing_value"]:
            pos["trailing_value"] = new_sl
            pos["sl"]             = new_sl
            log.debug(f"portfolio: trailing SL {pair} actualizado a {new_sl}")
        elif pos["direction"] == "SHORT" and new_sl < pos["trailing_value"]:
            pos["trailing_value"] = new_sl
            pos["sl"]             = new_sl
            log.debug(f"portfolio: trailing SL {pair} actualizado a {new_sl}")
        self._save()

    # ── Check exits ───────────────────────────────────────────────────────────
    def check_exits(self, current_prices: dict) -> list[dict]:
        """
        Check all open positions against current prices.
        Returns list of closed position dicts (with pnl, result).
        """
        closed = []
        for pair, pos in list(self._state["positions"].items()):
            price = current_prices.get(pair)
            if price is None:
                continue
            self.update_position_price(pair, price)
            result = None
            exit_price = None

            if pos["direction"] == "LONG":
                if price >= pos["tp"]:
                    result, exit_price = "TP", pos["tp"]
                elif price <= pos["sl"]:
                    result, exit_price = "SL", pos["sl"]
            else:
                if price <= pos["tp"]:
                    result, exit_price = "TP", pos["tp"]
                elif price >= pos["sl"]:
                    result, exit_price = "SL", pos["sl"]

            if result:
                closed_pos = self._close_position(pair, exit_price, result)
                closed.append(closed_pos)

        return closed

    def _close_position(self, pair: str, exit_price: float, result: str) -> dict:
        pos   = self._state["positions"].pop(pair)
        entry = pos["entry_price"]
        qty   = pos["qty"]
        if pos["direction"] == "LONG":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        pnl_pct = pnl / (entry * qty) * 100
        self._state["equity"] = round(self._state["equity"] + pnl, 4)
        self._state["total_trades"] += 1
        self._save()

        closed = {
            **pos,
            "exit_price":    exit_price,
            "exit_time":     datetime.utcnow().isoformat(),
            "result":        result,
            "pnl":           round(pnl, 4),
            "pnl_pct":       round(pnl_pct, 4),
            "final_equity":  self._state["equity"],
        }
        log.info(f"portfolio: CERRADA {pos['direction']} {pair} {result} "
                 f"pnl={pnl:.2f} USDT ({pnl_pct:.2f}%)")
        return closed

    # ── Handle pending on-touch orders ───────────────────────────────────────
    def check_touch_entries(self, current_prices: dict) -> list[tuple]:
        """
        For any position opened with entry_type='on_touch' that is still
        pending (no entry_price set yet), check if price has touched touch_price.
        Returns list of (pair,) that should now be entered at market.
        NOT USED directly — main.py opens DTDS positions immediately for simplicity,
        with the EMA mid price as the reference entry.
        """
        return []

    def get_summary(self) -> dict:
        return {
            "equity":       self._state["equity"],
            "cash":         self._state["cash"],
            "open_positions": self.open_count(),
            "total_trades": self._state["total_trades"],
            "positions":    list(self._state["positions"].values()),
        }
