"""Steam store discovery: full-text search with every store filter,
autocomplete, filtered browse (IStoreQueryService), the store front's
featured lists, tag / category reference lists, and package / bundle
details."""
from steam import fetch, refs
from steam import parsers as P
from steam.shared import (CARD_REQUEST, category_names, context, currency_for, get_items, key_cards,
                          paged_result, start_of, tag_names)

SEARCH_PAGE_SIZE = 25        # store search/results serves fixed 25-row windows
SEARCH_SORTS = {"relevance": "_ASC", "release_date": "Released_DESC", "name": "Name_ASC",
                "lowest_price": "Price_ASC", "highest_price": "Price_DESC", "user_reviews": "Reviews_DESC"}
SEARCH_LISTS = {"top_sellers": "topsellers", "global_top_sellers": "globaltopsellers",
                "popular_new": "popularnew", "coming_soon": "comingsoon"}
SEARCH_TYPES = {"game": "998", "dlc": "21", "software": "994", "demo": "10", "soundtrack": "990"}
SEARCH_OS = {"windows": "win", "mac": "mac", "linux": "linux"}
DECK_FILTER = {"verified": "3", "playable": "2"}

BROWSE_SORTS = {"relevance": 11, "trending": 10, "top_sellers": 12, "most_played": 13,
                "new_and_trending": 20, "most_reviewed": 30, "name": 1}
BROWSE_TYPES = {"game": "include_games", "dlc": "include_dlc", "software": "include_software",
                "demo": "include_demos", "soundtrack": "include_music", "video": "include_video",
                "hardware": "include_hardware", "mod": "include_mods", "bundle": "include_bundles",
                "package": "include_packages"}
CATEGORY_GROUPS = {0: "app_type", 1: "players", 2: "features", 3: "controller", 4: "accessibility"}


# ---- search ---------------------------------------------------------------------------------------

def search(query=None, page=1, sort="relevance", section=None, types=None, tags=None, max_price=None,
           discounted_only=False, hide_free=False, os=None, steam_deck=None, supported_language=None,
           country=None, language=None):
    """The store's search page: free text plus every filter the page
    offers (price cap, discounts, tags, type, OS, Deck status, supported
    language, top-seller / coming-soon lists). 25 results per page, with
    the total count."""
    params = {"start": start_of(page, SEARCH_PAGE_SIZE), "count": SEARCH_PAGE_SIZE, "infinite": 1, "json": 1,
              "cc": (country or "US").upper(), "l": language or "english"}
    if query:
        params["term"] = query
    if sort and sort != "relevance":
        params["sort_by"] = SEARCH_SORTS[sort]
    if section:
        params["filter"] = SEARCH_LISTS[section]
    if types:
        params["category1"] = ",".join(SEARCH_TYPES[t] for t in types)
    if tags:
        params["tags"] = ",".join(str(t) for t in tags)
    if max_price is not None:
        params["maxprice"] = "free" if max_price == 0 else str(int(max_price) if float(max_price).is_integer() else max_price)
    if discounted_only:
        params["specials"] = 1
    if hide_free:
        params["hidef2p"] = 1
    if os:
        params["os"] = ",".join(SEARCH_OS[o] for o in os)
    if steam_deck:
        params["deck_compatibility"] = DECK_FILTER[steam_deck]
    if supported_language:
        params["supportedlang"] = supported_language
    body = fetch.store_json("search/results/", params, label="store search")
    if not isinstance(body, dict) or body.get("success") != 1:
        raise fetch.SteamUpstreamError("store search: unexpected answer")
    keys = P.item_keys_in(body.get("results_html"))
    results = key_cards(keys, country, language)
    total = P.to_int(body.get("total_count"))
    return paged_result("results", results, page, SEARCH_PAGE_SIZE, total=total, query=query)


