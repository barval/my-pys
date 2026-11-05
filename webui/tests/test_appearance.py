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
