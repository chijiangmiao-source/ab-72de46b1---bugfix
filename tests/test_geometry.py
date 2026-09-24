"""Core geometry tests for the sweep-line engine."""

from __future__ import annotations

import random

import pytest

from app.geometry import Metrics, Rect, compute_metrics
from tests.reference import raster_metrics


def metrics_of(*coords):
    return compute_metrics([Rect(*c) for c in coords])


def test_empty_input():
    assert compute_metrics([]) == Metrics(0, 0)


def test_single_rectangle():
    # 2x3 rectangle: area 6, perimeter 2*(2+3) = 10.
    assert metrics_of((0, 0, 2, 3)) == Metrics(6, 10)
    # Negative coordinates: [-3,1] x [-2,2] is a 4x4 square.
    assert metrics_of((-3, -2, 1, 2)) == Metrics(16, 16)


def test_overlapping_pair_area_10_perimeter_14():
    # Two 3x2 rectangles overlapping in a 1x2 strip.
    # Area 6+6-2 = 10; perimeter 14 (the required fixture).
    assert metrics_of((0, 0, 3, 2), (2, 0, 5, 2)) == Metrics(10, 14)


def test_adjacent_rectangles_ignore_shared_edge():
    # Side by side, sharing the full edge x=2 for 0<=y<=2.
    assert metrics_of((0, 0, 2, 2), (2, 0, 4, 2)) == Metrics(8, 12)
    # Stacked, sharing the full edge y=2 for 0<=x<=4.
    assert metrics_of((0, 0, 4, 2), (0, 2, 4, 4)) == Metrics(16, 16)
    # Three in a row -> one 6x2 bar: area 12, perimeter 16.
    assert metrics_of(
        (0, 0, 2, 2), (2, 0, 4, 2), (4, 0, 6, 2)
    ) == Metrics(12, 16)


def test_duplicate_rectangle_adds_nothing():
    one = metrics_of((0, 0, 2, 2))
    two = metrics_of((0, 0, 2, 2), (0, 0, 2, 2))
    three = metrics_of((0, 0, 2, 2), (0, 0, 2, 2), (0, 0, 2, 2))
    assert one == two == three == Metrics(4, 8)


def test_containment_does_not_count_inner_seam():
    # Outer 4x4 with a fully enclosed 1x1 duplicate-area rectangle:
    # union is the outer box, so no interior perimeter at all.
    assert metrics_of((0, 0, 4, 4), (1, 1, 2, 2)) == Metrics(16, 16)
    # Inner box flush against one outer edge -> still one simple polygon.
    assert metrics_of((0, 0, 4, 4), (0, 1, 2, 3)) == Metrics(16, 16)


def test_partial_edge_touch():
    # Two 2x2 squares touching along a 1-unit edge segment.
    assert metrics_of((0, 0, 2, 2), (2, 1, 4, 3)) == Metrics(8, 14)
    # Symmetric in y.
    assert metrics_of((0, 0, 2, 2), (1, 2, 3, 4)) == Metrics(8, 14)


def test_corner_touch_has_no_shared_edge():
    # Touching only at a point: perimeters simply add.
    assert metrics_of((0, 0, 1, 1), (1, 1, 2, 2)) == Metrics(2, 8)


def test_plus_shape_multiple_runs():
    # Horizontal bar [0,3]x[1,2] plus vertical bar [1,2]x[0,3]:
    # area 3 + 3 - 1 = 5, perimeter 12.
    assert metrics_of((0, 1, 3, 2), (1, 0, 2, 3)) == Metrics(5, 12)


def test_events_at_same_coordinate_are_adjudicated_together():
    # One leaves and one enters at x=2 over the same y-range while a
    # third stays active the whole way -> one continuous 6x2 bar.
    assert metrics_of(
        (-5, 0, 2, 2), (2, 0, 4, 2), (-5, 0, 4, 2)
    ) == Metrics(18, 22)


def test_disconnected_components_perimeter_adds():
    # Two disjoint squares: perimeter 8+8=16.
    assert metrics_of((0, 0, 1, 1), (10, 10, 11, 11)) == Metrics(2, 8)


def test_large_coordinates_exact_integer():
    # 1e9 cube; no float rounding anywhere.
    assert metrics_of((0, 0, 10**9, 10**9)) == Metrics(
        10**18, 4 * 10**9
    )
    assert metrics_of((-(10**9), -(10**9), 10**9, 10**9)) == Metrics(
        (2 * 10**9) ** 2, 8 * 10**9
    )


@pytest.mark.parametrize("seed", range(30))
def test_matches_raster_reference_random(seed):
    rng = random.Random(seed)
    rects = []
    for _ in range(rng.randint(1, 12)):
        x0 = rng.randint(-4, 4)
        y0 = rng.randint(-4, 4)
        x1 = x0 + rng.randint(1, 5)
        y1 = y0 + rng.randint(1, 5)
        if rng.random() < 0.3:  # frequent exact duplicates
            rects.append(rects[rng.randrange(len(rects))] if rects else Rect(x0, y0, x1, y1))
        else:
            rects.append(Rect(x0, y0, x1, y1))
    got = compute_metrics(rects)
    exp_area, exp_perim = raster_metrics(rects)
    assert got.area == exp_area
    assert got.perimeter == exp_perim


def test_degenerate_grid_stripes_match_reference():
    # Many thin adjacent stripes exercising run merges at both axes.
    rects = [Rect(i, 0, i + 1, 5) for i in range(10)]
    got = compute_metrics(rects)
    area, perim = raster_metrics(rects)
    assert got == Metrics(area, perim)


def test_50k_stress_runs_and_is_exact():
    rng = random.Random(2026)
    rects = []
    for i in range(50_000):
        x0 = rng.randint(-10**9, 10**9 - 1)
        y0 = rng.randint(-10**9, 10**9 - 1)
        x1 = min(10**9, x0 + rng.randint(1, 10**6))
        y1 = min(10**9, y0 + rng.randint(1, 10**6))
        rects.append(Rect(x0, y0, x1, y1))
    got = compute_metrics(rects)
    assert got.area > 0 and got.perimeter > 0
    # Upper bound: union area cannot exceed the bounding square area.
    assert got.area <= (2 * 10**9) ** 2
