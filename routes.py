"""The 50 Steam endpoints. Every path is served with and without the
`/steam` prefix, so code generated against the hosted API on RapidAPI
(paths like /games/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in steam/schemas.py (unknown
params are rejected with a 400), responses have the same shape as the hosted
API: paginated lists carry count / per_page / current_page / total_pages /
next / previous."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from schema_fields import load_query
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from steam import (charts, community, creators, games, groups, market, reviews, schemas,  # noqa: F401
                   store, users)


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _page_link(path, params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "", False)}
    query["page"] = page
    return f"{request.urlparts.scheme}://{request.urlparts.netloc}{path}?{urlencode(query, doseq=True)}"


def paginate(result, path, raw_params):
    """Lift the endpoint's `pagination` block into the flat response shape
    with next / previous links built from the caller's own params."""
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = _as_int(pagination.get("page")) or _as_int(raw_params.get("page")) or 1
    total_pages = max(_as_int(pagination.get("total_pages")), 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(path, raw_params, page + 1 if page < total_pages else None),
        "previous": _page_link(path, raw_params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(path, schema, impl, paginated):
    """Validate the query, run the scraper function, map errors: bad params
    -> 400, missing entity -> 404, Steam blocking / failing -> 502, anything
    else -> 500."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    label = path.strip("/")
    try:
        result = impl(**data)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"steam rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Blocked as e:
        return json_response({"error": f"steam blocked the request, retry later: {e}"}, 502)
    except UpstreamError as e:
        return json_response({"error": f"steam {label} failed: {e}"}, 502)
    except Exception as e:
        return json_response({"error": f"steam {label} failed: {type(e).__name__}: {e}"}, 500)
    if paginated:
        result = paginate(result, request.path, raw)
    return json_response(result)


# (public path, request schema, scraper function, paginated) — in the API's documented order
ENDPOINTS = [
    ("/games/details", schemas.GameStorefrontSchema, games.details, False),
    ("/search/autocomplete", schemas.AutocompleteSchema, store.autocomplete, False),
    ("/search", schemas.StoreSearchSchema, store.search, True),
    ("/games/browse", schemas.BrowseSchema, store.browse, True),
    ("/games/reviews", schemas.ReviewsSchema, reviews.reviews, False),
    ("/games/reviews/summary", schemas.GameLanguageSchema, reviews.summary, False),
    ("/games/reviews/histogram", schemas.GameLanguageSchema, reviews.histogram, False),
    ("/games/prices", schemas.GamePricesSchema, games.prices, False),
    ("/games/player-count", schemas.GameSchema, games.player_count, False),
    ("/games/dlc", schemas.GameDlcSchema, games.dlc, True),
    ("/games/similar", schemas.GameSimilarSchema, games.similar, False),
    ("/games/achievements", schemas.GameLanguageSchema, games.achievements, False),
    ("/games/compatibility", schemas.GameSchema, games.compatibility, False),
    ("/games/news", schemas.GameNewsSchema, games.news, False),
    ("/games/events", schemas.GameEventsSchema, games.events, False),
    ("/charts/most-played", schemas.ChartSchema, charts.most_played, False),
    ("/charts/concurrent-players", schemas.ChartSchema, charts.concurrent_players, False),
    ("/charts/top-sellers", schemas.TopSellersSchema, charts.top_sellers, True),
    ("/charts/top-releases", schemas.TopReleasesSchema, charts.top_releases, False),
    ("/featured", schemas.StorefrontSchema, store.featured, False),
    ("/market/search", schemas.MarketSearchSchema, market.search, True),
    ("/market/autocomplete", schemas.MarketQuerySchema, market.autocomplete, False),
    ("/market/items/details", schemas.MarketItemSchema, market.item, False),
    ("/market/items/price-history", schemas.MarketHistorySchema, market.price_history, False),
    ("/market/items/order-book", schemas.MarketBookSchema, market.order_book, False),
    ("/market/filters", schemas.MarketGameSchema, market.filters, False),
    ("/users/profile", schemas.UserSchema, users.profile, False),
    ("/users/resolve", schemas.UserSchema, users.resolve, False),
    ("/users/friends", schemas.UserSchema, users.friends, False),
    ("/users/badges", schemas.UserSchema, users.badges, False),
    ("/users/reviews", schemas.UserPagedSchema, users.reviews, True),
    ("/users/achievements", schemas.UserAchievementsSchema, users.achievements, False),
    ("/users/wishlist", schemas.WishlistSchema, users.wishlist, True),
    ("/users/inventory", schemas.InventorySchema, users.inventory, False),
    ("/users/groups", schemas.UserSchema, users.groups, False),
    ("/games/guides", schemas.GuidesSchema, community.guides, True),
    ("/guides/details", schemas.GuideSchema, community.guide, False),
    ("/games/discussions", schemas.DiscussionsSchema, community.discussions, True),
    ("/games/workshop", schemas.WorkshopSchema, community.workshop, True),
    ("/workshop/items/details", schemas.WorkshopItemSchema, community.workshop_item, False),
    ("/workshop/collections/details", schemas.CollectionSchema, community.collection, False),
    ("/creators/games", schemas.CreatorGamesSchema, creators.games, True),
    ("/curators", schemas.CuratorsSchema, creators.curators, True),
    ("/curators/reviews", schemas.CuratorReviewsSchema, creators.curator_reviews, True),
    ("/groups/details", schemas.GroupSchema, groups.details, False),
    ("/groups/members", schemas.GroupMembersSchema, groups.members, True),
    ("/packages/details", schemas.PackageSchema, store.package, False),
    ("/bundles/details", schemas.BundleSchema, store.bundle, False),
    ("/tags", schemas.LanguageOnlySchema, store.tags, False),
    ("/categories", schemas.LanguageOnlySchema, store.categories, False),]


def mount(path, schema, impl, paginated):
    """Serve one endpoint at /path and /steam/path."""
    def handler():
        return call(path, schema, impl, paginated)
    handler.__name__ = "steam_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/steam" + path, method="GET")(handler)


for _endpoint in ENDPOINTS:
    mount(*_endpoint)


@route("/", method="GET")
@route("/health", method="GET")
@route("/steam/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [e[0] for e in ENDPOINTS]})
