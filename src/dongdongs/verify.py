"""Verification.

``clean`` stage: the no-alteration oracle for watermark removal. Outside the
removed watermark rectangles the cleaned page must render pixel-identical to
the original; inside them the cleaned page may only get lighter (removing a
multiply-blended layer can never darken); the footer must still render and the
protected optional-content objects must still be referenced.

``hwp`` stage: structure and value checks between the before and processed HWP
inventories. It needs no Hancom Office and runs on any OS.
"""

from __future__ import annotations

import math
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops, ImageDraw

DARKER_TOLERANCE = 8
EDGE_PAD_PX = 2


def _render(page: pymupdf.Page, dpi: int) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _max_channel(image: Image.Image) -> Image.Image:
    red, green, blue = image.split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue)


def _count(binary: Image.Image) -> int:
    return binary.histogram()[255]


def _protected_names(doc: pymupdf.Document, page: pymupdf.Page, ocg_xrefs: set[int]) -> set[str]:
    names = set()
    for xref, name, _invoker, _bbox in page.get_xobjects():
        kind, value = doc.xref_get_key(xref, "OC")
        if kind == "xref" and int(value.split()[0]) in ocg_xrefs:
            names.add(name)
    return names


def compare_clean(original: Path, cleaned: Path, report: dict, institution: dict, dpi: int = 300, pages: list[int] | None = None) -> dict:
    scale = dpi / 72
    by_page = {p["page"]: p for p in report["pages"]}
    band_pt = institution.get("footer_band_pt")
    protect = set(institution.get("protect", {}).get("ocg_names", []))
    results = []
    with pymupdf.open(original) as before, pymupdf.open(cleaned) as after:
        if before.page_count != after.page_count:
            return {"stage": "clean", "passed": False, "error": f"page count {before.page_count} -> {after.page_count}"}
        ocg_xrefs = {x for x, info in before.get_ocgs().items() if info["name"] in protect}
        numbers = pages or list(range(1, before.page_count + 1))
        for number in numbers:
            page_a, page_b = before[number - 1], after[number - 1]
            image_a, image_b = _render(page_a, dpi), _render(page_b, dpi)
            entry: dict = {"page": number, "watermark_status": by_page.get(number, {}).get("status")}
            if image_a.size != image_b.size:
                entry.update(size_changed=True, passed=False)
                results.append(entry)
                continue
            mask = Image.new("L", image_a.size, 255)
            draw = ImageDraw.Draw(mask)
            for x0, y0, x1, y1 in by_page.get(number, {}).get("removed_bboxes", []):
                draw.rectangle(
                    [math.floor(x0 * scale) - EDGE_PAD_PX, math.floor(y0 * scale) - EDGE_PAD_PX, math.ceil(x1 * scale) + EDGE_PAD_PX, math.ceil(y1 * scale) + EDGE_PAD_PX],
                    fill=0,
                )
            changed = _max_channel(ImageChops.difference(image_a, image_b)).point(lambda v: 255 if v else 0)
            outside = _count(ImageChops.multiply(changed, mask))
            darker = _max_channel(ImageChops.subtract(image_a, image_b)).point(lambda v: 255 if v > DARKER_TOLERANCE else 0)
            darker_inside = _count(ImageChops.multiply(darker, ImageChops.invert(mask)))
            entry.update(pixel_diff_outside_wm=outside, darker_pixels_inside_wm=darker_inside)
            if band_pt is not None:
                top = int(band_pt * scale)
                had_footer = image_a.crop((0, top, image_a.width, image_a.height)).convert("L").getextrema()[0] < 128
                has_footer = image_b.crop((0, top, image_b.width, image_b.height)).convert("L").getextrema()[0] < 128
                entry["footer_present"] = has_footer or not had_footer
            if ocg_xrefs:
                missing = _protected_names(before, page_a, ocg_xrefs) - {x[1] for x in page_b.get_xobjects()}
                entry["protected_objects_missing"] = sorted(missing)
            entry["passed"] = outside == 0 and darker_inside == 0 and entry.get("footer_present", True) and not entry.get("protected_objects_missing")
            results.append(entry)
        remaining = []
        for number in numbers:
            status = by_page.get(number, {}).get("status")
            if status == "delete":
                page = after[number - 1]
                names = {m["name"] for m in by_page[number]["matches"]}
                for stream in page.get_contents():
                    data = after.xref_stream(stream)
                    if any(f"/{n} Do".encode() in data or f"/{n}\nDo".encode() in data for n in names):
                        remaining.append(number)
    return {
        "stage": "clean",
        "dpi": dpi,
        "pages_checked": len(results),
        "pixel_diff_outside_wm": sum(r.get("pixel_diff_outside_wm", 0) for r in results),
        "pages_with_outside_diff": [r["page"] for r in results if r.get("pixel_diff_outside_wm")],
        "pages_darker_inside_wm": [r["page"] for r in results if r.get("darker_pixels_inside_wm")],
        "footer_present": all(r.get("footer_present", True) for r in results),
        "protected_objects_kept": not any(r.get("protected_objects_missing") for r in results),
        "watermark_draws_remaining_on_deleted_pages": remaining,
        "manual_watermark_pages": [p["page"] for p in report["pages"] if p["status"] == "review_required"],
        "passed": all(r["passed"] for r in results) and not remaining,
        "pages": results,
    }


