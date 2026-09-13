"""Mapping candidates from the PDF extraction to HWP cells and pictures.

Every candidate is ``review_required``. Nothing reaches the HWP unless the
reviewer approves it in ``approved_changes.json``.

Table rules (handoff section 7):
- the HWP section block is anchored by its header cell text in row 0;
- inside the block, label / unit / value are the three columns under the header;
- PDF rows update the HWP row with the same label, or fill an empty HWP row;
- HWP rows whose label is not in the PDF are cleared, structure is kept.
"""

from __future__ import annotations

import re
import unicodedata

from ..config.charmap import to_hwp_text
from .inspector import occurrence_of, oscillogram_pages, picture_slots, tables_with_cell


_SPLIT = re.compile(r"^(?P<label>.*?\S)(?P<gap>[ \t]{2,})(?P<unit>\S(?:.*\S)?)$")


def norm(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def key(text: str) -> str:
    """Matching key: Unicode-compatible, case-folded, all whitespace removed."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).casefold()


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


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
    if _squash(before) == _squash(after):
        return ["whitespace_only_difference"]
    if _squash(unicodedata.normalize("NFKC", before)) == _squash(unicodedata.normalize("NFKC", after)):
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
                warnings.append(f"p{page} {section}: no HWP row left for PDF row {pdf_row['label']!r}")
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
            same = _squash(target["label_text"]) == _squash(pdf_row["label"]) and _squash(target["unit_text"]) == _squash(pdf_row["unit"])
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
            texts = [c["text"] for c in (h["label"], h["value"]) if c is not None and c["text"].strip()]
            if texts:
                warnings.append(f"p{page} {section}: HWP row {h['row']} has merged or missing cells with text {texts!r}; not touched")
    return changes, warnings


def picture_changes(regions: list[dict], inventory: dict, watermark_pages: dict[int, str], anchor_text: str = "Circuit components") -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    diagrams = sorted((r for r in regions if r["kind"] == "circuit_diagram" and r.get("png")), key=lambda r: r["page"])
    tables = tables_with_cell(inventory, anchor_text)
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
        fit = fit_picture(region["bbox"], hu_to_mm(picture["width"]), hu_to_mm(picture["height"]))
        flags = ["watermark_manual_required"] if blocked else []
        if fit["fill_ratio"] is not None and fit["fill_ratio"] < SMALL_FILL_RATIO:
            flags.append("picture_small_in_box")
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


PT_PER_MM = 72 / 25.4


def natural_size_mm(bbox) -> tuple[float, float]:
    """Size of a PDF region drawn at the PDF's own scale (1 pt = 1/72 in)."""
    x0, y0, x1, y1 = bbox
    return (x1 - x0) / PT_PER_MM, (y1 - y0) / PT_PER_MM


def fit_picture(bbox, box_width_mm: float, box_height_mm: float, scale: float | None = None) -> dict:
    """Target size for a PDF region inside a ``box_width_mm`` x ``box_height_mm`` box.

    The PDF aspect ratio is kept: one uniform ``scale`` (the largest that fits the
    box, unless given) is applied to both sides. ``fill_ratio`` tells the reviewer
    how much of the box the picture covers.
    """
    natural_w, natural_h = natural_size_mm(bbox)
    if scale is None:
        scale = min(box_width_mm / natural_w, box_height_mm / natural_h) if natural_w and natural_h else 1.0
    width, height = natural_w * scale, natural_h * scale
    return {
        "width_mm": round(width, 2),
        "height_mm": round(height, 2),
        "natural_width_mm": round(natural_w, 2),
        "natural_height_mm": round(natural_h, 2),
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


def plan_oscillogram_pages(regions: list[dict], inventory: dict, cfg: dict, watermark_pages: dict[int, str] | None = None) -> tuple[list[dict], list[str]]:
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
    hwp_pages = sorted(oscillogram_pages(inventory, title_pattern.pattern), key=lambda p: p["page_no"])
    warnings: list[str] = []
    if not pdf_pages:
        return [], warnings
    if not hwp_pages:
        return [], [f"{len(pdf_pages)} graph pages in the PDF but no page with an 'Osc.' title in the HWP; graph pages not planned"]
    if len(pdf_pages) > len(hwp_pages):
        warnings.append(f"{len(pdf_pages)} graph pages in the PDF, {len(hwp_pages)} in the HWP: {len(pdf_pages) - len(hwp_pages)} pages will be added by copying the last graph page")
    elif len(pdf_pages) < len(hwp_pages):
        warnings.append(f"{len(pdf_pages)} graph pages in the PDF, {len(hwp_pages)} in the HWP: the last {len(hwp_pages) - len(pdf_pages)} HWP graph pages keep their old content")
    inner = float(cfg.get("inner_width_mm", 168.8))
    gap = float(cfg.get("gap_mm", 1.5))
    reserved = float(cfg.get("reserved_height_mm", 14.0)) + float(cfg.get("padding_height_mm", 1.0))
    changes = []
    last = hwp_pages[-1]
    for index, page in enumerate(pdf_pages):
        page_regions = by_page[page]
        title = next((r["title"] for r in page_regions if r.get("title")), None)
        if index < len(hwp_pages):
            target, added = hwp_pages[index], 0
        else:
            target, added = last, index - len(hwp_pages) + 1
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
                    "table": target["table"],
                    "page_no": target["page_no"] + added,
                    "row": target["row"],
                    "col": target["col"],
                    "address": cell_address(target["row"], target["col"]),
                    "existing_title": target["title"],
                    "existing_pictures": len(target["pictures"]),
                    "page_to_be_added": bool(added),
                    "copies_after_anchor": added,
                    "cell_inner_width_mm": inner,
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
                "status": "blocked" if wm == "review_required" else "review_required",
                "no_op": False,
            }
        )
    return changes, warnings


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
        fit = fit_picture(region["bbox"], hu_to_mm(slot["width"]), hu_to_mm(slot["height"]))
        flags = ["slot_paired_by_order"] + (["watermark_manual_required"] if blocked else [])
        if fit["fill_ratio"] is not None and fit["fill_ratio"] < SMALL_FILL_RATIO:
            flags.append("picture_small_in_box")
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


