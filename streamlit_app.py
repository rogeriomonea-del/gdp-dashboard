"""GDP dashboard: a thin Streamlit UI over the pure helpers in `gdp_dashboard`."""

from __future__ import annotations

import math
from functools import partial

import altair as alt
import pandas as pd
import streamlit as st

from gdp_dashboard import data as gd
from gdp_dashboard.formatting import axis_unit, format_number, format_pct, format_ratio, format_usd

VIEW_GDP = "GDP (current US$)"
VIEW_INDEXED = "Indexed (start year = 100)"
VIEW_YOY = "Year-over-year growth (%)"
VIEW_SHARE = "Share of world GDP (%)"
VIEWS = (VIEW_GDP, VIEW_INDEXED, VIEW_YOY, VIEW_SHARE)
MAX_READABLE_SERIES = 12
CARDS_PER_ROW = 4

st.set_page_config(page_title="GDP dashboard", page_icon=":earth_americas:")


@st.cache_data(show_spinner=False)
def get_data() -> gd.GdpData:
    return gd.load_gdp()


def seed_state_from_url(data: gd.GdpData) -> None:
    """Seed widget state from the URL once per session; anything malformed falls back."""
    if st.session_state.get("_seeded"):
        return
    st.session_state["_seeded"] = True
    params = st.query_params
    valid = set(gd.selectable_codes(data, include_aggregates=True))
    codes = [c.strip().upper() for c in params.get("countries", "").split(",") if c.strip()]
    codes = list(dict.fromkeys(c for c in codes if c in valid))  # unknown dropped, no duplicates
    st.session_state["countries"] = codes or [c for c in gd.DEFAULT_COUNTRIES if c in valid]
    st.session_state["aggregates"] = any(gd.is_aggregate(data, c) for c in codes)
    default_from = gd.default_from_year(data, gd.DEFAULT_COUNTRIES)
    try:
        from_year = int(params.get("from", default_from))
        to_year = int(params.get("to", data.max_year))
    except ValueError:
        from_year, to_year = default_from, data.max_year
    from_year = min(max(from_year, data.min_year), data.max_year)
    to_year = min(max(to_year, data.min_year), data.max_year)
    st.session_state["years"] = (min(from_year, to_year), max(from_year, to_year))
    view = params.get("view", VIEW_GDP)
    st.session_state["view"] = view if view in VIEWS else VIEW_GDP


