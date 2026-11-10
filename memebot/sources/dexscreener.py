"""DexScreener: token discovery and live pair data."""
from ..http import get_json

BASE = "https://api.dexscreener.com"


def discover(chain):
    """Token addresses currently boosted or newly profiled on DexScreener.

    Returns {address: boost_amount}. Boosts are paid promotion, so this is a
    measure of attention, not of quality.
    """
    found = {}
    for path in ("/token-boosts/top/v1", "/token-boosts/latest/v1", "/token-profiles/latest/v1"):
        for item in get_json(BASE + path) or []:
            if item.get("chainId") == chain and item.get("tokenAddress"):
                addr = item["tokenAddress"]
                found[addr] = max(found.get(addr, 0), item.get("totalAmount") or 0)
    return found


def pairs_for_tokens(chain, addresses):
    """Most liquid pair for each token. Returns {token_address: pair_dict}."""
    best = {}
    addresses = list(addresses)
    for i in range(0, len(addresses), 30):  # endpoint accepts up to 30 addresses
        chunk = addresses[i:i + 30]
        for pair in get_json(f"{BASE}/tokens/v1/{chain}/{','.join(chunk)}") or []:
            addr = pair.get("baseToken", {}).get("address")
            liq = (pair.get("liquidity") or {}).get("usd") or 0
            if addr and liq > ((best.get(addr, {}).get("liquidity") or {}).get("usd") or 0):
                best[addr] = pair
    return best
