"""Steam Community content about a game: guides (list + full guide),
discussion topics, the Workshop (browse, item details, collections) —
steamcommunity.com server-rendered pages plus the keyless
ISteamRemoteStorage published-file POSTs."""
import html as _html
import json
import re

from steam import fetch, refs
from steam import parsers as P
from steam.shared import paged_result

GUIDE_SORTS = {"trending": "trend", "top_rated": "toprated", "most_recent": "mostrecent"}
GUIDE_PAGE_SIZE = 30
WORKSHOP_SORTS = {"trending": "trend", "top_rated": "toprated", "most_recent": "mostrecent",
                  "last_updated": "lastupdated", "most_subscribed": "totaluniquesubscribers"}
WORKSHOP_PERIODS = {"today": 1, "week": 7, "month": 30, "three_months": 90, "six_months": 180, "year": 365,
                    "all_time": -1}
WORKSHOP_PAGE_SIZE = 30
DISCUSSION_PAGE_SIZE = 15
FILE_BATCH = 100
RATING_STARS = {"1-star": 1, "2-star": 2, "3-star": 3, "4-star": 4, "5-star": 5}

_PAGING_RE = re.compile(r"Showing\s+([\d,]+)\s*-\s*([\d,]+)\s+of\s+([\d,]+)", re.I)
_GUIDE_BLOCK_RE = re.compile(r'class="workshopItemCollectionContainer">(.*?)<div class="workshopItemClear"', re.S)
_HOVER_RE = re.compile(r'SharedFileBindMouseHover\(\s*"[^"]+",\s*(?:true|false),\s*(\{.*?\})\s*\);', re.S)
_TOPIC_RE = re.compile(r'<div[^>]*class="forum_topic\s[^"]*"[^>]*data-gidforumtopic="(\d+)"(.*?)'
                       r'<div style="clear: both;"></div>\s*</div>', re.S)


def _stars(fragment):
    match = re.search(r"sharedfiles/(\d-star|not-yet)(?:_large)?\.png", fragment or "")
    return RATING_STARS.get(match.group(1)) if match else None


def _paging_total(html_text):
    match = _PAGING_RE.search(html_text or "")
    return P.to_int(match.group(3)) if match else None


# ---- guides ---------------------------------------------------------------------------------------------------

def guides(game, sort="trending", query=None, category=None, page=1, language=None):
    """Community guides for a game: title, author, summary, star rating,
    30 per page, with the total count."""
    params = {"browsefilter": GUIDE_SORTS[sort], "p": page, "l": language or "english"}
    if query:
        params["searchText"] = query
    if category:
        params["requiredtags[]"] = category
    html_text = fetch.community_page(f"app/{game}/guides/", params, not_found=f"app {game}")
    hover = {}
    for raw in _HOVER_RE.findall(html_text):
        try:
            data = json.loads(raw)
            hover[str(data.get("id"))] = data
        except ValueError:
            continue
    rows = []
    for block in _GUIDE_BLOCK_RE.findall(html_text):
        file_id = P.attr(block, "data-publishedfileid")
        if not file_id:
            continue
        info = hover.get(file_id, {})
        rows.append({
            "id": int(file_id),
            "title": P.text_between(block, 'class="workshopItemTitle">') or P.clean(_html.unescape(info.get("title") or "")),
            "link": refs.file_link(file_id),
            "author": P.text_between(block, 'class="workshopItemAuthorName">', "</span>"),
            "summary": P.text_between(block, 'class="workshopItemShortDesc">') or P.html_to_text(info.get("description")),
            "rating_stars": _stars(block),
            "image": _full_image(P.attr(block[block.find("workshopItemPreviewImage"):], "src"))
            if "workshopItemPreviewImage" in block else None,
        })
    total = _paging_total(html_text)
    if total is None and not rows and page == 1 and "workshopBrowseItems" not in html_text:
        raise fetch.SteamNotFound(f"app {game} has no community guides hub")
    return paged_result("guides", rows, page, GUIDE_PAGE_SIZE, total=total or (0 if not rows else None),
                        game_id=game)


def _full_image(link):
    """Drop the letterbox resize params so the link serves the original image."""
    if not link:
        return None
    return link.split("?")[0]


def _stats_table(html_text):
    stats = {}
    for value, label in re.findall(r"<tr>\s*<td>([\d,]+)</td>\s*<td>([^<]+)</td>\s*</tr>", html_text or ""):
        stats[re.sub(r"[^a-z]+", "_", label.strip().lower()).strip("_")] = P.to_int(value)
    return stats


