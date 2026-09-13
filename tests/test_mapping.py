from dongdongs.hwp.mapping import build_candidates, cell_address, section_blocks, section_changes


def _cell(row, col, text, colspan=1, rowspan=1):
    return {"row": row, "col": col, "rowspan": rowspan, "colspan": colspan, "width": 100, "height": 100, "text": text}


def _inventory():
    cells = [
        _cell(0, 0, "Supply circuit", colspan=3),
        _cell(1, 0, "Impedance"), _cell(1, 1, "Ω"), _cell(1, 2, "1.0"),
        _cell(2, 0, "frequency"), _cell(2, 1, "Hz"), _cell(2, 2, "60"),
        _cell(3, 0, "Old item"), _cell(3, 1, "kV"), _cell(3, 2, "1"),
        _cell(4, 0, ""), _cell(4, 1, ""), _cell(4, 2, ""),
    ]
    table = {"index": 5, "depth": 1, "container": None, "rows": 5, "cols": 3, "width": 1, "height": 1, "cells": cells}
    return {
        "table_count": 1,
        "picture_count": 0,
        "tables": [table],
        "pictures": [],
        "paragraphs": [{"text": "Supply circuit", "container": {"table": 5, "row": 0, "col": 0}}],
    }


def _pdf_row(row, label, unit, value, flags=()):
    cells = [{"col": i, "colspan": 1, "rowspan": 1, "text": t, "markup": t, "bbox": [i, row, i + 1, row + 1]} for i, t in enumerate((label, unit, value))]
    return {"row": row, "cells": cells, "label": label, "unit": unit, "value": value, "flags": list(flags), "status": "review_required"}


def _pdf_table():
    return {
        "section": "Supply circuit",
        "known_section": True,
        "source": {"pdf": "x.pdf", "pdf_page": 5, "printed_page": "5 of 10"},
        "bbox": [0, 0, 1, 1],
        "grid": {"rows": 4, "cols": 3},
        "rows": [_pdf_row(1, "Impedance", "Ω", "2.00"), _pdf_row(2, "Frequency", "Hz", "60"), _pdf_row(3, "Power factor", "", "< 0.1")],
    }


def _by(changes):
    return {(c["hwp"]["row"], c["field"]): c for c in changes}


def test_cell_address():
    assert [cell_address(0, 0), cell_address(3, 8), cell_address(0, 26)] == ["A1", "I4", "AA1"]


def test_section_changes_update_fill_and_clear():
    inventory = _inventory()
    table = inventory["tables"][0]
    block = section_blocks(table, ["Supply circuit"])["Supply circuit"]
    changes, warnings = section_changes(_pdf_table(), table, block, inventory)
    by = _by(changes)
    assert by[(1, "value")]["before"] == "1.0" and by[(1, "value")]["after"] == "2.00" and not by[(1, "value")]["no_op"]
    assert by[(1, "value")]["hwp"]["address"] == "C2"
    assert by[(1, "unit")]["no_op"]
    assert by[(2, "label")]["after"] == "Frequency" and by[(2, "label")]["before"] == "frequency"
    assert by[(4, "value")]["after"] == "< 0.1" and "row_assigned_to_empty_or_unmatched_hwp_row" in by[(4, "value")]["flags"]
    assert by[(3, "label")]["after"] == "" and "clear_not_in_pdf" in by[(3, "label")]["flags"]
    assert all(c["anchor"] == {"text": "Supply circuit", "occurrence": 1, "address": "A1"} for c in changes)
    assert all(c["status"] == "review_required" for c in changes)
    assert warnings == []


def test_build_candidates_flags_manual_watermark_pages():
    result = build_candidates({"tables": [_pdf_table()]}, [], _inventory(), ["Supply circuit"], {5: "review_required"})
    assert result["pairs"] == [{"pdf_page": 5, "hwp_table": 5, "method": "document_order", "label_similarity": 0.5}]
    assert all("watermark_manual_required_on_source_page" in c["flags"] for c in result["changes"])


def test_lookalike_units_are_flagged_not_hidden():
    inventory = _inventory()
    table = inventory["tables"][0]
    table["cells"][2]["text"] = "\u2126"  # OHM SIGN in the HWP
    pdf = _pdf_table()
    pdf["rows"][0]["unit"] = "\u03a9"  # GREEK CAPITAL OMEGA in the PDF
    block = section_blocks(table, ["Supply circuit"])["Supply circuit"]
    changes, _ = section_changes(pdf, table, block, inventory)
    unit = _by(changes)[(1, "unit")]
    assert not unit["no_op"] and "unicode_lookalike_only" in unit["flags"]
    assert "case_or_spacing_only" in _by(changes)[(2, "label")]["flags"]


