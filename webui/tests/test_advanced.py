from __future__ import annotations
import json


def test_more_page_has_sections(client, login, csrf):
    """More page shows backup/audit/password; mode and short-cuts are gone."""
    login()
    body = client.get("/more").get_data(as_text=True)
    for anchor in ('id="backup"', 'id="audit"', 'id="password"'):
        assert anchor in body
    for removed in ('id="mode"', 'id="actions"', "Режим интерфейса", "Переходы"):
        assert removed not in body
    assert "/logout" in body
    assert 'href="/advanced"' in body
    assert "Настройки" in body


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


def test_advanced_pages_render_200(client, login):
    """Advanced pages render 200 with expected content."""
    login()
    assert client.get("/advanced").status_code == 200
    assert client.get("/advanced/jobs").status_code == 200
    assert client.get("/advanced/routes").status_code == 200


def test_advanced_shows_raw_route_json(client, login, csrf, settings):
    """Advanced routes page shows raw JSON with redaction."""
    from webui.tests.test_app import write_router_config

    write_router_config(settings.router_config)
    login()
    body = client.get("/advanced/routes").get_data(as_text=True)
    assert '"token_file"' in body
    assert "router-token-speaker-a" in body
    assert "sk-router-test" not in body


def test_advanced_routes_redacts_inline_api_key(client, login, csrf, settings):
    """Advanced routes page redacts inline API keys."""
    from webui.tests.test_app import write_router_config

    write_router_config(settings.router_config)
    config = json.loads(settings.router_config.read_text(encoding="utf-8"))
    config["routes"][0]["primary"]["api_key"] = "sk-inline-secret-0123456789"
    settings.router_config.write_text(
        json.dumps(config), encoding="utf-8"
    )
    login()
    body = client.get("/advanced/routes").get_data(as_text=True)
    assert "sk-inline-secret-0123456789" not in body
    assert "***" in body


def test_advanced_bridge_policy_is_read_only(client, login, csrf):
    """Advanced bridge page shows policy and restricts edits."""
    login()
    body = client.get("/advanced/bridge").get_data(as_text=True)
    assert "default_route" in body
    assert 'name="rules"' not in body
    assert "/speakers/speaker-a/actions/routing" in body

def test_more_page_audit_is_scrollable(client, login):
    login()
    body = client.get("/more").get_data(as_text=True)
    assert "audit-scroll" in body
    assert "Записей нет" in body or "<tbody>" in body


def test_advanced_index_has_no_back_link(client, login):
    login()
    body = client.get("/advanced").get_data(as_text=True)
    assert "<h1>Дополнительно</h1>" in body
    assert 'class="back" href="/advanced"' not in body


def test_menu_uses_settings_and_models_and_access(client, login):
    login()
    body = client.get("/").get_data(as_text=True)
    assert ">Настройки</a>" in body
    assert ">Модели и доступ</a>" in body
    assert ">Дополнительно</a>" in body
    assert ">Ещё</a>" not in body
