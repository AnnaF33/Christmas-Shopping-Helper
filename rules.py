"""Every tunable number and business rule in one place.

Change values here, not in matching.py. The browser reads the relationships and age
bands from /api/config, so the form updates itself when you edit this file.
"""

# What each signal is worth out of 100. Starting judgement, to be tuned with real usage.
# Gender is deliberately 0: no evidence it predicts a better gift once interests are known.
WEIGHTS = {"asked": 40, "interest": 30, "useful": 15, "rel": 10, "age": 5, "gender": 0}

# Age band -> (label shown in the form, youngest, oldest)
AGE_BANDS = {
    "0-2": ("0–2", 0, 2),
    "3-5": ("3–5", 3, 5),
    "6-9": ("6–9", 6, 9),
    "10-12": ("10–12", 10, 12),
    "13-17": ("Teen (13–17)", 13, 17),
    "18-64": ("Adult (18–64)", 18, 64),
    "65+": ("65+", 65, 120),
}
ADULT_RANGE = (18, 120)  # assumed when no age band is given, since children must have one

# Relationship -> (closeness tier, suggested min $, suggested max $).
# The price bands are starting suggestions shown in the form, not research findings.
RELATIONSHIPS = {
    "Partner": ("close", 60, 200),
    "Child": ("close", 30, 100),
    "Parent or in-law": ("close", 40, 120),
    "Sibling": ("family", 30, 80),
    "Grandparent": ("family", 30, 80),
    "Niece or nephew": ("family", 20, 50),
    "Other family": ("family", 25, 60),
    "Friend": ("friend", 20, 50),
    "Colleague": ("work", 15, 30),
    "Other": ("work", 15, 40),
}
DEFAULT_TIER = "family"  # for relationships saved before the dropdown existed
KID_RELATIONSHIPS = ("Child", "Niece or nephew")  # age band is required for these

# Small words ignored when matching "asked for" text against product names.
STOP_WORDS = {"with", "some", "from", "that", "this", "more", "nice", "good", "pair"}

# Gift cards are only offered when the person asked for one.
GIFT_CARD_WORDS = ("gift card", "giftcard", "voucher")

PICKS = 3  # recommendations shown per recipient
ALTERNATES = 12  # extra ranked ideas sent to the browser for the Swap button
