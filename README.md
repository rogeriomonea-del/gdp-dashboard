# :earth_americas: GDP dashboard template

A simple Streamlit app showing the GDP of different countries in the world.

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://gdp-dashboard-template.streamlit.app/)

### How to run it on your own machine

1. Install the requirements

   ```
   $ pip install -r requirements.txt
   ```

2. Run the app

   ```
   $ streamlit run streamlit_app.py
   ```

### Web data via Firecrawl

This repo uses [Firecrawl](https://docs.firecrawl.dev) as its web-data layer
(refreshing the GDP snapshot, in-app fetching, and monitoring the source for
new releases). Setup, credentials (`.env.example`), and usage routing live in
[FIRECRAWL.md](FIRECRAWL.md).
