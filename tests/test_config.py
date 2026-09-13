from dongdongs.config import institution, load_config, with_defaults


def test_an_institution_overrides_only_what_differs():
    config = {"defaults": {"tables": {"known_sections": ["A"]}, "regions": {"dpi": 300, "min_width_pt": 200}},
              "institutions": {"X": {"regions": {"dpi": 150}, "watermarks": []}}}
    rules = institution(config, "X")
    assert rules["tables"] == {"known_sections": ["A"]} and rules["regions"] == {"dpi": 150, "min_width_pt": 200}
    assert config["defaults"]["regions"]["dpi"] == 300


def test_an_unlisted_institution_still_has_every_rule_needed_to_reach_review():
    rules = with_defaults(load_config())
    assert {"tables", "regions", "pictures"} <= set(rules) and not rules.get("watermarks") and not rules.get("sections")