def _details_dates(html_text):
    """The 'Posted' / 'Updated' (and 'File Size') rows of a sharedfile page."""
    labels = re.findall(r'<div class="detailsStatLeft">([^<]*)</div>', html_text or "")
    values = re.findall(r'<div class="detailsStatRight">([^<]*)</div>', html_text or "")
    out = {}
    for label, value in zip(labels, values):
        out[label.strip().rstrip(":").lower()] = value.strip()
    if not labels and values:
        # guides render values without left labels: posted, then updated
        out["posted"] = values[0]
        if len(values) > 1:
            out["updated"] = values[1]
    return out


def _tags_groups(html_text):
    groups = {}
    for block in re.findall(r'<div[^>]*class="workshopTags">(.*?)</div>', html_text or "", re.S):
        title = P.text_between(block, '<span class="workshopTagsTitle">', "</span>")
        names = [P.html_to_text(n) for n in re.findall(r"<a [^>]*>(.*?)</a>", block)]
        if title:
            groups[re.sub(r"[^a-z]+", "_", title.replace("&nbsp;", "").rstrip(":").lower()).strip("_")] = [n for n in names if n]
    return groups


def _comment_count(html_text):
    match = re.search(r'_totalcount">([\d,]+)</span>', html_text or "")
    return P.to_int(match.group(1)) if match else None


def _rating_count(html_text):
    match = re.search(r'<div class="numRatings">([^<]+)</div>', html_text or "")
    return P.number_in(match.group(1)) if match else None


def _creators(html_text):
    """The 'Created by' friend blocks of a sharedfile page -> [{name, link}]."""
    out = []
    for link, name in re.findall(r'<a class="friendBlockLinkOverlay" href="([^"]+)"></a>.*?<div class="friendBlockContent">\s*(.*?)<br>',
                                 html_text or "", re.S):
        entry = {"name": P.html_to_text(name), "link": link}
        if entry not in out:
            out.append(entry)
    return out


def guide(guide):
    """A full community guide: every section's text, author, rating,
    visitor / favourite counts, category tags and dates."""
    html_text = fetch.community_page("sharedfiles/filedetails/", {"id": guide, "l": "english"},
                                     not_found=f"guide {guide}")
    title = P.text_between(html_text, '<div class="workshopItemTitle">')
    if not title:
        raise fetch.SteamNotFound(f"guide {guide} not found")
    sections = []
    for sec_title, body in re.findall(r'<div class="subSectionTitle">(.*?)</div>\s*<div class="subSectionDesc">(.*?)</div>\s*'
                                      r'(?=<div style="clear: both"|</div>|<div class="subSection)', html_text, re.S):
        sections.append({"title": P.html_to_text(sec_title), "content": P.html_to_text(body)})
    app_match = re.search(r'steamcommunity\.com/app/(\d+)', html_text)
    dates = _details_dates(html_text)
    stats = _stats_table(html_text)
    tags = _tags_groups(html_text)
    authors = P.text_between(html_text, '<div class="guideAuthors">')
    creators = _creators(html_text)
    return {
        "id": guide,
        "title": title,
        "link": refs.file_link(guide),
        "description": P.text_between(html_text, '<div class="guideTopDescription" id="highlightContent">'),
        "game_id": P.to_int(app_match.group(1)) if app_match else None,
        "authors": creators or ([{"name": authors.replace("By ", "", 1), "link": None}] if authors else None),
        "categories": tags.get("category"),
        "languages": tags.get("languages"),
        "posted_on": P.community_date(dates.get("posted")),
        "updated_on": P.community_date(dates.get("updated")),
        "rating_stars": _stars(html_text[html_text.find("ratingSection"):] if "ratingSection" in html_text else ""),
        "rating_count": _rating_count(html_text),
        "unique_visitors": stats.get("unique_visitors"),
        "favorites": stats.get("current_favorites"),
        "comment_count": _comment_count(html_text),
        "image": _full_image(P.attr(html_text[html_text.find('class="guidePreviewImage"'):], "src"))
        if 'class="guidePreviewImage"' in html_text else None,
        "sections": sections or None,
    }


# ---- discussions -----------------------------------------------------------------------------------------------

