from dongdongs.hwp.mapping import build_candidates, cell_address, section_blocks, section_changes


def _cell(row, col, text, colspan=1, rowspan=1):
    return {"row": row, "col": col, "rowspan": rowspan, "colspan": colspan, "width": 100, "height": 100, "text": text}


def _inventory():
    cells = [
        _cell(0, 0, "Supply circuit", colspan=3),
        _cell(1, 0, "Impedance"), _cell(1, 1, "\u2126"), _cell(1, 2, "1.0"),
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
    assert [{k: v for k, v in p.items() if k != "section"} for p in result["pairs"]] == [{"pdf_page": 5, "hwp_table": 5, "method": "document_order", "label_similarity": 0.5}]
    assert result["mode"] == "whole" and result["scopes"][0]["key"] == "all"
    assert all("watermark_manual_required_on_source_page" in c["flags"] for c in result["changes"])


def test_lookalike_units_outside_the_charmap_are_flagged_not_hidden():
    inventory = _inventory()
    table = inventory["tables"][0]
    table["cells"][2]["text"] = "\u2160"  # ROMAN NUMERAL ONE in the HWP (not in charmap)
    pdf = _pdf_table()
    pdf["rows"][0]["unit"] = "I"
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
    assert by[(1, "label+unit")]["after"] == "Impedance                  \u2126"
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


def test_fit_picture_keeps_the_pdf_aspect_ratio():
    from dongdongs.hwp.mapping import fit_picture

    fit = fit_picture([0, 0, 480, 330], 168.8, 98.0)  # 169.3 x 116.4 mm natural
    assert fit["natural_width_mm"] == 169.33 and fit["natural_height_mm"] == 116.42
    assert fit["height_mm"] == 98.0 and 0.84 < fit["scale"] < 0.85 and abs(fit["width_mm"] - 169.33 * fit["scale"]) < 0.1
    assert abs(fit["width_mm"] / fit["height_mm"] - 480 / 330) < 0.01
    natural = fit_picture([0, 0, 480, 330], 200.0, 200.0)
    assert natural["scale"] > 1 and natural["width_mm"] == 200.0
    forced = fit_picture([0, 0, 240, 330], 83.65, 98.0, scale=0.5)
    assert forced["scale"] == 0.5 and forced["width_mm"] == round(240 / (72 / 25.4) * 0.5, 2)


def _graph_regions(page, layouts):
    boxes = {"full": [86, 106, 566, 433], "half-left": [86, 435, 324, 762], "half-right": [327, 435, 566, 762]}
    return [{"page": page, "index": i, "kind": "oscillogram", "layout": l, "bbox": boxes[l], "title": f"Osc. X-{page:03d}" if i == 0 else None, "png": f"images/p{page:03d}-{i}.png", "export": True} for i, l in enumerate(layouts)]


def _graph_page_inventory(titles):
    tables, paragraphs = [], []
    for i, title in enumerate(titles):
        cells = [{"row": r, "col": 0, "rowspan": 1, "colspan": 1, "width": 48880, "height": 60070 if r == 3 else 1000, "text": ("\n" + title + "\n") if r == 3 else f"h{r}"} for r in range(4)]
        tables.append({"index": i, "depth": 0, "page_no": i + 1, "frame": i, "container": None, "rows": 4, "cols": 1, "width": 1, "height": 1, "cells": cells})
        paragraphs.append({"text": title, "container": {"table": i, "row": 3, "col": 0}})
    return {"table_count": len(tables), "picture_count": 0, "tables": tables, "pictures": [], "paragraphs": paragraphs}


def test_graph_pages_are_planned_in_order_and_missing_pages_are_added():
    from dongdongs.hwp.mapping import plan_oscillogram_pages

    regions = _graph_regions(22, ["full", "half-left", "half-right"]) + _graph_regions(23, ["full", "full"]) + _graph_regions(24, ["full"])
    inventory = _graph_page_inventory(["Osc. OLD-1", "Osc. OLD-2"])
    cfg = {"inner_width_mm": 168.8, "gap_mm": 1.5, "reserved_height_mm": 14.0, "padding_height_mm": 1.0}
    changes, warnings = plan_oscillogram_pages(regions, inventory, cfg, {})
    assert [c["source"]["pdf_page"] for c in changes] == [22, 23, 24]
    assert [c["hwp"]["page_no"] for c in changes] == [1, 2, 3]
    assert changes[0]["before"] == "Osc. OLD-1" and changes[0]["after"] == "Osc. X-022"
    assert [p["layout"] for p in changes[0]["pictures"]] == ["full", "half-left", "half-right"]
    first = changes[0]["pictures"]
    assert len({p["scale"] for p in first}) == 1 and first[0]["scale"] == changes[0]["hwp"]["page_scale"]
    assert first[1]["width_mm"] + 1.5 + first[2]["width_mm"] <= 168.8 and first[0]["width_mm"] <= 168.8
    assert first[0]["height_mm"] + first[1]["height_mm"] <= changes[0]["hwp"]["available_height_mm"]
    assert all(abs(p["width_mm"] / p["height_mm"] - (p["bbox"][2] - p["bbox"][0]) / (p["bbox"][3] - p["bbox"][1])) < 0.01 for c in changes for p in c["pictures"])
    assert all(0.8 < p["scale"] <= 1.0 for c in changes for p in c["pictures"])
    assert changes[2]["hwp"]["page_to_be_added"] and changes[2]["hwp"]["copies_after_anchor"] == 1 and "page_to_be_added" in changes[2]["flags"]
    assert changes[2]["anchor"]["text"] == "Osc. OLD-2"
    assert any("1 pages will be added" in w for w in warnings)
    assert all(c["status"] == "review_required" for c in changes)


def test_untitled_oscillograms_go_to_slot_tables_in_order():
    from dongdongs.hwp.mapping import plan_oscillogram_pages, plan_picture_slots
    from dongdongs.hwp.inspector import picture_slots

    inventory = _graph_page_inventory(["Osc. OLD-1"])
    slot_cells = [{"row": r, "col": c, "rowspan": 1, "colspan": 1, "width": 20000, "height": 10000, "text": ""} for r in (1, 2) for c in (0, 1)]
    cells = [{"row": 0, "col": 0, "rowspan": 1, "colspan": 2, "width": 40000, "height": 1500, "text": "오실로그램"}, *slot_cells,
             {"row": 3, "col": 0, "rowspan": 1, "colspan": 2, "width": 40000, "height": 1500, "text": "Osc.No.01 (01 ~ 04)"}]
    inventory["tables"].append({"index": 1, "depth": 1, "page_no": 5, "frame": 1, "container": None, "rows": 4, "cols": 2, "width": 1, "height": 1, "cells": cells})
    inventory["paragraphs"].append({"text": "오실로그램", "container": {"table": 1, "row": 0, "col": 0}})
    for i, cell in enumerate(slot_cells):
        inventory["pictures"].append({"index": i, "bindata_id": 50 + i, "width": 20700, "height": 10500, "treat_as_char": None, "flow": "block", "container": {"table": 1, "row": cell["row"], "col": cell["col"]}, "page_no": 5})
    slots = picture_slots(inventory)
    assert [(s["row"], s["col"]) for s in slots] == [(1, 0), (1, 1), (2, 0), (2, 1)] and slots[0]["caption"] == "Osc.No.01 (01 ~ 04)"
    titled = _graph_regions(22, ["full", "half-left", "half-right"])
    untitled = [dict(r, page=30, title=None, png=f"images/p030-{r['index']}.png") for r in _graph_regions(30, ["full", "full"])]
    pages, _ = plan_oscillogram_pages(titled + untitled, inventory, {}, {})
    assert [c["source"]["pdf_page"] for c in pages] == [22]
    used = {p["png"] for c in pages for p in c["pictures"]}
    changes, warnings = plan_picture_slots(titled + untitled, slots, {}, used)
    assert [c["after_png"] for c in changes] == ["images/p030-0.png", "images/p030-1.png"]
    assert changes[0]["hwp"]["address"] == "A2" and changes[0]["anchor"]["text"] == "오실로그램" and "slot_paired_by_order" in changes[0]["flags"]
    assert changes[0]["target"]["scale"] < 1 and abs(changes[0]["target"]["width_mm"] / changes[0]["target"]["height_mm"] - 480 / 327) < 0.01
    assert warnings[0].startswith("HWP 오실로그램 칸 4개, PDF 미배정 그래프 2장")
