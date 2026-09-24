"""Reference brute-force helpers shared by the tests."""

from __future__ import annotations

from app.geometry import Rect


def raster_metrics(rects: list[Rect]) -> tuple[int, int]:
    """Unit-cell raster reference: covered cells + exposed cell edges.

    Only valid for integer-coordinate rectangles on a modest domain.
    """
    cells: set[tuple[int, int]] = set()
    for r in rects:
        for x in range(r.x0, r.x1):
            for y in range(r.y0, r.y1):
                cells.add((x, y))
    area = len(cells)
    perimeter = 0
    for x, y in cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in cells:
                perimeter += 1
    return area, perimeter
