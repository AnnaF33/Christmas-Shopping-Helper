import os
"""Accounts and the North Pole Gift Co demo shop. Run with:  python -m pytest

Stripe is replaced by a fake, so these tests never touch the network or move money.
"""
import threading

import pytest

import db
import shop
from app import create_app
from catalogue.sample import SampleSource

SHOP_KEY = "sk_test_fake_shop_key"
SHOP_PROFILE = "profile_test_fake_north_pole"


def make_app(tmp_path, **extra):
    settings = {"DATABASE_URL": os.environ["DATABASE_URL"], "SECRET_KEY": "test-secret",
                "SHOP_SECRET_KEY": SHOP_KEY, "SHOP_PROFILE_ID": SHOP_PROFILE, **extra}
    return create_app(SampleSource(), settings=settings)


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    return app.test_client()


# ---- Accounts

def signup(c, email="anna@example.com", password="correct horse battery"):
    return c.post("/api/auth/signup", json={"email": email, "password": password})


def test_signup_signs_you_in(client):
    r = signup(client)
    assert r.status_code == 201 and r.get_json()["user"]["email"] == "anna@example.com"
    assert client.get("/api/auth/me").get_json()["user"]["email"] == "anna@example.com"


def test_password_is_stored_hashed(app, client):
    signup(client)
    with app.extensions["db"].connect() as c:
        stored = c.execute(db.users.select()).first().password_hash
    assert "correct horse" not in stored and stored.startswith(("scrypt:", "pbkdf2:"))


@pytest.mark.parametrize("email,password,message", [
    ("not-an-email", "long enough password", "valid email"),
    ("a@example.com", "short", "at least 10"),
    ("a@example.com", "A@EXAMPLE.COM", "isn't your email"),
])
def test_signup_validation(client, email, password, message):
    r = signup(client, email, password)
    assert r.status_code == 400 and message in r.get_json()["error"]


def test_duplicate_email_is_refused_case_insensitively(client):
    signup(client)
    r = signup(client, "ANNA@example.com")
    assert r.status_code == 409


def test_login_logout_cycle(app):
    c = app.test_client()
    signup(c)
    c.post("/api/auth/logout", json={})
    assert c.get("/api/auth/me").get_json()["user"] is None
    assert c.post("/api/auth/login", json={"email": "Anna@Example.com", "password": "wrong password!"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "Anna@Example.com", "password": "correct horse battery"})
    assert r.status_code == 200 and c.get("/api/auth/me").get_json()["user"]["email"] == "anna@example.com"


def test_unknown_email_gets_the_same_message_as_a_wrong_password(client):
    signup(client)
    a = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    b = client.post("/api/auth/login", json={"email": "anna@example.com", "password": "whatever123"})
    assert a.status_code == b.status_code == 401 and a.get_json() == b.get_json()


def test_repeated_failed_logins_are_slowed_down(client):
    signup(client)
    for _ in range(10):
        client.post("/api/auth/login", json={"email": "anna@example.com", "password": "wrong password!"})
    r = client.post("/api/auth/login", json={"email": "anna@example.com", "password": "correct horse battery"})
    assert r.status_code == 429


