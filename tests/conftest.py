"""Shared fixtures: tiny synthetic World Bank style CSVs written into ``tmp_path``."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from gdp_dashboard.data import GdpData, load_gdp

YEARS: tuple[int, ...] = (2000, 2001, 2002, 2003, 2004, 2005)

# code -> (name, values per year in YEARS order; None = missing)
SYNTHETIC_ROWS: dict[str, tuple[str, tuple[float | None, ...]]] = {
    # steady 10 %/yr growth with a gap in 2003
    "AAA": ("Aland", (100.0, 110.0, 121.0, None, 146.41, 161.051)),
    # declining series, first and last years missing; the name contains a comma
    "BBB": ("Borduria, Republic of", (None, 200.0, 190.0, 180.0, 170.0, None)),
    # a single data point
    "CCC": ("Cisalpina", (None, None, None, None, 50.0, None)),
    # the aggregate (World): 1000 every year so shares are easy to check
    "WLD": ("World", (1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0)),
    # a series without any value at all
    "NUL": ("Nullland", (None, None, None, None, None, None)),
}

COUNTRY_META: dict[str, tuple[str, str, str]] = {
    # code -> (region, income group, is_aggregate)
    "AAA": ("Europe & Central Asia", "High income", "false"),
    "BBB": ("Europe & Central Asia", "Upper middle income", "false"),
    "CCC": ("Latin America & Caribbean", "Lower middle income", "false"),
    "WLD": ("Aggregates", "Aggregates", "true"),
    "NUL": ("Sub-Saharan Africa", "Low income", "false"),
    # metadata for a code that is NOT in the GDP file (must be ignored)
    "ZZZ": ("Nowhere", "Unknown", "false"),
}


def _cell(value: float | None) -> str:
    return "" if value is None or math.isnan(value) else repr(value)


def write_wide_csv(
    path: Path,
    rows: dict[str, tuple[str, tuple[float | None, ...]]] = SYNTHETIC_ROWS,
    years: tuple[int, ...] = YEARS,
    *,
    bom: bool = True,
    trailing_comma: bool = True,
    with_names: bool = True,
    trailing_blank_line: bool = True,
) -> Path:
    """Write a World Bank style wide CSV (quoted fields, optional BOM / trailing comma)."""
    tail = "," if trailing_comma else ""
    header = ["Country Code", "Indicator Name", "Indicator Code", *[str(y) for y in years]]
    if with_names:
        header.insert(0, "Country Name")
    lines = [",".join(f'"{h}"' for h in header) + tail]
    for code, (name, values) in rows.items():
        fields = [code, "GDP (current US$)", "NY.GDP.MKTP.CD", *[_cell(v) for v in values]]
        if with_names:
            fields.insert(0, name)
        lines.append(",".join(f'"{f}"' for f in fields) + tail)
    text = "\n".join(lines) + "\n"
    if trailing_blank_line:
        text += "\n"
    path.write_text(text, encoding="utf-8-sig" if bom else "utf-8")
    return path


def write_countries_csv(path: Path, meta: dict[str, tuple[str, str, str]] = COUNTRY_META) -> Path:
    """Write a matching countries.csv (header exactly as the refresh script writes it)."""
    lines = ["Country Code,Country Name,Region,Income Group,Is Aggregate"]
    for code in sorted(meta):
        region, income, aggregate = meta[code]
        name = SYNTHETIC_ROWS[code][0] if code in SYNTHETIC_ROWS else "Nowhere"
        quoted_name = f'"{name}"' if "," in name else name
        lines.append(f"{code},{quoted_name},{region},{income},{aggregate}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def gdp_csv(tmp_path: Path) -> Path:
    """Synthetic wide GDP CSV with BOM, trailing comma, quoted fields and a blank last line."""
    return write_wide_csv(tmp_path / "gdp_data.csv")


@pytest.fixture
def countries_csv(tmp_path: Path) -> Path:
    return write_countries_csv(tmp_path / "countries.csv")


@pytest.fixture
def data(gdp_csv: Path, countries_csv: Path) -> GdpData:
    """GdpData loaded from the synthetic fixtures (with metadata)."""
    return load_gdp(gdp_csv, countries_csv)


@pytest.fixture
def data_no_meta(gdp_csv: Path) -> GdpData:
    """GdpData loaded without a countries.csv (fallback metadata path)."""
    return load_gdp(gdp_csv, countries_path=None)
