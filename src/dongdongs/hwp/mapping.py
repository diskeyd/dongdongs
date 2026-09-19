"""Mapping candidates from the PDF extraction to HWP cells and pictures.

Every candidate is ``review_required``. Nothing reaches the HWP unless the
reviewer approves it in ``approved_changes.json``.

Table rules:
- the HWP section block is anchored by its header cell text in row 0;
- inside the block, label / unit / value are the three columns under the header;
- PDF rows update the HWP row with the same label, or fill an empty HWP row;
- HWP rows whose label is not in the PDF are cleared, structure is kept.
"""

from __future__ import annotations

import re
import unicodedata

from ..config.charmap import to_hwp_text
from ..pdf.sections import squash
from .inspector import occurrence_of, oscillogram_pages, picture_slots, tables_with_cell


_SPLIT = re.compile(r"^(?P<label>.*?\S)(?P<gap>[ \t]{2,})(?P<unit>\S(?:.*\S)?)$")


def norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def key(text: str) -> str:
    """Matching key: Unicode-compatible, case-folded, all whitespace removed."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).casefold()


def col_letters(col: int) -> str:
    letters = ""
    col += 1
    while col:
        col, rem = divmod(col - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def cell_address(row: int, col: int) -> str:
    return f"{col_letters(col)}{row + 1}"


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "-", text.casefold()).strip("-")


def section_tables(inventory: dict, sections: list[str]) -> list[dict]:
    wanted = {norm(s) for s in sections}
    return [t for t in inventory["tables"] if any(c["row"] == 0 and norm(c["text"]) in wanted for c in t["cells"])]


def section_blocks(table: dict, sections: list[str]) -> dict[str, dict]:
    canonical = {norm(s): s for s in sections}
    return {
        canonical[norm(c["text"])]: {"col": c["col"], "colspan": c["colspan"], "header_text": c["text"]}
        for c in table["cells"]
        if c["row"] == 0 and norm(c["text"]) in canonical
    }


def split_label_unit(text: str) -> tuple[str, str | None, str]:
    """'Impedance            Ω' -> ('Impedance', '            ', 'Ω'); no wide gap -> (text, None, '')."""
    match = _SPLIT.match(text or "")
    if match:
        return match.group("label"), match.group("gap"), match.group("unit")
    return (text or "").strip(), None, ""


def block_rows(table: dict, block: dict) -> list[dict]:
    """Resolve each body row of a section block to its label / unit / value cells.

    shape "separate": three cells under a 3-column header.
    shape "shared":   label and unit share one cell (2-column header, or a merged
                      label cell that also covers the unit column), value separate.
    shape None:       merged or missing cells; the row is never edited automatically.
    """
    by_row: dict[int, list[dict]] = {}
    for cell in table["cells"]:
        by_row.setdefault(cell["row"], []).append(cell)
    other_blocks = {
        col
        for c in by_row.get(0, [])
        if c["text"].strip() and c["col"] != block["col"]
        for col in range(c["col"], c["col"] + c["colspan"])
    }
    width = block["colspan"]
    label_col, value_col = block["col"], block["col"] + width - 1
    rows = []
    for r in range(1, table["rows"]):

        def covering(col: int, r: int = r):
            return next((c for c in by_row.get(r, []) if c["col"] <= col < c["col"] + c["colspan"]), None)

        label, value = covering(label_col), covering(value_col)
        unit = covering(label_col + 1) if width == 3 else None
        shape = None
        if (
            width in (2, 3)
            and label is not None
            and value is not None
            and label is not value
            and label["rowspan"] == 1
            and value["rowspan"] == 1
            and value["colspan"] == 1
            and not set(range(label["col"], label["col"] + label["colspan"])) & other_blocks
        ):
            if width == 3 and unit is not None and unit is not label and unit is not value and unit["rowspan"] == 1 and unit["colspan"] == 1:
                shape = "separate"
            elif width == 2 or unit is label:
                shape = "shared"
        if shape == "separate":
            label_text, gap, unit_text = label["text"], None, unit["text"]
        elif shape == "shared":
            label_text, gap, unit_text = split_label_unit(label["text"])
        else:
            label_text, gap, unit_text = "", None, ""
        rows.append(
            {
                "row": r,
                "shape": shape,
                "label": label,
                "unit": unit if shape == "separate" else None,
                "value": value,
                "label_text": label_text,
                "unit_text": unit_text,
                "gap": gap,
            }
        )
    return rows


def _labels_pdf(tables: list[dict], section: str) -> set[str]:
    return {key(r["label"]) for t in tables if t["section"] == section for r in t["rows"] if r.get("label")}


def _labels_hwp(table: dict, block: dict) -> set[str]:
    return {key(h["label_text"]) for h in block_rows(table, block) if h["shape"] and h["label_text"].strip()}


def pair_pages(pdf_tables: list[dict], hwp_tables: list[dict], sections: list[str]) -> list[dict]:
    pages = sorted({t["source"]["pdf_page"] for t in pdf_tables if t["known_section"]})
    by_page = {p: [t for t in pdf_tables if t["source"]["pdf_page"] == p] for p in pages}

    def score(page: int, table: dict) -> float:
        values = []
        for section, block in section_blocks(table, sections).items():
            a, b = _labels_pdf(by_page[page], section), _labels_hwp(table, block)
            if a or b:
                values.append(len(a & b) / len(a | b))
        return round(sum(values) / len(values), 3) if values else 0.0

    pairs = []
    if len(pages) == len(hwp_tables):
        for page, table in zip(pages, hwp_tables):
            pairs.append({"pdf_page": page, "hwp_table": table["index"], "method": "document_order", "label_similarity": score(page, table)})
        return pairs
    used: set[int] = set()
    for page in pages:
        ranked = sorted(((score(page, t), t["index"]) for t in hwp_tables if t["index"] not in used), reverse=True)
        if ranked:
            best, index = ranked[0]
            used.add(index)
            pairs.append({"pdf_page": page, "hwp_table": index, "method": "best_label_similarity", "label_similarity": best})
        else:
            pairs.append({"pdf_page": page, "hwp_table": None, "method": "unpaired", "label_similarity": 0.0})
    return pairs


def _difference_flags(before: str, after: str) -> list[str]:
    if before.strip() == after.strip():
        return []
    if squash(before) == squash(after):
        return ["whitespace_only_difference"]
    if squash(unicodedata.normalize("NFKC", before)) == squash(unicodedata.normalize("NFKC", after)):
        return ["unicode_lookalike_only"]
    if key(before) == key(after):
        return ["case_or_spacing_only"]
    return []


def _change(change_id, field, table, cell, after, anchor, source, flags, markup=None) -> dict:
    before = cell["text"]
    extracted = after
    after, applied = to_hwp_text(after)
    charmap_flags = [f"charmap_applied:{name}" for name in applied if name not in ("lookalike", "private_glyph_dropped")]
    if "lookalike" in applied:
        charmap_flags.append("charmap_lookalike")
    if "private_glyph_dropped" in applied:
        charmap_flags.append("private_glyph_dropped")
    return {
        "id": change_id,
        "kind": "set_cell_text",
        "field": field,
        "hwp": {"table": table["index"], "row": cell["row"], "col": cell["col"], "address": cell_address(cell["row"], cell["col"])},
        "anchor": anchor,
        "before": before,
        "after": after,
        "after_extracted": extracted,
        "after_markup": markup,
        "no_op": before.strip() == after.strip(),
        "source": source,
        "flags": list(flags) + charmap_flags + _difference_flags(before, after),
        "status": "review_required",
    }


def _union_bbox(*boxes) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _is_empty(h: dict) -> bool:
    cells = [h["label"], h["value"]] + ([h["unit"]] if h["unit"] else [])
    return not any(c["text"].strip() for c in cells)


def section_changes(pdf_table: dict, hwp_table: dict, block: dict, inventory: dict) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    page = pdf_table["source"]["pdf_page"]
    section = pdf_table["section"]
    if block["colspan"] not in (2, 3):
        return [], [f"p{page} {section}: HWP block spans {block['colspan']} columns; map it by hand"]
    anchor = {
        "text": block["header_text"],
        "occurrence": occurrence_of(inventory, block["header_text"], hwp_table["index"], 0, block["col"]),
        "address": cell_address(0, block["col"]),
    }
    rows = block_rows(hwp_table, block)
    usable = [h for h in rows if h["shape"]]
    pdf_rows = [r for r in pdf_table["rows"] if "label" in r]
    for r in pdf_table["rows"]:
        if "label" not in r:
            warnings.append(f"p{page} {section} row {r['row']}: irregular PDF row, map it by hand")

    assigned: dict[int, dict] = {}
    taken: set[int] = set()
    for pdf_row in pdf_rows:
        for h in usable:
            if h["row"] not in taken and key(h["label_text"]) == key(pdf_row["label"]):
                assigned[id(pdf_row)] = h
                taken.add(h["row"])
                break
    free = [h for h in usable if h["row"] not in taken and _is_empty(h)]
    leftovers = [h for h in usable if h["row"] not in taken and not _is_empty(h)]

    changes: list[dict] = []
    prefix = f"p{page}-{_slug(section)}"
    printed = pdf_table["source"].get("printed_page")
    for index, pdf_row in enumerate(pdf_rows):
        target = assigned.get(id(pdf_row))
        flags = list(pdf_row.get("flags", []))
        if target is None:
            pool = free or leftovers
            if not pool:
                warnings.append(f"p{page} {section}: no HWP row left for PDF row {pdf_row['row']}")
                continue
            target = pool.pop(0)
            taken.add(target["row"])
            flags.append("row_assigned_to_empty_or_unmatched_hwp_row")
        source = {"pdf_page": page, "printed_page": printed, "section": section, "pdf_row": pdf_row["row"], "row_bbox": _union_bbox(*(c["bbox"] for c in pdf_row["cells"]))}
        cells = pdf_row["cells"]
        if target["shape"] == "separate":
            specs = [
                ("label", target["label"], pdf_row["label"], pdf_row.get("label_markup"), cells[0]["bbox"], []),
                ("unit", target["unit"], pdf_row["unit"], pdf_row.get("unit_markup"), cells[1]["bbox"], []),
                ("value", target["value"], pdf_row["value"], None, cells[2]["bbox"], []),
            ]
        else:
            same = squash(target["label_text"]) == squash(pdf_row["label"]) and squash(target["unit_text"]) == squash(pdf_row["unit"])
            if same:
                combined, extra = target["label"]["text"], []
            else:
                flat = " ".join(pdf_row["label"].split())
                combined = flat + ((target["gap"] or "  ") + pdf_row["unit"] if pdf_row["unit"] else "")
                extra = ["label_and_unit_share_cell_reconstructed"]
            specs = [
                ("label+unit", target["label"], combined, pdf_row.get("label_markup"), _union_bbox(cells[0]["bbox"], cells[1]["bbox"]), extra),
                ("value", target["value"], pdf_row["value"], None, cells[2]["bbox"], []),
            ]
        for field, cell, value, markup, bbox, extra in specs:
            changes.append(_change(f"{prefix}-r{index + 1}-{field}", field, hwp_table, cell, value, anchor, {**source, "cell_bbox": bbox}, flags + extra, markup))

    for h in usable:
        if h["row"] in taken or _is_empty(h):
            continue
        source = {"pdf_page": page, "printed_page": printed, "section": section, "reason": "row is not in the PDF"}
        targets = [("label", h["label"]), ("unit", h["unit"]), ("value", h["value"])] if h["shape"] == "separate" else [("label+unit", h["label"]), ("value", h["value"])]
        for field, cell in targets:
            changes.append(_change(f"{prefix}-clear-hwp-r{h['row']}-{field}", field, hwp_table, cell, "", anchor, source, ["clear_not_in_pdf"]))
    for h in rows:
        if h["shape"] is None:
            if any(c is not None and c["text"].strip() for c in (h["label"], h["value"])):
                # cell text stays out of warnings: they end up in logs and the error-report zip
                warnings.append(f"p{page} {section}: HWP table {hwp_table['index']} row {h['row']} has merged or missing cells with text; not touched")
    return changes, warnings


def picture_changes(regions: list[dict], inventory: dict, watermark_pages: dict[int, str], anchor_text: str = "Circuit components", pages=None) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    diagrams = sorted((r for r in regions if r["kind"] == "circuit_diagram" and r.get("png")), key=lambda r: r["page"])
    tables = tables_with_cell(inventory, anchor_text, pages)
    if len(diagrams) != len(tables):
        warnings.append(f"{len(diagrams)} circuit diagrams in the PDF but {len(tables)} '{anchor_text}' tables in the HWP; pictures not paired")
        return [], warnings
    changes = []
    for region, table in zip(diagrams, tables):
        pictures = sorted(
            (p for p in inventory["pictures"] if p["container"] and p["container"]["table"] == table["index"]),
            key=lambda p: (p["container"]["row"], p["container"]["col"]),
        )
        if not pictures:
            warnings.append(f"HWP table {table['index']} has no picture for the p{region['page']} circuit diagram")
            continue
        picture = pictures[0]
        header = next(c for c in table["cells"] if norm(c["text"]) == norm(anchor_text))
        wm = watermark_pages.get(region["page"], "no_watermark")
        blocked = wm == "review_required"
        # the diagram takes the place of an existing picture: keep its width, change only the height
        fit = fit_picture(region["bbox"], hu_to_mm(picture["width"]), hu_to_mm(picture["height"]), mode="width")
        flags = ["watermark_manual_required"] if blocked else []
        if fit["height_squeezed"]:
            flags.append("picture_height_squeezed")
        changes.append(
            {
                "id": f"p{region['page']}-circuit-diagram",
                "kind": "replace_picture",
                "hwp": {
                    "table": table["index"],
                    "row": picture["container"]["row"],
                    "col": picture["container"]["col"],
                    "address": cell_address(picture["container"]["row"], picture["container"]["col"]),
                    "picture_index": picture["index"],
                    "bindata_id": picture["bindata_id"],
                    "size_hwpunit": [picture["width"], picture["height"]],
                    "treat_as_char": picture.get("treat_as_char"),
                },
                "target": fit,
                "anchor": {
                    "text": header["text"],
                    "occurrence": occurrence_of(inventory, header["text"], table["index"], header["row"], header["col"]),
                    "address": cell_address(header["row"], header["col"]),
                },
                "after_png": region["png"],
                "source": {"pdf_page": region["page"], "section": region.get("title"), "bbox": region["bbox"], "watermark_status": wm},
                "flags": flags,
                "status": "blocked" if blocked else "review_required",
                "no_op": False,
            }
        )
    return changes, warnings


HWPUNIT_PER_MM = 7200 / 25.4


def hu_to_mm(value: float) -> float:
    return round(value / HWPUNIT_PER_MM, 2)


def mm_to_hu(value: float) -> int:
    return int(round(value * HWPUNIT_PER_MM))


SIZE_TOLERANCE = 0.01  # 1 % of the planned size


def size_matches(expected: tuple[int, int], found: tuple[int, int], tolerance: float = SIZE_TOLERANCE) -> bool:
    return all(abs(e - f) <= max(1, e * tolerance) for e, f in zip(expected, found))


PT_PER_MM = 72 / 25.4


def natural_size_mm(bbox) -> tuple[float, float]:
    """Size of a PDF region drawn at the PDF's own scale (1 pt = 1/72 in)."""
    x0, y0, x1, y1 = bbox
    return (x1 - x0) / PT_PER_MM, (y1 - y0) / PT_PER_MM


