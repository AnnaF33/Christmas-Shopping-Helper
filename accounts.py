"""User accounts: sign up, sign in, sign out, and "who am I".

  POST /api/auth/signup   {"email": ..., "password": ...}
  POST /api/auth/login    {"email": ..., "password": ...}
  POST /api/auth/logout
  GET  /api/auth/me

Passwords are stored only as salted hashes (Werkzeug's scrypt). The signed-in user is kept
in Flask's signed session cookie, which is HttpOnly, SameSite=Lax and, on https, Secure.
Later steps tie a user's Link wallet connection and saved card to this account.
"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque

from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from db import now, users

bp = Blueprint("accounts", __name__, url_prefix="/api/auth")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD, MAX_PASSWORD = 10, 128
# A hash of a random password, checked when the email is unknown so a wrong email and a
# wrong password take the same time (no hint about which accounts exist).
_DUMMY_HASH = generate_password_hash("not-a-real-password-0000")


class AttemptLimiter:
    """At most `limit` failed sign-ins per key within `window` seconds."""

    def __init__(self, limit=10, window=900):
        self.limit, self.window = limit, window
        self._fails = defaultdict(deque)
        self._lock = threading.Lock()

    def blocked(self, *keys) -> bool:
        cutoff = time.time() - self.window
        with self._lock:
            for k in keys:
                q = self._fails[k]
                while q and q[0] < cutoff:
                    q.popleft()
                if len(q) >= self.limit:
                    return True
        return False

    def fail(self, *keys):
        with self._lock:
            for k in keys:
                self._fails[k].append(time.time())

    def clear(self, *keys):
        with self._lock:
            for k in keys:
                self._fails.pop(k, None)


def _engine():
    return current_app.extensions["db"]


def _visitor() -> str:
    return (request.headers.get("X-Forwarded-For") or request.remote_addr or "?").split(",")[0].strip()


def _credentials():
    body = request.get_json(silent=True) or {}
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    return email, password


def current_user():
    """The signed-in user as a dict, or None."""
    uid = session.get("user_id")
    if not uid:
        return None
    with _engine().connect() as c:
        row = c.execute(select(users.c.id, users.c.email).where(users.c.id == uid)).first()
    if not row:
        session.clear()
        return None
    return {"id": row.id, "email": row.email}


def _sign_in(user_id: int):
    session.clear()  # a fresh session on every sign-in
    session.permanent = True
    session["user_id"] = user_id


@bp.post("/signup")
def signup():
    email, password = _credentials()
    if not EMAIL_RE.match(email) or len(email) > 254:
        return jsonify(error="Please enter a valid email address."), 400
    if not (MIN_PASSWORD <= len(password) <= MAX_PASSWORD):
        return jsonify(error=f"Please choose a password of at least {MIN_PASSWORD} characters."), 400
    if password.lower() == email:
        return jsonify(error="Please choose a password that isn't your email address."), 400
    try:
        with _engine().begin() as c:
            result = c.execute(insert(users).values(
                email=email, password_hash=generate_password_hash(password), created_at=now()))
            uid = result.inserted_primary_key[0]
    except IntegrityError:
        return jsonify(error="An account with that email already exists. Try signing in."), 409
    _sign_in(uid)
    return jsonify(user={"id": uid, "email": email}), 201


@bp.post("/login")
def login():
    email, password = _credentials()
    limiter = current_app.extensions["login_limiter"]
    keys = ("ip:" + _visitor(), "email:" + email)
    if limiter.blocked(*keys):
        return jsonify(error="Too many sign-in attempts. Please wait 15 minutes and try again."), 429
    with _engine().connect() as c:
        row = c.execute(select(users.c.id, users.c.email, users.c.password_hash)
                        .where(func.lower(users.c.email) == email)).first()
    if not row:
        check_password_hash(_DUMMY_HASH, password)
        limiter.fail(*keys)
        return jsonify(error="That email and password don't match an account."), 401
    if not check_password_hash(row.password_hash, password):
        limiter.fail(*keys)
        return jsonify(error="That email and password don't match an account."), 401
    limiter.clear(*keys)
    _sign_in(row.id)
    return jsonify(user={"id": row.id, "email": row.email})


@bp.post("/logout")
def logout():
    session.clear()
    return jsonify(ok=True)


@bp.get("/me")
def me():
    return jsonify(user=current_user())


def protect_from_other_sites(app):
    """Stops other websites from submitting requests with a signed-in user's cookie.

    Every request that changes something under /api/ must be JSON, and if the browser
    says where it came from (the Origin header), that must be this site.
    """

    @app.before_request
    def _check():
        if request.method in ("GET", "HEAD", "OPTIONS") or not request.path.startswith("/api/"):
            return None
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != request.host_url.rstrip("/"):
            allowed = [o.strip().rstrip("/") for o in app.config.get("ALLOWED_ORIGINS", [])]
            if origin.rstrip("/") not in allowed:
                return jsonify(error="Request blocked: it came from another website."), 403
        if request.path.startswith(("/api/auth/", "/api/wallet")) and not request.is_json:
            return jsonify(error="Please send JSON."), 400
        return None
