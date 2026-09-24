"""Unit tests for gdp_dashboard.data against the synthetic fixtures, plus one real-data check."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from gdp_dashboard import data as gd
from gdp_dashboard.data import (
    DATA_DIR,
    DEFAULT_COUNTRIES,
    KNOWN_AGGREGATES,
    GdpData,
    GrowthSummary,
    default_from_year,
    first_valid_year,
    growth_summary,
    indexed,
    label,
    last_valid_year,
    load_gdp,
    missing_in_range,
    read_wide_csv,
    selectable_codes,
    series,
    share_of_world,
    to_long,
    yoy_growth,
)
from tests.conftest import SYNTHETIC_ROWS, YEARS, write_wide_csv

CODES = list(SYNTHETIC_ROWS)


def _nan(value: object) -> bool:
    return isinstance(value, float) and math.isnan(value)


# --------------------------------------------------------------------------------------
# read_wide_csv
# --------------------------------------------------------------------------------------


def test_read_wide_csv_tolerates_bom_trailing_column_and_quotes(gdp_csv: Path) -> None:
    wide = read_wide_csv(gdp_csv)
    assert list(wide.index) == CODES
    assert wide.index.name == "code"
    assert list(wide.columns) == list(YEARS)  # the "Unnamed: N" trailing column is ignored
    assert wide.columns.name == "year"
    assert wide.dtypes.eq("float64").all()
    assert wide.at["AAA", 2000] == 100.0
    assert _nan(wide.at["AAA", 2003])
    assert wide.loc["NUL"].isna().all()


def test_read_wide_csv_any_years_no_bom_no_trailing_comma(tmp_path: Path) -> None:
    rows = {"XXX": ("Xland", (1.0, None, 3.0)), "YYY": ("Yland", (None, 2.0, None))}
    path = write_wide_csv(
        tmp_path / "other.csv", rows, (1990, 1991, 1995), bom=False, trailing_comma=False
    )
    wide = read_wide_csv(path)
    assert list(wide.columns) == [1990, 1991, 1995]
    assert list(wide.index) == ["XXX", "YYY"]
    assert wide.at["YYY", 1991] == 2.0


def test_read_wide_csv_ignores_non_year_columns_and_sorts_years(tmp_path: Path) -> None:
    path = tmp_path / "shuffled.csv"
    path.write_text(
        "Country Code,2001,Notes,1999,Country Name\nAAA,1.5,hello,0.5,Aland\n", encoding="utf-8"
    )
    wide = read_wide_csv(path)
    assert list(wide.columns) == [1999, 2001]
    assert wide.at["AAA", 1999] == 0.5


def test_read_wide_csv_drops_blank_and_duplicate_codes(tmp_path: Path) -> None:
    path = tmp_path / "dupes.csv"
    path.write_text(
        "Country Code,2000,2001\nAAA,1,2\n,3,4\nAAA,5,6\n  BBB ,7,8\n", encoding="utf-8"
    )
    wide = read_wide_csv(path)
    assert list(wide.index) == ["AAA", "BBB"]
    assert wide.at["AAA", 2000] == 1.0  # first occurrence wins
    assert wide.at["BBB", 2001] == 8.0


def test_read_wide_csv_coerces_non_numeric_cells(tmp_path: Path) -> None:
    path = tmp_path / "placeholders.csv"
    path.write_text("Country Code,2000,2001\nAAA,1.5,..\nBBB,n/a,2\n", encoding="utf-8")
    wide = read_wide_csv(path)
    assert wide.dtypes.eq("float64").all()
    assert wide.at["AAA", 2000] == 1.5
    assert _nan(wide.at["AAA", 2001]) and _nan(wide.at["BBB", 2000])
    assert wide.at["BBB", 2001] == 2.0


def test_read_wide_csv_rejects_files_without_code_or_year_columns(tmp_path: Path) -> None:
    no_code = tmp_path / "no_code.csv"
    no_code.write_text("Country Name,2000\nAland,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Country Code"):
        read_wide_csv(no_code)
    no_years = tmp_path / "no_years.csv"
    no_years.write_text("Country Name,Country Code\nAland,AAA\n", encoding="utf-8")
    with pytest.raises(ValueError, match="year"):
        read_wide_csv(no_years)


# --------------------------------------------------------------------------------------
# load_gdp
# --------------------------------------------------------------------------------------


def test_load_gdp_shapes_and_dtypes(data: GdpData) -> None:
    assert isinstance(data, GdpData)
    assert (data.min_year, data.max_year) == (2000, 2005)

    # wide: every year min..max, one column per code, NaN where missing
    assert list(data.wide.index) == list(YEARS)
    assert data.wide.index.name == "year"
    assert str(data.wide.index.dtype) == "int64"
    assert list(data.wide.columns) == CODES
    assert data.wide.columns.name == "code"
    assert data.wide.dtypes.eq("float64").all()
    assert data.wide.at[2005, "AAA"] == pytest.approx(161.051)
    assert _nan(data.wide.at[2000, "BBB"])

    # tidy: NaN rows dropped, sorted by code then year
    assert list(data.tidy.columns) == ["code", "year", "gdp"]
    assert str(data.tidy["year"].dtype) == "int64"
    assert str(data.tidy["gdp"].dtype) == "float64"
    assert data.tidy["gdp"].notna().all()
    expected_rows = sum(v is not None for _, vals in SYNTHETIC_ROWS.values() for v in vals)
    assert len(data.tidy) == expected_rows
    assert data.tidy.equals(data.tidy.sort_values(["code", "year"]).reset_index(drop=True))
    assert list(data.tidy.loc[data.tidy["code"] == "CCC", "year"]) == [2004]

    # countries: one row per code in the GDP file, metadata joined, extra codes ignored
    assert list(data.countries.columns) == ["name", "region", "income_group", "is_aggregate"]
    assert list(data.countries.index) == CODES
    assert "ZZZ" not in data.countries.index
    assert data.countries.at["BBB", "name"] == "Borduria, Republic of"
    assert data.countries.at["AAA", "region"] == "Europe & Central Asia"
    assert data.countries.at["CCC", "income_group"] == "Lower middle income"
    assert data.countries["is_aggregate"].dtype == bool
    assert bool(data.countries.at["WLD", "is_aggregate"])
    assert not data.countries.at["AAA", "is_aggregate"]


def test_load_gdp_accepts_str_paths(gdp_csv: Path, countries_csv: Path) -> None:
    loaded = load_gdp(str(gdp_csv), str(countries_csv))
    assert loaded.max_year == 2005


def test_load_gdp_missing_countries_file_falls_back(gdp_csv: Path, tmp_path: Path) -> None:
    loaded = load_gdp(gdp_csv, tmp_path / "does-not-exist.csv")
    assert loaded.countries.at["AAA", "name"] == "Aland"
    assert loaded.countries.at["AAA", "region"] == gd.UNKNOWN
    assert bool(loaded.countries.at["WLD", "is_aggregate"])
    assert not loaded.countries.at["AAA", "is_aggregate"]


def test_load_gdp_partial_metadata_is_filled_from_gdp_file(gdp_csv: Path, tmp_path: Path) -> None:
    meta = tmp_path / "countries.csv"
    meta.write_text(
        "Country Code,Country Name,Region,Income Group,Is Aggregate\nAAA,Aland renamed,,,false\n",
        encoding="utf-8",
    )
    loaded = load_gdp(gdp_csv, meta)
    assert loaded.countries.at["AAA", "name"] == "Aland renamed"
    assert loaded.countries.at["AAA", "region"] == gd.UNKNOWN
    assert loaded.countries.at["BBB", "name"] == "Borduria, Republic of"  # from the GDP file
    assert bool(loaded.countries.at["WLD", "is_aggregate"])  # from KNOWN_AGGREGATES
    assert not loaded.countries.at["NUL", "is_aggregate"]


@pytest.mark.parametrize(
    "content",
    ["", "\n\n", 'Country Code,Country Name,Region,Income Group,Is Aggregate\nAAA,"Aland re'],
    ids=["empty", "whitespace", "truncated-quote"],
)
def test_load_gdp_unreadable_countries_file_falls_back(
    gdp_csv: Path, tmp_path: Path, content: str
) -> None:
    """An empty or truncated countries.csv must not take the GDP data down with it."""
    meta = tmp_path / "countries.csv"
    meta.write_text(content, encoding="utf-8")
    loaded = load_gdp(gdp_csv, meta)
    assert loaded.max_year == 2005
    assert loaded.countries.at["AAA", "name"] == "Aland"  # from the GDP file
    assert loaded.countries.at["AAA", "region"] == gd.UNKNOWN
    assert bool(loaded.countries.at["WLD", "is_aggregate"])  # from KNOWN_AGGREGATES


def test_load_gdp_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("Country Name,Country Code,2000\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_gdp(path, None)


def test_load_gdp_does_not_mutate_inputs(data: GdpData) -> None:
    before = data.wide.copy()
    subset = series(data, ["AAA", "BBB"], 2000, 2005)
    subset.iloc[0, 0] = -1.0
    indexed(subset)
    yoy_growth(subset)
    share_of_world(data, subset)
    to_long(subset, data)
    growth_summary(data, "AAA", 2000, 2005)
    pd.testing.assert_frame_equal(data.wide, before)


# --------------------------------------------------------------------------------------
# metadata helpers
# --------------------------------------------------------------------------------------


def test_selectable_codes_excludes_aggregates_and_all_null_series(data: GdpData) -> None:
    assert selectable_codes(data) == ["AAA", "BBB", "CCC"]  # sorted by name
    assert selectable_codes(data, include_aggregates=True) == ["AAA", "BBB", "CCC", "WLD"]
    assert "NUL" not in selectable_codes(data, include_aggregates=True)


def test_selectable_codes_sorts_by_name_case_insensitively(tmp_path: Path) -> None:
    rows = {
        "BBB": ("zeta", (1.0,)),
        "AAA": ("Alpha", (1.0,)),
        "CCC": ("beta", (1.0,)),
    }
    loaded = load_gdp(write_wide_csv(tmp_path / "g.csv", rows, (2000,)), None)
    assert selectable_codes(loaded) == ["AAA", "CCC", "BBB"]


def test_filter_codes(data: GdpData) -> None:
    codes = ["AAA", "BBB", "CCC", "WLD"]
    assert gd.filter_codes(data, codes, [], []) == codes
    assert gd.filter_codes(data, codes, ["Europe & Central Asia"], []) == ["AAA", "BBB"]
    assert gd.filter_codes(data, codes, [], ["High income"]) == ["AAA"]
    assert gd.filter_codes(data, codes, ["Europe & Central Asia"], ["Upper middle income"]) == [
        "BBB"
    ]
    assert gd.filter_codes(data, codes, ["Nowhere"], []) == []
    assert gd.filter_codes(data, ["CCC", "AAA"], ["Latin America & Caribbean"], []) == ["CCC"]
    assert gd.filter_codes(data, ["AAA", "QQQ"], ["Europe & Central Asia"], []) == ["AAA"]
    assert gd.filter_codes(data, [], ["Europe & Central Asia"], []) == []


def test_label_uses_name_and_code(data: GdpData) -> None:
    assert label(data, "AAA") == "Aland (AAA)"
    assert label(data, "BBB") == "Borduria, Republic of (BBB)"
    assert label(data, "WLD") == "World (WLD)"
    assert label(data, "QQQ") == "QQQ"  # unknown code falls back to the code


def test_label_falls_back_when_countries_csv_is_absent(data_no_meta: GdpData) -> None:
    assert label(data_no_meta, "AAA") == "Aland (AAA)"  # name from the GDP file
    assert gd.is_aggregate(data_no_meta, "WLD")
    assert not gd.is_aggregate(data_no_meta, "AAA")


def test_label_falls_back_to_code_without_any_names(tmp_path: Path) -> None:
    path = write_wide_csv(tmp_path / "nonames.csv", with_names=False)
    loaded = load_gdp(path, None)
    assert label(loaded, "AAA") == "AAA"
    assert gd.name_of(loaded, "AAA") == "AAA"
    assert selectable_codes(loaded) == ["AAA", "BBB", "CCC"]


def test_known_aggregates_contains_expected_codes() -> None:
    assert isinstance(KNOWN_AGGREGATES, frozenset)
    assert {"WLD", "EUU", "HIC", "ARB", "LIC", "UMC"} <= KNOWN_AGGREGATES
    assert not {"DEU", "BRA", "USA"} & KNOWN_AGGREGATES
    assert len(KNOWN_AGGREGATES) == 49


# --------------------------------------------------------------------------------------
# year helpers
# --------------------------------------------------------------------------------------


def test_default_from_year(data: GdpData) -> None:
    assert default_from_year(data, ["AAA"]) == 2000
    assert default_from_year(data, ["AAA", "BBB"]) == 2001
    assert default_from_year(data, ["AAA", "BBB", "NUL"]) == 2001  # no-data codes ignored
    assert default_from_year(data, ["AAA", "QQQ"]) == 2000  # unknown codes ignored
    assert default_from_year(data, []) == data.min_year
    assert default_from_year(data, ["NUL"]) == data.min_year
    # clamped to max_year - 1 so the default range always spans two years
    assert default_from_year(data, ["CCC"]) == 2004
    assert default_from_year(data, ["AAA"], floor=2003) == 2003
    assert default_from_year(data, ["AAA"], floor=2999) == data.max_year - 1
    assert default_from_year(data, ["AAA"], floor=1900) == 2000


def test_default_from_year_requires_every_code_to_have_a_value(tmp_path: Path) -> None:
    """A code with an internal gap at another code's first year pushes the default later."""
    rows = {"AAA": ("A", (1.0, None, 3.0, 4.0)), "BBB": ("B", (None, 2.0, 3.0, 4.0))}
    loaded = load_gdp(write_wide_csv(tmp_path / "g.csv", rows, (2000, 2001, 2002, 2003)), None)
    assert default_from_year(loaded, ["AAA", "BBB"]) == 2002  # 2001: AAA is null
    assert default_from_year(loaded, ["BBB", "AAA", "AAA"]) == 2002  # order / duplicates
    assert default_from_year(loaded, ["AAA"]) == 2000
    assert default_from_year(loaded, ["BBB"]) == 2001
    # no year has both values: fall back to min_year
    disjoint = {"AAA": ("A", (1.0, None, None)), "BBB": ("B", (None, None, 3.0))}
    loaded = load_gdp(write_wide_csv(tmp_path / "d.csv", disjoint, (2000, 2001, 2002)), None)
    assert default_from_year(loaded, ["AAA", "BBB"]) == 2000


