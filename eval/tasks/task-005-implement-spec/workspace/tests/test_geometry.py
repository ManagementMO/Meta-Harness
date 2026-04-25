from geometry import Line, Point


def test_point_origin():
    p = Point(0, 0)
    assert p.x == 0 and p.y == 0


def test_point_distance_3_4_5():
    assert Point(0, 0).distance_to(Point(3, 4)) == 5.0


def test_point_equality():
    assert Point(1, 2) == Point(1, 2)
    assert Point(1, 2) != Point(2, 1)


def test_line_length():
    assert Line(Point(0, 0), Point(3, 4)).length() == 5.0


def test_line_contains_endpoint_start():
    line = Line(Point(0, 0), Point(2, 2))
    assert line.contains(Point(0, 0))


def test_line_contains_endpoint_end():
    line = Line(Point(0, 0), Point(2, 2))
    assert line.contains(Point(2, 2))


def test_line_contains_midpoint():
    line = Line(Point(0, 0), Point(4, 4))
    assert line.contains(Point(2, 2))


def test_line_does_not_contain_external():
    line = Line(Point(0, 0), Point(2, 0))
    assert not line.contains(Point(1, 1))


def test_line_does_not_contain_extension():
    """Past the endpoint, on the same infinite line — must be False."""
    line = Line(Point(0, 0), Point(2, 0))
    assert not line.contains(Point(3, 0))
