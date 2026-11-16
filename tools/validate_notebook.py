"""Validate the generated notebook by executing its code cells in order.

Jupyter is not installed in this environment, so this script emulates a
top-to-bottom run: same interpreter, one shared namespace, matplotlib on Agg.
Any exception is reported with the cell index.

Usage:
    python tools/validate_notebook.py
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "01_source_profiling.ipynb"


def main() -> int:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    namespace = {"__name__": "__main__"}
    import os

    os.chdir(ROOT)
    failures = 0
    executed = 0

    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        executed += 1
        print(f"\n{'=' * 70}\n[código {executed}] celda {index}\n{'=' * 70}")
        try:
            exec(compile(source, f"<cell {index}>", "exec"), namespace)  # noqa: S102
        except Exception:
            failures += 1
            print(f"FALLO en la celda {index}:")
            traceback.print_exc()

    print(f"\n{'=' * 70}")
    print(f"celdas de código ejecutadas: {executed} | fallos: {failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
