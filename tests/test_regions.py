import pymupdf
import pytest

from dongdongs.pdf.regions import find_regions


def _regions(pdf, keri, page):
    with pymupdf.open(pdf) as doc:
        return find_regions(doc[page - 1], keri["regions"])


def test_circuit_diagram_region_includes_outline_and_excludes_title(fixture_pdf, keri, expected):
    e = expected["regions"]["circuit"]
    (region,) = _regions(fixture_pdf, keri, e["page"])
    assert region["kind"] == "circuit_diagram" and region["title"] == e["title"]
    assert region["bbox"] == pytest.approx(e["bbox"], abs=0.05)
    assert region["images"] == e["images"]
    assert region["export"]


def test_two_oscillograms_on_one_page_are_both_exported(fixture_pdf, keri, expected):
    e = expected["regions"]["two_oscillograms"]
    first, second = _regions(fixture_pdf, keri, e["page"])
    assert first["kind"] == second["kind"] == "oscillogram"
    assert first["title"] == e["first_title"]
    assert second["title"] is None and second["kind_source"].startswith("same width")
    assert first["export"] and second["export"]
    assert first["bbox"][3] <= second["bbox"][1]


def test_full_width_graph_with_two_half_width_below(fixture_pdf, keri, expected):
    e = expected["regions"]["three_on_one_page"]
    regions = _regions(fixture_pdf, keri, e["page"])
    assert [r["kind"] for r in regions] == ["oscillogram"] * 3
    assert [r["layout"] for r in regions] == e["layouts"]
    assert [round(r["bbox"][2] - r["bbox"][0]) for r in regions] == pytest.approx(e["widths"], abs=2)
    assert regions[0]["title"] and regions[1]["title"] is None and regions[2]["title"] is None
    assert all(r["export"] for r in regions)


def test_oscillogram_totals_over_the_document(fixture_pdf, keri, expected):
    from collections import Counter

    from dongdongs.pdf.regions import find_document_regions

    e = expected["regions"]
    osc = [r for r in find_document_regions(fixture_pdf, keri["regions"]) if r["kind"] == "oscillogram"]
    assert len(osc) == e["oscillogram_total"]
    per_page = Counter(Counter(r["page"] for r in osc).values())
    assert {str(k): v for k, v in per_page.items()} == e["oscillogram_pages"]
