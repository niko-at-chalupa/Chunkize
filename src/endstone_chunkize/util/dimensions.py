DIMENSION_ALIASES = {
    "overworld": "overworld",
    "world": "overworld",
    "nether": "nether",
    "thenether": "nether",
    "end": "the_end",
    "theend": "the_end",
}


def normalizeDimensionName(raw):
    cleaned = raw.lower().replace("minecraft:", "").replace("_", "").replace(" ", "")
    return DIMENSION_ALIASES.get(cleaned)
