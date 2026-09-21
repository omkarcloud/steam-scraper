"""Steam Community Market: item search (every game or one, with facet
filters), autocomplete, item details with live prices, full daily price
history, the live order book, and a game's filter facets.

Prices from the new market app's query-action API (price history, order
book) come in the currency of the exit IP's country; `country` picks it
(fetch.market_action pins a residential exit when it differs from the
pod's own). Legacy search results are always priced in USD for anonymous
visitors."""
import re
from datetime import datetime, timedelta, timezone

from steam import fetch, refs
from steam import parsers as P
from steam.shared import paged_result, start_of

SEARCH_PAGE_SIZE = 10          # market/search/render serves fixed 10-row windows
SEARCH_SORTS = {"popular": "popular", "price": "price", "name": "name", "quantity": "quantity"}
HISTORY_PERIODS = {"day": 1, "week": 7, "month": 31, "three_months": 92, "year": 366, "all": None}
# ECurrencyCode -> ISO 4217
CURRENCIES = {1: "USD", 2: "GBP", 3: "EUR", 4: "CHF", 5: "RUB", 6: "PLN", 7: "BRL", 8: "JPY", 9: "NOK", 10: "IDR",
              11: "MYR", 12: "PHP", 13: "SGD", 14: "THB", 15: "VND", 16: "KRW", 17: "TRY", 18: "UAH", 19: "MXN",
              20: "CAD", 21: "AUD", 22: "NZD", 23: "CNY", 24: "INR", 25: "CLP", 26: "PEN", 27: "COP", 28: "ZAR",
              29: "HKD", 30: "TWD", 31: "SAR", 32: "AED", 33: "SEK", 34: "ARS", 35: "ILS", 36: "BYN", 37: "KZT",
              38: "KWD", 39: "QAR", 40: "CRC", 41: "UYU", 42: "BGN", 43: "HRK", 44: "CZK", 45: "DKK", 46: "HUF",
              47: "RON"}


def _game_and_name(item, game):
    app_id = item.get("app_id") or game
    if not app_id:
        raise ValueError("game is required when item is a market hash name (730 = Counter-Strike 2, "
                         "440 = Team Fortress 2, 570 = Dota 2, 753 = Steam trading cards) — or pass the "
                         "item's steamcommunity.com/market/listings link")
    return int(app_id), item["name"]


def _currency(ecurrency):
    return CURRENCIES.get(P.to_int(ecurrency))


def _price_text(text):
    """A localized price string ('$1,234.56', '1.234,56€', '0,03€', '1,--€',
    '¥ 1,234', '12.345₫') -> number. The last separator is the decimal mark
    only when 1-2 digits (or '--') follow it; every other separator groups
    thousands."""
    m = re.search(r"\d[\d.,' \u00a0]*(?:--)?", str(text or ""))
    if not m:
        return None
    raw = m.group(0).rstrip(" \u00a0").replace("--", "00")
    dec = re.search(r"[.,](\d{1,2})$", raw)
    whole = raw[:dec.start()] if dec else raw
    whole = re.sub(r"\D", "", whole)
    if not whole:
        return None
    return float(f"{whole}.{dec.group(1)}") if dec else int(whole)


# ---- search / autocomplete / filters -----------------------------------------------------------------------

def _search_row(r):
    desc = r.get("asset_description") or {}
    app_id = P.to_int(desc.get("appid"))
    name = P.clean(r.get("hash_name"))
    return {
        "name": P.clean(r.get("name")),
        "hash_name": name,
        "link": P.market_link(app_id, name),
        "game": {"id": app_id, "name": P.clean(r.get("app_name")), "icon": P.clean(r.get("app_icon"))},
        "type": P.clean(desc.get("type")),
        "lowest_price": {"amount": P.money(r.get("sell_price"), "USD"), "currency": "USD"} if r.get("sell_price") is not None else None,
        "sale_price": {"amount": P.number_in(str(r.get("sale_price_text") or "").replace(",", "")), "currency": "USD"}
        if P.clean(r.get("sale_price_text")) else None,
        "listings": P.to_int(r.get("sell_listings")),
        "name_color": ("#" + desc["name_color"]) if P.clean(desc.get("name_color")) else None,
        "image": P.econ_image(desc.get("icon_url")),
        "class_id": P.clean(str(desc.get("classid"))) if desc.get("classid") is not None else None,
        "group_name": P.clean(desc.get("market_bucket_group_name")),
        "is_commodity": P.to_bool(desc.get("commodity")),
        "is_tradable": P.to_bool(desc.get("tradable")),
    }


