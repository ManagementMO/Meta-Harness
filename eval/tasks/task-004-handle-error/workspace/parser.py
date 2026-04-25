"""Parse a comma-separated list of ages."""


def parse_ages(text: str) -> list[int]:
    """Return a list of integer ages parsed from a comma-separated string.

    Currently crashes on:
    - Empty input ('').
    - Tokens that aren't valid integers (e.g. 'abc').
    """
    return [int(x.strip()) for x in text.split(",")]
