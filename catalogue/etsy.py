"""Etsy catalogue source. STUB: written from Etsy's Open API v3 documentation but never
run against the live API, because there is no key yet. Expect to adjust it on first use.

How it works:
  1. For each thing the recipient asked for or is interested in, search active listings
     within the price range.                      GET /v3/application/listings/active
  2. Fetch images and shop names for the results. GET /v3/application/listings/batch
  3. Convert each listing to a Product so matching.py can rank it.

Auth: every request needs the header  x-api-key: <keystring>:<shared secret>
(both parts have been mandatory since February 2026). Searching public listings needs no
user login. Docs: https://developer.etsy.com/documentation/essentials/requests

Known gaps to close once the key arrives:
  - Etsy listings carry no age range, usefulness or "too personal" label, so every
    listing gets the neutral default. Step 4 (model-based judging) is what fills these in.
  - No caching or rate-limit handling yet.
  - Prices are assumed to be in USD.
"""
from __future__ import annotations

import requests

from matching import search_phrase, terms
from models import Product

from . import CatalogueError

BASE = "https://api.etsy.com/v3/application"
MAX_SEARCHES = 5  # searches per recipient, to stay well inside Etsy's rate limits
PER_SEARCH = 10
TIMEOUT = 10


class EtsySource:
    name = "etsy"

    def __init__(self, keystring: str, shared_secret: str):
        if not keystring or not shared_secret:
            raise CatalogueError(
                "Etsy is selected but ETSY_KEYSTRING or ETSY_SHARED_SECRET is missing from .env. "
                'Add them, or set CATALOGUE_SOURCE=sample.')
        self._headers = {"x-api-key": f"{keystring}:{shared_secret}", "Accept": "application/json"}

    def _get(self, path: str, params: dict) -> dict:
        try:
            resp = requests.get(f"{BASE}{path}", headers=self._headers, params=params, timeout=TIMEOUT)
        except requests.RequestException:
            raise CatalogueError("Could not reach Etsy. Check the internet connection and try again.")
        if resp.status_code in (401, 403):
            raise CatalogueError("Etsy rejected the API key. Check the keystring and shared secret in .env.")
        if resp.status_code == 429:
            raise CatalogueError("Etsy's rate limit was hit. Wait a minute and try again.")
        if not resp.ok:
            raise CatalogueError(f"Etsy returned an error ({resp.status_code}).")
        return resp.json()

    def candidates(self, recipient) -> list[Product]:
        # Asked-for terms first: they matter most and searches are capped.
        queries = (terms(recipient.asked) + terms(recipient.interests))[:MAX_SEARCHES]
        found: dict[int, tuple[dict, str]] = {}
        for q in queries:
            params = {"keywords": search_phrase(q), "limit": PER_SEARCH, "min_price": recipient.min_price}
            if recipient.max_price is not None:
                params["max_price"] = recipient.max_price
            for listing in self._get("/listings/active", params).get("results", []):
                found.setdefault(listing["listing_id"], (listing, q))
        if not found:
            return []
        details = self._get("/listings/batch", {
            "listing_ids": ",".join(str(i) for i in found), "includes": "Images,Shop"})
        extra = {d["listing_id"]: d for d in details.get("results", [])}
        return [to_product(listing, query, extra.get(lid, {})) for lid, (listing, query) in found.items()]


def to_product(listing: dict, query: str, extra: dict | None = None) -> Product:
    """Convert one Etsy listing to a Product. `query` is the search term that found it,
    added as a tag so the matching step credits the right interest."""
    extra = extra or {}
    price = listing.get("price") or {}
    amount = price.get("amount", 0) / (price.get("divisor") or 1)
    images = extra.get("images") or []
    shop = (extra.get("shop") or {}).get("shop_name") or "Etsy shop"
    tags = [t.lower() for t in listing.get("tags", [])]
    if query not in tags:
        tags.append(query)
    return Product(
        id=f"etsy-{listing['listing_id']}", name=listing.get("title", "Etsy listing"), shop=shop,
        price=round(amount, 2), tags=tags, url=listing.get("url", ""),
        image_url=images[0].get("url_570xN", "") if images else "")
