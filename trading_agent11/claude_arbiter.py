"""
ClaudeArbiter – uses Claude to choose between conflicting strategy signals,
or approve/reject a single signal.  Tracks API cost.
All prompts and responses are in Spanish.
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic

from config import (
    CLAUDE_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS, COSTS_FILE,
)

log = logging.getLogger(__name__)

# Approximate pricing (USD per 1M tokens) for haiku-class models
INPUT_PRICE_PER_M  = 0.80
OUTPUT_PRICE_PER_M = 4.00


class ClaudeArbiter:
    def __init__(self):
        self.client     = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
        self.costs_path = Path(COSTS_FILE)
        self._costs: dict = self._load_costs()

    # ── Cost tracking ────────────────────────────────────────────────────────
    def _load_costs(self) -> dict:
        if self.costs_path.exists():
            try:
                with open(self.costs_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"total_usd": 0.0, "total_calls": 0, "calls": []}

    def _save_costs(self):
        self.costs_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.costs_path, "w") as f:
            json.dump(self._costs, f, indent=2, default=str)

    def _track_cost(self, input_tokens: int, output_tokens: int, pair: str):
        cost = (input_tokens * INPUT_PRICE_PER_M / 1_000_000 +
                output_tokens * OUTPUT_PRICE_PER_M / 1_000_000)
        self._costs["total_usd"]   = round(self._costs["total_usd"] + cost, 6)
        self._costs["total_calls"] += 1
        self._costs["calls"].append({
            "ts":     datetime.utcnow().isoformat(),
            "pair":   pair,
            "in_tok": input_tokens,
            "out_tok": output_tokens,
            "cost":   round(cost, 6),
        })
        if len(self._costs["calls"]) > 500:
            self._costs["calls"] = self._costs["calls"][-500:]
        self._save_costs()
        return cost

    # ── Single-signal mode (behave like agent7 claude_filter) ────────────────
    def _prompt_single(
        self,
        pair: str,
        strategy_name: str,
        signal: dict,
        context: dict,
        journal_insights: list[dict],
    ) -> str:
        journal_text = ""
        if journal_insights:
            lines = []
            for j in journal_insights[-5:]:
                lines.append(
                    f"  - {j.get('pair','?')} {j.get('direction','?')} "
                    f"{j.get('strategy','?')}: {j.get('result','?')} "
                    f"PnL={j.get('pnl_pct',0)*100:.2f}%"
                )
            journal_text = "Últimas operaciones:\n" + "\n".join(lines)

        return f"""Eres un árbitro de trading experto. Analiza la siguiente señal y decide si operar.

Par: {pair}
Estrategia: {strategy_name}
Dirección: {signal.get('direction')}
Entrada: {signal.get('entry_type','market')}
TP: {signal.get('tp')}
SL: {signal.get('sl')}
ATR: {signal.get('atr')}
Score: {signal.get('score')}
Razón: {signal.get('reason','')}

Contexto de mercado:
- Tendencia 4H: {context.get('4h_trend','desconocida')}
- RSI 14: {context.get('rsi_14','?')}
- Precio actual: {context.get('price','?')}
- Relación volumen: {context.get('volume_ratio','?')}

{journal_text}

Responde ÚNICAMENTE en este formato JSON:
{{"decision": "ENTER" o "SKIP", "reasoning": "explicación breve en español"}}"""

    # ── Multi-signal arbitration ─────────────────────────────────────────────
    def _prompt_multi(
        self,
        pair: str,
        signals_dict: dict,
        context: dict,
        shadow_insights: dict,
        journal_insights: list[dict],
    ) -> str:
        signals_text = ""
        for name, sig in signals_dict.items():
            signals_text += f"""
Estrategia: {name}
  Dirección: {sig.get('direction')}  Tipo entrada: {sig.get('entry_type','market')}
  TP: {sig.get('tp')}  SL: {sig.get('sl')}  ATR: {sig.get('atr')}
  Score: {sig.get('score')}
  Razón: {sig.get('reason','')}
