"""Steam transport: plain curl_cffi with browser-impersonated TLS against
the three Steam hosts — no browser, no cookies, no login (validated
2026-09-21 from direct Indian egress and residential US/DE exits; 60
appdetails + 60 appreviews bursts in under 3 s, all 200; datacenter exits
are refused).

Surfaces:
  store_json(path, params)     store.steampowered.com JSON (api/appdetails,
                               api/storesearch, search/results?json=1,
                               appreviews, appreviewhistogram, api/featured*,
                               api/dlcforapp, actions/ajaxresolve*, events/*,
                               saleaction/*, <developer|publisher|franchise>
                               /<slug>/ajaxgetfilteredrecommendations, …)
  store_page(path, params)     store HTML with the age-gate cookies set
                               (app pages, morelike)
  webapi(interface, method, version, params=None, input_json=None,
         key=False)            api.steampowered.com GET; `input_json` is the
                               JSON-encoded body the IStore*Service methods
                               take; key=True adds STEAM_WEB_API_KEY (400
                               when unset)
  webapi_post(...)             the ISteamRemoteStorage published-file POSTs
  community_json / community_xml / community_page
                               steamcommunity.com JSON, ?xml=1 documents,
                               and the classic server-rendered pages
  market_action(path, method, *args, country=None)
                               the new market SSR "query action" API:
                               GET /market/<path>?q=<Method>&qp=<json args>
                               with `x-valve-request-type: queryAction`;
                               prices follow the exit country, so a
                               `country` other than the pod's own egress is
                               served through a residential exit pinned to it
  market_json(path, params)    the legacy market JSON (search/render,
                               priceoverview, appfilters, recent) with the
                               per-thread 429 fallback exit

Age gate: app pages redirect to /agecheck/ for mature titles unless the
birthtime / lastagecheckage / wants_mature_content cookies are present; the
JSON APIs never gate. Bottle serves each request on its own thread, and
every thread keeps one curl_cffi session per host (sticky exit when a proxy
is configured).

FALLBACK HOOK: if Steam ever starts challenging the pod's IP (a captcha or
403 on every call) route it through a proxy (config.steam_proxy()); if a
challenge ever needs JavaScript, escalate the way g2 does — a patchright
pool with flag "steam" in config.CHROME_POOLS that opens the store and runs
the same GETs through the in-page fetch (patchright_driver.FetchResponse).
Not built: dead code while plain HTTP works.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  SteamUpstreamError  transport failure / 5xx / non-JSON body   — retryable
  SteamBlocked        403 / 429 (after the fallback exit)       — retryable
  SteamBadRequest     upstream rejected the params / key needed — never retried
  SteamNotFound       entity does not exist / is private        — never retried
"""
import json
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

STORE = "https://store.steampowered.com"
WEBAPI = "https://api.steampowered.com"
COMMUNITY = "https://steamcommunity.com"
IMPERSONATE = "chrome"
TIMEOUT = 40
RETRIES = 2                 # transport failures / 5xx per call
FANOUT_WORKERS = 8

AGE_COOKIES = {"birthtime": "0", "lastagecheckage": "1-0-1970", "wants_mature_content": "1",
               "Steam_Language": "english"}
JSON_HEADERS = {"accept": "application/json, text/javascript, */*; q=0.01",
                "accept-language": "en-US,en;q=0.9",
                "x-requested-with": "XMLHttpRequest"}
PAGE_HEADERS = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "en-US,en;q=0.9"}
MARKET_ACTION_HEADERS = {"accept": "application/json", "accept-language": "en-US,en;q=0.9",
                         "x-valve-request-type": "queryAction"}


class SteamUpstreamError(UpstreamError):
    """Transport failure, 5xx or a non-JSON body — retryable."""


class SteamBlocked(SteamUpstreamError, Blocked):
    """403 / 429 (after the market fallback exit was tried) — retryable."""


class SteamBadRequest(BadRequest):
    """Upstream rejected the request, or the route needs a Web API key — never retried."""


class SteamNotFound(NotFound):
    """Entity does not exist, or its owner keeps it private — never retried."""


class _PinnedRateLimited(SteamBlocked):
    """429 through a caller-pinned exit: the caller retries on a fresh one."""


# ---- sessions (one per worker thread and host) ----------------------------------

_local = threading.local()


def _sessions():
    store = getattr(_local, "sessions", None)
    if store is None:
        store = _local.sessions = {}
    return store


