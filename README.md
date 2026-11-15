# Christmas Shopping Helper

Enter the people you're buying for, get three gift recommendations each, tick the ones you
want, and review a basket grouped by shop.

This is the first real-app version: a small Python server plus the web page. It runs on the
invented sample catalogue until an Etsy API key is added.

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

## What's where

| File | What it does |
|---|---|
| `app.py` | The web server and its three API endpoints |
| `rules.py` | Every tunable setting: scoring weights, age bands, relationships and their suggested price ranges |
| `matching.py` | Scores products for a recipient and picks the best three |
| `models.py` | The `Product` and `Recipient` definitions, and input validation |
| `catalogue/sample.py` | The 38 invented sample products |
| `catalogue/etsy.py` | Etsy connection (stub, see below) |
| `static/` | The web page: `index.html`, `styles.css`, `app.js` |
| `tests/test_app.py` | Automated checks of the rules and the API |

To change how gifts are ranked, edit `WEIGHTS` in `rules.py`. To change the dropdowns or
suggested price ranges, edit `RELATIONSHIPS` or `AGE_BANDS` in the same file; the page picks
the changes up from the server.

## How recommendations are chosen

1. Hard rules remove products: outside the price range, wrong age band, too personal for a
   colleague, or a gift card nobody asked for.
2. What's left is scored: asked for (40), fits an interest (30), usefulness (15),
   relationship fit (10), age fit (5). Gender is recorded but worth 0.
3. If the person asked for something that's available, it is guaranteed one of the three places.

The matching is keyword overlap. It is a stand-in until a model does the judging.

## Switching on Etsy

1. Create a personal app at https://www.etsy.com/developers and wait for approval.
2. Copy `.env.example` to `.env`.
3. In `.env`, set `CATALOGUE_SOURCE=etsy` and paste in `ETSY_KEYSTRING` and `ETSY_SHARED_SECRET`.
4. Restart the server.

Never share `.env` or commit it; `.gitignore` already excludes it.

**The Etsy code has not been run against the live API**, because there was no key when it
was written. It follows Etsy's documentation, and the conversion from an Etsy listing to a
product is tested, but expect small fixes on first use. Known gaps:

- Etsy listings have no age range, usefulness or "too personal" label, so every listing gets
  a neutral default. Child safety filtering in particular is not reliable on Etsy data yet.
- No caching or rate-limit handling.
- Prices are assumed to be in USD.

## Not built yet

- Model-based matching and labelling of real listings
- User accounts (the gift list is saved in the browser only)
- Hosting on the public internet (it runs on your own computer for now)
- Agent checkout (v2). In this version you buy at the shop.
