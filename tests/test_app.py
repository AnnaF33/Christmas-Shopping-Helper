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


# ---- Shopify source (no network: parsing and conversion only)

from catalogue import MultiSource, label
from catalogue.shopify import ShopifySource, parse_response
from catalogue.shopify import to_product as shopify_product
import json as _json

SHOPIFY_RAW = {
    "id": "gid://shopify/p/7f3a2b8c1d9e", "title": "Trail Runner Pro",
    "url": "https://example-running.myshopify.com/products/trail-runner-pro",
    "categories": [{"value": "5133", "taxonomy": "google_product_category"},
                   {"value": "Sporting Goods > Athletics > Running > Shoes", "taxonomy": "merchant"}],
    "price_range": {"min": {"amount": 8999, "currency": "USD"}, "max": {"amount": 12999, "currency": "USD"}},
    "media": [{"type": "image", "url": "https://cdn.shopify.com/products/trail-runner-pro.jpg"}],
    "variants": [{"id": "gid://shopify/ProductVariant/12345678", "price": {"amount": 8999, "currency": "USD"},
                  "tags": ["road", "Lightweight"], "seller": {"name": "Example Running"}}],
}


def _reply(products):
    return _json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"products": products}}})


def test_shopify_result_converts_to_product():
    p = shopify_product(SHOPIFY_RAW, "running")
    assert (p.id, p.name, p.shop, p.price) == ("shopify-7f3a2b8c1d9e", "Trail Runner Pro", "Example Running", 89.99)
    assert p.url.endswith("/products/trail-runner-pro") and p.image_url.endswith("trail-runner-pro.jpg")
    assert {"road", "lightweight", "running", "shoes"} <= set(p.tags)
    assert shopify_product({**SHOPIFY_RAW, "price_range": {"min": {"amount": 500, "currency": "EUR"}}}, "x") is None
    assert shopify_product({**SHOPIFY_RAW, "title": "Running Store Gift Card"}, "x").is_gift_card


def test_shopify_reply_parsing():
    assert parse_response(_reply([SHOPIFY_RAW]))[0]["title"] == "Trail Runner Pro"
    assert parse_response("event: message\ndata: " + _reply([SHOPIFY_RAW]) + "\n\n")[0]["title"] == "Trail Runner Pro"
    text_form = _json.dumps({"result": {"content": [{"type": "text", "text": _json.dumps({"products": [SHOPIFY_RAW]})}]}})
    assert len(parse_response(text_form)) == 1
    for bad in ('{"error": {"message": "invalid profile"}}', "<html>oops</html>",
                '{"result": {"isError": true, "content": [{"type": "text", "text": "nope"}]}}'):
        with pytest.raises(CatalogueError):
            parse_response(bad)


def test_shopify_search_sends_price_in_cents_and_ranks_results(monkeypatch):
    sent = []

    def fake_call(self, catalog, profile):
        sent.append((catalog, profile))
        return [SHOPIFY_RAW]

    monkeypatch.setattr(ShopifySource, "_call", fake_call)
    r = Recipient.from_dict({**SAM, "int": "running, coffee", "min": "50", "max": "100"})
    products = ShopifySource("https://example.test/profile.json").candidates(r)
    assert len(products) == 1 and len(sent) == 2  # two interests searched, duplicate result merged
    catalog, profile = sent[0]
    assert catalog["filters"]["price"] == {"min": 5000, "max": 10000}
    assert catalog["filters"]["ships_to"] == {"country": "US"} and catalog["query"] == "running"
    assert profile == "https://example.test/profile.json"
    pick = matching.recommend(r, products)["picks"][0]
    assert matching.why(r, pick) == "Fits interest: running"
    kid = Recipient.from_dict({**MAX, "int": "lego"})
    ShopifySource().candidates(kid)
    assert sent[-1][0]["query"] == "lego for kids"


def test_shopify_falls_back_to_example_profile(monkeypatch):
    from catalogue import shopify
    seen = []

    def fake_call(self, catalog, profile):
        seen.append(profile)
        if profile != shopify.EXAMPLE_PROFILE:
            raise CatalogueError("profile rejected")
        return [SHOPIFY_RAW]

    monkeypatch.setattr(ShopifySource, "_call", fake_call)
    src = ShopifySource("https://example.test/profile.json")
    assert len(src.candidates(Recipient.from_dict(SAM))) == 1
    assert seen[0] == "https://example.test/profile.json" and seen[-1] == shopify.EXAMPLE_PROFILE


class _Broken:
    name = "etsy"

    def candidates(self, recipient):
        raise CatalogueError("Etsy is down")


def test_multi_source_survives_one_failure_and_labels_itself():
    multi = MultiSource([SampleSource(), _Broken()])
    assert len(multi.candidates(Recipient.from_dict(SAM))) == 38
    assert multi.name == "sample+etsy" and label(multi) == "the sample catalogue and Etsy"
    with pytest.raises(CatalogueError, match="Etsy is down"):
        MultiSource([_Broken(), _Broken()]).candidates(Recipient.from_dict(SAM))


def test_source_selection_from_settings():
    assert get_source({}).name == "sample"
    assert get_source({"CATALOGUE_SOURCE": "Shopify"}).name == "shopify"
    assert get_source({"CATALOGUE_SOURCE": "shopify, sample"}).name == "shopify+sample"
    on_render = get_source({"CATALOGUE_SOURCE": "shopify", "RENDER_EXTERNAL_URL": "https://x.onrender.com"})
    assert on_render._profile == "https://x.onrender.com/ucp-agent-profile.json"
    with pytest.raises(CatalogueError, match="Unknown"):
        get_source({"CATALOGUE_SOURCE": "amazon"})


def test_agent_profile_is_served(client):
    profile = client.get("/ucp-agent-profile.json").get_json()
    assert "dev.shopify.catalog.global" in profile["ucp"]["capabilities"]


def test_usage_limits():
    from app import Limiter
    c = create_app(SampleSource(), Limiter(per_visitor=(2, 600), daily=3)).test_client()
    post = lambda ip: c.post("/api/recommendations", json={"recipient": GRANDMA}, headers={"X-Forwarded-For": ip})
    assert post("1.1.1.1").status_code == 200 and post("1.1.1.1").status_code == 200
    assert post("1.1.1.1").status_code == 429  # this visitor is over their limit
    assert post("2.2.2.2").status_code == 200  # another visitor is unaffected
    r = post("3.3.3.3")
    assert r.status_code == 429 and "today" in r.get_json()["error"]  # daily cap reached


def test_picks_are_spread_across_reasons():
    _, out = rec(GRANDMA)  # asked for a scarf; interests gardening, baking, crime novels
    reasons = [s.asked or s.interest for s in out["picks"]]
    assert reasons == ["a new scarf", "gardening", "baking"]
    _, out = rec(SAM)  # only two interests, so the third pick repeats one
    assert {s.interest for s in out["picks"]} == {"coffee", "hiking"} and len(out["picks"]) == 3


def test_search_phrase_drops_filler_words():
    assert matching.search_phrase("a new scarf") == "scarf"
    assert matching.search_phrase("the") == "the" and matching.search_phrase("pasta maker") == "pasta maker"
