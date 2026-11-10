"""RugCheck: token safety summary (Solana only)."""
from ..http import get_json


def summary(token):
    """Returns {"score": normalised score, "danger": [risk names]}."""
    data = get_json(f"https://api.rugcheck.xyz/v1/tokens/{token}/report/summary")
    risks = data.get("risks") or []
    return {
        "score": data.get("score_normalised"),
        "danger": [r.get("name", "?") for r in risks if r.get("level") == "danger"],
    }
