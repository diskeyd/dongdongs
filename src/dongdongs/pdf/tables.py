"""Rule-based table extraction from the PDF text layer.

Tables are found only where every cell is drawn as a filled rectangle framed by
hairline rectangles (how KERI reports draw them); a report that draws tables
with plain lines yields no tables, and ``extract`` warns about it. Cells are grouped into tables through shared edges, characters are
assigned to cells by their centre point, and text is kept as printed: no number
parsing, no translation, no unit normalisation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

EDGE_TOL = 1.0       # pt; edges closer than this are the same grid line
MIN_CELL = 3.0       # pt; thinner rectangles are border strokes
SCRIPT_RATIO = 0.8   # glyphs smaller than this share of the line size are sub/superscripts
BASELINE_TOL = 2.5   # pt; glyphs whose baselines differ less than this share a text line
SPACE_GAP = 0.2      # gap wider than this share of the font size reads as a space


@dataclass
class Cell:
    rect: pymupdf.Rect
    chars: list = field(default_factory=list)
    row: int = 0
    col: int = 0
    rowspan: int = 1
    colspan: int = 1


def rb(rect) -> list[float]:
    return [round(v, 2) for v in rect]


def _cell_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    seen: set = set()
    rects: list[pymupdf.Rect] = []
    for path in page.get_drawings():
        for item in path["items"]:
            if item[0] != "re":
                continue
            rect = pymupdf.Rect(item[1])
            if rect.width < MIN_CELL or rect.height < MIN_CELL:
                continue
            key = tuple(round(v * 2) for v in rect)
            if key not in seen:
                seen.add(key)
                rects.append(rect)
    # page frames and graph outlines that hold several rectangles are not cells
    return [r for r in rects if sum(1 for o in rects if o is not r and r.contains(o)) < 2]


def _touch(a: pymupdf.Rect, b: pymupdf.Rect) -> bool:
    x_overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
    y_overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
    if x_overlap > EDGE_TOL and (abs(a.y1 - b.y0) <= EDGE_TOL or abs(b.y1 - a.y0) <= EDGE_TOL):
        return True
    return y_overlap > EDGE_TOL and (abs(a.x1 - b.x0) <= EDGE_TOL or abs(b.x1 - a.x0) <= EDGE_TOL)


def _groups(rects: list[pymupdf.Rect]) -> list[list[pymupdf.Rect]]:
    parent = list(range(len(rects)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if _touch(rects[i], rects[j]):
                parent[find(i)] = find(j)
    buckets: dict[int, list[pymupdf.Rect]] = {}
    for i, rect in enumerate(rects):
        buckets.setdefault(find(i), []).append(rect)
    return [g for g in buckets.values() if len(g) >= 2]


def _grid_lines(values) -> list[float]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if clusters and value - clusters[-1][-1] <= EDGE_TOL:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [sum(c) / len(c) for c in clusters]


def _nearest(lines: list[float], value: float) -> int:
    return min(range(len(lines)), key=lambda i: abs(lines[i] - value))


def _page_chars(page: pymupdf.Page) -> list[dict]:
    raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_PRESERVE_LIGATURES)
    chars = []
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for ch in span["chars"]:
                    chars.append({"c": ch["c"], "bbox": ch["bbox"], "origin": ch["origin"], "size": span["size"]})
    return chars


def cell_text(chars: list[dict]) -> tuple[str, str, bool]:
    """Return (plain text, text with <sub>/<sup> markup, has_script) for one cell."""
    lines: list[list[dict]] = []
    for ch in sorted(chars, key=lambda c: c["origin"][1]):
        if lines and abs(ch["origin"][1] - lines[-1][0]["origin"][1]) <= BASELINE_TOL:
            lines[-1].append(ch)
        else:
            lines.append([ch])
    plain_lines, markup_lines, scripted = [], [], False
    for line in lines:
        line.sort(key=lambda c: c["bbox"][0])
        base = max(c["size"] for c in line)
        base_y = next(c["origin"][1] for c in line if c["size"] == base)
        plain, markup, mode, prev = [], [], None, None
        for ch in line:
            kind = None
            if ch["c"].strip() and ch["size"] < base * SCRIPT_RATIO:
                kind = "sup" if ch["origin"][1] < base_y - 1.0 else "sub"
            if prev is not None and ch["c"].strip() and prev["c"].strip() and kind is None and mode is None:
                if ch["bbox"][0] - prev["bbox"][2] > SPACE_GAP * base:
                    plain.append(" ")
                    markup.append(" ")
            if kind != mode:
                if mode:
                    markup.append(f"</{mode}>")
                if kind:
                    markup.append(f"<{kind}>")
                    scripted = True
                mode = kind
            plain.append(ch["c"])
            markup.append(ch["c"])
            prev = ch
        if mode:
            markup.append(f"</{mode}>")
        plain_text = " ".join("".join(plain).split())
        if plain_text:
            plain_lines.append(plain_text)
            markup_lines.append(" ".join("".join(markup).split()))
    return "\n".join(plain_lines), "\n".join(markup_lines), scripted


def _build_cells(group: list[pymupdf.Rect], chars: list[dict]) -> tuple[list[Cell], int, int]:
    xs = _grid_lines([v for r in group for v in (r.x0, r.x1)])
    ys = _grid_lines([v for r in group for v in (r.y0, r.y1)])
    cells = []
    for rect in group:
        cell = Cell(rect)
        cell.col, cell.row = _nearest(xs, rect.x0), _nearest(ys, rect.y0)
        cell.colspan = max(1, _nearest(xs, rect.x1) - cell.col)
        cell.rowspan = max(1, _nearest(ys, rect.y1) - cell.row)
        cells.append(cell)
    for ch in chars:
        x0, y0, x1, y1 = ch["bbox"]
        point = pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)
        for cell in cells:
            if cell.rect.contains(point):
                cell.chars.append(ch)
                break
    return cells, len(ys) - 1, len(xs) - 1


def extract_page(page: pymupdf.Page, known_sections: list[str], pdf_name: str) -> list[dict]:
    chars = _page_chars(page)
    page_no = page.number + 1
    page_count = page.parent.page_count
    tables = []
    for group in _groups(_cell_rects(page)):
        cells, nrows, ncols = _build_cells(group, chars)
        header = [c for c in cells if c.row == 0 and c.col == 0 and c.colspan == ncols]
        section = cell_text(header[0].chars)[0] if header else ""
        if not section:
            continue
        rows = []
        for r in range(1, nrows):
            row_cells = sorted((c for c in cells if c.row == r), key=lambda c: c.col)
            if not row_cells:
                continue
            texts = [cell_text(c.chars) for c in row_cells]
            entry: dict = {
                "row": r,
                "cells": [
                    {"col": c.col, "colspan": c.colspan, "rowspan": c.rowspan, "text": t[0], "markup": t[1], "bbox": rb(c.rect)}
                    for c, t in zip(row_cells, texts)
                ],
                "status": "review_required",
                "flags": [],
            }
            if ncols == 3 and len(row_cells) == 3 and all(c.colspan == 1 for c in row_cells):
                entry.update(label=texts[0][0], unit=texts[1][0], value=texts[2][0])
                if texts[0][2]:
                    entry["flags"].append("label_has_sub_or_superscript")
                    entry["label_markup"] = texts[0][1]
                if texts[1][2]:
                    entry["flags"].append("unit_has_sub_or_superscript")
                    entry["unit_markup"] = texts[1][1]
                if not texts[2][0]:
                    entry["flags"].append("empty_value")
            else:
                entry["flags"].append("irregular_row")
            rows.append(entry)
        tables.append(
            {
                "section": section,
                "known_section": section in known_sections,
                "source": {
                    "pdf": pdf_name,
                    "pdf_page": page_no,
                    "printed_page": f"{page_no} of {page_count}",
                    "printed_page_source": "derived from page index; the printed footer is vector paths",
                    "document_code": None,
                    "document_code_source": "not in the text layer; confirm in review or with --use-gemini",
                },
                "bbox": _union(group),
                "grid": {"rows": nrows, "cols": ncols},
                "rows": rows,
            }
        )
    tables.sort(key=lambda t: (t["bbox"][1], t["bbox"][0]))
    return tables


def _union(rects: list[pymupdf.Rect]) -> list[float]:
    total = pymupdf.Rect(rects[0])
    for rect in rects[1:]:
        total |= rect
    return rb(total)


def pages_with_sections(doc: pymupdf.Document, sections: list[str]) -> list[int]:
    return [p.number + 1 for p in doc if any(s in p.get_text() for s in sections)]


def extract_document(pdf_path: Path, known_sections: list[str], pages: list[int] | None = None) -> dict:
    with pymupdf.open(pdf_path) as doc:
        targets = pages or pages_with_sections(doc, known_sections)
        tables = []
        for page_no in targets:
            tables.extend(extract_page(doc[page_no - 1], known_sections, Path(pdf_path).name))
        return {"pdf": Path(pdf_path).name, "page_count": doc.page_count, "pages_scanned": targets, "tables": tables}