def search(query=None, game=None, filters=None, sort="popular", order="desc", search_descriptions=False, page=1):
    """Market listings summary per item (lowest price, listing count),
    across every game or one, optionally narrowed by facet filters (see
    /steam/market/filters). 10 per page, with the total count; prices in USD."""
    params = {"query": query or "", "start": start_of(page, SEARCH_PAGE_SIZE), "count": SEARCH_PAGE_SIZE,
              "norender": 1, "sort_column": SEARCH_SORTS[sort], "sort_dir": order,
              "search_descriptions": 1 if search_descriptions else 0}
    if game:
        params["appid"] = game
    for f in filters or []:
        category, _, tag = f.partition(":")
        if game and category and tag:
            params.setdefault(f"category_{game}_{category}[]", [])
            params[f"category_{game}_{category}[]"].append(tag if tag.startswith("tag_") else f"tag_{tag}")
    body = fetch.market_json("search/render/", params, label="market search")
    if not isinstance(body, dict) or not body.get("success"):
        raise fetch.SteamUpstreamError("market search: unexpected answer")
    rows = [_search_row(r) for r in body.get("results") or [] if isinstance(r, dict)]
    return paged_result("results", rows, page, SEARCH_PAGE_SIZE, total=P.to_int(body.get("total_count")), query=query)


def autocomplete(query):
    """Item groups matching a partial name across every market game (the
    market search box)."""
    body = fetch.market_json("searchsuggestionsresults", {"q": query}, label="market autocomplete")
    rows = []
    for r in (body or {}).get("results") or []:
        if not isinstance(r, dict):
            continue
        rows.append({"name": P.clean(r.get("market_name")), "group_id": P.clean(r.get("market_hash_name")),
                     "type": P.clean(r.get("market_type")),
                     "game": {"id": P.to_int(r.get("app_id")), "name": P.clean(r.get("app_name"))},
                     "listings": P.to_int(r.get("listing_count")), "image": P.clean(r.get("icon_url"))})
    return {"query": query, "results": rows}


def filters(game):
    """The facet filters of a game's market (exterior, rarity, weapon,
    hero, …) with every tag's id and item count — pass them to
    /steam/market/search as `filters=Exterior:WearCategory0`."""
    body = fetch.market_json(f"appfilters/{game}", label=f"market filters of app {game}")
    facets = (body or {}).get("facets") if isinstance(body, dict) else None
    if not facets:
        raise fetch.SteamNotFound(f"app {game} has no market filters (not a market game)")
    out = []
    for key, f in facets.items():
        if not isinstance(f, dict):
            continue
        tags = [{"id": tag_id, "name": P.clean(t.get("localized_name")), "item_count": P.to_int(t.get("matches"))}
                for tag_id, t in (f.get("tags") or {}).items() if isinstance(t, dict)]
        tags.sort(key=lambda t: -(t["item_count"] or 0))
        out.append({"id": P.clean(f.get("name")) or key.split("_", 1)[-1], "name": P.clean(f.get("localized_name")),
                    "tags": tags})
    return {"game_id": game, "filters": out}


# ---- item -------------------------------------------------------------------------------------------------------

def _book(data, depth=None):
    def ladder(compact, is_buy):
        out = []
        for i in range(0, len(compact or []) - 1, 2):
            out.append({"price": P.money(compact[i], None), "quantity": P.to_int(compact[i + 1])})
        return out[:depth] if depth else out
    currency = _currency(data.get("eCurrency"))
    buys = ladder(data.get("rgCompactBuyOrders"), True)
    sells = ladder(data.get("rgCompactSellOrders"), False)
    return {
        "currency": currency,
        "highest_buy_order": P.money(data.get("amtMaxBuyOrder"), currency),
        "lowest_sell_order": P.money(data.get("amtMinSellOrder"), currency),
        "buy_order_count": P.to_int(data.get("cBuyOrders")),
        "sell_order_count": P.to_int(data.get("cSellOrders")),
        "buy_orders": buys or None,
        "sell_orders": sells or None,
    }


