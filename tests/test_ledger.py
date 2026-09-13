import pymupdf

from dongdongs.job import create_job, report_stem, sha256_file, write_json
from dongdongs.ledger import compact_numbers, list_ledgers, numbers_with_status, parse_numbers, section_counts, update_ledger, usable_latest


def test_report_stem_drops_result_suffixes():
    assert report_stem("보고서.hwp") == "보고서"
    assert report_stem("보고서.processed.hwp") == "보고서"
    assert report_stem("보고서.processed.processed.hwp") == "보고서"
    assert report_stem("보고서.before.hwp") == "보고서"


def test_compact_numbers():
    assert compact_numbers([12, 1, 8, 10, 11]) == "1, 8, 10–12"
    assert compact_numbers([]) == ""


def test_parse_numbers_keeps_the_order_given():
    assert parse_numbers("2, 10-12") == [2, 10, 11, 12]
    assert parse_numbers("3,0") == [3, 0]
    assert parse_numbers("2;3") is None and parse_numbers("") is None


def _job(tmp_path, name="t1", hwp_name="보고서.hwp", parent=None):
    pdf = tmp_path / f"{name}.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pdf)
    hwp = tmp_path / hwp_name
    if not hwp.exists():
        hwp.write_bytes(b"hwp original")
    return create_job(tmp_path / "work", pdf, hwp, job_id=name, parent_job=parent)


def _write_run(job, sections_applied, blocked_section=None, held_section=None):
    scopes = [{"key": f"s{n}", "method": "code", "no": n, "code": f"T{n}", "title": f"{n}. 시험{n}", "pdf_ranges": [[n, n]], "hwp_ranges": [[n, n]]} for n in sections_applied]
    changes = [{"id": f"c{n}", "kind": "set_cell_text", "section": {"key": f"s{n}", "no": n}, "status": "review_required", "flags": []} for n in sections_applied]
    if blocked_section:
        changes.append({"id": "g", "kind": "fill_oscillogram_page", "section": {"key": f"s{blocked_section}", "no": blocked_section}, "status": "blocked", "flags": ["no_graph_page_in_section"]})
    if held_section:
        changes.append({"id": "h", "kind": "set_cell_text", "section": {"key": f"s{held_section}", "no": held_section}, "status": "review_required", "flags": []})
    decisions = [{"id": c["id"], "decision": "hold" if c["id"] == "h" else "approve"} for c in changes if c["status"] != "blocked"]
    write_json(job.path("approved_changes.json"), {"changes": decisions})
    write_json(job.path("mapping_candidates.json"), {
        "scopes": scopes,
        "hwp_sections": [{"no": n, "title": f"{n}. 시험{n}", "code": None, "page_from": n, "page_to": n} for n in (1, 2, 3, 4)],
        "changes": changes,
    })
    processed = job.path("result", f"{report_stem(job.hwp)}.processed.hwp")
    processed.write_bytes(b"processed " + job.root.name.encode())
    write_json(job.path("apply_log.json"), {
        "processed_hwp": str(processed),
        "changes": [{**c, "apply_status": "applied"} for c in changes if c["status"] != "blocked" and c["id"] != "h"],
    })
    return processed


def test_ledger_records_sections_and_the_newest_result(tmp_path):
    first = _job(tmp_path, "t1")
    processed = _write_run(first, [2, 3], blocked_section=3)
    path, ledger = update_ledger(first)
    assert path.name == "보고서.json" and path.parent.name == "_reports"
    assert {k: v["status"] for k, v in ledger["sections"].items()} == {"1": "pending", "2": "done", "3": "blocked", "4": "pending"}
    assert section_counts(ledger) == {"total": 4, "done": 1, "partial": 0, "blocked": 1, "pending": 2}
    work = tmp_path / "work"
    assert usable_latest(ledger, work) == processed and ledger["latest"]["processed_hwp"] == "t1/result/보고서.processed.hwp"

    # the next test report continues from the previous result: same ledger, sections accumulate
    second = _job(tmp_path, "t2", hwp_name="t1-result.processed.hwp", parent="t1")
    second.update(inputs={**second.manifest()["inputs"], "hwp": {**second.manifest()["inputs"]["hwp"], "path": str(processed)}})
    assert second.manifest()["parent_job"] == "t1" and second.manifest()["inputs"]["hwp"]["role"] == "processed_of:t1"
    newer = _write_run(second, [1])
    _, ledger = update_ledger(second)
    assert numbers_with_status(ledger, "done") == [1, 2] and numbers_with_status(ledger, "pending") == [4]
    assert usable_latest(ledger, work) == newer and [h["job"] for h in ledger["history"]] == ["t1", "t2"]
    assert len(list_ledgers(work)) == 1

    newer.write_bytes(b"changed by hand")
    assert usable_latest(ledger, work) is None
    assert sha256_file(processed)


def test_a_section_with_held_items_is_only_partial(tmp_path):
    job = _job(tmp_path, "t1")
    _write_run(job, [2, 3], held_section=3)
    _, ledger = update_ledger(job)
    assert numbers_with_status(ledger, "done") == [2] and numbers_with_status(ledger, "partial") == [3]


def _candidates(job, mode, scopes, sections=(1, 2, 3)):
    write_json(job.path("mapping_candidates.json"), {
        "mode": mode, "scopes": scopes, "warnings": [],
        "hwp_sections": [{"no": n, "title": f"시험{n}", "code": None, "page_from": n, "page_to": n} for n in sections],
    })


def test_wizard_never_accepts_an_empty_section_choice(tmp_path, monkeypatch):
    from dongdongs import wizard

    job = _job(tmp_path, "t1")
    _candidates(job, "whole", [{"key": "all", "no": None, "title": "문서 전체"}])
    calls = []

    def fake_main(argv):
        calls.append(argv)
        _candidates(job, "user", [{"key": "s2-3", "no": "2,3", "title": "시험2 / 시험3"}])
        return 0

    answers = iter(["", "9", "2,3", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert wizard.confirm_sections(job.root, fake_main, False) is True
    assert len(calls) == 1 and calls[0][-2:] == ["--sections", "2,3"]


def test_wizard_asks_one_section_per_listed_test_and_can_stop(tmp_path, monkeypatch):
    from dongdongs import wizard

    job = _job(tmp_path, "t1")
    write_json(job.path("sections.json"), {"found": True, "sections": [{"title": "시험A (TDa)"}, {"title": "시험B (TDb)"}]})
    _candidates(job, "auto", [])
    calls = []

    def fake_main(argv):
        calls.append(argv)
        _candidates(job, "user", [{"key": "s2", "no": 2, "title": "시험2", "pdf_title": "시험A (TDa)"}])
        return 0

    answers = iter(["2", "2,0", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert wizard.confirm_sections(job.root, fake_main, False) is True
    assert [c[-1] for c in calls] == ["2,0"]
    _candidates(job, "auto", [])
    monkeypatch.setattr("builtins.input", lambda prompt="": "q")
    assert wizard.confirm_sections(job.root, fake_main, False) is False


def test_wizard_offers_to_continue_the_report(tmp_path, monkeypatch):
    from dongdongs import wizard

    job = _job(tmp_path, "t1")
    processed = _write_run(job, [2])
    update_ledger(job)
    answers = iter([""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert wizard.choose_report(tmp_path / "work") == (processed, "t1")
    answers = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert wizard.choose_report(tmp_path / "work") == (None, None)
    assert wizard.choose_report(tmp_path / "empty") == (None, None)
