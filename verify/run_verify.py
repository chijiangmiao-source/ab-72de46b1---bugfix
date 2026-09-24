#!/usr/bin/env python3
"""One-shot verification gate for the audit service.

Runs, in order, and reports a single process exit code:

1. code tests (pytest);
2. build check (byte-compilation of every source file plus importing the
   ASGI application and its two components);
3. API/HTTP smoke tests against the running audit container, covering the
   mandated fixtures:
   * overlapping boxes  -> area 10, perimeter 14;
   * edge-adjacent boxes -> the common edge is not perimeter;
   * geometric duplicates -> no increment;
   * 64 dense same-start boxes (32+32 overlap/containment) -> area 25,
     perimeter 34, count 64;
   * duplicate id -> 422 with a position-tagged error.

The container exits 0 only when every stage passes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import httpx
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_URL = os.environ.get("AUDIT_URL", "http://audit:8000")
HEALTH_TIMEOUT_S = 30.0

failures: list[str] = []


def stage(name: str):
    print(f"\n=== verify: {name} ===", flush=True)


def check(ok: bool, label: str) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}", flush=True)
    if not ok:
        failures.append(label)
    return ok


def wait_for_health() -> bool:
    stage("service health")
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    last_status = None
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{AUDIT_URL}/health", timeout=2.0)
            last_status = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                ok = (
                    data.get("components", {}).get("request_validator") is True
                    and data.get("components", {}).get("scan_engine") is True
                )
                check(ok, "GET /health -> 200 with validator and scan engine ready")
                return ok
        except httpx.HTTPError as exc:
            last_status = f"connection error: {exc}"
        time.sleep(0.5)
    check(False, f"GET /health did not become ready (last: {last_status})")
    return False


def run_pytest() -> bool:
    stage("code tests (pytest)")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        cwd=REPO_ROOT,
    )
    return check(proc.returncode == 0, f"pytest exit code {proc.returncode}")


def run_build_check() -> bool:
    stage("build check")
    proc = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "app", "tests", "verify"],
        cwd=REPO_ROOT,
    )
    ok = check(proc.returncode == 0, "byte-compile app/, tests/, verify/")
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from app.main import app, readiness; "
                "from app.validation import parse_and_validate; "
                "from app.geometry import compute_metrics; "
                "assert callable(app); "
                "print('imports ok: asgi app, validator, scan engine present')",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        ok = check(proc.returncode == 0, "import ASGI app and both components") and ok
        if proc.returncode:
            print(proc.stdout, proc.stderr)
    except OSError as exc:
        ok = check(False, f"import ASGI app: {exc}") and ok
    return ok


def _post(client: httpx.Client, rects):
    return client.post(
        f"{AUDIT_URL}/api/audit", json={"rectangles": rects}, timeout=10.0
    )


def _r(rid, x0, y0, x1, y1):
    return {"id": rid, "x0": x0, "y0": y0, "x1": x1, "y1": y1}


def run_smoke() -> bool:
    stage("API/HTTP smoke")
    ok = True
    with httpx.Client() as client:
        # Mandated fixture: overlapping boxes area 10, perimeter 14.
        resp = _post(client, [_r("a", 0, 0, 3, 2), _r("b", 2, 0, 5, 2)])
        ok &= check(
            resp.status_code == 200
            and resp.json().get("area") == "10"
            and resp.json().get("perimeter") == "14",
            "overlapping boxes -> area=10 perimeter=14 "
            f"(got {resp.status_code} {resp.text if resp.status_code != 200 else resp.json()})",
        )

        # Adjacent boxes: common edge x=2 must not be counted.
        resp = _post(client, [_r("a", 0, 0, 2, 2), _r("b", 2, 0, 4, 2)])
        body = resp.json() if resp.status_code == 200 else {}
        ok &= check(
            resp.status_code == 200
            and body.get("area") == "8"
            and body.get("perimeter") == "12",
            f"adjacent boxes -> area=8 perimeter=12 (got {body})",
        )

        # Geometric duplicates add nothing; distinct ids still accepted.
        resp_single = _post(client, [_r("a", 0, 0, 2, 2)])
        resp_dup = _post(
            client,
            [_r("a", 0, 0, 2, 2), _r("b", 0, 0, 2, 2), _r("c", 0, 0, 2, 2)],
        )
        s = resp_single.json()
        d = resp_dup.json()
        ok &= check(
            resp_single.status_code == 200
            and resp_dup.status_code == 200
            and d["area"] == s["area"] == "4"
            and d["perimeter"] == s["perimeter"] == "8",
            f"geometric duplicates add nothing (single={s}, triple={d})",
        )

        # Duplicate identity is rejected, position-tagged, no partial data.
        resp = _post(client, [_r("x", 0, 0, 1, 1), _r("x", 2, 2, 3, 3)])
        errs = resp.json().get("errors", []) if resp.status_code == 422 else []
        ok &= check(
            resp.status_code == 422
            and any(e.get("loc") == "/rectangles/1/id" for e in errs)
            and "area" not in resp.json(),
            f"duplicate id -> 422 with loc /rectangles/1/id and no partial result "
            f"(got {resp.status_code} {resp.text[:200]})",
        )

        # Touching edges at a shared x coordinate must not make seams.
        resp = _post(
            client,
            [_r("a", 0, 0, 2, 2), _r("b", 2, 0, 4, 2), _r("c", 0, 0, 4, 2)],
        )
        body = resp.json() if resp.status_code == 200 else {}
        ok &= check(
            body.get("area") == "8" and body.get("perimeter") == "12",
            f"mixed same-coordinate events adjudicated together (got {body})",
        )

        # Dense same-start batch: 32 boxes [0,1]x[0,10] plus 32 boxes
        # [0,2]x[5,15] with distinct ids (geometric repetition is legal).
        # All 64 enter at x=0 with overlapping/contained vertical ranges;
        # cover-count multiplicity must survive the dense batch.
        dense = [_r(f"s{i}", 0, 0, 1, 10) for i in range(32)]
        dense += [_r(f"t{i}", 0, 5, 2, 15) for i in range(32)]
        resp = _post(client, dense)
        body = resp.json() if resp.status_code == 200 else {}
        ok &= check(
            resp.status_code == 200
            and body.get("count") == 64
            and body.get("area") == "25"
            and body.get("perimeter") == "34",
            "64 dense same-start boxes (32+32 overlap/containment) -> "
            "count=64 area=25 perimeter=34 "
            f"(got {resp.status_code} {resp.text[:200]})",
        )

        # Results must be decimal strings even at 1e9 scale.
        resp = _post(client, [_r("big", -(10**9), -(10**9), 10**9, 10**9)])
        body = resp.json() if resp.status_code == 200 else {}
        ok &= check(
            body.get("area") == str((2 * 10**9) ** 2)
            and body.get("perimeter") == str(8 * 10**9)
            and isinstance(body.get("area"), str),
            f"1e9-scale result returned as decimal string (got {body})",
        )
    return ok


def main() -> int:
    print("verify: starting audit service verification", flush=True)
    healthy = wait_for_health()
    tests_ok = run_pytest()
    build_ok = run_build_check()
    smoke_ok = run_smoke() if healthy else False

    stage("summary")
    print(f"  health: {'ok' if healthy else 'FAILED'}")
    print(f"  tests:  {'ok' if tests_ok else 'FAILED'}")
    print(f"  build:  {'ok' if build_ok else 'FAILED'}")
    print(f"  smoke:  {'ok' if smoke_ok else 'FAILED'}")
    if failures:
        print(f"\nverify: {len(failures)} check(s) failed", flush=True)
        return 1
    print("\nverify: ALL CHECKS PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