def test_first_and_last_valid_year_with_gaps(data: GdpData) -> None:
    assert first_valid_year(data, "AAA", 2000, 2005) == 2000
    assert last_valid_year(data, "AAA", 2000, 2005) == 2005
    assert first_valid_year(data, "AAA", 2003, 2005) == 2004  # 2003 is a gap
    assert last_valid_year(data, "AAA", 2000, 2003) == 2002
    assert first_valid_year(data, "BBB", 2000, 2005) == 2001
    assert last_valid_year(data, "BBB", 2000, 2005) == 2004
    assert first_valid_year(data, "CCC", 2000, 2005) == 2004
    assert last_valid_year(data, "CCC", 2000, 2005) == 2004
    assert first_valid_year(data, "CCC", 2000, 2003) is None
    assert last_valid_year(data, "CCC", 2000, 2003) is None
    assert first_valid_year(data, "NUL", 2000, 2005) is None
    assert first_valid_year(data, "QQQ", 2000, 2005) is None  # unknown code
    # out-of-range bounds are tolerated
    assert first_valid_year(data, "AAA", 1900, 2100) == 2000
    assert last_valid_year(data, "AAA", 1900, 2100) == 2005
    assert first_valid_year(data, "AAA", 2010, 2020) is None
    assert isinstance(first_valid_year(data, "AAA", 2000, 2005), int)


