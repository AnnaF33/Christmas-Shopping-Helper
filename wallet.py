"""The agent's own wallet: the "save a card in the app" payment path.

A signed-in buyer saves a card once (through Stripe's own form, so this app never sees the
card number), sets a mandate (a spending cap and an end date), then approves a whole
basket with one click. For each shop in the basket, the agent:

  1. opens a checkout at the shop (the seller's price is the one that counts)
  2. reserves the amount against the mandate, or stops if it would go over
  3. issues a Shared Payment Token from the saved card, scoped to that shop's Stripe
     profile and capped at exactly the checkout total, expiring in 15 minutes
  4. hands the token to the shop, which charges it with its own Stripe account

Every step is written to the activity log. Sandbox only: test keys are required.

  GET  /api/wallet                 card, mandate and settings for the Basket page
  POST /api/wallet/setup-intent    start saving a card
  POST /api/wallet/card            finish saving a card   {"setup_intent": "seti_..."}
  POST /api/wallet/card/remove
  POST /api/wallet/mandate         {"cap": 300, "expires_on": "2026-12-24"}
  POST /api/wallet/mandate/revoke
  POST /api/wallet/purchase        {"key": "...", "items": [{"id": "sample-3", "quantity": 1,
                                     "for": "Grandma Jo", "budget_max": 80}]}
  GET  /api/wallet/activity
"""
from __future__ import annotations

import json
import secrets
import time
from datetime import date, datetime, timezone

import requests
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import and_, insert, select, update
from sqlalchemy.exc import IntegrityError

import shop
from accounts import current_user
from db import agent_events, mandates, now, purchases, wallets

bp = Blueprint("wallet", __name__, url_prefix="/api/wallet")

STRIPE_API = "https://api.stripe.com/v1"
PREVIEW_VERSION = "2026-09-30.preview"
TOKEN_LIFETIME = 15 * 60  # seconds a token stays usable
MAX_CAP = 2000_00  # cents; the most a mandate can allow in this demo
MAX_MANDATE_DAYS = 60
REPEAT_WINDOW = 10 * 60  # seconds in which the same gifts won't be bought again


class StripeError(Exception):
    """Stripe refused. The message is safe to show the buyer."""


class AgentStripe:
    """The agent's calls to its own Stripe account ("New business")."""

    def __init__(self, secret_key: str):
        self.key = secret_key

    def _call(self, method, path, data=None, preview=False):
        headers = {"Stripe-Version": PREVIEW_VERSION} if preview else {}
        try:
            r = requests.request(method, STRIPE_API + path, auth=(self.key, ""), data=data or {},
                                 headers=headers, timeout=30)
            body = r.json()
        except (requests.RequestException, ValueError):
            raise StripeError("Couldn't reach Stripe. Please try again.")
        if not r.ok:
            raise StripeError((body.get("error") or {}).get("message") or "Stripe refused the request.")
        return body

    def create_customer(self, email, user_id):
        return self._call("POST", "/customers", {"email": email, "metadata[user_id]": str(user_id)})["id"]

    def create_setup_intent(self, customer_id):
        # Which payment methods appear is set in the Stripe Dashboard
        # (Settings > Payment methods); Stripe no longer accepts payment_method_types here.
        si = self._call("POST", "/setup_intents", {
            "customer": customer_id, "usage": "off_session", "automatic_payment_methods[enabled]": "true"})
        return {"id": si["id"], "client_secret": si["client_secret"]}

    def get_setup_intent(self, setup_intent_id):
        si = self._call("GET", f"/setup_intents/{setup_intent_id}?expand[]=payment_method")
        pm = si.get("payment_method") or {}
        if not isinstance(pm, dict):  # not expanded: just the id
            pm = {"id": pm}
        card = pm.get("card") or {}
        return {"status": si.get("status"), "customer": si.get("customer"),
                "payment_method": pm.get("id"),
                "brand": card.get("brand"), "last4": card.get("last4"),
                "exp_month": card.get("exp_month"), "exp_year": card.get("exp_year")}

    def detach(self, payment_method_id):
        self._call("POST", f"/payment_methods/{payment_method_id}/detach")

    def issue_token(self, payment_method_id, seller_profile, amount, currency, expires_at):
        spt = self._call("POST", "/shared_payment/issued_tokens", {
            "payment_method": payment_method_id,
            "seller_details[network_business_profile]": seller_profile,
            "usage_limits[currency]": currency,
            "usage_limits[max_amount]": str(amount),
            "usage_limits[expires_at]": str(expires_at),
        }, preview=True)
        return spt["id"]


