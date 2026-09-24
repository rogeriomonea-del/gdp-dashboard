"""End-to-end checks of streamlit_app.py through streamlit.testing.v1.AppTest (real data)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from gdp_dashboard import data as gd
from gdp_dashboard.data import (
    DEFAULT_COUNTRIES,
    GdpData,
    growth_summary,
    label,
    load_gdp,
    selectable_codes,
)
from tests.conftest import write_wide_csv

APP_PATH = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")
VIEWS = (
    "GDP (current US$)",
    "Indexed (start year = 100)",
    "Year-over-year growth (%)",
    "Share of world GDP (%)",
)


def fresh_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def countries_widget(at: AppTest):  # noqa: ANN201 - AppTest widget types are private
    """The Countries picker (the last multiselect; Region / Income group live in an expander)."""
    widget = at.multiselect[-1]
    assert widget.label == "Countries"
    return widget


def charts(at: AppTest) -> list:
    return list(at.get("vega_lite_chart")) + list(at.get("arrow_vega_lite_chart"))


def metric_texts(at: AppTest) -> list[str]:
    return [f"{m.label} {m.value} {m.delta}" for m in at.metric]


def chart_rows(at: AppTest) -> pd.DataFrame:
    """The rows the (single) chart was rendered with: Arrow IPC inside the Vega-Lite proto."""
    (chart,) = charts(at)
    return pa.ipc.open_stream(chart.proto.datasets[0].data.data).read_pandas()


@pytest.fixture
def synthetic_app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Callable[[dict, tuple[int, ...]], AppTest]:
    """Run the app against a synthetic GDP CSV (no countries.csv) instead of data/."""

    def run(rows: dict, years: tuple[int, ...]) -> AppTest:
        gdp = write_wide_csv(tmp_path / "gdp_data.csv", rows, years)
        monkeypatch.setattr(gd.load_gdp, "__defaults__", (gdp, None))
        st.cache_data.clear()  # get_data() is cached process-wide
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        return at

    yield run
    st.cache_data.clear()


@pytest.fixture(scope="module")
def real() -> GdpData:
    return load_gdp()


@pytest.fixture
def app() -> AppTest:
    return fresh_app()


def test_default_run_has_no_exception_and_no_nan(app: AppTest, real: GdpData) -> None:
    assert not app.exception
    assert not app.error
    assert app.title[0].value.endswith("GDP dashboard")
    present_defaults = [c for c in DEFAULT_COUNTRIES if c in real.wide.columns]
    assert countries_widget(app).value == present_defaults
    assert len(app.metric) == len(present_defaults)
    for text in metric_texts(app):
        assert "nan" not in text.lower()
        assert "n/a" not in text.lower()
    assert len(charts(app)) == 1
    assert app.slider[0].value[1] == real.max_year
    assert app.slider[0].value[0] < real.max_year


def test_every_default_metric_has_a_delta(app: AppTest, real: GdpData) -> None:
    labels = [m.label for m in app.metric]
    for code, metric in zip(DEFAULT_COUNTRIES, app.metric, strict=True):
        assert metric.label.startswith(f"{label(real, code).split(' (')[0]} · ")
        assert metric.label.endswith(str(real.max_year))
        assert metric.value.startswith("$")
        assert metric.delta, f"no delta for {metric.label}"
        assert metric.delta[0] in "+-"
        assert metric.delta.endswith("%")
    assert len(set(labels)) == len(labels)


def test_afg_and_deu_show_no_nan(app: AppTest, real: GdpData) -> None:
    countries_widget(app).set_value(["AFG", "DEU"]).run()
    assert not app.exception
    assert countries_widget(app).value == ["AFG", "DEU"]
    assert len(app.metric) == 2
    for text in metric_texts(app):
        assert "nan" not in text.lower()
        assert "no data" not in text.lower()
    afg, deu = app.metric
    # the year on the card is the last year WITH data in the range, not the slider end
    assert afg.label == f"Afghanistan · {int(real.wide['AFG'].last_valid_index())}"
    assert deu.label == f"Germany · {int(real.wide['DEU'].last_valid_index())}"
    assert afg.delta and deu.delta


def test_empty_selection_shows_info_and_no_chart(app: AppTest) -> None:
    countries_widget(app).set_value([]).run()
    assert not app.exception
    assert [i.value for i in app.info] == ["Select at least one country to see the chart."]
    assert charts(app) == []
    assert len(app.metric) == 0
    assert len(app.download_button) == 0
    assert countries_widget(app).value == []  # the widget is still there to pick again


def test_declining_series_shows_negative_delta(app: AppTest, real: GdpData) -> None:
    # find a default country and a start year with a decline up to max_year (derived, not fixed)
    decline = None
    for code in DEFAULT_COUNTRIES:
        column = real.wide[code].dropna()
        for year in reversed(column.index[:-1]):
            summary = growth_summary(real, code, int(year), real.max_year)
            if summary is not None and summary.pct_change < 0:
                decline = (code, int(year))
                break
        if decline:
            break
    assert decline is not None, "no declining default series in the data"
    code, start = decline
    countries_widget(app).set_value([code]).run()
    app.slider[0].set_value((start, real.max_year)).run()
    assert not app.exception
    assert len(app.metric) == 1
    assert app.metric[0].delta.startswith("-")
    assert app.metric[0].delta.endswith("%")


def test_toggle_aggregates_makes_wld_selectable(app: AppTest, real: GdpData) -> None:
    picker = countries_widget(app)
    assert label(real, "WLD") not in picker.options
    assert app.toggle[0].value is False
    app.toggle[0].set_value(True).run()
    assert not app.exception
    picker = countries_widget(app)
    assert label(real, "WLD") in picker.options
    assert picker.options == [
        label(real, c) for c in selectable_codes(real, include_aggregates=True)
    ]
    assert picker.value == list(DEFAULT_COUNTRIES)  # selection survives the toggle

    picker.set_value(["WLD"]).run()
    assert not app.exception
    assert len(app.metric) == 1
    assert app.metric[0].label.startswith("World · ")
    assert "nan" not in app.metric[0].value.lower()

    # turning aggregates off again prunes WLD instead of raising
    app.toggle[0].set_value(False).run()
    assert not app.exception
    assert countries_widget(app).value == []
    assert len(app.info) == 1


def test_download_button_exists(app: AppTest, real: GdpData) -> None:
    assert len(app.download_button) == 1
    button = app.download_button[0]
    assert button.label == "Download CSV"
    assert len(app.dataframe) == 1
    assert [e.label for e in app.expander] == ["Filter the country list", "Data table & download"]
    assert app.slider[0].value[1] == real.max_year


@pytest.mark.parametrize("view", VIEWS)
def test_each_view_runs(view: str, real: GdpData) -> None:
    at = fresh_app()
    assert list(at.radio[0].options) == list(VIEWS)
    at.radio[0].set_value(view).run()
    assert not at.exception
    assert at.radio[0].value == view
    assert len(charts(at)) == 1
    assert len(at.metric) == len(DEFAULT_COUNTRIES)
    for text in metric_texts(at):
        assert "nan" not in text.lower()
    from_year, to_year = at.slider[0].value
    assert at.header[0].value.endswith(f", {from_year}\u2013{to_year}")
    # the log-scale checkbox only exists for the GDP view
    assert [c.label for c in at.checkbox] == (["Log scale"] if view == VIEWS[0] else [])


def test_log_scale_runs(app: AppTest) -> None:
    assert [c.label for c in app.checkbox] == ["Log scale"]
    app.checkbox[0].set_value(True).run()
    assert not app.exception
    assert len(charts(app)) == 1


def test_single_year_range_runs_without_deltas(app: AppTest, real: GdpData) -> None:
    year = real.max_year - 1
    app.slider[0].set_value((year, year)).run()
    assert not app.exception
    assert app.slider[0].value == (year, year)
    assert len(charts(app)) == 1
    assert len(app.metric) == len(DEFAULT_COUNTRIES)
    for metric in app.metric:
        assert metric.label.endswith(str(year))
        assert metric.value.startswith("$")
        assert not metric.delta
    assert app.header[1].value == f"Latest GDP ({year})"
    assert app.header[0].value == f"GDP (trillion US$), {year}"
    assert not app.info


@pytest.mark.parametrize("view", [VIEWS[1], VIEWS[2]])
def test_single_year_with_indexed_or_yoy_view_falls_back_to_gdp_bars(
    view: str, app: AppTest, real: GdpData
) -> None:
    """Indexed is all-100 and YoY all-NaN for one year: chart that year's GDP and say so."""
    year = real.max_year - 1
    app.slider[0].set_value((year, year))
    app.radio[0].set_value(view).run()
    assert not app.exception
    assert app.radio[0].value == view  # the user's choice is kept in the widget / URL
    assert at_query(app)["view"] == view
    assert [i.value for i in app.info] == [
        f"{view} needs at least two years; showing {VIEWS[0]} for {year} instead."
    ]
    assert app.header[0].value == f"GDP (trillion US$), {year}"
    rows = chart_rows(app)
    assert len(rows) == len(DEFAULT_COUNTRIES)
    assert rows["value"].notna().all() and rows["value"].nunique() > 1
    assert rows["display"].str.startswith("$").all()
    assert all(not m.delta for m in app.metric)


