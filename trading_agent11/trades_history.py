"""
Trades history – appends closed trades to an Excel file.
Columns include "Estrategia Elegida" and "Estrategias Disponibles".
"""
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import TRADES_FILE

log = logging.getLogger(__name__)

COLUMNS = [
    "Fecha Entrada",
    "Fecha Salida",
    "Par",
    "Dirección",
    "Estrategia Elegida",
    "Estrategias Disponibles",
    "Precio Entrada",
    "Precio Salida",
    "TP",
    "SL",
    "Cantidad",
    "Nocional",
    "PnL USDT",
    "PnL %",
    "Resultado",
    "Capital Final",
    "ATR",
    "Tendencia 4H",
    "RSI",
]


def _load_or_create() -> pd.DataFrame:
    path = Path(TRADES_FILE)
    if path.exists():
        try:
            return pd.read_excel(path, engine="openpyxl")
        except Exception as e:
            log.warning(f"trades_history: no se pudo leer Excel, recreando: {e}")
    return pd.DataFrame(columns=COLUMNS)


def append_trade(closed_pos: dict, context: dict = None):
    """Append a closed position record to the Excel history file."""
    if context is None:
        context = {}
    path = Path(TRADES_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)

    df = _load_or_create()

    available = closed_pos.get("available_strategies", [closed_pos.get("strategy", "")])
    if isinstance(available, list):
        available_str = ", ".join(str(s) for s in available)
    else:
        available_str = str(available)

    row = {
        "Fecha Entrada":          closed_pos.get("entry_time", ""),
        "Fecha Salida":           closed_pos.get("exit_time", datetime.utcnow().isoformat()),
        "Par":                    closed_pos.get("pair", ""),
        "Dirección":              closed_pos.get("direction", ""),
        "Estrategia Elegida":     closed_pos.get("strategy", ""),
        "Estrategias Disponibles": available_str,
        "Precio Entrada":         closed_pos.get("entry_price", 0),
        "Precio Salida":          closed_pos.get("exit_price", 0),
        "TP":                     closed_pos.get("tp", 0),
        "SL":                     closed_pos.get("sl", 0),
        "Cantidad":               closed_pos.get("qty", 0),
        "Nocional":               closed_pos.get("notional", 0),
        "PnL USDT":               closed_pos.get("pnl", 0),
        "PnL %":                  closed_pos.get("pnl_pct", 0),
        "Resultado":              closed_pos.get("result", ""),
        "Capital Final":          closed_pos.get("final_equity", 0),
        "ATR":                    context.get("atr", ""),
        "Tendencia 4H":           context.get("4h_trend", ""),
        "RSI":                    context.get("rsi_14", ""),
    }

    new_row = pd.DataFrame([row])
    df      = pd.concat([df, new_row], ignore_index=True)

    try:
        df.to_excel(path, index=False, engine="openpyxl")
        log.info(f"trades_history: operación guardada {closed_pos.get('pair')} "
                 f"{closed_pos.get('result')} PnL={closed_pos.get('pnl',0):.2f}")
    except Exception as e:
        log.error(f"trades_history: error al guardar Excel: {e}")


def get_summary_df() -> pd.DataFrame:
    return _load_or_create()
