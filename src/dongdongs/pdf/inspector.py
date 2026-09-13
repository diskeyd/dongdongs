"""Object-level survey of a PDF: content streams, images, form XObjects, optional content."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf


def _compact(pages: list[int]) -> str:
    ranges, start, prev = [], None, None
    for n in pages:
        if start is None:
            start = prev = n
        elif n == prev + 1:
            prev = n
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = n
    if start is not None:
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)


def inspect_pdf(pdf_path: Path) -> dict:
    with pymupdf.open(pdf_path) as doc:
        usage: dict[int, dict] = {}
        pages = []
        text_pages = 0
        for page in doc:
            number = page.number + 1
            text_chars = len(page.get_text().strip())
            text_pages += bool(text_chars)
            boxes: dict[int, list] = {}
            for info in page.get_image_info(xrefs=True):
                boxes.setdefault(info["xref"], []).append([round(v, 2) for v in info["bbox"]])
            images = []
            for im in page.get_images(full=True):
                xref, name = im[0], im[7]
                entry = usage.setdefault(xref, {"xref": xref, "width": im[2], "height": im[3], "names": set(), "pages": [], "drawn_pages": []})
                entry["names"].add(name)
                entry["pages"].append(number)
                if boxes.get(xref):
                    entry["drawn_pages"].append(number)
                images.append({"xref": xref, "name": name, "width": im[2], "height": im[3], "bboxes": boxes.get(xref, [])})
            forms = []
            for xref, name, _invoker, bbox in page.get_xobjects():
                kind, value = doc.xref_get_key(xref, "OC")
                forms.append({"xref": xref, "name": name, "bbox": [round(v, 2) for v in bbox], "optional_content": value if kind != "null" else None})
            pages.append(
                {
                    "page": number,
                    "size_pt": [round(page.rect.width, 2), round(page.rect.height, 2)],
                    "content_streams": page.get_contents(),
                    "text_chars": text_chars,
                    "images": images,
                    "forms": forms,
                }
            )
        repeated = []
        for entry in usage.values():
            if len(entry["pages"]) >= max(2, doc.page_count // 2):
                try:
                    digest = hashlib.sha256(doc.extract_image(entry["xref"])["image"]).hexdigest()
                except Exception:  # not a decodable image
                    digest = None
                repeated.append(
                    {
                        "xref": entry["xref"],
                        "width": entry["width"],
                        "height": entry["height"],
                        "names": sorted(entry["names"]),
                        "referenced_pages": _compact(entry["pages"]),
                        "drawn_pages": _compact(entry["drawn_pages"]),
                        "drawn_page_count": len(entry["drawn_pages"]),
                        "sha256": digest,
                    }
                )
        ocg_forms: dict[str, int] = {}
        for page in pages:
            for form in page["forms"]:
                if form["optional_content"]:
                    ocg_forms[form["optional_content"]] = ocg_forms.get(form["optional_content"], 0) + 1
        return {
            "pdf": Path(pdf_path).name,
            "page_count": doc.page_count,
            "text_layer_pages": text_pages,
            "optional_content_groups": {str(x): v for x, v in doc.get_ocgs().items()},
            "forms_per_optional_content": ocg_forms,
            "repeated_images": repeated,
            "pages": pages,
        }
