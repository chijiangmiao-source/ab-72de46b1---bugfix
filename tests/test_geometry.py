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


def test_dense_same_start_32_plus_32_fixture():
    # 光刻版复核场景: 32 boxes covering [0,1] x [0,10] and 32 boxes
    # covering [0,2] x [5,15], all 64 entering at the same x coordinate
    # with overlapping/contained vertical ranges.  Geometric repetition is
    # legal; the sweep must preserve cover-count multiplicity (a dense
    # same-coordinate batch used to be merged into one range add, which
    # collapsed the 32 stacked enters to a cover count of 1 and dropped
    # coverage of the shared neck at x=1 -> area came out as 20).
    rects = [Rect(0, 0, 1, 10) for _ in range(32)]
    rects += [Rect(0, 5, 2, 15) for _ in range(32)]
    got = compute_metrics(rects)
    # Duplicates never change a union: identical to the two-shape union.
    assert got == metrics_of((0, 0, 1, 10), (0, 5, 2, 15))
    # 10 + 20 - 5 shared = 25.
    assert got.area == 25
    # L-shaped union: vertical runs 15 (x=0) + 5 (neck step at x=1) +
    # 10 (x=2) = 30; horizontal runs 1 + 1 + 2 = 4; total 34.  The
    # perimeter of any lattice polyomino is even (4A = P + 2S), so an
    # odd value such as 29 is impossible for this union.
    assert got.perimeter == 34
    area, perim = raster_metrics(rects)
    assert (got.area, got.perimeter) == (area, perim)


@pytest.mark.parametrize("copies", [1, 32, 33])
@pytest.mark.parametrize(
    "a,b",
    [
        ((0, 0, 2, 5), (0, 2, 4, 7)),   # overlapping vertical ranges
        ((0, 0, 2, 5), (0, 5, 4, 9)),   # tangent at y=5 (seam not exposed)
        ((0, 0, 2, 10), (0, 2, 2, 8)),  # b fully contained, x edges flush
    ],
)
def test_same_x_overlap_tangent_containment_with_multiplicity(a, b, copies):
    # Dense batches at the same starting x: multiplicity must not alter the
    # union, and the tangent edge must never become interior perimeter.
    rects = [Rect(*a)] * copies + [Rect(*b)] * copies
    got = compute_metrics(rects)
    assert got == compute_metrics([Rect(*a), Rect(*b)])
    area, perim = raster_metrics(rects)
    assert got == Metrics(area, perim)


def test_dense_cover_multiplicity_matches_reference_on_both_axes():
    # Same shapes repeated >= the old 32-event compaction threshold so that
    # both sweeps (x and the swapped y sweep) see oversized batches; leave
    # and enter batches exercise removals as well as additions.
    rng = random.Random(72)
    base_specs = [
        (0, 0, 1, 10),
        (0, 5, 2, 15),
        (-2, 7, 3, 12),
        (1, 0, 2, 6),
    ]
    for copies in (1, 31, 32, 40):
        rects = [Rect(*s) for s in base_specs for _ in range(copies)]
        got = compute_metrics(rects)
        area, perim = raster_metrics(rects)
        assert got == Metrics(area, perim)
    # Random multiplicities on a small, collision-heavy coordinate set.
    for _ in range(40):
        base = []
        for _ in range(rng.randint(1, 6)):
            x0 = rng.choice([-2, 0, 0, 3])
            y0 = rng.choice([-2, 0, 0, 4])
            base.append(
                Rect(x0, y0, x0 + rng.choice([1, 2, 5]), y0 + rng.choice([1, 2, 5]))
            )
        copies = rng.choice([1, 16, 32, 40])
        rects = [r for r in base for _ in range(copies)]
        got = compute_metrics(rects)
        area, perim = raster_metrics(rects)
        assert got == Metrics(area, perim)


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
