COOKIE_NAME = "ui_mode"
SIMPLE = "simple"
ADVANCED = "advanced"


def current_mode(cookie_value: str | None) -> str:
    return ADVANCED if cookie_value == ADVANCED else SIMPLE


def is_advanced(cookie_value: str | None) -> bool:
    return current_mode(cookie_value) == ADVANCED
