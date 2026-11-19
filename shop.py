"""North Pole Gift Co: an invented demo seller that accepts payment from agents.

It lives in this app for convenience, but it plays a separate business: it charges with
its OWN Stripe account (SHOP_SECRET_KEY) and is identified by its own Stripe profile
(SHOP_PROFILE_ID). Agents, whether our own wallet or Link's, pay it with a Shared Payment
Token (SPT) scoped to that profile. Sandbox only: it refuses live keys.

The API is modelled on the Universal Commerce Protocol (UCP) checkout flow and the
com.stripe.payments handler, simplified for a demo:

  GET  /demo-shop/.well-known/ucp            who we are and how agents can pay us
  GET  /demo-shop/products                   what we sell (the sample catalogue)
  POST /demo-shop/checkouts                  {"line_items": [{"id": ..., "quantity": 1}], "buyer": {"email": ...}}
  GET  /demo-shop/checkouts/<id>
  POST /demo-shop/checkouts/<id>/complete    {"payment": {"instruments": [{"handler_id": "stripe_payments",
                                               "type": "card", "credential": {"type": "stripe_payment_token",
                                               "token": "spt_..."}}]}}   plus an Idempotency-Key header

Prices always come from the shop's own catalogue, never from the agent's request.
"""
from __future__ import annotations

import hashlib
import json
import secrets

import requests
from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from catalogue.sample import SampleSource
from db import now, shop_checkouts, shop_idempotency

bp = Blueprint("shop", __name__, url_prefix="/demo-shop")

SHOP_NAME = "North Pole Gift Co"
STRIPE_API = "https://api.stripe.com/v1"
STRIPE_VERSION = "2026-09-30.preview"
HANDLER_ID = "stripe_payments"
MAX_QUANTITY = 10

# The shop stocks every product in the invented sample catalogue.
_CATALOGUE = {p.id: p for p in SampleSource().candidates(None)}


class ChargeError(Exception):
    """Stripe refused the payment. The message is safe to show the agent."""


def stripe_charge(secret_key: str, spt: str, amount: int, currency: str, checkout_id: str,
                  idempotency_key: str) -> dict:
    """Charge an SPT with the shop's own Stripe account. Returns the PaymentIntent."""
    try:
        resp = requests.post(
            f"{STRIPE_API}/payment_intents",
            auth=(secret_key, ""),
            headers={"Stripe-Version": STRIPE_VERSION, "Idempotency-Key": idempotency_key},
            data={
                "amount": str(amount),
                "currency": currency,
                "payment_method_data[shared_payment_granted_token]": spt,
                "confirm": "true",
                "description": f"{SHOP_NAME} demo order {checkout_id}",
                "metadata[checkout_id]": checkout_id,
            },
            timeout=30,
        )
    except requests.RequestException:
        raise ChargeError("Couldn't reach Stripe. Please try again.")
    try:
        body = resp.json()
    except ValueError:
        raise ChargeError("Stripe returned an unexpected reply.")
    if not resp.ok:
        raise ChargeError((body.get("error") or {}).get("message") or "Stripe refused the payment.")
    return body


def _settings():
    cfg = current_app.config
    return cfg.get("SHOP_SECRET_KEY", ""), cfg.get("SHOP_PROFILE_ID", "")


def is_configured():
    key, profile = _settings()
    return key.startswith(("sk_test_", "rk_test_")) and profile.startswith("profile_test_")


def _engine():
    return current_app.extensions["db"]


def _handlers():
    _, profile = _settings()
    return {"com.stripe.payments": [{
        "id": HANDLER_ID,
        "version": "2026-08-25",
        "config": {"environment": "testmode", "business_profile": profile},
        "available_instruments": [{"type": "card"}],
    }]}


def _checkout_json(row) -> dict:
    items = json.loads(row.line_items)
    return {
        "id": row.id,
        "status": row.status,
        "currency": row.currency,
        "line_items": items,
        "totals": [{"type": "subtotal", "amount": row.total}, {"type": "total", "amount": row.total}],
        "seller": {"name": SHOP_NAME, "network_business_profile": _settings()[1]},
        "payment": {"handlers": _handlers()},
        "order": {"id": row.order_id, "payment_intent": row.payment_intent_id} if row.order_id else None,
        "messages": [{"type": "error", "content": row.error}] if row.error else [],
    }


def _get(checkout_id):
    with _engine().connect() as c:
        return c.execute(select(shop_checkouts).where(shop_checkouts.c.id == checkout_id)).first()


@bp.before_request
def _require_setup():
    if request.endpoint in ("shop.profile", "shop.products"):
        return None
    if not is_configured():
        return jsonify(error="The demo shop isn't set up. Set SHOP_SECRET_KEY (a test key) and "
                             "SHOP_PROFILE_ID (profile_test_...)."), 503
    return None


@bp.get("/.well-known/ucp")
def profile():
    return jsonify(
        ucp={"version": "2026-08-25",
             "services": {"dev.ucp.shopping": {"rest": {"endpoint": request.host_url.rstrip("/") + "/demo-shop"}}},
             "capabilities": {"dev.ucp.shopping.checkout": [{"version": "2026-08-25"}]},
             "payment_handlers": _handlers()},
        business={"name": SHOP_NAME, "note": "Invented demo seller. Stripe test mode only; nothing is shipped."},
        ready=is_configured())


@bp.get("/products")
def products():
    return jsonify(products=[{"id": p.id, "name": p.name, "unit_amount": round(p.price * 100),
                              "currency": "usd", "emoji": p.emoji} for p in _CATALOGUE.values()])


