"""HWP structure inventory through pyhwp's XML export.

Read-only and platform independent. It is used on macOS during development and
on Windows to check the result of ``apply`` against the original.
"""

from __future__ import annotations

import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_RUNNER = "import sys; from hwp5.hwp5proc import main; sys.argv = ['hwp5proc'] + sys.argv[1:]; sys.exit(main())"
_CONTROLS = {"TableControl", "GShapeObjectControl"}


def export_xml(hwp_path: Path, out_xml: Path) -> Path:
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    with out_xml.open("wb") as handle:
        proc = subprocess.run([sys.executable, "-c", _RUNNER, "xml", str(hwp_path)], stdout=handle, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"hwp5proc xml failed with exit code {proc.returncode}: {tail}")
    return out_xml


def _own_text(element) -> str:
    """Text of an element without descending into nested tables or pictures."""
    parts: list[str] = []

    def walk(node) -> None:
        for child in node:
            if child.tag in _CONTROLS:
                continue
            if child.tag == "Text":
                parts.append(child.text or "")
            walk(child)

    walk(element)
    return "".join(parts)


def build_inventory(xml_path: Path, source_name: str | None = None) -> dict:
    root = ET.parse(xml_path).getroot()
    parent = {child: node for node in root.iter() for child in node}
    tables = list(root.iter("TableControl"))
    table_index = {table: i for i, table in enumerate(tables)}

    def enclosing(element):
        node = parent.get(element)
        depth, first = 0, None
        while node is not None:
            if node.tag == "TableCell":
                control = parent[parent[parent[node]]]
                depth += 1
                if first is None:
                    first = {"table": table_index[control], "row": int(node.get("row")), "col": int(node.get("col"))}
            node = parent.get(node)
        return depth, first

    table_entries = []
    frame_of: dict[int, int] = {}
    page_no = 0
    for i, table in enumerate(tables):
        body = table.find("TableBody")
        depth, container = enclosing(table)
        if depth == 0:
            page_no += 1
            frame_of[i] = i
        else:
            frame_of[i] = frame_of[container["table"]]
        cells = []
        for row in body.findall("TableRow"):
            for cell in row.findall("TableCell"):
                cells.append(
                    {
                        "row": int(cell.get("row")),
                        "col": int(cell.get("col")),
                        "rowspan": int(cell.get("rowspan")),
                        "colspan": int(cell.get("colspan")),
                        "width": int(cell.get("width")),
                        "height": int(cell.get("height")),
                        "text": "\n".join(_own_text(p) for p in cell.findall("Paragraph")),
                    }
                )
        table_entries.append(
            {
                "index": i,
                "depth": depth,
                "container": container,
                "rows": int(body.get("rows")),
                "cols": int(body.get("cols")),
                "width": int(table.get("width")),
                "height": int(table.get("height")),
                "frame": frame_of[i],
                "page_no": page_no if depth == 0 else None,
                "cells": cells,
            }
        )
    page_of_frame = {t["index"]: t["page_no"] for t in table_entries if t["depth"] == 0}
    for entry in table_entries:
        entry["page_no"] = page_of_frame.get(entry["frame"])

    pictures = []
    for control in root.iter("GShapeObjectControl"):
        info = control.find(".//PictureInfo")
        if info is None:
            continue
        depth, container = enclosing(control)
        pictures.append(
            {
                "index": len(pictures),
                "bindata_id": int(info.get("bindata-id")),
                "width": int(control.get("width")),
                "height": int(control.get("height")),
                "treat_as_char": (control.get("treat-as-char") == "1") if control.get("treat-as-char") is not None else None,
                "flow": control.get("flow"),
                "depth": depth,
                "container": container,
                "page_no": page_of_frame.get(frame_of[container["table"]]) if container else None,
            }
        )

    paragraphs = []
    for para in root.iter("Paragraph"):
        text = _own_text(para)
        if text.strip():
            _, container = enclosing(para)
            paragraphs.append({"text": text, "container": container})

    return {
        "source": source_name or Path(xml_path).name,
        "page_count": page_no,
        "table_count": len(table_entries),
        "picture_count": len(pictures),
        "cell_count": sum(len(t["cells"]) for t in table_entries),
        "tables": table_entries,
        "pictures": pictures,
        "paragraphs": paragraphs,
    }


def _in_pages(table: dict, pages) -> bool:
    return pages is None or table.get("page_no") in pages


def tables_with_cell(inventory: dict, text: str, pages=None) -> list[dict]:
    """Tables with a cell whose whole text is ``text``; ``pages`` limits them to those page numbers."""
    wanted = text.strip().casefold()
    return [t for t in inventory["tables"] if _in_pages(t, pages) and any(c["text"].strip().casefold() == wanted for c in t["cells"])]