# ---- helpers

def _engine():
    return current_app.extensions["db"]


def _stripe() -> AgentStripe:
    return current_app.config.get("AGENT_STRIPE") or AgentStripe(current_app.config["STRIPE_SECRET_KEY"])


def _ready():
    cfg = current_app.config
    return (cfg.get("STRIPE_SECRET_KEY", "").startswith(("sk_test_", "rk_test_"))
            and cfg.get("STRIPE_PUBLISHABLE_KEY", "").startswith("pk_test_"))


def _money(cents):
    return f"${cents / 100:,.2f}"


def _log(user_id, kind, message, purchase_id=None):
    with _engine().begin() as c:
        c.execute(insert(agent_events).values(user_id=user_id, purchase_id=purchase_id, kind=kind,
                                              message=message, created_at=now()))


def _wallet(user_id):
    with _engine().connect() as c:
        return c.execute(select(wallets).where(wallets.c.user_id == user_id)).first()


def _mandate(user_id):
    """The buyer's active mandate, or None. Expired mandates count as inactive."""
    with _engine().connect() as c:
        row = c.execute(select(mandates).where(mandates.c.user_id == user_id, mandates.c.status == "active")
                        .order_by(mandates.c.id.desc())).first()
    return row if row and row.expires_at > now() else None


def _mandate_json(m):
    if not m:
        return None
    return {"id": m.id, "cap": m.cap, "spent": m.spent, "remaining": m.cap - m.spent,
            "currency": m.currency, "expires_at": m.expires_at}


def _card_json(w):
    if not w or not w.payment_method_id:
        return None
    return {"brand": w.brand, "last4": w.last4, "exp_month": w.exp_month, "exp_year": w.exp_year}


@bp.before_request
def _signed_in():
    user = current_user()
    if not user:
        return jsonify(error="Please sign in first."), 401
    request.user = user
    if request.endpoint != "wallet.overview" and not _ready():
        return jsonify(error="The agent's Stripe sandbox isn't set up. Set STRIPE_SECRET_KEY and "
                             "STRIPE_PUBLISHABLE_KEY (test keys)."), 503
    return None


# ---- card

@bp.get("")
def overview():
    uid = request.user["id"]
    return jsonify(ready=_ready() and shop.is_configured(),
                   publishable_key=current_app.config.get("STRIPE_PUBLISHABLE_KEY") if _ready() else None,
                   card=_card_json(_wallet(uid)), mandate=_mandate_json(_mandate(uid)),
                   seller={"name": shop.SHOP_NAME}, stock=sorted(shop.stock_ids()))


@bp.post("/setup-intent")
def setup_intent():
    user = request.user
    w = _wallet(user["id"])
    try:
        customer = w.customer_id if w else _stripe().create_customer(user["email"], user["id"])
        if not w:
            with _engine().begin() as c:
                c.execute(insert(wallets).values(user_id=user["id"], customer_id=customer, updated_at=now()))
        si = _stripe().create_setup_intent(customer)
    except StripeError as e:
        return jsonify(error=str(e)), 502
    return jsonify(client_secret=si["client_secret"])


