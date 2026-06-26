"""
ShadowTracker – records every multi-strategy decision and tracks hypothetical
outcomes of the strategies that were NOT chosen.  Over time this builds an
insight database of "which strategy wins in which context".
"""
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import SHADOW_FILE, SHADOW_MIN_SAMPLES

log = logging.getLogger(__name__)


def _context_bucket(context: dict) -> str:
    """Map continuous context values to discrete bucket key."""
    trend = context.get("4h_trend", "sideways")
    rsi   = context.get("rsi_14", 50)
    if rsi < 40:
        rsi_bucket = "rsi_low"
    elif rsi > 60:
        rsi_bucket = "rsi_high"
    else:
        rsi_bucket = "rsi_mid"
    return f"{trend}_{rsi_bucket}"


def _conflict_key(strategies: list[str]) -> str:
    """Canonical key for a pair/group of strategies."""
    return "_vs_".join(sorted(strategies))


class ShadowTracker:
    def __init__(self):
        self.path = Path(SHADOW_FILE)
        self._data: list[dict] = []
        self._load()

    # ── Persistence ─────────────────────────────────────────────────────────
    def _load(self):
        if self.path.exists():
            try:
                with open(self.path) as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                log.warning(f"shadow_tracker: no se pudo leer {self.path}: {e}")
                self._data = []
        else:
            self._data = []
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False, default=str)

    # ── Recording ────────────────────────────────────────────────────────────
    def record_decision(
        self,
        pair: str,
        timestamp: str,
        all_signals: dict,
        chosen: Optional[str],
        reasoning: str,
        context: dict,
    ):
        """
        all_signals: {strategy_name: signal_dict_or_None}
        chosen: strategy name that was selected, or None (SKIP_ALL)
        """
        entry = {
            "id":          str(uuid.uuid4()),
            "pair":        pair,
            "timestamp":   timestamp,
            "context":     context,
            "context_bucket": _context_bucket(context),
            "all_signals": all_signals,
            "chosen":      chosen,
            "entry_price": context.get("price"),
            "reasoning":   reasoning,
            "shadow_outcomes": {
                name: None
                for name, sig in all_signals.items()
                if sig is not None and name != chosen
            },
            "status": "pending",
        }
        self._data.append(entry)
        self._save()
        log.info(f"shadow_tracker: decisión registrada {pair} -> {chosen or 'SKIP_ALL'}")

    # ── Update shadows ────────────────────────────────────────────────────────
    def update_shadow_results(self, current_prices: dict):
        """
        current_prices: {pair: current_price}
        For each pending entry, check if non-chosen signals have resolved.
        """
        changed = False
        for entry in self._data:
            if entry["status"] != "pending":
                continue
            pair  = entry["pair"]
            price = current_prices.get(pair)
            if price is None:
                continue

            entry_price = entry.get("entry_price")
            if not entry_price:
                continue

            all_resolved = True
            for strategy, outcome in entry["shadow_outcomes"].items():
                if outcome is not None:
                    continue  # already resolved

                sig = entry["all_signals"].get(strategy)
                if not sig:
                    continue

                tp = sig.get("tp")
                sl = sig.get("sl")
                direction = sig.get("direction")
                if not all([tp, sl, direction]):
                    continue

                resolved = False
                if direction == "LONG":
                    if price >= tp:
                        pnl_pct = (tp - entry_price) / entry_price
                        entry["shadow_outcomes"][strategy] = {
                            "result":      "TP",
                            "pnl_pct":     round(pnl_pct, 5),
                            "exit_price":  tp,
                            "resolved_at": datetime.utcnow().isoformat(),
                        }
                        resolved = True
                    elif price <= sl:
                        pnl_pct = (sl - entry_price) / entry_price
                        entry["shadow_outcomes"][strategy] = {
                            "result":      "SL",
                            "pnl_pct":     round(pnl_pct, 5),
                            "exit_price":  sl,
                            "resolved_at": datetime.utcnow().isoformat(),
                        }
                        resolved = True
                elif direction == "SHORT":
                    if price <= tp:
                        pnl_pct = (entry_price - tp) / entry_price
                        entry["shadow_outcomes"][strategy] = {
                            "result":      "TP",
                            "pnl_pct":     round(pnl_pct, 5),
                            "exit_price":  tp,
                            "resolved_at": datetime.utcnow().isoformat(),
                        }
                        resolved = True
                    elif price >= sl:
                        pnl_pct = (entry_price - sl) / entry_price
                        entry["shadow_outcomes"][strategy] = {
                            "result":      "SL",
                            "pnl_pct":     round(pnl_pct, 5),
                            "exit_price":  sl,
                            "resolved_at": datetime.utcnow().isoformat(),
                        }
                        resolved = True

                if not resolved:
                    all_resolved = False

            # Check if all non-chosen shadows resolved
            if all_resolved and all(v is not None for v in entry["shadow_outcomes"].values()):
                entry["status"] = "resolved"

            changed = True

        if changed:
            self._save()

    # ── Insights ─────────────────────────────────────────────────────────────
    def get_insights(self, min_samples: int = None) -> dict:
        """
        Returns win-rate stats for strategy conflicts grouped by context bucket.
        Structure:
          {
            "DTDS_vs_SuperTrend": {
              "bullish_rsi_mid": {
                "samples": 8,
                "DTDS_wins": 2, "SuperTrend_wins": 6,
                "description": "..."
              }
            }
          }
        Only includes buckets with >= min_samples entries.
        """
        if min_samples is None:
            min_samples = SHADOW_MIN_SAMPLES

        # Gather resolved entries where >=2 strategies had signals
        stats: dict = {}

        for entry in self._data:
            if entry["status"] != "resolved":
                continue

            chosen = entry.get("chosen")
            if not chosen:
                continue

            bucket  = entry.get("context_bucket", "unknown")
            signals = entry["all_signals"]
            active  = [k for k, v in signals.items() if v is not None]

            if len(active) < 2:
                continue  # no conflict to learn from

            shadow_outcomes = entry.get("shadow_outcomes", {})
            entry_price     = entry.get("entry_price", 0)

            # Determine which strategy "won" for this decision
            # Winner = whichever had a TP outcome (or best pnl)
            outcomes_for_entry = {}
            for strategy in active:
                if strategy == chosen:
                    # We don't track real outcome here (that's in trades_history)
                    # Mark as unknown for shadow comparison purposes
                    outcomes_for_entry[strategy] = None
                else:
                    outcome = shadow_outcomes.get(strategy)
                    if outcome:
                        outcomes_for_entry[strategy] = outcome.get("result")

            # Only process conflicts between non-chosen shadows
            shadow_strategies = [s for s in active if s != chosen]
            if len(shadow_strategies) < 1:
                continue

            # For each pair of active strategies
            all_strats = active  # includes chosen
            for i in range(len(all_strats)):
                for j in range(i + 1, len(all_strats)):
                    s_a = all_strats[i]
                    s_b = all_strats[j]
                    key = _conflict_key([s_a, s_b])

                    if key not in stats:
                        stats[key] = {}
                    if bucket not in stats[key]:
                        stats[key][bucket] = {
                            "samples": 0,
                            s_a: {"wins": 0, "total": 0},
                            s_b: {"wins": 0, "total": 0},
                        }

                    bucket_data = stats[key][bucket]
                    bucket_data["samples"] += 1

                    # Determine winner between s_a and s_b
                    result_a = outcomes_for_entry.get(s_a)
                    result_b = outcomes_for_entry.get(s_b)

                    if s_a in bucket_data:
                        bucket_data[s_a]["total"] += 1
                        if result_a == "TP":
                            bucket_data[s_a]["wins"] += 1

                    if s_b in bucket_data:
                        bucket_data[s_b]["total"] += 1
                        if result_b == "TP":
                            bucket_data[s_b]["wins"] += 1

        # Filter by min_samples and add descriptions
        insights = {}
        for conflict_key, buckets in stats.items():
            strategies = conflict_key.split("_vs_")
            for bucket, data in buckets.items():
                if data["samples"] < min_samples:
                    continue
                if conflict_key not in insights:
                    insights[conflict_key] = {}
                s_a, s_b = strategies[0], strategies[-1]
                wr_a = (data.get(s_a, {}).get("wins", 0) /
                        max(data.get(s_a, {}).get("total", 1), 1))
                wr_b = (data.get(s_b, {}).get("wins", 0) /
                        max(data.get(s_b, {}).get("total", 1), 1))
                wins_a = data.get(s_a, {}).get("wins", 0)
                wins_b = data.get(s_b, {}).get("wins", 0)
                total  = data["samples"]
                desc = (
                    f"Cuando {s_a} vs {s_b} conflictan + contexto={bucket}: "
                    f"{s_a} gana {wins_a}/{total}, {s_b} gana {wins_b}/{total}"
                )
                insights[conflict_key][bucket] = {
                    "samples":         total,
                    f"{s_a}_win_rate": round(wr_a, 3),
                    f"{s_b}_win_rate": round(wr_b, 3),
                    f"{s_a}_wins":     wins_a,
                    f"{s_b}_wins":     wins_b,
                    "description":     desc,
                }

        return insights

    def get_recent_decisions(self, n: int = 10) -> list[dict]:
        """Return last n decisions (any status) for dashboard display."""
        return self._data[-n:]

    def total_count(self) -> int:
        return len(self._data)

    def pending_count(self) -> int:
        return sum(1 for e in self._data if e["status"] == "pending")