def test_sections(inventory: dict, heading_pattern: str = r"^(\d{1,3})\.\s+(\S.*)$", code_pattern: str = r"\(([A-Za-z][A-Za-z0-9_]*)\)\s*$") -> list[dict]:
    """Test sections of the report, from page cells whose first line reads ``N. name(code)``.

    Numbers must run on by one, so a stray numbered line in body text does not
    start a section. A section runs to the page before the next one starts; the
    last runs to the end of the document. Returns [] when the report has no such
    headings (then the whole document is one scope).
    """
    heading, code_re = re.compile(heading_pattern), re.compile(code_pattern)
    starts: list[dict] = []
    frames = sorted((t for t in inventory["tables"] if t.get("depth") == 0 and t.get("page_no")), key=lambda t: (t["page_no"], t["index"]))
    for table in frames:
        for cell in sorted(table["cells"], key=lambda c: (c["row"], c["col"])):
            first = next((line.strip() for line in cell["text"].split("\n") if line.strip()), "")
            match = heading.match(first)
            if not match:
                continue
            no = int(match.group(1))
            if starts and no != starts[-1]["no"] + 1:
                continue
            title = " ".join(match.group(2).split())
            code = code_re.search(title)
            starts.append(
                {
                    "no": no,
                    "title": title,
                    "name": title[: code.start()].strip() if code else title,
                    "code": code.group(1) if code else None,
                    "page_from": table["page_no"],
                    "table": table["index"],
                }
            )
    last_page = inventory.get("page_count") or max((t.get("page_no") or 0 for t in inventory["tables"]), default=0)
    for current, following in zip(starts, starts[1:]):
        current["page_to"] = max(current["page_from"], following["page_from"] - 1)
    if starts:
        starts[-1]["page_to"] = max(starts[-1]["page_from"], last_page)
    return starts


test_sections.__test__ = False


def occurrence_of(inventory: dict, text: str, table: int, row: int, col: int) -> int | None:
    """1-based order of ``text`` among all paragraphs, as a forward text search would meet it."""
    count = 0
    for para in inventory["paragraphs"]:
        hits = para["text"].count(text)
        if not hits:
            continue
        container = para["container"]
        if container == {"table": table, "row": row, "col": col}:
            return count + 1
        count += hits
    return None


def oscillogram_pages(inventory: dict, title_pattern: str = r"^Osc\. \S+$", pages=None) -> list[dict]:
    """Top-level page frames whose big cell holds a line matching ``title_pattern`` (the graph pages)."""
    pattern = re.compile(title_pattern)
    limit = pages
    pages = []
    for table in inventory["tables"]:
        if table["depth"] != 0 or not _in_pages(table, limit):
            continue
        for cell in table["cells"]:
            lines = [line.strip() for line in cell["text"].split("\n")]
            title = next((line for line in lines if pattern.match(line)), None)
            if title is None:
                continue
            pictures = [p for p in inventory["pictures"] if p["container"] == {"table": table["index"], "row": cell["row"], "col": cell["col"]}]
            pages.append(
                {
                    "table": table["index"],
                    "page_no": table["page_no"],
                    "row": cell["row"],
                    "col": cell["col"],
                    "title": title,
                    "cell_width": cell["width"],
                    "cell_height": cell["height"],
                    "pictures": [p["index"] for p in pictures],
                }
            )
            break
    return pages


def picture_slots(inventory: dict, header_text: str = "오실로그램", pages=None) -> list[dict]:
    """Picture-holding cells of the tables that carry ``header_text`` (the oscillogram tables), in document order.

    Each slot records the picture's size (the box a replacement must fit in), the
    nearest caption text in the same table and the table's header cell as anchor.
    """
    slots = []
    for table in inventory["tables"]:
        if not _in_pages(table, pages):
            continue
        header = next((c for c in table["cells"] if c["text"].strip().casefold() == header_text.strip().casefold()), None)
        if header is None:
            continue
        pictures = sorted(
            (p for p in inventory["pictures"] if p["container"] and p["container"]["table"] == table["index"]),
            key=lambda p: (p["container"]["row"], p["container"]["col"], p["index"]),
        )
        if not pictures:
            continue
        picture_cells = {(p["container"]["row"], p["container"]["col"]) for p in pictures}
        captions = [c for c in table["cells"] if c["text"].strip() and (c["row"], c["col"]) not in picture_cells and c is not header]
        occurrence = occurrence_of(inventory, header["text"], table["index"], header["row"], header["col"])
        for picture in pictures:
            row, col = picture["container"]["row"], picture["container"]["col"]
            near = sorted(captions, key=lambda c: (abs(c["row"] - row) + (0 if c["row"] == row else 0.5), abs(c["col"] - col)))
            slots.append(
                {
                    "table": table["index"],
                    "page_no": table.get("page_no"),
                    "row": row,
                    "col": col,
                    "picture_index": picture["index"],
                    "bindata_id": picture["bindata_id"],
                    "width": picture["width"],
                    "height": picture["height"],
                    "treat_as_char": picture.get("treat_as_char"),
                    "caption": near[0]["text"].strip() if near else None,
                    "anchor_text": header["text"],
                    "anchor_occurrence": occurrence,
                    "anchor_row": header["row"],
                    "anchor_col": header["col"],
                }
            )
    return slots


def structure_signature(inventory: dict) -> dict:
    return {
        "table_count": inventory["table_count"],
        "picture_count": inventory["picture_count"],
        "tables": [[t["rows"], t["cols"], len(t["cells"])] for t in inventory["tables"]],
        "pictures": [[p["width"], p["height"]] for p in inventory["pictures"]],
    }
