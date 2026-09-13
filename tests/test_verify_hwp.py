import copy

from dongdongs.verify import compare_hwp


def _inv():
    cells = [{"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "width": 10, "height": 10, "text": "a"}, {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "width": 10, "height": 10, "text": "1.0"}]
    return {"table_count": 1, "picture_count": 0, "tables": [{"index": 0, "rows": 1, "cols": 2, "cells": cells}], "pictures": []}


def _applied(after):
    return [{"hwp": {"table": 0, "row": 0, "col": 1}, "after": after, "apply_status": "applied"}]


def test_expected_change_passes():
    before, after = _inv(), _inv()
    after["tables"][0]["cells"][1]["text"] = "2.00"
    assert compare_hwp(before, after, _applied("2.00"))["passed"]


def test_unexpected_change_and_missing_value_fail():
    before, after = _inv(), copy.deepcopy(_inv())
    after["tables"][0]["cells"][0]["text"] = "changed"
    result = compare_hwp(before, after, _applied("2.00"))
    assert not result["passed"]
    assert result["unexpected_text_changes"] and result["applied_values_not_found"]


def test_structure_change_fails():
    before, after = _inv(), _inv()
    after["tables"][0]["cells"][1]["width"] = 20
    after["picture_count"] = 1
    after["pictures"].append({"index": 0, "bindata_id": 1, "width": 5, "height": 5, "container": None})
    result = compare_hwp(before, after, [])
    assert not result["passed"] and result["cell_size_changes"] and result["structure_problems"]


def _page_inventory(page_titles, pictures_per_page):
    """Top-level frame per page; big cell (3,0) holds the title; pictures anchored there."""
    tables, pictures = [], []
    for i, title in enumerate(page_titles):
        cells = [{"row": r, "col": 0, "rowspan": 1, "colspan": 1, "width": 100, "height": 100, "text": ("\n" + title + "\n") if r == 3 else f"h{r}"} for r in range(4)]
        tables.append({"index": i, "depth": 0, "page_no": i + 1, "frame": i, "rows": 4, "cols": 1, "cells": cells})
        for w, h in pictures_per_page[i]:
            pictures.append({"index": len(pictures), "bindata_id": 100 + len(pictures), "width": w, "height": h, "container": {"table": i, "row": 3, "col": 0}, "page_no": i + 1})
    return {"table_count": len(tables), "picture_count": len(pictures), "tables": tables, "pictures": pictures}


def test_filled_and_added_graph_pages_pass_when_they_match_the_plan():
    before = _page_inventory(["Osc. A-1", "Osc. A-2"], [[], []])
    plan = [
        {"id": "g1", "kind": "fill_oscillogram_page", "apply_status": "applied", "after": "Osc. B-1", "hwp": {"table": 0, "page_no": 1, "page_no_before": 1, "row": 3, "col": 0, "existing_pictures": 0, "page_to_be_added": False},
         "pictures": [{"width_hwpunit": 1000, "height_hwpunit": 500}, {"width_hwpunit": 490, "height_hwpunit": 500}, {"width_hwpunit": 490, "height_hwpunit": 500}]},
        {"id": "g3", "kind": "fill_oscillogram_page", "apply_status": "applied", "after": "Osc. B-3", "hwp": {"table": 1, "page_no": 3, "page_no_before": 2, "anchor_page": 2, "copies_after_anchor": 1, "row": 3, "col": 0, "existing_pictures": 0, "page_to_be_added": True},
         "pictures": [{"width_hwpunit": 1000, "height_hwpunit": 700}]},
    ]
    after = _page_inventory(["Osc. B-1", "Osc. A-2", "Osc. B-3"], [[(1000, 500), (490, 500), (490, 500)], [], [(1000, 703)]])
    result = compare_hwp(before, after, plan)
    assert result["passed"], result
    assert result["pages_added"] == [3]
    wrong = _page_inventory(["Osc. B-1", "Osc. A-2", "Osc. B-3"], [[(1000, 500), (490, 500)], [], [(1000, 703)]])
    assert not compare_hwp(before, wrong, plan)["passed"]


def test_replaced_picture_must_change_data_and_keep_size():
    before = _page_inventory(["x"], [[(800, 300)]])
    change = {"kind": "replace_picture", "apply_status": "applied", "hwp": {"table": 0, "row": 3, "col": 0}, "target": {"width_hwpunit": 800, "height_hwpunit": 300}}
    same = _page_inventory(["x"], [[(800, 300)]])
    assert not compare_hwp(before, same, [change])["passed"]  # bindata unchanged
    swapped = _page_inventory(["x"], [[(800, 302)]])
    swapped["pictures"][0]["bindata_id"] = 999
    assert compare_hwp(before, swapped, [change])["passed"]


def test_pictures_after_an_inserted_page_are_matched_by_shifted_index():
    before = _page_inventory(["Osc. A-1", "photo page"], [[], [(800, 300)]])
    plan = [{"id": "g2", "kind": "fill_oscillogram_page", "apply_status": "applied", "after": "Osc. B-2", "hwp": {"table": 0, "page_no": 2, "page_no_before": 1, "anchor_page": 1, "copies_after_anchor": 1, "row": 3, "col": 0, "existing_pictures": 0, "page_to_be_added": True},
             "pictures": [{"width_hwpunit": 1000, "height_hwpunit": 700}]}]
    after = _page_inventory(["Osc. A-1", "Osc. B-2", "photo page"], [[], [(1000, 700)], [(800, 300)]])
    result = compare_hwp(before, after, plan)
    assert result["passed"], result


def _added(change_id, title, anchor_page, rank=1):
    return {"id": change_id, "kind": "fill_oscillogram_page", "apply_status": "applied", "after": title,
            "hwp": {"table": None, "page_no": 0, "page_no_before": anchor_page, "anchor_page": anchor_page, "copies_after_anchor": rank, "row": 3, "col": 0, "existing_pictures": 0, "page_to_be_added": True},
            "pictures": [{"width_hwpunit": 1000, "height_hwpunit": 700}]}


def test_each_section_gets_its_copies_right_after_its_own_last_graph_page():
    # section 1 = pages 1-2, section 2 = pages 3-4; each section adds one graph page
    before = _page_inventory(["Osc. A-1", "other 1", "Osc. C-1", "other 2"], [[], [(800, 300)], [], [(800, 300)]])
    plan = [_added("s1", "Osc. B-1", 1), _added("s2", "Osc. D-1", 3)]
    copies = [{"anchor": "Osc. A-1", "anchor_page": 1, "count": 1}, {"anchor": "Osc. C-1", "anchor_page": 3, "count": 1}]
    good = _page_inventory(["Osc. A-1", "Osc. B-1", "other 1", "Osc. C-1", "Osc. D-1", "other 2"], [[], [(1000, 700)], [(800, 300)], [], [(1000, 700)], [(800, 300)]])
    result = compare_hwp(before, good, plan, copies)
    assert result["passed"], result
    assert result["pages_added"] == [2, 5]
    # both copies at the end of the document: wrong sections
    wrong = _page_inventory(["Osc. A-1", "other 1", "Osc. C-1", "other 2", "Osc. B-1", "Osc. D-1"], [[], [(800, 300)], [], [(800, 300)], [(1000, 700)], [(1000, 700)]])
    assert not compare_hwp(before, wrong, plan, copies)["passed"]
