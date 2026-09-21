"""Steam users: id resolution (vanity / steamid2 / steamid3 / links ->
steamid64), public profiles, friends, badges, reviews, per-game
achievements, wishlist, inventory, groups, and — with a Steam Web API key
— owned and recently played games.

A `user` param arrives from the schema as {"steamid": "7656…"} or
{"vanity": "name"}; every endpoint resolves it through steamid() first."""
import re

from steam import fetch, refs
from steam import parsers as P
from steam.shared import app_cards, paged_result, start_of

ONLINE_STATES = {"online": "online", "offline": "offline", "in-game": "in_game"}
INVENTORY_MAX = 2000


def _text(node, tag):
    if node is None:
        return None
    return P.clean(node.findtext(tag))


def steamid(user):
    """{"steamid": …} | {"vanity": …} -> steamid64 string (vanity names are
    looked up through the profile's XML document)."""
    if user.get("steamid"):
        return user["steamid"]
    root = fetch.community_xml(f"id/{user['vanity']}/", not_found=f"user {user['vanity']}")
    sid = _text(root, "steamID64")
    if not sid:
        raise fetch.SteamNotFound(f"user {user['vanity']} not found")
    return sid


def _profile_xml(sid):
    return fetch.community_xml(f"profiles/{sid}/", not_found=f"user {sid}")


def resolve(user):
    """Every id form of a user (steamid64 / steamid2 / steamid3 / account
    id), their name, vanity URL and profile link."""
    sid = steamid(user)
    root = _profile_xml(sid)
    vanity = _text(root, "customURL")
    return {**refs.steamid_formats(sid), "name": _text(root, "steamID"), "vanity_name": vanity,
            "vanity_link": f"https://steamcommunity.com/id/{vanity}/" if vanity else None,
            "link": refs.profile_link(sid)}


# ---- profile ---------------------------------------------------------------------------------------------

def _group_xml(g):
    gid = _text(g, "groupID64")
    url = _text(g, "groupURL")
    return {"id": gid, "name": _text(g, "groupName"), "link": refs.group_link(url) if url else None,
            "headline": _text(g, "headline"), "summary": P.html_to_text(_text(g, "summary")),
            "avatar": _text(g, "avatarFull"), "is_primary": g.get("isPrimary") == "1",
            "members": P.to_int(_text(g, "memberCount")), "members_in_game": P.to_int(_text(g, "membersInGame")),
            "members_online": P.to_int(_text(g, "membersOnline")), "members_in_chat": P.to_int(_text(g, "membersInChat"))}


def _most_played(root):
    out = []
    for g in root.findall("./mostPlayedGames/mostPlayedGame"):
        link = _text(g, "gameLink")
        app = re.search(r"/app/(\d+)", link or "")
        out.append({"game_id": P.to_int(app.group(1)) if app else None, "name": _text(g, "gameName"),
                    "link": link, "icon": _text(g, "gameIcon"), "logo": _text(g, "gameLogo"),
                    "hours_last_two_weeks": P.to_float(_text(g, "hoursPlayed")),
                    "hours_on_record": P.to_float(_text(g, "hoursOnRecord"))})
    return out or None


_COUNT_RE = re.compile(r'<span class="count_link_label">([^<]+)</span>&nbsp;\s*<span class="profile_count_link_total">\s*([\d,]*)')


