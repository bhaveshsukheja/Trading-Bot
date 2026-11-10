"""X (Twitter) research via the official API v2 recent-search endpoint.

UNTESTED: written without an API token, so the request has never been run
against the live API. Check the query and fields against the current X API
docs, and check that your access tier includes recent search.
"""
import os

from ..http import get_json

SEARCH_URL = "https://api.x.com/2/tweets/search/recent"

BULLISH = {"moon", "bullish", "pump", "pumping", "gem", "send", "sending", "ath", "buy",
           "bought", "long", "runner", "breakout", "accumulate", "undervalued", "lfg"}
BEARISH = {"rug", "rugged", "scam", "dump", "dumping", "honeypot", "bearish", "sell",
           "sold", "dead", "avoid", "exit", "fraud", "drained", "bundled"}


def token():
    return os.environ.get("X_BEARER_TOKEN", "").strip()


def score_text(texts):
    """Crude keyword sentiment in [-1, 1]. Cannot detect sarcasm or paid shills."""
    bull = bear = 0
    for text in texts:
        words = {w.strip("#$.,!?:;()\"'").lower() for w in text.split()}
        bull += len(words & BULLISH)
        bear += len(words & BEARISH)
    return (bull - bear) / (bull + bear) if bull + bear else 0.0


def research(address, symbol):
    """Recent posts mentioning a token.

    Returns {"mentions", "authors", "engagement", "sentiment"} or None when no
    token is configured.
    """
    if not token():
        return None
    query = f'("{address}" OR ("{symbol}" (solana OR memecoin OR pumpfun))) -is:retweet'
    data = get_json(
        SEARCH_URL,
        params={
            "query": query,
            "max_results": 100,
            "tweet.fields": "public_metrics,author_id",
        },
        headers={"Authorization": f"Bearer {token()}"},
        retries=0,
    )
    tweets = data.get("data") or []
    engagement = 0
    for t in tweets:
        m = t.get("public_metrics") or {}
        engagement += m.get("like_count", 0) + m.get("retweet_count", 0) + m.get("reply_count", 0)
    return {
        "mentions": len(tweets),
        "authors": len({t.get("author_id") for t in tweets}),
        "engagement": engagement,
        "sentiment": score_text(t.get("text", "") for t in tweets),
    }
