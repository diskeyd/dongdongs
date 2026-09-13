import pymupdf

from dongdongs.hwp.inspector import report_sections
from dongdongs.hwp.mapping import build_candidates, graph_page_positions, pair_sections, resolve_scopes
from dongdongs.pdf.sections import read_test_index


def _frame(index, page, lines):
    cells = [{"row": r, "col": 0, "rowspan": 1, "colspan": 1, "width": 48880, "height": 60070 if r == 3 else 1000, "text": lines if r == 3 else f"h{r}"} for r in range(4)]
    return {"index": index, "depth": 0, "page_no": page, "frame": index, "container": None, "rows": 4, "cols": 1, "width": 1, "height": 1, "cells": cells}


def _report(pages):
    """pages: list of the big-cell text of each page (one frame per page)."""
    tables = [_frame(i, i + 1, text) for i, text in enumerate(pages)]
    paragraphs = []
    for table in tables:
        for line in table["cells"][3]["text"].split("\n"):
            if line.strip():
                paragraphs.append({"text": line.strip(), "container": {"table": table["index"], "row": 3, "col": 0}})
    return {"table_count": len(tables), "picture_count": 0, "page_count": len(tables), "tables": tables, "pictures": [], "paragraphs": paragraphs}


def test_report_sections_need_consecutive_numbers_and_latin_codes():
    inventory = _report(["1. 외관검사(일반)", "2. 개폐시험(TDx1)", "body", "7. stray numbered line", "3. 루프시험(TDx2)", "body"])
    sections, warnings = report_sections(inventory)
    assert [(s["no"], s["code"], s["page_from"], s["page_to"]) for s in sections] == [(1, None, 1, 1), (2, "TDx1", 2, 4), (3, "TDx2", 5, 6)]
    assert sections[0]["name"] == "외관검사(일반)" and sections[1]["name"] == "개폐시험"


def test_report_sections_take_the_longest_increasing_run():
    sections, warnings = report_sections(_report(["3. 목차 항목", "1. 가시험(TDa)", "2. 나시험(TDb)", "3. 다시험(TDc)"]))
    assert [(s["no"], s["page_from"]) for s in sections] == [(1, 2), (2, 3), (3, 4)] and "not taken" in warnings[0]
    sections, warnings = report_sections(_report(["1. 가", "2. 나", "4. 라", "5. 마"]))
    assert [s["no"] for s in sections] == [1, 2, 4, 5] and any("[3]" in w for w in warnings)


def test_user_numbers_follow_the_pdf_test_order():
    hwp = [{"no": n, "title": f"{n}", "name": f"s{n}", "code": None, "page_from": n * 10, "page_to": n * 10 + 9} for n in (1, 2, 3)]
    pdf = {"sections": [{"title": "A", "name": "A", "code": None, "page_from": 5, "page_to": 9}, {"title": "B", "name": "B", "code": None, "page_from": 10, "page_to": 14}]}
    scopes, warnings, _ = resolve_scopes(pdf, hwp, [2])
    assert scopes == [] and "2 tests" in warnings[0]
    scopes, _, _ = resolve_scopes(pdf, hwp, [3, 0])
    assert [(s["no"], s["pdf_ranges"]) for s in scopes] == [(3, [[5, 9]])]
    assert resolve_scopes(pdf, hwp, [2, 2])[0] == [] and resolve_scopes(pdf, hwp, [2, 9])[0] == []


def test_whole_mode_never_calls_sections_untouched():
    inventory = _report(["1. 시험A(TDa)", "\nOsc. OLD-1\n", "2. 시험B(TDb)"])
    result = build_candidates({"tables": []}, [_graph(11)], inventory, [], {}, {}, None, report_sections(inventory)[0])
    assert result["mode"] == "whole" and result["pending_sections"] == []


