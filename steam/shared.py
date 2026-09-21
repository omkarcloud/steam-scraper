"""Helpers shared by the Steam endpoint modules: the store context
(country + language), in-process lookup tables (tag names, category names,
the currency a country is priced in), GetItems hydration of id lists into
full cards, and the paged-result envelope route_glue lifts."""
import threading
import time

import config
from steam import fetch
from steam import parsers as P

# public language code -> Steam's language name (the `l=` / context value)
LANGUAGES = {
    "en": "english", "de": "german", "fr": "french", "it": "italian", "ko": "koreana", "es": "spanish",
    "es-419": "latam", "zh-cn": "schinese", "zh-tw": "tchinese", "ru": "russian", "th": "thai",
    "ja": "japanese", "pt": "portuguese", "pt-br": "brazilian", "pl": "polish", "da": "danish",
    "nl": "dutch", "fi": "finnish", "no": "norwegian", "sv": "swedish", "hu": "hungarian", "cs": "czech",
    "ro": "romanian", "tr": "turkish", "bg": "bulgarian", "el": "greek", "ar": "arabic", "uk": "ukrainian",
    "vi": "vietnamese", "id": "indonesian",
}
DEFAULT_LANGUAGE = "english"
DEFAULT_COUNTRY = "US"
HYDRATE_BATCH = 100
LOOKUP_TTL = 6 * 3600

CARD_REQUEST = {"include_assets": True, "include_release": True, "include_platforms": True,
                "include_tag_count": 20, "include_reviews": True, "include_basic_info": True}

_lookup_lock = threading.Lock()
_lookups = {}


def lookup(key, build, ttl=LOOKUP_TTL):
    """Memoise build() for `ttl` seconds; a failed rebuild keeps serving the
    last good value (and re-raises only when there is none)."""
    now = time.time()
    with _lookup_lock:
        hit = _lookups.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        value = build()
    except Exception:
        if hit:
            return hit[1]
        raise
    with _lookup_lock:
        _lookups[key] = (now + ttl, value)
    return value


def context(country=None, language=None):
    return {"language": language or DEFAULT_LANGUAGE, "country_code": (country or DEFAULT_COUNTRY).upper(),
            "steam_realm": 1}


# ---- lookup tables ------------------------------------------------------------------------------------

def tag_names(language=None):
    """{tag id: localized name} from IStoreService/GetTagList (6 h); {} when
    the list cannot be fetched (cards then carry no tag names)."""
    language = language or DEFAULT_LANGUAGE

    def build():
        body = fetch.webapi("IStoreService", "GetTagList", 1, {"language": language})
        return {t["tagid"]: t.get("name") for t in (body or {}).get("tags") or []
                if isinstance(t, dict) and t.get("tagid") is not None}
    try:
        return lookup(("tags", language), build)
    except Exception:
        return {}


def category_names(language=None):
    """{category id: display name} from IStoreBrowseService/GetStoreCategories."""
    language = language or DEFAULT_LANGUAGE

    def build():
        body = fetch.webapi("IStoreBrowseService", "GetStoreCategories", 1, {"language": language})
        return {c["categoryid"]: c for c in (body or {}).get("categories") or []
                if isinstance(c, dict) and c.get("categoryid") is not None}
    try:
        return lookup(("categories", language), build)
    except Exception:
        return {}


# apps sold (paid) in virtually every storefront; the first that answers
# gives the country's currency code
_PRICE_PROBE_APPS = (1245620, 292030, 1091500, 271590)


def currency_for(country=None):
    """ISO currency code the store prices `country` in (USD for US, EUR for
    DE, INR for IN, USD for many LatAm / MENA countries …). GetItems prices
    carry no currency code, so this is read once per country from an
    appdetails price_overview and memoised; None when unknown."""
    country = (country or DEFAULT_COUNTRY).upper()

    def build():
        for app_id in _PRICE_PROBE_APPS:
            body = fetch.store_json("api/appdetails", {"appids": app_id, "cc": country, "filters": "price_overview"})
            entry = (body or {}).get(str(app_id)) or {}
            data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
            code = (data.get("price_overview") or {}).get("currency")
            if code:
                return code
        return None
    try:
        return lookup(("currency", country), build, ttl=24 * 3600)
    except Exception:
        return None


# ---- hydration --------------------------------------------------------------------------------------------

def get_items(ids, country=None, language=None, data_request=None):
    """IStoreBrowseService/GetItems for [{"appid": n} | {"packageid": n} |
    {"bundleid": n}, …] in batches -> raw store items in request order."""
    ids = list(ids)
    if not ids:
        return []
    batches = [ids[i:i + HYDRATE_BATCH] for i in range(0, len(ids), HYDRATE_BATCH)]

    def one(batch):
        body = fetch.webapi("IStoreBrowseService", "GetItems", 1, input_json={
            "ids": batch, "context": context(country, language), "data_request": data_request or CARD_REQUEST})
        return (body or {}).get("store_items") or []
    rows = [row for chunk in fetch.fanout(one, batches, workers=4) for row in chunk]
    by_key = {}
    for row in rows:
        if isinstance(row, dict):
            kind = {0: "appid", 1: "packageid", 2: "bundleid"}.get(row.get("item_type"), "appid")
            by_key[(kind, row.get("id"))] = row
    return [by_key.get(next(iter(i.items()))) for i in ids]


def cards(ids, country=None, language=None):
    """Id list -> shared cards (hidden / failed items dropped)."""
    currency = currency_for(country)
    names = tag_names(language)
    out = []
    for row in get_items(ids, country, language):
        card = P.store_item(row, currency, names) if row else None
        if card:
            out.append(card)
    return out


def app_cards(app_ids, country=None, language=None):
    return cards([{"appid": int(a)} for a in app_ids if a], country, language)


def key_cards(keys, country=None, language=None):
    """[(kind, id)] from store HTML rows -> cards."""
    return cards([{kind: item_id} for kind, item_id in keys], country, language)


# ---- paging ------------------------------------------------------------------------------------------------

def pagination(page, per_page, total=None, has_more=None):
    total_pages = None
    if total is not None:
        total_pages = (total + per_page - 1) // per_page if per_page else 0
    elif has_more is not None:
        total_pages = page + 1 if has_more else page
    return {"page": page, "items_per_page": per_page, "total_count": total, "total_pages": total_pages}


def paged_result(key, results, page, per_page, total=None, has_more=None, **extra):
    """Endpoint result with a `pagination` block route_glue lifts."""
    if has_more is None and total is None:
        has_more = len(results) >= per_page
    out = dict(extra)
    out[key] = results
    out["pagination"] = pagination(page, per_page, total, has_more)
    return out


def start_of(page, per_page):
    return (page - 1) * per_page


def country_or_default(country):
    return (country or DEFAULT_COUNTRY).upper()


def web_api_key_configured():
    return bool(config.STEAM_WEB_API_KEY)
