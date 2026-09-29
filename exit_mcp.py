#!/usr/bin/env python3
"""Exit as an MCP server -- ask an assistant "can I get out of $2M of BONK?".

This file is NOT named mcp.py and does not live in an mcp/ directory on purpose:
either would shadow the installed `mcp` SDK package on sys.path.

It is a thin client over the public API (web/app.py), so the answer an assistant
gives is the same number the website serves -- one source of truth, and it proves
the deployed API works. No CoinMarketCap key is needed.

Point it somewhere else with EXIT_API:
    EXIT_API=http://127.0.0.1:5055          # your local Flask app, works offline
    EXIT_API=https://exit-henna.vercel.app  # the deployed site (default)

Run by hand (it speaks MCP over stdin/stdout, so it looks like it hangs -- that is
correct, press Ctrl-C):
    python exit_mcp.py

Register with Claude Code:
    claude mcp add exit -- /abs/path/.venv/bin/python /abs/path/exit_mcp.py

MCP spec:  https://modelcontextprotocol.io/
Python SDK: https://github.com/modelcontextprotocol/python-sdk
"""
import os

import requests
from mcp.server.mcpserver import MCPServer

API = os.getenv("EXIT_API", "https://exit-henna.vercel.app").rstrip("/")
TIMEOUT = 20

