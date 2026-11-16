"""Execute the profiling notebook and store its outputs inside the .ipynb.

Jupyter is not installable in this environment (pip is blocked), so this script
does what a kernel would do for this notebook: it runs every code cell in one
shared namespace, captures stdout, keeps matplotlib figures as PNG, and writes
the results into the `outputs` arrays so the deliverable shows what it produced.

It stops at the first failing cell and reports it.

Usage:
    set PYTHONPATH=%CD%\vendor;%CD%\src
    python tools/execute_notebook.py
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import sys
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "01_source_profiling.ipynb"


def stream(text: str) -> list[dict]:
    if not text:
        return []
    return [{"output_type": "stream", "name": "stdout", "text": text.splitlines(keepends=True)}]


def figures() -> list[dict]:
    outputs = []
    for number in plt.get_fignums():
        buffer = io.BytesIO()
        plt.figure(number).savefig(buffer, format="png", dpi=110, bbox_inches="tight")
        buffer.seek(0)
        outputs.append(
            {
                "output_type": "display_data",
                "data": {"image/png": base64.b64encode(buffer.read()).decode("ascii")},
                "metadata": {},
            }
        )
    plt.close("all")
    return outputs


def main() -> int:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    os.chdir(ROOT)
    namespace: dict = {"__name__": "__main__"}
    counter = 0

    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        counter += 1
        source = "".join(cell["source"])
        buffer = io.StringIO()
        print(f"celda {index} (ejecucion {counter})", end=" ")
        try:
            with contextlib.redirect_stdout(buffer):
                exec(compile(source, f"<cell {index}>", "exec"), namespace)  # noqa: S102
        except Exception:
            traceback.print_exc()
            print("FALLO")
            return 1
        cell["execution_count"] = counter
        cell["outputs"] = stream(buffer.getvalue()) + figures()
        print(f"-> {len(cell['outputs'])} salidas")

    NOTEBOOK.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    with_figures = sum(
        1
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
        and any(o["output_type"] == "display_data" for o in cell.get("outputs", []))
    )
    print(f"\nescrito: {NOTEBOOK.relative_to(ROOT)}")
    print(f"celdas ejecutadas: {counter}, de ellas con figura: {with_figures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
