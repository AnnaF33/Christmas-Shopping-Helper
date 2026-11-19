"""The web server. Serves the interface and the API.

Run it with:  python app.py     then open http://localhost:5000

  GET  /api/health           is the server up, and which catalogue and database is it using
  GET  /api/config           relationships and age bands for the form
  POST /api/recommendations  {"recipient": {...}} -> three picks plus alternates
  /api/auth/...              user accounts (see accounts.py)
  /demo-shop/...             North Pole Gift Co, the demo seller (see shop.py)

API keys live in .env on the server and are never sent to the browser.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict
from datetime import timedelta

from flask import Flask, jsonify, request
from werkzeug.middleware.proxy_fix import ProxyFix

import accounts
import db
import matching
import rules
import shop
from catalogue import CatalogueError, get_source, label
from models import Recipient

log = logging.getLogger(__name__)

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


class Limiter:
    """Small in-memory usage limiter. Resets when the server restarts, which is fine here."""

    def __init__(self, per_visitor=rules.RATE_LIMIT_PER_VISITOR, daily=rules.DAILY_SEARCH_LIMIT):
        self.max_hits, self.window = per_visitor
        self.daily = daily
        self._hits = defaultdict(deque)
        self._day, self._count = None, 0
        self._lock = threading.Lock()

    def check(self, visitor: str) -> str | None:
        """Returns None if the request may go ahead, otherwise a message for the user."""
        now = time.time()
        with self._lock:
            today = time.strftime("%Y-%m-%d", time.gmtime(now))
            if today != self._day:
                self._day, self._count = today, 0
            if self._count >= self.daily:
                return "The app has reached its search limit for today. Please try again tomorrow."
            hits = self._hits[visitor]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.max_hits:
                return "That's a lot of searches in a short time. Please wait a few minutes and try again."
            hits.append(now)
            self._count += 1
            return None


def _configure(app: Flask, settings: dict):
    """Sessions, the database, the demo shop's keys, and running behind Render's proxy."""
    hosted = bool(settings.get("RENDER") or settings.get("RENDER_EXTERNAL_URL"))
    secret = (settings.get("SECRET_KEY") or "").strip()
    if not secret:
        if hosted:
            log.warning("SECRET_KEY is not set: everyone is signed out whenever the app restarts. "
                        "Set it in Render's Environment tab.")
        secret = secrets.token_hex(32)
    app.config.update(
        SECRET_KEY=secret,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=hosted,  # https only once hosted
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        MAX_CONTENT_LENGTH=64 * 1024,
        SHOP_SECRET_KEY=(settings.get("SHOP_SECRET_KEY") or "").strip(),
        SHOP_PROFILE_ID=(settings.get("SHOP_PROFILE_ID") or "").strip(),
    )
    if hosted:  # Render's proxy tells us the real https address and visitor IP
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    engine = db.connect(settings)
    if hosted and db.kind(engine) == "sqlite":
        log.warning("DATABASE_URL is not set: accounts are stored in a local file that Render "
                    "wipes on every restart. Set DATABASE_URL to a Postgres database.")
    app.extensions["db"] = engine
    app.extensions["login_limiter"] = accounts.AttemptLimiter()


def create_app(source=None, limiter=None, settings=None) -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="")
    settings = dict(os.environ) if settings is None else settings
    state = {"source": source, "error": None}
    limiter = limiter or Limiter()
    _configure(app, settings)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(shop.bp)
    accounts.protect_from_other_sites(app)
    if source is None:
        try:
            state["source"] = get_source(settings)
        except CatalogueError as e:
            state["error"] = str(e)  # start anyway so the page can show what is wrong

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/health")
    def health():
        ok = state["source"] is not None
        return jsonify(status="ok" if ok else "misconfigured",
                       source=state["source"].name if ok else None, error=state["error"],
                       database=db.kind(app.extensions["db"]),
                       demo_shop_ready=shop.is_configured())

    @app.get("/api/config")
    def config():
        return jsonify(
            source=state["source"].name if state["source"] else None,
            source_label=label(state["source"]) if state["source"] else None,
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
        # Behind the hosting service's proxy the visitor's address is in X-Forwarded-For.
        visitor = (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()
        blocked = limiter.check(visitor)
        if blocked:
            return jsonify(error=blocked), 429
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
