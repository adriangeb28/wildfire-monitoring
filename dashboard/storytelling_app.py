from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html

from dashboard.utils import (
    ANOMALY_COLORS,
    PALETTE,
    apply_standard_layout,
    build_header,
    load_latest_gold,
)

SEVERITY_ORDER = ["Very low", "Low", "Normal", "Elevated", "Extreme"]


def _kpi_card(title: str, value: str, subtitle: str, accent_color: str) -> dbc.Card:
    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(title, className="text-muted small fw-semibold text-uppercase"),
                html.H3(value, className="fw-bold my-1", style={"color": accent_color}),
                html.Div(subtitle, className="text-secondary small"),
            ]
        ),
        className="shadow-sm border-0 h-100",
        style={"borderTop": f"4px solid {accent_color}"},
    )


def _build_severity_donut(df: pd.DataFrame) -> go.Figure:
    counts = (
        df["anomaly_level"]
        .value_counts()
        .reindex(SEVERITY_ORDER, fill_value=0)
        .reset_index()
    )
    counts.columns = ["anomaly_level", "region_days"]
    counts = counts[counts["region_days"] > 0]

    fig = px.pie(
        counts,
        names="anomaly_level",
        values="region_days",
        hole=0.48,
        color="anomaly_level",
        color_discrete_map=ANOMALY_COLORS,
        category_orders={"anomaly_level": SEVERITY_ORDER},
    )
    fig.update_traces(
        textinfo="label+percent",
        hovertemplate="<b>Severity: %{label}</b><br>Department-Days: %{value}<br>Share: %{percent}<extra></extra>",
    )
    return apply_standard_layout(
        fig,
        title="Wildfire Alert Severity Distribution (Department-Days)",
        xaxis_title="",
        yaxis_title="",
        source_note="Source: Gold Layer Storytelling Parquet (Weather-Conditioned Anomaly Classification)",
        show_legend=True,
    )


def _build_top_departments_bar(df: pd.DataFrame) -> go.Figure:
    rank_map = {lvl: idx for idx, lvl in enumerate(SEVERITY_ORDER)}
    df_tmp = df.copy()
    df_tmp["sev_num"] = df_tmp["anomaly_level"].map(rank_map).fillna(0)

    agg = (
        df_tmp.groupby("region_name", as_index=False)
        .agg(
            total_frp_mw=("total_frp_mw", "sum"),
            fire_event_count=("fire_event_count", "sum"),
            detection_count=("detection_count", "sum"),
            max_sev_num=("sev_num", "max"),
        )
        .sort_values("total_frp_mw", ascending=True)
        .tail(10)
    )
    inv_map = {idx: lvl for lvl, idx in rank_map.items()}
    agg["peak_severity"] = agg["max_sev_num"].map(inv_map)

    fig = px.bar(
        agg,
        x="total_frp_mw",
        y="region_name",
        color="peak_severity",
        orientation="h",
        color_discrete_map=ANOMALY_COLORS,
        category_orders={"peak_severity": SEVERITY_ORDER},
        custom_data=["fire_event_count", "detection_count"],
        labels={
            "total_frp_mw": "Cumulative Fire Radiative Power (MW)",
            "region_name": "Department",
            "peak_severity": "Peak Severity",
        },
    )
    fig.update_traces(
        texttemplate="%{x:,.0f} MW",
        textposition="outside",
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Total Radiative Power: %{x:,.2f} MW<br>"
            "Consolidated Fire Events (~1 km²): %{customdata[0]:,}<br>"
            "Raw Satellite Hotspots: %{customdata[1]:,}<extra></extra>"
        ),
    )
    max_x = float(agg["total_frp_mw"].max()) * 1.25 if not agg.empty else 100
    fig.update_xaxes(range=[0, max_x])
    return apply_standard_layout(
        fig,
        title="Top 10 Most Affected Departments by Cumulative Fire Intensity (MW)",
        xaxis_title="Cumulative Fire Radiative Power (MW)",
        yaxis_title="Colombian Department",
        source_note="Source: Gold Layer Storytelling Parquet (Aggregated Across Selected Dates)",
        show_legend=True,
    )


