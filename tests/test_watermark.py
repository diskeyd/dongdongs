import copy

import pymupdf

from dongdongs.pdf.watermark import apply_removal, plan_removal
from dongdongs.verify import compare_clean


def test_plan_matches_every_drawn_watermark(cleaned, expected):
    e = expected["watermark"]
    _, report = cleaned
    assert report["counts"] == e["counts"]
    assert report["overall"] == "removed"
    assert [p["page"] for p in report["pages"] if p["status"] == "reference_only"] == e["reference_only_pages"]
    assert report["protected_ocgs"] == e["protected_ocgs"]


def test_cleaned_pdf_has_no_watermark_object_left(cleaned, expected):
    e = expected["watermark"]
    out, _ = cleaned
    name = e["xobject_name"].encode()
    with pymupdf.open(out) as doc:
        assert not any(name in doc.xref_stream(s) for page in doc for s in page.get_contents())
        assert not [im for page in doc for im in page.get_images(full=True) if [im[2], im[3]] == e["image_size"]]
        assert set(e["protected_ocgs"].values()) <= {v["name"] for v in doc.get_ocgs().values()}


def test_no_alteration_oracle_on_sample_pages(fixture_pdf, cleaned, keri, expected):
    out, report = cleaned
    result = compare_clean(fixture_pdf, out, report, keri, dpi=72, pages=expected["watermark"]["oracle_pages"])
    assert result["passed"], result["pages"]
    assert result["pixel_diff_outside_wm"] == 0
    assert result["footer_present"] and result["protected_objects_kept"]


def test_wrong_image_hash_deletes_nothing(fixture_pdf, keri, expected):
    rules = copy.deepcopy(keri)
    rules["watermarks"][0]["image"]["sha256"] = "0" * 64
    with pymupdf.open(fixture_pdf) as doc:
        plan = plan_removal(doc, rules)
        assert plan["counts"] == {"no_watermark": expected["watermark"]["page_count"]}
        assert apply_removal(doc, plan) == {"streams_edited": 0, "resource_entries_removed": 0}


def test_unmet_draw_condition_sends_pages_to_manual_review(fixture_pdf, keri, expected):
    rules = copy.deepcopy(keri)
    rules["watermarks"][0]["draw"]["after_marker"] = "%NOT-PRESENT"
    with pymupdf.open(fixture_pdf) as doc:
        plan = plan_removal(doc, rules)
        assert plan["counts"].get("delete", 0) == 0
        assert plan["counts"]["review_required"] == expected["watermark"]["counts"]["delete"]
        assert plan["overall"] == "manual_required"
        assert apply_removal(doc, plan)["streams_edited"] == 0