def build_candidates(extracted: dict, regions: list[dict], inventory: dict, sections: list[str], watermark_pages: dict[int, str], pictures_cfg: dict | None = None) -> dict:
    hwp_tables = section_tables(inventory, sections)
    pdf_tables = [t for t in extracted["tables"] if t["known_section"]]
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
    pictures_cfg = pictures_cfg or {}
    picture, picture_notes = picture_changes(regions, inventory, watermark_pages, pictures_cfg.get("circuit_anchor", "Circuit components"))
    changes.extend(picture)
    warnings.extend(picture_notes)
    pages_planned, page_notes = plan_oscillogram_pages(regions, inventory, pictures_cfg.get("oscillogram_page", {}), watermark_pages)
    changes.extend(pages_planned)
    warnings.extend(page_notes)
    planned = {(pic["png"]) for change in pages_planned for pic in change["pictures"]}
    slots = picture_slots(inventory, pictures_cfg.get("oscillogram_slots", {}).get("header_text", "오실로그램"))
    slot_changes, slot_notes = plan_picture_slots(regions, slots, watermark_pages, planned)
    changes.extend(slot_changes)
    warnings.extend(slot_notes)
    planned |= {c["after_png"] for c in slot_changes}
    unmapped = [r for r in regions if r.get("export") and r["kind"] != "circuit_diagram" and r.get("png") not in planned]
    return {
        "pairs": pairs,
        "changes": changes,
        "warnings": warnings,
        "unmapped_regions": [{"page": r["page"], "index": r["index"], "kind": r["kind"], "title": r.get("title"), "png": r.get("png")} for r in unmapped],
    }
