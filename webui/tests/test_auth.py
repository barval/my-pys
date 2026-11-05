from __future__ import annotations

from webui.auth import hash_password, verify_password


def test_password_roundtrip():
    encoded = hash_password("correct horse")
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong", encoded)


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
