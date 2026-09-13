import json
import threading
import urllib.error
import urllib.request

import pymupdf
import pytest

from dongdongs.job import create_job, read_json, write_json
from dongdongs.review.server import make_server, save_decisions


@pytest.fixture()
def job(tmp_path):
    pdf = tmp_path / "input.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pdf)
    job = create_job(tmp_path / "work", pdf, job_id="t1")
    (job.root / "previews" / "p.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    write_json(
        job.path("mapping_candidates.json"),
        {
            "pairs": [],
            "warnings": [],
            "unmapped_regions": [],
            "changes": [
                {"id": "c1", "kind": "set_cell_text", "field": "value", "hwp": {"table": 0, "row": 1, "col": 2, "address": "C2"}, "anchor": {}, "before": "1.0", "after": "2.00", "after_extracted": "2.00", "no_op": False, "source": {"pdf_page": 5}, "flags": [], "status": "review_required", "preview": "previews/p.png"},
                {"id": "c2", "kind": "replace_picture", "hwp": {"table": 1, "row": 0, "col": 0, "address": "A1"}, "anchor": {}, "source": {"pdf_page": 5}, "flags": [], "status": "blocked", "no_op": False},
            ],
        },
    )
    return job


def test_save_records_edits_and_refuses_blocked(job):
    result = save_decisions(job, {"reviewer": "kim", "decisions": {"c1": {"decision": "approve", "after": "2.000"}, "c2": {"decision": "approve"}, "zz": {"decision": "approve"}}})
    assert result["approved"] == 1 and result["held"] == 1
    saved = {c["id"]: c for c in read_json(job.path("approved_changes.json"))["changes"]}
    assert saved["c1"]["after"] == "2.000" and saved["c1"]["after_extracted"] == "2.00" and saved["c1"]["edited"]
    assert saved["c2"]["decision"] == "hold" and "approval_refused_item_is_blocked" in saved["c2"]["flags"]


def test_server_binds_localhost_and_blocks_traversal(job):
    server = make_server(job, port=0)
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert host == "127.0.0.1"
        page = urllib.request.urlopen(f"http://127.0.0.1:{port}/").read().decode("utf-8")
        assert "t1" in page and "C2" in page
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/files/previews/p.png").status == 200
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/files/previews/../manifest.json")
        assert err.value.code == 404
        request = urllib.request.Request(f"http://127.0.0.1:{port}/save", data=json.dumps({"decisions": {}}).encode(), headers={"Origin": "http://evil.example", "Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(request)
        assert err.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_page_groups_candidates_by_report_section(job):
    from dongdongs.review.server import render_page

    data = read_json(job.path("mapping_candidates.json"))
    data.update(
        mode="auto",
        scopes=[{"key": "s2", "method": "code", "no": 2, "code": "TDb", "title": "시험B(TDb)", "pdf_ranges": [[5, 9]], "hwp_ranges": [[3, 4]]}],
        hwp_sections=[{"no": n, "title": f"시험{n}", "code": None, "page_from": n, "page_to": n} for n in (1, 2, 3, 4, 5)],
        pending_sections=[1, 3, 4, 5],
    )
    for change in data["changes"]:
        change["section"] = {"key": "s2", "no": 2}
    write_json(job.path("mapping_candidates.json"), data)
    page = render_page(job)
    assert "2. 시험B(TDb)" in page and "표 칸 1 · 그림 1" in page
    assert "성적서가 아직 없는 구역 (손대지 않음): 1, 3–5" in page
