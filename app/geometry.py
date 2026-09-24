"""Axis-aligned rectangle union metrics via sweep line + coordinate compression.

Computes the area of the union and the perimeter of the union boundary
("exposed perimeter") for up to tens of thousands of rectangles with
integer coordinates up to 1e9 in absolute value.

The algorithm never materialises a unit grid, never pairwise-cuts
rectangles and uses no computational-geometry library.  All arithmetic is
exact integer arithmetic.

Two one-dimensional sweeps are performed (the second with axes swapped):

* Area: between two consecutive sweep coordinates the active set is
  constant, so the gap times the covered cross-axis length is added.
* Cross-axis boundary: boundary edges perpendicular to the sweep axis
  occur only at event coordinates.  At an event coordinate x the exposed
  edge length equals the measure of the symmetric difference between the
  covered cross-axis set immediately before and immediately after x.
  All events sharing x are adjudicated as one batch; within the batch
  the entering (+1) events are applied before the leaving (-1) events.
  The total absolute covered-length change then equals the symmetric
  difference measure: a cell that stays covered (including a cell that
  one rectangle leaves and another enters at the same coordinate)
  contributes nothing, so touching edges never form interior perimeter.

Covered cross-axis length is maintained by an iterative lazy segment
tree supporting range add in O(log n) per event.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    """A half-open rectangle [x0, x1) x [y0, y1) with strict bounds."""

    x0: int
    y0: int
    x1: int
    y1: int


@dataclass(frozen=True)
class Metrics:
    area: int
    perimeter: int


class _CoverageTree:
    """Lazy segment tree over compressed elementary intervals.

    Leaves are the intervals ``coords[i] .. coords[i+1]``; the leaf count
    is rounded up to a power of two and padded with zero-length intervals.
    Each node stores a range-add cover count and the total length of the
    parts of its span with cover count greater than zero.
    """

    __slots__ = ("size", "n", "coords", "cover", "length", "node_lo", "node_hi")

    def __init__(self, coords: list[int]):
        self.coords = coords
        n = len(coords) - 1  # number of elementary intervals
        size = 1
        while size < n:
            size <<= 1
        self.size = size
        self.n = n
        total = 2 * size
        self.cover = [0] * total
        self.length = [0] * total
        self.node_lo = [0] * total
        self.node_hi = [0] * total
        # Leaf spans; padded leaves are zero-length at the last coordinate.
        last = coords[-1] if coords else 0
        for i in range(size):
            p = size + i
            if i < n:
                self.node_lo[p] = coords[i]
                self.node_hi[p] = coords[i + 1]
            else:
                self.node_lo[p] = last
                self.node_hi[p] = last
        for p in range(size - 1, 0, -1):
            self.node_lo[p] = self.node_lo[p << 1]
            self.node_hi[p] = self.node_hi[p << 1 | 1]

    def _pull(self, p: int) -> None:
        if self.cover[p] > 0:
            self.length[p] = self.node_hi[p] - self.node_lo[p]
        elif p >= self.size:
            self.length[p] = 0
        else:
            self.length[p] = self.length[p << 1] + self.length[p << 1 | 1]

    def add(self, ql: int, qr: int, delta: int) -> int:
        """Range-add delta on elementary intervals [ql, qr).

        Returns the change in total covered length, i.e. the measure of
        elementary intervals whose zero/non-zero cover status flipped.
        """
        if ql >= qr:
            return 0
        l = ql + self.size
        r = qr + self.size
        touched: list[int] = []
        while l < r:
            if l & 1:
                self.cover[l] += delta
                touched.append(l)
                l += 1
            if r & 1:
                r -= 1
                self.cover[r] += delta
                touched.append(r)
            l >>= 1
            r >>= 1
        # The touched nodes themselves (their cover count changed) and all
        # ancestors must be refreshed, deepest first.
        to_pull: set[int] = set()
        for node in touched:
            p = node
            while p and p not in to_pull:
                to_pull.add(p)
                p >>= 1
        before = self.length[1]
        for p in sorted(to_pull, reverse=True):
            self._pull(p)
        return abs(self.length[1] - before)

    def covered_length(self) -> int:
        return self.length[1]


_BATCH_COMPACTION_THRESHOLD = 32


def _compact_dense_batch(
    events: list[tuple[int, int, int, int]], start: int, end: int
) -> list[tuple[int, int, int, int]]:
    """Reduce a dense same-coordinate batch before updating the tree."""
    compacted: list[tuple[int, int, int, int]] = []
    for kind in (1, 0):
        spans = sorted(
            (events[i][2], events[i][3])
            for i in range(start, end)
            if events[i][1] == kind
        )
        if not spans:
            continue
        lo, hi = spans[0]
        for next_lo, next_hi in spans[1:]:
            if next_lo <= hi:
                hi = max(hi, next_hi)
                continue
            compacted.append((events[start][0], kind, lo, hi))
            lo, hi = next_lo, next_hi
        compacted.append((events[start][0], kind, lo, hi))
    return compacted


def _sweep(rects: list[Rect]) -> tuple[int, int]:
    """Sweep rectangles along their first axis.

    Returns ``(area, cross_boundary)`` where ``cross_boundary`` is the
    total exposed edge length perpendicular to the sweep direction.
    """
    if not rects:
        return 0, 0

    coords = sorted({v for r in rects for v in (r.y0, r.y1)})
    index = {v: i for i, v in enumerate(coords)}
    tree = _CoverageTree(coords)

    # Events: (sweep coordinate, kind) where kind=1 enters first,
    # kind=0 leaves; sorting on (x, kind descending) puts the whole batch
    # in adjacency order, additions ahead of removals.
    events: list[tuple[int, int, int, int]] = []
    for r in rects:
        lo = index[r.y0]
        hi = index[r.y1]
        events.append((r.x0, 1, lo, hi))
        events.append((r.x1, 0, lo, hi))
    events.sort(key=lambda e: (e[0], -e[1]))

    area = 0
    cross_boundary = 0
    prev_x = events[0][0]
    i = 0
    n_events = len(events)
    while i < n_events:
        x = events[i][0]
        gap = x - prev_x
        if gap:
            # Active set is constant across the open slab.
            area += gap * tree.covered_length()
        batch_end = i + 1
        while batch_end < n_events and events[batch_end][0] == x:
            batch_end += 1
        if batch_end - i >= _BATCH_COMPACTION_THRESHOLD:
            batch = _compact_dense_batch(events, i, batch_end)
        else:
            batch = events[i:batch_end]
        # Apply the whole batch at x; enters before leaves.  The summed
        # covered-length flips equal the before/after symmetric-difference
        # measure, i.e. the exposed edge at x.
        batch_flips = 0
        for _, kind, lo, hi in batch:
            batch_flips += tree.add(lo, hi, 1 if kind else -1)
        cross_boundary += batch_flips
        i = batch_end
        prev_x = x
    return area, cross_boundary


def compute_metrics(rects: list[Rect]) -> Metrics:
    """Union area and exposed perimeter of the given rectangles.

    Geometric duplicates are harmless (they simply overlap fully);
    rectangle identities are validated by the caller.
    """
    if not rects:
        return Metrics(0, 0)
    area, vertical = _sweep(rects)
    swapped = [Rect(r.y0, r.x0, r.y1, r.x1) for r in rects]
    _, horizontal = _sweep(swapped)
    return Metrics(area=area, perimeter=vertical + horizontal)
