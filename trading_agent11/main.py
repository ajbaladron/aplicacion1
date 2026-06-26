"""
trading_agent11 – Multi-Strategy Shadow Learning Agent
Lock: main11.lock | Guard: trading_agent11 | Port: 5014
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Guard: prevent duplicate processes ───────────────────────────────────────
GUARD_NAME = "trading_agent11"
MAIN_LOCK  = "main11.lock"

def _acquire_lock():
    lock = Path(MAIN_LOCK)
    if lock.exists():
        try:
            pid = int(lock.read_text().strip())
            # Check if process still running
            os.kill(pid, 0)
            print(f"[{GUARD_NAME}] Ya está en ejecución (PID {pid}). Saliendo.")
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            lock.unlink(missing_ok=True)
    lock.write_text(str(os.getpid()))
    return lock

_lock_path = _acquire_lock()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"trading_agent11/agent11.log", mode="a"),
    ],
)
log = logging.getLogger(GUARD_NAME)

# ── Imports (after lock acquired) ─────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    PAPER_TRADING, SCAN_INTERVAL_MIN, MONITOR_INTERVAL_S,
    STATE_FILE, PAIR_PERF_FILE, INITIAL_CAPITAL,
)
from bitunix_client import BitunixClient
from portfolio import VirtualPortfolio
from journal import Journal
from trades_history import append_trade
from shadow_tracker import ShadowTracker
from claude_arbiter import ClaudeArbiter
from strategies import dtds, supertrend, ema_crossover, vwap_structure

client  = BitunixClient()
port    = VirtualPortfolio()
journal = Journal()
tracker = ShadowTracker()
arbiter = ClaudeArbiter()


# ── State helpers ─────────────────────────────────────────────────────────────
def load_state() -> dict:
    path = Path(STATE_FILE)
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "last_scan":    None,
        "scan_count":   0,
        "pairs_scanned": [],
        "started_at":  datetime.utcnow().isoformat(),
    }


def save_state(state: dict):
    path = Path(STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2, default=str)


def update_pair_performance(pair: str, closed_pos: dict):
    path = Path(PAIR_PERF_FILE)
    data: dict = {}
    if path.exists():
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            pass
    if pair not in data:
        data[pair] = {"wins": 0, "losses": 0, "pnl": 0, "trades": 0}
    data[pair]["trades"] += 1
    data[pair]["pnl"]     = round(data[pair]["pnl"] + closed_pos.get("pnl", 0), 4)
    if closed_pos.get("result") == "TP":
        data[pair]["wins"] += 1
    else:
        data[pair]["losses"] += 1
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Signal detection ──────────────────────────────────────────────────────────
def run_all_detectors(pair: str) -> dict:
    """Run all 4 strategy detectors; return {name: signal_or_None}."""
    try:
        df_15m = client.get_klines(pair, "15m", 250)
    except Exception as e:
        log.error(f"get_klines 15m {pair}: {e}")
        return {}

    if df_15m.empty or len(df_15m) < 50:
        return {}

    results = {}
    for name, module in [
        ("DTDS",           dtds),
        ("SuperTrend",     supertrend),
        ("EMA_Crossover",  ema_crossover),
        ("VWAP_Structure", vwap_structure),
    ]:
        try:
            results[name] = module.detect(df_15m)
        except Exception as e:
            log.warning(f"{name} detector error {pair}: {e}")
            results[name] = None

    return results


# ── Position entry ────────────────────────────────────────────────────────────
def enter_position(pair: str, chosen_strategy: str, signal: dict,
                   context: dict, available_strategies: list[str]):
    """Open a paper position based on the chosen signal."""
    price = context.get("price")
    if not price:
        try:
            price = client.get_price(pair)
        except Exception:
            pass
    if not price:
        log.warning(f"enter_position: sin precio para {pair}")
        return

    # DTDS uses on_touch entry logic: reference the ema_mid touch price
    # but we still open at market for simplicity in paper mode
    entry_type    = signal.get("entry_type", "market")
    touch_price   = signal.get("touch_price")
    trailing      = signal.get("trailing_stop", False)
    trailing_val  = signal.get("trailing_value")

    pos = port.open_position(
        pair                = pair,
        direction           = signal["direction"],
        entry_price         = touch_price if (entry_type == "on_touch" and touch_price) else price,
        tp                  = signal["tp"],
        sl                  = signal["sl"],
        strategy            = chosen_strategy,
        atr                 = signal.get("atr", 0),
        entry_type          = entry_type,
        touch_price         = touch_price,
        trailing_stop       = trailing,
        trailing_value      = trailing_val,
        available_strategies = available_strategies,
    )
    if pos:
        log.info(f"POSICIÓN ABIERTA: {pair} {signal['direction']} [{chosen_strategy}] "
                 f"entry={pos['entry_price']} tp={signal['tp']} sl={signal['sl']}")


# ── 15-minute scan loop ───────────────────────────────────────────────────────
def scan_cycle(state: dict):
    log.info("=== INICIANDO ESCANEO DE PARES ===")
    try:
        pairs = client.get_top_pairs()
    except Exception as e:
        log.error(f"get_top_pairs: {e}")
        return

    if not pairs:
        log.warning("Sin pares disponibles.")
        return

    log.info(f"Escaneando {len(pairs)} pares...")
    state["pairs_scanned"] = pairs
    state["scan_count"]    = state.get("scan_count", 0) + 1
    state["last_scan"]     = datetime.utcnow().isoformat()
    save_state(state)

    shadow_insights = tracker.get_insights()
    journal_recent  = journal.get_recent(5)

    for pair in pairs:
        if port.has_position(pair):
            continue  # already in this pair

        # Run all 4 detectors
        signals_dict = run_all_detectors(pair)
        if not signals_dict:
            continue

        # Filter active (non-None) signals
        active = {k: v for k, v in signals_dict.items() if v is not None}
        if not active:
            continue

        # Get market context for arbitration
        try:
            context = client.get_market_context(pair)
        except Exception as e:
            log.warning(f"get_market_context {pair}: {e}")
            context = {"pair": pair}

        if not context:
            context = {"pair": pair}

        log.info(f"{pair}: {len(active)} señal(es) activa(s): {list(active.keys())}")

        # Arbiter decides
        chosen, reasoning = arbiter.choose(
            pair            = pair,
            signals_dict    = active,
            market_context  = context,
            shadow_insights = shadow_insights,
            journal_insights = journal_recent,
        )

        log.info(f"{pair} → elegida={chosen or 'SKIP_ALL'} | {reasoning[:100]}")

        # Record shadow decision (always, even if skipped)
        ts = datetime.utcnow().isoformat()
        tracker.record_decision(
            pair        = pair,
            timestamp   = ts,
            all_signals = signals_dict,
            chosen      = chosen,
            reasoning   = reasoning,
            context     = context,
        )

        # Open position if a strategy was chosen
        if chosen and chosen in active:
            enter_position(
                pair                 = pair,
                chosen_strategy      = chosen,
                signal               = active[chosen],
                context              = context,
                available_strategies = list(active.keys()),
            )

        time.sleep(0.3)  # Rate-limit API calls between pairs


# ── 1-minute monitor loop ─────────────────────────────────────────────────────
def monitor_cycle():
    open_positions = port.positions
    if not open_positions:
        return

    pairs = list(open_positions.keys())
    try:
        current_prices = client.get_prices_bulk(pairs)
    except Exception as e:
        log.error(f"get_prices_bulk: {e}")
        return

    # Fallback: fetch individually for missing prices
    for pair in pairs:
        if pair not in current_prices:
            try:
                p = client.get_price(pair)
                if p:
                    current_prices[pair] = p
            except Exception:
                pass

    # Update unrealized PnL
    for pair, price in current_prices.items():
        port.update_position_price(pair, price)

    # Update trailing stops for SuperTrend positions
    for pair, pos in list(open_positions.items()):
        if pos.get("strategy") == "SuperTrend" and pos.get("trailing_stop"):
            try:
                df_15m = client.get_klines(pair, "15m", 30)
                if not df_15m.empty:
                    new_sl = supertrend.get_trailing_sl(df_15m)
                    if new_sl:
                        port.update_trailing_sl(pair, new_sl)
            except Exception as e:
                log.debug(f"trailing update {pair}: {e}")

    # Check exits (TP / SL hit)
    closed_positions = port.check_exits(current_prices)
    for closed in closed_positions:
        pair = closed["pair"]
        log.info(f"CERRADA: {pair} {closed['direction']} {closed['result']} "
                 f"PnL={closed['pnl']:.2f} USDT ({closed['pnl_pct']:.2f}%)")
        journal.add_trade(closed)
        append_trade(closed, context={})
        update_pair_performance(pair, closed)

    # Update shadow results with current prices
    tracker.update_shadow_results(current_prices)


# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    mode = "[PAPER]" if PAPER_TRADING else "[LIVE]"
    log.info(f"{'='*60}")
    log.info(f"  {GUARD_NAME} iniciando {mode}")
    log.info(f"  Capital inicial: {INITIAL_CAPITAL:,.2f} USDT")
    log.info(f"  Estrategias: DTDS, SuperTrend, EMA_Crossover, VWAP_Structure")
    log.info(f"  Escaneo: cada {SCAN_INTERVAL_MIN} min | Monitor: cada {MONITOR_INTERVAL_S}s")
    log.info(f"{'='*60}")

    state             = load_state()
    scan_interval_s   = SCAN_INTERVAL_MIN * 60
    last_scan_time    = 0.0

    try:
        while True:
            now = time.time()

            # 15-minute scan
            if now - last_scan_time >= scan_interval_s:
                try:
                    scan_cycle(state)
                except Exception as e:
                    log.error(f"scan_cycle error: {e}", exc_info=True)
                last_scan_time = time.time()

            # 1-minute monitor
            try:
                monitor_cycle()
            except Exception as e:
                log.error(f"monitor_cycle error: {e}", exc_info=True)

            time.sleep(MONITOR_INTERVAL_S)

    except KeyboardInterrupt:
        log.info("Agente detenido por usuario.")
    finally:
        _lock_path.unlink(missing_ok=True)
        log.info("Lock liberado.")


if __name__ == "__main__":
    main()
