#!/usr/bin/env python3
"""Refresh ``data/gdp_data.csv`` and ``data/countries.csv`` from the World Bank API.

Standard library only. Usage::

    python scripts/refresh_data.py [--out-dir data] [--indicator NY.GDP.MKTP.CD]
                                   [--timeout 120] [--retries 3] [--dry-run] [--validate]

``urllib`` honours ``HTTPS_PROXY`` / ``HTTP_PROXY`` from the environment, so there is no
proxy code here. Both files are written atomically (temp file in the same directory, then
``os.replace``); on any failure the script exits 1 and leaves the existing files untouched.

Output layouts
--------------
``countries.csv``: ``Country Code,Country Name,Region,Income Group,Is Aggregate`` sorted by
code, ``Is Aggregate`` is ``true`` when the World Bank region is "Aggregates".

``gdp_data.csv``: the World Bank bulk-download wide layout, ``csv.QUOTE_ALL``, no trailing
comma: ``Country Name,Country Code,Indicator Name,Indicator Code,1960,...,<last year>`` where
``<last year>`` is the last year with at least one non-null value. Rows are sorted by
Country Name; missing values are empty strings; present values are ``repr``'d floats.

The API leaves ``countryiso3code`` empty for the income-group aggregates (HIC, LIC, LMC, UMC
and the all-null INX) while still sending their ISO2 code in ``country.id``; those rows get
their ISO3 code back from the country list. Rows that still have no code are dropped.
"""

import argparse
import csv
import datetime
import http.client
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.worldbank.org/v2"
DEFAULT_INDICATOR = "NY.GDP.MKTP.CD"
FIRST_YEAR = 1960
USER_AGENT = "gdp-dashboard/refresh_data.py (Python urllib)"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "data"
COUNTRIES_FILE = "countries.csv"
GDP_FILE = "gdp_data.csv"
COUNTRIES_HEADER = ["Country Code", "Country Name", "Region", "Income Group", "Is Aggregate"]
GDP_FIXED_HEADER = ["Country Name", "Country Code", "Indicator Name", "Indicator Code"]

Row = dict[str, object]


class RefreshError(Exception):
    """A fatal problem (exhausted retries, malformed API payload, no data)."""


def log(message: str) -> None:
    """Progress and errors go to stderr; the final summary goes to stdout."""
    print(message, file=sys.stderr, flush=True)


# --- HTTP -----------------------------------------------------------------------------------


