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


def compare_hwp(before: dict, after: dict, applied: list[dict]) -> dict:
    problems: list[str] = []
    if before["table_count"] != after["table_count"]:
        problems.append(f"table count {before['table_count']} -> {after['table_count']}")
    if before["picture_count"] != after["picture_count"]:
        problems.append(f"picture count {before['picture_count']} -> {after['picture_count']}")
    expected = {(c["hwp"]["table"], c["hwp"]["row"], c["hwp"]["col"]): c for c in applied if c.get("apply_status") == "applied"}
    unexpected, missing_values, size_changes = [], [], []
    for table_a, table_b in zip(before["tables"], after["tables"]):
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
            if key in expected:
                if _norm(cell_b["text"]) != _norm(expected[key]["after"]):
                    missing_values.append({"cell": key, "expected": expected[key]["after"], "found": cell_b["text"]})
            elif _norm(cell_a["text"]) != _norm(cell_b["text"]):
                unexpected.append({"cell": key, "before": cell_a["text"], "after": cell_b["text"]})
    return {
        "stage": "hwp",
        "structure_problems": problems,
        "cell_size_changes": size_changes,
        "unexpected_text_changes": unexpected,
        "applied_values_not_found": missing_values,
        "applied_changes_checked": len(expected),
        "passed": not (problems or size_changes or unexpected or missing_values),
    }
