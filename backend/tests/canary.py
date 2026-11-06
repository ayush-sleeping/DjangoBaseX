"""
The one canary generator for leak tests (BUG_CLASSES BC-14).

A canary must be unique and must NOT be detectable by the scrubber's high-entropy backstop
(OBSERVABILITY § 3), so that a canary missing from the logs was removed by a KEY or path rule,
which is what a leak test exists to prove, and never because it merely looked random. Lowercase
dictionary words joined by '-', with no digits: every backstop rule skips that shape by
construction (single-case, no digit between letters, word separators), whatever the draw. A
canary-shaped value that the backstop WOULD catch hides broken key rules, and once made a positive
control fail on roughly one run in eight (TECH_DEBT DB-51).
"""

import secrets

WORDS = (
    "amber anchor apple arrow aspen autumn badge bamboo basin beacon birch blossom bramble breeze "
    "cactus canyon cedar chalk cherry cinder clover cobalt comet copper coral cotton crater "
    "dawn delta desert dune ember falcon fern fjord forest garnet glacier granite harbor hazel "
    "heron island ivory jasper juniper kettle lagoon lantern lemon linen lotus maple marble meadow "
    "mesa mint nectar oasis olive orchid otter pebble pepper pine plum prairie quartz raven reef "
    "river saffron sage sierra silver spruce summit thistle thunder timber topaz tulip velvet "
    "violet walnut willow winter yarrow zephyr"
).split()
WORD_COUNT = 6  # 6 words from ~110: about 40 bits, unique enough for any single test run


def canary() -> str:
    return "canary-" + "-".join(secrets.choice(WORDS) for _ in range(WORD_COUNT))
