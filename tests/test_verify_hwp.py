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
    result = compare_hwp(before, after, [])
    assert not result["passed"] and result["cell_size_changes"] and result["structure_problems"]
