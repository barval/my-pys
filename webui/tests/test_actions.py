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
