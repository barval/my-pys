from webui.ui_mode import current_mode, is_advanced


def test_missing_or_unknown_cookie_is_simple():
    assert current_mode(None) == "simple"
    assert current_mode("") == "simple"
    assert current_mode("hacker") == "simple"
    assert is_advanced(None) is False


def test_advanced_cookie_is_advanced():
    assert current_mode("advanced") == "advanced"
    assert is_advanced("advanced") is True
