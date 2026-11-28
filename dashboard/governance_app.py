from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Dash, Input, Output, dash_table, dcc, html

from dashboard.utils import (
    PALETTE,
    apply_standard_layout,
    build_header,
    load_latest_gold,
)

# Governance thresholds for automated status evaluation
KPI_THRESHOLDS: dict[str, tuple[str, callable]] = {
    "valid_ingestion_volume": (">= 50 records/run", lambda v: "PASS" if v >= 50 else "WARN"),
    "null_rate_pct": ("<= 5.0%", lambda v: "PASS" if v <= 5.0 else "ALERT"),
    "schema_compliance_rate_pct": (">= 95.0%", lambda v: "PASS" if v >= 95.0 else "WARN"),
    "frp_outlier_rate_pct": ("<= 5.0% (flagged, retained)", lambda v: "PASS" if v <= 5.0 else "WARN"),
    "revision_rate_pct": ("<= 10.0%", lambda v: "PASS" if v <= 10.0 else "WARN"),
    "quarantine_rejection_rate_pct": ("<= 90.0% (spatial bbox filter)", lambda v: "PASS" if v <= 90.0 else "WARN"),
    "imputation_rate_pct": ("<= 10.0%", lambda v: "PASS" if v <= 10.0 else "WARN"),
    "extreme_zscore_rate_pct": ("<= 1.0%", lambda v: "PASS" if v <= 1.0 else "WARN"),
    "median_ingestion_latency_h": ("<= 24.0 h (NRT SLA)", lambda v: "PASS" if v <= 24.0 else "INFO (Backfill)"),
}


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


def _build_null_rate_fig(df: pd.DataFrame) -> go.Figure:
    null_df = df[df["kpi_name"] == "null_rate_pct"].copy()
    null_df["field_label"] = null_df["source"] + " · " + null_df["dimension"]
    null_df = null_df.sort_values(["kpi_value", "field_label"], ascending=[True, False])

    fig = go.Figure(
        go.Bar(
            x=null_df["kpi_value"],
            y=null_df["field_label"],
            orientation="h",
            marker_color=PALETTE["blue"],
            text=null_df["kpi_value"].map(lambda v: f"{v:.2f}%"),
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Null Rate: %{x:.4f}%<extra></extra>",
        )
    )
    max_x = max(6.0, float(null_df["kpi_value"].max()) * 1.25) if not null_df.empty else 6.0
    fig.add_vline(
        x=5.0,
        line_dash="dash",
        line_color=PALETTE["vermilion"],
        annotation_text="Completeness SLA Limit (5.0%)",
        annotation_position="top right",
        annotation_font_color=PALETTE["vermilion"],
    )
    fig.update_xaxes(range=[0, max_x], ticksuffix="%")
    return apply_standard_layout(
        fig,
        title="Null Rate by Monitored Field (Ordered by Severity)",
        xaxis_title="Null Rate (%)",
        yaxis_title="Source · Field",
        show_legend=False,
    )


def _build_volume_fig(df: pd.DataFrame) -> go.Figure:
    vol_df = df[df["kpi_name"] == "valid_ingestion_volume"].copy()
    vol_df = vol_df.sort_values(["metric_date", "dimension"])

    fig = px.bar(
        vol_df,
        x="metric_date",
        y="kpi_value",
        color="dimension",
        barmode="group",
        text_auto=".0f",
        color_discrete_map={"N20": PALETTE["blue"], "N21": PALETTE["green"]},
        labels={"metric_date": "Observation Date", "kpi_value": "Valid Records", "dimension": "Satellite"},
    )
    fig.update_traces(
        textposition="outside",
        hovertemplate="<b>Date:</b> %{x}<br><b>Records:</b> %{y:,.0f}<extra></extra>",
    )
    fig.update_xaxes(type="category")
    max_y = float(vol_df["kpi_value"].max()) * 1.2 if not vol_df.empty else 100
    fig.update_yaxes(range=[0, max_y])
    return apply_standard_layout(
        fig,
        title="Valid Ingested Volume Over Time by VIIRS Satellite",
        xaxis_title="Observation Date (UTC)",
        yaxis_title="Valid Detections (records)",
        show_legend=True,
    )


