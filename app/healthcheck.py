#!/usr/bin/env python3
"""Container health check.

Exits 0 only when GET /health returns 200 *and* both the request
validator and the scan engine report ready; exits 1 otherwise.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error

PORT = os.environ.get("PORT", "8000")
URL = f"http://127.0.0.1:{PORT}/health"

try:
    with urllib.request.urlopen(URL, timeout=3) as resp:
        if resp.status != 200:
            sys.exit(1)
        data = json.loads(resp.read().decode())
except (OSError, urllib.error.URLError, ValueError):
    sys.exit(1)

components = data.get("components", {})
if (
    data.get("status") == "ok"
    and components.get("request_validator") is True
    and components.get("scan_engine") is True
):
    sys.exit(0)
sys.exit(1)
