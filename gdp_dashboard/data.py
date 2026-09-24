"""Pure pandas helpers for the GDP dashboard: loading, tidying, metadata and growth maths.

Nothing in here imports Streamlit, touches global state or mutates its inputs, so every
function can be unit-tested with a small synthetic CSV.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"

# World Bank aggregate codes (regions, income groups, lending categories, World) used when
# data/countries.csv is absent or does not list a code.
KNOWN_AGGREGATES: frozenset[str] = frozenset(
    {
        "AFE", "AFW", "ARB", "CEB", "CSS", "EAP", "EAR", "EAS", "ECA", "ECS", "EMU", "EUU",
        "FCS", "HIC", "HPC", "IBD", "IBT", "IDA", "IDB", "IDX", "INX", "LAC", "LCN", "LDC",
        "LIC", "LMC", "LMY", "LTE", "MEA", "MIC", "MNA", "NAC", "OED", "OSS", "PRE", "PSS",
        "PST", "SAS", "SSA", "SSF", "SST", "TEA", "TEC", "TLA", "TMN", "TSA", "TSS", "UMC",
        "WLD",
    }
)  # fmt: skip

DEFAULT_COUNTRIES: tuple[str, ...] = ("DEU", "FRA", "GBR", "BRA", "MEX", "JPN")

WORLD_CODE = "WLD"
UNKNOWN = "Unknown"

_CODE_COL = "Country Code"
_NAME_COL = "Country Name"
_COUNTRY_COLUMNS = ("name", "region", "income_group", "is_aggregate")


@dataclass(frozen=True)
class GdpData:
    """Everything the UI needs, loaded once."""

    tidy: pd.DataFrame  # columns: code (str), year (int64), gdp (float64); NaN rows dropped
    wide: pd.DataFrame  # index: year (int64, every year min..max); columns: code; NaN = missing
    countries: pd.DataFrame  # index: code; columns: name, region, income_group, is_aggregate
    min_year: int
    max_year: int


@dataclass(frozen=True)
class GrowthSummary:
    """Growth of one series between the first and last valid years inside a range."""

    code: str
    start_year: int
    end_year: int
    start_value: float
    end_value: float
    ratio: float  # end / start
    pct_change: float  # (ratio - 1) * 100
    cagr: float | None  # % per year; None when start_year == end_year


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def _is_year(column: object) -> bool:
    """Year columns are exactly the headers that are all digits."""
    return str(column).strip().isdigit()


def _read_wide(path: Path | str, *, with_names: bool) -> tuple[pd.DataFrame, pd.Series]:
    """Read the World Bank wide CSV: (index=code, columns=int years) plus a code->name series."""
    wanted = {_CODE_COL, _NAME_COL} if with_names else {_CODE_COL}
    raw = pd.read_csv(  # one pass: only the code / name / year columns are parsed
        path,
        usecols=lambda c: c in wanted or _is_year(c),
        encoding="utf-8-sig",
        skip_blank_lines=True,
    )
    if _CODE_COL not in raw.columns:
        raise ValueError(f"{path}: missing required column {_CODE_COL!r}")
    year_cols = [c for c in raw.columns if _is_year(c)]
    if not year_cols:
        raise ValueError(f"{path}: no year columns (all-digit headers) found")
    has_names = with_names and _NAME_COL in raw.columns

    raw = raw.dropna(subset=[_CODE_COL])
    codes = raw[_CODE_COL].astype(str).str.strip()
    raw = raw.assign(**{_CODE_COL: codes})
    raw = raw[codes != ""].drop_duplicates(subset=[_CODE_COL], keep="first")

    values = raw[year_cols]
    if not all(pd.api.types.is_numeric_dtype(d) for d in values.dtypes):
        values = values.apply(pd.to_numeric, errors="coerce")  # e.g. ".." placeholders
    values = values.astype("float64")
    values.index = pd.Index(raw[_CODE_COL].to_numpy(), name="code")
    values.columns = pd.Index([int(c) for c in year_cols], name="year")
    values = values.sort_index(axis=1)

    if has_names:
        names = raw[_NAME_COL].astype("string").fillna("").astype(str).str.strip()
    else:
        names = pd.Series("", index=range(len(raw)), dtype=str)
    names = pd.Series(names.to_numpy(), index=values.index, name="name")
    return values, names


def read_wide_csv(path: Path | str) -> pd.DataFrame:
    """Return the GDP file as index=code, columns=int years (digit headers only), float values.

    Tolerates a BOM, a trailing empty column, quoted fields, blank lines and any set of years.
    """
    values, _ = _read_wide(path, with_names=False)
    return values


def read_countries_csv(path: Path | str) -> pd.DataFrame:
    """Read data/countries.csv into index=code, columns name/region/income_group/is_aggregate."""
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    raw = raw.rename(
        columns={
            _CODE_COL: "code",
            _NAME_COL: "name",
            "Region": "region",
            "Income Group": "income_group",
            "Is Aggregate": "is_aggregate",
        }
    )
    if "code" not in raw.columns:
        raise ValueError(f"{path}: missing required column {_CODE_COL!r}")
    for col in ("name", "region", "income_group"):
        if col not in raw.columns:
            raw[col] = ""
        raw[col] = raw[col].astype(str).str.strip()
    flag = raw["is_aggregate"] if "is_aggregate" in raw.columns else pd.Series("", index=raw.index)
    raw["is_aggregate"] = flag.astype(str).str.strip().str.lower().eq("true")
    raw["code"] = raw["code"].astype(str).str.strip()
    raw = raw[raw["code"] != ""].drop_duplicates(subset=["code"], keep="first")
    return raw.set_index("code")[list(_COUNTRY_COLUMNS)]


def _build_countries(codes: pd.Index, names: pd.Series, meta: pd.DataFrame | None) -> pd.DataFrame:
    """One metadata row per code in the GDP file, filling gaps from the GDP file itself."""
    fallback = pd.DataFrame(
        {
            "name": names.reindex(codes).fillna("").to_numpy(),
            "region": UNKNOWN,
            "income_group": UNKNOWN,
            "is_aggregate": [c in KNOWN_AGGREGATES for c in codes],
        },
        index=codes,
    )
    if meta is None:
        countries = fallback
    else:
        meta = meta.reindex(codes)
        countries = pd.DataFrame(
            {
                "name": meta["name"].where(meta["name"].fillna("") != "", fallback["name"]),
                "region": meta["region"].where(meta["region"].fillna("") != "", UNKNOWN),
                "income_group": meta["income_group"].where(
                    meta["income_group"].fillna("") != "", UNKNOWN
                ),
                "is_aggregate": meta["is_aggregate"].where(
                    meta["is_aggregate"].notna(), fallback["is_aggregate"]
                ),
            },
            index=codes,
        )
    countries = countries.astype(
        {"name": str, "region": str, "income_group": str, "is_aggregate": bool}
    )
    countries["name"] = countries["name"].where(countries["name"] != "", pd.Series(codes, codes))
    countries.index.name = "code"
    return countries


def load_gdp(
    gdp_path: Path | str = DATA_DIR / "gdp_data.csv",
    countries_path: Path | str | None = DATA_DIR / "countries.csv",
) -> GdpData:
    """Load the GDP file (and the optional countries metadata) into a GdpData bundle."""
    by_code, names = _read_wide(gdp_path, with_names=True)
    if by_code.empty:
        raise ValueError(f"{gdp_path}: no data rows")

    min_year = int(by_code.columns.min())
    max_year = int(by_code.columns.max())
    wide = by_code.T.reindex(pd.RangeIndex(min_year, max_year + 1, name="year"))
    wide.index = wide.index.astype("int64")
    wide.columns = pd.Index(wide.columns.astype(str), name="code")

    tidy = (  # stack is much cheaper than melt for a numeric frame
        wide.stack(future_stack=True)
        .dropna()
        .rename("gdp")
        .reset_index()
        .astype({"code": str, "year": "int64", "gdp": "float64"})
        .sort_values(["code", "year"], kind="stable")
        .reset_index(drop=True)
        .loc[:, ["code", "year", "gdp"]]
    )

    meta = None
    if countries_path is not None and Path(countries_path).is_file():
        try:
            meta = read_countries_csv(countries_path)
        except ValueError:  # EmptyDataError / ParserError: an empty or truncated file
            meta = None  # names fall back to the GDP file, aggregates to KNOWN_AGGREGATES
    countries = _build_countries(wide.columns, names, meta)

    return GdpData(tidy=tidy, wide=wide, countries=countries, min_year=min_year, max_year=max_year)


# --------------------------------------------------------------------------------------
# Metadata helpers
# --------------------------------------------------------------------------------------


def name_of(data: GdpData, code: str) -> str:
    """Country name for a code, falling back to the code itself."""
    if code in data.countries.index:
        name = str(data.countries.at[code, "name"])
        if name:
            return name
    return code


def label(data: GdpData, code: str) -> str:
    """Display label such as "Brazil (BRA)"; falls back to the bare code."""
    name = name_of(data, code)
    return code if name == code else f"{name} ({code})"


def is_aggregate(data: GdpData, code: str) -> bool:
    """True for World Bank aggregates (regions, income groups, World)."""
    if code in data.countries.index:
        return bool(data.countries.at[code, "is_aggregate"])
    return code in KNOWN_AGGREGATES


def codes_with_data(data: GdpData) -> list[str]:
    """Codes that have at least one non-null value, in file order."""
    has_data = data.wide.notna().any(axis=0)
    return [str(c) for c in has_data.index[has_data.to_numpy()]]


def selectable_codes(data: GdpData, include_aggregates: bool = False) -> list[str]:
    """Codes with data, aggregates excluded unless asked, sorted by display name."""
    codes = codes_with_data(data)
    meta = data.countries.reindex(codes)  # vectorised equivalents of name_of / is_aggregate
    names = meta["name"].fillna("").astype(str)
    names = names.where(names != "", meta.index.to_series())
    known = pd.Series([c in KNOWN_AGGREGATES for c in codes], index=meta.index)
    aggregate = meta["is_aggregate"].where(meta["is_aggregate"].notna(), known).astype(bool)
    order = pd.DataFrame({"key": names.str.casefold().to_numpy(), "code": codes})
    if not include_aggregates:
        order = order[~aggregate.to_numpy()]
    return [str(c) for c in order.sort_values(["key", "code"], kind="stable")["code"]]


def filter_codes(
    data: GdpData, codes: Sequence[str], regions: Iterable[str], incomes: Iterable[str]
) -> list[str]:
    """Codes (in the given order) whose region / income group match; an empty filter keeps all."""
    regions, incomes = list(regions), list(incomes)
    if not regions and not incomes:
        return list(codes)
    meta = data.countries.reindex(codes)
    keep = pd.Series(True, index=meta.index)
    if regions:
        keep &= meta["region"].isin(regions)
    if incomes:
        keep &= meta["income_group"].isin(incomes)
    return [c for c, k in zip(codes, keep.to_numpy(), strict=True) if k]


# --------------------------------------------------------------------------------------
# Year helpers
# --------------------------------------------------------------------------------------


def _column(data: GdpData, code: str) -> pd.Series | None:
    return data.wide[code] if code in data.wide.columns else None


def first_valid_year(data: GdpData, code: str, from_year: int, to_year: int) -> int | None:
    """Earliest year in [from_year, to_year] with a value for `code`, or None."""
    col = _column(data, code)
    if col is None:
        return None
    year = col.loc[from_year:to_year].first_valid_index()
    return None if year is None else int(year)


def last_valid_year(data: GdpData, code: str, from_year: int, to_year: int) -> int | None:
    """Latest year in [from_year, to_year] with a value for `code`, or None."""
    col = _column(data, code)
    if col is None:
        return None
    year = col.loc[from_year:to_year].last_valid_index()
    return None if year is None else int(year)


def default_from_year(data: GdpData, codes: Iterable[str], floor: int | None = None) -> int:
    """Earliest year at which every code (that has any data) has a value.

    Clamped to [min_year, max_year - 1] (and to `floor` when given) so the default range
    always spans at least two years and every default card shows a growth delta.
    """
    subset = data.wide.reindex(columns=list(dict.fromkeys(codes)))
    subset = subset.loc[:, subset.notna().any()]  # codes without any data are ignored
    complete = subset.notna().all(axis=1) if not subset.empty else pd.Series(dtype=bool)
    year = int(complete.idxmax()) if complete.any() else data.min_year
    if floor is not None:
        year = max(year, floor)
    upper = max(data.min_year, data.max_year - 1)
    return min(max(year, data.min_year), upper)


def missing_in_range(
    data: GdpData, codes: Iterable[str], from_year: int, to_year: int
) -> list[str]:
    """Codes (in the given order) that have no value anywhere inside the range."""
    return [c for c in codes if first_valid_year(data, c, from_year, to_year) is None]


# --------------------------------------------------------------------------------------
# Growth maths
# --------------------------------------------------------------------------------------


def growth_summary(data: GdpData, code: str, from_year: int, to_year: int) -> GrowthSummary | None:
    """Growth between the first and last valid years inside the range.

    Returns None when the series has no value in the range. With a single data point the
    summary has start == end, ratio 1, pct_change 0 and cagr None.
    """
    start_year = first_valid_year(data, code, from_year, to_year)
    end_year = last_valid_year(data, code, from_year, to_year)
    if start_year is None or end_year is None:
        return None
    start_value = float(data.wide.at[start_year, code])
    end_value = float(data.wide.at[end_year, code])
    ratio = end_value / start_value if start_value else float("nan")
    pct_change = (ratio - 1.0) * 100.0
    cagr: float | None = None
    years = end_year - start_year
    if years > 0 and ratio > 0:
        cagr = (ratio ** (1.0 / years) - 1.0) * 100.0
    return GrowthSummary(
        code=code,
        start_year=start_year,
        end_year=end_year,
        start_value=start_value,
        end_value=end_value,
        ratio=ratio,
        pct_change=pct_change,
        cagr=cagr,
    )


# --------------------------------------------------------------------------------------
# Views (all return NEW frames; NaN kept so charts can draw gaps)
# --------------------------------------------------------------------------------------


def series(data: GdpData, codes: Sequence[str], from_year: int, to_year: int) -> pd.DataFrame:
    """Wide subset year × code for the range; unknown codes become all-NaN columns."""
    # dict.fromkeys drops duplicates while keeping order (duplicate columns cannot be stacked)
    return data.wide.loc[from_year:to_year].reindex(columns=list(dict.fromkeys(codes)))


def indexed(wide_subset: pd.DataFrame) -> pd.DataFrame:
    """Each column divided by its first non-null value, times 100."""
    if wide_subset.empty:
        return wide_subset.astype("float64").copy()
    first = wide_subset.bfill().iloc[0]
    return wide_subset.div(first, axis=1) * 100.0


def yoy_growth(wide_subset: pd.DataFrame) -> pd.DataFrame:
    """Year-over-year percentage change; NaN for the first year and after gaps."""
    return wide_subset.pct_change(fill_method=None) * 100.0


def share_of_world(data: GdpData, wide_subset: pd.DataFrame) -> pd.DataFrame:
    """Each column as a percentage of world GDP (WLD) for the same year; NaN when WLD is missing."""
    if WORLD_CODE in data.wide.columns:
        world = data.wide[WORLD_CODE].reindex(wide_subset.index)
    else:
        world = pd.Series(float("nan"), index=wide_subset.index, dtype="float64")
    return wide_subset.div(world, axis=0) * 100.0


def to_long(wide_subset: pd.DataFrame, data: GdpData, dropna: bool = False) -> pd.DataFrame:
    """Long frame with columns year, code, name, value (for Altair and the CSV download)."""
    long = wide_subset.rename_axis(index="year", columns="code").stack(future_stack=True)
    long = long.rename("value").reset_index()
    long["year"] = long["year"].astype("int64")
    long["code"] = long["code"].astype(str)
    long["name"] = long["code"].map(data.countries["name"]).fillna(long["code"]).astype(str)
    if dropna:
        long = long.dropna(subset=["value"])
    long = long.sort_values(["code", "year"], kind="stable").reset_index(drop=True)
    return long[["year", "code", "name", "value"]]
