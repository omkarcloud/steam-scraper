"""Offline tests for the Steam refs, marshmallow schemas, parsers and
endpoint functions with the transport monkeypatched to serve fixtures (raw
payloads captured 2026-09-21) — no network.

    python -m pytest steam/test_parsers.py -q
"""
import json
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schema_fields import load_query  # noqa: E402
from steam import (community, fetch, games, groups, market, parsers as P, refs, reviews,  # noqa: E402
                   schemas as S, shared, users)

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return f.read()


def js(name):
    return json.loads(raw(name))


@pytest.fixture(autouse=True)
def no_lookups(monkeypatch):
    """Tag names / currency come from in-process lookups; pin them."""
    monkeypatch.setattr(shared, "tag_names", lambda language=None: {29482: "Souls-like", 1695: "Open World"})
    monkeypatch.setattr(shared, "currency_for", lambda country=None: "USD")
    for module in (games, reviews, users):
        if hasattr(module, "tag_names"):
            monkeypatch.setattr(module, "tag_names", lambda language=None: {29482: "Souls-like"})
        if hasattr(module, "currency_for"):
            monkeypatch.setattr(module, "currency_for", lambda country=None: "USD")


# ---- refs ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["1245620", "https://store.steampowered.com/app/1245620/ELDEN_RING/",
                                   "store.steampowered.com/app/1245620", "https://steamcommunity.com/app/1245620/reviews/",
                                   "https://store.steampowered.com/agecheck/app/1245620/"])
def test_app_ref(value):
    assert refs.resolve_app(value) == 1245620


@pytest.mark.parametrize("value,expected", [
    ("76561197960287930", {"steamid": "76561197960287930"}),
    ("STEAM_0:0:11101", {"steamid": "76561197960287930"}),
    ("[U:1:22202]", {"steamid": "76561197960287930"}),
    ("22202", {"steamid": "76561197960287930"}),
    ("gabelogannewell", {"vanity": "gabelogannewell"}),
    ("https://steamcommunity.com/id/gabelogannewell/games/?tab=all", {"vanity": "gabelogannewell"}),
    ("https://steamcommunity.com/profiles/76561197960287930/", {"steamid": "76561197960287930"}),
])
def test_user_ref(value, expected):
    assert refs.resolve_user(value) == expected


def test_steamid_formats():
    f = refs.steamid_formats("76561197960287930")
    assert f["steamid2"] == "STEAM_0:0:11101" and f["steamid3"] == "[U:1:22202]" and f["account_id"] == 22202


def test_other_refs():
    assert refs.resolve_group("https://steamcommunity.com/groups/valve") == {"name": "valve"}
    assert refs.resolve_group("103582791429521412") == {"gid": "103582791429521412"}
    assert refs.resolve_file("https://steamcommunity.com/sharedfiles/filedetails/?id=104691717") == 104691717
    assert refs.resolve_bundle("https://store.steampowered.com/bundle/232/Valve_Complete_Pack/") == 232
    assert refs.resolve_package("https://store.steampowered.com/sub/440408/") == 440408
    assert refs.resolve_creator("https://store.steampowered.com/publisher/BANDAINAMCO/") == {"kind": "publisher", "slug": "BANDAINAMCO"}
    assert refs.resolve_creator("FromSoftware") == {"kind": None, "slug": "FromSoftware"}
    assert refs.resolve_curator("https://store.steampowered.com/curator/1850-PC-Gamer/") == "1850-PC-Gamer"
    assert refs.resolve_market_item("https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20(Field-Tested)") == \
        {"app_id": 730, "name": "AK-47 | Redline (Field-Tested)"}
    with pytest.raises(ValueError):
        refs.resolve_app("https://example.com/app/1")


# ---- schemas ---------------------------------------------------------------------------------------

def test_schemas():
    data, err = load_query(S.StoreSearchSchema, {"query": "souls", "section": "top_sellers", "types": "game,dlc",
                                                 "tags": "19,122", "language": "de", "country": "gb"})
    assert err is None and data["section"] == "top_sellers" and data["tags"] == [19, 122]
    assert data["language"] == "german" and data["country"] == "GB"
    data, err = load_query(S.ReviewsSchema, {"game": "1245620", "review_type": "negative", "language": "all"})
    assert err is None and data["review_type"] == "negative"
    assert load_query(S.StoreSearchSchema, {"typo": "1"})[1]
    assert load_query(S.BrowseSchema, {"tags": "action"})[1]
    assert load_query(S.MarketSearchSchema, {"filters": "Exterior:WearCategory0"})[1]      # needs a game
    assert load_query(S.GamePricesSchema, {"game": "570", "countries": "US,XX"})[1]
    data, _ = load_query(S.LanguageOnlySchema, {"language": "zh-CN"})
    assert data["language"] == "schinese"


# ---- parsers ------------------------------------------------------------------------------------------

