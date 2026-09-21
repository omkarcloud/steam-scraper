"""Steam payload normalizers: raw store / Web API / community payloads ->
one clean snake_case shape per entity type.

Conventions: `link` for web URLs, images as absolute links, dates as
YYYY-MM-DD and timestamps as full UTC ISO datetimes, prices as numeric
`amount` (major units, e.g. 59.99) + separate `currency` code, percentages
as 0-100 numbers, `is_*` / `has_*` booleans, null for anything missing.

Upstream fields dropped on purpose (and why):
  * `success` / `visible` / `item_type` flags on GetItems rows (transport
    state; a row that failed is dropped, `type` names the item kind),
    `store_url_path` / `store_url_slug` (folded into `link`).
  * snr= tracking params on every store link, `data-ds-crtrids` creator
    clan ids on list rows, `hide_discount_pct_for_compliance` /
    `price_cannot_be_displayed_as_discount` / `user_can_purchase_as_gift`
    (store-UI switches), `formatted_*_price` strings (the numeric amount +
    currency carry the same value), `active_discounts[].discount_description`
    (a localisation token such as #discount_desc_preset_special).
  * asset hashes duplicated as `_2x` variants (retina copies of the same
    image), `page_background_path` / `raw_page_background` (CSS helpers),
    `last_modified` cache-buster, trailer `microtrailer` webm/mp4 loops
    (6-second hover previews) — full trailers keep their DASH/HLS links.
  * appdetails `capsule_imagev5` (same image as `capsule_image`),
    `background_raw` (unblurred copy of `background`), `package_groups[].
    save_text` / `selection_text` / `display_type` (purchase-box layout),
    `recommendations.total` (the same review count GetItems reports).
  * review `author.avatar` hash when no avatar exists, `reactions` (Steam
    points award ids with no names), `weighted_vote_score` kept as
    `helpfulness_score`.
  * inventory `rwgrsn` / `asset_properties` internals, `instanceid` "0",
    `currency` 0, market_actions steam:// inspect links (kept once as
    `inspect_link`).
"""
import html as _html
import re
from datetime import datetime, timezone

from steam import refs

ASSET_CDN = "https://shared.fastly.steamstatic.com/store_item_assets/"
STORE_CDN = "https://store.fastly.steamstatic.com/"
COMMUNITY_CDN = "https://shared.fastly.steamstatic.com/community_assets/images/apps/"
AVATAR_CDN = "https://avatars.fastly.steamstatic.com/"
ECON_IMAGE = "https://community.fastly.steamstatic.com/economy/image/"

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>|</p>\s*<p[^>]*>|</li>\s*<li[^>]*>|</h\d>|</div>", re.I)
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_SNR_RE = re.compile(r"[?&](snr|curator_clanid)=[^&#]*")
_NUMBER_RE = re.compile(r"-?\d[\d,.\s]*")

# EStoreAppType (GetItems `type`)
APP_TYPES = {0: "game", 1: "demo", 2: "mod", 3: "movie", 4: "dlc", 5: "guide", 6: "software", 7: "video",
             8: "series", 9: "episode", 10: "hardware", 11: "music", 12: "beta", 13: "tool", 14: "advertising"}
ITEM_KINDS = {0: "app", 1: "package", 2: "bundle", 3: "mtx", 4: "tag", 5: "creator", 6: "hub"}
DECK_COMPAT = {0: "unknown", 1: "unsupported", 2: "playable", 3: "verified"}
REVIEW_SCORE_LABELS = {1: "Overwhelmingly Negative", 2: "Very Negative", 3: "Negative", 4: "Mostly Negative",
                       5: "Mixed", 6: "Mostly Positive", 7: "Positive", 8: "Very Positive",
                       9: "Overwhelmingly Positive"}
# ELanguage (GetItems supported_languages[].elanguage)
ELANGUAGE = {0: "English", 1: "German", 2: "French", 3: "Italian", 4: "Korean", 5: "Spanish - Spain",
             6: "Simplified Chinese", 7: "Traditional Chinese", 8: "Russian", 9: "Thai", 10: "Japanese",
             11: "Portuguese - Portugal", 12: "Polish", 13: "Danish", 14: "Dutch", 15: "Finnish",
             16: "Norwegian", 17: "Swedish", 18: "Hungarian", 19: "Czech", 20: "Romanian", 21: "Turkish",
             22: "Portuguese - Brazil", 23: "Bulgarian", 24: "Greek", 25: "Arabic", 26: "Ukrainian",
             27: "Spanish - Latin America", 28: "Vietnamese", 29: "Indonesian"}