def _norm(text: str) -> str:
    return "\n".join(line.strip() for line in text.replace("\r\n", "\n").split("\n")).strip()


def _size_ok(expected, found, tolerance: float = 0.01) -> bool:
    return all(abs(e - f) <= max(1, e * tolerance) for e, f in zip(expected, found))


def compare_hwp(before: dict, after: dict, applied: list[dict], copies: list[dict] | None = None) -> dict:
    """Structure must be unchanged except for what the applied changes explain.

    Applied ``fill_oscillogram_page`` changes may add page frames (copied graph
    pages) and pictures; applied ``replace_picture`` changes swap one picture for
    another of the same size. Everything else must be identical.
    """
    problems: list[str] = []
    done = [c for c in applied if c.get("apply_status") == "applied"]
    text_changes = {(c["hwp"]["table"], c["hwp"]["row"], c["hwp"]["col"]): c for c in done if c.get("kind", "set_cell_text") == "set_cell_text"}
    picture_changes = {(c["hwp"]["table"], c["hwp"]["row"], c["hwp"]["col"]): c for c in done if c.get("kind") == "replace_picture"}
    from .hwp.mapping import graph_page_positions

    fills = [c for c in done if c.get("kind") == "fill_oscillogram_page"]
    counts_given = {int(c["anchor_page"]): int(c["count"]) for c in copies} if copies is not None else None
    positions, copy_counts = graph_page_positions(fills, counts_given)

    def shift(page: int) -> int:
        return sum(n for anchor, n in copy_counts.items() if anchor < page)

    # copies sit right after their section's last graph page; later pages move down by the copies before them
    added_pages = {anchor + shift(anchor) + k for anchor, n in copy_counts.items() for k in range(1, n + 1)}
    added_changes = {positions[c["id"]]: c for c in fills if c["hwp"].get("page_to_be_added") and c["id"] in positions}
    # filled pages are named by their page in the "before" document
    filled_changes = {(c["hwp"].get("page_no_before") or c["hwp"]["page_no"]): c for c in fills if not c["hwp"].get("page_to_be_added")}

    # drop the frames that were added (and everything nested in them) so the rest lines up
    after_tables = [t for t in after["tables"] if t.get("page_no") not in added_pages]
    after_pictures = [p for p in after["pictures"] if p.get("page_no") not in added_pages]
    if len(before["tables"]) != len(after_tables):
        problems.append(f"table count {len(before['tables'])} -> {len(after_tables)} (after removing {len(added_pages)} added pages)")
    expected_pictures = before["picture_count"]
    for change in filled_changes.values():
        expected_pictures += len(change["pictures"]) - int(change["hwp"].get("existing_pictures") or 0)
    if expected_pictures != len(after_pictures):
        problems.append(f"picture count {len(after_pictures)}, expected {expected_pictures}")
    after_index_of = {a["index"]: b["index"] for a, b in zip(before["tables"], after_tables)}
    after_page_of = {t["index"]: t.get("page_no") for t in after["tables"]}
    for anchor in copy_counts:
        frame = next((t for t in before["tables"] if t.get("depth") == 0 and t.get("page_no") == anchor), None)
        moved_to = after_page_of.get(after_index_of.get(frame["index"])) if frame else None
        if moved_to != anchor + shift(anchor):
            problems.append(f"graph page {anchor} should be on page {anchor + shift(anchor)} after the copies before it, found {moved_to}")
    if before.get("sections") and after.get("sections"):
        names_before = [(x["no"], x["title"]) for x in before["sections"]]
        names_after = [(x["no"], x["title"]) for x in after["sections"]]
        if names_before != names_after:
            problems.append("report test sections changed (numbers or titles)")
    unexpected, missing_values, size_changes, picture_problems = [], [], [], []
    for table_a, table_b in zip(before["tables"], after_tables):
        if (table_a["rows"], table_a["cols"], len(table_a["cells"])) != (table_b["rows"], table_b["cols"], len(table_b["cells"])):
            problems.append(f"table {table_a['index']} structure {table_a['rows']}x{table_a['cols']}/{len(table_a['cells'])} -> {table_b['rows']}x{table_b['cols']}/{len(table_b['cells'])}")
            continue
        cells_b = {(c["row"], c["col"]): c for c in table_b["cells"]}
        for cell_a in table_a["cells"]:
            key = (table_a["index"], cell_a["row"], cell_a["col"])
            cell_b = cells_b.get((cell_a["row"], cell_a["col"]))
            if cell_b is None:
                problems.append(f"table {key[0]} cell {key[1:]} disappeared")
                continue
            if (cell_a["width"], cell_a["height"]) != (cell_b["width"], cell_b["height"]):
                size_changes.append({"cell": key, "before": [cell_a["width"], cell_a["height"]], "after": [cell_b["width"], cell_b["height"]]})
            page_change = filled_changes.get(table_a.get("page_no")) if table_a.get("depth") == 0 else None
            if page_change and (cell_a["row"], cell_a["col"]) == (page_change["hwp"]["row"], page_change["hwp"]["col"]):
                if _norm(page_change["after"]) not in _norm(cell_b["text"]):
                    missing_values.append({"cell": key, "expected": page_change["after"], "found": cell_b["text"]})
            elif key in text_changes:
                if _norm(cell_b["text"]) != _norm(text_changes[key]["after"]):
                    missing_values.append({"cell": key, "expected": text_changes[key]["after"], "found": cell_b["text"]})
            elif _norm(cell_a["text"]) != _norm(cell_b["text"]):
                unexpected.append({"cell": key, "before": cell_a["text"], "after": cell_b["text"]})
    # pictures: same position and size unless replaced; filled pages carry the planned sizes
    def by_cell(pictures):
        grouped: dict[tuple, list] = {}
        for pic in pictures:
            if pic["container"]:
                grouped.setdefault((pic["container"]["table"], pic["container"]["row"], pic["container"]["col"]), []).append(pic)
        return grouped

    pics_a, pics_b = by_cell(before["pictures"]), by_cell(after_pictures)
    for key, group in pics_a.items():
        table_index = key[0]
        table_before = before["tables"][table_index] if table_index < len(before["tables"]) else {}
        page_change = filled_changes.get(table_before.get("page_no")) if table_before.get("depth") == 0 else None
        if page_change and key[1:] == (page_change["hwp"]["row"], page_change["hwp"]["col"]):
            continue
        found = pics_b.get((after_index_of.get(table_index, table_index),) + key[1:], [])
        if key in picture_changes:
            target = picture_changes[key]["target"]
            if len(found) != 1 or not _size_ok((target["width_hwpunit"], target["height_hwpunit"]), (found[0]["width"], found[0]["height"])):
                picture_problems.append({"cell": key, "expected": [target["width_hwpunit"], target["height_hwpunit"]], "found": [[p["width"], p["height"]] for p in found]})
            elif found[0]["bindata_id"] == group[0]["bindata_id"]:
                picture_problems.append({"cell": key, "problem": "picture data unchanged after replacement"})
            continue
        if [(p["width"], p["height"]) for p in group] != [(p["width"], p["height"]) for p in found]:
            picture_problems.append({"cell": key, "before": [[p["width"], p["height"]] for p in group], "after": [[p["width"], p["height"]] for p in found]})
    for page_no, change in filled_changes.items():
        # a filled page keeps its "before" table; its "after" index may have shifted past inserted pages
        frame_index = after_index_of.get(change["hwp"]["table"])
        found = pics_b.get((frame_index, change["hwp"]["row"], change["hwp"]["col"]), []) if frame_index is not None else []
        planned = [(p["width_hwpunit"], p["height_hwpunit"]) for p in change["pictures"]]
        if len(found) != len(planned) or not all(_size_ok(p, (f["width"], f["height"])) for p, f in zip(planned, found)):
            picture_problems.append({"page": page_no, "expected": planned, "found": [[p["width"], p["height"]] for p in found]})
    for page_no in sorted(added_pages):
        frame = next((t for t in after["tables"] if t.get("depth") == 0 and t.get("page_no") == page_no), None)
        change = added_changes.get(page_no)
        if change is None:
            problems.append(f"graph page {page_no} was copied but not filled")
            continue
        if frame is None:
            problems.append(f"added graph page {page_no} not found")
            continue
        cell = next((c for c in frame["cells"] if (c["row"], c["col"]) == (change["hwp"]["row"], change["hwp"]["col"])), None)
        if cell is None or _norm(change["after"]) not in _norm(cell["text"]):
            missing_values.append({"page": page_no, "expected": change["after"], "found": cell["text"] if cell else None})
        found = [p for p in after["pictures"] if p["container"] == {"table": frame["index"], "row": change["hwp"]["row"], "col": change["hwp"]["col"]}]
        planned = [(p["width_hwpunit"], p["height_hwpunit"]) for p in change["pictures"]]
        if len(found) != len(planned) or not all(_size_ok(p, (f["width"], f["height"])) for p, f in zip(planned, found)):
            picture_problems.append({"page": page_no, "expected": planned, "found": [[p["width"], p["height"]] for p in found]})
    return {
        "stage": "hwp",
        "structure_problems": problems,
        "cell_size_changes": size_changes,
        "unexpected_text_changes": unexpected,
        "applied_values_not_found": missing_values,
        "picture_problems": picture_problems,
        "pages_added": sorted(added_pages),
        "applied_changes_checked": len(done),
        "passed": not (problems or size_changes or unexpected or missing_values or picture_problems),
    }
