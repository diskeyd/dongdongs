"""Symbol map between PDF text and the code points the HWP report uses.

``charmap.json`` lists PDF-side variants and the HWP-side canonical form.
Every pair carries a *tier* that decides what ``to_hwp_text`` does with it:

    measured   the HWP itself uses this code point (checked on the real report)  -> replace
    standard   NFKC-equivalent (compatibility units, fullwidth forms, spaces)     -> replace
    lookalike  same meaning, different Unicode identity (∆/Δ, dashes, ≦/≤)        -> replace + flag
    style      typographic preference (quotes, x/×)                               -> stored only

Characters in ``drop_ranges`` (private-use glyphs used as leader dots) are
removed and reported.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources

APPLY_TIERS = {"measured", "standard", "lookalike"}
FLAG_TIERS = {"lookalike"}


@lru_cache(maxsize=1)
def load_charmap() -> dict:
    text = resources.files(__package__).joinpath("charmap.json").read_text(encoding="utf-8")
    data = json.loads(text)
    data["_drop"] = [(int(a, 16), int(b, 16)) for a, b in data.get("drop_ranges", [])]
    data["_by_len"] = sorted((p for p in data["pairs"] if p["tier"] in APPLY_TIERS), key=lambda p: -len(p["pdf"]))
    return data


def _dropped(ch: str, ranges) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in ranges)


def to_hwp_text(text: str) -> tuple[str, list[str]]:
    """Return the text as the HWP should hold it and the names of the rules applied."""
    if not text:
        return text, []
    data = load_charmap()
    pairs = data["_by_len"]
    out: list[str] = []
    applied: list[str] = []
    i = 0
    while i < len(text):
        for pair in pairs:
            key = pair["pdf"]
            if text.startswith(key, i):
                out.append(pair["hwp"])
                applied.append(pair["name"])
                if pair["tier"] in FLAG_TIERS:
                    applied.append("lookalike")
                i += len(key)
                break
        else:
            ch = text[i]
            if _dropped(ch, data["_drop"]):
                applied.append("private_glyph_dropped")
            else:
                out.append(ch)
            i += 1
    seen: dict[str, None] = {}
    for name in applied:
        seen.setdefault(name, None)
    return "".join(out), list(seen)


__all__ = ["APPLY_TIERS", "load_charmap", "to_hwp_text"]
