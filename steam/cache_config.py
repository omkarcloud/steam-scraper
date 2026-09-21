"""Cache TTL per /steam/* endpoint (cache.py, keyed on the validated params
— marshmallow fills the defaults, so `?page=1` and no `page` share a row).

Tiers follow how fast each surface moves: live player counts and the
market order book change by the minute, prices / charts / review lists by
the hour, store pages and profiles over the day, reference lists (tags,
categories) almost never."""
from datetime import timedelta

# --- store -------------------------------------------------------------------
SEARCH_CACHE = timedelta(hours=1)
AUTOCOMPLETE_CACHE = timedelta(hours=6)
BROWSE_CACHE = timedelta(hours=1)
FEATURED_CACHE = timedelta(minutes=30)
REFERENCE_CACHE = timedelta(days=7)
PACKAGE_CACHE = timedelta(hours=6)

# --- games -------------------------------------------------------------------
GAME_CACHE = timedelta(hours=6)
PRICES_CACHE = timedelta(hours=1)
DLC_CACHE = timedelta(hours=6)
SIMILAR_CACHE = timedelta(days=1)
ACHIEVEMENTS_CACHE = timedelta(days=1)
PLAYER_COUNT_CACHE = timedelta(minutes=5)
COMPATIBILITY_CACHE = timedelta(days=3)
NEWS_CACHE = timedelta(hours=1)
EVENTS_CACHE = timedelta(hours=1)

# --- reviews -------------------------------------------------------------------
REVIEWS_CACHE = timedelta(minutes=30)
REVIEW_SUMMARY_CACHE = timedelta(hours=3)
HISTOGRAM_CACHE = timedelta(hours=12)

# --- community -------------------------------------------------------------------
GUIDES_CACHE = timedelta(hours=6)
GUIDE_CACHE = timedelta(days=1)
DISCUSSIONS_CACHE = timedelta(minutes=15)
WORKSHOP_CACHE = timedelta(hours=3)
WORKSHOP_ITEM_CACHE = timedelta(hours=6)

# --- charts ------------------------------------------------------------------------
LIVE_CHART_CACHE = timedelta(minutes=10)
DAILY_CHART_CACHE = timedelta(hours=3)
WEEKLY_CHART_CACHE = timedelta(hours=6)
TOP_RELEASES_CACHE = timedelta(days=1)

# --- creators / curators --------------------------------------------------------------
CREATOR_CACHE = timedelta(hours=6)
CURATORS_CACHE = timedelta(hours=12)
CURATOR_REVIEWS_CACHE = timedelta(hours=6)

# --- users / groups --------------------------------------------------------------------
USER_CACHE = timedelta(hours=1)
USER_LIST_CACHE = timedelta(hours=3)
INVENTORY_CACHE = timedelta(minutes=30)
GROUP_CACHE = timedelta(hours=6)

# --- market -------------------------------------------------------------------------------
MARKET_SEARCH_CACHE = timedelta(minutes=15)
MARKET_ITEM_CACHE = timedelta(minutes=5)
MARKET_BOOK_CACHE = timedelta(minutes=1)
MARKET_HISTORY_CACHE = timedelta(hours=1)
MARKET_FILTERS_CACHE = timedelta(days=3)
