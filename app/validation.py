"""Manual request validation for the audit endpoint.

Validation is deliberately done on the raw JSON document rather than
through a schema library, so that every error carries the precise input
position (e.g. ``/rectangles/12/x0``) and error responses never contain
partial results.  Error collection is deterministic: errors are emitted
in input order, and within a rectangle in a fixed field order.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .geometry import Rect

MAX_RECTANGLES = 50_000
COORDINATE_LIMIT = 10**9
# A little headroom beyond a typical maximal payload (~50k records).
MAX_BODY_BYTES = 64 * 1024 * 1024

_COORD_FIELDS = ("x0", "y0", "x1", "y1")


@dataclass
class ValidationError(Exception):
    errors: list[dict[str, str]] = field(default_factory=list)


def _err(loc: str, code: str, message: str) -> dict[str, str]:
    return {"loc": loc, "code": code, "message": message}


def _reject_constant(value: str):
    raise ValueError("json: NaN/Infinity are not allowed")


def parse_and_validate(raw: bytes | str) -> list[Rect]:
    """Validate a raw request body and return the parsed rectangles.

    Raises :class:`ValidationError` with a deterministic, position-tagged
    error list on any problem.
    """
    errors: list[dict[str, str]] = []

    if isinstance(raw, bytes) and len(raw) > MAX_BODY_BYTES:
        raise ValidationError(
            [_err("/", "payload_too_large", "request body exceeds the size limit")]
        )

    try:
        payload = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValidationError([_err("/", "invalid_json", f"request body is not valid JSON: {exc}")])

    if not isinstance(payload, dict):
        raise ValidationError(
            [_err("/", "invalid_type", "request body must be a JSON object")]
        )
    if "rectangles" not in payload:
        raise ValidationError(
            [_err("/rectangles", "missing_field", "'rectangles' is required")]
        )
    items = payload["rectangles"]
    if not isinstance(items, list):
        raise ValidationError(
            [_err("/rectangles", "invalid_type", "'rectangles' must be an array")]
        )
    if not items:
        raise ValidationError(
            [_err("/rectangles", "empty", "at least one rectangle is required")]
        )
    if len(items) > MAX_RECTANGLES:
        raise ValidationError(
            [
                _err(
                    "/rectangles",
                    "too_many",
                    f"at most {MAX_RECTANGLES} rectangles are allowed (got {len(items)})",
                )
            ]
        )
    # Only the documented top-level shape is accepted.
    extra = set(payload) - {"rectangles"}
    if extra:
        name = sorted(extra)[0]
        raise ValidationError(
            [_err(f"/{name}", "unknown_field", f"unexpected top-level field '{name}'")]
        )

    rects: list[Rect | None] = [None] * len(items)
    seen_ids: dict[object, int] = {}
    coords: dict[str, int] = {}

    for idx, item in enumerate(items):
        base = f"/rectangles/{idx}"
        if not isinstance(item, dict):
            errors.append(_err(base, "invalid_type", "rectangle must be a JSON object"))
            continue

        for name in sorted(set(item) - {"id", *_COORD_FIELDS}):
            errors.append(_err(f"{base}/{name}", "unknown_field", f"unexpected field '{name}'"))

        # Identity.
        rid = item.get("id")
        if "id" not in item:
            errors.append(_err(f"{base}/id", "missing_field", "'id' is required"))
        elif isinstance(rid, bool) or not isinstance(rid, (str, int)):
            errors.append(
                _err(f"{base}/id", "invalid_type", "'id' must be a string or an integer")
            )
        elif isinstance(rid, str) and not rid:
            errors.append(_err(f"{base}/id", "invalid_value", "'id' must not be empty"))
        elif rid in seen_ids:
            errors.append(
                _err(
                    f"{base}/id",
                    "duplicate_id",
                    f"duplicate rectangle id {json.dumps(rid)}; first seen at index {seen_ids[rid]}",
                )
            )
        else:
            seen_ids[rid] = idx

        # Coordinates, checked in a fixed field order for stable output.
        coords.clear()
        for name in _COORD_FIELDS:
            if name not in item:
                errors.append(_err(f"{base}/{name}", "missing_field", f"'{name}' is required"))
                continue
            value = item[name]
            if isinstance(value, bool) or not isinstance(value, int):
                errors.append(
                    _err(
                        f"{base}/{name}",
                        "invalid_type",
                        f"'{name}' must be an integer",
                    )
                )
                continue
            if abs(value) > COORDINATE_LIMIT:
                errors.append(
                    _err(
                        f"{base}/{name}",
                        "out_of_range",
                        f"'{name}' must be between -{COORDINATE_LIMIT} and {COORDINATE_LIMIT}",
                    )
                )
                continue
            coords[name] = value

        if all(name in coords for name in _COORD_FIELDS):
            if coords["x0"] >= coords["x1"]:
                errors.append(
                    _err(
                        f"{base}/x1",
                        "invalid_bounds",
                        f"expected x0 < x1 (got {coords['x0']} >= {coords['x1']})",
                    )
                )
            if coords["y0"] >= coords["y1"]:
                errors.append(
                    _err(
                        f"{base}/y1",
                        "invalid_bounds",
                        f"expected y0 < y1 (got {coords['y0']} >= {coords['y1']})",
                    )
                )
            if coords["x0"] < coords["x1"] and coords["y0"] < coords["y1"]:
                rects[idx] = Rect(
                    coords["x0"], coords["y0"], coords["x1"], coords["y1"]
                )

    if errors:
        raise ValidationError(errors)
    return [r for r in rects if r is not None]
