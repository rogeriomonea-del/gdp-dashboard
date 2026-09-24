"""Every branch of the pure formatters in gdp_dashboard.formatting."""

from __future__ import annotations

import math

import pytest

from gdp_dashboard.formatting import (
    axis_unit,
    format_number,
    format_pct,
    format_ratio,
    format_usd,
)

NAN = float("nan")
INF = float("inf")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.234e12, "$1.23T"),
        (4.56e9, "$4.56B"),
        (7.8e6, "$7.80M"),
        (950, "$950"),
        (950.4, "$950"),
        (999_999.0, "$999,999"),
        (1e6, "$1.00M"),
        (1e9, "$1.00B"),
        (1e12, "$1.00T"),
        (1.0133e14, "$101.33T"),
        (0, "$0"),
        (0.0, "$0"),
        (-1.234e12, "-$1.23T"),
        (-4.56e9, "-$4.56B"),
        (-7.8e6, "-$7.80M"),
        (-950, "-$950"),
        (17_780_000_000.0, "$17.78B"),
    ],
)
def test_format_usd(value: float, expected: str) -> None:
    assert format_usd(value) == expected


@pytest.mark.parametrize(
    ("value", "digits", "expected"),
    [
        (999_999_999_999.999, 2, "$1.00T"),  # not "$1000.00B"
        (999_999_999.996, 2, "$1.00B"),  # not "$1000.00M"
        (999_995_000_000.0, 2, "$1.00T"),
        (999_994_999_999.0, 2, "$999.99B"),
        (999_999.6, 2, "$1.00M"),  # not "$1,000,000"
        (999_999.4, 2, "$999,999"),
        (999_999_999_999.0, 0, "$1T"),
        (999_400_000_000.0, 0, "$999B"),
        (999_999_999_999.999, 3, "$1.000T"),
        (994_999_999.0, 2, "$995.00M"),
        (-999_999_999_999.999, 2, "-$1.00T"),
        (-0.4, 2, "$0"),  # not "-$0"
        (0.4, 2, "$0"),
        (-0.6, 2, "-$1"),
        (1e15, 2, "$1000.00T"),  # no unit above trillions
    ],
)
def test_format_usd_rounds_before_choosing_the_unit(value: float, digits: int, expected: str):
    assert format_usd(value, digits=digits) == expected


def test_format_usd_digits() -> None:
    assert format_usd(1.234e12, digits=0) == "$1T"
    assert format_usd(1.234e12, digits=1) == "$1.2T"
    assert format_usd(1.234e12, digits=3) == "$1.234T"
    assert format_usd(4.5678e9, digits=1) == "$4.6B"
    assert format_usd(950, digits=3) == "$950"  # no decimals below a million


@pytest.mark.parametrize("value", [None, NAN, INF, -INF, "12"])
def test_format_usd_missing(value: object) -> None:
    assert format_usd(value) == "n/a"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (128.86, "128.9"),
        (100.0, "100.0"),
        (0, "0.0"),
        (-3.14, "-3.1"),
        (1234.56, "1,234.6"),
    ],
)
def test_format_number(value: float, expected: str) -> None:
    assert format_number(value) == expected


def test_format_number_digits_and_missing() -> None:
    assert format_number(128.86, digits=0) == "129"
    assert format_number(128.86, digits=2) == "128.86"
    for value in (None, NAN, INF, -INF, "12"):
        assert format_number(value) == "n/a"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12.345, "+12.3%"),
        (-3, "-3.0%"),
        (0, "+0.0%"),
        (0.04, "+0.0%"),
        (-0.04, "-0.0%"),
        (5869.04, "+5869.0%"),
        (100.0, "+100.0%"),
    ],
)
def test_format_pct_signed(value: float, expected: str) -> None:
    assert format_pct(value) == expected


def test_format_pct_unsigned_and_digits() -> None:
    assert format_pct(12.345, sign=False) == "12.3%"
    assert format_pct(-3, sign=False) == "-3.0%"
    assert format_pct(12.345, digits=0) == "+12%"
    assert format_pct(12.345, digits=2) == "+12.35%"
    assert format_pct(12.345, digits=2, sign=False) == "12.35%"
    assert format_pct(-3.14159, digits=3) == "-3.142%"


@pytest.mark.parametrize("value", [None, NAN, INF, -INF, "12"])
def test_format_pct_missing(value: object) -> None:
    assert format_pct(value) == "n/a"  # type: ignore[arg-type]
    assert format_pct(value, sign=False) == "n/a"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2.5, "2.50×"),
        (1, "1.00×"),
        (0.85, "0.85×"),
        (3.8571, "3.86×"),
        (0, "0.00×"),
        (-2.0, "-2.00×"),
    ],
)
def test_format_ratio(value: float, expected: str) -> None:
    assert format_ratio(value) == expected


@pytest.mark.parametrize("value", [None, NAN, INF, -INF, "2"])
def test_format_ratio_missing(value: object) -> None:
    assert format_ratio(value) == "n/a"  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5e12, (1e12, "trillion US$")),
        (1e12, (1e12, "trillion US$")),
        (1.0133e14, (1e12, "trillion US$")),
        (999e9, (1e9, "billion US$")),
        (1e9, (1e9, "billion US$")),
        (4.56e9, (1e9, "billion US$")),
        (999e6, (1e6, "million US$")),
        (1e6, (1e6, "million US$")),
        (999_999, (1, "US$")),
        (950, (1, "US$")),
        (0, (1, "US$")),
        (-5e12, (1e12, "trillion US$")),  # sign is ignored
        (-4.56e9, (1e9, "billion US$")),
    ],
)
def test_axis_unit(value: float, expected: tuple[float, str]) -> None:
    scale, unit = axis_unit(value)
    assert (scale, unit) == expected
    assert isinstance(scale, float)


@pytest.mark.parametrize("value", [NAN, INF, -INF, None])
def test_axis_unit_missing_falls_back_to_dollars(value: object) -> None:
    assert axis_unit(value) == (1.0, "US$")  # type: ignore[arg-type]


def test_formatters_round_trip_with_axis_unit() -> None:
    scale, unit = axis_unit(5.05e12)
    assert unit == "trillion US$"
    assert format_usd(5.05e12) == "$5.05T"
    assert math.isclose(5.05e12 / scale, 5.05)
