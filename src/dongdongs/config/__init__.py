"""Institution rule loading, detection and the PDF -> HWP symbol map."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pymupdf
import yaml


def load_config(path: Path | None = None) -> dict:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = resources.files(__package__).joinpath("institutions.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def with_defaults(config: dict, own: dict | None = None) -> dict:
    """Rules of one institution on top of ``defaults``; dict-valued keys (tables, regions, pictures) merge one level deep."""
    rules = {k: (dict(v) if isinstance(v, dict) else v) for k, v in (config.get("defaults") or {}).items()}
    for k, v in (own or {}).items():
        rules[k] = {**rules[k], **v} if isinstance(v, dict) and isinstance(rules.get(k), dict) else v
    return rules


def institution(config: dict, name: str) -> dict:
    try:
        own = config["institutions"][name]
    except KeyError as exc:
        known = ", ".join(config.get("institutions", {}))
        raise KeyError(f"unknown institution {name!r}; configured: {known}") from exc
    return with_defaults(config, own)


REPORT_DEFAULTS = {
    "section_heading_pattern": r"^(\d{1,3})\.\s+(\S.*)$",
    "section_code_pattern": r"\(([A-Za-z][A-Za-z0-9_]*)\)\s*$",
}


def report_rules(config: dict) -> dict:
    """Rules of the HWP report format (not of an institution), with defaults."""
    return {**REPORT_DEFAULTS, **(config.get("report") or {})}


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


__all__ = ["detect_institution", "institution", "load_config", "report_rules", "with_defaults"]