def fit_picture(bbox, box_width_mm: float, box_height_mm: float, scale: float | None = None, mode: str = "ratio") -> dict:
    """Target size for a PDF region inside a ``box_width_mm`` x ``box_height_mm`` box.

    ``ratio`` keeps the PDF aspect ratio with one uniform ``scale`` (the largest
    that fits, unless given) — graph pages, where several pictures share a page.
    ``width`` keeps the box width so the report layout does not move and changes
    only the height — a picture that replaces an existing one in its own box
    (circuit diagram, oscillogram slot). A picture too tall for its box is then
    squeezed vertically, which ``height_squeezed`` reports.
    """
    natural_w, natural_h = natural_size_mm(bbox)
    squeezed = False
    if mode == "width" and natural_w and natural_h:
        width = box_width_mm
        height = natural_h * (box_width_mm / natural_w)
        if box_height_mm and height > box_height_mm:
            height, squeezed = box_height_mm, True
        scale = width / natural_w
    else:
        if scale is None:
            scale = min(box_width_mm / natural_w, box_height_mm / natural_h) if natural_w and natural_h else 1.0
        width, height = natural_w * scale, natural_h * scale
    return {
        "width_mm": round(width, 2),
        "height_mm": round(height, 2),
        "natural_width_mm": round(natural_w, 2),
        "natural_height_mm": round(natural_h, 2),
        "mode": mode,
        "height_squeezed": squeezed,
        "scale": round(scale, 3),
        "fill_ratio": round((width * height) / (box_width_mm * box_height_mm), 3) if box_width_mm and box_height_mm else None,
        "width_hwpunit": mm_to_hu(width),
        "height_hwpunit": mm_to_hu(height),
    }


