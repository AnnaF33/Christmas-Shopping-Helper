"""Where products come from.

Every source has a `name` and a `candidates(recipient)` method that returns a list of
Product. Adding a new shop means adding one file here and one entry in `_build` below.

CATALOGUE_SOURCE in the settings picks the source. List several, separated by commas, to
search them together, for example:  CATALOGUE_SOURCE=shopify,etsy
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

LABELS = {"sample": "the sample catalogue", "shopify": "Shopify", "etsy": "Etsy"}


class CatalogueError(Exception):
    """A source could not return products. The message is safe to show the user."""


def _build(choice: str, settings: dict):
    if choice == "sample":
        from .sample import SampleSource
        return SampleSource()
    if choice == "shopify":
        from .shopify import ShopifySource
        profile = settings.get("SHOPIFY_AGENT_PROFILE_URL", "")
        if not profile and settings.get("RENDER_EXTERNAL_URL"):  # set automatically on Render
            profile = settings["RENDER_EXTERNAL_URL"].rstrip("/") + "/ucp-agent-profile.json"
        return ShopifySource(profile)
    if choice == "etsy":
        from .etsy import EtsySource
        return EtsySource(settings.get("ETSY_KEYSTRING", ""), settings.get("ETSY_SHARED_SECRET", ""))
    raise CatalogueError(f'Unknown CATALOGUE_SOURCE "{choice}". Use sample, shopify or etsy.')


def get_source(settings: dict):
    choices = [c.strip().lower() for c in (settings.get("CATALOGUE_SOURCE") or "sample").split(",") if c.strip()]
    choices = list(dict.fromkeys(choices)) or ["sample"]
    sources = [_build(c, settings) for c in choices]
    return sources[0] if len(sources) == 1 else MultiSource(sources)


def label(source) -> str:
    names = [LABELS.get(n, n) for n in source.name.split("+")]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


class MultiSource:
    """Searches several sources at once and pools the results. If one shop is down the
    others still answer; it only fails when every source fails."""

    def __init__(self, sources):
        self.sources = sources
        self.name = "+".join(s.name for s in sources)

    def candidates(self, recipient):
        def one(source):
            try:
                return source.candidates(recipient), None
            except CatalogueError as e:
                log.warning("Catalogue source %s failed: %s", source.name, e)
                return [], str(e)

        with ThreadPoolExecutor(max_workers=len(self.sources)) as pool:
            results = list(pool.map(one, self.sources))
        errors = [err for _, err in results if err]
        if len(errors) == len(self.sources):
            raise CatalogueError(errors[0])
        return [p for products, _ in results for p in products]
