"""Marshmallow request schemas for every /steam/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Steam resolvers and per-route schemas. Every schema's load()
output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrLinkField convention, never a
sibling `url`/`id` pair): `game`, `package`, `bundle` take an id OR a store
link; `user` a steamid64 / STEAM_0:x:y / [U:1:n] / account id / vanity name
OR a profile link; `group` a name / 64-bit id OR a group link; `guide`,
`item` (workshop), `collection` a published file id OR its link;
`creator` a slug OR a developer / publisher / franchise link; `curator` an
id OR a curator link; the market `item` a market hash name OR a listing
link (refs.py).
"""
from marshmallow import ValidationError, fields, validate

from steam import refs
from steam.community import GUIDE_SORTS, WORKSHOP_PERIODS, WORKSHOP_SORTS
from steam.market import HISTORY_PERIODS, SEARCH_SORTS as MARKET_SORTS
from steam.reviews import PURCHASE_TYPES, REVIEW_SORTS, REVIEW_TYPES
from steam.shared import LANGUAGES
from steam.store import BROWSE_SORTS, BROWSE_TYPES, DECK_FILTER, SEARCH_LISTS, SEARCH_OS, SEARCH_SORTS, SEARCH_TYPES
from schema_fields import (BaseSchema, ChoiceField, CommaListField, CountryCodeField, DateField, Flag, LimitField,
                           NonNegativeNumber, PageField, PositiveInt, QueryField, RefField, StrippedString,
                           YearMonthField)


# ---- resolver fields --------------------------------------------------------------------------------------------

class AppRefField(RefField):
    resolver = staticmethod(refs.resolve_app)


class PackageRefField(RefField):
    resolver = staticmethod(refs.resolve_package)


class BundleRefField(RefField):
    resolver = staticmethod(refs.resolve_bundle)


class UserRefField(RefField):
    resolver = staticmethod(refs.resolve_user)


class GroupRefField(RefField):
    resolver = staticmethod(refs.resolve_group)


class FileRefField(RefField):
    resolver = staticmethod(refs.resolve_file)


class CreatorRefField(RefField):
    resolver = staticmethod(refs.resolve_creator)


class CuratorRefField(RefField):
    resolver = staticmethod(refs.resolve_curator)


class MarketItemField(RefField):
    resolver = staticmethod(refs.resolve_market_item)


class LanguageField(ChoiceField):
    """ISO language code (en, de, fr, pt-BR, zh-CN, es-419 …) -> Steam's
    language name; `allow_all` adds "all" (every language)."""

    def __init__(self, allow_all=False, **kwargs):
        choices = dict(LANGUAGES)
        if allow_all:
            choices["all"] = "all"
        super().__init__(choices, **kwargs)


