from __future__ import annotations

import json


def test_more_page_has_sections_in_simple_mode(client, login, csrf):
    """In simple mode, /advanced link is hidden."""
    login()
    client.post(
        "/mode", data={"mode": "simple"}, headers={"X-CSRF-Token": csrf(client)}
    )
    body = client.get("/more").get_data(as_text=True)
    for anchor in ('id="mode"', 'id="backup"', 'id="audit"', 'id="password"'):
        assert anchor in body
    assert "/setup/prepare" in body
    assert "/logout" in body
    assert 'href="/advanced"' not in body


def test_more_page_has_sections_in_advanced_mode(client, login, csrf):
    """In advanced mode, /advanced link is shown."""
    login()
    client.post(
        "/mode", data={"mode": "advanced"}, headers={"X-CSRF-Token": csrf(client)}
    )
    body = client.get("/more").get_data(as_text=True)
    for anchor in ('id="mode"', 'id="backup"', 'id="audit"', 'id="password"'):
        assert anchor in body
    assert "/setup/prepare" in body
    assert "/logout" in body
    assert 'href="/advanced"' in body


def test_legacy_backup_audit_password_redirect_to_more(client, login):
    login()
    for old, fragment in (
        ("/backup", "#backup"),
        ("/audit", "#audit"),
        ("/password", "#password"),
    ):
        response = client.get(old)
        assert response.status_code == 301
        assert response.headers["Location"].endswith("/more" + fragment)


def test_advanced_pages_require_advanced_mode(client, login, csrf):
    login()
    assert client.get("/advanced").status_code == 404
    client.post(
        "/mode", data={"mode": "advanced"}, headers={"X-CSRF-Token": csrf(client)}
    )
    assert client.get("/advanced").status_code == 200
    assert client.get("/advanced/jobs").status_code == 200
    assert client.get("/advanced/routes").status_code == 200


def test_advanced_shows_raw_route_json(client, login, csrf, settings):
    from webui.tests.test_app import write_router_config

    write_router_config(settings.router_config)
    login()
    client.post(
        "/mode", data={"mode": "advanced"}, headers={"X-CSRF-Token": csrf(client)}
    )
    body = client.get("/advanced/routes").get_data(as_text=True)
    assert '"token_file"' in body
    assert "router-token-speaker-a" in body
    assert "sk-router-test" not in body


def test_advanced_routes_redacts_inline_api_key(client, login, csrf, settings):
    from webui.tests.test_app import write_router_config

    write_router_config(settings.router_config)
    config = json.loads(settings.router_config.read_text(encoding="utf-8"))
    config["routes"][0]["primary"]["api_key"] = "sk-inline-secret-0123456789"
    settings.router_config.write_text(
        json.dumps(config), encoding="utf-8"
    )
    login()
    client.post(
        "/mode", data={"mode": "advanced"}, headers={"X-CSRF-Token": csrf(client)}
    )
    body = client.get("/advanced/routes").get_data(as_text=True)
    assert "sk-inline-secret-0123456789" not in body
    assert "***" in body


def test_advanced_bridge_policy_is_read_only(client, login, csrf):
    login()
    client.post(
        "/mode", data={"mode": "advanced"}, headers={"X-CSRF-Token": csrf(client)}
    )
    body = client.get("/advanced/bridge").get_data(as_text=True)
    assert "default_route" in body
    assert 'name="rules"' not in body
    assert "/speakers/speaker-a/actions/routing" in body
