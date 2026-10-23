# 🎮 Steam Scraper

Steam Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Steam data for free.

## ✨ What Can I Get?

- 🎮 **Full details on 130K+ Steam games** — price, reviews, tags, requirements, Deck status & trailers
- 💬 **Millions of user reviews** — filter by verdict, language, playtime & purchase type
- 💰 **530K+ Community Market items** — live order book, full price history & 24h volume
- 📈 **Charts, profiles & Workshop** — most played, top sellers, inventories, wishlists & mods

## 🎥 Example: A Full Steam Game

```json
{
  "id": 1245620,
  "name": "ELDEN RING",
  "link": "https://store.steampowered.com/app/1245620/ELDEN_RING/",
  "release_date": "2022-02-24",
  "price": { "amount": 59.99, "original_amount": 59.99, "discount_percent": 0, "currency": "USD" },
  "current_players": 34941,
  "reviews": {
    "overall": { "label": "Very Positive", "total": 831470, "percent_positive": 93 }
  },
  "metacritic": { "score": 94 },
  "developers": ["FromSoftware, Inc."],
  "publishers": ["FromSoftware, Inc.", "Bandai Namco Entertainment"],
  "tags": [
    { "id": 29482, "name": "Souls-like", "weight": 1078 },
    { "id": 1695, "name": "Open World", "weight": 790 }
  ],
  "compatibility": { "steam_deck": "verified", "steam_os": "compatible" },
  "requirements": {
    "windows": {
      "minimum": {
        "specs": { "os": "Windows 10", "memory": "12 GB RAM", "graphics": "NVIDIA GEFORCE GTX 1060 3 GB or AMD RADEON RX 580 4 GB" }
      }
    }
  },
  "languages": [{ "name": "English", "has_full_audio": true, "has_subtitles": true }],
  "media": {
    "trailers": [{ "name": "ELDEN RING - Accolades Trailer", "hls": "https://video.akamai.steamstatic.com/store_trailers/1245620/468143/7a6be00f78fb0fd8b419e92cea72cc4a19ec45f8/1750650501/hls_264_master.m3u8?t=1716311566" }]
  }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Steam Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/steam-scraper
cd steam-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/games/details?game=1245620"
```

```json
{
  "id": 1245620,
  "type": "game",
  "name": "ELDEN RING",
  "link": "https://store.steampowered.com/app/1245620/ELDEN_RING/",
  "release_date": "2022-02-24",
  "price": { "amount": 59.99, "original_amount": 59.99, "discount_percent": 0, "currency": "USD", "is_free": false, "discount_ends_at": null },
  "current_players": 34941,
  "reviews": {
    "overall": { "score": 8, "label": "Very Positive", "total": 831470, "percent_positive": 93 },
    "in_language": { "score": 8, "label": "Very Positive", "total": 435387, "percent_positive": 94 }
  },
  "developers": ["FromSoftware, Inc."],
  "genres": [{ "id": 1, "name": "Action" }, { "id": 3, "name": "RPG" }],
  "compatibility": { "steam_deck": "verified", "steam_os": "compatible", "steam_machine": "verified", "steam_frame": "unknown" },
  "tags": [
    { "id": 29482, "name": "Souls-like", "weight": 1078 },
    { "id": 1695, "name": "Open World", "weight": 790 }
  ]
}
```

All 50 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

50 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Game Details | `/games/details` | Everything on a store page in one call |
| Autocomplete | `/search/autocomplete` | Instant matches as you type, with price and reviews |
| Search Store | `/search` | 25 per page with every store filter and a total count |
| Browse Games | `/games/browse` | The whole catalogue by tags, sorted by trending or top sellers |
| Game Reviews / Summary / History | `/games/reviews`, `/games/reviews/summary`, `/games/reviews/histogram` | Full reviews, score breakdowns and lifetime review trends |
| Regional Prices | `/games/prices` | One game's price in up to 40 countries at once |
| Live Player Count | `/games/player-count` | Players in-game right now |
| DLC / Similar Games | `/games/dlc`, `/games/similar` | Every DLC and the games Steam calls similar |
| Achievements / Deck Compatibility | `/games/achievements`, `/games/compatibility` | Unlock rates and Valve's tested Deck verdicts |
| News / Events | `/games/news`, `/games/events` | Patch notes, announcements, sales and streams as clean text |
| Charts | `/charts/most-played`, `/charts/concurrent-players`, `/charts/top-sellers`, `/charts/top-releases` | Most played, live players, weekly top sellers, monthly top releases |
| Featured & Specials | `/featured` | Spotlights, daily deal, specials and new releases |
| Market Search / Autocomplete | `/market/search`, `/market/autocomplete` | Market items with lowest price and listing count |
| Market Item / History / Order Book | `/market/items/details`, `/market/items/price-history`, `/market/items/order-book` | Live bids and asks plus the item's full sales history |
| Market Filters | `/market/filters` | Every exterior, rarity and weapon filter with item counts |
| User Profile / Resolve ID | `/users/profile`, `/users/resolve` | Level, status, bans, counts and every Steam ID format |
| Friends / Badges / Groups | `/users/friends`, `/users/badges`, `/users/groups` | A public profile's social graph and badge collection |
| User Reviews / Achievements | `/users/reviews`, `/users/achievements` | What a player wrote and what they unlocked |
| Wishlist / Inventory | `/users/wishlist`, `/users/inventory` | Wishlisted games and every item a player owns |
| Guides | `/games/guides`, `/guides/details` | Community guides with full section text |
| Discussions | `/games/discussions` | Forum topics with replies and last post time |
| Workshop | `/games/workshop`, `/workshop/items/details`, `/workshop/collections/details` | Mods, maps and skins with subscriber stats |
| Developer & Publisher Games | `/creators/games` | Every product from one studio or franchise |
| Curators | `/curators`, `/curators/reviews` | Top curators and every review they wrote |
| Groups | `/groups/details`, `/groups/members` | Group profile and full member list |
| Packages / Bundles | `/packages/details`, `/bundles/details` | Editions and bundles with prices and included games |
| Tags / Categories | `/tags`, `/categories` | Every filter ID the store uses |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-steam-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-steam-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-steam-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/games/details",
    params={"game": "https://store.steampowered.com/app/1245620/ELDEN_RING/"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Steam Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Steam%20Scraper%20API.)

[![Ask Us by Email about Steam Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Steam%20Scraper%20API&body=I%20need%20help%20using%20the%20Steam%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/steam-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/steam-scraper)