def _build_temporal_trend_fig(df: pd.DataFrame) -> go.Figure:
    daily = (
        df.groupby("metric_date", as_index=False)
        .agg(
            detection_count=("detection_count", "sum"),
            fire_event_count=("fire_event_count", "sum"),
            expected_detections=("expected_detections", "sum"),
        )
        .sort_values("metric_date")
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=daily["metric_date"],
            y=daily["detection_count"],
            mode="lines+markers+text",
            name="Observed Hotspot Pixels",
            text=daily["detection_count"].map(lambda v: f"{v:,}"),
            textposition="top center",
            line=dict(color=PALETTE["vermilion"], width=3),
            marker=dict(size=9),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=daily["metric_date"],
            y=daily["fire_event_count"],
            mode="lines+markers+text",
            name="Distinct Fire Events (~1 km²)",
            text=daily["fire_event_count"].map(lambda v: f"{v:,}"),
            textposition="bottom center",
            line=dict(color=PALETTE["blue"], width=3),
            marker=dict(size=9),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=daily["metric_date"],
            y=daily["expected_detections"],
            mode="lines+markers",
            name="Weather-Expected Baseline",
            line=dict(color=PALETTE["grey"], width=2, dash="dash"),
            marker=dict(size=7),
        )
    )
    fig.update_xaxes(type="category")
    max_y = float(daily["detection_count"].max()) * 1.22 if not daily.empty else 100
    fig.update_yaxes(range=[0, max_y])
    return apply_standard_layout(
        fig,
        title="Daily Wildfire Activity Trend: Observed vs. Weather-Expected Baseline",
        xaxis_title="Observation Date (UTC)",
        yaxis_title="Count (Detections / Events)",
        source_note="Source: Gold Layer Storytelling Parquet (Spatial Grid Clustering & Open-Meteo Baseline)",
        show_legend=True,
    )


def _build_source_comparison_fig(df: pd.DataFrame) -> go.Figure:
    by_date = (
        df.groupby("metric_date", as_index=False)
        .agg(
            noaa20_count=("noaa20_count", "sum"),
            noaa21_count=("noaa21_count", "sum"),
            day_count=("day_count", "sum"),
            night_count=("night_count", "sum"),
        )
        .sort_values("metric_date")
    )

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=by_date["metric_date"],
            y=by_date["noaa20_count"],
            name="NOAA-20 Satellite",
            marker_color=PALETTE["blue"],
            text=by_date["noaa20_count"],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            x=by_date["metric_date"],
            y=by_date["noaa21_count"],
            name="NOAA-21 Satellite",
            marker_color=PALETTE["green"],
            text=by_date["noaa21_count"],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            x=by_date["metric_date"],
            y=by_date["day_count"],
            name="Daytime Overpasses",
            marker_color=PALETTE["orange"],
            text=by_date["day_count"],
            textposition="outside",
        )
    )
    fig.add_trace(
        go.Bar(
            x=by_date["metric_date"],
            y=by_date["night_count"],
            name="Nighttime Overpasses",
            marker_color=PALETTE["purple"],
            text=by_date["night_count"],
            textposition="outside",
        )
    )
    fig.update_layout(barmode="group")
    fig.update_xaxes(type="category")
    max_val = max(
        float(by_date[["noaa20_count", "noaa21_count", "day_count", "night_count"]].max().max()) * 1.22,
        10,
    ) if not by_date.empty else 100
    fig.update_yaxes(range=[0, max_val])
    return apply_standard_layout(
        fig,
        title="Detection Breakdown by Satellite Sensor & Diurnal Cycle",
        xaxis_title="Observation Date (UTC)",
        yaxis_title="Valid Hotspot Detections",
        source_note="Source: Gold Layer Storytelling Parquet (VIIRS N20 vs N21 & Day/Night Flags)",
        show_legend=True,
    )


def _build_weather_drivers_fig(df: pd.DataFrame) -> go.Figure:
    fig = px.scatter(
        df,
        x="temp_max_c",
        y="fire_event_count",
        size="total_frp_mw",
        color="rh_min_pct",
        hover_name="region_name",
        custom_data=["metric_date", "wind_max_kmh", "anomaly_level", "total_frp_mw"],
        color_continuous_scale="YlOrRd_r",
        labels={
            "temp_max_c": "Daily Max Temperature (°C)",
            "fire_event_count": "Consolidated Fire Events (~1 km²)",
            "rh_min_pct": "Min Humidity (%)",
        },
    )
    fig.update_traces(
        marker=dict(line=dict(width=1, color="#1F2937"), opacity=0.85),
        hovertemplate=(
            "<b>%{hovertext}</b> (%{customdata[0]})<br>"
            "Max Temperature: %{x:.1f} °C<br>"
            "Consolidated Fire Events: %{y:,}<br>"
            "Cumulative Intensity: %{customdata[3]:,.2f} MW<br>"
            "Peak Wind Speed: %{customdata[1]:.1f} km/h<br>"
            "Alert Level: %{customdata[2]}<extra></extra>"
        ),
    )
    return apply_standard_layout(
        fig,
        title="Meteorological Drivers: Fire Events vs. Max Temperature & Min Humidity (Bubble Size = FRP)",
        xaxis_title="Daily Maximum Temperature (°C)",
        yaxis_title="Consolidated Fire Events (~1 km²)",
        source_note="Source: Gold Layer Storytelling Parquet (Joined NASA FIRMS & Open-Meteo Telemetry)",
        height=390,
        show_legend=False,
    )


