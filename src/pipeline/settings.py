"""Paths and environment.

Every path is derived from PROJECT_ROOT so the same code runs on the host
(repository root) and inside the Airflow containers (/opt/airflow), where the
folders are mounted as volumes by docker-compose.yml.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

try:  # optional: load .env when running on the host
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[2]))

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

BRONZE_DIR = Path(os.getenv("DATALAKE_BRONZE", PROJECT_ROOT / "datalake_bronze"))
SILVER_DIR = Path(os.getenv("DATALAKE_SILVER", PROJECT_ROOT / "datalake_silver"))
GOLD_DIR = Path(os.getenv("DATALAKE_GOLD", PROJECT_ROOT / "datalake_gold"))
QUARANTINE_DIR = SILVER_DIR / "_quarantine"
STATE_DB = SILVER_DIR / "_state" / "silver_state.sqlite"

REFERENCE_DIR = PROJECT_ROOT / "reference"
REGIONS_GEOJSON = REFERENCE_DIR / "regions_col_adm1.geojson"
CENTROIDS_CSV = REFERENCE_DIR / "regions_centroids.csv"

# Colombia bounding box (west, south, east, north); see config/sources.yaml
BBOX = tuple(float(v) for v in os.getenv("FIRE_BBOX", "-79.0,-4.5,-66.5,13.5").split(","))

FIRMS_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
FIRMS_PRODUCTS = ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
FIRMS_DAY_RANGE = int(os.getenv("FIRMS_DAY_RANGE", "2"))  # 1-day overlap, see W1 contract

OPEN_METEO_FORECAST_URL = os.getenv("OPEN_METEO_BASE_URL", "https://api.open-meteo.com/v1") + "/forecast"
OPEN_METEO_HOURLY = ("temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m")
OPEN_METEO_PAST_DAYS = int(os.getenv("OPEN_METEO_PAST_DAYS", "7"))
OPEN_METEO_FORECAST_DAYS = int(os.getenv("OPEN_METEO_FORECAST_DAYS", "7"))

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT_SECONDS", "60"))
USER_AGENT = os.getenv(
    "HTTP_USER_AGENT",
    "wildfire-monitoring/0.2 (Universidad Distrital, Data Analysis Programming course project)",
)


def firms_map_key() -> str:
    key = os.getenv("FIRMS_MAP_KEY", "").strip()
    if not key or key == "your_map_key_here":
        raise RuntimeError("FIRMS_MAP_KEY is not set; copy .env.example to .env and fill it in")
    return key


def ensure_dirs() -> None:
    for path in (BRONZE_DIR, SILVER_DIR, GOLD_DIR, QUARANTINE_DIR, STATE_DB.parent):
        path.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """Structured-ish logger; inside Airflow the task logger captures it."""
    logger = logging.getLogger(name)
    if not logging.getLogger().handlers and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    return logger