def profile(user):
    """A public profile: name, real name, avatar, country, level, member
    since, online / in-game status, bans, summary, counts (games, badges,
    friends, groups, screenshots, reviews, awards…), favourite badge and
    group, most played games and group memberships."""
    sid = steamid(user)
    root = _profile_xml(sid)
    try:
        html_text = fetch.community_page(f"profiles/{sid}/", {"l": "english"})
    except Exception:
        html_text = ""
    levels = re.findall(r'friendPlayerLevelNum">(\d+)', html_text)
    flag = re.search(r'countryflags/([a-z]{2})\.gif', html_text)
    counts = {}
    for label, value in _COUNT_RE.findall(html_text):
        key = re.sub(r"[^a-z]+", "_", label.strip().lower()).strip("_")
        counts[key] = P.to_int(value)
    for value, label in re.findall(r'<a class="showcase_stat"[^>]*>\s*<div class="value">([\d,]+)</div>\s*<div class="label">([^<]+)</div>',
                                   html_text):
        counts.setdefault(re.sub(r"[^a-z]+", "_", label.strip().lower()).strip("_"), P.to_int(value))
    badge = None
    if "favorite_badge_description" in html_text:
        seg = html_text[html_text.find("favorite_badge_description"):][:1500]
        badge = {"name": P.text_between(seg, '<div class="name ellipsis">'),
                 "xp": P.number_in(P.text_between(seg, '<div class="xp">'))}
    in_game = P.text_between(html_text, '<div class="profile_in_game_name">') if "profile_in_game_name" in html_text else None
    vanity = _text(root, "customURL")
    privacy = _text(root, "privacyState")
    return {
        "steamid": sid,
        "name": _text(root, "steamID"),
        "link": refs.profile_link(sid),
        "vanity_name": vanity,
        "real_name": _text(root, "realname"),
        "headline": _text(root, "headline"),
        "summary": P.html_to_text(_text(root, "summary")),
        "location": _text(root, "location"),
        "country_code": flag.group(1).upper() if flag else None,
        "avatar": _text(root, "avatarFull"),
        "level": P.to_int(levels[0]) if levels else None,
        "member_since": P.parse_date_text(_text(root, "memberSince")),
        "status": ONLINE_STATES.get(_text(root, "onlineState") or "", _text(root, "onlineState")),
        "status_text": P.html_to_text(_text(root, "stateMessage")),
        "in_game": in_game,
        "privacy": {"public": "public", "friendsonly": "friends_only", "private": "private"}.get(privacy, privacy),
        "is_limited_account": _text(root, "isLimitedAccount") == "1",
        "is_vac_banned": _text(root, "vacBanned") == "1",
        "trade_ban_state": _text(root, "tradeBanState"),
        "hours_played_last_two_weeks": P.to_float(_text(root, "hoursPlayed2Wk")),
        "counts": counts or None,
        "favorite_badge": badge,
        "most_played_games": _most_played(root),
        "groups": [_group_xml(g) for g in root.findall("./groups/group")] or None,
    }


# ---- friends / badges / reviews / achievements ------------------------------------------------------------------

_FRIEND_SPLIT_RE = re.compile(r'class="selectable friend_block_v2 persona ([a-z\-]+)[^"]*"')


def friends(user):
    """A public profile's friends list: name, avatar, status and the game
    they are playing."""
    sid = steamid(user)
    html_text = fetch.community_page(f"profiles/{sid}/friends/", {"l": "english"}, not_found=f"user {sid}")
    if "profile_private_info" in html_text or "This profile is private" in html_text:
        raise fetch.SteamNotFound(f"user {sid} keeps their friends list private")
    rows = []
    parts = _FRIEND_SPLIT_RE.split(html_text)
    # split -> [before, state1, block1, state2, block2, ...]
    for state, block in zip(parts[1::2], parts[2::2]):
        sid_match = re.search(r'data-steamid="(\d+)"', block)
        if not sid_match:
            continue
        fsid = sid_match.group(1)
        link = re.search(r'class="selectable_overlay"[^>]*href="([^"]+)"', block)
        name_block = P.text_between(block, '<div class="friend_block_content">', "<br>")
        game = P.text_between(block, '<span class="friend_game_link">', "</span>")
        last_online = P.text_between(block, '<span class="friend_last_online_text">', "</span>")
        rows.append({"steamid": fsid, "name": name_block, "link": link.group(1) if link else refs.profile_link(fsid),
                     "avatar": P.attr(block[block.find("<img"):], "src") if "<img" in block else None,
                     "status": ONLINE_STATES.get(state, state), "in_game": game, "last_online": last_online})
    if not rows and "friends_header_count" not in html_text and "search_results" not in html_text:
        raise fetch.SteamNotFound(f"no public friends list for user {sid}")
    return {"steamid": sid, "total": len(rows), "friends": rows}