def _proxies():
    """Per-thread proxy URLs in use (fallback exit, country-pinned exits)."""
    store = getattr(_local, "proxies", None)
    if store is None:
        store = _local.proxies = {}
    return store


def _new_session(proxy):
    from curl_cffi import requests as curl_requests
    sess = curl_requests.Session(impersonate=IMPERSONATE)
    if proxy:
        sess.proxies = {"http": proxy, "https": proxy}
    return sess


def session(key="default", proxy=None):
    """The calling thread's session for `key` (a host or a purpose), created
    on first use with the configured proxy (config.steam_proxy() unless a
    specific one is given)."""
    store = _sessions()
    sess = store.get(key)
    if sess is None:
        sess = store[key] = _new_session(proxy if proxy is not None else config.steam_proxy())
    return sess


def drop_session(key="default"):
    sess = _sessions().pop(key, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def dump_debug(name, text):
    """Write a raw response to $STEAM_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("STEAM_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text)
        except OSError:
            pass


# ---- generic GET with retries -------------------------------------------------------

_fallback_lock = threading.Lock()
_fallback_until = {}    # thread ident -> time its direct egress may be retried
FALLBACK_ROTATIONS = 2  # fresh exits tried after the first fallback exit also answers 429


def _on_fallback():
    until = _fallback_until.get(threading.get_ident(), 0.0)
    return bool(until) and time.time() < until


def _enter_fallback(rotate=False):
    """Move the calling thread to a residential exit for
    STEAM_DIRECT_COOLDOWN seconds (a fresh one when `rotate`). False when
    no fallback is configured."""
    proxy = config.steam_fallback_proxy()
    if not proxy:
        return False
    with _fallback_lock:
        _fallback_until[threading.get_ident()] = time.time() + config.STEAM_DIRECT_COOLDOWN
    store = _sessions()
    for key in [k for k in store if k.endswith("~fallback")]:
        drop_session(key)
    _proxies()["fallback"] = proxy
    return True


def _route(session_key, proxy):
    """(session key, proxy) for this call: a pinned proxy is used as-is,
    otherwise the thread's fallback exit while its cooldown runs."""
    if proxy is None and _on_fallback():
        return session_key + "~fallback", _proxies().get("fallback") or config.steam_fallback_proxy()
    return session_key, proxy


def _request(method, url, *, params=None, data=None, headers=None, cookies=None, session_key="default",
             proxy=None, label=None, allow_redirects=True):
    """One HTTP call with transport retries (5xx / network) and the 429
    fallback: the thread moves to a residential exit (config.
    steam_fallback_proxy) and retries, rotating exits up to
    FALLBACK_ROTATIONS times; a pinned `proxy` is rotated by re-creating
    its session instead."""
    label = label or url
    attempt = 0
    rotations = 0
    while True:
        key, use_proxy = _route(session_key, proxy)
        sess = session(key, use_proxy)
        try:
            resp = sess.request(method, url, params=params or None, data=data, headers=headers,
                                cookies=cookies, timeout=TIMEOUT, allow_redirects=allow_redirects)
        except Exception as e:
            drop_session(key)
            attempt += 1
            if attempt > RETRIES:
                raise SteamUpstreamError(f"{label}: {type(e).__name__}: {e}")
            time.sleep(0.5 * attempt)
            continue
        if resp.status_code == 429:
            if rotations >= FALLBACK_ROTATIONS + 1:
                raise SteamBlocked(f"HTTP 429 on {label} (per-IP rate limit, fallback exits exhausted)")
            rotations += 1
            if proxy is not None:
                drop_session(key)        # pinned exit: the caller picks a new sticky port (= a new IP)
                raise _PinnedRateLimited(f"HTTP 429 on {label} through a pinned exit")
            if _enter_fallback(rotate=key.endswith("~fallback")):
                continue
            raise SteamBlocked(f"HTTP 429 on {label} (per-IP rate limit)")
        if resp.status_code >= 500:
            attempt += 1
            if attempt > RETRIES:
                raise SteamUpstreamError(f"HTTP {resp.status_code} on {label}")
            time.sleep(0.5 * attempt)
            continue
        return resp


def _json_body(resp, label):
    text = resp.text or ""
    try:
        return json.loads(text) if text.strip() else None
    except ValueError:
        dump_debug("non_json", text)
        raise SteamUpstreamError(f"non-JSON body (HTTP {resp.status_code}) on {label}")


def _check_status(resp, label, not_found=None):
    status = resp.status_code
    if status in (403, 429):
        dump_debug("blocked", resp.text)
        raise SteamBlocked(f"HTTP {status} on {label}")
    if status == 404:
        raise SteamNotFound(f"{not_found} not found" if not_found else f"{label} does not exist")
    if status == 400:
        text = (resp.text or "")[:300]
        if "key" in text.lower() and "missing" in text.lower():
            raise SteamBadRequest("this endpoint needs a Steam Web API key (STEAM_WEB_API_KEY)")
        raise SteamBadRequest(f"HTTP 400 on {label}")
    if status == 401:
        raise SteamBadRequest(f"HTTP 401 on {label} (a Steam Web API key is required)")
    if status != 200:
        raise SteamUpstreamError(f"HTTP {status} on {label}")


# ---- store.steampowered.com ---------------------------------------------------------

def store_json(path, params=None, not_found=None, label=None):
    """GET store.steampowered.com/<path> -> parsed JSON. A `null` body (how
    appdetails answers a bad `appids`) is a SteamBadRequest."""
    label = label or f"store {path}"
    resp = _request("GET", f"{STORE}/{path.lstrip('/')}", params=params, headers=JSON_HEADERS,
                    cookies=AGE_COOKIES, session_key="store", label=label)
    _check_status(resp, label, not_found)
    try:
        body = _json_body(resp, label)
    except SteamUpstreamError:
        if not_found:
            # unknown creator / curator slugs redirect to an HTML search page
            raise SteamNotFound(f"{not_found} not found")
        raise
    if body is None:
        raise SteamBadRequest(f"steam returned an empty answer for {label}")
    return body


def store_page(path, params=None, not_found=None, label=None):
    """GET a store HTML page with the age-gate cookies -> text. A redirect
    to /agecheck/ (cookies rejected) or the store front (unknown app) is a
    SteamNotFound when `not_found` names the entity."""
    label = label or f"store {path}"
    resp = _request("GET", f"{STORE}/{path.lstrip('/')}", params=params, headers=PAGE_HEADERS,
                    cookies=AGE_COOKIES, session_key="store", label=label)
    _check_status(resp, label, not_found)
    final = str(getattr(resp, "url", "") or "")
    if not_found and ("/agecheck/" in final or final.rstrip("/") == STORE):
        raise SteamNotFound(f"{not_found} not found")
    return resp.text or ""


# ---- api.steampowered.com -----------------------------------------------------------

def _key_params(params, key):
    params = dict(params or {})
    if key:
        if not config.STEAM_WEB_API_KEY:
            raise SteamBadRequest("this endpoint needs a Steam Web API key (set STEAM_WEB_API_KEY; "
                                  "free at steamcommunity.com/dev/apikey)")
        params["key"] = config.STEAM_WEB_API_KEY
    return params


def webapi(interface, method, version=1, params=None, input_json=None, key=False, not_found=None):
    """GET api.steampowered.com/<interface>/<method>/v<version>/ -> the
    `response` object (or the whole body when there is none)."""
    label = f"{interface}/{method}"
    params = _key_params(params, key)
    params.setdefault("format", "json")
    if input_json is not None:
        params["input_json"] = json.dumps(input_json, separators=(",", ":"))
    resp = _request("GET", f"{WEBAPI}/{interface}/{method}/v{version}/", params=params,
                    headers=JSON_HEADERS, session_key="webapi", label=label)
    _check_status(resp, label, not_found)
    body = _json_body(resp, label)
    if isinstance(body, dict) and "response" in body:
        return body["response"]
    return body


def webapi_post(interface, method, version=1, data=None, key=False, not_found=None):
    """POST form data (the ISteamRemoteStorage published-file lookups)."""
    label = f"{interface}/{method}"
    form = _key_params(data, key)
    resp = _request("POST", f"{WEBAPI}/{interface}/{method}/v{version}/", data=form,
                    headers=JSON_HEADERS, session_key="webapi", label=label)
    _check_status(resp, label, not_found)
    body = _json_body(resp, label)
    if isinstance(body, dict) and "response" in body:
        return body["response"]
    return body


# ---- steamcommunity.com --------------------------------------------------------------

def community_json(path, params=None, not_found=None, label=None, session_key="community", proxy=None):
    label = label or f"community {path}"
    resp = _request("GET", f"{COMMUNITY}/{path.lstrip('/')}", params=params, headers=JSON_HEADERS,
                    cookies=AGE_COOKIES, session_key=session_key, proxy=proxy, label=label)
    if resp.status_code == 403 and not_found:
        # the inventory endpoint answers a private / unknown inventory with 403 "null"
        raise SteamNotFound(f"{not_found} not found (private or does not exist)")
    _check_status(resp, label, not_found)
    return _json_body(resp, label)


def community_xml(path, params=None, not_found=None, label=None):
    """GET a steamcommunity ?xml=1 document -> ElementTree root. A profile
    that answers with an <error> element is a SteamNotFound."""
    label = label or f"community {path}"
    params = dict(params or {})
    params["xml"] = "1"
    resp = _request("GET", f"{COMMUNITY}/{path.lstrip('/')}", params=params, headers=PAGE_HEADERS,
                    cookies=AGE_COOKIES, session_key="community", label=label)
    _check_status(resp, label, not_found)
    text = resp.text or ""
    if not text.lstrip().startswith("<?xml"):
        dump_debug("non_xml", text)
        if not_found:
            raise SteamNotFound(f"{not_found} not found")
        raise SteamUpstreamError(f"non-XML body on {label}")
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        dump_debug("bad_xml", text)
        raise SteamUpstreamError(f"unparseable XML on {label}: {e}")
    if root.tag == "response" or root.find("error") is not None:
        message = (root.findtext("error") or "").strip()
        raise SteamNotFound(f"{not_found} not found: {message}" if not_found else message or "not found")
    return root


def community_page(path, params=None, not_found=None, label=None):
    """GET a classic server-rendered community page -> text. An error page
    (profile / file / group missing) is a SteamNotFound."""
    label = label or f"community {path}"
    resp = _request("GET", f"{COMMUNITY}/{path.lstrip('/')}", params=params, headers=PAGE_HEADERS,
                    cookies=AGE_COOKIES, session_key="community", label=label)
    _check_status(resp, label, not_found)
    text = resp.text or ""
    if not_found and ("<title>Steam Community :: Error</title>" in text or 'id="message"' in text[:20000]
                      and "could not be found" in text[:20000].lower()):
        raise SteamNotFound(f"{not_found} not found")
    return text


# ---- the market ------------------------------------------------------------------------

def market_json(path, params=None, not_found=None, label=None):
    """GET steamcommunity.com/market/<path> JSON (search/render,
    priceoverview, appfilters). priceoverview allows ~20 calls a minute per
    IP; its 429s ride the shared fallback in _request."""
    label = label or f"market {path}"
    resp = _request("GET", f"{COMMUNITY}/market/{path.lstrip('/')}", params=params, headers=JSON_HEADERS,
                    cookies=AGE_COOKIES, session_key="market", label=label)
    _check_status(resp, label, not_found)
    body = _json_body(resp, label)
    if body is None:
        raise SteamUpstreamError(f"empty body on {label}")
    return body


def market_action(path, method, *args, country=None, not_found=None):
    """The new market app's query-action API -> its `data` object. Prices
    follow the exit country: `country` other than config.STEAM_EGRESS_COUNTRY
    is served through a residential exit pinned to that country."""
    label = f"market {path} {method}"
    country = (country or config.STEAM_EGRESS_COUNTRY or "").upper()
    params = {"q": method, "qp": json.dumps(list(args), separators=(",", ":"))}
    pinned = bool(country) and country != config.STEAM_EGRESS_COUNTRY
    for attempt in range(3):
        if pinned:
            key = f"market-{country}"
            proxy = _proxies().get(key)
            if proxy is None:
                proxy = _proxies()[key] = config.steam_country_proxy(country)
        else:
            key, proxy = "market-actions", None
        try:
            resp = _request("GET", f"{COMMUNITY}/market/{path.lstrip('/')}", params=params,
                            headers=MARKET_ACTION_HEADERS, cookies=AGE_COOKIES, session_key=key, proxy=proxy,
                            label=label)
            break
        except _PinnedRateLimited:
            _proxies().pop(key, None)
            if attempt == 2:
                raise SteamBlocked(f"HTTP 429 on {label} through three {country} exits")
    _check_status(resp, label, not_found)
    body = _json_body(resp, label)
    if not isinstance(body, dict) or "data" not in body:
        raise SteamUpstreamError(f"unexpected answer on {label}")
    if body["data"] is None and not_found:
        raise SteamNotFound(f"{not_found} not found")
    return body["data"]


# ---- helpers ---------------------------------------------------------------------------

def fanout(fn, items, workers=FANOUT_WORKERS):
    """fn(item) for every item, in parallel, results in order."""
    items = list(items)
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(fn, items))
