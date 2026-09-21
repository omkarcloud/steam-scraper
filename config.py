"""Configuration for the Steam Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT                   port the API listens on (default 8000)
    STEAM_PROXY            proxy URL for every request, e.g. http://user:pass@host:port
                           (default: none — direct). Steam has no bot protection;
                           it only refuses datacenter IPs and rate-limits bursts,
                           so from a home or office connection you don't need this.
    STEAM_FALLBACK_PROXY   proxy a request thread switches to for
                           STEAM_DIRECT_COOLDOWN seconds after Steam answers 429
                           (store search allows ~40 quick calls per IP, market
                           prices ~20 a minute). Default: none — the 429 is returned.
    STEAM_EGRESS_COUNTRY   2-letter country of your own IP (default US). Market
                           prices come in the currency of the IP's country; a
                           `country` param other than this one is served through
                           STEAM_PROXY when set (else your own IP's currency, and
                           the response's `currency` field says which).
    STEAM_WEB_API_KEY      optional Steam Web API key (free at
                           steamcommunity.com/dev/apikey). No endpoint here needs it.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

STEAM_PROXY = os.environ.get("STEAM_PROXY") or None
STEAM_DIRECT_COOLDOWN = int(os.environ.get("STEAM_DIRECT_COOLDOWN", "300"))
STEAM_EGRESS_COUNTRY = (os.environ.get("STEAM_EGRESS_COUNTRY") or "US").upper()
STEAM_WEB_API_KEY = os.environ.get("STEAM_WEB_API_KEY") or None


def steam_proxy():
    """The proxy every session uses (None = direct)."""
    return os.environ.get("STEAM_PROXY") or None


def steam_fallback_proxy():
    """The proxy a thread moves to after a 429 (None = no fallback)."""
    return os.environ.get("STEAM_FALLBACK_PROXY") or None


def steam_country_proxy(country):
    """The proxy for market prices in another country's currency."""
    return os.environ.get("STEAM_PROXY") or None
