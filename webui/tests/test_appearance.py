from __future__ import annotations

from webui.appearance import (
    color_hex,
    load_overrides,
    resolve_color,
    resolve_model,
    save_override,
)


def test_color_name_maps_to_hex():
    assert color_hex("green", "EXAMPLE") == "#7fb069"


def test_fallback_color_is_stable_for_device():
    first = color_hex("", "EXAMPLE0001")
    second = color_hex("", "EXAMPLE0001")
    assert first == second
    assert first.startswith("#")


def test_override_wins_for_color_and_model(tmp_path, make_profile):
    profile = make_profile("speaker-a")
    path = tmp_path / "appearance.json"
    save_override(path, profile.device_id, "purple", "Yandex Station Micro v1.2")
    overrides = load_overrides(path)
    item = overrides[profile.device_id]
    assert resolve_color(profile, item) == "#8e6bbf"
    assert resolve_model(profile, item) == "Yandex Station Micro v1.2"


def test_marketing_color_aliases():
    from webui.appearance import canonical_color, color_label

    assert color_hex("cappuccino", "EXAMPLE") == "#d9c3a5"
    assert color_label("cappuccino") == "Капучино"
    assert canonical_color("ультравиолет") == "purple"
    assert canonical_color("mint") == "green"


import pytest

from webui.appearance import canonical_color, color_label

LITE_COLORS = [
    ("cappuccino", "beige", "Капучино"),
    ("капучино", "beige", "Капучино"),
    ("mint", "green", "Мята"),
    ("мята", "green", "Мята"),
    ("flamingo", "pink", "Фламинго"),
    ("фламинго", "pink", "Фламинго"),
    ("chili", "red", "Чили"),
    ("чили", "red", "Чили"),
    ("ultraviolet", "purple", "Ультрафиолет"),
    ("ультрафиолет", "purple", "Ультрафиолет"),
    ("ультравиолет", "purple", "Ультрафиолет"),
    ("lemon", "yellow", "Лимон"),
    ("лимон", "yellow", "Лимон"),
]


@pytest.mark.parametrize("value,key,label", LITE_COLORS)
def test_lite_marketing_names(value, key, label):
    assert canonical_color(value) == key
    assert color_label(value) == label
