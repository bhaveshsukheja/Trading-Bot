"""GeckoTerminal: trending pools, OHLCV candles and recent trades."""
from ..http import get_json

BASE = "https://api.geckoterminal.com/api/v2"


def trending_tokens(chain):
    """Base-token addresses of pools trending on GeckoTerminal."""
    data = get_json(f"{BASE}/networks/{chain}/trending_pools", params={"page": 1})
    out = []
    for pool in data.get("data", []):
        token_id = pool["relationships"]["base_token"]["data"]["id"]  # "<chain>_<address>"
        out.append(token_id.split("_", 1)[1])
    return out


def candles(chain, pool, minutes=5, limit=100):
    """Candles oldest-first as (timestamp, open, high, low, close, volume_usd)."""
    data = get_json(
        f"{BASE}/networks/{chain}/pools/{pool}/ohlcv/minute",
        params={"aggregate": minutes, "limit": limit},
    )
    rows = data["data"]["attributes"]["ohlcv_list"]
    return sorted(tuple(r) for r in rows)


def trades(chain, pool):
    """Up to the last 300 trades of a pool, as flat dicts."""
    data = get_json(f"{BASE}/networks/{chain}/pools/{pool}/trades")
    out = []
    for t in data.get("data", []):
        a = t["attributes"]
        buy = a["kind"] == "buy"
        out.append({
            "id": t["id"],
            "ts": a["block_timestamp"],
            "wallet": a["tx_from_address"],
            "kind": a["kind"],
            # Amount of the base (meme) token that changed hands.
            "tokens": float(a["to_token_amount"] if buy else a["from_token_amount"]),
            "usd": float(a["volume_in_usd"] or 0),
        })
    return out