def _build_narrative_summary(df: pd.DataFrame) -> dbc.Card:
    if df.empty:
        text = "No wildfire events match the current filter criteria. Broaden the date, department, or severity filter."
    else:
        total_det = int(df["detection_count"].sum())
        total_ev = int(df["fire_event_count"].sum())
        total_frp = float(df["total_frp_mw"].sum())
        extreme_cnt = int((df["anomaly_level"] == "Extreme").sum())
        top_row = df.sort_values(["anomaly_ratio", "total_frp_mw"], ascending=[False, False]).iloc[0]
        top_dept = str(top_row["region_name"])
        top_date = str(top_row["metric_date"])
        top_ratio = float(top_row["anomaly_ratio"])
        top_frp = float(top_row["total_frp_mw"])

        text = (
            f"Across the selected scope, satellites detected {total_det:,} thermal hotspots consolidated into "
            f"{total_ev:,} distinct ~1 km² wildfire events releasing {total_frp:,.2f} MW of cumulative radiative power. "
            f"A total of {extreme_cnt} department-day alerts reached 'Extreme' severity (>= 3x weather-adjusted baseline). "
            f"The most critical hotspot concentration occurred in {top_dept} on {top_date}, recording {top_frp:,.2f} MW "
            f"({top_ratio:.1f}x above expected activity under local temperature and humidity conditions), signaling "
            f"immediate priority for regional fire-response brigades."
        )

    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(
                    [
                        dbc.Badge("EXECUTIVE NARRATIVE INSIGHT", color="danger", className="me-2"),
                        html.Span(
                            "Key Takeaway for Environmental & Emergency Decision-Makers",
                            className="fw-bold text-dark small",
                        ),
                    ],
                    className="mb-2",
                ),
                html.P(text, className="mb-0 text-dark", style={"lineHeight": "1.55"}),
            ]
        ),
        className="shadow-sm border-0 mb-3",
        style={"backgroundColor": "#FFF8F6", "borderLeft": f"5px solid {PALETTE['vermilion']}"},
    )