def test_requests_from_other_websites_are_blocked(client):
    r = client.post("/api/auth/signup", json={"email": "x@example.com", "password": "long enough pw"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    ok = client.post("/api/auth/signup", json={"email": "x@example.com", "password": "long enough pw"},
                     headers={"Origin": "http://localhost"})
    assert ok.status_code == 201  # same site as the test server


def test_auth_requires_json(client):
    assert client.post("/api/auth/login", data="email=a&password=b").status_code == 400


def test_session_cookie_is_locked_down_when_hosted(tmp_path):
    hosted = make_app(tmp_path, RENDER="true").test_client()
    r = hosted.post("/api/auth/signup", json={"email": "h@example.com", "password": "long enough pw"},
                    base_url="https://shoppinghelper.app")
    cookie = r.headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Lax" in cookie


# ---- Demo shop

class FakeStripe:
    """Pretends to be Stripe. Records every charge."""

    def __init__(self, outcome="succeeded"):
        self.calls, self.outcome = [], outcome

    def __call__(self, key, spt, amount, currency, checkout_id, idem):
        self.calls.append({"key": key, "spt": spt, "amount": amount, "idem": idem})
        if self.outcome == "error":
            raise shop.ChargeError("The requested amount is greater than the remaining amount capturable.")
        return {"id": f"pi_fake_{len(self.calls)}", "status": self.outcome}


@pytest.fixture
def stripe(app):
    fake = FakeStripe()
    app.config["SHOP_CHARGE"] = fake
    return fake


def new_checkout(c, items=None):
    items = items or [{"id": "sample-35", "quantity": 1}, {"id": "sample-3", "quantity": 2}]
    return c.post("/demo-shop/checkouts", json={"line_items": items, "buyer": {"email": "anna@example.com"}})


def pay(c, checkout_id, token="spt_test_123", key="key-1"):
    body = {"payment": {"instruments": [{"handler_id": "stripe_payments", "type": "card",
                                          "credential": {"type": "stripe_payment_token", "token": token}}]}}
    return c.post(f"/demo-shop/checkouts/{checkout_id}/complete", json=body, headers={"Idempotency-Key": key})


def test_profile_advertises_the_stripe_handler_and_shop_profile(client):
    j = client.get("/demo-shop/.well-known/ucp").get_json()
    handler = j["ucp"]["payment_handlers"]["com.stripe.payments"][0]
    assert handler["config"] == {"environment": "testmode", "business_profile": SHOP_PROFILE}
    assert j["ready"] is True


def test_checkout_prices_come_from_the_shop_not_the_agent(client):
    r = new_checkout(client, [{"id": "sample-35", "quantity": 1, "unit_amount": 1}])
    j = r.get_json()
    assert r.status_code == 201 and j["status"] == "ready_for_complete"
    assert j["line_items"][0]["unit_amount"] == 3300  # the candle trio is $33 in the catalogue
    assert j["totals"][-1] == {"type": "total", "amount": 3300}
    assert j["seller"]["network_business_profile"] == SHOP_PROFILE


@pytest.mark.parametrize("items,message", [
    ([{"id": "nope"}], "don't sell"),
    ([{"id": "sample-3", "quantity": 0}], "Quantity"),
    ([{"id": "sample-3", "quantity": 99}], "Quantity"),
    ([], "line_items"),
])
def test_checkout_validation(client, items, message):
    r = client.post("/demo-shop/checkouts", json={"line_items": items})
    assert r.status_code == 400 and message in r.get_json()["error"]


def test_completing_a_checkout_charges_the_total_with_the_shop_key(client, stripe):
    co = new_checkout(client).get_json()
    r = pay(client, co["id"])
    j = r.get_json()
    assert r.status_code == 200 and j["status"] == "completed" and j["order"]["id"].startswith("ord_")
    assert stripe.calls == [{"key": SHOP_KEY, "spt": "spt_test_123", "amount": co["totals"][-1]["amount"],
                             "idem": f"{co['id']}:key-1"}]
    assert client.get(f"/demo-shop/checkouts/{co['id']}").get_json()["status"] == "completed"


def test_a_retry_with_the_same_key_does_not_charge_twice(client, stripe):
    co = new_checkout(client).get_json()
    first, again = pay(client, co["id"]), pay(client, co["id"])
    assert first.get_json() == again.get_json() and len(stripe.calls) == 1


def test_same_key_different_request_is_refused(client, stripe):
    co = new_checkout(client).get_json()
    pay(client, co["id"], token="spt_a")
    assert pay(client, co["id"], token="spt_b").status_code == 409


def test_a_paid_checkout_cannot_be_paid_again(client, stripe):
    co = new_checkout(client).get_json()
    pay(client, co["id"], key="k1")
    r = pay(client, co["id"], key="k2")
    assert r.status_code == 409 and len(stripe.calls) == 1


def test_refused_payment_can_be_retried_with_a_new_token(client, stripe):
    co = new_checkout(client).get_json()
    stripe.outcome = "error"
    r = pay(client, co["id"], key="k1")
    assert r.status_code == 402 and "greater than" in r.get_json()["error"]
    assert r.get_json()["checkout"]["status"] == "ready_for_complete"
    stripe.outcome = "succeeded"
    assert pay(client, co["id"], token="spt_new", key="k2").status_code == 200


def test_payment_needing_buyer_action_is_reported(client, stripe):
    co = new_checkout(client).get_json()
    stripe.outcome = "requires_action"
    r = pay(client, co["id"])
    assert r.status_code == 402 and r.get_json()["checkout"]["status"] == "requires_escalation"


def test_two_payments_at_once_charge_only_once(app):
    slow = threading.Event()

    def blocking_charge(key, spt, amount, currency, checkout_id, idem):
        slow.wait(2)
        return {"id": "pi_once", "status": "succeeded"}

    app.config["SHOP_CHARGE"] = blocking_charge
    c = app.test_client()
    co = new_checkout(c).get_json()
    results = []
    t = threading.Thread(target=lambda: results.append(pay(app.test_client(), co["id"], key="a").status_code))
    t.start()
    import time
    time.sleep(0.3)  # let the first one claim the checkout
    second = pay(c, co["id"], key="b").status_code
    slow.set()
    t.join()
    assert second == 409 and results == [200]


@pytest.mark.parametrize("credential,message", [
    ({"type": "card", "token": "spt_x"}, "stripe_payment_token"),
    ({"type": "stripe_payment_token", "token": "pm_123"}, "spt_"),
])
def test_bad_credentials_are_refused(client, stripe, credential, message):
    co = new_checkout(client).get_json()
    body = {"payment": {"instruments": [{"handler_id": "stripe_payments", "type": "card", "credential": credential}]}}
    r = client.post(f"/demo-shop/checkouts/{co['id']}/complete", json=body, headers={"Idempotency-Key": "k"})
    assert r.status_code == 400 and message in r.get_json()["error"] and not stripe.calls


def test_complete_needs_an_idempotency_key(client, stripe):
    co = new_checkout(client).get_json()
    r = client.post(f"/demo-shop/checkouts/{co['id']}/complete", json={})
    assert r.status_code == 400 and "Idempotency-Key" in r.get_json()["error"]


def test_shop_refuses_to_run_with_a_live_key(tmp_path):
    c = make_app(tmp_path, SHOP_SECRET_KEY="sk_live_real_money").test_client()
    assert new_checkout(c).status_code == 503
    assert c.get("/demo-shop/.well-known/ucp").get_json()["ready"] is False


def test_health_reports_database_and_shop(client):
    j = client.get("/api/health").get_json()
    assert j["database"] == "sqlite" and j["demo_shop_ready"] is True


def test_postgres_urls_are_given_the_right_driver():
    assert db.database_url({"DATABASE_URL": "postgres://u:p@h/d"}) == "postgresql+psycopg://u:p@h/d"
    assert db.database_url({"DATABASE_URL": "postgresql://u:p@h/d?sslmode=require"}).startswith("postgresql+psycopg://")
