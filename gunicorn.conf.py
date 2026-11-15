# Settings the hosting service's web server (gunicorn) reads automatically.
# Several threads matter: while this app is waiting on Shopify, Shopify fetches our
# agent profile from this same app, so one request must not block another.
workers = 1
threads = 8
timeout = 60