def create_app() -> Dash:
    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.FLATLY],
        title="Wildfire Monitoring | Regional Storytelling",
    )

    df_init, fname_init = load_latest_gold("storytelling")
    ts_init = str(df_init["generated_at"].iloc[0]) if not df_init.empty else "N/A"
    date_options = [{"label": d, "value": d} for d in sorted(df_init["metric_date"].astype(str).unique())]
    dept_options = [{"label": r, "value": r} for r in sorted(df_init["region_name"].astype(str).unique())]
    sev_options = [{"label": s, "value": s} for s in SEVERITY_ORDER]

    app.layout = dbc.Container(
        [
            dcc.Interval(id="story-auto-refresh", interval=60_000, n_intervals=0),
            html.Div(
                build_header(
                    dashboard_title="Colombia Wildfire Risk & Environmental Storytelling Dashboard",
                    audience_label="FUNCTIONAL USER / EMERGENCY & ENVIRONMENTAL ANALYSTS",
                    last_updated=ts_init,
                    source_file=fname_init,
                    refresh_btn_id="story-refresh-btn",
                ),
                id="story-header-container",
            ),
            dbc.Card(
                dbc.CardBody(
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Label("Filter by Observation Date", className="small fw-semibold text-muted"),
                                    dcc.Dropdown(
                                        id="story-date-filter",
                                        options=date_options,
                                        multi=True,
                                        placeholder="All available dates",
                                    ),
                                ],
                                md=4,
                            ),
                            dbc.Col(
                                [
                                    html.Label("Filter by Department", className="small fw-semibold text-muted"),
                                    dcc.Dropdown(
                                        id="story-dept-filter",
                                        options=dept_options,
                                        multi=True,
                                        placeholder="All 26 active departments",
                                    ),
                                ],
                                md=4,
                            ),
                            dbc.Col(
                                [
                                    html.Label("Filter by Alert Severity Level", className="small fw-semibold text-muted"),
                                    dcc.Dropdown(
                                        id="story-sev-filter",
                                        options=sev_options,
                                        multi=True,
                                        placeholder="All severity levels",
                                    ),
                                ],
                                md=4,
                            ),
                        ],
                        className="g-3",
                    )
                ),
                className="shadow-sm border-0 mb-3",
            ),
            html.Div(id="story-narrative-container"),
            dbc.Row(id="story-kpi-cards", className="g-3 mb-3"),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="story-donut-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=5,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="story-top-dept-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=7,
                    ),
                ],
                className="g-3 mb-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="story-trend-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=6,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="story-source-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=6,
                    ),
                ],
                className="g-3 mb-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="story-weather-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=12,
                    ),
                ],
                className="g-3 mb-4",
            ),
        ],
        fluid=True,
        style={"backgroundColor": PALETTE["bg_page"], "minHeight": "100vh", "padding": "18px 24px"},
    )

    @app.callback(
        Output("story-header-container", "children"),
        Output("story-narrative-container", "children"),
        Output("story-kpi-cards", "children"),
        Output("story-donut-chart", "figure"),
        Output("story-top-dept-chart", "figure"),
        Output("story-trend-chart", "figure"),
        Output("story-source-chart", "figure"),
        Output("story-weather-chart", "figure"),
        Input("story-date-filter", "value"),
        Input("story-dept-filter", "value"),
        Input("story-sev-filter", "value"),
        Input("story-refresh-btn", "n_clicks"),
        Input("story-auto-refresh", "n_intervals"),
    )
    def update_storytelling(selected_dates, selected_depts, selected_sevs, _n_clicks, _n_intervals):
        df, fname = load_latest_gold("storytelling")
        df["metric_date"] = df["metric_date"].astype(str)
        last_ts = str(df["generated_at"].iloc[0]) if not df.empty else "N/A"

        filtered = df.copy()
        if selected_dates:
            filtered = filtered[filtered["metric_date"].isin(selected_dates)]
        if selected_depts:
            filtered = filtered[filtered["region_name"].isin(selected_depts)]
        if selected_sevs:
            filtered = filtered[filtered["anomaly_level"].isin(selected_sevs)]

        total_events = int(filtered["fire_event_count"].sum())
        total_detections = int(filtered["detection_count"].sum())
        total_frp = float(filtered["total_frp_mw"].sum())
        active_depts = int(filtered["region_name"].nunique())
        extreme_alerts = int((filtered["anomaly_level"] == "Extreme").sum())

        cards = [
            dbc.Col(
                _kpi_card(
                    "Consolidated Fire Events",
                    f"{total_events:,}",
                    f"From {total_detections:,} raw satellite hotspots",
                    PALETTE["blue"],
                ),
                md=3,
            ),
            dbc.Col(
                _kpi_card(
                    "Cumulative Fire Intensity",
                    f"{total_frp:,.1f} MW",
                    "Total Fire Radiative Power released",
                    PALETTE["vermilion"],
                ),
                md=3,
            ),
            dbc.Col(
                _kpi_card(
                    "Extreme Severity Alerts",
                    f"{extreme_alerts}",
                    "Department-days >= 3x expected baseline",
                    "#B91C1C",
                ),
                md=3,
            ),
            dbc.Col(
                _kpi_card(
                    "Affected Departments",
                    f"{active_depts}",
                    "Colombian ADM1 regions with active burns",
                    PALETTE["green"],
                ),
                md=3,
            ),
        ]

        header = build_header(
            dashboard_title="Colombia Wildfire Risk & Environmental Storytelling Dashboard",
            audience_label="FUNCTIONAL USER / EMERGENCY & ENVIRONMENTAL ANALYSTS",
            last_updated=last_ts,
            source_file=fname,
            refresh_btn_id="story-refresh-btn",
        )

        return (
            header,
            _build_narrative_summary(filtered),
            cards,
            _build_severity_donut(filtered),
            _build_top_departments_bar(filtered),
            _build_temporal_trend_fig(filtered),
            _build_source_comparison_fig(filtered),
            _build_weather_drivers_fig(filtered),
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=8051, debug=False)