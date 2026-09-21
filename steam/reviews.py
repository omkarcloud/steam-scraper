"""Steam user reviews: the review list (cursor paging, every store filter),
the score summary and the review-history histogram — store.steampowered.com
/appreviews and /appreviewhistogram JSON."""
from steam import fetch
from steam import parsers as P

# public -> upstream `filter`
REVIEW_SORTS = {"recent": "recent", "updated": "updated", "helpful": "all"}
REVIEW_TYPES = ["all", "positive", "negative"]
PURCHASE_TYPES = {"all": "all", "steam": "steam", "other": "non_steam_purchase"}


def _get(game, params):
    return fetch.store_json(f"appreviews/{game}", {"json": 1, **params}, label=f"reviews of app {game}")


def reviews(game, sort="recent", review_type="all", purchase_type="all", language="all", day_range=None,
            playtime_min=None, playtime_max=None, include_off_topic=False, cursor=None, limit=20):
    """One page of user reviews. `cursor` is the `next_cursor` of the page
    before; the score summary comes with the first page only."""
    if cursor:
        cursor = cursor.replace(" ", "+")   # base64 cursor: an unencoded '+' arrives as a space
    params = {
        "filter": REVIEW_SORTS[sort], "review_type": review_type,
        "purchase_type": PURCHASE_TYPES[purchase_type], "language": language or "all",
        "num_per_page": limit, "cursor": cursor or "*",
        "filter_offtopic_activity": 0 if include_off_topic else 1,
    }
    if sort == "helpful" and day_range:
        params["day_range"] = day_range
    if playtime_min:
        params["playtime_filter_min"] = playtime_min
    if playtime_max:
        params["playtime_filter_max"] = playtime_max
    body = _get(game, params)
    if not isinstance(body, dict) or body.get("success") != 1:
        raise fetch.SteamUpstreamError(f"reviews of app {game}: unexpected answer")
    rows = [r for r in (P.review(x, game) for x in body.get("reviews") or []) if r]
    summary = P.review_query_summary(body.get("query_summary")) if not cursor else None
    if summary is not None and summary["total"] == 0 and not rows and not cursor:
        _require_app(game)
    next_cursor = body.get("cursor")
    has_more = bool(rows) and len(rows) >= limit and next_cursor and next_cursor != (cursor or "*")
    return {"game_id": game, "summary": summary, "reviews": rows,
            "next_cursor": next_cursor if has_more else None}


def _require_app(game):
    """appreviews answers an unknown app with an empty 200; confirm the app exists."""
    body = fetch.store_json("api/appdetails", {"appids": game, "filters": "basic"})
    entry = (body or {}).get(str(game)) or {}
    if not entry.get("success"):
        raise fetch.SteamNotFound(f"app {game} not found on the Steam store")


def summary(game, language=None):
    """Review score, label and counts: all languages, the chosen language,
    Steam purchasers only and the last 30 days."""
    def one(args):
        params = {"filter": "all", "language": args.get("language", "all"), "num_per_page": 0, "cursor": "*",
                  "purchase_type": args.get("purchase_type", "all")}
        if args.get("day_range"):
            params["filter"] = "all"
            params["day_range"] = args["day_range"]
        body = _get(game, params)
        return P.review_query_summary((body or {}).get("query_summary"))
    jobs = [{}, {"language": language or "english"}, {"purchase_type": "steam"}]
    overall, in_language, steam_only = fetch.fanout(one, jobs, workers=3)
    if not overall or overall["total"] == 0:
        _require_app(game)
    recent = None
    try:
        hist = fetch.store_json(f"appreviewhistogram/{game}", {"l": "english"})
        rows = ((hist or {}).get("results") or {}).get("recent") or []
        up = sum(P.to_int(r.get("recommendations_up")) or 0 for r in rows if isinstance(r, dict))
        down = sum(P.to_int(r.get("recommendations_down")) or 0 for r in rows if isinstance(r, dict))
        if up or down:
            recent = {"total": up + down, "positive": up, "negative": down,
                      "percent_positive": round(up * 100 / (up + down)), "days": len(rows)}
    except Exception:
        recent = None
    return {"game_id": game, "overall": overall, "in_language": in_language, "steam_purchasers": steam_only,
            "recent": recent}


def _periods(rows):
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        up = P.to_int(r.get("recommendations_up")) or 0
        down = P.to_int(r.get("recommendations_down")) or 0
        out.append({"date": P.iso_date(r.get("date")), "positive": up, "negative": down, "total": up + down,
                    "percent_positive": round(up * 100 / (up + down)) if up + down else None})
    return out or None


def histogram(game, language=None):
    """Positive / negative review counts over the game's lifetime (per
    month or week, as Steam rolls them up) and per day for the last 30 days."""
    body = fetch.store_json(f"appreviewhistogram/{game}", {"l": language or "english"},
                            label=f"review histogram of app {game}")
    results = (body or {}).get("results") if isinstance(body, dict) else None
    if not isinstance(results, dict) or not (results.get("rollups") or results.get("recent")):
        _require_app(game)
        raise fetch.SteamNotFound(f"app {game} has no review history")
    return {
        "game_id": game,
        "start_date": P.iso_date(results.get("start_date")),
        "end_date": P.iso_date(results.get("end_date")),
        "period": P.clean(results.get("rollup_type")),
        "history": _periods(results.get("rollups")),
        "last_30_days": _periods(results.get("recent")),
    }