def test_pair_sections_by_code_then_name_and_report_unpaired():
    hwp = [{"no": 2, "title": "2", "name": "부하전류 개폐시험", "code": "TDload2", "page_from": 1, "page_to": 5},
           {"no": 8, "title": "8", "name": "단시간 전류시험", "code": None, "page_from": 6, "page_to": 9}]
    pdf = [{"title": "부하전류개폐시험 (TDload2)", "name": "부하전류개폐시험", "code": "TDload2", "page_from": 10, "page_to": 20},
           {"title": "단시간전류시험", "name": "단시간전류시험", "code": None, "page_from": 21, "page_to": 30},
           {"title": "없는시험 (TDzz)", "name": "없는시험", "code": "TDzz", "page_from": 31, "page_to": 40}]
    pairs, warnings = pair_sections(pdf, hwp)
    assert [(p["hwp"]["no"], p["method"]) for p in pairs] == [(2, "code"), (8, "name")]
    assert len(warnings) == 1 and "TDzz" in warnings[0]


def test_user_chosen_sections_scope_the_report_pages():
    hwp = [{"no": n, "title": f"{n}", "name": f"s{n}", "code": None, "page_from": n * 10, "page_to": n * 10 + 9} for n in (1, 2, 3)]
    scopes, warnings, mode = resolve_scopes(None, hwp, [2, 3, 9])
    assert mode == "user" and len(scopes) == 1 and scopes[0]["hwp_ranges"] == [[20, 29], [30, 39]] and scopes[0]["pdf_ranges"] is None
    assert warnings and "[9]" in warnings[0]


def _graph(page, title=True):
    return {"page": page, "index": 0, "kind": "oscillogram", "layout": "full", "bbox": [86, 106, 566, 433], "title": f"Osc. N-{page:03d}" if title else None, "png": f"images/p{page:03d}.png", "export": True}


def test_graph_pages_stay_inside_their_section_and_later_pages_shift():
    # report: section 1 pages 1-3 (graph page on 2), section 2 pages 4-6 (graph page on 5), section 3 pages 7-8 (no graph page)
    inventory = _report(["1. 시험A(TDa)", "\nOsc. OLD-1\n", "note", "2. 시험B(TDb)", "\nOsc. OLD-2\n", "note", "3. 시험C(TDc)", "note"])
    hwp_sections, warnings = report_sections(inventory)
    pdf_index = {"found": True, "sections": [
        {"no": 1, "title": "시험A (TDa)", "name": "시험A", "code": "TDa", "page_from": 10, "page_to": 19},
        {"no": 2, "title": "시험B (TDb)", "name": "시험B", "code": "TDb", "page_from": 20, "page_to": 29},
        {"no": 3, "title": "시험C (TDc)", "name": "시험C", "code": "TDc", "page_from": 30, "page_to": 39}]}
    regions = [_graph(11), _graph(12), _graph(21), _graph(22), _graph(31)]
    result = build_candidates({"tables": []}, regions, inventory, [], {}, {}, pdf_index, hwp_sections)
    pages = {c["source"]["pdf_page"]: c for c in result["changes"] if c["kind"] == "fill_oscillogram_page"}
    assert result["mode"] == "auto" and [s["no"] for s in result["scopes"]] == [1, 2, 3]
    assert pages[11]["hwp"]["page_no_before"] == 2 and not pages[11]["hwp"]["page_to_be_added"]
    assert pages[12]["hwp"]["page_to_be_added"] and pages[12]["hwp"]["anchor_page"] == 2 and pages[12]["hwp"]["page_no_after"] == 3
    assert pages[12]["anchor"]["text"] == "Osc. OLD-1"
    # section 2's existing graph page moves down by the one copy made in section 1
    assert pages[21]["hwp"]["page_no_before"] == 5 and pages[21]["hwp"]["page_no_after"] == 6
    assert pages[22]["hwp"]["anchor_page"] == 5 and pages[22]["hwp"]["page_no_after"] == 7 and pages[22]["anchor"]["text"] == "Osc. OLD-2"
    # section 3 has no graph page: planned but blocked
    assert pages[31]["status"] == "blocked" and "no_graph_page_in_section" in pages[31]["flags"] and pages[31]["hwp"]["table"] is None
    assert result["pending_sections"] == []


