"""Render a Markdown file or an executed notebook to PDF, through LaTeX.

The course platform only accepts PDF, so this produces uploadable versions of
`workshop_1/mapping.md` and `notebooks/01_source_profiling.ipynb`. It handles the
subset of Markdown these files actually use: headings, paragraphs, bullet and
numbered lists, pipe tables, fenced code and inline code.

Usage:
    python tools/md_to_pdf.py workshop_1/mapping.md
    python tools/md_to_pdf.py notebooks/01_source_profiling.ipynb --title "Source profiling notebook"
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "docs" / "build_pdf"

# glifos que pdflatex con inputenc utf8 no resuelve solo
SYMBOLS = {
    "Σ": r"$\Sigma$", "≈": r"$\approx$", "→": r"$\to$", "≥": r"$\ge$", "≤": r"$\le$",
    "×": r"$\times$", "·": r"$\cdot$", "Δ": r"$\Delta$", "±": r"$\pm$", "−": "-",
    "“": "``", "”": "''", "‘": "`", "’": "'", "–": "--", "—": "---", "°": r"\textdegree{}",
    "σ": r"$\sigma$", "ε": r"$\varepsilon$", "½": r"\textonehalf{}", "…": r"\ldots{}",
}

ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}",
}


def esc(text: str) -> str:
    for glyph, latex in SYMBOLS.items():
        text = text.replace(glyph, latex)
    out = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "$":  # respetar formulas ya introducidas por SYMBOLS
            end = text.find("$", i + 1)
            if end > i:
                out.append(text[i:end + 1])
                i = end + 1
                continue
        out.append(ESCAPES.get(char, char))
        i += 1
    return "".join(out)


INLINE_TOKEN = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*|\[[^\]]+\]\([^)]+\))")


def inline(text: str) -> str:
    """Convierte code spans, negritas, cursivas y enlaces, escapando el resto."""
    parts = INLINE_TOKEN.split(text)
    out = []
    for index, part in enumerate(parts):
        if index % 2 == 0:
            out.append(esc(part))
            continue
        if part.startswith("`"):
            out.append(r"\texttt{" + esc(part[1:-1]) + "}")
        elif part.startswith("**"):
            out.append(r"\textbf{" + inline(part[2:-2]) + "}")
        elif part.startswith("*"):
            out.append(r"\emph{" + inline(part[1:-1]) + "}")
        else:
            match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", part)
            out.append(esc(match.group(1)))
    return "".join(out)


def is_table_row(line: str) -> bool:
    return line.strip().startswith("|") and line.strip().endswith("|")


def render_table(rows: list[str]) -> str:
    cells = [[c.strip() for c in row.strip().strip("|").split("|")] for row in rows]
    cells = [c for c in cells if not all(re.fullmatch(r":?-{2,}:?", x or "") for x in c)]
    if not cells:
        return ""
    n = max(len(c) for c in cells)
    width = r"L{\dimexpr(\linewidth-%d\tabcolsep)/%d\relax}" % (2 * (n - 1), n)
    spec = "|".join([width] * n)
    out = [r"\begin{center}\small\begin{longtable}{" + spec + "}", r"\toprule"]
    for index, row in enumerate(cells):
        row = row + [""] * (n - len(row))
        out.append(" & ".join(inline(c) for c in row) + r" \\")
        if index == 0:
            out.append(r"\midrule\endhead")
    out += [r"\bottomrule", r"\end{longtable}\end{center}"]
    return "\n".join(out)


def render_markdown(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            j = i + 1
            block = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                block.append(lines[j])
                j += 1
            out.append("{\\footnotesize\\begin{verbatim}\n" + "\n".join(block) + "\n\\end{verbatim}}")
            i = j + 1
            continue

        if is_table_row(line) and i + 1 < len(lines) and is_table_row(lines[i + 1]):
            block = []
            while i < len(lines) and is_table_row(lines[i]):
                block.append(lines[i])
                i += 1
            out.append(render_table(block))
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            cmd = {1: "section*", 2: "subsection*", 3: "subsubsection*"}.get(level, "paragraph*")
            out.append("\\" + cmd + "{" + inline(heading.group(2)) + "}")
            i += 1
            continue

        if stripped.startswith(("- ", "* ")):
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(lines[i].strip()[2:])
                i += 1
            out.append("\\begin{itemize}\\itemsep2pt")
            out += ["\\item " + inline(item) for item in items]
            out.append("\\end{itemize}")
            continue

        if re.match(r"^\d+\.\s", stripped):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            out.append("\\begin{enumerate}\\itemsep2pt")
            out += ["\\item " + inline(item) for item in items]
            out.append("\\end{enumerate}")
            continue

        if not stripped or stripped == "---":
            out.append("")
            i += 1
            continue

        paragraph = [stripped]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if (not nxt or nxt.startswith(("#", "|", "```", "- ", "* "))
                    or re.match(r"^\d+\.\s", nxt)):
                break
            paragraph.append(nxt)
            i += 1
        out.append(inline(" ".join(paragraph)) + "\n")

    return "\n".join(out)


def render_notebook(nb: dict) -> str:
    out: list[str] = []
    counter = 0
    fig_dir = BUILD / "figs"
    fig_dir.mkdir(parents=True, exist_ok=True)

    for cell in nb["cells"]:
        source = "".join(cell["source"])
        if cell["cell_type"] == "markdown":
            out.append(render_markdown(source))
            continue

        counter += 1
        out.append(r"\begin{flushleft}{\scriptsize\color{gray}In [" + str(counter) + r"]}\end{flushleft}")
        out.append("{\\footnotesize\\begin{verbatim}\n" + source.rstrip() + "\n\\end{verbatim}}")

        for index, output in enumerate(cell.get("outputs", [])):
            if output["output_type"] == "stream":
                text = "".join(output["text"]).rstrip()
                if text:
                    out.append("{\\footnotesize\\begin{verbatim}\n" + text + "\n\\end{verbatim}}")
            elif output["output_type"] == "display_data" and "image/png" in output.get("data", {}):
                path = fig_dir / f"cell{counter}_{index}.png"
                path.write_bytes(base64.b64decode(output["data"]["image/png"]))
                out.append(
                    r"\begin{center}\includegraphics[width=0.92\textwidth]{"
                    + str(path.relative_to(BUILD)).replace("\\", "/")
                    + r"}\end{center}"
                )
    return "\n".join(out)


PREAMBLE = r"""\documentclass[10pt,a4paper]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage[margin=2.2cm]{geometry}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{xcolor}
\usepackage{hyperref}
\usepackage{enumitem}
\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}
\setlength{\parindent}{0pt}
\setlength{\parskip}{4pt}
\hypersetup{colorlinks=true,linkcolor=blue!50!black,urlcolor=blue!50!black}
"""


def build(source: Path, title: str, subtitle: str) -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".ipynb":
        nb = json.loads(source.read_text(encoding="utf-8"))
        body = render_notebook(nb)
    else:
        body = render_markdown(source.read_text(encoding="utf-8"))

    tex = BUILD / (source.stem + ".tex")
    tex.write_text(
        PREAMBLE
        + "\\title{\\textbf{" + esc(title) + "}\\\\[4pt]\\large " + esc(subtitle) + "}\n"
        + "\\author{Wildfire monitoring, Team 3}\n\\date{}\n\\begin{document}\n\\maketitle\n"
        + body
        + "\n\\end{document}\n",
        encoding="utf-8",
    )

    for run in (1, 2):
        result = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex.name],
            cwd=BUILD, capture_output=True, text=True, errors="replace",
        )
        produced = (BUILD / (source.stem + ".pdf")).exists()
        if result.returncode != 0 and not produced:
            tail = (result.stdout or "")[-2500:]
            print(tail)
            raise SystemExit(f"pdflatex fallo en la pasada {run}")

    pdf = BUILD / (source.stem + ".pdf")
    target = source.with_suffix(".pdf")
    shutil.copyfile(pdf, target)
    print(f"escrito: {target.relative_to(ROOT)} ({target.stat().st_size // 1024} KB)")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--title", default=None)
    parser.add_argument("--subtitle", default="Workshop 1, Data Analysis Programming 2026-II")
    args = parser.parse_args()

    source = Path(args.source)
    if not source.is_absolute():
        source = ROOT / source

    if args.title:
        title = args.title
    elif source.suffix.lower() == ".ipynb":
        title = "Source profile notebook"
    else:
        title = "Canonical mapping table"

    build(source, title, args.subtitle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