def fetch_json(url: str, timeout: float, retries: int) -> object:
    """GET ``url`` and decode the JSON body, retrying transient failures with backoff."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    attempt = 0
    while True:
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            transient = exc.code in (408, 429) or exc.code >= 500
            if not transient or attempt >= retries:
                raise RefreshError(f"HTTP {exc.code} {exc.reason} for {url}") from exc
            reason = f"HTTP {exc.code}"
        except (OSError, ValueError, http.client.HTTPException) as exc:
            # URLError, connection resets and timeouts are OSError; a non-JSON body is a
            # ValueError (json.JSONDecodeError); a body cut off mid-transfer is an
            # http.client.IncompleteRead (an HTTPException, NOT an OSError).
            if attempt >= retries:
                raise RefreshError(f"{type(exc).__name__}: {exc} for {url}") from exc
            reason = f"{type(exc).__name__}: {exc}"
        attempt += 1
        delay = 2**attempt
        log(f"  attempt {attempt}/{retries} failed ({reason}); retrying in {delay}s")
        time.sleep(delay)


def unpack(payload: object, what: str) -> tuple[dict[str, object], list[Row]]:
    """Validate the ``[meta, rows]`` envelope of a World Bank list endpoint."""
    if isinstance(payload, list) and len(payload) == 2 and isinstance(payload[0], dict):
        rows = payload[1] if payload[1] is not None else []
        if isinstance(rows, list):
            return payload[0], rows
    # Error responses look like [{"message": [{"id": "120", "key": "...", "value": "..."}]}].
    detail = ""
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        messages = payload[0].get("message") or []
        detail = "; ".join(str(m.get("value", m)) for m in messages if isinstance(m, dict))
    raise RefreshError(f"unexpected API response for {what}: {detail or repr(payload)[:200]}")


def fetch_pages(path: str, params: dict[str, str], timeout: float, retries: int) -> list[Row]:
    """Fetch every page of a World Bank list endpoint and concatenate the rows."""
    rows: list[Row] = []
    page = 1
    while True:
        query = {**params, "format": "json", "page": str(page)}
        url = f"{API_BASE}/{path}?" + "&".join(f"{k}={v}" for k, v in query.items())
        meta, page_rows = unpack(fetch_json(url, timeout, retries), path)
        rows.extend(page_rows)
        pages = int(meta.get("pages") or 1)
        if page >= pages:
            return rows
        log(f"  page {page}/{pages} fetched ({len(rows)} rows so far)")
        page += 1


# --- Table building -------------------------------------------------------------------------


def _nested_value(row: Row, key: str) -> str:
    """Return ``row[key]["value"]`` as a stripped string ("" when absent)."""
    nested = row.get(key)
    value = nested.get("value") if isinstance(nested, dict) else None
    return str(value).strip() if value is not None else ""


def build_countries(rows: list[Row]) -> list[list[str]]:
    """Rows for countries.csv, sorted by code; API rows with an empty ``id`` are dropped."""
    by_code: dict[str, list[str]] = {}
    for row in rows:
        code = str(row.get("id") or "").strip()
        if not code:
            continue
        region = _nested_value(row, "region")
        by_code[code] = [
            code,
            str(row.get("name") or "").strip(),
            region,
            _nested_value(row, "incomeLevel"),
            "true" if region == "Aggregates" else "false",
        ]
    return [by_code[code] for code in sorted(by_code)]


def iso3_by_iso2(rows: list[Row]) -> dict[str, str]:
    """``{iso2Code: id}`` from the country list, e.g. ``{"XD": "HIC", "BR": "BRA"}``."""
    mapping: dict[str, str] = {}
    for row in rows:
        iso2 = str(row.get("iso2Code") or "").strip()
        iso3 = str(row.get("id") or "").strip()
        if iso2 and iso3:
            mapping[iso2] = iso3
    return mapping


def build_wide(
    rows: list[Row], indicator: str, iso3_for_iso2: dict[str, str]
) -> tuple[list[str], list[list[str]], dict[str, int]]:
    """Build the wide layout: ``(header, data rows sorted by Country Name, counters)``."""
    values: dict[str, dict[int, float]] = {}
    names: dict[str, str] = {}
    indicator_name, indicator_code = "", indicator
    dropped = recovered = 0
    for row in rows:
        code = str(row.get("countryiso3code") or "").strip()
        if not code:
            # Income-group aggregates arrive without an ISO3 code but with country.id = ISO2.
            nested = row.get("country")
            iso2 = str(nested.get("id") or "").strip() if isinstance(nested, dict) else ""
            code = iso3_for_iso2.get(iso2, "")
            if not code:
                dropped += 1
                continue
            recovered += 1
        date = str(row.get("date") or "")
        if not date.isdigit():
            continue  # not an annual observation
        names.setdefault(code, _nested_value(row, "country") or code)
        if not indicator_name:
            indicator_name = _nested_value(row, "indicator")
            nested = row.get("indicator")
            indicator_code = (
                str(nested.get("id") or indicator) if isinstance(nested, dict) else indicator
            )
        value = row.get("value")
        if value is not None:
            values.setdefault(code, {})[int(date)] = float(value)  # type: ignore[arg-type]
    if not values:
        raise RefreshError(f"the API returned no non-null values for {indicator}")

    last_year = max(max(per_code) for per_code in values.values())
    years = list(range(FIRST_YEAR, last_year + 1))
    header = [*GDP_FIXED_HEADER, *(str(year) for year in years)]
    data_rows: list[list[str]] = []
    for code in sorted(names, key=lambda c: (names[c], c)):
        per_code = values.get(code, {})
        cells = [repr(per_code[year]) if year in per_code else "" for year in years]
        data_rows.append([names[code], code, indicator_name, indicator_code, *cells])
    counters = {
        "dropped_no_iso3": dropped,
        "recovered_iso3": recovered,
        "last_year": last_year,
        "observations": sum(len(per_code) for per_code in values.values()),
    }
    return header, data_rows, counters


# --- Atomic writing -------------------------------------------------------------------------


def _default_mode() -> int:
    """The permissions ``open(path, "w")`` would give a new file: ``0o666`` masked by the umask."""
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


def stage_csv(path: Path, header: list[str], rows: list[list[str]], quoting: int) -> Path:
    """Write the CSV to a temp file next to ``path`` and return the temp path (fsync'd)."""
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, quoting=quoting, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates 0600 files; give the result normal permissions.
        os.chmod(tmp_path, _default_mode())
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


def write_atomically(files: list[tuple[Path, list[str], list[list[str]], int]]) -> None:
    """Stage every file first, then ``os.replace`` them, so a failure leaves nothing behind."""
    staged: list[tuple[Path, Path]] = []
    try:
        for path, header, rows, quoting in files:
            staged.append((stage_csv(path, header, rows, quoting), path))
        for tmp_path, path in staged:
            os.replace(tmp_path, path)
    finally:
        for tmp_path, _ in staged:
            tmp_path.unlink(missing_ok=True)


# --- Validation -----------------------------------------------------------------------------


def validate(out_dir: Path) -> int:
    """Re-read both files through the dashboard's own loader and print what it sees."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    try:
        from gdp_dashboard.data import load_gdp
    except ImportError as exc:
        log(f"warning: validation skipped, gdp_dashboard.data is not importable ({exc})")
        return 0
    try:
        data = load_gdp(out_dir / GDP_FILE, out_dir / COUNTRIES_FILE)
        aggregates = int(data.countries["is_aggregate"].sum())
        print(
            f"validation: load_gdp ok, years {data.min_year}-{data.max_year}, "
            f"{len(data.tidy)} tidy rows, {data.wide.shape[1]} codes "
            f"({aggregates} aggregates), {len(data.countries)} metadata rows"
        )
    except Exception as exc:
        log(f"error: validation failed: {type(exc).__name__}: {exc}")
        return 1
    return 0


# --- CLI ------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh gdp_data.csv and countries.csv from the World Bank API."
    )
    parser.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR), help="output directory (default: %(default)s)"
    )
    parser.add_argument(
        "--indicator", default=DEFAULT_INDICATOR, help="indicator code (default: %(default)s)"
    )
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="per-request timeout in seconds"
    )
    parser.add_argument(
        "--retries", type=int, default=3, help="retries per request after the first attempt"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch and print the summary but write nothing"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="after writing, re-read both files with gdp_dashboard.data.load_gdp",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = Path(args.out_dir)
    this_year = datetime.date.today().year
    date_range = f"{FIRST_YEAR}:{this_year}"
    try:
        log("Fetching country metadata ...")
        country_rows = fetch_pages("country", {"per_page": "400"}, args.timeout, args.retries)
        countries = build_countries(country_rows)
        log(f"Fetching {args.indicator} for {date_range} ...")
        indicator_rows = fetch_pages(
            f"country/all/indicator/{args.indicator}",
            {"per_page": "20000", "date": date_range},
            args.timeout,
            args.retries,
        )
        header, gdp_rows, counters = build_wide(
            indicator_rows, args.indicator, iso3_by_iso2(country_rows)
        )
    except RefreshError as exc:
        log(f"error: {exc}")
        return 1

    aggregate_codes = {row[0] for row in countries if row[4] == "true"}
    gdp_aggregates = sum(1 for row in gdp_rows if row[1] in aggregate_codes)
    print(
        f"{COUNTRIES_FILE}: {len(countries)} rows, {len(aggregate_codes)} aggregates\n"
        f"{GDP_FILE}: {len(gdp_rows)} rows ({gdp_aggregates} aggregates), "
        f"years {FIRST_YEAR}-{counters['last_year']}, "
        f"{counters['observations']} non-null values; API rows without an ISO3 code: "
        f"{counters['recovered_iso3']} recovered via ISO2, {counters['dropped_no_iso3']} dropped"
    )
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        write_atomically(
            [
                (out_dir / COUNTRIES_FILE, COUNTRIES_HEADER, countries, csv.QUOTE_MINIMAL),
                (out_dir / GDP_FILE, header, gdp_rows, csv.QUOTE_ALL),
            ]
        )
    except OSError as exc:
        log(f"error: could not write files in {out_dir}: {exc}")
        return 1
    print(f"wrote {out_dir / COUNTRIES_FILE} and {out_dir / GDP_FILE}")
    return validate(out_dir) if args.validate else 0


if __name__ == "__main__":
    sys.exit(main())
