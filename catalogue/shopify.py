"""Shopify catalogue source: one search across every Shopify merchant.

Written from Shopify's Global Catalog documentation and its example response. It could not
be run against Shopify from the build environment, so the first live run is the real test.

How it works:
  1. For each thing the recipient asked for or is interested in, call the `search_catalog`
     tool at https://catalog.shopify.com/api/ucp/mcp with the price range and US shipping.
  2. Convert each result to a Product so matching.py can rank it.

Auth: no API key. Each request names an "agent profile", a small public JSON file that says
what this app can do. Ours is served by this app at /ucp-agent-profile.json. If Shopify
rejects it, the code falls back to Shopify's own example profile and logs a warning.
Docs: https://shopify.dev/docs/agents/catalog/global-catalog

Shopify's usage rules that matter here:
  - Show results to shoppers only; no bulk harvesting or building a copy of the catalogue.
  - Do not keep prices or availability for more than 10 minutes. This app stores nothing:
    every search is live.
  - Leave product and checkout links exactly as Shopify returns them.

Known gaps:
  - Listings carry no age range, usefulness or "too personal" label, so each gets the
    neutral default. For children the search phrase adds "for kids" or "for teens", which
    is a hint to Shopify's search, not a safety filter.
  - Only products priced in USD are kept.
"""
from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import requests

import rules
from matching import search_phrase, terms
from models import Product

from . import CatalogueError

log = logging.getLogger(__name__)

ENDPOINT = "https://catalog.shopify.com/api/ucp/mcp"
EXAMPLE_PROFILE = "https://shopify.dev/ucp/agent-profiles/examples/2026-08-25/valid-with-capabilities.json"
MAX_SEARCHES = 5  # searches per recipient
PER_SEARCH = 10
TIMEOUT = 15


class ShopifySource:
    name = "shopify"

    def __init__(self, profile_url: str = ""):
        self._profile = profile_url or EXAMPLE_PROFILE

    # ---- one search
    def _call(self, catalog: dict, profile: str) -> dict:
        body = {"jsonrpc": "2.0", "method": "tools/call", "id": 1, "params": {
            "name": "search_catalog",
            "arguments": {"meta": {"ucp-agent": {"profile": profile}}, "catalog": catalog}}}
        try:
            resp = requests.post(ENDPOINT, json=body, timeout=TIMEOUT, headers={
                "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        except requests.RequestException:
            raise CatalogueError("Could not reach Shopify. Try again in a moment.")
        if resp.status_code == 429:
            raise CatalogueError("Shopify's rate limit was hit. Wait a minute and try again.")
        if not resp.ok:
            raise CatalogueError(f"Shopify returned an error ({resp.status_code}).")
        return parse_response(resp.text)

    def _search(self, catalog: dict) -> list[dict]:
        try:
            return self._call(catalog, self._profile)
        except CatalogueError as first:
            if self._profile == EXAMPLE_PROFILE:
                raise
            # Our own profile may be unreachable or malformed; Shopify's example one is known good.
            log.warning("Shopify search failed with our agent profile (%s). Retrying with the example profile.", first)
            result = self._call(catalog, EXAMPLE_PROFILE)
            self._profile = EXAMPLE_PROFILE
            return result

    # ---- all searches for one recipient
    def candidates(self, recipient) -> list[Product]:
        band = rules.AGE_BANDS.get(recipient.age)
        oldest = band[2] if band else 99
        suffix = " for kids" if oldest < 13 else " for teens" if oldest < 18 else ""
        price = {"min": int(round(recipient.min_price * 100))}
        if recipient.max_price is not None:
            price["max"] = int(round(recipient.max_price * 100))
        # Asked-for terms first: they matter most and searches are capped.
        queries = (terms(recipient.asked) + terms(recipient.interests))[:MAX_SEARCHES]
        if not queries:
            return []

        def one(q: str) -> list[Product]:
            catalog = {
                "query": search_phrase(q) + suffix,
                "context": {"address_country": "US", "currency": "USD", "intent": "Looking for a Christmas gift"},
                "filters": {"ships_to": {"country": "US"}, "available": True, "price": price},
                "pagination": {"limit": PER_SEARCH},
            }
            return [p for p in (to_product(raw, q) for raw in self._search(catalog)) if p]

        # The first search runs alone so a profile fallback is settled before the rest go out together.
        found = one(queries[0])
        if len(queries) > 1:
            with ThreadPoolExecutor(max_workers=4) as pool:
                for batch in pool.map(one, queries[1:]):
                    found.extend(batch)
        unique: dict[str, Product] = {}
        for p in found:
            unique.setdefault(p.id, p)
        return list(unique.values())


def parse_response(text: str) -> list[dict]:
    """Pull the product list out of Shopify's reply. Handles plain JSON and the
    'event-stream' form (lines starting with 'data:')."""
    payload = None
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except ValueError:
            payload = None
    else:
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    candidate = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if isinstance(candidate, dict) and ("result" in candidate or "error" in candidate):
                    payload = candidate
    if not isinstance(payload, dict):
        raise CatalogueError("Shopify sent a reply this app could not read.")
    if "error" in payload:
        message = (payload["error"] or {}).get("message", "unknown error")
        raise CatalogueError(f"Shopify rejected the search: {message}")
    result = payload.get("result") or {}
    content = result.get("structuredContent")
    if content is None:  # older servers put the same JSON inside a text block
        for block in result.get("content") or []:
            if block.get("type") == "text":
                try:
                    content = json.loads(block["text"])
                    break
                except (ValueError, KeyError):
                    if result.get("isError"):
                        raise CatalogueError(f"Shopify rejected the search: {block.get('text', '')[:200]}")
    if result.get("isError") or not isinstance(content, dict):
        raise CatalogueError("Shopify rejected the search.")
    return content.get("products") or []


def to_product(raw: dict, query: str) -> Product | None:
    """Convert one Shopify catalogue result to a Product. `query` is the search term that
    found it, added as a tag so the matching step credits the right interest.
    Returns None for results this app cannot show (no price, or not in USD)."""
    low = ((raw.get("price_range") or {}).get("min")) or {}
    variants = raw.get("variants") or []
    first = variants[0] if variants else {}
    if "amount" not in low:
        low = first.get("price") or {}
    if "amount" not in low or low.get("currency", "USD") != "USD":
        return None
    title = raw.get("title") or first.get("title") or "Shopify product"
    image = next((m.get("url", "") for m in raw.get("media") or [] if m.get("type") == "image"), "")
    tags = [str(t).lower() for t in first.get("tags") or []]
    for cat in raw.get("categories") or []:
        if cat.get("taxonomy") == "merchant":
            tags += [part.strip().lower() for part in str(cat.get("value", "")).split(">") if part.strip()]
    if query not in tags:
        tags.append(query)
    gid = str(raw.get("id") or first.get("id") or title)
    safe_id = re.sub(r"[^A-Za-z0-9]+", "-", gid.rsplit("/", 1)[-1]).strip("-") or "item"
    return Product(
        id=f"shopify-{safe_id}", name=title, shop=(first.get("seller") or {}).get("name") or "Shopify shop",
        price=round(low["amount"] / 100, 2), tags=tags, url=raw.get("url", ""), image_url=image,
        is_gift_card="gift card" in title.lower())
