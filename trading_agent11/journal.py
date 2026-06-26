"""
Trading journal – stores closed trade summaries used by ClaudeArbiter as context.
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from config import JOURNAL_FILE

log = logging.getLogger(__name__)


class Journal:
    def __init__(self):
        self.path = Path(JOURNAL_FILE)
        self._entries: list[dict] = []
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path) as f:
                    self._entries = json.load(f)
            except Exception as e:
                log.warning(f"journal: no se pudo leer: {e}")
                self._entries = []
        else:
            self._entries = []
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._entries, f, indent=2, default=str, ensure_ascii=False)

    def add_trade(self, closed_pos: dict):
        entry = {
            "ts":         datetime.utcnow().isoformat(),
            "pair":       closed_pos.get("pair"),
            "direction":  closed_pos.get("direction"),
            "strategy":   closed_pos.get("strategy"),
            "result":     closed_pos.get("result"),
            "pnl":        closed_pos.get("pnl"),
            "pnl_pct":    closed_pos.get("pnl_pct"),
            "entry_price": closed_pos.get("entry_price"),
            "exit_price":  closed_pos.get("exit_price"),
            "entry_time":  closed_pos.get("entry_time"),
            "exit_time":   closed_pos.get("exit_time"),
            "available_strategies": closed_pos.get("available_strategies", []),
        }
        self._entries.append(entry)
        if len(self._entries) > 1000:
            self._entries = self._entries[-1000:]
        self._save()

    def get_recent(self, n: int = 5) -> list[dict]:
        return self._entries[-n:]

    def get_stats(self) -> dict:
        if not self._entries:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_pnl": 0}
        wins   = [e for e in self._entries if e.get("result") == "TP"]
        losses = [e for e in self._entries if e.get("result") == "SL"]
        total_pnl = sum(e.get("pnl", 0) for e in self._entries)
        return {
            "total":    len(self._entries),
            "wins":     len(wins),
            "losses":   len(losses),
            "win_rate": round(len(wins) / len(self._entries) * 100, 1),
            "total_pnl": round(total_pnl, 2),
        }

    def get_strategy_stats(self) -> dict:
        stats = {}
        for e in self._entries:
            s = e.get("strategy", "Unknown")
            if s not in stats:
                stats[s] = {"wins": 0, "losses": 0, "pnl": 0}
            if e.get("result") == "TP":
                stats[s]["wins"] += 1
            else:
                stats[s]["losses"] += 1
            stats[s]["pnl"] = round(stats[s]["pnl"] + e.get("pnl", 0), 2)
        for s in stats:
            total = stats[s]["wins"] + stats[s]["losses"]
            stats[s]["win_rate"] = round(stats[s]["wins"] / total * 100, 1) if total else 0
        return stats
