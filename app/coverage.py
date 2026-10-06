COVERAGE_REQUEST = frozenset(
    {
        "coverage",
        "what do you know",
        "what do you know about",
        "knowledge coverage",
        "what is covered",
    }
)


def is_coverage_request(text: str) -> bool:
    normalized = " ".join(text.casefold().split()).strip(" ?.!")
    return normalized in COVERAGE_REQUEST
