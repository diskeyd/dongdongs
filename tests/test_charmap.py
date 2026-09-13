import unicodedata

from dongdongs.config.charmap import APPLY_TIERS, load_charmap, to_hwp_text
from dongdongs.hwp.mapping import section_blocks, section_changes


def test_measured_pairs_replace_and_report():
    text, applied = to_hwp_text("4.84 Ω / 2 μF")
    assert text == "4.84 Ω / 2 µF"
    assert any("OMEGA" in a for a in applied) and any("MU" in a for a in applied)


def test_standard_units_and_fullwidth():
    assert to_hwp_text("㎸")[0] == "kV"        # ㎸
    assert to_hwp_text("㎌")[0] == "µF"   # ㎌ -> µF with HWP's micro sign
    assert to_hwp_text("１０％")[0] == "10%"
    assert to_hwp_text("°C")[0] == "℃"


def test_lookalike_is_applied_and_flagged():
    text, applied = to_hwp_text("∆t − 3")
    assert text == "Δt - 3" and "lookalike" in applied


def test_style_tier_is_never_applied():
    assert to_hwp_text("“x” 2 x 3")[0] == "“x” 2 x 3"


def test_private_glyphs_are_dropped_and_reported():
    text, applied = to_hwp_text("abc")
    assert text == "abc" and "private_glyph_dropped" in applied


def test_every_applied_pair_keeps_meaning():
    data = load_charmap()
    norm = lambda s: unicodedata.normalize("NFKC", s).replace("μ", "µ")
    for pair in data["pairs"]:
        if pair["tier"] in ("measured", "standard"):
            assert norm(pair["pdf"]) == norm(pair["hwp"]), pair
        assert pair["tier"] in APPLY_TIERS | {"style"}


def test_mapping_uses_charmap_so_lookalike_units_become_no_op():
    cells = [
        {"row": 0, "col": 0, "rowspan": 1, "colspan": 3, "width": 1, "height": 1, "text": "Supply circuit"},
        {"row": 1, "col": 0, "rowspan": 1, "colspan": 1, "width": 1, "height": 1, "text": "Impedance"},
        {"row": 1, "col": 1, "rowspan": 1, "colspan": 1, "width": 1, "height": 1, "text": "Ω"},
        {"row": 1, "col": 2, "rowspan": 1, "colspan": 1, "width": 1, "height": 1, "text": "1.0"},
    ]
    table = {"index": 1, "depth": 1, "container": None, "rows": 2, "cols": 3, "width": 1, "height": 1, "cells": cells}
    inventory = {"tables": [table], "pictures": [], "paragraphs": [{"text": "Supply circuit", "container": {"table": 1, "row": 0, "col": 0}}]}
    row = {"row": 1, "label": "Impedance", "unit": "Ω", "value": "2.0", "flags": [], "status": "review_required",
           "cells": [{"col": i, "colspan": 1, "rowspan": 1, "text": t, "markup": t, "bbox": [i, 1, i + 1, 2]} for i, t in enumerate(("Impedance", "Ω", "2.0"))]}
    pdf = {"section": "Supply circuit", "known_section": True, "source": {"pdf": "x.pdf", "pdf_page": 5, "printed_page": "5 of 10"}, "bbox": [0, 0, 1, 1], "grid": {"rows": 2, "cols": 3}, "rows": [row]}
    block = section_blocks(table, ["Supply circuit"])["Supply circuit"]
    changes, _ = section_changes(pdf, table, block, inventory)
    unit = next(c for c in changes if c["field"] == "unit")
    assert unit["no_op"] and unit["after"] == "Ω" and unit["after_extracted"] == "Ω"
    assert any(f.startswith("charmap_applied:") for f in unit["flags"]) and "unicode_lookalike_only" not in unit["flags"]
