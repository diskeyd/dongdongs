import pytest

from dongdongs.hwp.inspector import build_inventory, export_xml, occurrence_of, tables_with_cell


@pytest.fixture(scope="module")
def inventory(fixture_hwp, tmp_path_factory):
    xml = export_xml(fixture_hwp, tmp_path_factory.mktemp("hwp") / "structure.xml")
    return build_inventory(xml, fixture_hwp.name)


def test_counts(inventory, expected):
    counts = (inventory["table_count"], inventory["picture_count"], inventory["cell_count"])
    assert list(counts) == expected["hwp"]["counts"]


def test_section_tables_and_anchor_order(inventory, expected):
    e = expected["hwp"]
    tables = [t["index"] for t in tables_with_cell(inventory, e["anchor"])]
    assert tables == e["anchor_tables"]
    assert [occurrence_of(inventory, e["anchor"], i, 0, 0) for i in tables] == list(range(1, len(tables) + 1))


def test_pictures_sit_in_first_cell_of_their_tables(inventory, expected):
    e = expected["hwp"]
    tables = {t["index"] for t in tables_with_cell(inventory, e["picture_anchor"])}
    assert len(tables) == e["picture_tables"]
    first_cells = [p for p in inventory["pictures"] if p["container"] and p["container"]["table"] in tables and p["container"]["row"] == 0]
    assert len(first_cells) == e["picture_tables"]


def test_pages_and_graph_pages(inventory, expected):
    from dongdongs.hwp.inspector import oscillogram_pages

    e = expected["hwp"]
    assert inventory["page_count"] == e["page_count"]
    pages = oscillogram_pages(inventory)
    assert len(pages) == e["graph_pages"] and pages[0]["page_no"] == e["first_graph_page"]
    assert all(p["row"] == 3 and p["col"] == 0 for p in pages)