def _build_outlier_fig(df: pd.DataFrame) -> go.Figure:
    out_df = df[df["kpi_name"].isin(["frp_outlier_rate_pct", "extreme_zscore_rate_pct"])].copy()
    out_df["label"] = out_df.apply(
        lambda r: (
            f"FIRMS {r['dimension']} ({r['metric_date']})"
            if r["kpi_name"] == "frp_outlier_rate_pct"
            else f"Weather: {r['dimension']}"
        ),
        axis=1,
    )
    out_df["metric_group"] = out_df["kpi_name"].map(
        {
            "frp_outlier_rate_pct": "FRP Outlier Rate (IQR)",
            "extreme_zscore_rate_pct": "Weather Extreme Z-Score (|z|>4)",
        }
    )
    out_df = out_df.sort_values("kpi_value", ascending=True)

    fig = px.bar(
        out_df,
        x="kpi_value",
        y="label",
        color="metric_group",
        orientation="h",
        color_discrete_map={
            "FRP Outlier Rate (IQR)": PALETTE["vermilion"],
            "Weather Extreme Z-Score (|z|>4)": PALETTE["orange"],
        },
        labels={"kpi_value": "Rate (%)", "label": "Field / Partition", "metric_group": "Check Type"},
    )
    fig.update_traces(
        texttemplate="%{x:.2f}%",
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Outlier Rate: %{x:.4f}%<extra></extra>",
    )
    max_x = max(3.0, float(out_df["kpi_value"].max()) * 1.25) if not out_df.empty else 3.0
    fig.update_xaxes(range=[0, max_x], ticksuffix="%")
    return apply_standard_layout(
        fig,
        title="Outlier & Extreme Anomaly Rates by Numeric Field",
        xaxis_title="Flagged Observations (%)",
        yaxis_title="Source / Dimension",
        show_legend=True,
    )


def _build_compliance_latency_fig(df: pd.DataFrame) -> go.Figure:
    comp_df = df[df["kpi_name"] == "schema_compliance_rate_pct"].copy()
    comp_df["label"] = comp_df["dimension"] + " (" + comp_df["metric_date"] + ")"
    comp_df = comp_df.sort_values(["metric_date", "dimension"])

    fig = go.Figure(
        go.Bar(
            x=comp_df["label"],
            y=comp_df["kpi_value"],
            marker_color=PALETTE["green"],
            text=comp_df["kpi_value"].map(lambda v: f"{v:.2f}%"),
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Schema Compliance: %{y:.2f}%<extra></extra>",
        )
    )
    fig.add_hline(
        y=95.0,
        line_dash="dash",
        line_color=PALETTE["dark"],
        annotation_text="Target SLA (95.0%)",
        annotation_position="bottom right",
    )
    fig.update_yaxes(range=[90, 102], ticksuffix="%")
    return apply_standard_layout(
        fig,
        title="Schema Compliance Rate by Satellite & Observation Date",
        xaxis_title="Satellite (Observation Date)",
        yaxis_title="Clean Schema Compliance (%)",
        show_legend=False,
    )


def _prepare_summary_table(df: pd.DataFrame) -> list[dict]:
    records = []
    for _, row in df.iterrows():
        kpi = str(row["kpi_name"])
        val = float(row["kpi_value"])
        threshold_desc, evaluator = KPI_THRESHOLDS.get(kpi, ("Monitored", lambda _: "PASS"))
        records.append(
            {
                "metric_date": str(row["metric_date"]),
                "source": str(row["source"]),
                "dimension": str(row["dimension"]),
                "kpi_name": kpi,
                "kpi_value": round(val, 4),
                "unit": str(row["unit"]),
                "threshold": threshold_desc,
                "status": evaluator(val),
            }
        )
    return records


