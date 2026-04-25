"""Statistics utilities."""


def mean(values: list[float]) -> float:
    """Return the arithmetic mean of values."""
    if not values:
        raise ValueError("mean of empty list")
    return sum(values) / len(values)
