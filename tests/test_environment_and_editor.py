import json
import sys

import pytest

from dongdongs.environment import collect
from dongdongs.hwp.editor import EditorError, HwpEditor, _parse, prepare_result_copies


def test_environment_never_contains_key_value(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value-123")
    data = collect()
    assert data["gemini"] == {"api_key_present": True, "api_key_value_saved": False, "connectivity_test": "not-run"}
    assert "secret-value-123" not in json.dumps(data)


def test_address_parsing():
    assert _parse("A1") == (0, 0) and _parse("AB10") == (9, 27)
    with pytest.raises(EditorError):
        _parse("1A")


@pytest.mark.skipif(sys.platform == "win32", reason="guard applies to non-Windows systems")
def test_editor_refuses_outside_windows():
    with pytest.raises(EditorError):
        HwpEditor()


def test_result_copies_never_overwrite(tmp_path):
    original = tmp_path / "report.hwp"
    original.write_bytes(b"original bytes")
    before, processed = prepare_result_copies(original, tmp_path / "result")
    assert before.read_bytes() == processed.read_bytes() == original.read_bytes()
    with pytest.raises(EditorError):
        prepare_result_copies(original, tmp_path / "result")
    assert original.read_bytes() == b"original bytes"


def test_size_matches_within_one_percent():
    from dongdongs.hwp.editor import size_matches

    assert size_matches((45706, 17218), (45706, 17390))
    assert not size_matches((45706, 17218), (45706, 17800))


def test_apply_order_fills_a_sections_new_pages_before_its_anchor_page_is_retitled():
    from dongdongs.hwp.editor import _apply_order

    def graph(change_id, page, added=0):
        hwp = {"page_no_before": page, "page_to_be_added": bool(added), "copies_after_anchor": added}
        return {"id": change_id, "kind": "fill_oscillogram_page", "hwp": hwp}

    changes = [
        {"id": "cell", "kind": "set_cell_text", "hwp": {"table": 1}},
        graph("s3-anchor", 60), graph("s3-add2", 60, 2), graph("s3-add1", 60, 1),
        {"id": "circuit", "kind": "replace_picture", "hwp": {"table": 2}},
        graph("s2-anchor", 46), graph("s2-add1", 46, 1), graph("s2-page", 23),
    ]
    order = [c["id"] for c in sorted(changes, key=_apply_order)]
    assert order[:6] == ["s2-page", "s2-add1", "s2-anchor", "s3-add1", "s3-add2", "s3-anchor"]
    assert set(order[6:]) == {"cell", "circuit"}


def test_hancom_probe_says_windows_only_here():
    from dongdongs.hancom import probe

    status = probe()
    assert status["com_available"] is False and "Windows" in status["verdict"]
    assert status["python_bits"] in (32, 64)


def test_apply_summary_carries_no_document_text(tmp_path):
    """It goes into the default report zip, so no cell text, no graph titles."""
    import pymupdf

    from dongdongs.cli import apply_summary
    from dongdongs.job import create_job

    pdf = tmp_path / "t.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pdf)
    job = create_job(tmp_path / "work", pdf, None, job_id="t1")
    result = {
        "saved_changed_bytes": False,
        "changes": [{"id": "p11-graph-page", "kind": "fill_oscillogram_page", "section": {"no": 2}, "apply_status": "error",
                     "error": "occurrence 1 of 'Osc. AB12C3456-001' not found", "before": "Osc. AB12C3456-001", "after": "Osc. ZZ-1"}],
    }
    summary = apply_summary(job, result, {"error": 1})
    assert summary["changes"][0]["error"] == "occurrence 1 of '…' not found"
    assert "Osc. AB12C3456-001" not in json.dumps(summary, ensure_ascii=False)
    assert summary["saved_changed_bytes"] is False and summary["counts"] == {"error": 1}
