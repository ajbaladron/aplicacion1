"""
Dashboard – Agente Bitunix [PAPER] v11 — Multi-Strategy Shadow Learning
Accent colour: #8b5cf6 (purple)
Port: 5014
Lock: dashboard11.lock
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template_string

from config import (
    DASHBOARD_PORT, DASHBOARD_LOCK, PORTFOLIO_FILE,
    JOURNAL_FILE, SHADOW_FILE, COSTS_FILE, PAIR_PERF_FILE,
    TRADES_FILE, INITIAL_CAPITAL,
)

log = logging.getLogger(__name__)
app = Flask(__name__)

ACCENT = "#8b5cf6"
TITLE  = "Agente Bitunix [PAPER] v11 — Multi-Strategy Shadow Learning"

# ── HTML template ─────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="30">
<title>{{ title }}</title>
<style>
  :root { --accent: {{ accent }}; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f1a; color: #e2e8f0; font-family: 'Segoe UI', monospace; font-size: 13px; }
  header { background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%);
           border-bottom: 2px solid var(--accent); padding: 14px 24px;
           display: flex; justify-content: space-between; align-items: center; }
  header h1 { color: var(--accent); font-size: 16px; letter-spacing: 1px; }
  header .ts { color: #94a3b8; font-size: 11px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 12px; padding: 16px; }
  .card { background: #1e1b2e; border: 1px solid #2d2a4a; border-radius: 8px; padding: 14px; }
  .card .label { color: #94a3b8; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
  .card .value { color: var(--accent); font-size: 22px; font-weight: 700; margin-top: 4px; }
  .card .sub { color: #64748b; font-size: 11px; margin-top: 2px; }
  .section { margin: 0 16px 16px; }
  .section h2 { color: var(--accent); font-size: 13px; letter-spacing: 1px;
                text-transform: uppercase; border-bottom: 1px solid #2d2a4a;
                padding-bottom: 6px; margin-bottom: 10px; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { background: #1e1b2e; color: #94a3b8; padding: 7px 10px; text-align: left;
       text-transform: uppercase; font-size: 10px; letter-spacing: 0.5px; }
  td { padding: 6px 10px; border-bottom: 1px solid #1e1b2e; }
  tr:hover td { background: #1e1b2e; }
  .long  { color: #10b981; }
  .short { color: #ef4444; }
  .tp    { color: #10b981; font-weight: 600; }
  .sl    { color: #ef4444; font-weight: 600; }
  .open  { color: #fbbf24; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px;
           font-weight: 600; }
  .badge-tp { background: #064e3b; color: #10b981; }
  .badge-sl { background: #450a0a; color: #ef4444; }
  .badge-open { background: #451a03; color: #fbbf24; }
  .badge-long  { background: #064e3b; color: #10b981; }
  .badge-short { background: #450a0a; color: #ef4444; }
  .strategy-tag { background: #312e81; color: #a5b4fc; padding: 1px 6px;
                  border-radius: 3px; font-size: 10px; }
  .pnl-pos { color: #10b981; }
  .pnl-neg { color: #ef4444; }
  footer { text-align: center; color: #374151; padding: 12px; font-size: 11px; }
  .shadow-table th, .shadow-table td { font-size: 11px; }
  .no-data { color: #4b5563; font-style: italic; padding: 12px 0; }
</style>
</head>
<body>
<header>
  <h1>&#9679; {{ title }}</h1>
  <span class="ts">Actualizado: {{ now }} | PAPER TRADING</span>
</header>

<!-- KPI row -->
<div class="grid">
  <div class="card">
    <div class="label">Capital</div>
    <div class="value">{{ equity }} USDT</div>
    <div class="sub">Inicial: {{ initial }} USDT</div>
  </div>
  <div class="card">
    <div class="label">PnL Total</div>
    <div class="value {% if pnl_total >= 0 %}pnl-pos{% else %}pnl-neg{% endif %}">
      {{ "{:+.2f}".format(pnl_total) }} USDT
    </div>
    <div class="sub">{{ "{:+.2f}".format(pnl_pct) }}%</div>
  </div>
  <div class="card">
    <div class="label">Posiciones Abiertas</div>
    <div class="value">{{ open_positions }}</div>
    <div class="sub">Máx: {{ max_pos }}</div>
  </div>
  <div class="card">
    <div class="label">Operaciones Totales</div>
    <div class="value">{{ total_trades }}</div>
    <div class="sub">Win rate: {{ win_rate }}%</div>
  </div>
  <div class="card">
    <div class="label">Costo API Claude</div>
    <div class="value">${{ api_cost }}</div>
    <div class="sub">{{ api_calls }} llamadas</div>
  </div>
  <div class="card">
    <div class="label">Shadow Decisions</div>
    <div class="value">{{ shadow_total }}</div>
    <div class="sub">Pendientes: {{ shadow_pending }}</div>
  </div>
</div>

<!-- Open positions -->
<div class="section">
  <h2>Posiciones Abiertas</h2>
  {% if positions %}
  <table>
    <tr>
      <th>Par</th><th>Dir</th><th>Estrategia</th>
      <th>Entrada</th><th>Precio</th><th>TP</th><th>SL</th>
      <th>PnL</th><th>Desde</th>
    </tr>
    {% for p in positions %}
    <tr>
      <td><b>{{ p.pair }}</b></td>
      <td><span class="badge badge-{{ p.direction.lower() }}">{{ p.direction }}</span></td>
      <td><span class="strategy-tag">{{ p.strategy }}</span></td>
      <td>{{ "%.4f"|format(p.entry_price) }}</td>
      <td>{{ "%.4f"|format(p.current_price) }}</td>
      <td class="tp">{{ "%.4f"|format(p.tp) }}</td>
      <td class="sl">{{ "%.4f"|format(p.sl) }}{% if p.trailing_stop %} &#x21E1;{% endif %}</td>
      <td class="{% if p.unrealized_pnl >= 0 %}pnl-pos{% else %}pnl-neg{% endif %}">
        {{ "{:+.2f}".format(p.unrealized_pnl) }} ({{ "{:+.2f}".format(p.unrealized_pnl_pct) }}%)
      </td>
      <td>{{ p.entry_time[:16] }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p class="no-data">Sin posiciones abiertas.</p>
  {% endif %}
</div>

<!-- Strategy performance -->
<div class="section">
  <h2>Rendimiento por Estrategia</h2>
  {% if strategy_stats %}
  <table>
    <tr><th>Estrategia</th><th>Operaciones</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>PnL Total</th></tr>
    {% for s, st in strategy_stats.items() %}
    <tr>
      <td><span class="strategy-tag">{{ s }}</span></td>
      <td>{{ st.wins + st.losses }}</td>
      <td class="pnl-pos">{{ st.wins }}</td>
      <td class="pnl-neg">{{ st.losses }}</td>
      <td>{{ st.win_rate }}%</td>
      <td class="{% if st.pnl >= 0 %}pnl-pos{% else %}pnl-neg{% endif %}">
        {{ "{:+.2f}".format(st.pnl) }}
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p class="no-data">Sin datos de estrategias todavía.</p>
  {% endif %}
</div>

<!-- Shadow Analysis -->
<div class="section">
  <h2>&#127772; Shadow Analysis — Aprendizaje Multi-Estrategia</h2>
  {% if shadow_insights %}
  <table class="shadow-table">
    <tr>
      <th>Conflicto</th><th>Contexto</th>
      <th>Estrategia A</th><th>WR A</th>
      <th>Estrategia B</th><th>WR B</th>
      <th>Muestras</th>
    </tr>
    {% for conflict, buckets in shadow_insights.items() %}
      {% set strats = conflict.split('_vs_') %}
      {% for bucket, data in buckets.items() %}
      <tr>
        <td><span class="strategy-tag">{{ conflict }}</span></td>
        <td>{{ bucket }}</td>
        <td><span class="strategy-tag">{{ strats[0] }}</span></td>
        <td>{{ (data.get(strats[0] + '_win_rate', 0) * 100) | round(1) }}%</td>
        <td><span class="strategy-tag">{{ strats[-1] }}</span></td>
        <td>{{ (data.get(strats[-1] + '_win_rate', 0) * 100) | round(1) }}%</td>
        <td>{{ data.samples }}</td>
      </tr>
      {% endfor %}
    {% endfor %}
  </table>
  {% else %}
  <p class="no-data">Shadow insights disponibles tras {{ min_samples }} muestras por contexto.</p>
  {% endif %}
</div>

<!-- Recent shadow decisions -->
<div class="section">
  <h2>Últimas Decisiones Shadow (10)</h2>
  {% if recent_decisions %}
  <table class="shadow-table">
    <tr>
      <th>Tiempo</th><th>Par</th><th>Elegida</th>
      <th>Señales Activas</th><th>Contexto</th><th>Estado</th>
    </tr>
    {% for d in recent_decisions %}
    <tr>
      <td>{{ d.timestamp[:16] if d.timestamp else '' }}</td>
      <td><b>{{ d.pair }}</b></td>
      <td>
        {% if d.chosen %}
          <span class="strategy-tag">{{ d.chosen }}</span>
        {% else %}
          <span style="color:#6b7280">SKIP</span>
        {% endif %}
      </td>
      <td>
        {% for name, sig in d.all_signals.items() %}
          {% if sig %}
            <span class="strategy-tag">{{ name }}</span>
          {% endif %}
        {% endfor %}
      </td>
      <td style="font-size:10px">
        {{ d.context.get('4h_trend','') }} RSI={{ d.context.get('rsi_14','?') }}
      </td>
      <td>
        {% if d.status == 'resolved' %}
          <span class="badge badge-tp">Resuelto</span>
        {% else %}
          <span class="badge badge-open">Pendiente</span>
        {% endif %}
      </td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p class="no-data">Sin decisiones registradas todavía.</p>
  {% endif %}
</div>

<!-- Recent trades -->
<div class="section">
  <h2>Últimas Operaciones</h2>
  {% if recent_trades %}
  <table>
    <tr>
      <th>Par</th><th>Dir</th><th>Estrategia</th>
      <th>Entrada</th><th>Salida</th><th>PnL</th><th>Resultado</th><th>Disponibles</th>
    </tr>
    {% for t in recent_trades %}
    <tr>
      <td><b>{{ t.get('Par','') }}</b></td>
      <td><span class="badge badge-{{ t.get('Dirección','').lower() }}">{{ t.get('Dirección','') }}</span></td>
      <td><span class="strategy-tag">{{ t.get('Estrategia Elegida','') }}</span></td>
      <td>{{ t.get('Precio Entrada',0) }}</td>
      <td>{{ t.get('Precio Salida',0) }}</td>
      <td class="{% if t.get('PnL USDT',0) >= 0 %}pnl-pos{% else %}pnl-neg{% endif %}">
        {{ "{:+.2f}".format(t.get('PnL USDT',0)) }}
      </td>
      <td>
        {% if t.get('Resultado') == 'TP' %}
          <span class="badge badge-tp">TP</span>
        {% else %}
          <span class="badge badge-sl">SL</span>
        {% endif %}
      </td>
      <td style="font-size:10px">{{ t.get('Estrategias Disponibles','') }}</td>
    </tr>
    {% endfor %}
  </table>
  {% else %}
  <p class="no-data">Sin operaciones cerradas todavía.</p>
  {% endif %}
</div>

<footer>Trading Agent v11 | Paper Trading | Puerto {{ port }} | {{ now }}</footer>
</body>
</html>"""


