"""Property tests for graph-page planning: titles are compared whole, never as prefixes."""
from hypothesis import example, given, settings
from hypothesis import strategies as st

from dongdongs.hwp.mapping import plan_oscillogram_pages

CFG = {"inner_width_mm": 168.8, "gap_mm": 1.5, "reserved_height_mm": 14.0, "padding_height_mm": 1.0}


def _inventory(titles):
    tables, paragraphs = [], []
    for i, title in enumerate(titles):
        cells = [
            {"row": r, "col": 0, "rowspan": 1, "colspan": 1, "width": 48880, "height": 60070 if r == 3 else 1000, "text": ("\n" + title + "\n") if r == 3 else f"h{r}"}
            for r in range(4)
        ]
        tables.append({"index": i, "depth": 0, "page_no": i + 1, "frame": i, "container": None, "rows": 4, "cols": 1, "width": 1, "height": 1, "cells": cells})
        paragraphs.append({"text": title, "container": {"table": i, "row": 3, "col": 0}})
    return {"table_count": len(tables), "picture_count": 0, "tables": tables, "pictures": [], "paragraphs": paragraphs}


def _regions(count):
    return [
        {"page": 20 + i, "index": 0, "kind": "oscillogram", "layout": "full", "bbox": [50.0, 100.0, 500.0, 400.0], "title": f"Osc. X-{i:03d}", "png": f"images/p{i:03d}-0.png", "export": True}
        for i in range(count)
    ]


def _shared_title_warnings(warnings):
    return [w for w in warnings if "share the titles" in w or "appear more than once" in w]


@settings(max_examples=200, deadline=None)
@example([1, 10])
@example([2, 20, 200])
@given(st.lists(st.integers(min_value=1, max_value=999), min_size=2, max_size=6, unique=True))
def test_distinct_graph_titles_are_never_reported_as_shared(numbers):
    titles = [f"Osc. {n}" for n in numbers]
    _, warnings = plan_oscillogram_pages(_regions(len(titles)), _inventory(titles), CFG, {})
    assert not _shared_title_warnings(warnings), warnings


@settings(max_examples=50, deadline=None)
@given(st.integers(min_value=1, max_value=999), st.integers(min_value=1, max_value=999))
def test_a_repeated_graph_title_is_reported(n, other):
    titles = [f"Osc. {n}", f"Osc. {n}"] + ([f"Osc. {other}"] if other != n else [])
    _, warnings = plan_oscillogram_pages(_regions(len(titles)), _inventory(titles), CFG, {})
    assert _shared_title_warnings(warnings)