def test_value_helpers():
    assert P.community_date("25 Oct, 2012 @ 8:41pm") == "2012-10-25"
    assert P.community_date("Posted 20 September.", today=__import__("datetime").date(2026, 9, 21)) == "2026-09-20"
    assert P.community_date("Dec 25", today=__import__("datetime").date(2026, 9, 21)) == "2025-12-25"
    assert P.parse_date_text("Feb 24, 2022") == "2022-02-24"
    assert P.price_block(11684, 12984, 0, "USD")["discount_percent"] == 10
    assert P.price_block(None, currency="USD", is_free=True)["is_free"] is True
    assert P.split_camel("#SteamDeckVerified_TestResult_InterfaceTextIsLegible") == "Interface text is legible"
    text = P.bbcode_to_text("[p]Fixes[/p][list][*] A [url=\"x\"]link[/url][*] B[/list][img]{STEAM_CLAN_IMAGE}/a.png[/img]")
    assert "• A link" in text and "• B" in text and "STEAM_CLAN_IMAGE" not in text


def test_store_item_card():
    item = js("getitems.json")["response"]["store_items"][0]
    card = P.store_item(item, "USD", {29482: "Souls-like"})
    assert card["id"] == 1245620 and card["type"] == "game" and card["price"]["currency"] == "USD"
    assert card["reviews"]["label"] and card["platforms"]["steam_deck_compatibility"] == "verified"
    assert card["tags"] == ["Souls-like"] and card["images"]["header"].startswith("https://")


def test_item_keys_in_search_html():
    keys = P.item_keys_in(js("search_results.json")["results_html"])
    assert len(keys) == 25 and keys[0][0] == "appid"


# ---- endpoint functions with fixtures ------------------------------------------------------------------

def test_reviews_page(monkeypatch):
    monkeypatch.setattr(fetch, "store_json", lambda path, params=None, **kw: js("appreviews_1245620.json"))
    out = reviews.reviews(1245620, limit=5)
    assert out["summary"]["total"] > 0 and len(out["reviews"]) == 5 and out["next_cursor"]
    r = out["reviews"][0]
    assert r["author"]["steamid"] and r["created_at"].endswith("Z") and isinstance(r["is_recommended"], bool)


def test_histogram(monkeypatch):
    monkeypatch.setattr(fetch, "store_json", lambda path, params=None, **kw: js("histogram_1245620.json"))
    out = reviews.histogram(1245620)
    assert out["period"] == "month" and out["history"][0]["date"] == "2022-02-01" and out["last_30_days"]


def test_compatibility(monkeypatch):
    monkeypatch.setattr(fetch, "store_json", lambda path, params=None, **kw: js("deck_1245620.json"))
    out = games.compatibility(1245620)
    assert out["steam_deck"]["verdict"] == "verified"
    assert all(c["result"] == "pass" for c in out["steam_deck"]["criteria"])


def test_achievements_page(monkeypatch):
    monkeypatch.setattr(fetch, "community_page", lambda path, params=None, **kw: raw("achievements_1245620.html"))
    out = games.achievements(1245620)
    assert out["total"] == 42 and out["achievements"][0]["percent_unlocked"] == 75.0


def test_user_stats(monkeypatch):
    monkeypatch.setattr(fetch, "community_xml", lambda path, params=None, **kw: ET.fromstring(raw("user_stats_1245620.xml").encode()))
    out = users.achievements({"steamid": "76561199079949101"}, 1245620)
    assert out["total"] == 42 and out["game"]["name"] == "ELDEN RING"


def test_profile_xml_groups(monkeypatch):
    monkeypatch.setattr(fetch, "community_xml", lambda path, params=None, **kw: ET.fromstring(raw("profile.xml").encode()))
    monkeypatch.setattr(fetch, "community_page", lambda *a, **kw: "")
    out = users.profile({"steamid": "76561199079949101"})
    assert out["name"] == "AnAmazingApple" and out["member_since"] == "2020-08-06" and out["privacy"] == "public"


def test_group_members(monkeypatch):
    monkeypatch.setattr(fetch, "community_xml", lambda path, params=None, **kw: ET.fromstring(raw("group_members.xml").encode()))
    out = groups.members({"name": "valve"})
    assert out["pagination"]["total_count"] == 151 and out["members"][0]["link"].startswith("https://")


def test_market_search(monkeypatch):
    monkeypatch.setattr(fetch, "market_json", lambda path, params=None, **kw: js("market_search.json"))
    out = market.search("ak-47", game=730)
    row = out["results"][0]
    assert row["lowest_price"]["currency"] == "USD" and row["link"].startswith("https://steamcommunity.com/market/listings/730/")


def test_market_needs_game():
    with pytest.raises(ValueError):
        market.order_book({"app_id": None, "name": "AK-47 | Redline (Field-Tested)"})


def test_workshop_file_row():
    row = {"publishedfileid": "104691717", "result": 1, "creator": "76561197978977007", "consumer_app_id": 4000,
           "title": "PAC3", "description": "[h1]ABOUT[/h1]Hats", "time_created": 1351222862, "subscriptions": 5,
           "tags": [{"tag": "Addon"}], "visibility": 0, "file_size": "8707053"}
    out = community.workshop_file(row)
    assert out["title"] == "PAC3" and out["visibility"] == "public" and out["file_size_bytes"] == 8707053
    assert out["created_at"] == "2012-10-26T03:41:02Z" and out["tags"] == ["Addon"]
