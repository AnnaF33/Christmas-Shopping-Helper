"""Where products come from.

Every source has a `name` and a `candidates(recipient)` method that returns a list of
Product. Adding a new shop (Shopify, say) means adding one file here and one line below.
"""
from __future__ import annotations


class CatalogueError(Exception):
    """A source could not return products. The message is safe to show the user."""


def get_source(settings: dict):
    choice = (settings.get("CATALOGUE_SOURCE") or "sample").lower()
    if choice == "etsy":
        from .etsy import EtsySource
        return EtsySource(settings.get("ETSY_KEYSTRING", ""), settings.get("ETSY_SHARED_SECRET", ""))
    if choice == "sample":
        from .sample import SampleSource
        return SampleSource()
    raise CatalogueError(f'Unknown CATALOGUE_SOURCE "{choice}". Use "sample" or "etsy".')
