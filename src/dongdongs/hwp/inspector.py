"""HWP structure inventory through pyhwp's XML export.

Read-only and platform independent. It is used on macOS during development and
on Windows to check the result of ``apply`` against the original.
"""

from __future__ import annotations

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
    for i, table in enumerate(tables):
        body = table.find("TableBody")
        depth, container = enclosing(table)
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
                "cells": cells,
            }
        )

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
                "depth": depth,
                "container": container,
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
        "table_count": len(table_entries),
        "picture_count": len(pictures),
        "cell_count": sum(len(t["cells"]) for t in table_entries),
        "tables": table_entries,
        "pictures": pictures,
        "paragraphs": paragraphs,
    }


def tables_with_cell(inventory: dict, text: str) -> list[dict]:
    wanted = text.strip().casefold()
    return [t for t in inventory["tables"] if any(c["text"].strip().casefold() == wanted for c in t["cells"])]


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


def structure_signature(inventory: dict) -> dict:
    return {
        "table_count": inventory["table_count"],
        "picture_count": inventory["picture_count"],
        "tables": [[t["rows"], t["cols"], len(t["cells"])] for t in inventory["tables"]],
        "pictures": [[p["width"], p["height"]] for p in inventory["pictures"]],
    }
