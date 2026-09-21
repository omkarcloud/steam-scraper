"""Live endpoint smoke tests: one call per /steam/* route against a running
service, with example values proven to return data (2026-09-21). The
listing tooling (derive_facts.py) reads each route's FIRST call from this
file's AST as its working example, so the values stay literals.

Skipped unless STEAM_BASE points at a running service:

    ONLY_SCRAPER=steam python run.py            # or any bottle runner
    STEAM_BASE=http://127.0.0.1:6002 python -m pytest steam/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("STEAM_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set STEAM_BASE to run live endpoint tests")


def call(path, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == 200, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def status(path, **params):
    from curl_cffi import requests
    return requests.get(BASE + path, params=params, timeout=180).status_code


def test_store():
    body = call("/steam/search", query="dark souls")
    assert body["results"] and body["count"] > 100 and body["next"]
    body = call("/steam/search", section="top_sellers", types="game", discounted_only="true", os="mac", country="GB")
    assert all(r["price"]["currency"] == "GBP" for r in body["results"] if r["price"] and not r["price"]["is_free"])
    assert call("/steam/search/autocomplete", query="elden")["results"][0]["id"] == 1245620
    body = call("/steam/games/browse", sort="new_and_trending", tags="19", hide_free="true", limit="10")
    assert body["results"] and all(not r["is_free"] for r in body["results"])
    body = call("/steam/search", max_price="10", sort="user_reviews")
    assert all(r["price"]["amount"] <= 10 for r in body["results"] if r["price"])
    assert call("/steam/games/browse", min_discount="50")["results"][0]["price"]["discount_percent"] >= 50
    body = call("/steam/featured", country="US")
    assert body["specials"] and body["top_sellers"]
    assert any(t["name"] == "Action" for t in call("/steam/tags")["tags"])
    assert call("/steam/categories")["categories"]
    assert call("/steam/packages/details", package="440408")["apps"]
    assert call("/steam/bundles/details", bundle="https://store.steampowered.com/bundle/232/Valve_Complete_Pack/")["apps"]


def test_games():
    game = call("/steam/games/details", game="https://store.steampowered.com/app/1245620/ELDEN_RING/")
    assert game["name"] == "ELDEN RING" and game["requirements"]["windows"] and game["tags"]
    assert game["compatibility"]["steam_deck"] == "verified"
    prices = call("/steam/games/prices", game="1245620", countries="US,IN,DE")["prices"]
    assert {p["price"]["currency"] for p in prices} == {"USD", "INR", "EUR"}
    assert call("/steam/games/dlc", game="1245620")["dlc"]
    assert call("/steam/games/similar", game="1245620")["similar"]
    assert call("/steam/games/achievements", game="1245620")["total"] == 42
    assert call("/steam/games/player-count", game="730")["player_count"] > 0
    assert call("/steam/games/compatibility", game="570")["steam_deck"]["criteria"]
    assert call("/steam/games/news", game="570", limit="5")["news"]
    assert call("/steam/games/events", game="1245620")["events"]


def test_reviews():
    first = call("/steam/games/reviews", game="1245620", limit="20")
    assert first["summary"]["total"] > 100000 and len(first["reviews"]) == 20 and first["next_cursor"]
    second = call("/steam/games/reviews", game="1245620", limit="20", cursor=first["next_cursor"])
    assert second["reviews"] and second["reviews"][0]["id"] != first["reviews"][0]["id"]
    assert call("/steam/games/reviews", game="1245620", sort="helpful", review_type="negative", language="en",
                day_range="30")["reviews"]
    assert call("/steam/games/reviews/summary", game="1245620")["overall"]["total"] > 100000
    assert call("/steam/games/reviews/histogram", game="1245620")["history"]


def test_community():
    assert call("/steam/games/guides", game="1245620", sort="top_rated")["guides"]
    assert call("/steam/games/discussions", game="1245620")["topics"]
    assert call("/steam/games/workshop", game="4000")["items"]
    assert call("/steam/guides/details", guide="3792776566")["sections"]
    assert call("/steam/workshop/items/details", item="104691717")["subscribers"] > 100000
    assert call("/steam/workshop/collections/details", collection="1997655872")["items"]


def test_charts():
    assert call("/steam/charts/most-played")["results"][0]["game"]["name"]
    assert call("/steam/charts/concurrent-players", limit="10")["results"][0]["current_players"] > 0
    assert call("/steam/charts/top-sellers", country="US")["results"]
    assert call("/steam/charts/top-releases")["results"]


def test_creators():
    assert call("/steam/creators/games", creator="FromSoftware")["results"]
    assert call("/steam/curators")["curators"]
    assert call("/steam/curators/reviews", curator="https://store.steampowered.com/curator/1850-PC-Gamer/")["reviews"]


def test_users():
    assert call("/steam/users/resolve", user="https://steamcommunity.com/id/robinwalker/")["steamid64"] == "76561197960435530"
    assert call("/steam/users/profile", user="robinwalker")["level"]
    assert call("/steam/users/friends", user="76561197960435530")["friends"]
    assert call("/steam/users/badges", user="robinwalker")["badges"]
    assert call("/steam/users/reviews", user="robinwalker")["reviews"]
    assert call("/steam/users/achievements", user="76561199079949101", game="1245620")["achievements"]
    assert call("/steam/users/wishlist", user="76561198084830238")["wishlist"]
    assert call("/steam/users/inventory", user="76561197960435530", game="730")["items"]
    assert call("/steam/users/groups", user="robinwalker")["groups"]
    # owned / recently played games need STEAM_WEB_API_KEY: 400 without it
    assert status("/steam/users/games", user="robinwalker") in (200, 400, 404)


def test_groups():
    assert call("/steam/groups/details", group="valve")["members"] > 0
    assert call("/steam/groups/members", group="https://steamcommunity.com/groups/valve")["members"]


def test_market():
    assert call("/steam/market/search", query="ak-47 redline", game="730")["results"]
    assert call("/steam/market/autocomplete", query="dragon lore")["results"]
    assert call("/steam/market/filters", game="730")["filters"]
    assert call("/steam/market/items/details",
                item="https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20(Field-Tested)")["prices"]["lowest_sell_order"]
    assert call("/steam/market/items/price-history",
                item="https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20(Field-Tested)", period="week")["history"]
    assert call("/steam/market/items/order-book",
                item="https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline%20(Field-Tested)")["sell_orders"]
    assert call("/steam/market/items/details", item="AK-47 | Redline (Field-Tested)", game="730")["class_id"]


def test_errors():
    assert status("/steam/games/details", game="99999999") == 404
    assert status("/steam/games/details", game="not a game") == 400
    assert status("/steam/users/profile", user="no_such_vanity_zz91") == 404
    assert status("/steam/search", bogus="1") == 400
