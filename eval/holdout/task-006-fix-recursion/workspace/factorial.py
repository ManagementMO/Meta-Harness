"""Compute n! recursively. Currently broken — never terminates."""


def factorial(n: int) -> int:
    if n < 0:
        raise ValueError("factorial undefined for negatives")
    return n * factorial(n)  # BUG: should recurse on n-1, with a base case
