"""ingest.py — command-line entry point for the wildfire ingestion pipeline.

STUB at Workshop-1 stage. The contract it must eventually honour is declared in
config/sources.yaml; this file only defines the interface so the structure of
the system is clear before any pipeline code exists.

Usage examples
--------------
    python ingest.py --list
    python ingest.py --source firms_nrt_viirs --mode incremental --dry-run
    python ingest.py --source firms_archive --mode historical --partition 2019

At this stage every real run exits with a message: the sources are validated by
hand and the unmodified responses are kept in workshop_1/samples/.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "sources.yaml"

SOURCES = {
    "firms_archive": "NASA FIRMS bulk archive (historical)",
    "open_meteo_historical": "Open-Meteo ERA5 reanalysis (historical)",
    "firms_nrt_viirs": "NASA FIRMS NRT VIIRS NOAA-20/21 (incremental)",
    "open_meteo_forecast": "Open-Meteo Forecast API (incremental)",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingest",
        description="Wildfire monitoring ingestion entry point (workshop stub).",
    )
    parser.add_argument("--list", action="store_true", help="list declared sources and exit")
    parser.add_argument("--source", choices=sorted(SOURCES), help="source to ingest")
    parser.add_argument(
        "--mode",
        choices=["historical", "incremental"],
        help="historical = bulk partition load, incremental = watermark-driven poll",
    )
    parser.add_argument(
        "--partition",
        help="partition identifier, e.g. '2019' for a year or '2019|VIIRS_NOAA20_SP'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve configuration and print the plan without contacting the source",
    )
    return parser


def check_environment(source: str) -> list[str]:
    """Report missing credentials for the given source, without printing them."""
    problems: list[str] = []
    if source.startswith("firms_nrt") and not os.getenv("FIRMS_MAP_KEY"):
        problems.append("FIRMS_MAP_KEY is not set (see .env.example)")
    if source.startswith("firms_archive") and not (
        os.getenv("EARTHDATA_USERNAME") or os.getenv("EARTHDATA_EMAIL_CODE")
    ):
        problems.append("Earthdata credentials are not set (see .env.example)")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list or not args.source:
        print("Declared sources (see config/sources.yaml):")
        for name, description in SOURCES.items():
            print(f"  {name:<22} {description}")
        print(f"\nContract file: {CONFIG_PATH.relative_to(ROOT)}")
        return 0

    print(f"source    : {args.source}")
    print(f"mode      : {args.mode or '(not specified)'}")
    print(f"partition : {args.partition or '(not specified)'}")

    problems = check_environment(args.source)
    for problem in problems:
        print(f"  ! {problem}")

    if args.dry_run:
        print("\ndry run: configuration resolved, nothing downloaded.")
        return 0 if not problems else 1

    print(
        "\nNot implemented yet: this is the Workshop-1 stub.\n"
        "At this stage each source is queried by hand and the unmodified response\n"
        "is stored under workshop_1/samples/. Implementation starts in Workshop 2."
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