def autocomplete(query, limit=10, country=None, language=None):
    """Instant matches as you type (the store search box), full cards."""
    body = fetch.webapi("IStoreQueryService", "SearchSuggestions", 1, input_json={
        "search_term": query, "max_results": limit, "context": context(country, language),
        "data_request": CARD_REQUEST, "filters": {"type_filters": {"include_apps": True, "include_bundles": True,
                                                                   "include_packages": True}}})
    currency = currency_for(country)
    names = tag_names(language)
    rows = [P.store_item(r, currency, names) for r in (body or {}).get("store_items") or []]
    return {"query": query, "results": [r for r in rows if r]}


# ---- browse -------------------------------------------------------------------------------------------

def browse(sort="relevance", types=None, tags=None, free_only=False, hide_free=False, min_discount=None,
           coming_soon_only=False, top_sellers_only=False, page=1, limit=25, country=None, language=None):
    """Filtered catalogue browse (IStoreQueryService/Query): tags, item
    types, free / paid / discounted / coming-soon / top-100-sellers only,
    sorted by relevance, trending, top sellers, most played, new and
    trending, most reviewed or name. Deep paging with an exact total.
    (Upstream has no price cap here — /steam/search takes max_price.)"""
    type_filters = {BROWSE_TYPES[t]: True for t in (types or ["game"])}
    filters = {"type_filters": type_filters}
    if tags:
        filters["tagids"] = list(tags)
    price = {}
    if hide_free:
        price["exclude_free_items"] = True
    if free_only:
        price["only_free_items"] = True
    if min_discount:
        price["min_discount_percent"] = min_discount
    if price:
        filters["price_filters"] = price
    if coming_soon_only:
        filters["coming_soon_only"] = True
    else:
        filters["released_only"] = True
    if top_sellers_only:
        filters["global_top_n_sellers"] = 100
    body = fetch.webapi("IStoreQueryService", "Query", 1, input_json={
        "query": {"start": start_of(page, limit), "count": limit, "sort": BROWSE_SORTS[sort], "filters": filters},
        "context": context(country, language), "data_request": CARD_REQUEST})
    currency = currency_for(country)
    names = tag_names(language)
    rows = [P.store_item(r, currency, names) for r in (body or {}).get("store_items") or []]
    total = P.to_int(((body or {}).get("metadata") or {}).get("total_matching_records"))
    return paged_result("results", [r for r in rows if r], page, limit, total=total)


# ---- featured / reference ----------------------------------------------------------------------------------

def _featured_item(item, currency_hint=None):
    if not isinstance(item, dict) or not item.get("id"):
        return None
    currency = P.clean(item.get("currency")) or currency_hint
    original = item.get("original_price")
    final = item.get("final_price")
    price = P.price_block(final, original if original is not None else final, item.get("discount_percent"),
                          currency, item.get("discount_expiration")) if final is not None else None
    kind = {0: "app", 1: "package", 2: "bundle"}.get(item.get("type"), "app")
    link = {"package": refs.package_link, "bundle": refs.bundle_link}.get(kind, refs.app_link)(item["id"])
    return {
        "id": item["id"],
        "type": kind,
        "name": P.clean(item.get("name")),
        "link": link,
        "price": price,
        "platforms": {"windows": bool(item.get("windows_available")), "mac": bool(item.get("mac_available")),
                      "linux": bool(item.get("linux_available"))},
        "controller_support": P.clean(item.get("controller_support")),
        "images": {"header": P.clean(item.get("header_image")), "capsule": P.clean(item.get("large_capsule_image")),
                   "capsule_small": P.clean(item.get("small_capsule_image"))},
    }


def _spotlight(item):
    if not isinstance(item, dict):
        return None
    return {"name": P.clean(item.get("name")), "link": P.strip_snr(item.get("url")),
            "description": P.clean((item.get("body") or "").replace("%1$s", "").strip()) if item.get("body") else None,
            "image": P.clean(item.get("header_image"))}


