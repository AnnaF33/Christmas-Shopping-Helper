"""Live check of the demo shop running inside the app (Stripe sandbox, no real money).

It plays the agent (own-wallet path): saves a test card in the AGENT account, issues a
Shared Payment Token to North Pole Gift Co's profile, then buys through the app's
/demo-shop checkout API, which charges the token with the SHOP's own key.

1. Start the app in one Anaconda Prompt window (with the SHOP_ settings set there too):
       set SHOP_SECRET_KEY=sk_test_...      (North Pole Gift Co)
       set SHOP_PROFILE_ID=profile_test_...
       python app.py
2. In a second window:
       set STRIPE_SECRET_KEY=rk_test_...    (agent, "New business")
       set SHOP_PROFILE_ID=profile_test_...
       python demo_shop_check.py
   Add a web address to test the hosted app instead, e.g.
       python demo_shop_check.py https://shoppinghelper.app
"""
import os
import sys
import time
import uuid

import requests

STRIPE = "https://api.stripe.com/v1"
PREVIEW = "2026-09-30.preview"


def stripe(path, data, key):
    r = requests.post(STRIPE + path, auth=(key, ""), data=data, headers={"Stripe-Version": PREVIEW}, timeout=30)
    body = r.json()
    if not r.ok:
        sys.exit(f"Stripe refused {path}: {(body.get('error') or {}).get('message')}")
    return body


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5000").rstrip("/")
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    shop_profile = os.environ.get("SHOP_PROFILE_ID", "").strip()
    if not key.startswith(("sk_test_", "rk_test_")) or not shop_profile.startswith("profile_test_"):
        sys.exit("Set STRIPE_SECRET_KEY (agent test key) and SHOP_PROFILE_ID first.")
    print(f"Demo shop check against {base}  (agent key ends ...{key[-4:]})\n")

    health = requests.get(base + "/api/health", timeout=60).json()
    print(f"[INFO] App is up. Database: {health.get('database')}. Demo shop ready: {health.get('demo_shop_ready')}")
    if not health.get("demo_shop_ready"):
        sys.exit("[FAIL] The app's demo shop isn't set up: set SHOP_SECRET_KEY and SHOP_PROFILE_ID where the app runs.")

    co = requests.post(base + "/demo-shop/checkouts", timeout=30, json={
        "line_items": [{"id": "sample-35", "quantity": 1}], "buyer": {"email": "buyer@example.com"}}).json()
    if "id" not in co:
        sys.exit(f"[FAIL] Could not create a checkout: {co}")
    total = co["totals"][-1]["amount"]
    print(f"[PASS] Checkout {co['id']} created: {co['line_items'][0]['name']}, ${total / 100:.2f}")

    customer = stripe("/customers", {"name": "Demo buyer"}, key)
    pm = stripe("/payment_methods", {"type": "card", "card[token]": "tok_visa"}, key)
    stripe(f"/payment_methods/{pm['id']}/attach", {"customer": customer["id"]}, key)
    spt = stripe("/shared_payment/issued_tokens", {
        "payment_method": pm["id"], "seller_details[network_business_profile]": shop_profile,
        "usage_limits[currency]": "usd", "usage_limits[max_amount]": str(total),
        "usage_limits[expires_at]": str(int(time.time()) + 3600)}, key)
    print(f"[PASS] Agent issued {spt['id']} capped at ${total / 100:.2f}")

    payment = {"payment": {"instruments": [{"handler_id": "stripe_payments", "type": "card",
                                            "credential": {"type": "stripe_payment_token", "token": spt["id"]}}]}}
    idem = str(uuid.uuid4())
    url = f"{base}/demo-shop/checkouts/{co['id']}/complete"
    r = requests.post(url, json=payment, headers={"Idempotency-Key": idem}, timeout=60)
    done = r.json()
    if r.status_code != 200:
        sys.exit(f"[FAIL] The shop refused the payment: {done.get('error')}")
    print(f"[PASS] Order {done['order']['id']} paid. PaymentIntent {done['order']['payment_intent']}")

    again = requests.post(url, json=payment, headers={"Idempotency-Key": idem}, timeout=60)
    print("[PASS] Retrying with the same Idempotency-Key returned the same order, no second charge"
          if again.status_code == 200 and again.json()["order"]["id"] == done["order"]["id"]
          else f"[FAIL] Retry behaved unexpectedly: {again.status_code} {again.text[:200]}")
    print("\nDone. Check Payments in the North Pole Gift Co dashboard.")


if __name__ == "__main__":
    main()