def at_query(at: AppTest) -> dict[str, str]:
    return {key: value[0] for key, value in dict(at.query_params).items()}


def test_single_year_share_view_keeps_shares(app: AppTest, real: GdpData) -> None:
    year = real.max_year - 1
    app.slider[0].set_value((year, year))
    app.radio[0].set_value(VIEWS[3]).run()
    assert not app.exception
    assert not app.info
    assert app.header[0].value == f"{VIEWS[3]}, {year}"
    rows = chart_rows(app)
    assert rows["value"].between(0, 100).all()
    assert rows["display"].str.fullmatch(r"\d+\.\d{2}%").all()


def test_tooltips_are_formatted_per_view(real: GdpData) -> None:
    """Indexed tooltips are index levels, shares are unsigned, only YoY carries a sign."""
    at = fresh_app()
    gdp = chart_rows(at)
    assert gdp["display"].str.fullmatch(r"\$\d+\.\d{2}[TBM]").all()
    scale = 1e12  # the axis is in trillions for the default selection
    assert gdp["display"].iloc[0] == f"${gdp['value'].iloc[0] * scale / 1e9:.2f}B"

    at.radio[0].set_value(VIEWS[1]).run()
    rows = chart_rows(at)
    shown = rows.loc[rows["value"].notna(), "display"]
    assert not shown.str.contains("%").any() and not shown.str.startswith("+").any()
    assert shown.str.fullmatch(r"-?[\d,]+\.\d").all()
    base = rows.groupby("code").first()  # the start year is the base of every index
    assert (base["value"] == 100.0).all() and (base["display"] == "100.0").all()

    at.radio[0].set_value(VIEWS[3]).run()
    rows = chart_rows(at)
    shown = rows.loc[rows["value"].notna(), "display"]
    assert shown.str.fullmatch(r"\d+\.\d{2}%").all()  # e.g. "5.79%", never "+5.8%"

    at.radio[0].set_value(VIEWS[2]).run()
    rows = chart_rows(at)
    shown = rows.loc[rows["value"].notna(), "display"]
    assert shown.str.fullmatch(r"[+-]\d+\.\d%").all()
    assert rows.loc[rows["value"].isna(), "display"].eq("n/a").all()


