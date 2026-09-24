# :earth_americas: GDP dashboard

A small [Streamlit](https://streamlit.io) app for exploring GDP (current US$) of the world's
economies, using [World Bank Open Data](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD).

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://gdp-dashboard-template.streamlit.app/)

## Features

- **Country picker searchable by name** – options show `Brazil (BRA)`; World Bank
  aggregates (World, EU, income groups, …) are hidden behind a toggle, and series with no data
  are never offered. An optional expander narrows the list by region and income group.
- **Four views** – GDP in current US$ (with an optional **log scale**), indexed
  (start year = 100), year-over-year growth (%), and share of world GDP (%).
- **Readable chart** – Altair line chart (bar chart when a single year is selected), legend
  and tooltips use country names, colours stay stable as you add countries, missing years are
  drawn as gaps.
- **Metric cards** – latest value in the range with a signed percentage change (red for a
  decline), and a tooltip with the exact years compared, the multiple and the CAGR. Cards say
  "no data" instead of `nan` when a series is empty in the chosen range.
- **Data table & CSV download** of the current selection.
- **Shareable URLs** – `?countries=DEU,FRA&from=1990&to=2020&view=…` seeds the widgets;
  the URL is kept in sync with them.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Requires Python 3.11+. Runtime dependencies are only `streamlit` and `pandas`
(Altair ships with Streamlit).

## Development

```bash
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest -q
```

CI (`.github/workflows/ci.yml`) runs the same three commands on Python 3.11 and 3.12.

Layout:

| Path | Purpose |
| --- | --- |
| `streamlit_app.py` | Thin UI (widgets, chart, metric cards); no data maths |
| `gdp_dashboard/data.py` | Loading, tidying, metadata and growth maths (pure pandas) |
| `gdp_dashboard/formatting.py` | `$1.23T`-style formatters and axis units |
| `scripts/refresh_data.py` | Downloads fresh data from the World Bank API |
| `data/gdp_data.csv` | GDP in the World Bank bulk-download wide layout |
| `data/countries.csv` | Country metadata: name, region, income group, aggregate flag |

## Refresh the data

```bash
python scripts/refresh_data.py            # rewrites data/gdp_data.csv and data/countries.csv
python scripts/refresh_data.py --dry-run  # only print what would be written
python scripts/refresh_data.py --validate # re-read the written files with the app loader
```

The script uses only the standard library, honours `HTTPS_PROXY`, retries transient errors and
writes both files atomically, so a failed run leaves the existing files untouched. Options:
`--out-dir`, `--indicator`, `--timeout`, `--retries`. The app derives the year range from the
CSV header, so a refreshed file needs no code change. A hand-downloaded World Bank CSV export
works too; if `countries.csv` is missing, names come from the GDP file and aggregates are
recognised from a built-in list.

## Data source and licence

- Indicator: **NY.GDP.MKTP.CD – GDP (current US$)**, World Bank Open Data, currently
  1960–2025.
- Licence: [CC BY-4.0](https://datacatalog.worldbank.org/public-licenses#cc-by).

**Caveat:** values are nominal current US$, so they move with inflation and exchange rates.
Multiples and growth rates shown here are not real (inflation-adjusted) growth.
