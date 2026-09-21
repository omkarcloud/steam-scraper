"""Steam Community groups: details (name, headline, summary, avatar,
member counts, founding date, abbreviation) and the member list —
steamcommunity.com group XML (memberslistxml, 1,000 steamids per page)
plus the group page for the fields the XML lacks."""
import re

from steam import fetch, refs
from steam import parsers as P

MEMBERS_PAGE_SIZE = 1000


def _path(group):
    return f"gid/{group['gid']}" if group.get("gid") else f"groups/{group['name']}"


def _text(node, tag):
    return P.clean(node.findtext(tag)) if node is not None else None


def _members_xml(group, page):
    return fetch.community_xml(f"{_path(group)}/memberslistxml/", {"p": page},
                               not_found=f"group {group.get('name') or group.get('gid')}")


def details(group):
    """A group's profile: name, abbreviation, headline, summary, avatar,
    member / online / in-game / chat counts and founding date."""
    root = _members_xml(group, 1)
    d = root.find("groupDetails")
    url = _text(d, "groupURL")
    try:
        html_text = fetch.community_page(f"groups/{url}" if url else _path(group), {"l": "english"})
    except Exception:
        html_text = ""
    abbrev = P.text_between(html_text, '<span class="grouppage_header_abbrev" style="">', "</span>")
    founded = re.search(r'<div class="label">Founded</div>\s*<div class="data">([^<]+)</div>', html_text)
    language = re.search(r'<div class="label">Language</div>\s*<div class="data">([^<]+)</div>', html_text)
    location = re.search(r'<div class="label">Location</div>\s*<div class="data">(.*?)</div>', html_text, re.S)
    join = P.text_between(html_text, '<div class="grouppage_join_area">')
    return {
        "id": _text(root, "groupID64"),
        "name": _text(d, "groupName"),
        "link": refs.group_link(url) if url else None,
        "abbreviation": abbrev.strip("[]") if abbrev else None,
        "headline": _text(d, "headline"),
        "summary": P.html_to_text(_text(d, "summary")),
        "avatar": _text(d, "avatarFull"),
        "members": P.to_int(_text(d, "memberCount")),
        "members_in_game": P.to_int(_text(d, "membersInGame")),
        "members_online": P.to_int(_text(d, "membersOnline")),
        "members_in_chat": P.to_int(_text(d, "membersInChat")),
        "founded_on": P.community_date(founded.group(1)) if founded else None,
        "language": P.clean(language.group(1)) if language else None,
        "location": P.html_to_text(location.group(1)) if location else None,
        "membership": "invite_only" if join and "invitation" in join.lower() else ("open" if join else None),
    }


def members(group, page=1):
    """One page (up to 1,000) of a group's members as steamids with profile
    links, plus the group's total member count."""
    root = _members_xml(group, page)
    ids = [P.clean(n.text) for n in root.findall("./members/steamID64") if P.clean(n.text)]
    rows = [{"steamid": sid, "link": refs.profile_link(sid)} for sid in ids]
    total = P.to_int(_text(root, "memberCount"))
    total_pages = P.to_int(_text(root, "totalPages"))
    return {"group_id": _text(root, "groupID64"), "group_name": _text(root.find("groupDetails"), "groupName"),
            "members": rows,
            "pagination": {"page": page, "items_per_page": MEMBERS_PAGE_SIZE, "total_count": total,
                           "total_pages": total_pages}}