@bp.post("/checkouts")
def create_checkout():
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("line_items"), list) or not body["line_items"]:
        return jsonify(error='Send {"line_items": [{"id": "sample-3", "quantity": 1}]}.'), 400
    items = []
    for raw in body["line_items"]:
        if not isinstance(raw, dict):
            return jsonify(error="Each line item must be an object."), 400
        product = _CATALOGUE.get(str(raw.get("id") or ""))
        if product is None:
            return jsonify(error=f'We don\'t sell "{raw.get("id")}".'), 400
        try:
            qty = int(raw.get("quantity", 1))
        except (TypeError, ValueError):
            qty = 0
        if not 1 <= qty <= MAX_QUANTITY:
            return jsonify(error=f"Quantity for {product.name} must be 1 to {MAX_QUANTITY}."), 400
        unit = round(product.price * 100)
        items.append({"id": product.id, "name": product.name, "quantity": qty,
                      "unit_amount": unit, "amount": unit * qty})
    total = sum(i["amount"] for i in items)
    buyer = body.get("buyer") if isinstance(body.get("buyer"), dict) else {}
    checkout_id = "co_" + secrets.token_urlsafe(12)
    with _engine().begin() as c:
        c.execute(insert(shop_checkouts).values(
            id=checkout_id, status="ready_for_complete", currency="usd", line_items=json.dumps(items),
            total=total, buyer_email=str(buyer.get("email") or "")[:254] or None, created_at=now()))
    return jsonify(_checkout_json(_get(checkout_id))), 201


@bp.get("/checkouts/<checkout_id>")
def get_checkout(checkout_id):
    row = _get(checkout_id)
    if row is None:
        return jsonify(error="No such checkout."), 404
    return jsonify(_checkout_json(row))


def _token_from(body):
    payment = body.get("payment") if isinstance(body, dict) else None
    instruments = payment.get("instruments") if isinstance(payment, dict) else None
    if not isinstance(instruments, list) or not instruments:
        return None, "Send payment.instruments with one Stripe payment token."
    chosen = next((i for i in instruments if isinstance(i, dict) and i.get("selected", True)), None)
    if not chosen or chosen.get("handler_id") != HANDLER_ID:
        return None, f'Use the "{HANDLER_ID}" payment handler.'
    cred = chosen.get("credential") or {}
    token = str(cred.get("token") or "")
    if cred.get("type") != "stripe_payment_token" or not token.startswith("spt_"):
        return None, "The credential must be a stripe_payment_token (spt_...)."
    return token, None


@bp.post("/checkouts/<checkout_id>/complete")
def complete_checkout(checkout_id):
    key = (request.headers.get("Idempotency-Key") or "").strip()
    if not key or len(key) > 255:
        return jsonify(error="An Idempotency-Key header is required."), 400
    raw = request.get_data() or b""
    request_hash = hashlib.sha256(raw).hexdigest()

    # A retry with the same key gets the original answer; a different request with the
    # same key is refused.
    with _engine().connect() as c:
        seen = c.execute(select(shop_idempotency).where(
            shop_idempotency.c.checkout_id == checkout_id, shop_idempotency.c.key == key)).first()
    if seen:
        if seen.request_hash != request_hash:
            return jsonify(error="This Idempotency-Key was already used with a different request."), 409
        return current_app.response_class(seen.response, status=seen.status_code, mimetype="application/json")

    row = _get(checkout_id)
    if row is None:
        return jsonify(error="No such checkout."), 404
    if row.status == "completed":
        return jsonify(error="This checkout is already paid.", checkout=_checkout_json(row)), 409

    token, problem = _token_from(request.get_json(silent=True))
    if problem:
        return jsonify(error=problem), 400

    # Claim the checkout so two payment attempts at once can't both charge.
    with _engine().begin() as c:
        claimed = c.execute(update(shop_checkouts)
                            .where(shop_checkouts.c.id == checkout_id,
                                   shop_checkouts.c.status.in_(("ready_for_complete", "requires_escalation")))
                            .values(status="processing")).rowcount
    if not claimed:
        return jsonify(error="A payment for this checkout is already in progress. Try again shortly."), 409

    charge = current_app.config.get("SHOP_CHARGE") or stripe_charge
    secret_key, _ = _settings()
    try:
        pi = charge(secret_key, token, row.total, row.currency, checkout_id, f"{checkout_id}:{key}")
    except ChargeError as e:
        status, code, values = "ready_for_complete", 402, {"error": str(e)}
    except Exception:
        with _engine().begin() as c:  # release the claim so the agent can retry
            c.execute(update(shop_checkouts).where(shop_checkouts.c.id == checkout_id)
                      .values(status="ready_for_complete"))
        raise
    else:
        if pi.get("status") == "succeeded":
            status, code = "completed", 200
            values = {"payment_intent_id": pi.get("id"), "order_id": "ord_" + secrets.token_urlsafe(9),
                      "completed_at": now(), "error": None}
        else:
            status, code = "requires_escalation", 402
            values = {"payment_intent_id": pi.get("id"),
                      "error": f"The payment needs the buyer to take action (status {pi.get('status')})."}

    with _engine().begin() as c:
        c.execute(update(shop_checkouts).where(shop_checkouts.c.id == checkout_id)
                  .values(status=status, **values))
    out = _checkout_json(_get(checkout_id))
    payload = json.dumps(out if code == 200 else {"error": values["error"], "checkout": out})
    try:
        with _engine().begin() as c:
            c.execute(insert(shop_idempotency).values(
                checkout_id=checkout_id, key=key, request_hash=request_hash,
                status_code=code, response=payload, created_at=now()))
    except IntegrityError:
        pass  # a parallel retry stored it first; both carry the same outcome
    return current_app.response_class(payload, status=code, mimetype="application/json")
