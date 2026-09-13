"""Institution rule loading, detection and the PDF -> HWP symbol map."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pymupdf
import yaml

from .charmap import load_charmap, nfkc_equal, to_hwp_text


def load_config(path: Path | None = None) -> dict:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files(__package__).joinpath("institutions.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def institution(config: dict, name: str) -> dict:
    try:
        return config["institutions"][name]
    except KeyError as exc:
        known = ", ".join(config.get("institutions", {}))
        raise KeyError(f"unknown institution {name!r}; configured: {known}") from exc


def detect_institution(pdf_path: Path, config: dict) -> str | None:
    with pymupdf.open(pdf_path) as doc:
        texts = [page.get_text() for page in doc]
    for name, rules in config.get("institutions", {}).items():
        detect = rules.get("detect", {})
        needles = detect.get("text_any", [])
        hits = sum(1 for text in texts if any(n in text for n in needles))
        if needles and hits >= detect.get("min_pages", 1):
            return name
    return None


__all__ = ["detect_institution", "institution", "load_charmap", "load_config", "nfkc_equal", "to_hwp_text"]
