"""Tests for request validation and stable error reporting."""

from __future__ import annotations

import json

import pytest

from app.validation import MAX_RECTANGLES, ValidationError, parse_and_validate


def body(rects):
    return json.dumps({"rectangles": rects}).encode()


def rect(rid=1, **over):
    return {"id": rid, "x0": 0, "y0": 0, "x1": 1, "y1": 1, **over}


def test_valid_minimal_request():
    rects = parse_and_validate(body([rect(1), rect("two", x0=2, x1=4)]))
    assert len(rects) == 2


def test_malformed_json_rejected():
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(b"{not json")
    assert ei.value.errors[0]["loc"] == "/"
    assert ei.value.errors[0]["code"] == "invalid_json"


def test_body_must_be_object():
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(b"[1,2,3]")
    assert ei.value.errors[0]["loc"] == "/"


def test_missing_rectangles_field():
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(b"{}")
    assert ei.value.errors[0]["loc"] == "/rectangles"
    assert ei.value.errors[0]["code"] == "missing_field"


def test_empty_and_too_many():
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body([]))
    assert ei.value.errors[0]["code"] == "empty"
    big = [rect(i) for i in range(MAX_RECTANGLES + 1)]
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body(big))
    assert ei.value.errors[0]["code"] == "too_many"


def test_duplicate_ids_rejected_with_positions():
    payload = body([rect("a"), rect(2), rect("a")])
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(payload)
    errs = ei.value.errors
    assert len(errs) == 1
    assert errs[0]["loc"] == "/rectangles/2/id"
    assert errs[0]["code"] == "duplicate_id"
    assert "index 0" in errs[0]["message"]


def test_duplicate_integer_and_string_ids_are_distinct():
    rects = parse_and_validate(body([rect(1), rect("1")]))
    assert len(rects) == 2


def test_geometric_duplicates_allowed():
    rects = parse_and_validate(body([rect("a"), rect("b"), rect("c")]))
    assert len(rects) == 3
    assert len({(r.x0, r.y0, r.x1, r.y1) for r in rects}) == 1


def test_missing_and_mistyped_fields_report_locations():
    bad = {"id": 7, "x0": 0, "y0": 0}  # x1/y1 missing
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body([bad]))
    locs = [e["loc"] for e in ei.value.errors]
    assert locs == ["/rectangles/0/x1", "/rectangles/0/y1"]


def test_boolean_is_not_an_integer():
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body([rect(1, x0=True)]))
    assert ei.value.errors[0]["loc"] == "/rectangles/0/x0"
    assert ei.value.errors[0]["code"] == "invalid_type"


def test_non_integer_coordinate_rejected():
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body([rect(1, x1=1.5)]))
    assert ei.value.errors[0]["loc"] == "/rectangles/0/x1"


def test_coordinate_bound_inclusive_and_strict_increasing():
    ok = parse_and_validate(
        body([rect(1, x0=-(10**9), x1=10**9, y0=-(10**9), y1=10**9)])
    )
    assert len(ok) == 1
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body([rect(1, x1=10**9 + 1)]))
    assert ei.value.errors[0]["code"] == "out_of_range"
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body([rect(1, x1=0)]))  # x0 == x1
    assert ei.value.errors[0]["code"] == "invalid_bounds"
    assert ei.value.errors[0]["loc"] == "/rectangles/0/x1"
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body([rect(1, y1=-3)]))  # y0 > y1
    assert ei.value.errors[0]["code"] == "invalid_bounds"


def test_errors_are_collected_in_stable_order():
    # Both the duplicate id and the bad bounds must be reported together,
    # field order fixed as x0,y0,x1,y1 within one record.
    payload = body(
        [
            rect("dup"),
            {"id": "dup", "x0": 5, "y0": 5, "x1": 1, "y1": 0},
        ]
    )
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(payload)
    locs = [e["loc"] for e in ei.value.errors]
    assert locs == ["/rectangles/1/id", "/rectangles/1/x1", "/rectangles/1/y1"]


def test_unknown_fields_reported():
    r = rect(1)
    r["extra"] = 9
    with pytest.raises(ValidationError) as ei:
        parse_and_validate(body([r]))
    assert ei.value.errors[0]["loc"] == "/rectangles/0/extra"