def test_missing_in_range(data: GdpData) -> None:
    assert missing_in_range(data, CODES, 2000, 2005) == ["NUL"]
    assert missing_in_range(data, CODES, 2000, 2003) == ["CCC", "NUL"]
    assert missing_in_range(data, ["BBB", "AAA"], 2000, 2000) == ["BBB"]
    assert missing_in_range(data, ["AAA", "QQQ"], 2000, 2005) == ["QQQ"]
    assert missing_in_range(data, [], 2000, 2005) == []


# --------------------------------------------------------------------------------------
# growth maths
# --------------------------------------------------------------------------------------


def test_growth_summary_maths(data: GdpData) -> None:
    summary = growth_summary(data, "AAA", 2000, 2005)
    assert isinstance(summary, GrowthSummary)
    assert (summary.code, summary.start_year, summary.end_year) == ("AAA", 2000, 2005)
    assert summary.start_value == 100.0
    assert summary.end_value == pytest.approx(161.051)
    assert summary.ratio == pytest.approx(1.61051)
    assert summary.pct_change == pytest.approx(61.051)
    assert summary.cagr == pytest.approx(10.0)


def test_growth_summary_uses_first_and_last_valid_years_inside_range(data: GdpData) -> None:
    summary = growth_summary(data, "BBB", 2000, 2005)  # 2000 and 2005 are missing
    assert summary is not None
    assert (summary.start_year, summary.end_year) == (2001, 2004)
    assert summary.ratio == pytest.approx(0.85)
    assert summary.pct_change == pytest.approx(-15.0)
    assert summary.cagr == pytest.approx((0.85 ** (1 / 3) - 1) * 100)
    assert summary.cagr < 0

    narrowed = growth_summary(data, "AAA", 2003, 2005)  # 2003 is a gap
    assert narrowed is not None
    assert (narrowed.start_year, narrowed.end_year) == (2004, 2005)
    assert narrowed.ratio == pytest.approx(1.1)