server = MCPServer(
    name="exit",
    instructions=(
        "Exit rates how much of a crypto token you could actually sell, calibrated "
        "against real order books on Binance, OKX, Coinbase and Kraken. Use can_i_exit "
        "for 'can I get out of $X of TOKEN', token_rating for a token's grade and safe "
        "size, and worst_exits to find the least liquid tokens. Every figure is a model "
        "estimate with a wide band: always report the band and the caveat, never present "
        "a single number as exact. Exit measures the cost of leaving; it does not predict "
        "crashes. Every cost already assumes the sale is routed across all four exchanges "
        "at once, so never suggest spreading it across venues as a way to pay less -- that "
        "saving is already priced in. Spreading the sale over TIME is the only mitigation "
        "the model supports."
    ),
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _get(path, **params):
    """One place for every HTTP call, so errors read the same in every tool."""
    try:
        r = requests.get(f"{API}{path}", params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        return {"error": f"could not reach the Exit API at {API}: {e}"}
    if r.status_code == 409:                      # symbols collide across tokens
        j = r.json()
        return {"error": j.get("error"), "candidates": j.get("candidates"),
                "hint": "call again with the slug of the one you mean"}
    if r.status_code == 404:
        return {"error": r.json().get("error", "not rated"),
                "hint": "Exit rates the 500 largest tokens on CoinMarketCap"}
    if r.status_code == 429:
        return {"error": "rate limited by the Exit API; wait a minute"}
    if not r.ok:
        return {"error": f"Exit API returned HTTP {r.status_code}"}
    return r.json()


def _pct(bps):
    """Costs are quoted in bps on the site; humans read percent."""
    return None if bps is None else round(bps / 100, 3)


def _money(v):
    return None if v is None else round(v, 2)


def _measured(obs):
    """The order-book measurements behind the estimate, so an assistant can cite
    evidence rather than only the model. None when no exchange we snapshot lists
    the token."""
    if not obs:
        return None
    return {
        "day": obs["day"],
        "exchanges_walked": obs["venues"],
        "largest_sale_the_books_filled_usd": obs.get("largest_absorbed_usd"),
        "smallest_sale_the_books_refused_usd": obs.get("smallest_unabsorbable_usd"),
        "sales": [{"size_usd": s["size_usd"],
                   "cost_percent": _pct(s["bps"]),
                   "status": s["status"]} for s in obs.get("sales", [])],
    }


def _safe_size(r):
    """Never print an extrapolated max position -- the site's rule, kept here."""
    if r.get("max_position_usd") is None:
        return {"max_position_usd": None, "note": r.get("max_position_note")}
    return {"max_position_usd": _money(r["max_position_usd"]),
            "band_50pct_usd": [_money(x) for x in (r.get("max_position_band_50pct") or [])] or None}


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

@server.tool(
    description="Answer 'can I get out of $X of TOKEN?'. Returns what selling that "
                "size immediately would cost, its 50% band, and a plain verdict."
)
def can_i_exit(symbol: str, size_usd: float) -> dict:
    """symbol: a ticker like BONK, or a slug like bonk1 when tickers collide.
    size_usd: the position you want to sell, in US dollars."""
    if size_usd <= 0:
        return {"error": "size_usd must be a positive number of US dollars"}

    r = _get(f"/api/v1/impact/{symbol}", size=size_usd)
    if "error" in r:
        return r

    e = r.get("exit")
    if not e:
        return {"symbol": r["symbol"], "grade": r["grade"],
                "error": "no exit cost: this token has no volume or no measurable volatility"}

    bps, band = e["bps"], e.get("band_bps_50pct")
    if bps < 50:
        verdict = "cheap to exit at this size"
    elif bps < 200:
        verdict = "inside the 2% tolerance Exit grades on"
    elif bps < 500:
        verdict = "expensive: this size moves the price against you"
    else:
        verdict = "very expensive: you would give up a large part of the position"

    caveats = []

    # A MEASUREMENT beats the model. If the real books refused a sale this size,
    # the estimate above is not just uncertain, it is known to be wrong -- say so
    # first and overrule the verdict rather than burying it in a caveat.
    if e.get("measured_unabsorbable"):
        verdict = ("NO -- not at this size. The model's estimate is contradicted by the "
                   "order books we actually measured, which could not fill this sale at all.")
        caveats.insert(0, e["measured_note"])
    if e.get("beyond_model"):
        caveats.append("this sale is larger than a full day of the token's volume, so the "
                       "figure is extrapolated well past anything measured")
    if e.get("beyond_calibration"):
        caveats.append("this sale is above $10M, the largest sale Exit has measured on real "
                       "order books, so the curve is extrapolating")
    caveats.append("a model estimate, typically within a factor of ~1.8 of the real cost, and "
                   "it tends to be too optimistic for thin tokens")

    return {
        "token": {"symbol": r["symbol"], "name": r["name"], "slug": r["slug"], "grade": r["grade"]},
        "selling_usd": size_usd,
        "cost": {
            "bps": round(bps, 1),
            "percent": _pct(bps),
            "usd": _money(e["cost_usd"]),
            "band_50pct_percent": [_pct(b) for b in band] if band else None,
        },
        "share_of_daily_volume": round(e["participation"], 4),
        "verdict": verdict,
        "measured_today": _measured(r.get("observed")),
        "already_assumed": "one sale routed across Binance, OKX, Coinbase and Kraken "
                           "simultaneously -- splitting across those venues is already "
                           "priced in and saves nothing further",
        "only_mitigation": "spreading the sale over hours or days costs less than this "
                           "figure, which is for selling everything immediately",
        "caveats": caveats,
        "safe_size": _safe_size(r),
        "as_of": r["as_of"],
        "methodology": r["methodology"],
    }


@server.tool(
    description="A token's Exit rating: grade, the largest position it can sell at "
                "under 2%, what a $100k sale costs, and the model inputs."
)
def token_rating(symbol: str) -> dict:
    """symbol: a ticker like BTC, or a slug like bitcoin."""
    r = _get(f"/api/v1/impact/{symbol}")
    if "error" in r:
        return r
    return {
        "token": {"symbol": r["symbol"], "name": r["name"], "slug": r["slug"]},
        "grade": r["grade"],
        "grade_scale": "AAA is $10M out at under 2%; D is under $10k; NR means not rated",
        "safe_size": _safe_size(r),
        "cost_of_100k_sale": {"bps": round(r["exit_100k_bps"], 1) if r["exit_100k_bps"] else None,
                              "percent": _pct(r["exit_100k_bps"])},
        "tolerance_bps": r["tolerance_bps"],
        "inputs": r["inputs"],
        "as_of": r["as_of"],
        "methodology": r["methodology"],
    }


@server.tool(
    description="The least liquid rated tokens: biggest market caps with the smallest "
                "positions you could actually sell. Good for finding paper valuations."
)
def worst_exits(limit: int = 10, min_market_cap_usd: float = 1_000_000_000) -> dict:
    """limit: how many to return (1-50). min_market_cap_usd: ignore small caps."""
    limit = max(1, min(int(limit), 50))
    r = _get("/api/v1/ratings")
    if "error" in r:
        return r

    rows = []
    for t in r["ratings"]:
        cap = (t.get("inputs") or {}).get("market_cap")
        mp = t.get("max_position_usd")
        if cap is None or mp is None or cap < min_market_cap_usd:
            continue            # max_position_usd is None when above the calibrated range
        rows.append({
            "symbol": t["symbol"], "name": t["name"], "grade": t["grade"],
            "market_cap_usd": _money(cap),
            "max_position_usd": _money(mp),
            "cap_to_exit_ratio": round(cap / mp) if mp else None,
            "cost_of_100k_percent": _pct(t.get("exit_100k_bps")),
        })
    rows.sort(key=lambda x: -(x["cap_to_exit_ratio"] or 0))

    return {
        "as_of": r["as_of"],
        "explanation": "cap_to_exit_ratio is market cap divided by the largest position that "
                       "can leave at under 2% -- higher means more of the valuation is on paper",
        "note": "tokens whose safe size is above $10M are left out: that is beyond what Exit "
                "has measured, so no number is published for them",
        "tokens": rows[:limit],
    }


@server.tool(
    description="How Exit computes its numbers and how wrong it is -- read this before "
                "presenting any Exit figure as fact."
)
def methodology() -> dict:
    return {
        "curve": "cost_bps = 10000 * Y * sigma * (Q / V) ^ delta",
        "terms": {"Q": "sale size in USD", "V": "yesterday's 24h volume (CoinMarketCap)",
                  "sigma": "30-day daily volatility", "Y and delta": "fitted to real order books"},
        "origin": "the square-root law of market impact (Almgren, Thum, Hauptmann & Li, 2005). "
                  "That law is for orders worked over a day; Exit measures selling immediately, "
                  "so delta is fitted rather than assumed.",
        "ground_truth": "every day the full public order books from Binance, OKX, Coinbase and "
                        "Kraken are merged and walked at $10k, $100k, $1M and $10M",
        "accuracy": "scored only on tokens it never trained on (5-fold cross-validation grouped "
                    "by token). Typical error is a factor of about 1.8.",
        "known_weakness": "'false comfort': of the sales no order book could absorb at all, the "
                          "shipped model still priced most of them under 10%. It is too "
                          "optimistic for thin tokens.",
        "not_a_crash_predictor": "run backwards through LUNA, FTT and CRV it gave no warning. "
                                 "Exit measures the cost of leaving, not the chance of collapse.",
        "read_more": f"{API}/methodology",
    }


if __name__ == "__main__":
    server.run(transport="stdio")
