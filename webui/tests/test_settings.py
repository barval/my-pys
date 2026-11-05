from __future__ import annotations

from webui.settings import load_settings


def test_default_is_host_mode(tmp_path):
    settings = load_settings(root=tmp_path, env={})
    assert settings.router_control == "host"
    assert settings.router_health_url == "http://127.0.0.1:5002/health"


def test_sidecar_mode_uses_container_service_names(tmp_path):
    settings = load_settings(
        root=tmp_path,
        env={
            "WEBUI_ROUTER_CONTROL": "sidecar",
            "WEBUI_SIDECAR_URL": "http://router-control:8081",
        },
    )
    assert settings.router_control == "sidecar"
    assert settings.sidecar_url == "http://router-control:8081"
    assert settings.router_health_url == "http://llm-router:5002/health"


def test_sidecar_stand_control(tmp_path):
    settings = load_settings(
        root=tmp_path,
        env={
            "WEBUI_STAND_CONTROL": "sidecar",
            "WEBUI_STAND_URL": "http://stand-control:8082",
        },
    )
    assert settings.stand_control == "sidecar"
    assert settings.stand_url == "http://stand-control:8082"


def test_stand_address_from_local_env(tmp_path):
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / ".env").write_text(
        "ROOT_STAND_IP=10.1.2.3\nLLM_BASE_URL=http://10.1.2.3:6000/v1\n",
        encoding="utf-8",
    )
    settings = load_settings(root=tmp_path, env={})
    assert settings.stand_ip == "10.1.2.3"
    assert settings.router_display_url == "http://10.1.2.3:6000/v1"
    assert settings.router_health_display_url == "http://10.1.2.3:6000/health"
