# Christmas Shopping Helper

Enter the people you're buying for, get three gift recommendations each, tick the ones you
want, and review a basket grouped by shop.

A small Python server plus the web page. It can search the invented sample catalogue, Shopify, Etsy, or several at once. It has user accounts, and a demo seller, North Pole Gift Co, that accepts agent payments with Stripe Shared Payment Tokens in Stripe's sandbox.

## Run it

Easiest: double-click `start.bat` in this folder. It installs what's needed the first time,
starts the app and opens your browser. Keep its window open while you use the app.

Or by hand, in Anaconda Prompt:

First time only:

```
cd path\to\christmas-shopping-helper
pip install -r requirements.txt
```

Every time:

```
python app.py
```

Then open http://localhost:5000 in your browser. Press Ctrl+C in the prompt to stop it.

To run the tests: `python -m pytest`

## Hosting (Render)

The app is set up to run on Render's free plan, deployed from the GitHub repository.

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn wsgi:app`

Free services go to sleep after 15 minutes without visitors, so the first visit after a
quiet spell takes about a minute to load. The gift list is stored in each visitor's own
browser, so nothing is lost when the service sleeps.

To publish a change: upload the changed files to GitHub and Render redeploys by itself.

### Settings Render needs

Set these in the service's **Environment** tab:

| Setting | What it is |
|---|---|
| `SECRET_KEY` | Long random text that signs the sign-in cookie. Without it everyone is signed out on every restart. |
| `DATABASE_URL` | A Postgres database (for example a free Neon database). Without it accounts and orders are lost whenever Render restarts or sleeps. |
| `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_PROFILE_ID` | The agent's Stripe sandbox ("New business") |
| `SHOP_SECRET_KEY`, `SHOP_PROFILE_ID` | North Pole Gift Co's own, separate Stripe sandbox |

`/api/health` shows which database is in use and whether the demo shop is set up.

## What's where

| File | What it does |
|---|---|
| `app.py` | The web server, settings and the recommendation API |
| `accounts.py` | Sign up, sign in, sign out; protection against other websites posting as a signed-in user |
| `shop.py` | North Pole Gift Co, the demo seller: checkout API that charges Shared Payment Tokens |
| `db.py` | The database tables (users, shop checkouts, idempotency keys) |
| `rules.py` | Every tunable setting: scoring weights, age bands, relationships and their suggested price ranges |
| `matching.py` | Scores products for a recipient and picks the best three |
| `models.py` | The `Product` and `Recipient` definitions, and input validation |
| `catalogue/sample.py` | The 38 invented sample products |
| `catalogue/shopify.py` | Shopify connection: searches every Shopify merchant |
| `catalogue/etsy.py` | Etsy connection (waiting on API approval) |
| `gunicorn.conf.py` | Web server settings used by the hosting service |
| `wsgi.py` | Entry point the hosting service uses |
| `static/` | The web page: `index.html`, `styles.css`, `app.js` |
| `tests/` | Automated checks of the rules, the API, accounts and the demo shop |
| `check_spt.py`, `shop_charge.py`, `demo_shop_check.py` | Live sandbox checks you run by hand (see below) |

To change how gifts are ranked, edit `WEIGHTS` in `rules.py`. To change the dropdowns or
suggested price ranges, edit `RELATIONSHIPS` or `AGE_BANDS` in the same file; the page picks
the changes up from the server.

## How recommendations are chosen

1. Hard rules remove products: outside the price range, wrong age band, too personal for a
   colleague, or a gift card nobody asked for.
2. What's left is scored: asked for (40), fits an interest (30), usefulness (15),
   relationship fit (10), age fit (5). Gender is recorded but worth 0.
3. The three picks are spread across different reasons, so one asked-for item and two
   different interests where possible. An available asked-for item always gets a place.

The matching is keyword overlap. It is a stand-in until a model does the judging.

## Choosing the shops

The `CATALOGUE_SOURCE` setting picks where products come from: `sample`, `shopify` or
`etsy`. List several separated by commas to search them together, e.g. `shopify,etsy`.
If one shop is down, results still come from the others.

On Render, set it under the service's **Environment** tab. On your own computer, copy
`.env.example` to `.env` and set it there. Never share `.env` or commit it.

### Shopify

No key or approval needed. Set `CATALOGUE_SOURCE=shopify`. One search covers every Shopify
merchant. The app serves a small "agent profile" file at `/ucp-agent-profile.json`, which
Shopify reads to learn what the app does.

### Etsy

1. Wait for the personal app at https://www.etsy.com/developers to be approved.
2. Set `ETSY_KEYSTRING` and `ETSY_SHARED_SECRET` (Render Environment tab, or `.env`).
3. Add `etsy` to `CATALOGUE_SOURCE`.

### What to know about live shops

**Neither the Shopify nor the Etsy code had been run against the real service when it was
written.** Both follow the official documentation and their result handling is tested
against the documented examples, but expect small fixes on first use.

- Real listings have no age range, usefulness or "too personal" label, so each gets a
  neutral default. For children, Shopify searches add "for kids" or "for teens", which is
  a hint and not a safety filter. Check children's picks yourself for now.
- Only USD prices are shown.
- Nothing is stored: every search is live, which also satisfies Shopify's rule against
  keeping prices for more than 10 minutes.

## Usage limits

To protect the shops' request allowances, the public site allows 30 recipient searches per
visitor per 10 minutes and 800 per day in total. Change these in `rules.py`.

## Accounts

Anyone can create an account with an email and a password of at least 10 characters.
Passwords are stored only as salted hashes. Repeated failed sign-ins are paused for 15
minutes. The gift list is still saved in the browser; the account is what a connected
wallet will belong to.

## North Pole Gift Co (demo seller)

An invented shop that sells the sample catalogue and takes payment from agents. It plays a
separate business: it charges with its own Stripe account (`SHOP_SECRET_KEY`), and agents
pay it with a Shared Payment Token scoped to its Stripe profile (`SHOP_PROFILE_ID`). It
refuses to run with live keys. The API follows the shape of a UCP checkout:

- `GET /demo-shop/.well-known/ucp`: who the shop is and how to pay it
- `POST /demo-shop/checkouts`: start a checkout; prices come from the shop's catalogue
- `POST /demo-shop/checkouts/<id>/complete`: pay with a token; needs an `Idempotency-Key`
  header, so a retried request never charges twice

### Live sandbox checks

- `check_spt.py`: the agent issues tokens and the shop charges them, including the
  over-limit and revoked-token refusals
- `shop_charge.py spt_...`: the shop charges a token from the Link Agent Wallet
- `demo_shop_check.py`: a full purchase through the app's demo shop API

## Not built yet

- Connecting a Link wallet and saving a card in the app, and buying the basket with them
- Model-based matching and labelling of real listings
- Saving the gift list to the account
