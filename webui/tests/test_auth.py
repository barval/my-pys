from __future__ import annotations

from webui.auth import hash_password, verify_password


def test_password_roundtrip():
    encoded = hash_password("correct horse")
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong", encoded)


def test_login_title_breaks_before_yandex(client):
    body = client.get("/login").get_data(as_text=True)
    assert "Моя персональная<br>Яндекс Станция" in body


def test_protected_page_redirects_to_login(client):
    response = client.get("/speakers")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_post_without_csrf_is_rejected(client, csrf):
    client.get("/login")
    client.post(
        "/login",
        data={"password": "correct horse", "csrf_token": csrf(client)},
    )
    response = client.post("/router/restart")
    assert response.status_code == 400


def test_session_cookie_is_same_site_strict(app):
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Strict"
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