_BADGE_RE = re.compile(r'<div[^>]*class="badge_row is_link">(.*?)<div style="clear: both;"></div>\s*</div>\s*</div>\s*</div>', re.S)


def badges(user):
    """Every badge on a public profile (community and game badges) with
    XP, unlock date and icon, plus the player's level and total XP."""
    sid = steamid(user)
    html_text = fetch.community_page(f"profiles/{sid}/badges/", {"l": "english"}, not_found=f"user {sid}")
    rows = []
    for block in _BADGE_RE.findall(html_text):
        link = re.search(r'class="badge_row_overlay" href="([^"]+)"', block)
        game = re.search(r'/gamecards/(\d+)', link.group(1)) if link else None
        title = P.text_between(block, '<div class="badge_info_title">') or P.text_between(block, '<div class="badge_title">', "&nbsp;")
        xp = None
        desc = block[block.find('badge_info_description'):] if 'badge_info_description' in block else ""
        m = re.search(r"([\d,]+)\s*XP", desc)
        if m:
            xp = P.to_int(m.group(1))
        level = re.search(r"Level\s+(\d+)", desc)
        rows.append({
            "name": title,
            "link": link.group(1) if link else None,
            "game_id": P.to_int(game.group(1)) if game else None,
            "game_name": P.text_between(block, '<div class="badge_title">', "&nbsp;") if game else None,
            "level": P.to_int(level.group(1)) if level else None,
            "xp": xp,
            "unlocked_on": P.community_date(P.text_between(block, '<div class="badge_info_unlocked">')),
            "icon": P.attr(block, "data-delayed-image") or (P.attr(block[block.find("badge_icon") - 300:], "src")
                                                            if "badge_icon" in block else None),
        })
    xp = re.search(r'profile_xp_block_xp">XP\s*([\d,]+)', html_text)
    level = re.findall(r'friendPlayerLevelNum">(\d+)', html_text)
    remaining = re.search(r'profile_xp_block_remaining">([\d,]+)\s*XP', html_text)
    return {"steamid": sid, "level": P.to_int(level[0]) if level else None, "xp": P.to_int(xp.group(1)) if xp else None,
            "xp_to_next_level": P.to_int(remaining.group(1)) if remaining else None, "total": len(rows), "badges": rows}


_REVIEW_BOX_RE = re.compile(r'class="review_box\s*">(.*?)<div class="control_block">', re.S)


def reviews(user, page=1):
    """Reviews a user has written: game, verdict, hours on record, date,
    text and helpful / funny counts. 10 per page."""
    sid = steamid(user)
    html_text = fetch.community_page(f"profiles/{sid}/recommended/", {"p": page, "l": "english"},
                                     not_found=f"user {sid}")
    rows = []
    for block in _REVIEW_BOX_RE.findall(html_text):
        app = re.search(r'steamcommunity\.com/app/(\d+)', block)
        hours = P.text_between(block, '<div class="hours">')
        helpful = P.text_between(block, '<div class="header">')
        link = re.search(r'<div class="title"><a href="([^"]+)"', block)
        at_review = re.search(r"\(([\d,.]+)\s*hrs at review time\)", hours or "")
        rows.append({
            "game_id": P.to_int(app.group(1)) if app else None,
            "link": link.group(1) if link else None,
            "is_recommended": "icon_thumbsUp" in block,
            "hours_on_record": P.to_float(P.number_in(hours)) if hours else None,
            "hours_at_review": P.to_float(at_review.group(1).replace(",", "")) if at_review else None,
            "posted_on": P.community_date(P.text_between(block, '<div class="posted">')),
            "text": P.inner(block, "content"),
            "helpful_votes": P.number_in(re.search(r"([\d,]+) people found this review helpful", helpful or "").group(1))
            if helpful and re.search(r"([\d,]+) people found this review helpful", helpful) else 0,
            "funny_votes": P.number_in(re.search(r"([\d,]+) people found this review funny", helpful or "").group(1))
            if helpful and re.search(r"([\d,]+) people found this review funny", helpful) else 0,
            "is_counted_in_score": "icon_review_counted" in block,
        })
    total = re.search(r"Showing\s+[\d,]+\s*-\s*[\d,]+\s+of\s+([\d,]+)", html_text)
    names = {c["id"]: c for c in app_cards([r["game_id"] for r in rows if r["game_id"]])} if rows else {}
    for r in rows:
        card = names.get(r["game_id"])
        r["game"] = {"id": r["game_id"], "name": card.get("name") if card else None,
                     "link": refs.app_link(r["game_id"]) if r["game_id"] else None,
                     "image": ((card or {}).get("images") or {}).get("capsule_small")}
        r.pop("game_id")
    return paged_result("reviews", rows, page, 10, total=P.to_int(total.group(1)) if total else (len(rows) if page == 1 and len(rows) < 10 else None),
                        steamid=sid)


