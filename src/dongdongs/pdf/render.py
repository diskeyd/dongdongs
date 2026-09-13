"""Render a region of the cleaned PDF to PNG (handoff section 6.1).

The clip is the full outline plus a small margin so the border strokes are kept;
nothing inside the outline is cut and no pixel is modified after rendering.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf


def render_region(pdf_path: Path, page_no: int, bbox, out_png: Path, dpi: int = 300, pad_pt: float = 0.5) -> dict:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_no - 1]
        clip = (pymupdf.Rect(bbox) + (-pad_pt, -pad_pt, pad_pt, pad_pt)) & page.rect
        pix = page.get_pixmap(dpi=dpi, clip=clip, alpha=False)
        pix.set_dpi(dpi, dpi)
        pix.save(out_png)
        return {
            "png": str(out_png),
            "page": page_no,
            "clip_pt": [round(v, 2) for v in clip],
            "dpi": dpi,
            "width_px": pix.width,
            "height_px": pix.height,
        }


def render_crop(pdf_path: Path, page_no: int, bbox, out_png: Path, dpi: int = 200, pad_pt: float = 2.0) -> str:
    """Evidence crop for the review screen only; never inserted into the HWP."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(pdf_path) as doc:
        page = doc[page_no - 1]
        clip = (pymupdf.Rect(bbox) + (-pad_pt, -pad_pt, pad_pt, pad_pt)) & page.rect
        page.get_pixmap(dpi=dpi, clip=clip, alpha=False).save(out_png)
    return str(out_png)