SMALL_FILL_RATIO = 0.5


def _graph_rows(regions: list[dict]) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for region in sorted(regions, key=lambda r: (r["bbox"][1], r["bbox"][0])):
        if region.get("layout") == "half-right" and rows and rows[-1][0].get("layout") == "half-left" and len(rows[-1]) == 1:
            rows[-1].append(region)
        else:
            rows.append([region])
    return rows


def plan_oscillogram_pages(regions: list[dict], inventory: dict, cfg: dict, watermark_pages: dict[int, str] | None = None, pages=None) -> tuple[list[dict], list[str]]:
    """One candidate per PDF graph page: the HWP page to fill, the title and every graph's target size."""
    cfg = cfg or {}
    watermark_pages = watermark_pages or {}
    title_pattern = re.compile(cfg.get("title_pattern", r"^Osc\. \S+$"))
    by_page: dict[int, list[dict]] = {}
    for region in regions:
        if region["kind"] == "oscillogram" and region.get("png"):
            by_page.setdefault(region["page"], []).append(region)
    # only PDF pages titled like a graph page; the rest may belong to oscillogram slot tables
    pdf_pages = sorted(p for p, group in by_page.items() if any(title_pattern.match(r.get("title") or "") for r in group))
    hwp_pages = sorted(oscillogram_pages(inventory, title_pattern.pattern, pages=pages), key=lambda p: p["page_no"])
    warnings: list[str] = []
    odd_titles = [p for p, group in by_page.items() if p not in pdf_pages and any(r.get("title") for r in group)]
    if odd_titles:
        warnings.append(f"{len(odd_titles)} PDF pages have graph titles that do not match the graph-page title pattern ({title_pattern.pattern}); they are offered to oscillogram tables or left unmapped")
    if not pdf_pages:
        return [], warnings
    template = None
    if not hwp_pages:
        if pages is None:
            return [], [f"{len(pdf_pages)} graph pages in the PDF but no page with an 'Osc.' title in the HWP; graph pages not planned"]
        # the section has no graph page to fill or copy: plan with another section's page as size model, blocked
        template = next(iter(sorted(oscillogram_pages(inventory, title_pattern.pattern), key=lambda p: p["page_no"])), None)
        if template is None:
            return [], [f"{len(pdf_pages)} graph pages in the PDF but no page with an 'Osc.' title anywhere in the HWP; graph pages not planned"]
        warnings.append(
            f"{len(pdf_pages)} graph pages in the PDF but this section has no 'Osc.' page in the HWP; "
            "copy one 'Osc.' page to the end of the section in Hancom and run again (candidates blocked)"
        )
    elif len(pdf_pages) > len(hwp_pages):
        warnings.append(f"{len(pdf_pages)} graph pages in the PDF, {len(hwp_pages)} in the HWP: {len(pdf_pages) - len(hwp_pages)} pages will be added by copying the last graph page of the section")
    elif len(pdf_pages) < len(hwp_pages):
        warnings.append(f"{len(pdf_pages)} graph pages in the PDF, {len(hwp_pages)} in the HWP: the last {len(hwp_pages) - len(pdf_pages)} HWP graph pages keep their old content")
    padding_width = float(cfg.get("padding_width_mm", 3.6))
    gap = float(cfg.get("gap_mm", 1.5))
    reserved = float(cfg.get("reserved_height_mm", 14.0)) + float(cfg.get("padding_height_mm", 1.0))
    changes = []
    last = hwp_pages[-1] if hwp_pages else template
    anchor_page = max(pages) if template else last["page_no"]
    # two graph pages with the same title: the editor groups copies and finds anchors by title, so it could edit the wrong one
    titles = [p["title"] for p in oscillogram_pages(inventory, title_pattern.pattern)]
    duplicated = {t for t in titles if titles.count(t) > 1}
    if duplicated:
        warnings.append(
            f"graph pages share the titles {sorted(duplicated)} in the HWP, so they cannot be told apart; "
            "give each graph page a unique title in Hancom and run again (candidates blocked)"
        )
    crowded = sorted({p["page_no"] for p in hwp_pages if p.get("other_lines")})
    if crowded:
        warnings.append(f"HWP graph pages {crowded} hold text besides the title, which filling would erase (candidates blocked)")
    for index, page in enumerate(pdf_pages):
        page_regions = by_page[page]
        title = next((r["title"] for r in page_regions if r.get("title")), None)
        if index < len(hwp_pages):
            target, added = hwp_pages[index], 0
        else:
            target, added = last, index - len(hwp_pages) + 1
        # the graphs fit the page cell's own inner width, whatever the report's page layout
        inner = hu_to_mm(target["cell_width"]) - padding_width
        available = hu_to_mm(target["cell_height"]) - reserved
        rows = _graph_rows(page_regions)
        row_height = available / len(rows)
        # one scale for the whole page so the layout stays exactly the PDF's
        page_scale = 1.0
        for row in rows:
            widths = [natural_size_mm(r["bbox"])[0] for r in row]
            heights = [natural_size_mm(r["bbox"])[1] for r in row]
            page_scale = min(page_scale, (inner - gap * (len(row) - 1)) / sum(widths), row_height / max(heights))
        pictures = []
        for row in rows:
            for region in row:
                fit = fit_picture(region["bbox"], inner if len(row) == 1 else (inner - gap) / 2, row_height, scale=page_scale)
                pictures.append({"png": region["png"], "pdf_index": region["index"], "layout": region.get("layout", "full"), "bbox": region["bbox"], **fit})
        wm = watermark_pages.get(page, "no_watermark")
        flags = []
        if added:
            flags.append("page_to_be_added")
        if template is not None:
            flags.append("no_graph_page_in_section")
        elif target["title"] in duplicated:
            flags.append("anchor_text_not_unique")
        if template is None and target.get("other_lines"):
            flags.append("cell_has_other_text")
        if page_scale < SMALL_FILL_RATIO:
            flags.append("picture_small_in_box")
        if title is None:
            flags.append("pdf_title_missing")
        if wm == "review_required":
            flags.append("watermark_manual_required")
        changes.append(
            {
                "id": f"p{page}-graph-page",
                "kind": "fill_oscillogram_page",
                "hwp": {
                    "table": None if template is not None else target["table"],
                    "page_no": (anchor_page if added else target["page_no"]) + added,
                    "page_no_before": anchor_page if added else target["page_no"],
                    "anchor_page": anchor_page if added else None,
                    "row": target["row"],
                    "col": target["col"],
                    "address": cell_address(target["row"], target["col"]),
                    "existing_title": target["title"],
                    "existing_pictures": len(target["pictures"]),
                    "page_to_be_added": bool(added),
                    "copies_after_anchor": added,
                    "cell_inner_width_mm": round(inner, 2),
                    "available_height_mm": round(available, 2),
                    "page_scale": round(page_scale, 3),
                },
                "anchor": {
                    "text": target["title"],
                    "occurrence": occurrence_of(inventory, target["title"], target["table"], target["row"], target["col"]),
                    "address": cell_address(target["row"], target["col"]),
                },
                "before": target["title"] if not added else "",
                "after": title or "",
                "after_extracted": title or "",
                "after_markup": None,
                "pictures": pictures,
                "source": {"pdf_page": page, "title": title, "graphs": len(page_regions), "rows": len(rows), "watermark_status": wm},
                "flags": flags,
                "status": "blocked" if wm == "review_required" or template is not None or {"anchor_text_not_unique", "cell_has_other_text"} & set(flags) else "review_required",
                # the page already carries this title and as many pictures as planned: applied before
                "no_op": not added and template is None and norm(target["title"]) == norm(title or "") and len(target["pictures"]) == len(pictures),
            }
        )
    return changes, warnings