def achievements(user, game):
    """A user's achievements in one game: unlocked or not, with unlock time,
    description and icons, plus their hours played."""
    sid = steamid(user)
    root = fetch.community_xml(f"profiles/{sid}/stats/{game}/", not_found=f"stats of user {sid} for app {game}")
    if (_text(root, "privacyState") or "public") != "public":
        raise fetch.SteamNotFound(f"user {sid} keeps their game stats private")
    rows = []
    for a in root.findall("./achievements/achievement"):
        unlocked = a.get("closed") == "1"
        rows.append({"id": _text(a, "apiname"), "name": _text(a, "name"), "description": _text(a, "description"),
                     "is_unlocked": unlocked, "unlocked_at": P.iso_datetime(_text(a, "unlockTimestamp")) if unlocked else None,
                     "icon": _text(a, "iconClosed") if unlocked else _text(a, "iconOpen"),
                     "icon_locked": _text(a, "iconOpen"), "icon_unlocked": _text(a, "iconClosed")})
    game_node = root.find("game")
    unlocked = sum(1 for r in rows if r["is_unlocked"])
    return {"steamid": sid,
            "game": {"id": game, "name": _text(game_node, "gameName"), "link": refs.app_link(game),
                     "icon": _text(game_node, "gameIcon"), "logo": _text(game_node, "gameLogo")},
            "hours_played": P.to_float(_text(root.find("stats"), "hoursPlayed")),
            "total": len(rows), "unlocked": unlocked,
            "percent_unlocked": round(unlocked * 100 / len(rows), 1) if rows else None,
            "achievements": rows}


# ---- wishlist / inventory / groups ------------------------------------------------------------------------------

def wishlist(user, page=1, limit=25, country=None, language=None):
    """A public wishlist in the owner's priority order, each game as a full
    card with its date added."""
    sid = steamid(user)
    body = fetch.webapi("IWishlistService", "GetWishlist", 1, {"steamid": sid})
    items = [i for i in (body or {}).get("items") or [] if isinstance(i, dict) and i.get("appid")]
    if not items:
        raise fetch.SteamNotFound(f"user {sid} has an empty or private wishlist")
    items.sort(key=lambda i: (P.to_int(i.get("priority")) or 0) or 10 ** 9)
    window = items[start_of(page, limit):start_of(page, limit) + limit]
    by_id = {c["id"]: c for c in app_cards([i["appid"] for i in window], country, language)}
    rows = []
    for i in window:
        card = by_id.get(i["appid"])
        rows.append({"priority": P.to_int(i.get("priority")) or None, "added_at": P.iso_datetime(i.get("date_added")),
                     "game": card or {"id": i["appid"], "link": refs.app_link(i["appid"])}})
    return paged_result("wishlist", rows, page, limit, total=len(items), steamid=sid)


