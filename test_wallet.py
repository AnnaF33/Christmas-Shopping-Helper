"""The agent's own wallet: saved card, mandate and one-approval purchase.

Both Stripe accounts are faked: the agent's (card, tokens) and the shop's (charges).
"""
import os
from datetime import date, timedelta

import pytest

import wallet
from app import create_app
from catalogue.sample import SampleSource

AGENT_KEY, AGENT_PK = "rk_test_fake_agent", "pk_test_fake_agent"
SHOP_KEY, SHOP_PROFILE = "sk_test_fake_shop", "profile_test_fake_north_pole"
SOON = (date.today() + timedelta(days=10)).isoformat()


class FakeAgentStripe:
    def __init__(self):
        self.tokens, self.detached, self.fail_token = [], [], False

    def create_customer(self, email, user_id):
        return f"cus_{user_id}"

    def create_setup_intent(self, customer):
        return {"id": "seti_1", "client_secret": "seti_1_secret_x"}

    def get_setup_intent(self, seti):
        owner = {"seti_mine": "cus_1", "seti_other": "cus_999"}.get(seti, "cus_1")
        return {"status": "succeeded", "customer": owner, "payment_method": "pm_card_1",
                "brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2030}

    def detach(self, pm):
        self.detached.append(pm)

    def issue_token(self, pm, profile, amount, currency, expires_at):
        if self.fail_token:
            raise wallet.StripeError("Your card was declined.")
        self.tokens.append({"pm": pm, "profile": profile, "amount": amount, "currency": currency})
        return f"spt_fake_{len(self.tokens)}"


class FakeShopStripe:
    def __init__(self):
        self.charges, self.refuse = [], False

    def __call__(self, key, spt, amount, currency, checkout_id, idem):
        if self.refuse:
            import shop
            raise shop.ChargeError("The requested amount is greater than the remaining amount capturable.")
        self.charges.append({"key": key, "spt": spt, "amount": amount})
        return {"id": f"pi_fake_{len(self.charges)}", "status": "succeeded"}


@pytest.fixture
def app():
    a = create_app(SampleSource(), settings={
        "DATABASE_URL": os.environ["DATABASE_URL"], "SECRET_KEY": "s",
        "STRIPE_SECRET_KEY": AGENT_KEY, "STRIPE_PUBLISHABLE_KEY": AGENT_PK,
        "SHOP_SECRET_KEY": SHOP_KEY, "SHOP_PROFILE_ID": SHOP_PROFILE})
    a.config["AGENT_STRIPE"] = FakeAgentStripe()
    a.config["SHOP_CHARGE"] = FakeShopStripe()
    return a


@pytest.fixture
def c(app):
    client = app.test_client()
    client.post("/api/auth/signup", json={"email": "anna@example.com", "password": "correct horse battery"})
    return client


def ready(c, cap=100):
    c.post("/api/wallet/setup-intent", json={})
    c.post("/api/wallet/card", json={"setup_intent": "seti_mine"})
    return c.post("/api/wallet/mandate", json={"cap": cap, "expires_on": SOON})


def buy(c, items=None, key="k1"):
    items = items or [{"id": "sample-35", "quantity": 1, "for": "Grandma Jo", "budget_max": 80},
                      {"id": "sample-3", "quantity": 1, "for": "Grandma Jo", "budget_max": 80}]
    return c.post("/api/wallet/purchase", json={"key": key, "items": items})


def test_wallet_needs_sign_in(app):
    assert app.test_client().get("/api/wallet").status_code == 401


def test_overview_shows_setup(c):
    j = c.get("/api/wallet").get_json()
    assert j["ready"] is True and j["publishable_key"] == AGENT_PK and j["card"] is None and j["mandate"] is None
    assert "sample-35" in j["stock"]


def test_saving_a_card_keeps_only_display_details(c):
    assert c.post("/api/wallet/setup-intent", json={}).get_json()["client_secret"].startswith("seti_")
    card = c.post("/api/wallet/card", json={"setup_intent": "seti_mine"}).get_json()["card"]
    assert card == {"brand": "visa", "last4": "4242", "exp_month": 12, "exp_year": 2030}


def test_someone_elses_card_setup_is_refused(c):
    c.post("/api/wallet/setup-intent", json={})
    assert c.post("/api/wallet/card", json={"setup_intent": "seti_other"}).status_code == 403


@pytest.mark.parametrize("cap,expires,message", [
    (0, SOON, "between $1"), (5000, SOON, "between $1"),
    (50, "2020-01-01", "within the next"), (50, "", "end date"), ("lots", SOON, "cap in dollars"),
])
def test_mandate_validation(c, cap, expires, message):
    r = c.post("/api/wallet/mandate", json={"cap": cap, "expires_on": expires})
    assert r.status_code == 400 and message in r.get_json()["error"]


def test_happy_path_one_token_capped_at_the_shop_total(app, c):
    ready(c)
    r = buy(c)
    j = r.get_json()
    assert r.status_code == 200 and j["status"] == "completed" and j["order"].startswith("ord_")
    assert j["total"] == 3300 + 3900  # candle trio + sourdough kit, priced by the shop
    tokens = app.config["AGENT_STRIPE"].tokens
    assert tokens == [{"pm": "pm_card_1", "profile": SHOP_PROFILE, "amount": 7200, "currency": "usd"}]
    assert app.config["SHOP_CHARGE"].charges == [{"key": SHOP_KEY, "spt": "spt_fake_1", "amount": 7200}]
    assert j["mandate"]["spent"] == 7200 and j["mandate"]["remaining"] == 2800


def test_over_the_mandate_is_blocked_before_any_token(app, c):
    ready(c, cap=50)
    r = buy(c)
    assert r.status_code == 402 and "Blocked by the mandate" in r.get_json()["error"]
    assert app.config["AGENT_STRIPE"].tokens == [] and app.config["SHOP_CHARGE"].charges == []
    events = [e["kind"] for e in c.get("/api/wallet/activity").get_json()["events"]]
    assert "blocked" in events


def test_mandate_is_spent_down_across_purchases(c):
    ready(c, cap=100)
    assert buy(c, key="a").status_code == 200  # $72
    r = buy(c, [{"id": "sample-35", "quantity": 1}], key="b")  # $33 more would make $105
    assert r.status_code == 402 and "$28.00 left" in r.get_json()["error"]


def test_a_double_click_buys_once(app, c):
    ready(c)
    first, again = buy(c, key="same"), buy(c, key="same")
    assert first.get_json() == again.get_json() and len(app.config["SHOP_CHARGE"].charges) == 1


def test_items_over_a_persons_budget_are_refused(app, c):
    ready(c)
    r = buy(c, [{"id": "sample-3", "quantity": 1, "for": "Sam", "budget_max": 20}])
    assert r.status_code == 400 and "over the $20.00 budget for Sam" in r.get_json()["error"]
    assert app.config["AGENT_STRIPE"].tokens == []


def test_items_the_shop_doesnt_sell_are_refused(c):
    ready(c)
    r = buy(c, [{"id": "shopify-abc", "quantity": 1}])
    assert r.status_code == 400 and "isn't sold by North Pole Gift Co" in r.get_json()["error"]


def test_revoked_mandate_stops_the_agent(c):
    ready(c)
    c.post("/api/wallet/mandate/revoke", json={})
    r = buy(c)
    assert r.status_code == 400 and "Set a mandate" in r.get_json()["error"]


def test_no_card_no_purchase(c):
    c.post("/api/wallet/mandate", json={"cap": 100, "expires_on": SOON})
    assert "Save a card" in buy(c).get_json()["error"]


def test_failed_token_releases_the_reservation(app, c):
    ready(c)
    app.config["AGENT_STRIPE"].fail_token = True
    r = buy(c, key="x")
    assert r.status_code == 502 and "declined" in r.get_json()["error"]
    assert c.get("/api/wallet").get_json()["mandate"]["spent"] == 0


def test_shop_refusal_releases_the_reservation(app, c):
    ready(c)
    app.config["SHOP_CHARGE"].refuse = True
    r = buy(c, key="y")
    assert r.status_code == 402 and c.get("/api/wallet").get_json()["mandate"]["spent"] == 0


def test_activity_log_tells_the_story(c):
    ready(c)
    buy(c)
    msgs = [e["message"] for e in reversed(c.get("/api/wallet/activity").get_json()["events"])]
    joined = " | ".join(msgs)
    for phrase in ("Card saved", "Mandate set", "Basket approved", "Checkout", "Within the mandate",
                   "Payment token", "Paid."):
        assert phrase in joined


def test_removing_the_card_detaches_it(app, c):
    ready(c)
    c.post("/api/wallet/card/remove", json={})
    assert c.get("/api/wallet").get_json()["card"] is None
    assert app.config["AGENT_STRIPE"].detached == ["pm_card_1"]


def test_wallet_posts_must_be_json(c):
    assert c.post("/api/wallet/mandate", data="cap=5").status_code == 400


def test_the_same_gifts_are_not_bought_twice_in_a_row(app, c):
    ready(c, cap=500)
    first = buy(c, key="first")
    second = buy(c, key="second")  # a new click, not a retry
    assert first.status_code == 200
    assert second.status_code == 409 and first.get_json()["order"] in second.get_json()["error"]
    assert len(app.config["SHOP_CHARGE"].charges) == 1
    # a different basket is still fine
    assert buy(c, [{"id": "sample-35", "quantity": 1, "for": "Sam"}], key="third").status_code == 200