def featured(country=None, language=None):
    """The store front: spotlights, daily deal, specials, top sellers, new
    releases and coming soon, priced for `country`."""
    body = fetch.store_json("api/featuredcategories", {"cc": (country or "US").upper(), "l": language or "english"})
    if not isinstance(body, dict):
        raise fetch.SteamUpstreamError("featured: unexpected answer")
    spotlights, daily = [], []
    sections = {}
    for key, block in body.items():
        if not isinstance(block, dict):
            continue
        cat = block.get("id")
        items = block.get("items") or []
        if cat == "cat_spotlight":
            spotlights.extend(s for s in (_spotlight(i) for i in items) if s)
        elif cat == "cat_dailydeal":
            daily.extend(i for i in (_featured_item(x) for x in items) if i)
        elif cat in ("cat_specials", "cat_topsellers", "cat_newreleases", "cat_comingsoon"):
            name = {"cat_specials": "specials", "cat_topsellers": "top_sellers",
                    "cat_newreleases": "new_releases", "cat_comingsoon": "coming_soon"}[cat]
            seen, rows = set(), []
            for it in (_featured_item(x) for x in items):
                if it and it["id"] not in seen:
                    seen.add(it["id"])
                    rows.append(it)
            sections[name] = rows
    return {"country": (country or "US").upper(), "spotlights": spotlights or None, "daily_deals": daily or None,
            "specials": sections.get("specials"), "top_sellers": sections.get("top_sellers"),
            "new_releases": sections.get("new_releases"), "coming_soon": sections.get("coming_soon")}


def tags(language=None):
    """Every store tag with its id (for the `tags` filters), most-used first."""
    names = tag_names(language)
    if not names:
        raise fetch.SteamUpstreamError("tag list unavailable")
    order = []
    try:
        popular = fetch.store_json(f"tagdata/populartags/{language or 'english'}")
        order = [t.get("tagid") for t in popular or [] if isinstance(t, dict)]
    except Exception:
        order = []
    rank = {tid: i for i, tid in enumerate(order, 1)}
    rows = [{"id": tid, "name": name, "popularity_rank": rank.get(tid)} for tid, name in names.items()]
    rows.sort(key=lambda r: (r["popularity_rank"] is None, r["popularity_rank"] or 0, r["name"] or ""))
    return {"total": len(rows), "tags": rows}


def categories(language=None):
    """Store categories (player modes, features, controller support, app
    types) with their ids."""
    index = category_names(language)
    if not index:
        raise fetch.SteamUpstreamError("category list unavailable")
    rows = [{"id": cid, "name": P.clean(c.get("display_name")), "internal_name": P.clean(c.get("internal_name")),
             "group": CATEGORY_GROUPS.get(c.get("type"), "other"), "is_computed": bool(c.get("computed"))}
            for cid, c in index.items()]
    rows.sort(key=lambda r: (r["group"], r["id"]))
    return {"total": len(rows), "categories": rows}


# ---- packages / bundles ------------------------------------------------------------------------------------------

def _included(item, country, language):
    apps = ((item or {}).get("included_items") or {}).get("included_apps") or []
    currency = currency_for(country)
    names = tag_names(language)
    return [c for c in (P.store_item(a, currency, names) for a in apps) if c] or None


