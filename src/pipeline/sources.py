"""HTTP clients for the two incremental sources (F3 FIRMS NRT, F4 Open-Meteo).

Both return a FetchResult holding the response exactly as received (text),
plus the request description with the MAP_KEY masked, so the Bronze layer can
store the raw payload without ever writing a secret to disk.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from datetime import date

import requests

from . import settings

log = settings.get_logger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    source: str            # logical source name (config/sources.yaml)
    product: str           # FIRMS product or Open-Meteo endpoint
    url: str               # request URL with secrets masked
    params: dict
    status: int
    headers: dict
    content_type: str
    payload: str           # body exactly as received
    extra: dict = field(default_factory=dict)


def _get(url: str, params: dict | None = None, attempts: int = 4) -> requests.Response:
    """GET with exponential backoff on network errors and retryable status codes."""
    delay = 5.0
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(
                url, params=params, timeout=settings.HTTP_TIMEOUT,
                headers={"User-Agent": settings.USER_AGENT},
            )
            if response.status_code in RETRY_STATUS:
                raise requests.HTTPError(f"retryable status {response.status_code}", response=response)
            response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status not in RETRY_STATUS:
                raise
            if attempt == attempts:
                break
            log.warning("GET failed (attempt %s/%s): %s; retrying in %.0fs", attempt, attempts, exc, delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"GET failed after {attempts} attempts: {last_error}")


def fetch_firms_nrt(product: str, day_range: int, start: date | None = None,
                    source: str = "firms_nrt_viirs") -> FetchResult:
    """FIRMS area API, Colombia bounding box, CSV.

    Also serves the historical archive: with a ``*_SP`` product and
    ``source="firms_archive"`` the same endpoint returns standard-processing
    records for past dates, 5 days per request at most.

    With ``start`` the window is [start, start + day_range - 1], which makes a
    re-run for the same Airflow interval request the same dates (idempotency).
    """
    key = settings.firms_map_key()
    bbox = ",".join(str(v) for v in settings.BBOX)
    parts = [settings.FIRMS_BASE, key, product, bbox, str(day_range)]
    if start is not None:
        parts.append(start.isoformat())
    url = "/".join(parts)
    response = _get(url)
    text = response.text
    if text.lstrip().lower().startswith(("invalid", "error")):
        raise RuntimeError(f"FIRMS answered with an error message: {text[:120]!r}")
    return FetchResult(
        source=source,
        product=product,
        url=url.replace(key, "***MAP_KEY***"),
        params={"bbox": bbox, "day_range": day_range, "start": start.isoformat() if start else None},
        status=response.status_code,
        headers=dict(response.headers),
        content_type=response.headers.get("Content-Type", ""),
        payload=text,
    )


def load_centroids() -> list[dict]:
    with settings.CENTROIDS_CSV.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def fetch_open_meteo_forecast() -> FetchResult:
    """One call for all 33 region centroids, hourly variables, forced to UTC."""
    regions = load_centroids()
    params = {
        "latitude": ",".join(r["lat"] for r in regions),
        "longitude": ",".join(r["lon"] for r in regions),
        "hourly": ",".join(settings.OPEN_METEO_HOURLY),
        "past_days": settings.OPEN_METEO_PAST_DAYS,
        "forecast_days": settings.OPEN_METEO_FORECAST_DAYS,
        "timezone": "UTC",
    }
    response = _get(settings.OPEN_METEO_FORECAST_URL, params=params)
    return FetchResult(
        source="open_meteo_forecast",
        product="forecast",
        url=settings.OPEN_METEO_FORECAST_URL,
        params=params,
        status=response.status_code,
        headers=dict(response.headers),
        content_type=response.headers.get("Content-Type", ""),
        payload=response.text,
        # the response is a list in the same order as the coordinates;
        # this order is what lets Silver map each block back to its region
        extra={"region_order": [r["region_id"] for r in regions]},
    )
