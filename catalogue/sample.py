"""Invented sample catalogue, the same 38 products as the prototype.

Shops, products and prices are made up. Usefulness (3 regular use, 2 standard, 1 novelty)
is a hand label; a live catalogue has to supply or infer it.
"""
from models import Product

# name, shop, price, tags, min age, max age, emoji, background, usefulness
_ROWS = [
    ("Enamel herb planter trio", "Juniper & Pine", 34, ["garden", "plants", "cooking"], 16, 99, "🪴", "#e3efe1", 2),
    ("Copper-handled garden trowel set", "Juniper & Pine", 48, ["garden", "outdoors"], 18, 99, "🌱", "#e6f0dc", 3),
    ("Seed-a-month subscription box", "Juniper & Pine", 72, ["garden", "plants"], 18, 99, "🌻", "#fbf0c9", 3),
    ("Sourdough starter kit", "Hearth Kitchen Co.", 39, ["baking", "cooking", "food"], 14, 99, "🍞", "#f6e6cf", 3),
    ("Hand-thrown stoneware mixing bowls", "Hearth Kitchen Co.", 85, ["baking", "cooking", "home"], 18, 99, "🥣", "#eadfd3", 3),
    ("Chef's knife, 8 inch", "Hearth Kitchen Co.", 120, ["cooking", "food"], 18, 99, "🔪", "#e3e6ea", 3),
    ("Pour-over coffee set", "Hearth Kitchen Co.", 58, ["coffee", "home"], 18, 99, "☕", "#eadbcb", 3),
    ("Loose-leaf tea sampler", "Hearth Kitchen Co.", 26, ["tea", "coffee", "food"], 14, 99, "🍵", "#e2efd9", 3),
    ("Building brick castle, 800 pieces", "Little Lantern Toys", 65, ["lego", "building", "construction", "puzzles"], 7, 14, "🏰", "#dde8f7", 3),
    ("Wooden train starter set", "Little Lantern Toys", 42, ["trains", "building", "cars"], 2, 6, "🚂", "#f7e0d6", 2),
    ("Dinosaur dig excavation kit", "Little Lantern Toys", 22, ["dinosaurs", "science", "animals"], 5, 10, "🦖", "#e0efd6", 1),
    ("Junior science lab, 30 experiments", "Little Lantern Toys", 38, ["science", "stem", "experiments"], 8, 13, "🔬", "#dfeaf5", 2),
    ("Plush woodland fox", "Little Lantern Toys", 19, ["animals", "soft toys"], 0, 7, "🦊", "#fbe3cf", 1),
    ("Kids' art studio case", "Little Lantern Toys", 29, ["art", "drawing", "crafts", "painting"], 4, 12, "🎨", "#f5e0ee", 3),
    ("Friendship bracelet loom", "Little Lantern Toys", 18, ["crafts", "fashion", "jewellery", "jewelry"], 7, 14, "🧶", "#f6dfe6", 1),
    ("Family board game: Lantern Quest", "Little Lantern Toys", 36, ["games", "board games", "puzzles", "family"], 8, 99, "🎲", "#e8e2f5", 3),
    ("1000-piece winter village puzzle", "Fieldnote Goods", 24, ["puzzles", "games"], 10, 99, "🧩", "#dfe9f3", 2),
    ("Linen-bound reading journal", "Fieldnote Goods", 21, ["reading", "books", "writing", "novels"], 12, 99, "📓", "#eee4d4", 2),
    ("Brass clip-on book light", "Fieldnote Goods", 28, ["reading", "books", "novels"], 10, 99, "📖", "#f5ecd0", 3),
    ("Fountain pen and ink set", "Fieldnote Goods", 54, ["writing", "art", "stationery"], 14, 99, "🖋️", "#e1e4ec", 2),
    ("Watercolour travel palette", "Fieldnote Goods", 44, ["art", "painting", "drawing", "travel"], 12, 99, "🖌️", "#e6eef6", 2),
    ("Leather passport wallet", "Fieldnote Goods", 62, ["travel"], 18, 99, "🧳", "#ead9c8", 2),
    ("Scratch-off world map", "Fieldnote Goods", 30, ["travel", "geography"], 10, 99, "🗺️", "#dcebe6", 1),
    ("Merino trail socks, 3 pairs", "Northbound Outfitters", 36, ["hiking", "outdoors", "running", "camping"], 14, 99, "🧦", "#e4e8dc", 3),
    ("Insulated trail flask", "Northbound Outfitters", 32, ["hiking", "outdoors", "camping", "fitness", "coffee"], 10, 99, "🥾", "#dfe8e9", 3),
    ("Compact camping lantern", "Northbound Outfitters", 27, ["camping", "outdoors"], 8, 99, "🏕️", "#f2e8cf", 2),
    ("Yoga mat with carry strap", "Northbound Outfitters", 55, ["yoga", "fitness", "pilates", "gym"], 14, 99, "🧘", "#e7e0f0", 3),
    ("Running belt with reflective trim", "Northbound Outfitters", 25, ["running", "fitness", "gym"], 14, 99, "🏃", "#fbe4d6", 3),
    ("Size 4 training football", "Northbound Outfitters", 23, ["soccer", "football", "sport", "sports"], 6, 16, "⚽", "#e1efe0", 3),
    ("Wireless earbuds, sample model", "Signal & Spark", 79, ["music", "tech", "gaming", "podcasts"], 12, 99, "🎧", "#e2e4ee", 3),
    ("Retro handheld game console", "Signal & Spark", 59, ["gaming", "tech", "games"], 8, 99, "🎮", "#e6e0f3", 1),
    ("Beginner ukulele", "Signal & Spark", 49, ["music", "guitar", "instruments"], 7, 99, "🎸", "#f5e6d0", 2),
    ("Smart reading lamp", "Signal & Spark", 45, ["tech", "reading", "home"], 12, 99, "💡", "#f8f0cf", 2),
    ("Instant-print camera", "Signal & Spark", 89, ["photography", "tech", "travel", "art"], 10, 99, "📷", "#e0e9ee", 2),
    ("Wool-blend scarf", "Juniper & Pine", 46, ["fashion", "clothes", "style"], 14, 99, "🧣", "#f3dcdc", 2),
    ("Scented candle trio: fir, clove, orange", "Juniper & Pine", 33, ["home", "candles", "relaxing"], 16, 99, "🕯️", "#f6e7d2", 1),
    ("Bath soak and robe set", "Juniper & Pine", 68, ["relaxing", "spa", "home", "beauty"], 16, 99, "🛁", "#e4eef0", 2),
    ("Hot chocolate gift tin", "Hearth Kitchen Co.", 20, ["food", "chocolate"], 4, 99, "🍫", "#ecdccd", 2),
]
_PERSONAL = {"Bath soak and robe set"}  # too intimate for a colleague


class SampleSource:
    name = "sample"

    def __init__(self):
        self._products = [
            Product(id=f"sample-{i}", name=n, shop=shop, price=price, tags=tags, min_age=lo,
                    max_age=120 if hi >= 99 else hi, usefulness=use, personal=n in _PERSONAL,
                    emoji=emoji, bg=bg)
            for i, (n, shop, price, tags, lo, hi, emoji, bg, use) in enumerate(_ROWS)
        ]

    def candidates(self, recipient):
        return list(self._products)
