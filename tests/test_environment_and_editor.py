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