def test_graph_pages_that_cannot_be_told_apart_or_hold_other_text_are_blocked():
    pdf_index = {"found": True, "sections": [
        {"no": 1, "title": "시험A (TDa)", "name": "시험A", "code": "TDa", "page_from": 10, "page_to": 19},
        {"no": 2, "title": "시험B (TDb)", "name": "시험B", "code": "TDb", "page_from": 20, "page_to": 29}]}
    inventory = _report(["1. 시험A(TDa)", "\nOsc. SAME\n", "2. 시험B(TDb)", "\nOsc. SAME\n"])
    result = build_candidates({"tables": []}, [_graph(11), _graph(12), _graph(21)], inventory, [], {}, {}, pdf_index, report_sections(inventory)[0])
    graph = [c for c in result["changes"] if c["kind"] == "fill_oscillogram_page"]
    assert len(graph) == 3 and all(c["status"] == "blocked" and "anchor_text_not_unique" in c["flags"] for c in graph)
    # "Osc. N-1" inside "Osc. N-10" is not a duplicate
    inventory = _report(["1. 시험A(TDa)", "\nOsc. N-1\n", "2. 시험B(TDb)", "\nOsc. N-10\n"])
    result = build_candidates({"tables": []}, [_graph(11), _graph(21)], inventory, [], {}, {}, pdf_index, report_sections(inventory)[0])
    assert all(c["status"] != "blocked" for c in result["changes"])
    inventory = _report(["1. 시험A(TDa)", "\nOsc. N-1\n시험 조건 12 kV\n"])
    result = build_candidates({"tables": []}, [_graph(11)], inventory, [], {}, {}, pdf_index, report_sections(inventory)[0])
    assert result["changes"][0]["status"] == "blocked" and "cell_has_other_text" in result["changes"][0]["flags"]


def test_graph_page_already_filled_is_no_op():
    inventory = _report(["1. 시험A(TDa)", "\nOsc. N-011\n"])
    inventory["pictures"].append({"index": 0, "bindata_id": 1, "width": 1, "height": 1, "container": {"table": 1, "row": 3, "col": 0}, "page_no": 2})
    pdf_index = {"found": True, "sections": [{"no": 1, "title": "시험A (TDa)", "name": "시험A", "code": "TDa", "page_from": 10, "page_to": 19}]}
    result = build_candidates({"tables": []}, [_graph(11)], inventory, [], {}, {}, pdf_index, report_sections(inventory)[0])
    assert result["changes"][0]["no_op"]


def test_positions_follow_the_copies_actually_made():
    changes = [
        {"id": "a", "kind": "fill_oscillogram_page", "hwp": {"page_no_before": 5, "anchor_page": 5, "copies_after_anchor": 3, "page_to_be_added": True}},
        {"id": "b", "kind": "fill_oscillogram_page", "hwp": {"page_no_before": 9, "page_to_be_added": False}},
    ]
    positions, counts = graph_page_positions(changes)
    assert counts == {5: 1} and positions == {"a": 6, "b": 10}
    positions, _ = graph_page_positions(changes, {5: 3})
    assert positions["b"] == 12


def test_pdf_test_index_reads_the_list_page_and_the_toc_end(tmp_path):
    pdf = tmp_path / "report.pdf"
    doc = pymupdf.open()
    pages = {
        1: "CONTENTS\nTEST RESULTS\n2\nDRAWINGS\n6",
        2: "TEST RESULTS\nitem\nplace\npage\n1\nLoad switching (TDa)\nLAB-1\n3\n2\nLoop switching (TDb)\nLAB-1\n4",
    }
    for number in range(1, 8):
        page = doc.new_page()
        page.insert_text((72, 72), pages.get(number, f"page {number}"))
    doc.save(pdf)
    rules = {"index_title": "TEST RESULTS", "code_pattern": r"\((TD\w+)\)", "end_titles": ["DRAWINGS"]}
    index = read_test_index(pdf, rules)
    assert index["found"] and index["index_page"] == 2 and index["end_page"] == 5 and index["end_source"] == "table_of_contents"
    assert [(t["no"], t["code"], t["name"], t["page_from"], t["page_to"]) for t in index["sections"]] == [(1, "TDa", "Load switching", 3, 3), (2, "TDb", "Loop switching", 4, 5)]
    assert not read_test_index(pdf, {})["found"]


def test_a_decimal_number_never_starts_a_section():
    inventory = _report(["25.8kV 개폐기", "1. 외관검사(일반)", "2. 개폐시험(TDx1)"])
    assert [(s["no"], s["page_from"]) for s in report_sections(inventory)[0]] == [(1, 2), (2, 3)]