def anchor_page_of(change: dict) -> int:
    hwp = change["hwp"]
    return hwp.get("anchor_page") or (hwp.get("page_no", 0) - (hwp.get("copies_after_anchor") or 1))


def graph_page_positions(changes: list[dict], copies: dict[int, int] | None = None) -> tuple[dict[str, int], dict[int, int]]:
    """Page number of each graph-page change in the document after apply, and copies per anchor page.

    Copies are inserted right after their section's last graph page, so every
    later page moves down by the copies made before it. Copies of one anchor
    are filled in ``copies_after_anchor`` order. ``copies`` (anchor page ->
    count, from the apply log) overrides the count derived from ``changes``.
    """
    groups: dict[int, list[dict]] = {}
    for change in changes:
        if change.get("kind") == "fill_oscillogram_page" and change["hwp"].get("page_to_be_added") and change.get("status") != "blocked":
            groups.setdefault(anchor_page_of(change), []).append(change)
    counts = dict(copies) if copies is not None else {page: len(group) for page, group in groups.items()}

    def shift(page: int) -> int:
        return sum(n for anchor, n in counts.items() if anchor < page)

    positions: dict[str, int] = {}
    for anchor, group in groups.items():
        for rank, change in enumerate(sorted(group, key=lambda c: c["hwp"].get("copies_after_anchor") or 0), start=1):
            positions[change["id"]] = anchor + rank + shift(anchor)
    for change in changes:
        if change.get("kind") == "fill_oscillogram_page" and not change["hwp"].get("page_to_be_added") and change.get("status") != "blocked":
            before = change["hwp"].get("page_no_before") or change["hwp"]["page_no"]
            positions[change["id"]] = before + shift(before)
    return positions, counts


