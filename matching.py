"""Scores products for a recipient and picks the best three.

Order of operations:
  1. Hard rules remove products outright (price, age band, relationship, gift cards).
  2. Weighted signals rank what is left (asked-for, interests, usefulness, relationship, age).
  3. The three picks are spread across different reasons (asked-for items, interests),
     and at least one asked-for item is guaranteed a place when one is available.

This is keyword matching, a stand-in until a model does the judging (step 4 of the plan).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import rules
from models import Product, Recipient


@dataclass
class Scored:
    product: Product
    score: float
    asked: str | None  # the asked-for term this product matched, if any
    interest: str | None  # the interest this product matched, if any


def terms(text: str) -> list[str]:
    """'Gardening, crime novels' -> ['gardening', 'crime novels']"""
    return [t.strip() for t in re.split(r"[,;]+", (text or "").lower()) if t.strip()]


def search_phrase(term: str) -> str:
    """'a new scarf' -> 'scarf'. Tidies a term before it is sent to a shop's search."""
    return re.sub(r"^((a|an|the|some|new|any)\s+)+", "", term).strip() or term


def interest_hit(word: str, p: Product) -> bool:
    return any(word in t or t in word or (len(word) > 4 and t.startswith(word[:5])) for t in p.tags)


def asked_hit(phrase: str, p: Product) -> bool:
    name = p.name.lower()
    if phrase in name:
        return True
    for w in phrase.split():
        if len(w) > 3 and w not in rules.STOP_WORDS:
            if w in name or any(t == w or t + "s" == w or t == w + "s" for t in p.tags):
                return True
    return False


def _age_range(r: Recipient) -> tuple[int, int]:
    if r.age in rules.AGE_BANDS:
        _, lo, hi = rules.AGE_BANDS[r.age]
        return lo, hi
    return rules.ADULT_RANGE


def _tier(r: Recipient) -> str:
    return rules.RELATIONSHIPS.get(r.rel, (rules.DEFAULT_TIER,))[0]


def score(r: Recipient, p: Product) -> Scored | None:
    """Returns None when a hard rule excludes the product."""
    # --- Hard rules
    if p.price < r.min_price or (r.max_price is not None and p.price > r.max_price):
        return None
    lo, hi = _age_range(r)
    if p.max_age < lo or p.min_age > hi:
        return None
    tier = _tier(r)
    if p.personal and tier == "work":
        return None
    if p.is_gift_card and not any(w in r.asked.lower() for w in rules.GIFT_CARD_WORDS):
        return None

    # --- Weighted signals
    w = rules.WEIGHTS
    asked = next((t for t in terms(r.asked) if asked_hit(t, p)), None)
    interest = next((t for t in terms(r.interests) if interest_hit(t, p)), None)
    useful = p.usefulness / 3
    rel_fit = 0.5 if (p.personal and tier == "friend") else 1.0
    is_child = hi < 18
    if not r.age:
        age_fit = 0.0
    elif is_child:
        age_fit = 1.0 if p.max_age < 18 else 0.4  # favour things made for their age
    else:
        age_fit = 1.0
    total = ((w["asked"] if asked else 0) + (w["interest"] if interest else 0)
             + useful * w["useful"] + rel_fit * w["rel"] + age_fit * w["age"])
    return Scored(p, total, asked, interest)


def rank(r: Recipient, products: list[Product]) -> list[Scored]:
    scored = [s for s in (score(r, p) for p in products) if s]
    return sorted(scored, key=lambda s: (-s.score, s.product.name))


def why(r: Recipient, s: Scored) -> str:
    """The one-line reason shown on each card."""
    parts = []
    if s.asked:
        parts.append(f"Asked for: {s.asked}")
    if s.interest:
        parts.append(f"Fits interest: {s.interest}")
    if s.product.usefulness == 3:
        parts.append("Gets regular use")
    if not parts:
        parts.append("Right for their age" if _age_range(r)[1] < 18 else "Practical pick within budget")
    return " · ".join(parts)


def recommend(r: Recipient, products: list[Product]) -> dict:
    """Returns {'picks': [...], 'alternates': [...], 'missing_asked': [...]}."""
    ranked = rank(r, products)
    # Variety first: one pick per reason (each asked-for item, each interest), best score
    # first. A big catalogue would otherwise return three near-identical scarves.
    picks, reasons = [], set()
    for s in ranked:
        reason = s.asked or s.interest
        if not reason or reason in reasons:
            continue
        picks.append(s)
        reasons.add(reason)
        if len(picks) == rules.PICKS:
            break
    for s in ranked:  # not enough distinct reasons: fill up with the next best
        if len(picks) == rules.PICKS:
            break
        if s not in picks:
            picks.append(s)
    if picks and not any(s.asked for s in picks):
        best_asked = next((s for s in ranked if s.asked), None)
        if best_asked:
            picks[-1] = best_asked
    chosen = {s.product.id for s in picks}
    alternates = [s for s in ranked if s.product.id not in chosen][:rules.ALTERNATES]
    missing = [t for t in terms(r.asked) if not any(asked_hit(t, s.product) for s in ranked)]
    return {"picks": picks, "alternates": alternates, "missing_asked": missing}