def inventory(user, game=730, context_id=2, cursor=None, limit=100, language=None):
    """A public inventory for one game (CS2 = 730, TF2 = 440, Dota 2 = 570,
    Steam trading cards / backgrounds = app 753 context 6): every item with
    its market name, type, tags, tradable / marketable flags and amount."""
    sid = steamid(user)
    params = {"l": language or "english", "count": limit}
    if cursor:
        params["start_assetid"] = cursor
    body = fetch.community_json(f"inventory/{sid}/{game}/{context_id}", params,
                                not_found=f"inventory of user {sid} for app {game}")
    if not isinstance(body, dict) or not body.get("success"):
        raise fetch.SteamNotFound(f"inventory of user {sid} for app {game} not found (private or empty)")
    descs = {}
    for d in body.get("descriptions") or []:
        if isinstance(d, dict):
            descs[(str(d.get("classid")), str(d.get("instanceid")))] = d
    items = []
    for a in body.get("assets") or []:
        if not isinstance(a, dict):
            continue
        d = descs.get((str(a.get("classid")), str(a.get("instanceid"))))
        info = P.market_description(d) or {}
        items.append({"asset_id": P.clean(str(a.get("assetid"))), "amount": P.to_int(a.get("amount")) or 1, **info,
                      "market_link": P.market_link(game, info.get("hash_name")) if info.get("is_marketable") else None})
    more = bool(body.get("more_items"))
    return {"steamid": sid, "game_id": game, "context_id": context_id,
            "total": P.to_int(body.get("total_inventory_count")), "items": items,
            "next_cursor": P.clean(str(body.get("last_assetid"))) if more and body.get("last_assetid") else None}


def groups(user):
    """The Steam groups a public profile belongs to (name, headline,
    avatar, member / online / in-game counts, primary group flag)."""
    sid = steamid(user)
    root = _profile_xml(sid)
    rows = [_group_xml(g) for g in root.findall("./groups/group")]
    if not rows and (_text(root, "privacyState") or "public") != "public":
        raise fetch.SteamNotFound(f"user {sid} keeps their profile private")
    return {"steamid": sid, "total": len(rows), "groups": rows}


# ---- keyed (STEAM_WEB_API_KEY) --------------------------------------------------------------------------------

def _owned_game(g):
    app_id = P.to_int(g.get("appid"))
    icon = P.clean(g.get("img_icon_url"))
    return {"id": app_id, "name": P.clean(g.get("name")), "link": refs.app_link(app_id),
            "hours_on_record": P.minutes_to_hours(g.get("playtime_forever")),
            "hours_last_two_weeks": P.minutes_to_hours(g.get("playtime_2weeks")) or 0.0,
            "hours_windows": P.minutes_to_hours(g.get("playtime_windows_forever")),
            "hours_mac": P.minutes_to_hours(g.get("playtime_mac_forever")),
            "hours_linux": P.minutes_to_hours(g.get("playtime_linux_forever")),
            "hours_steam_deck": P.minutes_to_hours(g.get("playtime_deck_forever")),
            "last_played_at": P.iso_datetime(g.get("rtime_last_played")),
            "icon": f"https://media.steampowered.com/steamcommunity/public/images/apps/{app_id}/{icon}.jpg" if icon else None,
            "has_community_stats": bool(g.get("has_community_visible_stats"))}


def games(user):
    """Every game a public profile owns with playtime per platform and
    last played time (needs STEAM_WEB_API_KEY)."""
    sid = steamid(user)
    body = fetch.webapi("IPlayerService", "GetOwnedGames", 1, {"steamid": sid, "include_appinfo": 1,
                                                                "include_played_free_games": 1}, key=True)
    rows = [_owned_game(g) for g in (body or {}).get("games") or [] if isinstance(g, dict)]
    if not rows and not (body or {}).get("game_count"):
        raise fetch.SteamNotFound(f"user {sid} keeps their game library private (or owns no games)")
    rows.sort(key=lambda g: g["hours_on_record"] or 0, reverse=True)
    return {"steamid": sid, "total": P.to_int((body or {}).get("game_count")) or len(rows), "games": rows}


def recently_played(user):
    """Games played in the last two weeks (needs STEAM_WEB_API_KEY)."""
    sid = steamid(user)
    body = fetch.webapi("IPlayerService", "GetRecentlyPlayedGames", 1, {"steamid": sid}, key=True)
    rows = [_owned_game(g) for g in (body or {}).get("games") or [] if isinstance(g, dict)]
    return {"steamid": sid, "total": P.to_int((body or {}).get("total_count")) or len(rows), "games": rows}
