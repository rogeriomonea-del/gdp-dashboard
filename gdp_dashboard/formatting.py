"""Pure formatting helpers (no Streamlit, no pandas)."""

from __future__ import annotations

import math

_USD_UNITS: tuple[tuple[float, str], ...] = (
    (1e12, "T"),
    (1e9, "B"),
    (1e6, "M"),
)

_AXIS_UNITS: tuple[tuple[float, str], ...] = (
    (1e12, "trillion US$"),
    (1e9, "billion US$"),
    (1e6, "million US$"),
)


def _is_missing(value: float | None) -> bool:
    """True for None, NaN and infinities: nothing sensible can be printed for them."""
    if value is None:
        return True
    try:
        return not math.isfinite(value)
    except TypeError:
        return True


def format_usd(value: float | None, digits: int = 2) -> str:
    """Format a US$ amount compactly: 1.234e12 -> "$1.23T", 950 -> "$950", None -> "n/a"."""
    if _is_missing(value):
        return "n/a"
    magnitude = abs(value)
    # Climb the units from plain dollars: whenever the *rounded* number in the current unit
    # would reach the next unit (e.g. "1000.00B"), move up, so 999.999B prints as $1.00T.
    threshold, suffix, decimals = 1.0, "", 0
    for next_threshold, next_suffix in reversed(_USD_UNITS):
        if float(f"{magnitude / threshold:.{decimals}f}") < next_threshold / threshold:
            break
        threshold, suffix, decimals = next_threshold, next_suffix, digits
    number = f"{magnitude / threshold:.{decimals}f}" if suffix else f"{magnitude:,.0f}"
    sign = "-" if value < 0 and float(number.replace(",", "")) != 0 else ""  # no "-$0"
    return f"{sign}${number}{suffix}"


def format_number(value: float | None, digits: int = 1) -> str:
    """Format a plain number (e.g. an index level): 128.86 -> "128.9", None -> "n/a"."""
    if _is_missing(value):
        return "n/a"
    return f"{value:,.{digits}f}"


def format_pct(value: float | None, digits: int = 1, sign: bool = True) -> str:
    """Format a percentage: 12.345 -> "+12.3%", -3 -> "-3.0%", None -> "n/a"."""
    if _is_missing(value):
        return "n/a"
    spec = f"+.{digits}f" if sign else f".{digits}f"
    return f"{value:{spec}}%"


def format_ratio(value: float | None) -> str:
    """Format a multiple: 2.5 -> "2.50×", None -> "n/a"."""
    if _is_missing(value):
        return "n/a"
    return f"{value:.2f}×"


def axis_unit(max_abs_value: float) -> tuple[float, str]:
    """Pick the scale and label of a US$ axis from the largest absolute value it shows."""
    if _is_missing(max_abs_value):
        return 1.0, "US$"
    magnitude = abs(max_abs_value)
    for threshold, unit in _AXIS_UNITS:
        if magnitude >= threshold:
            return threshold, unit
    return 1.0, "US$"