def chart_frame(data: gd.GdpData, view: str, wide: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
    """Long frame (year, code, name, value, display) for a view, plus axis title and format."""
    if view == VIEW_GDP:
        scale, unit = axis_unit(float(wide.abs().max().max()))
        long = gd.to_long(wide, data)
        long["display"] = [format_usd(v) for v in long["value"]]  # tooltips: unscaled dollars
        long["value"] = long["value"] / scale
        return long, f"GDP ({unit})", ",.1f"
    if view == VIEW_INDEXED:  # an index level, not a percentage: no sign, no "%"
        frame, fmt, show = gd.indexed(wide), ",.0f", format_number
    elif view == VIEW_YOY:
        frame, fmt, show = gd.yoy_growth(wide), "+.1f", format_pct
    else:  # a share is not a signed quantity
        frame, fmt = gd.share_of_world(data, wide), ".2f"
        show = partial(format_pct, digits=2, sign=False)
    long = gd.to_long(frame, data)
    long["display"] = [show(v) for v in long["value"]]
    return long, view, fmt


def build_chart(
    long: pd.DataFrame, names: list[str], y_title: str, y_format: str, log_scale: bool
) -> alt.Chart:
    """Line chart over years, or a bar chart when the range is a single year."""
    scheme = "tableau10" if len(names) <= 10 else "category20"
    color = alt.Color("name:N", title="Country", scale=alt.Scale(domain=names, scheme=scheme))
    tooltip = [
        alt.Tooltip("name:N", title="Country"),
        alt.Tooltip("year:Q", title="Year", format="d"),
        alt.Tooltip("display:N", title=y_title),
    ]
    if long["year"].nunique() == 1:
        x = alt.X("value:Q", axis=alt.Axis(title=y_title, format=y_format))
        y = alt.Y("name:N", sort="-x", title=None)
        chart = alt.Chart(long.dropna(subset=["value"])).mark_bar()
        return chart.encode(x=x, y=y, color=color, tooltip=tooltip)
    y_scale = alt.Scale(type="log") if log_scale else alt.Scale()
    x = alt.X("year:Q", axis=alt.Axis(format="d", title="Year"), scale=alt.Scale(nice=False))
    y = alt.Y("value:Q", axis=alt.Axis(title=y_title, format=y_format), scale=y_scale)
    return alt.Chart(long).mark_line(point=True).encode(x=x, y=y, color=color, tooltip=tooltip)


def metric_card(data: gd.GdpData, code: str, from_year: int, to_year: int, years: str) -> None:
    summary = gd.growth_summary(data, code, from_year, to_year)
    name = gd.name_of(data, code)
    if summary is None:
        st.metric(f"{name} · {years}", "no data")
        return
    delta = help_text = None
    if summary.start_year != summary.end_year:
        help_text = (
            f"{summary.start_year}→{summary.end_year}: {format_ratio(summary.ratio)} "
            f"(CAGR {format_pct(summary.cagr)}/yr), nominal US$"
        )
        if math.isfinite(summary.pct_change):  # a zero start value has no growth figure
            delta = format_pct(summary.pct_change)
    value = format_usd(summary.end_value)
    st.metric(f"{name} · {summary.end_year}", value, delta, delta_color="normal", help=help_text)


def main() -> None:
    try:
        data = get_data()
    except Exception as exc:  # any load failure is fatal for the page
        st.error(f"Could not load the GDP data from `{gd.DATA_DIR / 'gdp_data.csv'}`: {exc}")
        st.stop()
    seed_state_from_url(data)

    st.title(":earth_americas: GDP dashboard")
    st.markdown(
        "Browse GDP in current US$ (indicator `NY.GDP.MKTP.CD`) from "
        "[World Bank Open Data](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD), "
        f"{data.min_year}–{data.max_year}. Some years are missing for some economies; "
        "growth is computed between the first and last years with data in the chosen range."
    )
    st.caption(
        "Values are nominal current US$ (driven by inflation and exchange rates), "
        "so multiples are not real growth."
    )

    include_aggregates = st.toggle(
        "Include World Bank aggregates (World, EU, income groups…)", key="aggregates"
    )
    options = gd.selectable_codes(data, include_aggregates)
    with st.expander("Filter the country list"):
        meta = data.countries.loc[options]
        regions = st.multiselect("Region", sorted(meta["region"].unique()))
        incomes = st.multiselect("Income group", sorted(meta["income_group"].unique()))
    picked = st.session_state["countries"]  # the filter never hides the current selection
    kept = set(gd.filter_codes(data, options, regions, incomes)) | set(picked)
    options = [c for c in options if c in kept]
    st.session_state["countries"] = [c for c in picked if c in options]
    selected: list[str] = st.multiselect(
        "Countries", options, key="countries", format_func=lambda c: gd.label(data, c)
    )
    if data.min_year == data.max_year:  # a one-year file: st.slider needs min < max
        from_year = to_year = data.min_year
        st.caption(f"The data file only covers {data.min_year}.")
    else:
        from_year, to_year = st.slider("Years", data.min_year, data.max_year, key="years")
    view = st.radio("View", VIEWS, horizontal=True, key="view")
    log_scale = st.checkbox("Log scale") if view == VIEW_GDP else False
    st.query_params.from_dict(
        {"countries": ",".join(selected), "from": from_year, "to": to_year, "view": view}
    )

    if not selected:
        st.info("Select at least one country to see the chart.")
        st.stop()
    if len(selected) > MAX_READABLE_SERIES:
        st.warning(f"{len(selected)} series selected: the chart may be hard to read.")
    years = f"{to_year}" if from_year == to_year else f"{from_year}–{to_year}"
    if from_year == to_year and view in (VIEW_INDEXED, VIEW_YOY):  # both need >= 2 years
        st.info(f"{view} needs at least two years; showing {VIEW_GDP} for {to_year} instead.")
        view = VIEW_GDP

    wide = gd.series(data, selected, from_year, to_year)
    chart_df, y_title, y_format = chart_frame(data, view, wide)
    if log_scale:  # a log axis cannot show zero or negative values: turn them into gaps
        chart_df["value"] = chart_df["value"].where(chart_df["value"] > 0)
    st.header(f"{y_title}, {years}", divider="gray")
    names = [gd.name_of(data, c) for c in selected]
    st.altair_chart(build_chart(chart_df, names, y_title, y_format, log_scale), width="stretch")

    st.header(f"Latest GDP ({years})", divider="gray")  # each card carries its own data year
    for i, code in enumerate(selected):
        if i % CARDS_PER_ROW == 0:
            cols = st.columns(CARDS_PER_ROW)
        with cols[i % CARDS_PER_ROW]:
            metric_card(data, code, from_year, to_year, years)
    if missing := gd.missing_in_range(data, selected, from_year, to_year):
        names = ", ".join(gd.label(data, c) for c in missing)
        st.caption(f"No data in the selected range for: {names}")

    with st.expander("Data table & download"):
        table = gd.to_long(wide, data, dropna=True)
        st.dataframe(table, hide_index=True)
        csv_bytes = table.to_csv(index=False).encode("utf-8")
        st.download_button("Download CSV", csv_bytes, f"gdp_{from_year}_{to_year}.csv", "text/csv")


main()
