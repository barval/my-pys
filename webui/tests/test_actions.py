from __future__ import annotations

import pytest

from webui.actions import CommandBuilder, UnknownAction


def test_speaker_action_uses_profile_env(tmp_path, make_profile):
    profile = make_profile("speaker-a")
    argv, env = CommandBuilder(tmp_path).build("bridge", profile)
    assert argv == ["bash", "scripts/install-quasar-bridge.sh", "--non-interactive"]
    assert env["SPEAKER_ENV"] == str(profile.path)


def test_unknown_action_is_rejected(tmp_path):
    with pytest.raises(UnknownAction):
        CommandBuilder(tmp_path).build("rm -rf /", None)


def test_host_action_has_no_profile(tmp_path):
    argv, env = CommandBuilder(tmp_path).build("router-start", None)
    assert argv == ["bash", "scripts/start-router.sh"]
    assert env == {}


def test_sidecar_mode_restarts_via_module(tmp_path):
    builder = CommandBuilder(
        tmp_path,
        router_control="sidecar",
        sidecar_url="http://router-control:8081",
    )
    argv, env = builder.build("router-restart", None)
    assert argv[1:] == ["-m", "webui.router_control"]
    assert env["WEBUI_SIDECAR_URL"] == "http://router-control:8081"


def test_sidecar_mode_rejects_start_and_stop(tmp_path):
    builder = CommandBuilder(tmp_path, router_control="sidecar")
    for action in ("router-start", "router-stop"):
        try:
            builder.build(action, None)
        except UnknownAction:
            continue
        raise AssertionError(f"{action} should not be available in sidecar mode")


def test_resolve_action_uses_profile(tmp_path, make_profile):
    profile = make_profile("speaker-a")
    argv, env = CommandBuilder(tmp_path).build("resolve", profile)
    assert argv == ["bash", "scripts/resolve-speaker.sh"]
    assert env["SPEAKER_ENV"] == str(profile.path)
