# Firecrawl setup & routing — GDP dashboard

Firecrawl is set up as the web-data layer for this project: search, clean
scraping, document parsing, and page-change monitoring.

## Install (one command, three skill segments)

```bash
npx -y firecrawl-cli@latest init --all --browser
```

Running headless / in an agent session with a key already available:

```bash
npx -y firecrawl-cli@latest init --all -y -k "$FIRECRAWL_API_KEY"
```

This installs the `firecrawl` CLI globally, authenticates, and installs three
skill segments for AI coding agents:

| Segment         | Question it answers                                   | Use in this repo                              |
| --------------- | ----------------------------------------------------- | --------------------------------------------- |
| CLI skills      | "Which Firecrawl command should I run right now?"     | Refreshing `data/gdp_data.csv` from the web   |
| Build skills    | "How do I add a Firecrawl API call to this codebase?" | In-app data fetch (see routing below)         |
| Workflow skills | "What finished deliverable should I produce?"         | Market/GDP research briefs alongside the app  |

## Credentials

```bash
# .env (gitignored — never commit a real key)
FIRECRAWL_API_KEY=fc-your-key-here
```

Copy `.env.example` to `.env` and fill in your key. Get a key at
<https://www.firecrawl.dev/signin?view=signup> (dashboard → API keys), or let
the CLI's browser auth store one for you.

## Verify

```bash
mkdir -p .firecrawl
firecrawl --status                                          # expect: Authenticated
firecrawl scrape "https://firecrawl.dev" -o .firecrawl/install-check.md
```

`.firecrawl/` is a local cache and is gitignored.

## Routing for this repo

The app reads a static snapshot (`data/gdp_data.csv`, World Bank GDP,
1960–2022). Firecrawl fits three jobs here:

| Job                                                        | Path                | How                                                                          |
| ---------------------------------------------------------- | ------------------- | ---------------------------------------------------------------------------- |
| Refresh the CSV snapshot during a session                  | Live CLI (Path A)   | `firecrawl search` / `firecrawl scrape` the source, save into `data/`        |
| Fetch data inside the app instead of a static CSV          | Build (Path B)      | `pip install firecrawl-py`; call `/scrape` in `get_gdp_data()` behind `@st.cache_data(ttl='1d')` |
| Know when the source publishes new data                    | Monitor             | `firecrawl monitor create` on the source page with a `--goal` like "new GDP release" and email/webhook notify |
| Produce a written GDP/market analysis to ship with the app | Workflows (Path C)  | Start from the `firecrawl-workflows` skill (e.g. market research brief)      |

Python SDK sketch for the in-app path:

```python
import os
from firecrawl import Firecrawl

fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
doc = fc.scrape("https://data.worldbank.org/...", formats=["markdown"])
```

For one-off pulls use the CLI; for product code hand off to the
`firecrawl-build` skills; for recurring checks prefer `/monitor` over
repeated scrapes.

## Claude Code on the web — proxy note

Remote sessions route HTTPS through an agent proxy. If `firecrawl` commands
fail with `405 Method Not Allowed`, the bundled axios (< 1.16.1) is sending
non-CONNECT proxy requests. Fix without touching TLS settings:

```bash
cd "$(npm root -g)/firecrawl-cli" && npm install axios@latest --no-save
cd "$(npm root -g)/firecrawl-cli/node_modules/firecrawl" && npm install axios@latest --no-save
```

## Rerun inputs

- Install: `npx -y firecrawl-cli@latest init --all -y -k "$FIRECRAWL_API_KEY"`
- Verify: `firecrawl --status` + scrape check above
- Key: `FIRECRAWL_API_KEY` in `.env` (local) or session env
- Docs: <https://docs.firecrawl.dev> · Skills: <https://github.com/firecrawl/skills>
