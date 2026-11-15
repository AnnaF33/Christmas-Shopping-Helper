"""Run with:  python -m pytest"""
import pytest

import matching
from app import create_app
from catalogue import CatalogueError, get_source
from catalogue.etsy import to_product
from catalogue.sample import SampleSource
from models import Product, Recipient

GRANDMA = {"name": "Grandma Jo", "rel": "Parent or in-law", "age": "65+", "gen": "Female",
           "int": "gardening, baking, crime novels", "asked": "a new scarf", "min": "30", "max": "80"}
MAX = {"name": "Max", "rel": "Niece or nephew", "age": "6-9", "gen": "Male",
       "int": "lego, dinosaurs, soccer", "asked": "", "min": "", "max": "50"}
SAM = {"name": "Sam", "rel": "Colleague", "age": "", "gen": "", "int": "coffee, hiking",
       "asked": "", "min": "20", "max": "40"}

PRODUCTS = SampleSource().candidates(None)


def rec(d):
    r = Recipient.from_dict(d)
    return r, matching.recommend(r, PRODUCTS)


def test_three_picks_within_price_range():
    for d in (GRANDMA, MAX, SAM):
        r, out = rec(d)
        assert len(out["picks"]) == 3
        for s in out["picks"] + out["alternates"]:
            assert s.product.price >= r.min_price
            assert r.max_price is None or s.product.price <= r.max_price


def test_asked_for_item_is_included_and_explained():
    r, out = rec(GRANDMA)
    scarf = [s for s in out["picks"] if s.product.name == "Wool-blend scarf"]
    assert scarf and matching.why(r, scarf[0]).startswith("Asked for: a new scarf")
    assert out["missing_asked"] == []


def test_asked_for_wins_a_place_even_when_outscored():
    # Strong interest matches fill the top three; the asked-for item must still get in.
    r, out = rec({**GRANDMA, "asked": "candle", "int": "gardening, baking", "min": "30", "max": "80"})
    assert any(s.asked == "candle" for s in out["picks"])


def test_asked_for_but_unavailable_is_reported():
    _, out = rec({**GRANDMA, "asked": "pasta maker"})
    assert out["missing_asked"] == ["pasta maker"]


def test_children_only_get_age_appropriate_items():
    _, out = rec(MAX)
    for s in out["picks"] + out["alternates"]:
        assert s.product.min_age <= 9 and s.product.max_age >= 6
    assert out["picks"][0].product.name == "Size 4 training football"


def test_adults_without_age_never_get_toys():
    _, out = rec(SAM)
    assert all(s.product.max_age >= 18 for s in out["picks"] + out["alternates"])


def test_colleagues_never_get_personal_items():
    _, out = rec({**SAM, "int": "spa, relaxing", "min": "0", "max": ""})
    assert all(not s.product.personal for s in out["picks"] + out["alternates"])


def test_gender_does_not_change_results():
    a = [s.product.id for s in rec(GRANDMA)[1]["picks"]]
    b = [s.product.id for s in rec({**GRANDMA, "gen": "Male"})[1]["picks"]]
    assert a == b


def test_gift_cards_only_when_asked():
    card = Product(id="x", name="Coffee shop gift card", shop="S", price=25, tags=["coffee"], is_gift_card=True)
    sam = Recipient.from_dict(SAM)
    assert matching.score(sam, card) is None
    assert matching.score(Recipient.from_dict({**SAM, "asked": "a coffee gift card"}), card) is not None


@pytest.mark.parametrize("change,message", [
    ({"name": ""}, "Name is required"),
    ({"rel": ""}, "Relationship is required"),
    ({"int": ""}, "Interests are required"),
    ({"rel": "Child", "age": ""}, "Age band is required"),
    ({"age": "68"}, "Age band is not recognised"),
    ({"min": "90", "max": "80"}, "Maximum price is below"),
])
def test_validation(change, message):
    with pytest.raises(ValueError, match=message):
        Recipient.from_dict({**GRANDMA, **change})


# ---- API

@pytest.fixture
def client():
    return create_app(SampleSource()).test_client()


def test_page_and_static_files_are_served(client):
    assert b"Christmas Shopping Helper" in client.get("/").data
    assert client.get("/app.js").status_code == 200
    assert client.get("/styles.css").status_code == 200


def test_health_and_config(client):
    assert client.get("/api/health").get_json()["source"] == "sample"
    cfg = client.get("/api/config").get_json()
    assert len(cfg["relationships"]) == 10 and len(cfg["age_bands"]) == 7
    assert {r["name"] for r in cfg["relationships"] if r["age_required"]} == {"Child", "Niece or nephew"}


def test_recommendations_endpoint(client):
    j = client.post("/api/recommendations", json={"recipient": GRANDMA}).get_json()
    assert len(j["picks"]) == 3 and j["source"] == "sample"
    pick = j["picks"][0]
    assert {"id", "name", "shop", "price", "why", "url", "image_url", "emoji", "bg"} <= set(pick)
    assert "usefulness" not in pick and "tags" not in pick  # scoring internals stay server-side


def test_recommendations_rejects_bad_input(client):
    r = client.post("/api/recommendations", json={"recipient": {**GRANDMA, "name": ""}})
    assert r.status_code == 400 and "Name is required" in r.get_json()["error"]
    assert client.post("/api/recommendations", data="not json").status_code == 400


# ---- Etsy stub (no network: only the parts that can be checked without a key)

def test_etsy_needs_both_key_parts():
    with pytest.raises(CatalogueError, match="ETSY_KEYSTRING"):
        get_source({"CATALOGUE_SOURCE": "etsy", "ETSY_KEYSTRING": "abc"})


def test_server_starts_and_explains_when_etsy_key_is_missing(monkeypatch):
    monkeypatch.setenv("CATALOGUE_SOURCE", "etsy")
    monkeypatch.delenv("ETSY_KEYSTRING", raising=False)
    monkeypatch.delenv("ETSY_SHARED_SECRET", raising=False)
    c = create_app().test_client()
    assert c.get("/api/health").get_json()["status"] == "misconfigured"
    assert c.post("/api/recommendations", json={"recipient": GRANDMA}).status_code == 503


def test_etsy_listing_converts_to_product():
    listing = {"listing_id": 123, "title": "Hand-knit wool scarf", "tags": ["Scarf", "Winter"],
               "price": {"amount": 4250, "divisor": 100, "currency_code": "USD"},
               "url": "https://www.etsy.com/listing/123"}
    extra = {"images": [{"url_570xN": "https://i.etsystatic.com/x.jpg"}], "shop": {"shop_name": "KnitCo"}}
    p = to_product(listing, "gardening", extra)
    assert (p.id, p.price, p.shop) == ("etsy-123", 42.5, "KnitCo")
    assert p.tags == ["scarf", "winter", "gardening"] and p.image_url.endswith("x.jpg")
