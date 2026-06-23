"""
Pionex Perpetual Futures — API client (HMAC-SHA256).

Docs: https://pionex-doc.gitbook.io/apidocs
Autenticacion:
  - Header  PIONEX-KEY       : api_key
  - Query   timestamp        : unix ms
  - Query   signature        : HMAC-SHA256(secret, mensaje)

Mensaje a firmar: {timestamp}{METHOD}{/path}?{sorted_query_sin_signature}

NOTA: Pionex NO soporta TP/SL embebidos en la orden principal.
      Usar place_tp_sl() despues de confirmar el fill.
"""
import requests
import time
import hmac
import hashlib

BASE_URL = "https://api.pionex.com"


# ── Firma ─────────────────────────────────────────────────────────────────────

def sign(message: str, secret: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _sign_request(method: str, path: str, params: dict, secret: str) -> tuple[str, int]:
    ts = int(time.time() * 1000)
    sorted_qs = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    base = f"{ts}{method}{path}"
    message = f"{base}?{sorted_qs}" if sorted_qs else base
    return sign(message, secret), ts


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _headers(api_key: str) -> dict:
    return {"PIONEX-KEY": api_key}


def post(path: str, params: dict, api_key: str, secret: str) -> dict:
    sig, ts = _sign_request("POST", path, params, secret)
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    url = f"{BASE_URL}{path}?{qs}&timestamp={ts}&signature={sig}"
    r = requests.post(url, headers=_headers(api_key), timeout=10)
    return r.json()


def delete(path: str, params: dict, api_key: str, secret: str) -> dict:
    sig, ts = _sign_request("DELETE", path, params, secret)
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    url = f"{BASE_URL}{path}?{qs}&timestamp={ts}&signature={sig}"
    r = requests.delete(url, headers=_headers(api_key), timeout=10)
    return r.json()


def get_auth(path: str, params: dict, api_key: str, secret: str) -> dict:
    sig, ts = _sign_request("GET", path, params, secret)
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    url = f"{BASE_URL}{path}?{qs}&timestamp={ts}&signature={sig}"
    r = requests.get(url, headers=_headers(api_key), timeout=10)
    return r.json()


# ── Apalancamiento ────────────────────────────────────────────────────────────

def set_leverage(symbol: str, leverage: int, api_key: str, secret: str) -> dict:
    return post(
        "/api/v1/perpetual/leverage",
        {"symbol": symbol, "leverage": str(leverage)},
        api_key, secret,
    )


# ── Orden principal ───────────────────────────────────────────────────────────

def place_order(
    symbol: str,
    side: str,       # 'BUY' o 'SELL'
    price: float,
    quantity: float,
    api_key: str,
    secret: str,
) -> dict:
    """Orden LIMIT perpetuo. TP/SL se colocan aparte con place_tp_sl()."""
    return post(
        "/api/v1/perpetual/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "LIMIT",
            "size": str(quantity),
            "price": str(price),
        },
        api_key, secret,
    )


# ── TP y SL post-fill ─────────────────────────────────────────────────────────

def place_tp_sl(
    symbol: str,
    close_side: str,   # cierre: SHORT abierto → 'BUY', LONG abierto → 'SELL'
    tp1_price: float,
    sl_price: float,
    qty_tp1: float,    # 60% de la posicion
    qty_sl: float,     # 100% restante
    api_key: str,
    secret: str,
) -> tuple[dict, dict]:
    """Coloca TP1 (60%) y SL (100%) como ordenes reduce-only tras el fill."""
    tp = post(
        "/api/v1/perpetual/order",
        {
            "symbol": symbol,
            "side": close_side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": str(tp1_price),
            "size": str(qty_tp1),
            "reduceOnly": "true",
        },
        api_key, secret,
    )
    sl = post(
        "/api/v1/perpetual/order",
        {
            "symbol": symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "stopPrice": str(sl_price),
            "size": str(qty_sl),
            "reduceOnly": "true",
        },
        api_key, secret,
    )
    return tp, sl


def place_tp2(
    symbol: str,
    close_side: str,
    tp2_price: float,
    qty_tp2: float,    # 40% de la posicion
    api_key: str,
    secret: str,
) -> dict:
    """Coloca TP2 (40%) cuando el usuario confirma que TP1 fue llenado."""
    return post(
        "/api/v1/perpetual/order",
        {
            "symbol": symbol,
            "side": close_side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": str(tp2_price),
            "size": str(qty_tp2),
            "reduceOnly": "true",
        },
        api_key, secret,
    )


# ── Consultas ─────────────────────────────────────────────────────────────────

def cancel_order(symbol: str, order_id: str, api_key: str, secret: str) -> dict:
    return delete(
        "/api/v1/perpetual/order",
        {"symbol": symbol, "orderId": order_id},
        api_key, secret,
    )


def get_open_orders(symbol: str, api_key: str, secret: str) -> dict:
    return get_auth(
        "/api/v1/perpetual/openOrders",
        {"symbol": symbol},
        api_key, secret,
    )


def get_positions(api_key: str, secret: str, symbol: str = "") -> dict:
    params = {"symbol": symbol} if symbol else {}
    return get_auth("/api/v1/perpetual/positions", params, api_key, secret)
