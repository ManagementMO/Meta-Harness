# geometry

A tiny 2D geometry library. Implement the following two classes in
`geometry/__init__.py`.

## `Point(x, y)`

- Constructor takes `x` and `y` (numeric).
- `Point(0, 0)` is the origin.
- Attributes: `x`, `y`.
- `Point.distance_to(other) -> float` — Euclidean distance to another Point.
- Two points are equal (`==`) iff their `x` and `y` match.

## `Line(start, end)`

- Constructor takes two `Point`s.
- Attributes: `start`, `end`.
- `Line.length() -> float` — Euclidean distance from `start` to `end`.
- `Line.contains(point) -> bool` — `True` iff `point` lies on the
  **closed line segment** from `start` to `end`. Use a floating-point
  tolerance of `1e-6`. Points strictly past either endpoint return
  `False`. Points on the infinite extension of the line but outside the
  segment also return `False`.