def test_growth_summary_single_point(data: GdpData) -> None:
    summary = growth_summary(data, "CCC", 2000, 2005)
    assert summary is not None
    assert summary.start_year == summary.end_year == 2004
    assert summary.start_value == summary.end_value == 50.0
    assert summary.ratio == 1.0
    assert summary.pct_change == 0.0
    assert summary.cagr is None

    same_year = growth_summary(data, "AAA", 2002, 2002)
    assert same_year is not None
    assert same_year.cagr is None and same_year.ratio == 1.0


def test_growth_summary_none_when_no_data(data: GdpData) -> None:
    assert growth_summary(data, "NUL", 2000, 2005) is None
    assert growth_summary(data, "CCC", 2000, 2003) is None
    assert growth_summary(data, "QQQ", 2000, 2005) is None
    assert growth_summary(data, "AAA", 2005, 2000) is None  # inverted range


def test_growth_summary_zero_start_value(tmp_path: Path) -> None:
    rows = {"ZER": ("Zero", (0.0, 5.0)), "NEG": ("Negative", (-2.0, 4.0))}
    loaded = load_gdp(write_wide_csv(tmp_path / "z.csv", rows, (2000, 2001)), None)
    zero = growth_summary(loaded, "ZER", 2000, 2001)
    assert zero is not None
    assert _nan(zero.ratio) and _nan(zero.pct_change)
    assert zero.cagr is None
    negative = growth_summary(loaded, "NEG", 2000, 2001)
    assert negative is not None
    assert negative.ratio == -2.0
    assert negative.cagr is None  # no real CAGR for a sign change


