"""Steam games (store apps): full details, regional prices, DLC, similar
games, achievements, live player count, Steam Deck / SteamOS compatibility
reports, news and events.

Details merge the two store surfaces: api/appdetails (descriptions, system
requirements, age ratings, metacritic, genres / categories by name,
screenshots, trailers, achievements highlight, support info) and
IStoreBrowseService/GetItems (tag weights, review summaries, purchase
options with discount end dates, per-language audio / subtitle support,
Deck / SteamOS / Steam Machine compatibility, social links, library art).
"""
import re

from steam import fetch, refs
from steam import parsers as P
from steam.shared import (app_cards, context, currency_for, get_items, paged_result, start_of,
                          tag_names)

DETAIL_REQUEST = {"include_assets": True, "include_release": True, "include_platforms": True,
                  "include_all_purchase_options": True, "include_ratings": True, "include_tag_count": 20,
                  "include_reviews": True, "include_basic_info": True, "include_supported_languages": True,
                  "include_included_items": True, "include_links": True}
DEFAULT_PRICE_COUNTRIES = ["US", "GB", "DE", "FR", "CA", "AU", "JP", "IN", "BR", "TR", "AR", "PL"]
EVENT_TYPES = {1: "other", 2: "game", 3: "party", 4: "meeting", 5: "special_cause", 6: "music_and_arts",
               7: "sports", 8: "trip", 9: "chat", 10: "game_release", 11: "broadcast", 12: "small_update",
               13: "pre_announce_major_update", 14: "major_update", 15: "dlc_release", 16: "future_release",
               17: "esports_tournament_stream", 18: "dev_stream", 19: "famous_stream", 20: "game_sale",
               21: "game_item_sale", 22: "in_game_bonus_xp", 23: "in_game_loot", 24: "in_game_perks",
               25: "in_game_challenge", 26: "in_game_contest", 27: "irl", 28: "news", 29: "beta_release",
               30: "in_game_content_release", 31: "free_trial", 32: "season_release", 33: "season_update",
               34: "crosspost", 35: "in_game_event"}
DECK_RESULTS = {4: "pass", 3: "warning", 2: "fail", 1: "info"}
RATING_BOARDS = {"esrb": "ESRB", "pegi": "PEGI", "usk": "USK", "cero": "CERO", "dejus": "DEJUS",
                 "oflc": "OFLC", "nzoflc": "NZ OFLC", "fpb": "FPB", "csrr": "CSRR", "crl": "CRL",
                 "kgrb": "KGRB", "grac": "GRAC", "agcom": "AGCOM", "steam_germany": "Steam Germany"}
_REQ_ITEM_RE = re.compile(r"<li>\s*(?:<strong>)?([^<:]+):?(?:</strong>)?:?\s*(.*?)(?:<br>)?\s*</li>", re.I | re.S)


# ---- raw fetchers ------------------------------------------------------------------------------------------

def appdetails(app_id, country=None, language=None, filters=None):
    params = {"appids": app_id, "cc": (country or "US").upper(), "l": language or "english"}
    if filters:
        params["filters"] = filters
    body = fetch.store_json("api/appdetails", params)
    entry = (body or {}).get(str(app_id)) or {}
    if not entry.get("success") or not isinstance(entry.get("data"), dict):
        raise fetch.SteamNotFound(f"app {app_id} not found on the Steam store (removed, unreleased region-locked or not an app)")
    return entry["data"]


# ---- details -------------------------------------------------------------------------------------------------