def create_app() -> Dash:
    app = Dash(
        __name__,
        external_stylesheets=[dbc.themes.FLATLY],
        title="Wildfire Monitoring | Data Governance",
    )

    df_init, fname_init = load_latest_gold("governance")
    ts_init = str(df_init["generated_at"].iloc[0]) if not df_init.empty else "N/A"

    app.layout = dbc.Container(
        [
            dcc.Interval(id="gov-auto-refresh", interval=60_000, n_intervals=0),
            html.Div(
                build_header(
                    dashboard_title="Data Governance & Pipeline Quality Dashboard",
                    audience_label="TECHNICAL / DATA ENGINEERING",
                    last_updated=ts_init,
                    source_file=fname_init,
                    refresh_btn_id="gov-refresh-btn",
                ),
                id="gov-header-container",
            ),
            dbc.Row(id="gov-kpi-cards", className="g-3 mb-3"),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="gov-null-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=6,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="gov-volume-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=6,
                    ),
                ],
                className="g-3 mb-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="gov-outlier-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=6,
                    ),
                    dbc.Col(
                        dbc.Card(dbc.CardBody(dcc.Graph(id="gov-compliance-chart", config={"displayModeBar": True})), className="shadow-sm border-0"),
                        lg=6,
                    ),
                ],
                className="g-3 mb-3",
            ),
            dbc.Card(
                dbc.CardBody(
                    [
                        html.H5("Data Quality Summary Table (All Governance KPIs)", className="fw-bold mb-1"),
                        html.P(
                            "Complete audit view of all Gold governance KPIs compared against operational quality thresholds.",
                            className="text-muted small mb-3",
                        ),
                        dash_table.DataTable(
                            id="gov-summary-table",
                            columns=[
                                {"name": "Date", "id": "metric_date"},
                                {"name": "Source", "id": "source"},
                                {"name": "Dimension", "id": "dimension"},
                                {"name": "KPI Name", "id": "kpi_name"},
                                {"name": "Current Value", "id": "kpi_value"},
                                {"name": "Unit", "id": "unit"},
                                {"name": "Defined Threshold", "id": "threshold"},
                                {"name": "Status", "id": "status"},
                            ],
                            sort_action="native",
                            filter_action="native",
                            page_size=12,
                            style_table={"overflowX": "auto"},
                            style_header={
                                "backgroundColor": PALETTE["dark"],
                                "color": "white",
                                "fontWeight": "bold",
                                "fontSize": "12px",
                            },
                            style_cell={
                                "textAlign": "left",
                                "padding": "8px 10px",
                                "fontSize": "12px",
                                "fontFamily": "Segoe UI, Roboto, Arial, sans-serif",
                            },
                            style_data_conditional=[
                                {
                                    "if": {"filter_query": '{status} = "PASS"', "column_id": "status"},
                                    "backgroundColor": "#D1FAE5",
                                    "color": "#065F46",
                                    "fontWeight": "bold",
                                },
                                {
                                    "if": {"filter_query": '{status} = "WARN"', "column_id": "status"},
                                    "backgroundColor": "#FEF3C7",
                                    "color": "#92400E",
                                    "fontWeight": "bold",
                                },
                                {
                                    "if": {"filter_query": '{status} = "ALERT"', "column_id": "status"},
                                    "backgroundColor": "#FEE2E2",
                                    "color": "#991B1B",
                                    "fontWeight": "bold",
                                },
                                {
                                    "if": {"filter_query": '{status} contains "INFO"', "column_id": "status"},
                                    "backgroundColor": "#E0F2FE",
                                    "color": "#075985",
                                    "fontWeight": "bold",
                                },
                            ],
                        ),
                    ]
                ),
                className="shadow-sm border-0 mb-4",
            ),
        ],
        fluid=True,
        style={"backgroundColor": PALETTE["bg_page"], "minHeight": "100vh", "padding": "18px 24px"},
    )

    @app.callback(
        Output("gov-header-container", "children"),
        Output("gov-kpi-cards", "children"),
        Output("gov-null-chart", "figure"),
        Output("gov-volume-chart", "figure"),
        Output("gov-outlier-chart", "figure"),
        Output("gov-compliance-chart", "figure"),
        Output("gov-summary-table", "data"),
        Input("gov-refresh-btn", "n_clicks"),
        Input("gov-auto-refresh", "n_intervals"),
    )
    def refresh_governance(_n_clicks, _n_intervals):
        df, fname = load_latest_gold("governance")
        last_ts = str(df["generated_at"].iloc[0]) if not df.empty else "N/A"

        total_valid = int(df.loc[df["kpi_name"] == "valid_ingestion_volume", "kpi_value"].sum())
        avg_null = float(df.loc[df["kpi_name"] == "null_rate_pct", "kpi_value"].mean())
        avg_compliance = float(df.loc[df["kpi_name"] == "schema_compliance_rate_pct", "kpi_value"].mean())
        quarantine_vals = df.loc[df["kpi_name"] == "quarantine_rejection_rate_pct", "kpi_value"]
        quarantine_rate = float(quarantine_vals.iloc[0]) if not quarantine_vals.empty else 0.0
        rev_rate = float(df.loc[df["kpi_name"] == "revision_rate_pct", "kpi_value"].mean())

        cards = [
            dbc.Col(
                _kpi_card(
                    "Total Valid Detections",
                    f"{total_valid:,}",
                    "Consolidated across NOAA-20 & NOAA-21",
                    PALETTE["blue"],
                ),
                md=3,
            ),
            dbc.Col(
                _kpi_card(
                    "Mean Schema Compliance",
                    f"{avg_compliance:.2f}%",
                    "Target >= 95.0% clean validation",
                    PALETTE["green"],
                ),
                md=3,
            ),
            dbc.Col(
                _kpi_card(
                    "Mean Null Rate",
                    f"{avg_null:.2f}%",
                    f"Across 9 FIRMS & Open-Meteo fields (Rev: {rev_rate:.2f}%)",
                    PALETTE["sky"],
                ),
                md=3,
            ),
            dbc.Col(
                _kpi_card(
                    "Spatial Quarantine Rate",
                    f"{quarantine_rate:.2f}%",
                    "Outside Colombia polygon (isolated in DLQ)",
                    PALETTE["orange"],
                ),
                md=3,
            ),
        ]

        header = build_header(
            dashboard_title="Data Governance & Pipeline Quality Dashboard",
            audience_label="TECHNICAL / DATA ENGINEERING",
            last_updated=last_ts,
            source_file=fname,
            refresh_btn_id="gov-refresh-btn",
        )

        return (
            header,
            cards,
            _build_null_rate_fig(df),
            _build_volume_fig(df),
            _build_outlier_fig(df),
            _build_compliance_latency_fig(df),
            _prepare_summary_table(df),
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=8050, debug=False)