def _safe_load(path: str) -> dict | list:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


@app.route("/")
def index():
    portfolio   = _safe_load(PORTFOLIO_FILE)
    equity      = portfolio.get("equity", INITIAL_CAPITAL)
    pnl_total   = round(equity - INITIAL_CAPITAL, 2)
    pnl_pct     = round(pnl_total / INITIAL_CAPITAL * 100, 2)
    positions   = list(portfolio.get("positions", {}).values())
    total_tr    = portfolio.get("total_trades", 0)

    journal_data = _safe_load(JOURNAL_FILE)
    if not isinstance(journal_data, list):
        journal_data = []
    wins      = sum(1 for e in journal_data if e.get("result") == "TP")
    win_rate  = round(wins / len(journal_data) * 100, 1) if journal_data else 0
    strat_stats: dict = {}
    for e in journal_data:
        s = e.get("strategy", "Unknown")
        if s not in strat_stats:
            strat_stats[s] = {"wins": 0, "losses": 0, "pnl": 0}
        if e.get("result") == "TP":
            strat_stats[s]["wins"] += 1
        else:
            strat_stats[s]["losses"] += 1
        strat_stats[s]["pnl"] = round(strat_stats[s]["pnl"] + e.get("pnl", 0), 2)
    for s in strat_stats:
        t = strat_stats[s]["wins"] + strat_stats[s]["losses"]
        strat_stats[s]["win_rate"] = round(strat_stats[s]["wins"] / t * 100, 1) if t else 0

    costs_data = _safe_load(COSTS_FILE)
    api_cost   = round(costs_data.get("total_usd", 0), 4) if isinstance(costs_data, dict) else 0
    api_calls  = costs_data.get("total_calls", 0) if isinstance(costs_data, dict) else 0

    shadow_data    = _safe_load(SHADOW_FILE)
    shadow_list    = shadow_data if isinstance(shadow_data, list) else []
    shadow_total   = len(shadow_list)
    shadow_pending = sum(1 for e in shadow_list if e.get("status") == "pending")

    # Shadow insights (recompute live from shadow file)
    from shadow_tracker import ShadowTracker
    from config import SHADOW_MIN_SAMPLES
    tracker = ShadowTracker()
    shadow_insights   = tracker.get_insights()
    recent_decisions  = tracker.get_recent_decisions(10)

    # Recent trades from Excel
    recent_trades = []
    try:
        import pandas as pd
        df = pd.read_excel(TRADES_FILE, engine="openpyxl")
        recent_trades = df.tail(10).to_dict("records")
    except Exception:
        pass

    return render_template_string(
        HTML,
        title           = TITLE,
        accent          = ACCENT,
        now             = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        equity          = f"{equity:,.2f}",
        initial         = f"{INITIAL_CAPITAL:,.0f}",
        pnl_total       = pnl_total,
        pnl_pct         = pnl_pct,
        open_positions  = len(positions),
        max_pos         = 5,
        total_trades    = total_tr,
        win_rate        = win_rate,
        api_cost        = f"{api_cost:.4f}",
        api_calls       = api_calls,
        shadow_total    = shadow_total,
        shadow_pending  = shadow_pending,
        positions       = positions,
        strategy_stats  = strat_stats,
        shadow_insights = shadow_insights,
        recent_decisions = recent_decisions,
        recent_trades   = recent_trades,
        min_samples     = 5,
        port            = DASHBOARD_PORT,
    )


@app.route("/api/status")
def api_status():
    portfolio = _safe_load(PORTFOLIO_FILE)
    return jsonify({
        "equity":    portfolio.get("equity", INITIAL_CAPITAL),
        "positions": len(portfolio.get("positions", {})),
        "ts":        datetime.utcnow().isoformat(),
    })


def run():
    lock_path = Path(DASHBOARD_LOCK)
    if lock_path.exists():
        log.warning(f"Dashboard lock {DASHBOARD_LOCK} existe. Saliendo.")
        sys.exit(0)
    lock_path.write_text(str(os.getpid()))
    try:
        log.info(f"Dashboard iniciando en puerto {DASHBOARD_PORT}")
        app.run(host="0.0.0.0", port=DASHBOARD_PORT, debug=False, use_reloader=False)
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