# --------------------------------------------------------------------------------------
# views
# --------------------------------------------------------------------------------------


def test_series_keeps_nan_and_selection_order(data: GdpData) -> None:
    subset = series(data, ["BBB", "AAA", "QQQ"], 2001, 2004)
    assert list(subset.columns) == ["BBB", "AAA", "QQQ"]
    assert list(subset.index) == [2001, 2002, 2003, 2004]
    assert _nan(subset.at[2003, "AAA"])
    assert subset["QQQ"].isna().all()
    assert subset.at[2001, "BBB"] == 200.0
    assert series(data, [], 2000, 2005).shape == (6, 0)
    assert subset.columns.name == "code" and subset.index.name == "year"
    # duplicates are dropped (a frame with duplicate columns cannot be stacked)
    assert list(series(data, ["AAA", "AAA", "BBB"], 2000, 2005).columns) == ["AAA", "BBB"]


def test_indexed(data: GdpData) -> None:
    out = indexed(series(data, ["AAA", "BBB", "NUL"], 2000, 2005))
    assert out.at[2000, "AAA"] == pytest.approx(100.0)
    assert out.at[2002, "AAA"] == pytest.approx(121.0)
    assert _nan(out.at[2003, "AAA"])
    assert out.at[2005, "AAA"] == pytest.approx(161.051)
    # first non-null value is the base, not the first row
    assert _nan(out.at[2000, "BBB"])
    assert out.at[2001, "BBB"] == pytest.approx(100.0)
    assert out.at[2004, "BBB"] == pytest.approx(85.0)
    assert out["NUL"].isna().all()
    assert indexed(series(data, [], 2000, 2005)).empty