def plan_picture_slots(regions: list[dict], slots: list[dict], watermark_pages: dict[int, str], used_pngs: set[str]) -> tuple[list[dict], list[str]]:
    """Pair the oscillograms that no graph page took with the picture cells of the HWP oscillogram tables.

    The pairing is by document order on both sides (no PDF with these tables has
    been seen yet, so every candidate is flagged ``slot_paired_by_order``).
    """
    leftover = sorted((r for r in regions if r["kind"] == "oscillogram" and r.get("png") and r["png"] not in used_pngs), key=lambda r: (r["page"], r["index"]))
    warnings = [f"HWP 오실로그램 칸 {len(slots)}개, PDF 미배정 그래프 {len(leftover)}장"] if slots or leftover else []
    changes = []
    for region, slot in zip(leftover, slots):
        wm = watermark_pages.get(region["page"], "no_watermark")
        blocked = wm == "review_required"
        fit = fit_picture(region["bbox"], hu_to_mm(slot["width"]), hu_to_mm(slot["height"]), mode="width")
        flags = ["slot_paired_by_order"] + (["watermark_manual_required"] if blocked else [])
        if fit["height_squeezed"]:
            flags.append("picture_height_squeezed")
        changes.append(
            {
                "id": f"p{region['page']}-{region['index']}-slot-t{slot['table']}-{slot['row']}-{slot['col']}",
                "kind": "replace_picture",
                "hwp": {
                    "table": slot["table"],
                    "row": slot["row"],
                    "col": slot["col"],
                    "address": cell_address(slot["row"], slot["col"]),
                    "page_no": slot.get("page_no"),
                    "picture_index": slot["picture_index"],
                    "bindata_id": slot["bindata_id"],
                    "size_hwpunit": [slot["width"], slot["height"]],
                    "treat_as_char": slot.get("treat_as_char"),
                    "caption": slot.get("caption"),
                },
                "target": fit,
                "anchor": {"text": slot["anchor_text"], "occurrence": slot["anchor_occurrence"], "address": cell_address(slot["anchor_row"], slot["anchor_col"])},
                "after_png": region["png"],
                "source": {"pdf_page": region["page"], "section": region.get("title"), "bbox": region["bbox"], "watermark_status": wm},
                "flags": flags,
                "status": "blocked" if blocked else "review_required",
                "no_op": False,
            }
        )
    if len(leftover) > len(slots):
        warnings.append(f"{len(leftover) - len(slots)} leftover oscillograms have no HWP slot")
    return changes, warnings


