"""Bootstrap a local vendor/ directory without using pip.

Why this exists: `pip install` fails in this environment with
    PermissionError: ... <wheel>.whl.metadata
when pip writes/cleans its unpack temp directory (OneDrive-synced workspace +
sandbox). This script downloads the wheels straight from PyPI and extracts them
with zipfile, which needs neither pip nor its temp handling.

Usage:
    python tools/bootstrap_vendor.py
    set PYTHONPATH=%CD%\vendor   &&  python -c "import pandas"
"""

from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
WHEELS = ROOT / "wheels"

# Packages we need plus their runtime dependencies. Latest version of each is
# taken; wheels are chosen for this interpreter / platform.
PACKAGES = [
    "pandas",
    "numpy",
    "python-dateutil",
    "six",
    "tzdata",
    "requests",
    "urllib3",
    "certifi",
    "idna",
    "charset-normalizer",
    "shapely",
    "matplotlib",
]

PY_TAG = f"cp{sys.version_info.major}{sys.version_info.minor}"


def _plat_tag(filename: str) -> str:
    """Platform tag of a wheel filename: the last dash-separated field."""
    return filename[: -len(".whl")].split("-")[-1]


def _abi_tag(filename: str) -> str:
    return filename[: -len(".whl")].split("-")[-2]


def _pick_wheel(files: list[dict]) -> dict | None:
    """Prefer a compiled wheel for this interpreter/platform, then pure-python."""
    wheels = [f for f in files if f["filename"].endswith(".whl")]

    # 1) compiled wheel for this CPython version and ABI on Windows
    for f in wheels:
        if _plat_tag(f["filename"]) == "win_amd64" and _abi_tag(f["filename"]) == PY_TAG:
            return f
    # 2) any Windows wheel
    for f in wheels:
        if _plat_tag(f["filename"]) in ("win_amd64", "win32"):
            return f
    # 3) pure-python wheel
    for f in wheels:
        if _plat_tag(f["filename"]) == "any":
            return f
    return None


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "bootstrap/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached  {dest.name}")
        return
    req = urllib.request.Request(url, headers={"User-Agent": "bootstrap/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as fh:
        fh.write(resp.read())
    print(f"  got     {dest.name}  ({dest.stat().st_size // 1024} KB)")


def main() -> int:
    VENDOR.mkdir(exist_ok=True)
    WHEELS.mkdir(exist_ok=True)

    for pkg in PACKAGES:
        print(f"[{pkg}]")
        try:
            meta = fetch_json(f"https://pypi.org/pypi/{pkg}/json")
        except Exception as exc:  # noqa: BLE001
            print(f"  SKIP: could not query PyPI ({exc})")
            continue
        wheel = _pick_wheel(meta["urls"])
        if wheel is None:
            print(f"  SKIP: no compatible wheel for {PY_TAG}")
            continue
        dest = WHEELS / wheel["filename"]
        download(wheel["url"], dest)
        with zipfile.ZipFile(dest) as zf:
            zf.extractall(VENDOR)
        print(f"  extracted into vendor/")

    print("\nVendor ready. Test with:")
    print(f'  $env:PYTHONPATH="{VENDOR}"')
    print('  python -c "import pandas, requests; print(pandas.__version__)"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