def test_yoy_growth(data: GdpData) -> None:
    out = yoy_growth(series(data, ["AAA", "BBB"], 2000, 2005))
    assert _nan(out.at[2000, "AAA"])  # first year
    assert out.at[2001, "AAA"] == pytest.approx(10.0)
    assert out.at[2002, "AAA"] == pytest.approx(10.0)
    assert _nan(out.at[2003, "AAA"])  # the gap itself
    assert _nan(out.at[2004, "AAA"])  # right after the gap: no previous value
    assert out.at[2005, "AAA"] == pytest.approx(10.0)
    assert out.at[2002, "BBB"] == pytest.approx(-5.0)
    assert _nan(out.at[2005, "BBB"])


def test_share_of_world(data: GdpData) -> None:
    out = share_of_world(data, series(data, ["AAA", "WLD", "NUL"], 2000, 2005))
    assert out.at[2000, "AAA"] == pytest.approx(10.0)
    assert out.at[2005, "AAA"] == pytest.approx(16.1051)
    assert _nan(out.at[2003, "AAA"])
    assert (out["WLD"] == 100.0).all()
    assert out["NUL"].isna().all()


def test_share_of_world_without_world_row(tmp_path: Path) -> None:
    rows = {"AAA": ("Aland", (1.0, 2.0))}
    loaded = load_gdp(write_wide_csv(tmp_path / "noworld.csv", rows, (2000, 2001)), None)
    out = share_of_world(loaded, series(loaded, ["AAA"], 2000, 2001))
    assert out.shape == (2, 1)
    assert out["AAA"].isna().all()


def test_to_long(data: GdpData) -> None:
    subset = series(data, ["BBB", "AAA"], 2000, 2002)
    long = to_long(subset, data)
    assert list(long.columns) == ["year", "code", "name", "value"]
    assert len(long) == 6  # NaN rows kept by default (chart gaps)
    assert str(long["year"].dtype) == "int64"
    assert set(long["code"]) == {"AAA", "BBB"}
    assert long.loc[long["code"] == "BBB", "name"].eq("Borduria, Republic of").all()
    aaa = long[long["code"] == "AAA"].set_index("year")["value"]
    assert list(aaa.index) == [2000, 2001, 2002]
    assert aaa[2001] == 110.0

    compact = to_long(subset, data, dropna=True)
    assert len(compact) == 5
    assert compact["value"].notna().all()
    assert to_long(series(data, [], 2000, 2002), data).empty
    # names fall back to the code for unknown codes and for files without names
    unknown = to_long(series(data, ["QQQ", "AAA"], 2000, 2001), data)
    assert list(unknown["name"].unique()) == ["Aland", "QQQ"]
    assert str(unknown["name"].dtype) != "object" or unknown["name"].map(type).eq(str).all()


