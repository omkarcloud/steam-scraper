"""Steam reference parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrLinkField convention — never a sibling `url`/`id`
pair). Every resolver returns a plain value so the validated params stay
usable as a response-cache key:

  app        1245620 | https://store.steampowered.com/app/1245620/ELDEN_RING/
             | steamcommunity.com/app/1245620/… | store.steampowered.com/agecheck/app/1245620
  package    440408 | https://store.steampowered.com/sub/440408/
  bundle     232 | https://store.steampowered.com/bundle/232/Valve_Complete_Pack/
  user       76561197960287930 (steamid64) | STEAM_0:0:11101 (steamid2)
             | [U:1:22202] (steamid3) | 22202 (account id) | gabelogannewell (vanity)
             | steamcommunity.com/profiles/7656…/… | steamcommunity.com/id/gabelogannewell/…
             -> {"steamid": "7656…"} or {"vanity": "gabelogannewell"} (resolved by users.py)
  group      valve | 103582791429521412 | steamcommunity.com/groups/valve
             | steamcommunity.com/gid/1035… -> {"name": …} or {"gid": …}
  file       104691717 (published file id) | steamcommunity.com/sharedfiles/filedetails/?id=…
             | steamcommunity.com/workshop/filedetails/?id=…
  creator    FromSoftware | https://store.steampowered.com/developer/FromSoftware/
             | …/publisher/BANDAINAMCO | …/franchise/Halo -> the slug
  curator    44944848 | https://store.steampowered.com/curator/44944848-Rock-Paper-Shotgun/
             -> "44944848-Rock-Paper-Shotgun" (the id, with the slug when given)
  market item  "AK-47 | Redline (Field-Tested)" (market hash name)
             | https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20(Field-Tested)
             -> {"app_id": 730 | None, "name": "AK-47 | Redline (Field-Tested)"}
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

STORE_HOSTS = ("store.steampowered.com", "steampowered.com")
COMMUNITY_HOSTS = ("steamcommunity.com", "www.steamcommunity.com")
STEAMID64_BASE = 76561197960265728
_VANITY_RE = re.compile(r"^[A-Za-z0-9_\-]{2,32}$")
_GROUP_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_STEAMID2_RE = re.compile(r"^STEAM_[0-5]:([01]):(\d+)$", re.I)
_STEAMID3_RE = re.compile(r"^\[?U:1:(\d+)\]?$", re.I)
_SLUG_RE = re.compile(r"^[A-Za-z0-9_\-.%]{1,100}$")


def _parsed(value):
    url = value if "://" in value else "https://" + value.lstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]
    return host, parts, parsed


def _is_link(value):
    low = value.lower()
    return low.startswith(("http://", "https://", "//")) or "steampowered.com" in low or "steamcommunity.com" in low


def _store_entity(value, segment, kind):
    """<segment>/<id>/… on the store (or community for apps) -> int id."""
    value = (value or "").strip()
    if value.isdigit():
        return int(value)
    if _is_link(value):
        host, parts, _ = _parsed(value)
        if host.endswith(STORE_HOSTS) or host in COMMUNITY_HOSTS:
            if parts and parts[0] == "agecheck":
                parts = parts[1:]
            if len(parts) >= 2 and parts[0].lower() == segment and parts[1].isdigit():
                return int(parts[1])
    raise ValueError(f"{kind} must be a Steam {kind} id (e.g. {'1245620' if kind == 'app' else '232'}) "
                     f"or a store.steampowered.com/{segment}/<id> link")


def resolve_app(value):
    return _store_entity(value, "app", "app")


def resolve_package(value):
    return _store_entity(value, "sub", "package")


def resolve_bundle(value):
    return _store_entity(value, "bundle", "bundle")


# ---- users ----------------------------------------------------------------------------

def steamid64_from_account(account_id):
    return str(STEAMID64_BASE + int(account_id))


def steamid_formats(steamid64):
    """Every id form of a 64-bit steamid."""
    sid = int(steamid64)
    account = sid - STEAMID64_BASE
    return {
        "steamid64": str(sid),
        "steamid2": f"STEAM_0:{account % 2}:{account // 2}",
        "steamid3": f"[U:1:{account}]",
        "account_id": account,
        "steamid64_hex": format(sid, "x"),
        "link": f"https://steamcommunity.com/profiles/{sid}",
    }


def resolve_user(value):
    """-> {"steamid": "7656…"} for any numeric form, {"vanity": …} for a
    custom URL name (looked up by users.py)."""
    value = (value or "").strip()
    if not value:
        raise ValueError("user must be a steamid64, STEAM_0:x:y, [U:1:n], a vanity name or a steamcommunity.com profile link")
    if _is_link(value):
        host, parts, _ = _parsed(value)
        if host in COMMUNITY_HOSTS and len(parts) >= 2:
            if parts[0] == "profiles" and parts[1].isdigit():
                return {"steamid": parts[1]}
            if parts[0] == "id" and _VANITY_RE.match(parts[1]):
                return {"vanity": parts[1]}
        raise ValueError("user link must be steamcommunity.com/profiles/<steamid64> or steamcommunity.com/id/<name>")
    match = _STEAMID2_RE.match(value)
    if match:
        return {"steamid": str(STEAMID64_BASE + int(match.group(2)) * 2 + int(match.group(1)))}
    match = _STEAMID3_RE.match(value)
    if match:
        return {"steamid": steamid64_from_account(match.group(1))}
    if value.isdigit():
        number = int(value)
        if number >= STEAMID64_BASE:
            return {"steamid": str(number)}
        if 0 < number < 2 ** 32:
            return {"steamid": steamid64_from_account(number)}
        raise ValueError("user id out of range")
    if _VANITY_RE.match(value):
        return {"vanity": value}
    raise ValueError("user must be a steamid64, STEAM_0:x:y, [U:1:n], a vanity name or a steamcommunity.com profile link")


# ---- groups ----------------------------------------------------------------------------

def resolve_group(value):
    value = (value or "").strip()
    if _is_link(value):
        host, parts, _ = _parsed(value)
        if host in COMMUNITY_HOSTS and len(parts) >= 2:
            if parts[0] == "groups" and _GROUP_RE.match(parts[1]):
                return {"name": parts[1]}
            if parts[0] == "gid" and parts[1].isdigit():
                return {"gid": parts[1]}
        raise ValueError("group link must be steamcommunity.com/groups/<name> or steamcommunity.com/gid/<id>")
    if value.isdigit() and len(value) >= 17:
        return {"gid": value}
    if _GROUP_RE.match(value):
        return {"name": value}
    raise ValueError("group must be a group name (valve), a 64-bit group id or a steamcommunity.com/groups link")


# ---- published files (workshop items, guides, collections, screenshots) -----------------

def resolve_file(value):
    value = (value or "").strip()
    if value.isdigit():
        return int(value)
    if _is_link(value):
        host, parts, parsed = _parsed(value)
        if host in COMMUNITY_HOSTS and parts and parts[0] in ("sharedfiles", "workshop"):
            file_id = (parse_qs(parsed.query).get("id") or [""])[0]
            if file_id.isdigit():
                return int(file_id)
    raise ValueError("file must be a published file id (e.g. 104691717) or a steamcommunity.com/sharedfiles/filedetails/?id=… link")


# ---- creators (developer / publisher / franchise pages), curators ------------------------------

CREATOR_KINDS = ("developer", "publisher", "franchise")


def resolve_creator(value):
    """-> {"kind": developer|publisher|franchise|None, "slug": …}; a bare
    slug carries no kind (the endpoint tries developer, then publisher)."""
    value = (value or "").strip()
    if _is_link(value):
        host, parts, _ = _parsed(value)
        if host.endswith(STORE_HOSTS) and len(parts) >= 2 and parts[0].lower() in CREATOR_KINDS:
            return {"kind": parts[0].lower(), "slug": unquote(parts[1])}
        raise ValueError("creator link must be store.steampowered.com/<developer|publisher|franchise>/<slug>")
    if _SLUG_RE.match(value):
        return {"kind": None, "slug": value}
    raise ValueError("creator must be a store developer / publisher / franchise slug (FromSoftware) or its store link")


def resolve_curator(value):
    value = (value or "").strip()
    if _is_link(value):
        host, parts, _ = _parsed(value)
        if host.endswith(STORE_HOSTS) and len(parts) >= 2 and parts[0].lower() == "curator":
            value = unquote(parts[1])
        else:
            raise ValueError("curator link must be store.steampowered.com/curator/<id>-<name>")
    head = value.split("-", 1)[0]
    if head.isdigit() and _SLUG_RE.match(value):
        return value
    raise ValueError("curator must be a curator id (44944848), an id-name slug (44944848-Rock-Paper-Shotgun) or its store link")


# ---- market items -----------------------------------------------------------------------

def resolve_market_item(value):
    """-> {"app_id": int|None, "name": market hash name}."""
    value = (value or "").strip()
    if not value:
        raise ValueError("item must be a market hash name or a steamcommunity.com/market/listings/<appid>/<name> link")
    if _is_link(value) and "market/listings" in value.lower():
        host, parts, _ = _parsed(value)
        if host in COMMUNITY_HOSTS and len(parts) >= 4 and parts[0] == "market" and parts[1] == "listings" and parts[2].isdigit():
            return {"app_id": int(parts[2]), "name": unquote("/".join(parts[3:]))}
        raise ValueError("market link must be steamcommunity.com/market/listings/<appid>/<market hash name>")
    return {"app_id": None, "name": value}


# ---- links -----------------------------------------------------------------------------------

def app_link(app_id, slug=None):
    return f"https://store.steampowered.com/app/{app_id}/{slug}/" if slug else f"https://store.steampowered.com/app/{app_id}/"


def package_link(package_id):
    return f"https://store.steampowered.com/sub/{package_id}/"


def bundle_link(bundle_id, slug=None):
    return f"https://store.steampowered.com/bundle/{bundle_id}/{slug}/" if slug else f"https://store.steampowered.com/bundle/{bundle_id}/"


def profile_link(steamid):
    return f"https://steamcommunity.com/profiles/{steamid}/"


def file_link(file_id):
    return f"https://steamcommunity.com/sharedfiles/filedetails/?id={file_id}"


def group_link(name):
    return f"https://steamcommunity.com/groups/{name}"


def market_item_link(app_id, name):
    from urllib.parse import quote
    return f"https://steamcommunity.com/market/listings/{app_id}/{quote(name, safe='')}"


def community_app_link(app_id):
    return f"https://steamcommunity.com/app/{app_id}"