@bp.post("/card")
def save_card():
    uid = request.user["id"]
    seti = str((request.get_json(silent=True) or {}).get("setup_intent") or "")
    w = _wallet(uid)
    if not seti.startswith("seti_") or not w:
        return jsonify(error="Start again: no card setup is in progress."), 400
    try:
        info = _stripe().get_setup_intent(seti)
    except StripeError as e:
        return jsonify(error=str(e)), 502
    if info["customer"] != w.customer_id:
        return jsonify(error="That card setup belongs to someone else."), 403
    if info["status"] != "succeeded" or not info["payment_method"]:
        return jsonify(error="The card wasn't saved. Please try again."), 400
    old = w.payment_method_id
    with _engine().begin() as c:
        c.execute(update(wallets).where(wallets.c.user_id == uid).values(
            payment_method_id=info["payment_method"], brand=info["brand"], last4=info["last4"],
            exp_month=info["exp_month"], exp_year=info["exp_year"], updated_at=now()))
    if old and old != info["payment_method"]:
        try:
            _stripe().detach(old)
        except StripeError:
            pass
    _log(uid, "info", f"Card saved: {(info['brand'] or 'card').title()} ending {info['last4']}.")
    return jsonify(card=_card_json(_wallet(uid)))


@bp.post("/card/remove")
def remove_card():
    uid = request.user["id"]
    w = _wallet(uid)
    if w and w.payment_method_id:
        try:
            _stripe().detach(w.payment_method_id)
        except StripeError:
            pass
        with _engine().begin() as c:
            c.execute(update(wallets).where(wallets.c.user_id == uid).values(
                payment_method_id=None, brand=None, last4=None, exp_month=None, exp_year=None, updated_at=now()))
        _log(uid, "info", "Card removed. The agent can no longer pay.")
    return jsonify(card=None)


# ---- mandate

