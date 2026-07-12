"""Validation helpers for security-relevant OPA request input."""

from __future__ import annotations

import math
import re
from numbers import Real


_DECIMAL_PATTERN = re.compile(r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)")


def parse_numeric_value(value: object) -> float:
    """Return a finite numeric target value or raise ``ValueError``.

    OPA decisions must never be made with an invented fallback value.  The
    gateway protocol currently supplies the modification as a numeric string,
    so text surrounding the number is intentionally rejected.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError("modification must be a finite number")

    if isinstance(value, Real):
        parsed = float(value)
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized or _DECIMAL_PATTERN.fullmatch(normalized) is None:
            raise ValueError("modification must contain only one numeric value")
        parsed = float(normalized.replace(",", "."))
    else:
        raise ValueError("modification must be a number or numeric string")

    if not math.isfinite(parsed):
        raise ValueError("modification must be finite")
    return parsed
