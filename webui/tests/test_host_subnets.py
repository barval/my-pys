from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from webui.subnets import fallback_prefixes, load_subnets, subnet_prefixes

ROOT = Path(__file__).resolve().parents[2]


def fake_profile(subnet: str):
    class Profile:
        pass

    profile = Profile()
    profile.subnet = subnet
    return profile


def test_load_subnets_valid(tmp_path):
    path = tmp_path / "host-subnets.json"
    path.write_text(json.dumps(["192.168.1.0/24", "10.0.0.0/24"]), encoding="utf-8")
    assert load_subnets(path) == ["192.168.1.0/24", "10.0.0.0/24"]


def test_load_subnets_missing_and_malformed(tmp_path):
    assert load_subnets(tmp_path / "absent.json") == []
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_subnets(broken) == []
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"subnets": []}), encoding="utf-8")
    assert load_subnets(wrong) == []


def test_subnet_prefixes_keeps_only_slash24_and_dedupes():
    prefixes = subnet_prefixes(
        ["192.168.1.0/24", "192.168.1.0/24", "10.0.0.0/16", "bad", "172.17.0.0/16"]
    )
    assert prefixes == ["192.168.1"]


def test_fallback_prefixes_from_profiles():
    profiles = [fake_profile("192.168.1"), fake_profile(""), fake_profile("10.0.0")]
    assert fallback_prefixes(profiles) == ["10.0.0", "192.168.1"]


def test_host_subnets_script_filters_and_writes_private_file(tmp_path):
    dump = tmp_path / "net.txt"
    dump.write_text(
        "\n".join(
            [
                "2: eth0    inet 192.168.1.5/24 brd 192.168.1.255 scope global eth0",
                "1: lo    inet 127.0.0.1/8 scope host lo",
                "3: docker0    inet 172.17.0.1/16 brd 172.17.255.255 scope global docker0",
                "4: eth1    inet 10.20.30.1/24 scope global eth1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "subnets.json"
    env = dict(os.environ, HOST_NET_DUMP=str(dump), HOST_SUBNETS_OUT=str(out))
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "host-subnets.sh")],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(out.read_text(encoding="utf-8")) == [
        "10.20.30.0/24",
        "192.168.1.0/24",
    ]
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_host_subnets_script_rejects_loopback_only(tmp_path):
    dump = tmp_path / "net.txt"
    dump.write_text("1: lo    inet 127.0.0.1/8 scope host lo\n", encoding="utf-8")
    out = tmp_path / "subnets.json"
    env = dict(os.environ, HOST_NET_DUMP=str(dump), HOST_SUBNETS_OUT=str(out))
    subprocess.run(
        ["bash", str(ROOT / "scripts" / "host-subnets.sh")],
        env=env,
        check=True,
    )
    assert json.loads(out.read_text(encoding="utf-8")) == []