def test_no_data_card_label_matches_the_header_range(app: AppTest, real: GdpData) -> None:
    afg = real.wide["AFG"]
    year = int(afg.index[afg.isna()][0])  # a year without an AFG value
    countries_widget(app).set_value(["AFG"]).run()
    app.slider[0].set_value((year, year)).run()
    assert not app.exception
    assert [(m.label, m.value, m.delta) for m in app.metric] == [
        (f"Afghanistan · {year}", "no data", "")
    ]
    assert app.header[1].value == f"Latest GDP ({year})"
    assert any(
        c.value == "No data in the selected range for: Afghanistan (AFG)" for c in app.caption
    )


def test_region_and_income_filters_narrow_options_but_keep_selection(
    app: AppTest, real: GdpData
) -> None:
    region_widget, income_widget = app.multiselect[0], app.multiselect[1]
    assert (region_widget.label, income_widget.label) == ("Region", "Income group")
    full = countries_widget(app).options
    region = real.countries.at["IND", "region"]
    assert region in region_widget.options
    region_widget.set_value([region]).run()
    assert not app.exception
    narrowed = countries_widget(app).options
    in_region = {c for c in selectable_codes(real) if real.countries.at[c, "region"] == region}
    assert set(narrowed) == {label(real, c) for c in in_region | set(DEFAULT_COUNTRIES)}
    assert 1 < len(narrowed) < len(full)
    assert countries_widget(app).value == list(DEFAULT_COUNTRIES)  # selection survives
    assert len(app.metric) == len(DEFAULT_COUNTRIES)

    # an income filter that hides the only selected country keeps it selected and charted
    countries_widget(app).set_value(["IND"]).run()
    other_income = next(
        g for g in app.multiselect[1].options if g != real.countries.at["IND", "income_group"]
    )
    app.multiselect[0].set_value([])
    app.multiselect[1].set_value([other_income]).run()
    assert not app.exception
    assert countries_widget(app).value == ["IND"]
    assert label(real, "IND") in countries_widget(app).options
    assert len(app.metric) == 1 and app.metric[0].label.startswith("India · ")

    app.multiselect[1].set_value([]).run()  # clearing the filter restores the full list
    assert countries_widget(app).options == full
    assert countries_widget(app).value == ["IND"]