@bp.post("/mandate")
def set_mandate():
    uid = request.user["id"]
    body = request.get_json(silent=True) or {}
    try:
        cap = round(float(body.get("cap")) * 100)
    except (TypeError, ValueError):
        return jsonify(error="Enter a spending cap in dollars."), 400
    if not 1_00 <= cap <= MAX_CAP:
        return jsonify(error=f"The cap must be between $1 and {_money(MAX_CAP)}."), 400
    try:
        day = date.fromisoformat(str(body.get("expires_on") or ""))
    except ValueError:
        return jsonify(error="Choose an end date."), 400
    expires = int(datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    if expires <= now() or expires > now() + MAX_MANDATE_DAYS * 86400:
        return jsonify(error=f"The end date must be within the next {MAX_MANDATE_DAYS} days."), 400
    with _engine().begin() as c:
        c.execute(update(mandates).where(mandates.c.user_id == uid, mandates.c.status == "active")
                  .values(status="replaced"))
        c.execute(insert(mandates).values(user_id=uid, cap=cap, spent=0, currency="usd", expires_at=expires,
                                          status="active", created_at=now()))
    _log(uid, "info", f"Mandate set: the agent may spend up to {_money(cap)} until {day:%d %b %Y}.")
    return jsonify(mandate=_mandate_json(_mandate(uid)))


@bp.post("/mandate/revoke")
def revoke_mandate():
    uid = request.user["id"]
    with _engine().begin() as c:
        n = c.execute(update(mandates).where(mandates.c.user_id == uid, mandates.c.status == "active")
                      .values(status="revoked")).rowcount
    if n:
        _log(uid, "info", "Mandate revoked. The agent can't spend until a new one is set.")
    return jsonify(mandate=None)


# ---- purchase

def _reserve(mandate_id, amount) -> bool:
    """Atomically add `amount` to the mandate's spend, only if it stays within the cap."""
    with _engine().begin() as c:
        return c.execute(update(mandates).where(and_(
            mandates.c.id == mandate_id, mandates.c.status == "active", mandates.c.expires_at > now(),
            mandates.c.spent + amount <= mandates.c.cap)).values(spent=mandates.c.spent + amount)).rowcount == 1


def _release(mandate_id, amount):
    with _engine().begin() as c:
        c.execute(update(mandates).where(mandates.c.id == mandate_id).values(spent=mandates.c.spent - amount))


def _finish(purchase_id, status, code, payload):
    payload["status"] = status
    with _engine().begin() as c:
        c.execute(update(purchases).where(purchases.c.id == purchase_id).values(
            status=status, result=json.dumps(payload), total=payload.get("total")))
    return jsonify(payload), code


def _shop_client():
    """Talk to the shop over its public API, exactly as an outside agent would."""
    return current_app.test_client()


@bp.post("/purchase")
def purchase():
    user = request.user
    uid = user["id"]
    body = request.get_json(silent=True) or {}
    key = str(body.get("key") or "")[:80]
    raw_items = body.get("items")
    if not key or not isinstance(raw_items, list) or not raw_items:
        return jsonify(error="Nothing to buy."), 400

    # A double click or a retried request returns the first result.
    with _engine().connect() as c:
        seen = c.execute(select(purchases).where(purchases.c.user_id == uid, purchases.c.client_key == key)).first()
    if seen:
        if seen.result:
            return jsonify(json.loads(seen.result)), 200
        return jsonify(error="This purchase is already in progress."), 409

    w = _wallet(uid)
    if not w or not w.payment_method_id:
        return jsonify(error="Save a card first."), 400
    m = _mandate(uid)
    if not m:
        return jsonify(error="Set a mandate first: how much the agent may spend, and until when."), 400

    # Only items the demo seller stocks can be bought by the agent; and each must sit
    # within the budget the buyer gave for that person.
    stock = shop.stock_ids()
    items, problems = [], []
    for raw in raw_items[:50]:
        if not isinstance(raw, dict):
            continue
        pid = str(raw.get("id") or "")
        who = str(raw.get("for") or "")[:60]
        product = shop.product(pid)
        if pid not in stock or not product:
            problems.append(f"{pid} isn't sold by {shop.SHOP_NAME}")
            continue
        try:
            qty = max(1, min(int(raw.get("quantity", 1)), shop.MAX_QUANTITY))
        except (TypeError, ValueError):
            qty = 1
        budget = raw.get("budget_max")
        if budget not in (None, "") and product.price > float(budget):
            problems.append(f"{product.name} ({_money(round(product.price * 100))}) is over the "
                            f"{_money(round(float(budget) * 100))} budget for {who or 'this person'}")
            continue
        items.append({"id": pid, "quantity": qty, "for": who})
    if problems:
        _log(uid, "blocked", "Agent stopped before buying: " + "; ".join(problems) + ".")
        return jsonify(error="The agent won't buy this basket: " + "; ".join(problems) + "."), 400

    # Safety net: the same gifts bought again within a few minutes is almost always a
    # mistake (a second click on a page that hadn't refreshed), so refuse it.
    signature = "|".join(sorted(f"{i['id']}x{i['quantity']}>{i['for']}" for i in items))
    with _engine().connect() as c:
        recent = c.execute(select(purchases.c.result).where(
            purchases.c.user_id == uid, purchases.c.status == "completed",
            purchases.c.created_at > now() - REPEAT_WINDOW)).all()
    for (res,) in recent:
        prev = json.loads(res or "{}")
        if prev.get("items_sig") == signature:
            msg = (f"You bought these gifts a moment ago (order {prev.get('order')}). "
                   "The agent won't buy them twice.")
            _log(uid, "blocked", msg)
            return jsonify(error=msg, already_bought=prev.get("order")), 409

    purchase_id = "pur_" + secrets.token_urlsafe(9)
    try:
        with _engine().begin() as c:
            c.execute(insert(purchases).values(id=purchase_id, user_id=uid, client_key=key, mandate_id=m.id,
                                               status="started", created_at=now()))
    except IntegrityError:
        return jsonify(error="This purchase is already in progress."), 409
    log = lambda kind, msg: _log(uid, kind, msg, purchase_id)  # noqa: E731
    who = sorted({i["for"] for i in items if i["for"]})
    log("info", f"Basket approved: {sum(i['quantity'] for i in items)} gift(s)"
                + (f" for {', '.join(who)}" if who else "") + f". Paying {shop.SHOP_NAME}.")

    # 1. Open a checkout at the shop. The shop's total is the one that counts.
    client = _shop_client()
    r = client.post("/demo-shop/checkouts", json={
        "line_items": [{"id": i["id"], "quantity": i["quantity"]} for i in items],
        "buyer": {"email": user["email"]}})
    co = r.get_json(silent=True) or {}
    if r.status_code != 201:
        log("error", f"{shop.SHOP_NAME} couldn't open a checkout: {co.get('error')}")
        return _finish(purchase_id, "failed", 502, {"error": co.get("error") or "The shop is unavailable."})
    total = co["totals"][-1]["amount"]
    profile = co["seller"]["network_business_profile"]
    log("info", f"Checkout {co['id']} opened at {shop.SHOP_NAME}: total {_money(total)}.")

    # 2. Reserve the amount against the mandate, or stop.
    if not _reserve(m.id, total):
        fresh = _mandate(uid)
        left = (fresh.cap - fresh.spent) if fresh else 0
        msg = (f"Blocked by the mandate: {_money(total)} is more than the {_money(left)} left "
               f"of your {_money(m.cap)} cap. No payment token was created.")
        log("blocked", msg)
        return _finish(purchase_id, "blocked", 402, {"error": msg, "total": total})
    log("ok", f"Within the mandate: {_money(total)} reserved, {_money(m.cap - m.spent - total)} left.")

    # 3. Issue a Shared Payment Token scoped to this shop and capped at this total.
    try:
        spt = _stripe().issue_token(w.payment_method_id, profile, total, "usd", int(time.time()) + TOKEN_LIFETIME)
    except StripeError as e:
        _release(m.id, total)
        log("error", f"Couldn't create a payment token: {e}")
        return _finish(purchase_id, "failed", 502, {"error": str(e), "total": total})
    log("ok", f"Payment token {spt} issued to {shop.SHOP_NAME}: up to {_money(total)}, "
              f"valid {TOKEN_LIFETIME // 60} minutes. The shop never sees the card.")

    # 4. Hand the token to the shop, which charges it with its own Stripe account.
    r = client.post(f"/demo-shop/checkouts/{co['id']}/complete", headers={"Idempotency-Key": purchase_id},
                    json={"payment": {"instruments": [{"handler_id": shop.HANDLER_ID, "type": "card",
                                                       "credential": {"type": "stripe_payment_token", "token": spt}}]}})
    done = r.get_json(silent=True) or {}
    if r.status_code != 200:
        _release(m.id, total)
        log("error", f"{shop.SHOP_NAME} refused the payment: {done.get('error')}")
        return _finish(purchase_id, "failed", 402, {"error": done.get("error") or "The payment failed.",
                                                    "total": total})
    order = done["order"]
    log("ok", f"Paid. {shop.SHOP_NAME} order {order['id']} confirmed (Stripe payment {order['payment_intent']}).")
    return _finish(purchase_id, "completed", 200, {
        "purchase": purchase_id, "total": total, "seller": shop.SHOP_NAME, "order": order["id"],
        "payment_intent": order["payment_intent"], "token": spt, "items_sig": signature,
        "items": [{"id": i["id"], "for": i["for"]} for i in items],
        "card": _card_json(w), "mandate": _mandate_json(_mandate(uid))})


@bp.get("/activity")
def activity():
    with _engine().connect() as c:
        rows = c.execute(select(agent_events).where(agent_events.c.user_id == request.user["id"])
                         .order_by(agent_events.c.id.desc()).limit(40)).all()
    return jsonify(events=[{"kind": r.kind, "message": r.message, "at": r.created_at,
                            "purchase": r.purchase_id} for r in rows])
