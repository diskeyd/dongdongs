"""Graph and diagram regions bounded by a drawn rectangular outline.

A region is a large filled rectangle plus the hairline rectangles that draw its
border. The title printed just above the outline is recorded but never part of
the region, and the region is never cropped inside its outline.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

HAIRLINE = 1.0
EDGE = 1.0
STACK_GAP = 5.0  # pt between a full-width graph and the half-width pair below it


def _rb(rect) -> list[float]:
    return [round(v, 2) for v in rect]


def outlines(page: pymupdf.Page, min_width: float, min_height: float) -> list[pymupdf.Rect]:
    big, thin = [], []
    for path in page.get_drawings():
        for item in path["items"]:
            if item[0] != "re":
                continue
            rect = pymupdf.Rect(item[1])
            if rect.width >= min_width and rect.height >= min_height:
                big.append(rect)
            elif rect.width < HAIRLINE or rect.height < HAIRLINE:
                thin.append(rect)
    found = []
    for rect in big:
        outline = pymupdf.Rect(rect)
        for line in thin:
            on_edge = min(abs(line.x0 - rect.x0), abs(line.x1 - rect.x1), abs(line.y0 - rect.y0), abs(line.y1 - rect.y1)) <= EDGE
            inside = line.x0 >= rect.x0 - EDGE and line.x1 <= rect.x1 + EDGE and line.y0 >= rect.y0 - EDGE and line.y1 <= rect.y1 + EDGE
            if on_edge and inside:
                outline |= line
        found.append(outline)
    kept: list[pymupdf.Rect] = []
    for outline in sorted(found, key=lambda r: -r.get_area()):
        if not any(k.contains(outline) for k in kept):
            kept.append(outline)
    return sorted(kept, key=lambda r: (r.y0, r.x0))


def _centre(bbox) -> pymupdf.Point:
    x0, y0, x1, y1 = bbox
    return pymupdf.Point((x0 + x1) / 2, (y0 + y1) / 2)


def _title(words, outline: pymupdf.Rect, all_outlines, gap: float) -> str | None:
    candidates = []
    for w in words:
        centre = pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
        if outline.y0 - gap <= w[3] <= outline.y0 + EDGE and w[2] > outline.x0 and w[0] < outline.x1:
            if not any(o.contains(centre) for o in all_outlines):
                candidates.append(w)
    if not candidates:
        return None
    bottom = max(w[3] for w in candidates)
    line = sorted((w for w in candidates if abs(w[3] - bottom) <= 3), key=lambda w: w[0])
    return " ".join(w[4] for w in line)


def find_regions(page: pymupdf.Page, cfg: dict) -> list[dict]:
    found = outlines(page, cfg.get("min_width_pt", 300), cfg.get("min_height_pt", 100))
    words = page.get_text("words")
    images = page.get_image_info(xrefs=True)
    kinds = cfg.get("kinds", {})
    export = set(cfg.get("export_kinds", []))
    regions = []
    for index, outline in enumerate(found):
        title = _title(words, outline, found, cfg.get("title_gap_pt", 22))
        kind = next((k for prefix, k in kinds.items() if title and title.startswith(prefix)), "unknown")
        regions.append(
            {
                "page": page.number + 1,
                "index": index,
                "bbox": _rb(outline),
                "title": title,
                "kind": kind,
                "kind_source": "title" if kind != "unknown" else None,
                "export": kind in export,
                "images": [i["xref"] for i in images if outline.contains(_centre(i["bbox"]))],
                "regions_on_page": len(found),
            }
        )
    titled = [r for r in regions if r["kind_source"] == "title"]
    for region in regions:
        if region["kind"] == "unknown" and region["title"] is None:
            x0, y0, x1, _ = region["bbox"]
            width = x1 - x0
            same_width = next((r for r in titled if abs((r["bbox"][2] - r["bbox"][0]) - width) <= 2), None)
            half_below = next(
                (r for r in titled if abs((r["bbox"][2] - r["bbox"][0]) / 2 - width) <= 6 and 0 <= y0 - r["bbox"][3] <= STACK_GAP),
                None,
            )
            sibling = same_width or half_below
            if sibling is not None:
                region["kind"] = sibling["kind"]
                region["kind_source"] = (
                    f"same width as titled region {sibling['index']} on the page"
                    if same_width
                    else f"half-width below titled region {sibling['index']} on the page"
                )
                region["export"] = region["kind"] in export
    widest = max((r["bbox"][2] - r["bbox"][0] for r in regions), default=0)
    for region in regions:
        x0, _, x1, _ = region["bbox"]
        if widest and (x1 - x0) < widest * 0.75:
            centre = (x0 + x1) / 2
            region["layout"] = "half-left" if centre < page.rect.width / 2 else "half-right"
        else:
            region["layout"] = "full"
    return regions


def find_document_regions(pdf_path: Path, cfg: dict, pages: list[int] | None = None) -> list[dict]:
    with pymupdf.open(pdf_path) as doc:
        numbers = pages or list(range(1, doc.page_count + 1))
        regions = []
        for number in numbers:
            regions.extend(find_regions(doc[number - 1], cfg))
        return regions
