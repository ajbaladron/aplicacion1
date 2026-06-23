import requests
import time
import hmac
import hashlib
import json

BASE_URL = "https://api.bitget.com"


def sign(payload: str, secret: str) -> str:
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _build_qs(params: dict, ts: int) -> str:
    parts = [f"{k}={params[k]}" for k in sorted(params.keys())]
    return "&".join(parts) + f"&timestamp={ts}"


def post(path: str, params: dict, api_key: str, secret: str) -> dict:
    ts = int(time.time() * 1000)
    qs = _build_qs(params, ts)
    sig = sign(qs, secret)
    url = f"{BASE_URL}{path}?{qs}&signature={sig}"
    r = requests.post(url, headers={"X-BX-APIKEY": api_key}, timeout=10)
    return r.json()


def delete(path: str, params: dict, api_key: str, secret: str) -> dict:
    ts = int(time.time() * 1000)
    qs = _build_qs(params, ts)
    sig = sign(qs, secret)
    url = f"{BASE_URL}{path}?{qs}&signature={sig}"
    r = requests.delete(url, headers={"X-BX-APIKEY": api_key}, timeout=10)
    return r.json()


def get(path: str, params: dict, api_key: str, secret: str) -> dict:
    ts = int(time.time() * 1000)
    qs = _build_qs(params, ts)
    sig = sign(qs, secret)
    url = f"{BASE_URL}{path}?{qs}&signature={sig}"
    r = requests.get(url, headers={"X-BX-APIKEY": api_key}, timeout=10)
    return r.json()


def set_leverage(symbol: str, side: str, leverage: int, api_key: str, secret: str) -> dict:
    return post(
        "/openApi/swap/v2/trade/leverage",
        {"symbol": symbol, "side": side, "leverage": leverage},
        api_key, secret,
    )


def place_order(
    symbol: str,
    side: str,           # 'BUY' or 'SELL'
    position_side: str,  # 'LONG' or 'SHORT'
    price: float,
    quantity: float,
    tp1: float,
    sl: float,
    api_key: str,
    secret: str,
) -> dict:
    tp_json = json.dumps({
        "type": "TAKE_PROFIT_MARKET",
        "stopPrice": str(tp1),
        "workingType": "MARK_PRICE",
    })
    sl_json = json.dumps({
        "type": "STOP_MARKET",
        "stopPrice": str(sl),
        "workingType": "MARK_PRICE",
    })
    return post(
        "/openApi/swap/v2/trade/order",
        {
            "symbol": symbol,
            "side": side,
            "positionSide": position_side,
            "type": "LIMIT",
            "price": str(price),
            "quantity": str(quantity),
            "takeProfit": tp_json,
            "stopLoss": sl_json,
        },
        api_key, secret,
    )


def cancel_order(symbol: str, order_id: str, api_key: str, secret: str) -> dict:
    return delete(
        "/openApi/swap/v2/trade/order",
        {"symbol": symbol, "orderId": order_id},
        api_key, secret,
    )


def get_open_orders(symbol: str, api_key: str, secret: str) -> dict:
    return get(
        "/openApi/swap/v2/trade/openOrders",
        {"symbol": symbol},
        api_key, secret,
    )


def get_positions(api_key: str, secret: str) -> dict:
    return get(
        "/openApi/swap/v2/user/positions",
        {},
        api_key, secret,
    )
