"""The two things the app passes around: a Product and a Recipient."""
from __future__ import annotations

from dataclasses import dataclass, field

import rules


@dataclass
class Product:
    id: str
    name: str
    shop: str
    price: float
    tags: list[str] = field(default_factory=list)
    min_age: int = 0
    max_age: int = 120
    usefulness: int = 2  # 3 = gets regular use, 2 = standard, 1 = novelty
    personal: bool = False  # too intimate for a colleague
    is_gift_card: bool = False
    url: str = ""
    image_url: str = ""
    emoji: str = "🎁"  # shown when there is no image
    bg: str = "#f1ead9"


@dataclass
class Recipient:
    name: str
    rel: str
    interests: str
    asked: str = ""
    age: str = ""  # an age band key from rules.AGE_BANDS, or "" for not given
    gender: str = ""  # stored, never used for ranking
    min_price: float = 0
    max_price: float | None = None  # None means no upper limit

    @classmethod
    def from_dict(cls, d: dict) -> "Recipient":
        """Build a Recipient from the JSON the browser sends. Raises ValueError with a
        message that is safe to show the user."""
        if not isinstance(d, dict):
            raise ValueError("Recipient details are missing.")
        name = str(d.get("name") or "").strip()
        rel = str(d.get("rel") or "").strip()
        interests = str(d.get("int") or "").strip()
        age = str(d.get("age") or "").strip()
        if not name:
            raise ValueError("Name is required.")
        if not rel:
            raise ValueError(f"Relationship is required for {name}.")
        if not interests:
            raise ValueError(f"Interests are required for {name}.")
        if age and age not in rules.AGE_BANDS:
            raise ValueError(f"Age band is not recognised for {name}. Edit them and pick one.")
        if rel in rules.KID_RELATIONSHIPS and not age:
            raise ValueError(f"Age band is required for {name}. Edit them and pick one.")
        try:
            lo = float(d.get("min") or 0)
            hi_raw = d.get("max")
            hi = None if hi_raw in ("", None) else float(hi_raw)
        except (TypeError, ValueError):
            raise ValueError(f"Price range is not valid for {name}.")
        if hi is not None and hi < lo:
            raise ValueError(f"Maximum price is below the minimum for {name}.")
        return cls(name=name, rel=rel, interests=interests,
                   asked=str(d.get("asked") or "").strip(), age=age,
                   gender=str(d.get("gen") or "").strip(), min_price=lo, max_price=hi)
