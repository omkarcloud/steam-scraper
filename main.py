"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. The functions live in steam/ (games.py, store.py, market.py,
reviews.py, charts.py, users.py, community.py …).
"""
import json
import os

from steam.games import details
from steam.market import price_history
from steam.refs import resolve_market_item
from steam.store import search

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a Steam app id (ELDEN RING) — the API also takes any store link
    save("game_1245620.json", details(1245620))

    # the store search, 25 per page, with every store filter
    save("search_cyberpunk.json", search(query="cyberpunk"))

    # a Community Market item's daily median price and units sold
    save("price_history_ak47_redline.json",
         price_history(resolve_market_item("AK-47 | Redline (Field-Tested)"), game=730, period="month"))
