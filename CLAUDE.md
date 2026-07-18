# GDP dashboard — agent notes

Streamlit app (`streamlit_app.py`) showing World Bank GDP data from a static
snapshot at `data/gdp_data.csv`. Run locally with
`pip install -r requirements.txt && streamlit run streamlit_app.py`.

## Web data: use Firecrawl

Firecrawl is the web-data layer for this repo. Routing:

- **Refreshing `data/gdp_data.csv`** or any ad-hoc web lookup →
  Firecrawl CLI / `firecrawl` skills (`firecrawl-search`, `firecrawl-scrape`).
- **Fetching data inside the app** (replacing the static CSV with a live
  source) → `firecrawl-build` skills; endpoint mapping lives in
  [FIRECRAWL.md](FIRECRAWL.md).
- **Watching the source for new releases** ("alert when new GDP data lands")
  → `/monitor` via `firecrawl monitor create`, not repeated one-off scrapes.
- **Finished deliverables** (GDP/market research brief) →
  `firecrawl-workflows` skills.

Setup, credentials, verification, and the remote-session proxy fix are in
[FIRECRAWL.md](FIRECRAWL.md). If skills/CLI are missing in a fresh session:
`npx -y firecrawl-cli@latest init --all -y -k "$FIRECRAWL_API_KEY"`.

`FIRECRAWL_API_KEY` comes from `.env` (copy `.env.example`); never commit a
real key.