def discussions(game, page=1, language=None):
    """The game's General Discussions topics (newest activity first): title,
    opening-post snippet, author, reply count and last-post time."""
    html_text = fetch.community_page(f"app/{game}/discussions/0/", {"fp": page, "l": language or "english"},
                                     not_found=f"app {game}")
    rows = []
    for topic_id, block in _TOPIC_RE.findall(html_text):
        tip_match = re.search(r'data-tooltip-forum="(.*?)"\s*>', block, re.S)
        tip = _html.unescape(tip_match.group(1)) if tip_match else ""
        link_match = re.search(r'class="forum_topic_overlay" href="([^"]+)"', block)
        last = re.search(r'data-timestamp="(\d+)"', block)
        rows.append({
            "id": topic_id,
            "title": P.text_between(block, 'class="forum_topic_name', "</div>").lstrip('"> ').strip()
            if 'forum_topic_name' in block else None,
            "link": link_match.group(1) if link_match else None,
            "snippet": P.text_between(tip, 'class="topic_hover_text">'),
            "author": P.text_between(block, '<div class="forum_topic_op">'),
            "reply_count": P.number_in(P.text_between(block, '<div class="forum_topic_reply_count">')) or 0,
            "last_post_at": P.iso_datetime(last.group(1)) if last else None,
            "last_post_author": _last_poster(tip),
            "is_pinned": "sticky" in block[:400] or "forum_icon_Sticky" in block,
            "is_locked": "locked" in block[:400] or "forum_icon_Locked" in block,
            "is_answered": "forum_icon_Answered" in block or "answered" in block[:400],
        })
    for r in rows:
        if r["title"]:
            r["title"] = P.html_to_text(r["title"].split(">", 1)[-1]) if ">" in r["title"] else r["title"]
    total = None
    match = re.search(r'_pagetotal">([\d,]+)<', html_text)
    if match:
        total = P.to_int(match.group(1))
    if not rows and total is None and page == 1:
        raise fetch.SteamNotFound(f"app {game} has no discussions forum")
    return paged_result("topics", rows, page, DISCUSSION_PAGE_SIZE, total=total, game_id=game)


def _last_poster(tip):
    match = re.search(r"Last post:\s*<span class=\"topic_hover_data\">(.*?)</span>", tip or "", re.S)
    return P.html_to_text(match.group(1)) if match else None


# ---- workshop ------------------------------------------------------------------------------------------------------

def file_details(ids):
    """ISteamRemoteStorage/GetPublishedFileDetails (keyless POST) for up to
    FILE_BATCH ids per call -> {id: raw row} (only rows that resolved)."""
    ids = [str(i) for i in ids]
    out = {}
    for start in range(0, len(ids), FILE_BATCH):
        chunk = ids[start:start + FILE_BATCH]
        form = {"itemcount": len(chunk)}
        for i, file_id in enumerate(chunk):
            form[f"publishedfileids[{i}]"] = file_id
        body = fetch.webapi_post("ISteamRemoteStorage", "GetPublishedFileDetails", 1, form)
        for row in (body or {}).get("publishedfiledetails") or []:
            if isinstance(row, dict) and row.get("result") == 1:
                out[str(row.get("publishedfileid"))] = row
    return out


def workshop_file(row):
    """A GetPublishedFileDetails row -> workshop item."""
    if not isinstance(row, dict):
        return None
    file_id = P.to_int(row.get("publishedfileid"))
    creator = P.clean(row.get("creator"))
    size = P.to_int(row.get("file_size"))
    return {
        "id": file_id,
        "title": P.clean(row.get("title")),
        "link": refs.file_link(file_id),
        "description": P.bbcode_to_text(row.get("description")),
        "game_id": P.to_int(row.get("consumer_app_id")),
        "creator_app_id": P.to_int(row.get("creator_app_id")),
        "authors": [{"name": None, "steamid": creator, "link": refs.profile_link(creator)}] if creator else None,
        "tags": [P.clean(t.get("tag")) for t in row.get("tags") or [] if isinstance(t, dict) and P.clean(t.get("tag"))] or None,
        "image": P.clean(row.get("preview_url")),
        "file_size_bytes": size or None,
        "file_link": P.clean(row.get("file_url")),
        "created_at": P.iso_datetime(row.get("time_created")),
        "updated_at": P.iso_datetime(row.get("time_updated")),
        "subscribers": P.to_int(row.get("subscriptions")),
        "favorites": P.to_int(row.get("favorited")),
        "lifetime_subscribers": P.to_int(row.get("lifetime_subscriptions")),
        "lifetime_favorites": P.to_int(row.get("lifetime_favorited")),
        "views": P.to_int(row.get("views")),
        "is_banned": bool(row.get("banned")),
        "ban_reason": P.clean(row.get("ban_reason")),
        "visibility": {0: "public", 1: "friends_only", 2: "private", 3: "unlisted"}.get(row.get("visibility")),
    }