class TagIdsField(CommaListField):
    """Comma-separated store tag ids (from /steam/tags): '19,122'."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_items", 10)
        super().__init__(upper=False, **kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        items = super()._deserialize(value, attr, data, **kwargs)
        if items is None:
            return None
        out = []
        for item in items:
            if not item.isdigit():
                raise ValidationError(f"'{item}' is not a tag id — use the numeric ids from /steam/tags (e.g. 19,122).")
            out.append(int(item))
        return out


class GameIdField(PositiveInt):
    """A Steam app id (market / inventory game): 730, 440, 570, 753 …"""


class CountryField(CountryCodeField):
    """Storefront country (ISO code): prices and availability follow it."""


# ---- store --------------------------------------------------------------------------------------------------------

class StoreSearchSchema(BaseSchema):
    query = StrippedString(load_default=None, validate=validate.Length(min=1, max=200))
    page = PageField(max_page=1000)
    sort = ChoiceField(list(SEARCH_SORTS), load_default="relevance")
    section = ChoiceField(list(SEARCH_LISTS))
    types = CommaListField(allowed=list(SEARCH_TYPES), upper=False, max_items=5)
    tags = TagIdsField()
    max_price = NonNegativeNumber()
    discounted_only = Flag(load_default=False)
    hide_free = Flag(load_default=False)
    os = CommaListField(allowed=list(SEARCH_OS), upper=False, max_items=3)
    steam_deck = ChoiceField(list(DECK_FILTER))
    supported_language = LanguageField()
    country = CountryField()
    language = LanguageField()


class AutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100)
    limit = LimitField(default=10, max_size=25)
    country = CountryField()
    language = LanguageField()


class BrowseSchema(BaseSchema):
    sort = ChoiceField(list(BROWSE_SORTS), load_default="relevance")
    types = CommaListField(allowed=list(BROWSE_TYPES), upper=False, max_items=10)
    tags = TagIdsField()
    free_only = Flag(load_default=False)
    hide_free = Flag(load_default=False)
    min_discount = PositiveInt(max_value=100)
    coming_soon_only = Flag(load_default=False)
    top_sellers_only = Flag(load_default=False)
    page = PageField(max_page=2000)
    limit = LimitField(default=25, max_size=50)
    country = CountryField()
    language = LanguageField()


class StorefrontSchema(BaseSchema):
    country = CountryField()
    language = LanguageField()


class LanguageOnlySchema(BaseSchema):
    language = LanguageField()


class PackageSchema(BaseSchema):
    package = PackageRefField()
    country = CountryField()
    language = LanguageField()


class BundleSchema(BaseSchema):
    bundle = BundleRefField()
    country = CountryField()
    language = LanguageField()


# ---- games ----------------------------------------------------------------------------------------------------------

class GameSchema(BaseSchema):
    game = AppRefField()


class GameStorefrontSchema(BaseSchema):
    game = AppRefField()
    country = CountryField()
    language = LanguageField()


class GameLanguageSchema(BaseSchema):
    game = AppRefField()
    language = LanguageField()


class GamePricesSchema(BaseSchema):
    game = AppRefField()
    countries = CommaListField(max_items=40)

    def load(self, data, **kwargs):
        out = super().load(data, **kwargs)
        from schema_fields import COUNTRY_CODES
        bad = [c for c in out.get("countries") or [] if c not in COUNTRY_CODES]
        if bad:
            raise ValidationError({"countries": [f"Not ISO country codes: {', '.join(bad)} (use US,GB,DE,IN …)."]})
        return out


class GameDlcSchema(BaseSchema):
    game = AppRefField()
    page = PageField(max_page=100)
    limit = LimitField(default=25, max_size=50)
    country = CountryField()
    language = LanguageField()


class GameSimilarSchema(BaseSchema):
    game = AppRefField()
    limit = LimitField(default=20, max_size=30)
    country = CountryField()
    language = LanguageField()


class GameNewsSchema(BaseSchema):
    game = AppRefField()
    limit = LimitField(default=20, max_size=100)
    before = DateField(bound="past")
    official_only = Flag(load_default=False)
    patch_notes_only = Flag(load_default=False)


class GameEventsSchema(BaseSchema):
    game = AppRefField()
    limit = LimitField(default=10, max_size=30)
    language = LanguageField()


class ReviewsSchema(BaseSchema):
    game = AppRefField()
    sort = ChoiceField(list(REVIEW_SORTS), load_default="recent")
    review_type = ChoiceField(REVIEW_TYPES, load_default="all")
    purchase_type = ChoiceField(list(PURCHASE_TYPES), load_default="all")
    language = LanguageField(allow_all=True, load_default="all")
    day_range = PositiveInt(max_value=365)
    playtime_min = PositiveInt(max_value=100000)
    playtime_max = PositiveInt(max_value=100000)
    include_off_topic = Flag(load_default=False)
    cursor = StrippedString(load_default=None, validate=validate.Length(min=1, max=200))
    limit = LimitField(default=20, max_size=100)


class GuidesSchema(BaseSchema):
    game = AppRefField()
    sort = ChoiceField(list(GUIDE_SORTS), load_default="trending")
    query = StrippedString(load_default=None, validate=validate.Length(min=1, max=100))
    category = StrippedString(load_default=None, validate=validate.Length(min=1, max=60))
    page = PageField(max_page=500)
    language = LanguageField()


class DiscussionsSchema(BaseSchema):
    game = AppRefField()
    page = PageField(max_page=500)
    language = LanguageField()


class WorkshopSchema(BaseSchema):
    game = AppRefField()
    sort = ChoiceField(list(WORKSHOP_SORTS), load_default="trending")
    period = ChoiceField(list(WORKSHOP_PERIODS), load_default="week")
    query = StrippedString(load_default=None, validate=validate.Length(min=1, max=100))
    page = PageField(max_page=1000)


# ---- charts ------------------------------------------------------------------------------------------------------------

class ChartSchema(BaseSchema):
    limit = LimitField(default=100, max_size=100)
    country = CountryField()
    language = LanguageField()


class TopSellersSchema(BaseSchema):
    country = CountryField()
    week = DateField(bound="past")
    page = PageField(max_page=40)
    limit = LimitField(default=25, max_size=100)
    language = LanguageField()


class TopReleasesSchema(BaseSchema):
    month = YearMonthField(bound="past")
    country = CountryField()
    language = LanguageField()


# ---- creators / curators -------------------------------------------------------------------------------------------------

class CreatorGamesSchema(BaseSchema):
    creator = CreatorRefField()
    # no `query`: ajaxgetfilteredrecommendations ignores its query param (same total for any text)
    page = PageField(max_page=500)
    limit = LimitField(default=24, max_size=50)
    country = CountryField()
    language = LanguageField()


class CuratorsSchema(BaseSchema):
    page = PageField(max_page=500)
    limit = LimitField(default=20, max_size=50)
    language = LanguageField()


class CuratorReviewsSchema(BaseSchema):
    curator = CuratorRefField()
    page = PageField(max_page=500)
    limit = LimitField(default=20, max_size=50)
    country = CountryField()
    language = LanguageField()


# ---- users / groups -------------------------------------------------------------------------------------------------------

class UserSchema(BaseSchema):
    user = UserRefField()


class UserPagedSchema(BaseSchema):
    user = UserRefField()
    page = PageField(max_page=500)


class UserAchievementsSchema(BaseSchema):
    user = UserRefField()
    game = AppRefField()


class WishlistSchema(BaseSchema):
    user = UserRefField()
    page = PageField(max_page=500)
    limit = LimitField(default=25, max_size=100)
    country = CountryField()
    language = LanguageField()


class InventorySchema(BaseSchema):
    user = UserRefField()
    game = GameIdField(load_default=730)
    context_id = PositiveInt(load_default=2, max_value=100)
    cursor = StrippedString(load_default=None, validate=validate.Regexp(r"^\d{1,25}$", error="Must be the next_cursor value."))
    limit = LimitField(default=100, max_size=1000)
    language = LanguageField()


class GroupSchema(BaseSchema):
    group = GroupRefField()


class GroupMembersSchema(BaseSchema):
    group = GroupRefField()
    page = PageField(max_page=10000)


# ---- workshop / guides ----------------------------------------------------------------------------------------------------

class GuideSchema(BaseSchema):
    guide = FileRefField()


class WorkshopItemSchema(BaseSchema):
    item = FileRefField()


class CollectionSchema(BaseSchema):
    collection = FileRefField()


# ---- market ----------------------------------------------------------------------------------------------------------------------

class MarketSearchSchema(BaseSchema):
    query = StrippedString(load_default=None, validate=validate.Length(min=1, max=200))
    game = GameIdField()
    filters = CommaListField(upper=False, max_items=10)
    sort = ChoiceField(list(MARKET_SORTS), load_default="popular")
    order = ChoiceField(["asc", "desc"], load_default="desc")
    search_descriptions = Flag(load_default=False)
    page = PageField(max_page=1000)

    def load(self, data, **kwargs):
        out = super().load(data, **kwargs)
        for f in out.get("filters") or []:
            if ":" not in f:
                raise ValidationError({"filters": [f"'{f}' must look like Facet:TagId (e.g. Exterior:WearCategory0) — see /steam/market/filters."]})
        if out.get("filters") and not out.get("game"):
            raise ValidationError({"filters": ["filters need a game (the facets belong to one game's market)."]})
        return out


class MarketQuerySchema(BaseSchema):
    query = QueryField(max_length=100)


class MarketGameSchema(BaseSchema):
    game = AppRefField()


class MarketItemSchema(BaseSchema):
    item = MarketItemField()
    game = GameIdField()
    country = CountryField()


class MarketHistorySchema(BaseSchema):
    item = MarketItemField()
    game = GameIdField()
    country = CountryField()
    period = ChoiceField(list(HISTORY_PERIODS), load_default="month")


class MarketBookSchema(BaseSchema):
    item = MarketItemField()
    game = GameIdField()
    country = CountryField()
    depth = LimitField(default=50, max_size=500)
