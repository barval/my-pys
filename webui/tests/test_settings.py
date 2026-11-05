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
