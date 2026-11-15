"""The web server. Serves the interface and three small API endpoints.

Run it with:  python app.py     then open http://localhost:5000

  GET  /api/health           is the server up, and which catalogue is it using
  GET  /api/config           relationships and age bands for the form
  POST /api/recommendations  {"recipient": {...}} -> three picks plus alternates

API keys live in .env on the server and are never sent to the browser.
"""
from __future__ import annotations

import os
from dataclasses import asdict

from flask import Flask, jsonify, request

import matching
import rules
from catalogue import CatalogueError, get_source
from models import Recipient

try:  # .env is optional: the sample catalogue needs no settings
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _product_json(recipient, scored) -> dict:
    p = asdict(scored.product)
    # Internal scoring attributes stay on the server.
    for key in ("tags", "min_age", "max_age", "usefulness", "personal", "is_gift_card"):
        p.pop(key)
    p["why"] = matching.why(recipient, scored)
    return p


def create_app(source=None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="")
    state = {"source": source, "error": None}
    if source is None:
        try:
            state["source"] = get_source(dict(os.environ))
        except CatalogueError as e:
            state["error"] = str(e)  # start anyway so the page can show what is wrong

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/health")
    def health():
        ok = state["source"] is not None
        return jsonify(status="ok" if ok else "misconfigured",
                       source=state["source"].name if ok else None, error=state["error"])

    @app.get("/api/config")
    def config():
        return jsonify(
            source=state["source"].name if state["source"] else None,
            error=state["error"],
            relationships=[{"name": name, "tier": tier, "min": lo, "max": hi,
                            "age_required": name in rules.KID_RELATIONSHIPS}
                           for name, (tier, lo, hi) in rules.RELATIONSHIPS.items()],
            age_bands=[{"value": key, "label": label, "min": lo, "max": hi}
                       for key, (label, lo, hi) in rules.AGE_BANDS.items()])

    @app.post("/api/recommendations")
    def recommendations():
        if state["source"] is None:
            return jsonify(error=state["error"]), 503
        body = request.get_json(silent=True) or {}
        try:
            recipient = Recipient.from_dict(body.get("recipient"))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        try:
            products = state["source"].candidates(recipient)
        except CatalogueError as e:
            return jsonify(error=str(e)), 502
        result = matching.recommend(recipient, products)
        return jsonify(
            source=state["source"].name,
            picks=[_product_json(recipient, s) for s in result["picks"]],
            alternates=[_product_json(recipient, s) for s in result["alternates"]],
            missing_asked=result["missing_asked"])

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    create_app().run(host="127.0.0.1", port=port, debug=False)