def package(package, country=None, language=None):
    """A package (the thing actually sold: a game, an edition, a DLC set)
    with its price and every app it grants."""
    body = fetch.store_json("api/packagedetails", {"packageids": package, "cc": (country or "US").upper(),
                                                   "l": language or "english"})
    entry = (body or {}).get(str(package)) or {}
    data = entry.get("data") if entry.get("success") and isinstance(entry.get("data"), dict) else None
    rows = get_items([{"packageid": package}], country, language,
                     {**CARD_REQUEST, "include_included_items": True, "include_all_purchase_options": True})
    item = rows[0] if rows and rows[0] and rows[0].get("success") == 1 else None
    if not data and not item:
        raise fetch.SteamNotFound(f"package {package} not found on the Steam store")
    data = data or {}
    price_raw = data.get("price") or {}
    currency = price_raw.get("currency") or currency_for(country)
    card = P.store_item(item, currency, tag_names(language)) if item else {}
    price = P.price_block(price_raw.get("final"), price_raw.get("initial"), price_raw.get("discount_percent"),
                          currency) if price_raw else (card or {}).get("price")
    release = data.get("release_date") or {}
    return {
        "id": package,
        "name": P.clean(data.get("name")) or (card or {}).get("name"),
        "link": refs.package_link(package),
        "price": price,
        "individual_price": P.money(price_raw.get("individual"), currency) if price_raw.get("individual") else None,
        "release_date": P.parse_date_text(release.get("date")) or (card or {}).get("release_date"),
        "is_coming_soon": bool(release.get("coming_soon")),
        "platforms": {k: bool((data.get("platforms") or {}).get(k)) for k in ("windows", "mac", "linux")}
        if data.get("platforms") else (card or {}).get("platforms"),
        "has_full_controller_support": bool((data.get("controller") or {}).get("full_gamepad")) if data.get("controller") else None,
        "reviews": (card or {}).get("reviews"),
        "images": P.compact({"page": P.clean(data.get("page_image")), "logo": P.clean(data.get("small_logo")),
                             **((card or {}).get("images") or {})}),
        "apps": _included(item, country, language) or [
            {"id": P.to_int(a.get("id")), "name": P.clean(a.get("name")), "link": refs.app_link(a.get("id"))}
            for a in data.get("apps") or [] if isinstance(a, dict)] or None,
    }


def bundle(bundle, country=None, language=None):
    """A bundle (a discounted set of packages) with its price, discount and
    every included game."""
    rows = get_items([{"bundleid": bundle}], country, language,
                     {**CARD_REQUEST, "include_included_items": True, "include_all_purchase_options": True})
    item = rows[0] if rows and rows[0] and rows[0].get("success") == 1 else None
    resolved = {}
    try:
        body = fetch.store_json("actions/ajaxresolvebundles", {"bundleids": bundle, "cc": (country or "US").upper(),
                                                              "l": language or "english"})
        resolved = body[0] if isinstance(body, list) and body else {}
    except Exception:
        resolved = {}
    if not item and not resolved:
        raise fetch.SteamNotFound(f"bundle {bundle} not found on the Steam store")
    currency = currency_for(country)
    card = P.store_item(item, currency, tag_names(language)) if item else {}
    price = (card or {}).get("price")
    if resolved.get("final_price") is not None:
        price = P.price_block(resolved.get("final_price"), resolved.get("initial_price"),
                              resolved.get("discount_percent"), currency) or price
    return {
        "id": bundle,
        "name": P.clean(resolved.get("name")) or (card or {}).get("name"),
        "link": (card or {}).get("link") or refs.bundle_link(bundle),
        "price": price,
        "bundle_discount_percent": P.to_int(resolved.get("bundle_base_discount")),
        "must_purchase_as_set": bool(resolved.get("must_purchase_as_set")) if resolved else None,
        "package_ids": resolved.get("packageids") or None,
        "app_ids": resolved.get("appids") or (card or {}).get("included_app_ids"),
        "is_coming_soon": bool(resolved.get("coming_soon")) if resolved else None,
        "platforms": {"windows": bool(resolved.get("available_windows")), "mac": bool(resolved.get("available_mac")),
                      "linux": bool(resolved.get("available_linux")),
                      "steam_deck_compatibility": P.DECK_COMPAT.get(resolved.get("deck_compatibility_category")),
                      "is_vr_supported": bool(resolved.get("support_vrhmd")),
                      "is_vr_only": bool(resolved.get("support_vrhmd_only"))} if resolved else (card or {}).get("platforms"),
        "reviews": (card or {}).get("reviews"),
        "tags": (card or {}).get("tags"),
        "images": P.compact({"header": P.clean(resolved.get("header_image_url")),
                             "capsule": P.clean(resolved.get("main_capsule")),
                             "library": P.clean(resolved.get("library_asset"))}),
        "apps": _included(item, country, language),
    }
