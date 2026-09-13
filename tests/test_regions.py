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