def pair_sections(pdf_sections: list[dict], hwp_sections: list[dict]) -> tuple[list[dict], list[str]]:
    """Pair the tests of one PDF with report sections: same code first, then the same name."""
    pairs, warnings, used = [], [], set()
    names = [key(h["name"]) for h in hwp_sections]
    repeated = sorted({h["no"] for h in hwp_sections if names.count(key(h["name"])) > 1})
    if repeated and any(not t.get("code") for t in pdf_sections):
        warnings.append(f"report sections {repeated} share a name; tests without a code are paired with them in document order, check the pairing")
    for test in pdf_sections:
        match, method = None, None
        if test.get("code"):
            match = next((h for h in hwp_sections if h["no"] not in used and h.get("code") and key(h["code"]) == key(test["code"])), None)
            method = "code" if match else None
        if match is None:
            match = next((h for h in hwp_sections if h["no"] not in used and key(h["name"]) == key(test["name"])), None)
            method = "name" if match else None
        if match is None:
            warnings.append(f"PDF test {test['title']!r} (p{test['page_from']}-{test['page_to']}) has no report section with the same code or name; not mapped")
            continue
        used.add(match["no"])
        pairs.append({"pdf": test, "hwp": match, "method": method})
    return pairs, warnings


def _range(section: dict) -> list[int]:
    return [section["page_from"], section["page_to"]]


def _page_set(ranges) -> set[int] | None:
    if ranges is None:
        return None
    return {page for a, b in ranges for page in range(a, b + 1)}