LINK_TYPES = {1: "youtube", 2: "facebook", 3: "x", 4: "twitch", 5: "discord", 6: "instagram", 7: "tiktok",
              8: "reddit", 9: "bluesky", 10: "website"}


# ---- value helpers -----------------------------------------------------------------------

def clean(value):
    """'' / [] / {} -> None (uniform nulls); strings are stripped."""
    if isinstance(value, str):
        value = value.strip()
    return None if value in ("", [], {}, None) else value


def plain(value):
    """Plain text with Windows line endings normalised."""
    value = clean(value)
    if isinstance(value, str):
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    return clean(value)


_BB_TAG_RE = re.compile(r"\[/?(?:b|i|u|strike|spoiler|noparse|hr|code|quote[^\]]*|table[^\]]*|tr|td|th|"
                        r"olist|list|previewyoutube[^\]]*|video[^\]]*|dynamiclink[^\]]*|expand[^\]]*|c|"
                        r"carousel|img[^\]]*|url[^\]]*|emoticon[^\]]*|color[^\]]*|size[^\]]*)\]", re.I)
_BB_BLOCK_RE = re.compile(r"\[/?(?:p|h\d|list|olist)\]|\[/tr\]", re.I)
_BB_IMG_RE = re.compile(r"\[img[^\]]*\].*?\[/img\]|\[previewyoutube[^\]]*\].*?\[/previewyoutube\]|"
                        r"\[video[^\]]*\].*?\[/video\]", re.I | re.S)
_BB_ITEM_RE = re.compile(r"\[\*\]\s*")
_CLAN_IMAGE_RE = re.compile(r"\{STEAM_CLAN_IMAGE\}\S*|\{STEAM_CLAN_LOC_IMAGE\}\S*")


def bbcode_to_text(value):
    """Steam BBCode (news / events / workshop descriptions) -> readable
    plain text: block tags become line breaks, list items bullets, images
    and embedded videos are dropped, link tags keep their text."""
    if not value:
        return None
    text = str(value)
    text = _BB_IMG_RE.sub("", text)
    text = _CLAN_IMAGE_RE.sub("", text)
    text = _BB_ITEM_RE.sub("\n• ", text)
    text = _BB_BLOCK_RE.sub("\n", text)
    text = _BB_TAG_RE.sub("", text)
    if "<" in text and ">" in text:
        out = html_to_text(text.replace("\n", "<br>"))
    else:
        out = html_to_text(_html.escape(text, quote=False).replace("\n", "<br>"))
    return re.sub(r"\n\s*\n(?=• )", "\n", out) if out else None