def test_to_long_names_without_metadata(tmp_path: Path) -> None:
    loaded = load_gdp(write_wide_csv(tmp_path / "nonames.csv", with_names=False), None)
    long = to_long(series(loaded, ["BBB", "AAA"], 2000, 2001), loaded)
    assert list(long["name"]) == list(long["code"]) == ["AAA", "AAA", "BBB", "BBB"]


# --------------------------------------------------------------------------------------
# the real data files
# --------------------------------------------------------------------------------------


def test_real_data_invariants() -> None:
    gdp_path = DATA_DIR / "gdp_data.csv"
    assert gdp_path.is_file()
    real = load_gdp()

    assert real.min_year == 1960
    assert real.max_year >= 2022
    assert list(real.wide.index) == list(range(real.min_year, real.max_year + 1))
    assert real.wide.columns.is_unique
    assert not real.tidy.duplicated(subset=["code", "year"]).any()
    assert set(real.countries.index) == set(real.wide.columns)

    for code in DEFAULT_COUNTRIES:
        assert code in real.wide.columns
        assert label(real, code) != code  # has a name
        assert not gd.is_aggregate(real, code)
    assert gd.is_aggregate(real, "WLD")
    assert "WLD" in real.wide.columns

    countries = selectable_codes(real)
    everything = selectable_codes(real, include_aggregates=True)
    assert set(DEFAULT_COUNTRIES) <= set(countries) < set(everything)
    assert "WLD" in everything and "WLD" not in countries
    assert not any(gd.is_aggregate(real, c) for c in countries)
    # every selectable code has data; every all-null series is excluded
    assert not missing_in_range(real, everything, real.min_year, real.max_year)
    all_null = [c for c in real.wide.columns if real.wide[c].isna().all()]
    assert not set(all_null) & set(everything)

    # every default country has a growth delta on first load (C3)
    start = default_from_year(real, DEFAULT_COUNTRIES)
    assert real.min_year <= start < real.max_year
    for code in DEFAULT_COUNTRIES:
        summary = growth_summary(real, code, start, real.max_year)
        assert summary is not None
        assert summary.start_year == start
        assert summary.end_year > summary.start_year
        assert summary.cagr is not None
        assert math.isfinite(summary.pct_change)

    # AFG (C1): a series with leading/trailing gaps is "missing" only in a range that ends
    # before its first value (expectations derived from the frame, not hard-coded).
    afg_first = int(real.wide["AFG"].first_valid_index())
    afg_last = int(real.wide["AFG"].last_valid_index())
    if afg_first > real.min_year:
        assert missing_in_range(real, ["AFG"], real.min_year, afg_first - 1) == ["AFG"]
    assert missing_in_range(real, ["AFG"], afg_first, afg_last) == []

    # DEU / BRA / AFG behave as the frame says they should (C1, C3)
    for code in ("DEU", "BRA", "AFG"):
        column = real.wide[code]
        first = int(column.first_valid_index())
        last = int(column.last_valid_index())
        assert first_valid_year(real, code, real.min_year, real.max_year) == first
        assert last_valid_year(real, code, real.min_year, real.max_year) == last
        summary = growth_summary(real, code, real.min_year, real.max_year)
        assert summary is not None
        assert (summary.start_year, summary.end_year) == (first, last)
        assert summary.end_value == column.loc[last]
        assert math.isfinite(summary.end_value)
    assert default_from_year(real, ("DEU", "BRA")) == max(
        int(real.wide["DEU"].first_valid_index()), int(real.wide["BRA"].first_valid_index())
    )