def resolve_scopes(pdf_index: dict | None, hwp_sections: list[dict], manual: list[int] | None = None) -> tuple[list[dict], list[str], str]:
    """Which PDF pages go to which report pages.

    ``auto``: the PDF lists its tests and they pair with report sections.
    ``user``: the reviewer named the report sections (other institutions).
    ``whole``: no section information; the whole PDF against the whole report.
    """
    pdf_sections = (pdf_index or {}).get("sections") or []
    warnings: list[str] = []
    if manual:
        by_no = {h["no"]: h for h in hwp_sections}
        if pdf_sections:
            # the PDF lists its tests: one report section per test, in the PDF's order (0 = leave that test out)
            if len(manual) != len(pdf_sections):
                return [], [f"the PDF lists {len(pdf_sections)} tests but {len(manual)} report section numbers were given; give one number per test in the PDF's order (0 leaves a test out)"], "user"
            missing = sorted({n for n in manual if n and n not in by_no})
            repeated = sorted({n for n in manual if n and manual.count(n) > 1})
            if missing or repeated:
                problems = ([f"sections {missing} do not exist"] if missing else []) + ([f"sections {repeated} were given twice"] if repeated else [])
                return [], ["; ".join(problems) + "; nothing mapped"], "user"
            scopes = [
                {"key": f"s{n}", "method": "user_order", "no": n, "code": by_no[n].get("code"), "title": by_no[n]["title"], "pdf_title": t["title"], "pdf_ranges": [_range(t)], "hwp_ranges": [_range(by_no[n])]}
                for t, n in zip(pdf_sections, manual)
                if n
            ]
            return (scopes, warnings, "user") if scopes else ([], ["every test was left out; nothing mapped"], "user")
        chosen = [h for h in hwp_sections if h["no"] in manual]
        missing = sorted(set(manual) - {h["no"] for h in chosen} - {0})
        if missing:
            warnings.append(f"report sections {missing} do not exist; ignored")
        if not chosen:
            return [], warnings + ["no report section chosen; nothing mapped"], "user"
        scope = {
            "key": "s" + "-".join(str(h["no"]) for h in chosen),
            "method": "user",
            "no": ",".join(str(h["no"]) for h in chosen),
            "code": None,
            "title": " / ".join(h["title"] for h in chosen),
            "pdf_ranges": None,
            "hwp_ranges": [_range(h) for h in chosen],
        }
        return [scope], warnings, "user"
    if pdf_sections and hwp_sections:
        pairs, warnings = pair_sections(pdf_sections, hwp_sections)
        scopes = [
            {"key": f"s{p['hwp']['no']}", "method": p["method"], "no": p["hwp"]["no"], "code": p["hwp"].get("code"), "title": p["hwp"]["title"], "pdf_title": p["pdf"]["title"], "pdf_ranges": [_range(p["pdf"])], "hwp_ranges": [_range(p["hwp"])]}
            for p in pairs
        ]
        return scopes, warnings, "auto"
    if hwp_sections:
        warnings.append(
            f"the report has {len(hwp_sections)} test sections but the PDF test list was not found; the whole PDF was mapped against the whole report. "
            "If this test report fills only some sections, choose them (--sections)"
        )
    elif pdf_sections:
        warnings.append(
            f"the PDF lists {len(pdf_sections)} tests but no 'N. name(code)' section headings were found in the report; the whole PDF was mapped against the whole report"
        )
    whole = {"key": "all", "method": "whole", "no": None, "code": None, "title": "문서 전체", "pdf_ranges": None, "hwp_ranges": None}
    return [whole], warnings, "whole"


def _table_candidates(pdf_tables: list[dict], hwp_tables: list[dict], inventory: dict, sections: list[str], watermark_pages: dict[int, str]) -> tuple[list[dict], list[dict], list[str]]:
    pairs = pair_pages(pdf_tables, hwp_tables, sections)
    table_by_index = {t["index"]: t for t in inventory["tables"]}
    changes: list[dict] = []
    warnings: list[str] = []
    for pair in pairs:
        if pair["hwp_table"] is None:
            warnings.append(f"p{pair['pdf_page']}: no HWP table paired")
            continue
        hwp_table = table_by_index[pair["hwp_table"]]
        blocks = section_blocks(hwp_table, sections)
        if pair["label_similarity"] < 0.5:
            warnings.append(f"p{pair['pdf_page']} -> HWP table {pair['hwp_table']}: label similarity {pair['label_similarity']} is low; check the pairing")
        for pdf_table in (t for t in pdf_tables if t["source"]["pdf_page"] == pair["pdf_page"]):
            block = blocks.get(pdf_table["section"])
            if block is None:
                warnings.append(f"p{pair['pdf_page']} {pdf_table['section']}: HWP table {pair['hwp_table']} has no such section")
                continue
            got, notes = section_changes(pdf_table, hwp_table, block, inventory)
            for change in got:
                if watermark_pages.get(pair["pdf_page"]) == "review_required":
                    change["flags"].append("watermark_manual_required_on_source_page")
            changes.extend(got)
            warnings.extend(notes)
        for section, block in blocks.items():
            if not any(t["section"] == section and t["source"]["pdf_page"] == pair["pdf_page"] for t in pdf_tables):
                page_tables = [t for t in pdf_tables if t["source"]["pdf_page"] == pair["pdf_page"]]
                printed = page_tables[0]["source"]["printed_page"] if page_tables else None
                absent = {"section": section, "known_section": True, "source": {"pdf_page": pair["pdf_page"], "printed_page": printed}, "rows": []}
                got, notes = section_changes(absent, hwp_table, block, inventory)
                for change in got:
                    change["flags"].append("section_not_in_pdf")
                changes.extend(got)
                warnings.extend(notes)
                warnings.append(f"p{pair['pdf_page']}: section {section!r} is in HWP table {pair['hwp_table']} but not on the PDF page; clearing candidates proposed")
    return pairs, changes, warnings