def to_int(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        text = str(value).strip().replace(",", "")
        return int(float(text)) if text not in ("", "None") else None
    except (TypeError, ValueError):
        return None


def to_float(value, digits=2):
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return round(number, digits) if digits is not None else number


def to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("1", "true", "yes"):
        return True
    if text in ("0", "false", "no", ""):
        return False
    return None


def number_in(text):
    """First number in a display string ('28,455 ratings' -> 28455)."""
    if not text:
        return None
    match = _NUMBER_RE.search(str(text))
    if not match:
        return None
    raw = match.group(0).replace(",", "").replace(" ", "").strip(".")
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return None


def iso_datetime(timestamp):
    """Unix seconds -> '2026-09-21T10:12:00Z' (None for 0 / missing)."""
    ts = to_int(timestamp)
    if not ts or ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def iso_date(timestamp):
    ts = to_int(timestamp)
    if not ts or ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return None


_DATE_FORMATS = ("%b %d, %Y", "%d %b, %Y", "%B %d, %Y", "%d %B, %Y", "%b %Y", "%B %Y", "%Y-%m-%d",
                 "%d %b %Y", "%b %d %Y")


def parse_date_text(text):
    """Store display dates ('Feb 24, 2022', '24 Feb, 2022', 'August 6, 2020')
    -> 'YYYY-MM-DD'; month-only dates -> 'YYYY-MM'; anything else (Coming
    soon, Q3 2026, To be announced) -> None."""
    text = clean(text)
    if not text:
        return None
    text = text.replace("Released:", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.strftime("%Y-%m") if "%d" not in fmt else parsed.strftime("%Y-%m-%d")
    return None


_STEAM_DT_RE = re.compile(r"(?P<a>\d{1,2}\s+[A-Za-z]+|[A-Za-z]+\s+\d{1,2})(?:,?\s*(?P<year>\d{4}))?"
                          r"(?:\s*@\s*(?P<time>\d{1,2}:\d{2}\s*[ap]m))?", re.I)


def community_date(text, today=None):
    """Community-page dates ('30 Aug @ 6:04am', '25 Oct, 2012 @ 8:41pm',
    'Posted 20 September.', 'September 21', 'Aug 27, 2026') -> 'YYYY-MM-DD'.
    A date without a year is this year (last year when that would be in
    the future). Times are dropped: Steam renders them in the viewer's
    timezone, unknown for anonymous visitors."""
    text = clean(text)
    if not text:
        return None
    text = re.sub(r"^(?:posted|updated|last edited|released|unlocked)\s*:?\s*", "", text, flags=re.I).strip().rstrip(".")
    iso = parse_date_text(text)
    if iso and len(iso) == 10:
        return iso
    match = _STEAM_DT_RE.search(text)
    if not match:
        return None
    part = " ".join(match.group("a").replace(",", " ").split())
    today = today or datetime.now(timezone.utc).date()
    for fmt in ("%d %b", "%d %B", "%b %d", "%B %d"):
        try:
            parsed = datetime.strptime(part, fmt)
        except ValueError:
            continue
        year = int(match.group("year")) if match.group("year") else today.year
        try:
            day = parsed.replace(year=year).date()
        except ValueError:
            return None
        if not match.group("year") and day > today:
            day = day.replace(year=year - 1)
        return day.isoformat()
    return None


def html_to_text(value):
    """HTML fragment -> readable plain text (block tags become newlines)."""
    if not value:
        return None
    text = _BR_RE.sub("\n", str(value))
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    lines = [_WS_RE.sub(" ", line).strip() for line in text.split("\n")]
    out, blank = [], False
    for line in lines:
        if not line:
            if out and not blank:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    return clean("\n".join(out).strip())


def strip_snr(link):
    if not link:
        return None
    link = _SNR_RE.sub("", str(link))
    if "?" not in link and "&" in link:
        link = link.replace("&", "?", 1)
    return link.rstrip("?")


def money(cents, currency, digits=2):
    """Minor units -> major-unit number (5999 -> 59.99)."""
    value = to_float(cents, None)
    if value is None:
        return None
    return round(value / 100, digits)


def price_block(final_cents, original_cents=None, discount_percent=None, currency=None, discount_ends_at=None,
                is_free=False):
    """The one price shape every endpoint returns (null when not sold)."""
    final = money(final_cents, currency)
    if final is None:
        if is_free:
            return {"amount": 0.0, "original_amount": 0.0, "discount_percent": 0, "currency": currency,
                    "is_free": True, "discount_ends_at": None}
        return None
    original = money(original_cents, currency) if original_cents not in (None, "", 0, "0") else final
    discount = to_int(discount_percent) or 0
    if not discount and original and original > final:
        discount = round((original - final) * 100 / original)
    return {"amount": final, "original_amount": original, "discount_percent": discount,
            "currency": currency, "is_free": final == 0, "discount_ends_at": iso_datetime(discount_ends_at)}


def asset(format_string, filename):
    """GetItems asset_url_format + file name -> absolute CDN link."""
    if not filename:
        return None
    if str(filename).startswith("http"):
        return filename
    if format_string and "${FILENAME}" in format_string:
        return ASSET_CDN + format_string.replace("${FILENAME}", filename)
    return ASSET_CDN + str(filename)


def avatar(hash_or_link, size="full"):
    """Avatar hash -> absolute link (size: small | medium | full)."""
    value = clean(hash_or_link)
    if not value or set(str(value)) == {"0"}:
        return None
    if str(value).startswith("http"):
        return value
    suffix = {"small": "", "medium": "_medium", "full": "_full"}[size]
    return f"{AVATAR_CDN}{value}{suffix}.jpg"


def econ_image(icon_hash, size=None):
    if not icon_hash:
        return None
    if str(icon_hash).startswith("http"):
        return icon_hash
    return ECON_IMAGE + icon_hash + (f"/{size}" if size else "")


def review_label(score):
    return REVIEW_SCORE_LABELS.get(to_int(score))


def split_camel(token):
    """'#SteamDeckVerified_TestResult_DefaultControllerConfigFullyFunctional'
    -> 'Default controller config fully functional'."""
    if not token:
        return None
    tail = str(token).lstrip("#").split("_")[-1]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", tail).split()
    if not words:
        return None
    text = " ".join(w if w.isupper() and len(w) > 1 else w.lower() for w in words)
    return text[0].upper() + text[1:]


# ---- GetItems store items -> cards ---------------------------------------------------------

def _review_summary(block):
    if not isinstance(block, dict):
        return None
    total = to_int(block.get("review_count"))
    if not total:
        return None
    return {"score": to_int(block.get("review_score")), "label": clean(block.get("review_score_label")),
            "total": total, "percent_positive": to_int(block.get("percent_positive"))}


def item_link(item):
    path = clean(item.get("store_url_path"))
    if path:
        return f"https://store.steampowered.com/{path}/"
    kind = ITEM_KINDS.get(item.get("item_type"), "app")
    item_id = item.get("id")
    if kind == "package":
        return refs.package_link(item_id)
    if kind == "bundle":
        return refs.bundle_link(item_id)
    return refs.app_link(item_id)


def purchase_price(option, currency):
    if not isinstance(option, dict):
        return None
    ends = None
    for disc in option.get("active_discounts") or []:
        if isinstance(disc, dict) and disc.get("discount_end_date"):
            ends = disc["discount_end_date"]
    return price_block(option.get("final_price_in_cents"), option.get("original_price_in_cents"),
                       option.get("discount_pct"), currency, ends)


def item_images(item):
    assets = item.get("assets") or {}
    fmt = assets.get("asset_url_format")
    icon = assets.get("community_icon")
    app_id = item.get("appid") or item.get("id")
    return {
        "header": asset(fmt, assets.get("header")),
        "capsule": asset(fmt, assets.get("main_capsule")),
        "capsule_small": asset(fmt, assets.get("small_capsule")),
        "hero": asset(fmt, assets.get("hero_capsule")),
        "library": asset(fmt, assets.get("library_capsule")),
        "library_hero": asset(fmt, assets.get("library_hero")),
        "icon": f"{COMMUNITY_CDN}{app_id}/{icon}.jpg" if icon and app_id else None,
    } if assets else None


def platforms(block):
    block = block or {}
    vr = block.get("vr_support") or {}
    return {
        "windows": bool(block.get("windows")),
        "mac": bool(block.get("mac")),
        "linux": bool(block.get("steamos_linux") or block.get("linux")),
        "steam_deck_compatibility": DECK_COMPAT.get(block.get("steam_deck_compat_category")),
        "is_vr_supported": bool(vr.get("vrhmd") or vr.get("vrhmd_only")) if vr else False,
        "is_vr_only": bool(vr.get("vrhmd_only")) if vr else False,
    }


def store_item(item, currency=None, tag_names=None):
    """A GetItems row -> the shared game/package/bundle card (None when the
    row failed or is hidden)."""
    if not isinstance(item, dict) or item.get("success") not in (1, None) or not item.get("id"):
        return None
    tag_names = tag_names or {}
    kind = ITEM_KINDS.get(item.get("item_type"), "app")
    basic = item.get("basic_info") or {}
    release = item.get("release") or {}
    reviews = item.get("reviews") or {}
    is_free = bool(item.get("is_free"))
    price = purchase_price(item.get("best_purchase_option"), currency)
    if price is None and is_free:
        price = price_block(None, currency=currency, is_free=True)
    tags = []
    for t in item.get("tags") or []:
        if isinstance(t, dict) and t.get("tagid") is not None:
            name = tag_names.get(t["tagid"])
            if name:
                tags.append(name)
    if not tags:
        tags = [tag_names[t] for t in item.get("tagids") or [] if t in tag_names]
    coming = release.get("is_coming_soon")
    return {
        "id": item.get("id"),
        "type": APP_TYPES.get(item.get("type"), "game") if kind == "app" else kind,
        "name": clean(item.get("name")),
        "link": item_link(item),
        "short_description": plain(basic.get("short_description")),
        "release_date": iso_date(release.get("steam_release_date") or release.get("original_release_date")),
        "release_date_text": clean(release.get("custom_release_date_message")),
        "is_coming_soon": bool(coming),
        "is_early_access": bool(item.get("is_early_access")),
        "is_free": is_free or (price or {}).get("is_free") is True,
        "price": price,
        "reviews": _review_summary(reviews.get("summary_filtered")),
        "tags": tags or None,
        "developers": [clean(d.get("name")) for d in basic.get("developers") or [] if clean(d.get("name"))] or None,
        "publishers": [clean(p.get("name")) for p in basic.get("publishers") or [] if clean(p.get("name"))] or None,
        "platforms": platforms(item.get("platforms")) if item.get("platforms") else None,
        "images": item_images(item),
        "parent_app_id": to_int((item.get("related_items") or {}).get("parent_appid")),
        "included_app_ids": item.get("included_appids") or None,
    }


def compact(block):
    """A dict whose values are all None -> None."""
    if isinstance(block, dict) and all(v is None for v in block.values()):
        return None
    return block


def numbered(cards, start=1, key="rank"):
    out = []
    for i, card in enumerate(cards, start):
        if card is None:
            continue
        out.append({key: i, **card})
    return out


# ---- store HTML list rows ---------------------------------------------------------------------

_ROW_ID_RE = re.compile(r'data-ds-itemkey="(App|Sub|Bundle)_(\d+)"')


def item_keys_in(html_text):
    """Ordered (kind, id) pairs from store list HTML (search results,
    creator / curator catalogs, morelike grids), de-duplicated."""
    seen, out = set(), []
    for kind, item_id in _ROW_ID_RE.findall(html_text or ""):
        key = ({"App": "appid", "Sub": "packageid", "Bundle": "bundleid"}[kind], int(item_id))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


# ---- reviews ------------------------------------------------------------------------------------

def review(raw, app_id=None):
    """An appreviews row -> review."""
    if not isinstance(raw, dict) or not raw.get("recommendationid"):
        return None
    author = raw.get("author") or {}
    steamid = clean(author.get("steamid"))
    rid = raw["recommendationid"]
    return {
        "id": str(rid),
        "link": f"https://steamcommunity.com/profiles/{steamid}/recommended/{app_id}/" if steamid and app_id else None,
        "is_recommended": bool(raw.get("voted_up")),
        "text": clean(raw.get("review")),
        "language": clean(raw.get("language")),
        "created_at": iso_datetime(raw.get("timestamp_created")),
        "updated_at": iso_datetime(raw.get("timestamp_updated")),
        "votes_helpful": to_int(raw.get("votes_up")) or 0,
        "votes_funny": to_int(raw.get("votes_funny")) or 0,
        "helpfulness_score": to_float(raw.get("weighted_vote_score"), 4),
        "comment_count": to_int(raw.get("comment_count")) or 0,
        "is_steam_purchase": bool(raw.get("steam_purchase")),
        "is_received_for_free": bool(raw.get("received_for_free")),
        "is_refunded": bool(raw.get("refunded")),
        "is_written_during_early_access": bool(raw.get("written_during_early_access")),
        "is_primarily_steam_deck": bool(raw.get("primarily_steam_deck")),
        "developer_response": clean(raw.get("developer_response")),
        "developer_responded_at": iso_datetime(raw.get("timestamp_dev_responded")),
        "author": {
            "steamid": steamid,
            "name": clean(author.get("personaname")),
            "link": clean(author.get("profile_url")) or (refs.profile_link(steamid) if steamid else None),
            "avatar": avatar(author.get("avatar")),
            "games_owned": to_int(author.get("num_games_owned")),
            "reviews_written": to_int(author.get("num_reviews")),
            "playtime_hours": minutes_to_hours(author.get("playtime_forever")),
            "playtime_last_two_weeks_hours": minutes_to_hours(author.get("playtime_last_two_weeks")),
            "playtime_at_review_hours": minutes_to_hours(author.get("playtime_at_review")),
            "playtime_steam_deck_hours": minutes_to_hours(author.get("deck_playtime_at_review")),
            "last_played_at": iso_datetime(author.get("last_played")),
        },
    }


def minutes_to_hours(minutes):
    value = to_float(minutes, None)
    if value is None:
        return None
    return round(value / 60, 1)


def review_query_summary(summary):
    if not isinstance(summary, dict) or summary.get("total_reviews") is None:
        return None
    total = to_int(summary.get("total_reviews")) or 0
    positive = to_int(summary.get("total_positive")) or 0
    return {
        "score": to_int(summary.get("review_score")),
        "label": clean(summary.get("review_score_desc")),
        "total": total,
        "positive": positive,
        "negative": to_int(summary.get("total_negative")) or 0,
        "percent_positive": round(positive * 100 / total) if total else None,
    }


# ---- market ------------------------------------------------------------------------------------------

def market_link(app_id, name):
    return refs.market_item_link(app_id, name) if app_id and name else None


def market_description(desc):
    """An econ asset description -> the item's descriptive block."""
    if not isinstance(desc, dict):
        return None
    lines = []
    for d in desc.get("descriptions") or []:
        if isinstance(d, dict):
            text = html_to_text(d.get("value"))
            if text and text.strip():
                lines.append(text)
    tags = []
    for t in desc.get("tags") or []:
        if isinstance(t, dict):
            tags.append({"category": clean(t.get("localized_category_name") or t.get("category")),
                         "name": clean(t.get("localized_tag_name") or t.get("name")),
                         "color": ("#" + t["color"]) if clean(t.get("color")) else None})
    inspect = None
    for action in (desc.get("market_actions") or desc.get("actions") or []):
        if isinstance(action, dict) and "inspect" in str(action.get("name", "")).lower():
            inspect = clean(action.get("link"))
    return {
        "class_id": clean(str(desc.get("classid"))) if desc.get("classid") is not None else None,
        "name": clean(desc.get("market_name") or desc.get("name")),
        "hash_name": clean(desc.get("market_hash_name")),
        "type": clean(desc.get("type")),
        "name_color": ("#" + desc["name_color"]) if clean(desc.get("name_color")) else None,
        "background_color": ("#" + desc["background_color"]) if clean(desc.get("background_color")) else None,
        "image": econ_image(desc.get("icon_url_large") or desc.get("icon_url")),
        "description": "\n".join(lines) or None,
        "tags": tags or None,
        "is_tradable": to_bool(desc.get("tradable")),
        "is_marketable": to_bool(desc.get("marketable")),
        "is_commodity": to_bool(desc.get("commodity")),
        "trade_restriction_days": to_int(desc.get("market_tradable_restriction")),
        "inspect_link": inspect,
    }


# ---- community HTML helpers ------------------------------------------------------------------------------

def text_between(html_text, start_marker, end_marker="</div>"):
    """Inner text between the first `start_marker` and the next `end_marker`."""
    if not html_text:
        return None
    i = html_text.find(start_marker)
    if i < 0:
        return None
    i += len(start_marker)
    j = html_text.find(end_marker, i)
    if j < 0:
        return None
    return html_to_text(html_text[i:j])


def inner(html_text, css_class, tag="div"):
    """Text of the first <tag class="css_class …"> element (class may carry
    extra names or trailing spaces), up to its first closing tag."""
    match = re.search(r'<' + tag + r'[^>]*\bclass="' + re.escape(css_class) + r'(?:\s[^"]*)?"[^>]*>(.*?)</' + tag + '>',
                      html_text or "", re.S)
    return html_to_text(match.group(1)) if match else None


def attr(fragment, name):
    match = re.search(r'\b' + re.escape(name) + r'="([^"]*)"', fragment or "")
    return _html.unescape(match.group(1)) if match else None
