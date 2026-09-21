"""Steam creators and curators: the catalogue of a developer / publisher /
franchise store page, the top curators list, and a curator's reviews."""
import json
import re
from urllib.parse import quote, urlencode

from steam import fetch, refs
from steam import parsers as P
from steam.shared import app_cards, key_cards, paged_result, start_of

CREATOR_KINDS = ("developer", "publisher", "franchise")
RECOMMENDATION_STATES = {0: "recommended", 1: "not_recommended", 2: "informational"}
_TOP_CURATORS_RE = re.compile(r"g_rgTopCurators\s*=\s*(\[.*?\]);\s*\n", re.S)
_REC_SPLIT_RE = re.compile(r'<div data-panel="[^"]*" role="button" class="recommendation"\s*>')


def _catalog(kind, slug, query, start, count, country, language):
    # a slug unquoted from a link may carry spaces, which curl rejects in a path; the
    # query goes into the URL too because curl_cffi unquotes the whole URL when params= is set
    qs = urlencode({"query": query or "", "start": start, "count": count, "cc": (country or "US").upper(),
                    "l": language or "english"})
    return fetch.store_json(f"{kind}/{quote(slug, safe='%')}/ajaxgetfilteredrecommendations/?{qs}",
                            not_found=f"{kind} {slug}")


def games(creator, page=1, limit=24, country=None, language=None):
    """Every product on a developer / publisher / franchise store page,
    newest first, as full cards. A bare slug is tried as a developer, then
    a publisher, then a franchise."""
    kinds = [creator["kind"]] if creator.get("kind") else list(CREATOR_KINDS)
    body, found = None, None
    for kind in kinds:
        try:
            body = _catalog(kind, creator["slug"], None, start_of(page, limit), limit, country, language)
        except fetch.SteamNotFound:
            continue
        if isinstance(body, dict) and body.get("success") == 1 and (P.to_int(body.get("total_count")) or kind == kinds[-1]):
            found = kind
            break
    if not found or not isinstance(body, dict):
        raise fetch.SteamNotFound(f"no Steam developer, publisher or franchise page named {creator['slug']}")
    keys = P.item_keys_in(body.get("results_html"))
    results = key_cards(keys, country, language)
    return paged_result("results", results, page, limit, total=P.to_int(body.get("total_count")),
                        creator={"type": found, "slug": creator["slug"],
                                 "link": f"https://store.steampowered.com/{found}/{creator['slug']}"})


# ---- curators ---------------------------------------------------------------------------------------------

def _curator(c):
    if not isinstance(c, dict) or not c.get("clanID"):
        return None
    recs = []
    for r in c.get("m_rgAppRecommendations") or []:
        if isinstance(r, dict) and r.get("appid"):
            recs.append({"game_id": P.to_int(r.get("appid")), "game_link": refs.app_link(r.get("appid")),
                         "verdict": RECOMMENDATION_STATES.get(r.get("recommendation_state"), "recommended"),
                         "text": P.html_to_text(r.get("blurb")), "review_link": P.clean(r.get("link_url")),
                         "recommended_at": P.iso_datetime(r.get("time_recommended")),
                         "was_received_for_free": bool(r.get("received_for_free"))})
    return {
        "id": P.to_int(c.get("clanID")),
        "name": P.clean(c.get("name")),
        "link": P.clean(c.get("link")),
        "description": P.html_to_text(c.get("curator_description")),
        "avatar": P.avatar(c.get("strAvatarHash")),
        "followers": P.to_int(c.get("total_followers")),
        "reviews": P.to_int(c.get("total_reviews")),
        "recommended": P.to_int(c.get("total_recommended")),
        "not_recommended": P.to_int(c.get("total_not_recommended")),
        "informational": P.to_int(c.get("total_informative")),
        "last_review_at": P.iso_datetime(c.get("last_curation_date")),
        "community_link": P.clean(c.get("communityLink")),
        "discussion_link": P.clean(c.get("discussion_url")),
        "recent_reviews": recs or None,
    }


def curators(page=1, limit=20, language=None):
    """Steam curators ranked by followers, with their review totals and
    latest reviews."""
    body = fetch.store_json("curators/ajaxgetcurators/render/", {"start": start_of(page, limit), "count": limit,
                                                                "l": language or "english"})
    if not isinstance(body, dict) or not body.get("success"):
        raise fetch.SteamUpstreamError("curators list: unexpected answer")
    match = _TOP_CURATORS_RE.search(body.get("results_html") or "")
    rows = []
    if match:
        try:
            rows = [c for c in (_curator(x) for x in json.loads(match.group(1))) if c]
        except ValueError:
            rows = []
    return paged_result("curators", rows[:limit], page, limit, total=P.to_int(body.get("total_count")))


def _recommendation(block):
    ids = re.findall(r'data-ds-appid="(\d+)"', block)
    if not ids:
        return None
    verdict = "recommended"
    if "color_informational" in block:
        verdict = "informational"
    elif "color_not_recommended" in block:
        verdict = "not_recommended"
    return {"game_id": int(ids[0]),
            "verdict": verdict,
            "date": P.community_date(P.text_between(block, '<span class="curator_review_date">', "</span>")),
            "text": P.text_between(block, '<div class="recommendation_desc">', "</div>"),
            "review_link": P.attr(block[block.find('recommendation_readmore'):], "href")
            if "recommendation_readmore" in block else None}


def curator_reviews(curator, page=1, limit=20, country=None, language=None):
    """One curator's reviews (verdict, blurb, link to the full review),
    newest first, each with the reviewed game's card."""
    curator_id = curator.split("-", 1)[0]
    body = fetch.store_json(f"curator/{curator_id}/ajaxgetfilteredrecommendations/",
                            {"query": "", "start": start_of(page, limit), "count": limit,
                             "cc": (country or "US").upper(), "l": language or "english"},
                            not_found=f"curator {curator}")
    if not isinstance(body, dict) or body.get("success") != 1:
        raise fetch.SteamNotFound(f"curator {curator} not found")
    total = P.to_int(body.get("total_count")) or 0
    if total == 0 and page == 1:
        raise fetch.SteamNotFound(f"curator {curator} not found or has no reviews")
    recs = [r for r in (_recommendation(b) for b in _REC_SPLIT_RE.split(body.get("results_html") or "")[1:]) if r]
    by_id = {c["id"]: c for c in app_cards([r["game_id"] for r in recs], country, language)}
    rows = []
    for r in recs:
        rows.append({"verdict": r["verdict"], "text": r["text"], "date": r["date"],
                     "review_link": P.strip_snr(r["review_link"]), "game": by_id.get(r["game_id"])
                     or {"id": r["game_id"], "link": refs.app_link(r["game_id"])}})
    return paged_result("reviews", rows, page, limit, total=total,
                        curator={"id": P.to_int(curator_id),
                                 "link": f"https://store.steampowered.com/curator/{curator}/"})