def test_zero_start_value_shows_no_delta(synthetic_app: Callable) -> None:
    """A NaN growth figure must not be rendered as an "n/a" delta with a green up arrow."""
    rows = {"DEU": ("Germany", (0.0, 5.0, 6.0)), "FRA": ("France", (1.0, 2.0, 3.0))}
    at = synthetic_app(rows, (2000, 2001, 2002))
    assert not at.exception
    assert [(m.label, m.value, m.delta) for m in at.metric] == [
        ("Germany · 2002", "$6", ""),
        ("France · 2002", "$3", "+200.0%"),
    ]
    assert "n/a" not in " ".join(metric_texts(at))


def test_single_year_data_file_runs_without_a_slider(synthetic_app: Callable) -> None:
    """st.slider refuses min == max; a one-year file must still render."""
    rows = {"DEU": ("Germany", (5.0,)), "FRA": ("France", (3.0,))}
    at = synthetic_app(rows, (2001,))
    assert not at.exception
    assert not at.error
    assert len(at.slider) == 0
    assert any("2001" in c.value for c in at.caption)
    assert len(charts(at)) == 1
    assert [(m.label, m.value, m.delta) for m in at.metric] == [
        ("Germany · 2001", "$5", ""),
        ("France · 2001", "$3", ""),
    ]
    assert at.header[1].value == "Latest GDP (2001)"
    assert at_query(at)["from"] == at_query(at)["to"] == "2001"


def test_more_than_twelve_series_warns_but_renders(app: AppTest, real: GdpData) -> None:
    many = selectable_codes(real)[:13]
    countries_widget(app).set_value(many).run()
    assert not app.exception
    assert len(app.warning) == 1
    assert "13" in app.warning[0].value
    assert len(app.metric) == 13
    assert len(charts(app)) == 1


def test_url_state_seeds_widgets_and_is_written_back(real: GdpData) -> None:
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.query_params["countries"] = "jpn,BRA,XXX"
    at.query_params["from"] = str(real.max_year - 5)
    at.query_params["to"] = "9999"
    at.query_params["view"] = VIEWS[2]
    at.run()
    assert not at.exception
    assert countries_widget(at).value == ["JPN", "BRA"]  # unknown code dropped, case fixed
    assert at.slider[0].value == (real.max_year - 5, real.max_year)  # clamped
    assert at.radio[0].value == VIEWS[2]
    assert dict(at.query_params) == {
        "countries": ["JPN,BRA"],
        "from": [str(real.max_year - 5)],
        "to": [str(real.max_year)],
        "view": [VIEWS[2]],
    }


def test_duplicate_url_codes_are_deduplicated(real: GdpData) -> None:
    """`?countries=BRA,BRA` must not build a frame with duplicate columns (stack raises)."""
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.query_params["countries"] = "BRA,deu,bra,DEU,Bra"
    at.run()
    assert not at.exception
    assert countries_widget(at).value == ["BRA", "DEU"]  # order of first appearance
    assert [m.label.split(" · ")[0] for m in at.metric] == ["Brazil", "Germany"]
    assert len(charts(at)) == 1
    assert at_query(at)["countries"] == "BRA,DEU"  # the URL is written back de-duplicated


def test_malformed_url_state_falls_back_to_defaults(real: GdpData) -> None:
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.query_params["countries"] = "nope"
    at.query_params["from"] = "abc"
    at.query_params["view"] = "bogus"
    at.run()
    assert not at.exception
    assert countries_widget(at).value == list(DEFAULT_COUNTRIES)
    assert at.slider[0].value[1] == real.max_year
    assert at.radio[0].value == VIEWS[0]
