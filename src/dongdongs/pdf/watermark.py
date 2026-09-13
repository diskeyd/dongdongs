"""Selective deletion of independent watermark objects.

Only whole PDF objects are removed: the content-stream block that paints a
matching image XObject, and the page's resource entry for it. Pixels are never
edited. When any condition of a rule fails, the page is left untouched and
reported as ``review_required`` ("확인 필요 — 워터마크 수동 처리").
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pymupdf

_NUM = rb"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
MANUAL = "확인 필요 — 워터마크 수동 처리"


def _block_re(name: str) -> re.Pattern[bytes]:
    return re.compile(
        rb"(?<!\S)q\s+(?:" + _NUM + rb"\s+){6}cm\s+(?:/(?P<gs>[^\s/\[\]<>()]+)\s+gs\s+)?/"
        + re.escape(name.encode("latin-1"))
        + rb"\s+Do\s+Q(?!\S)\s*"
    )


def _do_re(name: str) -> re.Pattern[bytes]:
    return re.compile(rb"/" + re.escape(name.encode("latin-1")) + rb"\s+Do(?![A-Za-z0-9])")


def image_signature(doc: pymupdf.Document, xref: int) -> dict | None:
    try:
        info = doc.extract_image(xref)
    except Exception:
        return None
    if not info:
        return None
    return {"width": info["width"], "height": info["height"], "ext": info["ext"], "sha256": hashlib.sha256(info["image"]).hexdigest()}


def _extgstate_alpha(doc: pymupdf.Document, page: pymupdf.Page, name: str) -> float | None:
    kind, value = doc.xref_get_key(page.xref, f"Resources/ExtGState/{name}")
    if kind == "xref":
        text = doc.xref_object(int(value.split()[0]))
    elif kind == "dict":
        text = value
    else:
        return None
    match = re.search(r"/ca\s+([-+]?[\d.]+)", text)
    return float(match.group(1)) if match else None


def _match_page(doc: pymupdf.Document, page: pymupdf.Page, rule: dict, signatures: dict) -> list[dict]:
    wanted = rule["image"]
    draw = rule.get("draw", {})
    matches = []
    for im in page.get_images(full=True):
        xref, name, referencer = im[0], im[7], im[9]
        if xref not in signatures:
            signatures[xref] = image_signature(doc, xref)
        sig = signatures[xref]
        if not sig or (sig["width"], sig["height"], sig["sha256"]) != (wanted["width"], wanted["height"], wanted["sha256"]):
            continue
        entry = {"rule": rule["id"], "xref": xref, "name": name, "blocks": [], "bboxes": [], "problems": []}
        if referencer != 0:
            entry["problems"].append("image is referenced through a form XObject, not the page")
            matches.append(entry)
            continue
        entry["bboxes"] = [[round(v, 3) for v in info["bbox"]] for info in page.get_image_info(xrefs=True) if info["xref"] == xref]
        for stream in page.get_contents():
            data = doc.xref_stream(stream)
            draws = len(_do_re(name).findall(data))
            if not draws:
                continue
            blocks = list(_block_re(name).finditer(data))
            if len(blocks) != draws:
                entry["problems"].append(f"stream {stream}: {draws} draw(s) but {len(blocks)} isolated q..Q block(s)")
            marker = draw.get("after_marker")
            if marker:
                position = data.rfind(marker.encode("latin-1"))
                if position < 0 or any(b.start() < position for b in blocks):
                    entry["problems"].append(f"stream {stream}: draw block is not after {marker!r}")
            limit = draw.get("require_extgstate_alpha_below")
            if limit is not None:
                for block in blocks:
                    gs = block.group("gs")
                    alpha = _extgstate_alpha(doc, page, gs.decode("latin-1")) if gs else None
                    if alpha is None or alpha >= limit:
                        entry["problems"].append(f"stream {stream}: fill alpha {alpha} is not below {limit}")
            entry["blocks"].extend([stream, b.start(), b.end()] for b in blocks)
        if entry["blocks"] and len(entry["blocks"]) != len(entry["bboxes"]):
            entry["problems"].append(f"{len(entry['bboxes'])} rendered draw(s) but {len(entry['blocks'])} block(s) found")
        matches.append(entry)
    return matches


def plan_removal(doc: pymupdf.Document, institution: dict) -> dict:
    rules = institution.get("watermarks", [])
    unsupported = [r.get("id") for r in rules if r.get("kind") != "image_xobject"]
    rules = [r for r in rules if r.get("kind") == "image_xobject"]
    signatures: dict[int, dict | None] = {}
    stream_pages: dict[int, set[int]] = {}
    pages = []
    for page in doc:
        number = page.number + 1
        for stream in page.get_contents():
            stream_pages.setdefault(stream, set()).add(number)
        matches = [m for rule in rules for m in _match_page(doc, page, rule, signatures)]
        if not matches:
            status = "no_watermark"
        elif any(m["problems"] for m in matches):
            status = "review_required"
        elif all(not m["blocks"] for m in matches):
            status = "reference_only"
        else:
            status = "delete"
        pages.append({"page": number, "status": status, "matches": matches, "reasons": [p for m in matches for p in m["problems"]]})

    by_number = {p["page"]: p for p in pages}
    for rule in rules:
        hits = sum(1 for p in pages if p["status"] == "delete" and any(m["rule"] == rule["id"] for m in p["matches"]))
        ratio = hits / max(1, doc.page_count)
        if hits and ratio < rule.get("min_page_ratio", 1.0):
            for p in pages:
                if p["status"] == "delete":
                    p["status"] = "review_required"
                    p["reasons"].append(f"rule {rule['id']} matched {hits} of {doc.page_count} pages, below min_page_ratio")

    for stream, numbers in stream_pages.items():
        if len(numbers) > 1 and any(by_number[n]["status"] == "delete" for n in numbers) and any(by_number[n]["status"] == "review_required" for n in numbers):
            for n in numbers:
                if by_number[n]["status"] == "delete":
                    by_number[n]["status"] = "review_required"
                    by_number[n]["reasons"].append(f"content stream {stream} is shared with a page that needs manual review")

    counts: dict[str, int] = {}
    for p in pages:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    for p in pages:
        if p["status"] == "review_required":
            p["manual_status"] = MANUAL
    return {
        "unsupported_rules": unsupported,
        "counts": counts,
        "overall": "manual_required" if counts.get("review_required") else ("removed" if counts.get("delete") else "nothing_to_remove"),
        "pages": pages,
    }


def apply_removal(doc: pymupdf.Document, plan: dict) -> dict:
    edits: dict[int, set[tuple[int, int]]] = {}
    for page in plan["pages"]:
        if page["status"] != "delete":
            continue
        for match in page["matches"]:
            for stream, start, end in match["blocks"]:
                edits.setdefault(stream, set()).add((start, end))
    for stream, spans in edits.items():
        data = doc.xref_stream(stream)
        for start, end in sorted(spans, reverse=True):
            data = data[:start] + data[end:]
        doc.update_stream(stream, data)
    references = 0
    for page in plan["pages"]:
        if page["status"] not in ("delete", "reference_only"):
            continue
        page_xref = doc[page["page"] - 1].xref
        if doc.xref_get_key(page_xref, "Resources")[0] != "dict":
            continue  # shared resource dictionaries are left alone
        for match in page["matches"]:
            doc.xref_set_key(page_xref, f"Resources/XObject/{match['name']}", "null")
            references += 1
    for page in plan["pages"]:
        page["removed_bboxes"] = [b for m in page["matches"] for b in m["bboxes"]] if page["status"] == "delete" else []
    return {"streams_edited": len(edits), "resource_entries_removed": references}


def protected_ocgs(doc: pymupdf.Document, institution: dict) -> dict[int, str]:
    names = set(institution.get("protect", {}).get("ocg_names", []))
    return {xref: info["name"] for xref, info in doc.get_ocgs().items() if info["name"] in names}


def clean_pdf(pdf_path: Path, out_path: Path, institution: dict, candidates_dir: Path | None = None) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf_path) as doc:
        plan = plan_removal(doc, institution)
        if candidates_dir is not None:
            candidates_dir.mkdir(parents=True, exist_ok=True)
            seen = set()
            for page in plan["pages"]:
                for match in page["matches"]:
                    if match["xref"] not in seen:
                        seen.add(match["xref"])
                        pix = pymupdf.Pixmap(doc, match["xref"])
                        if pix.alpha or pix.n > 3:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        pix.save(candidates_dir / f"xref-{match['xref']}.png")
        protected = protected_ocgs(doc, institution)
        applied = apply_removal(doc, plan)
        doc.save(out_path, garbage=1)
    return {
        "source_pdf": Path(pdf_path).name,
        "cleaned_pdf": Path(out_path).name,
        "method": "delete matching image draw blocks and page resource entries; no pixel edits",
        "protected_ocgs": {str(k): v for k, v in protected.items()},
        **applied,
        **plan,
    }
