"""Steam charts: most played (daily peak), live concurrent players, weekly
top sellers per country, and Valve's monthly top-release lists
(ISteamChartsService / IStoreTopSellersService), every row hydrated into a
full game card."""
from datetime import datetime, timezone

from steam import fetch
from steam import parsers as P
from steam.shared import CARD_REQUEST, app_cards, context, currency_for, paged_result, tag_names


def _merge(ranks, cards, extra):
    by_id = {c["id"]: c for c in cards}
    out = []
    for r in ranks:
        card = by_id.get(r.get("appid"))
        if card is None:
            continue
        out.append({"rank": P.to_int(r.get("rank")), **extra(r), "game": card})
    return out


def most_played(country=None, language=None, limit=100):
    """The 100 games with the most players at their daily peak (Steam's
    "Most Played" chart), with last week's rank."""
    body = fetch.webapi("ISteamChartsService", "GetMostPlayedGames", 1)
    ranks = [r for r in (body or {}).get("ranks") or [] if isinstance(r, dict)][:limit]
    cards = app_cards([r.get("appid") for r in ranks], country, language)
    return {"updated_on": P.iso_date((body or {}).get("rollup_date")),
            "results": _merge(ranks, cards, lambda r: {"last_week_rank": P.to_int(r.get("last_week_rank")) or None,
                                                       "daily_peak_players": P.to_int(r.get("peak_in_game"))})}


def concurrent_players(country=None, language=None, limit=100):
    """The 100 games with the most players in-game right now, with today's peak."""
    body = fetch.webapi("ISteamChartsService", "GetGamesByConcurrentPlayers", 1)
    ranks = [r for r in (body or {}).get("ranks") or [] if isinstance(r, dict)][:limit]
    cards = app_cards([r.get("appid") for r in ranks], country, language)
    return {"updated_at": P.iso_datetime((body or {}).get("last_update")),
            "results": _merge(ranks, cards, lambda r: {"current_players": P.to_int(r.get("concurrent_in_game")),
                                                       "peak_players": P.to_int(r.get("peak_in_game"))})}


def top_sellers(country=None, week=None, page=1, limit=25, language=None):
    """The weekly top sellers of one country's store (by revenue), with
    last week's rank and weeks on the chart. `week` = any date of the
    wanted week (default: the latest published week)."""
    country = (country or "US").upper()
    request = {"country_code": country, "context": context(country, language), "data_request": CARD_REQUEST,
               "page_start": (page - 1) * limit, "page_count": limit}
    if week:
        request["start_date"] = int(datetime.strptime(week, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    body = fetch.webapi("IStoreTopSellersService", "GetWeeklyTopSellers", 1, input_json=request)
    ranks = [r for r in (body or {}).get("ranks") or [] if isinstance(r, dict)]
    if not ranks and page == 1:
        raise fetch.SteamNotFound(f"Steam publishes no weekly top-seller chart for {country}"
                                  + (f" for the week of {week}" if week else ""))
    currency = currency_for(country)
    names = tag_names(language)
    rows = []
    for r in ranks:
        card = P.store_item(r.get("item"), currency, names)
        if card:
            rows.append({"rank": P.to_int(r.get("rank")), "last_week_rank": P.to_int(r.get("last_week_rank")) or None,
                         "weeks_on_chart": P.to_int(r.get("consecutive_weeks")), "game": card})
    next_start = P.to_int((body or {}).get("next_page_start"))
    return paged_result("results", rows, page, limit, has_more=bool(rows) and next_start is not None and len(rows) >= limit,
                        country=country, week_start=P.iso_date((body or {}).get("start_date")))


_MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"), 1)}


def _month_of(page):
    """'top_january_2025' -> '2025-01' (start_of_month is a Pacific-time
    stamp, so its UTC date can land in the previous/next month)."""
    parts = str(page.get("url_path") or "").lower().split("_")
    if len(parts) >= 3 and parts[-2] in _MONTHS and parts[-1].isdigit():
        return f"{parts[-1]}-{_MONTHS[parts[-2]]:02d}"
    start = P.iso_date(page.get("start_of_month"))
    return start[:7] if start else None


def top_releases(month=None, country=None, language=None):
    """Valve's "Top Releases" lists: the best-selling new games of each
    month. `month` (YYYY-MM) picks one list; by default the latest. The
    months Valve has published come back in `available_months`."""
    body = fetch.webapi("ISteamChartsService", "GetTopReleasesPages", 1)
    pages = [p for p in (body or {}).get("pages") or [] if isinstance(p, dict)]
    months = []
    for p in pages:
        months.append({"month": _month_of(p), "name": P.clean(p.get("name")),
                       "link": f"https://store.steampowered.com/charts/{p.get('url_path')}" if p.get("url_path") else None,
                       "game_count": len(p.get("item_ids") or []), "_ids": [i.get("appid") for i in p.get("item_ids") or []
                                                                           if isinstance(i, dict)]})
    if not months:
        raise fetch.SteamNotFound("no top-release lists published")
    chosen = months[0] if not month else next((m for m in months if m["month"] == month), None)
    if chosen is None:
        raise fetch.SteamNotFound(f"no top-release list for {month}; available: "
                                  + ", ".join(m["month"] for m in months if m["month"]))
    cards = app_cards(chosen["_ids"], country, language)
    return {"month": chosen["month"], "name": chosen["name"], "link": chosen["link"],
            "results": P.numbered(cards),
            "available_months": [{k: v for k, v in m.items() if k != "_ids"} for m in months]}