def test_section_missing_from_pdf_gets_clearing_candidates():
    inventory = _inventory()
    table = inventory["tables"][0]
    table["cols"] = 6
    table["cells"] += [_cell(0, 3, "Prospective TRV", colspan=3), _cell(1, 3, "uc"), _cell(1, 4, "kV"), _cell(1, 5, "12.3")]
    for r in (2, 3, 4):
        table["cells"] += [_cell(r, 3, ""), _cell(r, 4, ""), _cell(r, 5, "")]
    inventory["paragraphs"].append({"text": "Prospective TRV", "container": {"table": 5, "row": 0, "col": 3}})
    result = build_candidates({"tables": [_pdf_table()]}, [], inventory, ["Supply circuit", "Prospective TRV"], {})
    trv = [c for c in result["changes"] if "section_not_in_pdf" in c["flags"]]
    assert {(c["hwp"]["address"], c["before"], c["after"]) for c in trv} == {("D2", "uc", ""), ("E2", "kV", ""), ("F2", "12.3", "")}
    assert all(c["status"] == "review_required" for c in trv)


def test_label_and_unit_sharing_one_cell_keep_hwp_spacing():
    cells = [
        _cell(0, 0, "Supply circuit", colspan=2),
        _cell(1, 0, "Impedance                  \u2126"), _cell(1, 1, "0.123 4"),
        _cell(2, 0, "Voltage(Phase to earth)     kV"), _cell(2, 1, "11.0"),
        _cell(3, 0, "Power factor"), _cell(3, 1, "<0.1"),
    ]
    table = {"index": 9, "depth": 1, "container": None, "rows": 4, "cols": 2, "width": 1, "height": 1, "cells": cells}
    inventory = {"tables": [table], "pictures": [], "paragraphs": [{"text": "Supply circuit", "container": {"table": 9, "row": 0, "col": 0}}]}
    pdf = _pdf_table()
    pdf["rows"] = [_pdf_row(1, "Impedance", "\u03a9", "2.50"), _pdf_row(2, "Voltage\n(Phase to earth)", "kV", "11.0"), _pdf_row(3, "Power factor", "", "< 0.1")]
    block = section_blocks(table, ["Supply circuit"])["Supply circuit"]
    changes, warnings = section_changes(pdf, table, block, inventory)
    by = _by(changes)
    assert by[(1, "label+unit")]["after"].startswith("Impedance") and "label_and_unit_share_cell_reconstructed" in by[(1, "label+unit")]["flags"]
    assert by[(1, "label+unit")]["after"] == "Impedance                  \u03a9"
    assert by[(1, "value")]["after"] == "2.50"
    assert by[(2, "label+unit")]["no_op"]
    assert by[(3, "value")]["after"] == "< 0.1" and "whitespace_only_difference" in by[(3, "value")]["flags"]
    assert warnings == []


def test_merged_label_cell_across_separator_is_matched():
    cells = [
        _cell(0, 0, "Supply circuit", colspan=3), _cell(0, 3, "", colspan=2), _cell(0, 5, "Load circuit", colspan=3),
        _cell(1, 0, "Impedance"), _cell(1, 1, "\u2126"), _cell(1, 2, "1.0"), _cell(1, 3, "", colspan=2),
        _cell(1, 5, "Impedance"), _cell(1, 6, "\u2126"), _cell(1, 7, "999"),
        _cell(2, 0, "Neutral"), _cell(2, 1, ""), _cell(2, 2, "earthed"), _cell(2, 3, ""),
        _cell(2, 4, "Short-circuit point", colspan=3), _cell(2, 7, "-"),
    ]
    table = {"index": 3, "depth": 1, "container": None, "rows": 3, "cols": 8, "width": 1, "height": 1, "cells": cells}
    inventory = {"tables": [table], "pictures": [], "paragraphs": [{"text": "Load circuit", "container": {"table": 3, "row": 0, "col": 5}}]}
    pdf = _pdf_table()
    pdf["section"] = "Load circuit"
    pdf["rows"] = [_pdf_row(1, "Short-circuit point", "", "earthed")]
    block = section_blocks(table, ["Supply circuit", "Load circuit"])["Load circuit"]
    changes, warnings = section_changes(pdf, table, block, inventory)
    by = {(c["hwp"]["address"], c["field"]): c for c in changes}
    assert by[("E3", "label+unit")]["no_op"]
    assert by[("H3", "value")]["before"] == "-" and by[("H3", "value")]["after"] == "earthed"
    assert {c["hwp"]["address"] for c in changes if "clear_not_in_pdf" in c["flags"]} == {"F2", "G2", "H2"}
    assert warnings == []
