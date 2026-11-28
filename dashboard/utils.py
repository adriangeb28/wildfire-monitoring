from __future__ import annotations

import os
from pathlib import Path

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import html

ROOT_DIR = Path(__file__).resolve().parents[1]
GOLD_DIR = Path(os.getenv("DATALAKE_GOLD", ROOT_DIR / "datalake_gold"))

PROJECT_TITLE = "Colombia Wildfire Monitoring Lakehouse"
TOPIC_ANGLE = "Near-Real-Time Thermal Anomalies (NASA FIRMS VIIRS) & Meteorological Drivers (Open-Meteo)"
TEAM_NAME = "Team 3: César Ospina, Santiago Alfonso & Adrián Espinosa"

# Colorblind-friendly Okabe-Ito & semantic palette
PALETTE = {
    "blue": "#0072B2",
    "sky": "#56B4E9",
    "orange": "#E69F00",
    "vermilion": "#D55E00",
    "green": "#009E73",
    "purple": "#CC79A7",
    "grey": "#6C757D",
    "dark": "#1F2937",
    "bg_card": "#FFFFFF",
    "bg_page": "#F4F6F9",
}

ANOMALY_COLORS = {
    "Very low": "#0072B2",
    "Low": "#009E73",
    "Normal": "#E69F00",
    "Elevated": "#D55E00",
    "Extreme": "#B91C1C",
}


def load_latest_gold(prefix: str) -> tuple[pd.DataFrame, str]:
    """Load the most recent Gold Parquet file matching <prefix>_*.parquet."""
    files = sorted(GOLD_DIR.glob(f"{prefix}_*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"No Gold Parquet files found matching '{prefix}_*.parquet' in {GOLD_DIR}"
        )
    latest = files[-1]
    return pd.read_parquet(latest), latest.name


def build_header(
    dashboard_title: str,
    audience_label: str,
    last_updated: str,
    source_file: str,
    refresh_btn_id: str,
) -> dbc.Card:
    """Reusable header card with project metadata, last-updated timestamp, and manual refresh."""
    return dbc.Card(
        dbc.CardBody(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Div(
                                [
                                    dbc.Badge(
                                        audience_label,
                                        color="primary",
                                        className="me-2",
                                    ),
                                    html.Span(
                                        PROJECT_TITLE,
                                        className="text-muted fw-semibold small",
                                    ),
                                ],
                                className="mb-1",
                            ),
                            html.H3(dashboard_title, className="mb-1 fw-bold text-dark"),
                            html.P(TOPIC_ANGLE, className="mb-0 text-secondary small"),
                        ],
                        md=7,
                    ),
                    dbc.Col(
                        [
                            html.Div(
                                TEAM_NAME,
                                className="small fw-semibold text-dark text-md-end",
                            ),
                            html.Div(
                                f"Last Updated (UTC): {last_updated}",
                                id=f"{refresh_btn_id}-timestamp",
                                className="small text-muted text-md-end",
                            ),
                            html.Div(
                                f"Gold Source: {source_file}",
                                id=f"{refresh_btn_id}-filename",
                                className="small text-muted text-md-end mb-2",
                            ),
                            html.Div(
                                dbc.Button(
                                    "Refresh Gold Data",
                                    id=refresh_btn_id,
                                    color="primary",
                                    size="sm",
                                    outline=True,
                                ),
                                className="text-md-end",
                            ),
                        ],
                        md=5,
                        className="d-flex flex-column justify-content-center",
                    ),
                ],
                className="align-items-center",
            )
        ),
        className="shadow-sm border-0 mb-3",
        style={"borderLeft": f"5px solid {PALETTE['blue']}"},
    )


def apply_standard_layout(
    fig: go.Figure,
    title: str,
    xaxis_title: str,
    yaxis_title: str,
    source_note: str = "Source: Gold Layer Parquet (NASA FIRMS VIIRS & Open-Meteo)",
    height: int = 360,
    show_legend: bool = True,
) -> go.Figure:
    """Apply consistent typography, margins, gridlines, and source annotation to Plotly figures."""
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=PALETTE["dark"]), x=0.01),
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        height=height,
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=show_legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1.0),
        margin=dict(l=60, r=25, t=65, b=65),
        font=dict(family="Segoe UI, Roboto, Arial, sans-serif", size=12, color=PALETTE["dark"]),
    )
    fig.add_annotation(
        text=source_note,
        xref="paper",
        yref="paper",
        x=0,
        y=-0.22,
        showarrow=False,
        font=dict(size=10, color=PALETTE["grey"]),
        xanchor="left",
    )
    return fig