def build_candidates(
    extracted: dict,
    regions: list[dict],
    inventory: dict,
    sections: list[str],
    watermark_pages: dict[int, str],
    pictures_cfg: dict | None = None,
    pdf_index: dict | None = None,
    hwp_sections: list[dict] | None = None,
    manual_sections: list[int] | None = None,
) -> dict:
    """Candidates for one PDF, matched section by section.

    ``sections`` are the known table section names (Supply circuit, ...);
    ``pdf_index`` / ``hwp_sections`` are the test sections of the PDF and of the
    report. Report sections this PDF does not cover are never touched.
    """
    pictures_cfg = pictures_cfg or {}
    hwp_sections = hwp_sections or []
    scopes, warnings, mode = resolve_scopes(pdf_index, hwp_sections, manual_sections)
    all_pdf_tables = [t for t in extracted["tables"] if t["known_section"]]
    all_hwp_tables = section_tables(inventory, sections)
    pairs: list[dict] = []
    changes: list[dict] = []
    used_pngs: set[str] = set()
    for scope in scopes:
        pdf_pages, hwp_pages = _page_set(scope["pdf_ranges"]), _page_set(scope["hwp_ranges"])
        label = f"[{scope['no']}. {scope['title']}] " if scope["no"] is not None else ""
        tag = {k: scope[k] for k in ("key", "method", "no", "code", "title", "pdf_ranges", "hwp_ranges")}
        scope_regions = [r for r in regions if pdf_pages is None or r["page"] in pdf_pages]
        pdf_tables = [t for t in all_pdf_tables if pdf_pages is None or t["source"]["pdf_page"] in pdf_pages]
        hwp_tables = [t for t in all_hwp_tables if hwp_pages is None or t.get("page_no") in hwp_pages]
        found: list[dict] = []
        notes: list[str] = []
        if pdf_tables:
            got_pairs, got, got_notes = _table_candidates(pdf_tables, hwp_tables, inventory, sections, watermark_pages)
            pairs.extend({**pair, "section": scope["key"]} for pair in got_pairs)
            found += got
            notes += got_notes
        got, got_notes = picture_changes(scope_regions, inventory, watermark_pages, pictures_cfg.get("circuit_anchor", "Circuit components"), hwp_pages)
        found += got
        notes += got_notes
        planned_pages, got_notes = plan_oscillogram_pages(scope_regions, inventory, pictures_cfg.get("oscillogram_page", {}), watermark_pages, hwp_pages)
        found += planned_pages
        notes += got_notes
        scope_used = {pic["png"] for change in planned_pages for pic in change["pictures"]} | {c["after_png"] for c in found if c.get("after_png")}
        slots = picture_slots(inventory, pictures_cfg.get("oscillogram_slots", {}).get("header_text", "오실로그램"), hwp_pages)
        got, got_notes = plan_picture_slots(scope_regions, slots, watermark_pages, scope_used)
        found += got
        notes += got_notes
        for change in found:
            change["section"] = tag
        used_pngs |= scope_used | {c["after_png"] for c in got}
        changes += found
        warnings += [label + note for note in notes]
    positions, _ = graph_page_positions(changes)
    for change in changes:
        if change["kind"] == "fill_oscillogram_page":
            change["hwp"]["page_no_after"] = positions.get(change["id"])
            if change["id"] in positions:
                change["hwp"]["page_no"] = positions[change["id"]]
    covered = _page_set([r for scope in scopes for r in (scope["pdf_ranges"] or [])]) if all(s["pdf_ranges"] is not None for s in scopes) else None
    unmapped = [r for r in regions if r.get("export") and r.get("png") and r["png"] not in used_pngs]
    touched = {s["no"] for s in scopes if isinstance(s["no"], int)}
    for scope in scopes:
        if isinstance(scope["no"], str):
            touched |= {int(n) for n in scope["no"].split(",")}
    return {
        "mode": mode,
        "scopes": scopes,
        "hwp_sections": [{k: h[k] for k in ("no", "title", "code", "page_from", "page_to")} for h in hwp_sections],
        # without sections the whole report is in play, so no section can be said to be left alone
        "pending_sections": [] if mode == "whole" else [h["no"] for h in hwp_sections if h["no"] not in touched],
        "pdf_index": {k: v for k, v in (pdf_index or {}).items() if k != "sections"} | {"tests": len((pdf_index or {}).get("sections") or [])},
        "pairs": pairs,
        "changes": changes,
        "warnings": warnings,
        "unmapped_regions": [
            {
                "page": r["page"],
                "index": r["index"],
                "kind": r["kind"],
                "title": r.get("title"),
                "png": r.get("png"),
                "reason": "outside_matched_sections" if covered is not None and r["page"] not in covered else "not_matched",
            }
            for r in unmapped
        ],
    }