"""
        active_names = list(signals_dict.keys())
        shadow_text  = ""
        if shadow_insights:
            lines = []
            for conflict, buckets in shadow_insights.items():
                strats = conflict.split("_vs_")
                if all(s in active_names for s in strats):
                    for bucket, data in buckets.items():
                        lines.append(f"  - {data.get('description','')}")
            if lines:
                shadow_text = "Historial shadow learning:\n" + "\n".join(lines)

        journal_text = ""
        if journal_insights:
            lines = []
            for j in journal_insights[-5:]:
                lines.append(
                    f"  - {j.get('pair','?')} {j.get('direction','?')} "
                    f"{j.get('strategy','?')}: {j.get('result','?')} "
                    f"PnL={j.get('pnl_pct',0)*100:.2f}%"
                )
            journal_text = "Últimas operaciones:\n" + "\n".join(lines)

        strategy_options = ", ".join(f'"{n}"' for n in active_names)

        return f"""Eres un árbitro de trading experto. Múltiples estrategias dan señal simultánea para {pair}. Elige la mejor.

SEÑALES ACTIVAS:
{signals_text}

Contexto de mercado:
- Tendencia 4H: {context.get('4h_trend','desconocida')}
- RSI 14: {context.get('rsi_14','?')}
- Precio actual: {context.get('price','?')}
- Relación volumen: {context.get('volume_ratio','?')}
- ATR: {context.get('atr','?')}

{shadow_text}

{journal_text}

Opciones de decisión: {strategy_options} o "SKIP_ALL"

Responde ÚNICAMENTE en este formato JSON:
{{"chosen": <nombre_estrategia_o_null>, "reasoning": "explicación breve en español"}}

Si eliges una estrategia, "chosen" debe ser exactamente uno de: {strategy_options}
Si decides no operar, "chosen" debe ser null."""

    # ── Public interface ──────────────────────────────────────────────────────
    def choose(
        self,
        pair: str,
        signals_dict: dict,
        market_context: dict,
        shadow_insights: dict,
        journal_insights: Optional[list] = None,
    ) -> tuple[Optional[str], str]:
        """
        signals_dict: {strategy_name: signal_dict} — only active signals (not None).
        Returns (chosen_strategy_name_or_None, reasoning_text).
        """
        if journal_insights is None:
            journal_insights = []

        n_signals = len(signals_dict)
        if n_signals == 0:
            return None, "Sin señales activas."

        if n_signals == 1:
            strategy_name, signal = next(iter(signals_dict.items()))
            prompt = self._prompt_single(
                pair, strategy_name, signal, market_context, journal_insights
            )
        else:
            prompt = self._prompt_multi(
                pair, signals_dict, market_context, shadow_insights, journal_insights
            )

        try:
            resp = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            raw      = resp.content[0].text.strip()
            in_tok   = resp.usage.input_tokens
            out_tok  = resp.usage.output_tokens
            self._track_cost(in_tok, out_tok, pair)

            # Parse JSON response
            # Strip any markdown fences if present
            text = raw
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            parsed    = json.loads(text.strip())

            if n_signals == 1:
                decision  = parsed.get("decision", "SKIP")
                reasoning = parsed.get("reasoning", "")
                if decision == "ENTER":
                    return strategy_name, reasoning
                else:
                    return None, reasoning
            else:
                chosen    = parsed.get("chosen")
                reasoning = parsed.get("reasoning", "")
                # Validate chosen is a real active strategy
                if chosen and chosen not in signals_dict:
                    log.warning(f"Claude devolvió estrategia desconocida '{chosen}', omitiendo")
                    return None, reasoning
                return chosen if chosen else None, reasoning

        except json.JSONDecodeError as e:
            log.error(f"claude_arbiter: JSON inválido de Claude para {pair}: {e}\nRaw: {raw}")
            # Fallback: pick highest-score strategy
            return self._fallback(signals_dict)
        except Exception as e:
            log.error(f"claude_arbiter: error API para {pair}: {e}")
            return self._fallback(signals_dict)

    def _fallback(self, signals_dict: dict) -> tuple[Optional[str], str]:
        """Fallback when Claude API fails: pick highest-scored signal."""
        if not signals_dict:
            return None, "API error — sin señales."
        best = max(signals_dict.items(), key=lambda x: x[1].get("score", 0))
        return best[0], f"Fallback automático (API error): elegida {best[0]} por mayor score."

    def total_cost_usd(self) -> float:
        return self._costs.get("total_usd", 0.0)

    def total_calls(self) -> int:
        return self._costs.get("total_calls", 0)