_CARD_RE = re.compile(r'filedetails/\?id=(\d+)" class="[^"]*"><img')


def workshop(game, sort="trending", period="week", query=None, page=1):
    """Browse a game's Workshop: mods, maps, skins… 30 per page, sorted by
    trending (over `period`), top rated, most recent, last updated or
    most subscribed, or matching `query` — each item with its stats."""
    params = {"appid": game, "section": "readytouseitems", "p": page,
              "browsesort": "textsearch" if query else WORKSHOP_SORTS[sort]}
    if query:
        params["searchtext"] = query
    if sort == "trending" and not query:
        params["days"] = WORKSHOP_PERIODS[period]
    html_text = fetch.community_page("workshop/browse/", params, not_found=f"workshop of app {game}")
    ids = list(dict.fromkeys(_CARD_RE.findall(html_text)))
    if not ids and page == 1 and '"bIsValidAppHub":true' not in html_text.replace(" ", ""):
        raise fetch.SteamNotFound(f"app {game} has no Steam Workshop")
    rows = file_details(ids)
    items = [workshop_file(rows[i]) for i in ids if i in rows]
    return paged_result("items", items, page, WORKSHOP_PAGE_SIZE, has_more=len(ids) >= WORKSHOP_PAGE_SIZE,
                        game_id=game)


def workshop_item(item):
    """A Workshop item: description, author, tags, stats (subscribers,
    favourites, views, lifetime counts), star rating, comment count,
    required items and change-note count."""
    rows = file_details([item])
    row = rows.get(str(item))
    if not row:
        raise fetch.SteamNotFound(f"workshop item {item} not found (removed, private or not a workshop item)")
    out = workshop_file(row)
    try:
        html_text = fetch.community_page("sharedfiles/filedetails/", {"id": item, "l": "english"})
    except Exception:
        html_text = ""
    required = []
    block = html_text[html_text.find('id="RequiredItems"'):] if 'id="RequiredItems"' in html_text else ""
    if block:
        block = block[:block.find('</div>\n\t\t\t</div>')] if '</div>\n\t\t\t</div>' in block else block[:6000]
        for rid, name in re.findall(r'filedetails/\?id=(\d+)"[^>]*>\s*<div class="requiredItem">\s*(.*?)\s*</div>', block, re.S):
            required.append({"id": int(rid), "title": P.html_to_text(name), "link": refs.file_link(rid)})
    named = _creators(html_text)
    if named:
        owner = (out.get("authors") or [{}])[0].get("steamid")
        out["authors"] = [{"name": a["name"], "steamid": owner if i == 0 else None, "link": a["link"]}
                          for i, a in enumerate(named)]
    notes = re.search(r"([\d,]+)\s+Change Notes", html_text)
    stats = _stats_table(html_text)
    out.update({
        "rating_stars": _stars(html_text[html_text.find("ratingSection"):] if "ratingSection" in html_text else ""),
        "rating_count": _rating_count(html_text),
        "unique_visitors": stats.get("unique_visitors") or out.get("views"),
        "comment_count": _comment_count(html_text),
        "change_note_count": P.to_int(notes.group(1)) if notes else None,
        "required_items": required or None,
        "tag_groups": _tags_groups(html_text) or None,
    })
    return out


def collection(collection):
    """A Workshop collection with every item in it (full item stats)."""
    body = fetch.webapi_post("ISteamRemoteStorage", "GetCollectionDetails", 1,
                             {"collectioncount": 1, "publishedfileids[0]": collection})
    details = ((body or {}).get("collectiondetails") or [{}])[0]
    if not isinstance(details, dict) or details.get("result") != 1:
        raise fetch.SteamNotFound(f"collection {collection} not found")
    children = sorted([c for c in details.get("children") or [] if isinstance(c, dict)],
                      key=lambda c: P.to_int(c.get("sortorder")) or 0)
    child_ids = [str(c.get("publishedfileid")) for c in children if c.get("publishedfileid")]
    rows = file_details([collection] + child_ids)
    head = workshop_file(rows.get(str(collection))) if rows.get(str(collection)) else {"id": collection,
                                                                                         "link": refs.file_link(collection)}
    items = []
    for c in children:
        cid = str(c.get("publishedfileid"))
        if cid in rows:
            entry = workshop_file(rows[cid])
            entry["is_collection"] = c.get("filetype") == 2
            items.append(entry)
        else:
            items.append({"id": P.to_int(cid), "link": refs.file_link(cid), "is_collection": c.get("filetype") == 2,
                          "is_available": False})
    head.update({"item_count": len(children), "items": items})
    return head
