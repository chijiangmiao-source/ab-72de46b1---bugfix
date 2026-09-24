"""API-level tests: health, audit responses, error contracts."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from app.main import app, readiness


@pytest.fixture()
def client():
    # TestClient runs the ASGI lifespan, so both readiness flags are set
    # through the real startup path.
    with TestClient(app) as c:
        yield c


def rect(rid, x0=0, y0=0, x1=1, y1=1):
    return {"id": rid, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def test_health_reports_both_components(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["components"]["request_validator"] is True
    assert data["components"]["scan_engine"] is True


def test_health_503_until_both_ready():
    readiness.validator_ready = False
    readiness.engine_ready = False
    try:
        with TestClient(app) as c:
            # Lifespan startup flips both flags; simulate their absence by
            # resetting after startup and exercising gating directly.
            readiness.validator_ready = False
            readiness.engine_ready = False
            resp = c.get("/health")
            assert resp.status_code == 503
            assert resp.json()["components"] == {
                "request_validator": False,
                "scan_engine": False,
            }
            readiness.mark_validator_ready()
            resp = c.get("/health")
            assert resp.status_code == 503  # engine still down
            readiness.mark_engine_ready()
            resp = c.get("/health")
            assert resp.status_code == 200
    finally:
        readiness.mark_validator_ready()
        readiness.mark_engine_ready()


def test_audit_single(client):
    resp = client.post("/api/audit", json={"rectangles": [rect("a", 0, 0, 2, 3)]})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"count": 1, "area": "6", "perimeter": "10"}
    # Decimal strings, not JSON numbers.
    assert isinstance(data["area"], str) and isinstance(data["perimeter"], str)


def test_audit_overlapping_fixture_area_10_perimeter_14(client):
    resp = client.post(
        "/api/audit",
        json={"rectangles": [rect("a", 0, 0, 3, 2), rect("b", 2, 0, 5, 2)]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 2, "area": "10", "perimeter": "14"}


def test_audit_adjacent_and_duplicates(client):
    resp = client.post(
        "/api/audit",
        json={
            "rectangles": [
                rect("a", 0, 0, 2, 2),
                rect("b", 2, 0, 4, 2),  # shares an edge -> not counted
                rect("c", 0, 0, 2, 2),  # geometric duplicate of a
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"count": 3, "area": "8", "perimeter": "12"}


def test_audit_duplicate_id_rejected_without_partial_results(client):
    resp = client.post(
        "/api/audit",
        json={"rectangles": [rect("x"), rect("x", 5, 5, 6, 6)]},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["error"] == "validation_failed"
    assert "area" not in data and "perimeter" not in data
    errs = data["errors"]
    assert errs[0]["loc"] == "/rectangles/1/id"
    assert errs[0]["code"] == "duplicate_id"


def test_audit_invalid_json_422(client):
    resp = client.post(
        "/api/audit", content=b"{", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["code"] == "invalid_json"


def test_audit_error_order_is_stable_across_calls(client):
    payload = json.dumps(
        {"rectangles": [rect("d"), rect("d"), rect("d", 0, 0, 0, 0)]}
    )
    headers = {"content-type": "application/json"}
    r1 = client.post("/api/audit", content=payload, headers=headers)
    r2 = client.post("/api/audit", content=payload, headers=headers)
    assert r1.status_code == r2.status_code == 422
    assert r1.json() == r2.json()
    locs = [e["loc"] for e in r1.json()["errors"]]
    assert locs == [
        "/rectangles/1/id",
        "/rectangles/2/id",
        "/rectangles/2/x1",
        "/rectangles/2/y1",
    ]


def test_audit_large_value_returned_as_decimal_string(client):
    resp = client.post(
        "/api/audit",
        json={"rectangles": [rect("big", -(10**9), -(10**9), 10**9, 10**9)]},
    )
    assert resp.status_code == 200
    assert resp.json()["area"] == str((2 * 10**9) ** 2)
    assert resp.json()["perimeter"] == str(8 * 10**9)


def test_audit_rejects_when_not_ready(client):
    readiness.engine_ready = False
    try:
        resp = client.post("/api/audit", json={"rectangles": [rect("a")]})
        assert resp.status_code == 503
    finally:
        readiness.mark_engine_ready()