def _load_book(app_id, name, country):
    body = fetch.market_action("orderbook", "Load", app_id, name, country=country,
                               not_found=f"market item {name}")
    data = (body or {}).get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not body.get("success"):
        raise fetch.SteamNotFound(f"market item {name!r} not found in app {app_id}")
    return data


def order_book(item, game=None, country=None, depth=50):
    """The live order book: highest buy / lowest sell, order counts and the
    price ladders (price + quantity per level), priced for `country`."""
    app_id, name = _game_and_name(item, game)
    book = _book(_load_book(app_id, name, country), depth)
    return {"game_id": app_id, "hash_name": name, "link": P.market_link(app_id, name), **book}


def price_history(item, game=None, country=None, period="month"):
    """The item's sale history: median price and units sold per day (per
    hour for the most recent month), priced for `country`."""
    app_id, name = _game_and_name(item, game)
    data = fetch.market_action("actions", "QueryPriceHistory", app_id, name, country=country,
                               not_found=f"market item {name}")
    points = (data or {}).get("prices") if isinstance(data, dict) else None
    if not points:
        raise fetch.SteamNotFound(f"no sales history for market item {name!r} in app {app_id}")
    currency = _currency(data.get("ecurrency"))
    days = HISTORY_PERIODS[period]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp() if days else None
    rows = []
    for p in points:
        if not isinstance(p, dict):
            continue
        ts = P.to_int(p.get("time"))
        if cutoff and ts and ts < cutoff:
            continue
        rows.append({"time": P.iso_datetime(ts), "median_price": P.to_float(p.get("price_median"), 2),
                     "units_sold": P.to_int(p.get("purchases"))})
    total_units = sum(r["units_sold"] or 0 for r in rows)
    prices = [r["median_price"] for r in rows if r["median_price"] is not None]
    return {"game_id": app_id, "hash_name": name, "link": P.market_link(app_id, name), "currency": currency,
            "period": period, "summary": {"points": len(rows), "units_sold": total_units,
                                          "lowest_median_price": min(prices) if prices else None,
                                          "highest_median_price": max(prices) if prices else None,
                                          "first_sale_at": P.iso_datetime(P.to_int(points[0].get("time")))},
            "history": rows}


def item(item, game=None, country=None):
    """A market item: description, type, tags, image, trade flags, the
    live order-book summary and the last-24-hours median price and volume."""
    app_id, name = _game_and_name(item, game)
    desc_raw = fetch.market_action("actions", "QueryDescription", app_id, name, country=None,
                                   not_found=f"market item {name}")
    if not isinstance(desc_raw, dict) or not desc_raw.get("classid"):
        raise fetch.SteamNotFound(f"market item {name!r} not found in app {app_id}")
    description = P.market_description(desc_raw) or {}
    book = None
    try:
        book = _book(_load_book(app_id, name, country), depth=5)
    except fetch.SteamNotFound:
        book = None
    overview = None
    try:
        ecur = next((k for k, v in CURRENCIES.items() if v == (book or {}).get("currency")), 1)
        raw = fetch.market_json("priceoverview/", {"appid": app_id, "currency": ecur, "market_hash_name": name},
                                label="market priceoverview")
        if isinstance(raw, dict) and raw.get("success"):
            overview = {"lowest_price": _price_text(raw.get("lowest_price")),
                        "median_price": _price_text(raw.get("median_price")),
                        "volume_24h": P.to_int(raw.get("volume")),
                        "currency": CURRENCIES.get(ecur)}
    except Exception:
        overview = None
    return {
        "game_id": app_id,
        "hash_name": name,
        "link": P.market_link(app_id, name),
        **{k: v for k, v in description.items() if k != "hash_name"},
        "prices": {
            "currency": (book or {}).get("currency") or (overview or {}).get("currency"),
            "lowest_sell_order": (book or {}).get("lowest_sell_order"),
            "highest_buy_order": (book or {}).get("highest_buy_order"),
            "sell_order_count": (book or {}).get("sell_order_count"),
            "buy_order_count": (book or {}).get("buy_order_count"),
            "median_price_24h": (overview or {}).get("median_price"),
            "volume_24h": (overview or {}).get("volume_24h"),
        },
    }
