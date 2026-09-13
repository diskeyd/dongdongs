import json
import os
import zipfile

from dongdongs.support import build_report_zip, latest_job, load_env_file, parse_env_text, redact_text


def test_parse_env_text_handles_quotes_comments_and_blank_values():
    text = "# comment\nGEMINI_API_KEY='abc def'\nDONGDONGS_GEMINI_MODEL=gemini-x # trailing\nEMPTY=\n"
    assert parse_env_text(text) == {"GEMINI_API_KEY": "abc def", "DONGDONGS_GEMINI_MODEL": "gemini-x", "EMPTY": ""}


def test_load_env_file_never_overrides_existing_variables(tmp_path, monkeypatch):
    env = tmp_path / "dongdongs.env"
    env.write_text("GEMINI_API_KEY=from-file\nDONGDONGS_GEMINI_MODEL=m1\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")
    monkeypatch.delenv("DONGDONGS_GEMINI_MODEL", raising=False)
    assert load_env_file(env) == ["DONGDONGS_GEMINI_MODEL"]
    assert os.environ["GEMINI_API_KEY"] == "from-shell" and os.environ["DONGDONGS_GEMINI_MODEL"] == "m1"


def _fake_job(root, name="job-1"):
    job = root / "work" / name
    for sub in ("cleaned_pdf", "images", "previews", "logs", "result"):
        (job / sub).mkdir(parents=True)
    manifest = {
        "job_id": name,
        "institution": "KERI",
        "inputs": {
            "pdf": {"path": "/Users/someone/Downloads/고객사 Draft.PDF", "name": "고객사 Draft.PDF", "bytes": 1, "sha256": "x"},
            "hwp": {"path": "/Users/someone/Downloads/보고서_고객사.hwp", "name": "보고서_고객사.hwp", "bytes": 1, "sha256": "y"},
        },
        "steps": [{"step": "init", "at": "t", "institution": "KERI"}],
    }
    (job / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (job / "environment.json").write_text("{}", encoding="utf-8")
    (job / "extracted_values.json").write_text(json.dumps({"tables": [{"rows": [{"value": "4.84"}]}]}), encoding="utf-8")
    (job / "hwp_inventory.json").write_text(json.dumps({"tables": [{"cells": [{"text": "성적서 번호 : 기용9999"}]}]}), encoding="utf-8")
    (job / "watermark_report.json").write_text(json.dumps({"source_pdf": "고객사 Draft.PDF", "overall": "removed"}, ensure_ascii=False), encoding="utf-8")
    (job / "cleaned_pdf" / "고객사 Draft.cleaned.pdf").write_bytes(b"%PDF")
    (job / "images" / "p022-0-oscillogram.png").write_bytes(b"\x89PNG")
    (job / "result" / "보고서_고객사.processed.hwp").write_bytes(b"hwp")
    (job / "logs" / "run-20260913-120000-analyze.log").write_text("표 17개 · 원본 고객사 Draft.PDF\n오류: 보고서_고객사.hwp 를 열 수 없음\n", encoding="utf-8")
    (job / "logs" / "hwp_structure.xml").write_text("<x/>", encoding="utf-8")
    return job


def test_report_zip_holds_no_data_files_and_no_input_names(tmp_path, monkeypatch):
    job = _fake_job(tmp_path)
    monkeypatch.setattr("dongdongs.support.project_root", lambda start=None: tmp_path)
    (tmp_path / "dongdongs.env").write_text("GEMINI_API_KEY=secret-123\n", encoding="utf-8")
    out = build_report_zip(job, tmp_path / "reports")
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        blob = b"".join(zf.read(n) for n in names).decode("utf-8")
    assert "report.txt" in names and "job/manifest.json" in names and "logs/job/run-20260913-120000-analyze.log" in names
    assert not any(n.endswith((".pdf", ".hwp", ".png", ".xml")) for n in names)
    assert "job/extracted_values.json" not in names and "job/hwp_inventory.json" not in names
    assert "고객사" not in blob and "secret-123" not in blob and "/Users/someone" not in blob
    assert "<pdf>" in blob and "<set>" in blob


def test_full_report_includes_values_and_is_labelled(tmp_path, monkeypatch):
    job = _fake_job(tmp_path)
    monkeypatch.setattr("dongdongs.support.project_root", lambda start=None: tmp_path)
    out = build_report_zip(job, tmp_path / "reports", full=True)
    assert out.name.endswith("-full.zip")
    with zipfile.ZipFile(out) as zf:
        assert "job/extracted_values.json" in zf.namelist()
        assert "공개 이슈에 올리지 말 것" in zf.read("report.txt").decode("utf-8")


def test_latest_job_and_redact():
    assert redact_text("GEMINI_API_KEY=abc", {}) == "GEMINI_API_KEY=<redacted>"
    assert latest_job(__import__("pathlib").Path("/nonexistent")) is None


def test_report_zip_name_and_summary_never_carry_the_input_name(tmp_path, monkeypatch):
    job = _fake_job(tmp_path, name="20260913-고객사 Draft")
    monkeypatch.setattr("dongdongs.support.project_root", lambda start=None: tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "run-20260913-110000-init.log").write_text("# argv: init --pdf <file.pdf>\n오류: 고객사 Draft.PDF 없음\n", encoding="utf-8")
    out = build_report_zip(job, tmp_path / "reports")
    assert "고객사" not in out.name
    with zipfile.ZipFile(out) as zf:
        blob = b"".join(zf.read(n) for n in zf.namelist()).decode("utf-8")
    assert "고객사" not in blob


def test_scrub_argv_hides_file_names():
    from dongdongs.support import _scrub_argv

    assert _scrub_argv(["init", "--pdf", "C:\\input\\고객사 Draft.PDF", "--hwp", "보고서.hwp", "--job-id", "20260913-1200"]) == ["init", "--pdf", "<file.pdf>", "--hwp", "<file.hwp>", "--job-id", "20260913-1200"]