def _requirements(block):
    """appdetails {minimum, recommended} HTML -> {minimum: {...}, recommended: {...}}."""
    if not isinstance(block, dict):
        return None
    out = {}
    for level in ("minimum", "recommended"):
        raw = block.get(level)
        if not raw:
            continue
        specs = {}
        for key, value in _REQ_ITEM_RE.findall(raw):
            label = P.html_to_text(key)
            text = P.html_to_text(value)
            if label and text:
                specs[re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")] = text
        notes = [P.html_to_text(li) for li in re.findall(r"<li>(?!\s*<strong>)(.*?)</li>", raw, re.S)]
        out[level] = {"specs": specs or None, "notes": [n for n in notes if n] or None,
                      "text": P.html_to_text(raw.replace("<strong>Minimum:</strong>", "").replace(
                          "<strong>Recommended:</strong>", ""))}
    return out or None


def _age_ratings(block):
    if not isinstance(block, dict):
        return None
    out = []
    for board, info in block.items():
        if not isinstance(info, dict):
            continue
        descriptors = [d.strip() for d in re.split(r"[\r\n]+", P.html_to_text(info.get("descriptors")) or "") if d.strip()]
        out.append({"board": RATING_BOARDS.get(board, board.upper()), "rating": P.clean(str(info.get("rating") or "")).upper()
                    if info.get("rating") else None, "required_age": P.to_int(info.get("required_age")),
                    "descriptors": descriptors or None,
                    "interactive_elements": P.clean(info.get("interactive_elements")),
                    "is_age_gated": P.to_bool(info.get("use_age_gate"))})
    return out or None


def _languages(item, fallback_html):
    rows = []
    for lang in (item or {}).get("supported_languages") or []:
        if not isinstance(lang, dict) or not lang.get("supported"):
            continue
        rows.append({"name": P.ELANGUAGE.get(lang.get("elanguage"), str(lang.get("elanguage"))),
                     "has_interface": True, "has_full_audio": bool(lang.get("full_audio")),
                     "has_subtitles": bool(lang.get("subtitles"))})
    if rows:
        return rows
    text = fallback_html or ""
    for part in P.html_to_text(text.split("<br>")[0] if text else "") .split(",") if text else []:
        name = part.replace("*", "").strip()
        if name:
            rows.append({"name": name, "has_interface": True, "has_full_audio": "*" in part, "has_subtitles": None})
    return rows or None


def _purchase_options(item, currency):
    out = []
    for opt in (item or {}).get("purchase_options") or []:
        if not isinstance(opt, dict):
            continue
        out.append({
            "package_id": P.to_int(opt.get("packageid")),
            "bundle_id": P.to_int(opt.get("bundleid")),
            "name": P.clean(opt.get("purchase_option_name")),
            "price": P.purchase_price(opt, currency),
            "included_game_count": P.to_int(opt.get("included_game_count")),
            "is_bundle": bool(opt.get("bundleid")),
            "must_purchase_as_set": bool(opt.get("must_purchase_as_set")),
            "is_recurring_subscription": bool(opt.get("recurrence_info")),
        })
    return out or None


def _screenshots(data):
    out = []
    for s in data.get("screenshots") or []:
        if isinstance(s, dict):
            out.append({"id": P.to_int(s.get("id")), "thumbnail": P.clean(s.get("path_thumbnail")),
                        "full": P.clean(s.get("path_full"))})
    return out or None


def _trailers(data):
    out = []
    for m in data.get("movies") or []:
        if not isinstance(m, dict):
            continue
        out.append({"id": P.to_int(m.get("id")), "name": P.clean(m.get("name")),
                    "thumbnail": P.clean(m.get("thumbnail")),
                    "hls": P.clean(m.get("hls_h264")), "dash_h264": P.clean(m.get("dash_h264")),
                    "dash_av1": P.clean(m.get("dash_av1")),
                    "mp4": P.clean((m.get("mp4") or {}).get("max")), "webm": P.clean((m.get("webm") or {}).get("max")),
                    "is_highlight": bool(m.get("highlight"))})
    return out or None


def _social_links(item):
    out = []
    for link in (item or {}).get("links") or []:
        if isinstance(link, dict) and P.clean(link.get("url")):
            out.append({"type": P.LINK_TYPES.get(link.get("link_type"), "other"), "link": link["url"]})
    return out or None


def _tags(item, names):
    out = []
    for t in (item or {}).get("tags") or []:
        if isinstance(t, dict) and t.get("tagid") is not None:
            out.append({"id": t["tagid"], "name": names.get(t["tagid"]), "weight": P.to_int(t.get("weight"))})
    return out or None


def _compat(item):
    plat = (item or {}).get("platforms") or {}
    cat = {0: "unknown", 1: "unsupported", 2: "compatible", 3: "verified"}
    return {
        "steam_deck": P.DECK_COMPAT.get(plat.get("steam_deck_compat_category")),
        "steam_os": cat.get(plat.get("steam_os_compat_category")),
        "steam_machine": P.DECK_COMPAT.get(plat.get("steam_machine_compat_category")),
        "steam_frame": P.DECK_COMPAT.get(plat.get("steam_frame_compat_category")),
    } if plat else None


def details(game, country=None, language=None):
    """Everything the store page shows about an app."""
    data = appdetails(game, country, language)
    rows = get_items([{"appid": game}], country, language, DETAIL_REQUEST)
    item = rows[0] if rows and rows[0] and rows[0].get("success") == 1 else {}
    currency = (data.get("price_overview") or {}).get("currency") or currency_for(country)
    names = tag_names(language)
    card = P.store_item(item, currency, names) if item else {}
    overview = data.get("price_overview") or {}
    if overview:
        price = P.price_block(overview.get("final"), overview.get("initial"), overview.get("discount_percent"),
                              overview.get("currency"))
        if card and card.get("price") and card["price"].get("discount_ends_at"):
            price["discount_ends_at"] = card["price"]["discount_ends_at"]
    else:
        price = (card or {}).get("price") or (P.price_block(None, currency=currency, is_free=True)
                                              if data.get("is_free") else None)
    release = data.get("release_date") or {}
    reviews = (item or {}).get("reviews") or {}
    metacritic = data.get("metacritic") or {}
    achievements = data.get("achievements") or {}
    support = data.get("support_info") or {}
    descriptors = data.get("content_descriptors") or {}
    fullgame = data.get("fullgame") or {}
    try:
        players = current_players(game)["player_count"]
    except Exception:
        players = None
    app_id = P.to_int(data.get("steam_appid")) or game
    return {
        "id": app_id,
        "type": P.clean(data.get("type")),
        "name": P.clean(data.get("name")),
        "link": (card or {}).get("link") or refs.app_link(app_id),
        "short_description": P.html_to_text(data.get("short_description")),
        "description": P.html_to_text(data.get("detailed_description")),
        "release_date": P.parse_date_text(release.get("date")) or (card or {}).get("release_date"),
        "release_date_text": P.clean(release.get("date")),
        "is_coming_soon": bool(release.get("coming_soon")),
        "is_free": bool(data.get("is_free")),
        "is_early_access": bool((item or {}).get("is_early_access")),
        "required_age": P.to_int(data.get("required_age")) or 0,
        "controller_support": P.clean(data.get("controller_support")),
        "price": price,
        "purchase_options": _purchase_options(item, currency),
        "current_players": players,
        "reviews": {
            "overall": P._review_summary(reviews.get("summary_filtered")),
            "in_language": P._review_summary(reviews.get("summary_language_specific")),
        } if reviews else None,
        "metacritic": {"score": P.to_int(metacritic.get("score")),
                       "link": (P.clean(metacritic.get("url")) or "").split("?")[0] or None}
        if metacritic else None,
        "critic_quotes": P.html_to_text(data.get("reviews")),
        "developers": [P.clean(d) for d in data.get("developers") or [] if P.clean(d)] or None,
        "publishers": [P.clean(p) for p in data.get("publishers") or [] if P.clean(p)] or None,
        "genres": [{"id": P.to_int(g.get("id")), "name": P.clean(g.get("description"))}
                   for g in data.get("genres") or [] if isinstance(g, dict)] or None,
        "categories": [{"id": P.to_int(c.get("id")), "name": P.clean(c.get("description"))}
                       for c in data.get("categories") or [] if isinstance(c, dict)] or None,
        "tags": _tags(item, names),
        "platforms": {
            "windows": bool((data.get("platforms") or {}).get("windows")),
            "mac": bool((data.get("platforms") or {}).get("mac")),
            "linux": bool((data.get("platforms") or {}).get("linux")),
            "is_vr_supported": ((card or {}).get("platforms") or {}).get("is_vr_supported"),
            "is_vr_only": ((card or {}).get("platforms") or {}).get("is_vr_only"),
        },
        "compatibility": _compat(item),
        "requirements": {
            "windows": _requirements(data.get("pc_requirements")),
            "mac": _requirements(data.get("mac_requirements")) if (data.get("platforms") or {}).get("mac") else None,
            "linux": _requirements(data.get("linux_requirements")) if (data.get("platforms") or {}).get("linux") else None,
        },
        "languages": _languages(item, data.get("supported_languages")),
        "age_ratings": _age_ratings(data.get("ratings")),
        "content_descriptors": {
            "ids": descriptors.get("ids") or None,
            "notes": P.html_to_text(descriptors.get("notes")),
        } if descriptors.get("ids") or descriptors.get("notes") else None,
        "achievements": {
            "total": P.to_int(achievements.get("total")) or 0,
            "highlighted": [{"name": P.clean(a.get("name")), "icon": P.clean(a.get("path"))}
                            for a in achievements.get("highlighted") or [] if isinstance(a, dict)] or None,
        } if achievements else None,
        "parent_game": {"id": P.to_int(fullgame.get("appid")), "name": P.clean(fullgame.get("name")),
                        "link": refs.app_link(fullgame.get("appid"))} if fullgame.get("appid") else None,
        "dlc_ids": data.get("dlc") or None,
        "demo_ids": [P.to_int(d.get("appid")) for d in data.get("demos") or [] if isinstance(d, dict)] or None,
        "package_ids": data.get("packages") or None,
        "media": {
            "screenshots": _screenshots(data),
            "trailers": _trailers(data),
            "background": P.clean(data.get("background")),
        },
        "images": (card or {}).get("images") or {"header": P.clean(data.get("header_image")),
                                                   "capsule": P.clean(data.get("capsule_image"))},
        "website": P.clean(data.get("website")),
        "support": {"link": P.clean(support.get("url")), "email": P.clean(support.get("email"))}
        if P.clean(support.get("url")) or P.clean(support.get("email")) else None,
        "social_links": _social_links(item),
        "legal_notice": P.html_to_text(data.get("legal_notice")),
        "community_link": refs.community_app_link(app_id),
    }


# ---- prices / dlc / similar ----------------------------------------------------------------------------------

def prices(game, countries=None):
    """The app's price in several storefronts (regional pricing)."""
    countries = countries or DEFAULT_PRICE_COUNTRIES

    def one(country):
        try:
            body = fetch.store_json("api/appdetails", {"appids": game, "cc": country, "filters": "price_overview"})
        except Exception as e:
            return {"country": country, "price": None, "error": str(e)}
        entry = (body or {}).get(str(game)) or {}
        if not entry.get("success"):
            return {"country": country, "price": None, "is_available": False}
        data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
        overview = data.get("price_overview") or {}
        price = P.price_block(overview.get("final"), overview.get("initial"), overview.get("discount_percent"),
                              overview.get("currency")) if overview else None
        return {"country": country, "price": price, "is_available": True}
    rows = fetch.fanout(one, countries, workers=6)
    if not any(r.get("is_available") for r in rows):
        appdetails(game)      # raises NotFound for an unknown app
    for r in rows:
        r.setdefault("error", None)
    return {"id": game, "prices": rows}


def dlc(game, country=None, language=None, page=1, limit=25):
    """The app's DLC as full cards (price, reviews, release date)."""
    data = appdetails(game, country, language, filters="basic")
    ids = data.get("dlc") or []
    window = ids[start_of(page, limit):start_of(page, limit) + limit]
    results = app_cards(window, country, language)
    return paged_result("dlc", results, page, limit, total=len(ids),
                        game={"id": game, "name": P.clean(data.get("name")), "link": refs.app_link(game)})


_SIMILAR_BLOCK_RE = re.compile(r'<div class="recommendation_area_ctn similar_grid_ctn" id="([a-z_]+)"(.*?)'
                               r'(?=<div class="recommendation_area_ctn similar_grid_ctn"|<div id="footer")', re.S)


def similar(game, country=None, language=None, limit=20):
    """Games that share the app's most-applied tags (the store's "More
    like this" page), grouped the way the page groups them."""
    html_text = fetch.store_page(f"recommended/morelike/app/{game}/", {"cc": country or "US"},
                                 not_found=f"app {game}")
    sections = {}
    for name, body in _SIMILAR_BLOCK_RE.findall(html_text):
        ids = [int(a) for a in re.findall(r'data-ds-appid="(\d+)"', body)]
        ids = [a for a in dict.fromkeys(ids) if a != game]
        if ids:
            sections[name] = ids
    if not sections:
        ids = [int(a) for a in re.findall(r'data-ds-appid="(\d+)"', html_text)]
        ids = [a for a in dict.fromkeys(ids) if a != game]
        if not ids:
            raise fetch.SteamNotFound(f"no similar games found for app {game}")
        sections["released"] = ids
    wanted = []
    for ids in sections.values():
        for a in ids[:limit]:
            if a not in wanted:
                wanted.append(a)
    by_id = {c["id"]: c for c in app_cards(wanted, country, language)}
    labels = {"released": "similar", "newreleases": "new_releases", "topsellers": "top_sellers",
              "comingsoon": "coming_soon", "freegames": "free_games"}
    out = {"game_id": game}
    for name, ids in sections.items():
        out[labels.get(name, name)] = [by_id[a] for a in ids[:limit] if a in by_id]
    return out


# ---- achievements / players / compatibility ---------------------------------------------------------------------

_ACH_ROW_RE = re.compile(r'<div class="achieveRow\s*">(.*?)<div style="clear: both;"></div>\s*</div>', re.S)


def achievements(game, language=None):
    """Every achievement with its description, icon and the share of
    players who unlocked it (the community stats page)."""
    html_text = fetch.community_page(f"stats/{game}/achievements/", {"l": language or "english"},
                                     not_found=f"app {game}")
    rows = []
    for block in _ACH_ROW_RE.findall(html_text):
        name = P.text_between(block, "<h3>", "</h3>")
        if not name:
            continue
        rows.append({
            "name": name,
            "description": P.text_between(block, "<h5>", "</h5>"),
            "percent_unlocked": P.to_float((P.text_between(block, '<div class="achievePercent">') or "").rstrip("%")),
            "icon": P.attr(block[block.find("<img"):], "src") if "<img" in block else None,
        })
    title = P.text_between(html_text, '<div class="profile_small_header_location">', "</div>") \
        or P.text_between(html_text, "<title>", "</title>")
    if not rows:
        body = fetch.webapi("ISteamUserStats", "GetGlobalAchievementPercentagesForApp", 2, {"gameid": game})
        pct = ((body or {}).get("achievementpercentages") or {}).get("achievements") or []
        if not pct:
            raise fetch.SteamNotFound(f"app {game} has no achievements")
        rows = [{"name": a.get("name"), "description": None, "percent_unlocked": P.to_float(a.get("percent")),
                 "icon": None} for a in pct if isinstance(a, dict)]
    return {"game_id": game, "game_name": (title or "").split("::")[-2].strip() if title and "::" in title else None,
            "total": len(rows), "achievements": rows}


def current_players(game):
    body = fetch.webapi("ISteamUserStats", "GetNumberOfCurrentPlayers", 1, {"appid": game})
    if not isinstance(body, dict) or body.get("result") != 1:
        raise fetch.SteamNotFound(f"no player count for app {game}")
    return {"game_id": game, "player_count": P.to_int(body.get("player_count"))}


def player_count(game):
    """Players in-game right now (Steam's live counter)."""
    return current_players(game)


def _compat_items(items):
    out = []
    for i in items or []:
        if isinstance(i, dict):
            out.append({"result": DECK_RESULTS.get(i.get("display_type"), "info"),
                        "note": P.split_camel(i.get("loc_token"))})
    return out or None


def compatibility(game):
    """Valve's Steam Deck / SteamOS / Steam Machine / Steam Frame
    compatibility verdicts with each tested criterion."""
    body = fetch.store_json("saleaction/ajaxgetdeckappcompatibilityreport", {"nAppID": game, "l": "english"})
    results = (body or {}).get("results") if isinstance(body, dict) else None
    if not isinstance(results, dict):
        raise fetch.SteamNotFound(f"no compatibility report for app {game}")
    cat = {0: "unknown", 1: "unsupported", 2: "playable", 3: "verified"}
    return {
        "game_id": game,
        "steam_deck": {"verdict": cat.get(results.get("resolved_category"), "unknown"),
                       "criteria": _compat_items(results.get("resolved_items"))},
        "steam_os": {"verdict": {0: "unknown", 1: "unsupported", 2: "compatible"}.get(results.get("steamos_resolved_category"), "unknown"),
                     "criteria": _compat_items(results.get("steamos_resolved_items"))},
        "steam_machine": {"verdict": cat.get(results.get("machine_resolved_category"), "unknown"),
                          "criteria": _compat_items(results.get("machine_resolved_items"))},
        "steam_frame": {"verdict": cat.get(results.get("frame_resolved_category"), "unknown"),
                        "criteria": _compat_items(results.get("frame_resolved_items"))},
        "blog_link": P.clean(results.get("steam_deck_blog_url")),
    }


# ---- news / events ---------------------------------------------------------------------------------------------------

def _news_item(n, app_id):
    gid = P.clean(n.get("gid"))
    feed = P.clean(n.get("feedname"))
    link = P.clean(n.get("url"))
    if feed == "steam_community_announcements" and gid:
        link = f"https://store.steampowered.com/news/app/{app_id}/view/{gid}"
    return {
        "id": gid,
        "title": P.clean(n.get("title")),
        "link": link,
        "author": P.clean(n.get("author")),
        "published_at": P.iso_datetime(n.get("date")),
        "content": P.bbcode_to_text(n.get("contents")),
        "source": P.clean(n.get("feedlabel")),
        "source_id": feed,
        "is_external": bool(n.get("is_external_url")) and feed != "steam_community_announcements",
        "tags": n.get("tags") or None,
    }


def news(game, limit=20, before=None, official_only=False, patch_notes_only=False):
    """News posts for an app (official announcements + press feeds),
    newest first. Page with `before` = the `published_at` date of the last
    item you received."""
    params = {"appid": game, "count": limit, "maxlength": 0}
    if before:
        # enddate takes unix seconds (a YYYY-MM-DD string silently returns no items)
        from datetime import datetime, timezone
        params["enddate"] = int(datetime.strptime(before, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    if official_only:
        params["feeds"] = "steam_community_announcements"
    if patch_notes_only:
        params["tags"] = "patchnotes"
    body = fetch.webapi("ISteamNews", "GetNewsForApp", 2, params, not_found=f"app {game}")
    appnews = (body or {}).get("appnews") if isinstance(body, dict) else None
    if not isinstance(appnews, dict):
        raise fetch.SteamNotFound(f"no news for app {game}")
    items = [_news_item(n, game) for n in appnews.get("newsitems") or [] if isinstance(n, dict)]
    last = items[-1]["published_at"] if items else None
    return {"game_id": game, "total": P.to_int(appnews.get("count")), "news": items,
            "next_before": last[:10] if last and len(items) >= limit else None}


def _event(e, app_id):
    import json as _json
    try:
        extra = _json.loads(e.get("jsondata") or "{}")
    except ValueError:
        extra = {}
    body = e.get("announcement_body") or {}
    gid = P.clean(str(e.get("gid") or "")) or None
    summaries = extra.get("localized_summary") or []
    subtitles = extra.get("localized_subtitle") or []
    return {
        "id": gid,
        "name": P.clean(e.get("event_name")),
        "link": f"https://store.steampowered.com/news/app/{app_id}/view/{body.get('gid') or gid}" if gid else None,
        "type": EVENT_TYPES.get(e.get("event_type"), "other"),
        "subtitle": P.clean(subtitles[0]) if subtitles else None,
        "summary": P.clean(summaries[0]) if summaries else None,
        "content": P.bbcode_to_text(body.get("body")),
        "starts_at": P.iso_datetime(e.get("rtime32_start_time")),
        "ends_at": P.iso_datetime(e.get("rtime32_end_time")),
        "published_at": P.iso_datetime(body.get("posttime") or e.get("rtime_created")),
        "updated_at": P.iso_datetime(body.get("updatetime") or e.get("rtime32_last_modified")),
        "votes_up": P.to_int(e.get("votes_up")) or 0,
        "votes_down": P.to_int(e.get("votes_down")) or 0,
        "comment_count": P.to_int(e.get("comment_count")) or 0,
        "build_id": P.to_int(e.get("build_id")) or None,
        "build_branch": P.clean(e.get("build_branch")),
        "referenced_app_ids": e.get("referenced_appids") or None,
    }


def events(game, limit=10, language=None):
    """The app's store events (updates, patch notes, sales, streams,
    releases) with their body text, newest first."""
    body = fetch.store_json("events/ajaxgetadjacentpartnerevents/",
                            {"appid": game, "count_before": 0, "count_after": limit, "l": language or "english"})
    rows = (body or {}).get("events") if isinstance(body, dict) else None
    if rows is None:
        raise fetch.SteamNotFound(f"no events for app {game}")
    items = [_event(e, game) for e in rows if isinstance(e, dict)]
    items.sort(key=lambda e: e["published_at"] or "", reverse=True)
    return {"game_id": game, "events": items[:limit]}
