import subprocess

import pytest

from webui.discovery import Discovered, merge_known_profiles, parse_subnet, probe_host, scan


def completed(argv, stdout=""):
    return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def fake_runner(alive):
    def run(argv):
        if "ping" in argv:
            return subprocess.CompletedProcess(argv, 0 if argv[-1] in alive else 1, "", "")
        if "connect" in argv:
            if argv[-1].split(":")[0] in alive:
                return completed(argv, f"connected to {argv[-1]}")
            return completed(argv, "failed to connect")
        if "ro.serialno" in argv:
            return completed(argv, "EXAMPLE000000000000000000000099\n")
        if "ro.product.model" in argv:
            return completed(argv, "Яндекс Станция Лайт\n")
        if "address" in argv:
            return completed(argv, "02:00:00:00:00:99\n")
        return completed(argv)
    return run


def test_merge_known_profiles_enriches_and_sorts():
    class Profile:
        def __init__(self, name, ip, mac, device_id, model):
            self.name = name
            self.ip = ip
            self.mac = mac
            self.device_id = device_id
            self.model = model

    devices = [
        Discovered("192.168.1.1", "", "", "", ""),
        Discovered("192.168.1.2", "", "", "", ""),
        Discovered("192.168.1.3", "02:00:00:00:00:03", "EXAMPLE3", "Station", ""),
    ]
    profiles = [
        Profile("kitchen", "192.168.1.2", "02:00:00:00:00:02", "EXAMPLE2", "Station")
    ]
    merged = merge_known_profiles(devices, profiles)
    assert [item.ip for item in merged] == ["192.168.1.2", "192.168.1.3", "192.168.1.1"]
    assert merged[0].profile_name == "kitchen"
    assert merged[0].device_id == "EXAMPLE2"
    assert merged[0].mac == "02:00:00:00:00:02"


def test_station_marker_rejects_foreign_adb_devices():
    assert not Discovered("192.168.1.43", "", "000490E468496EA1", "SaluteTV", "").station
    assert Discovered("192.168.1.130", "", "LP0001", "Яндекс Станция Лайт", "").station
    assert Discovered("192.168.1.131", "", "", "", "", profile_name="speaker-a").station


def test_parse_subnet_returns_254_hosts():
    hosts = parse_subnet("192.168.1")
    assert len(hosts) == 254
    assert hosts[0] == "192.168.1.1"


@pytest.mark.parametrize("value", ["8.8.8.8", "10.0.0.0/16", "not-a-subnet"])
def test_parse_subnet_rejects_public_and_large(value):
    with pytest.raises(ValueError):
        parse_subnet(value)


def test_probe_host_returns_discovered_device():
    device = probe_host("192.168.1.150", runner=fake_runner({"192.168.1.150"}))
    assert device.device_id == "EXAMPLE000000000000000000000099"
    assert device.mac == "02:00:00:00:00:99"
    assert device.model == "Яндекс Станция Лайт"


def test_probe_host_skips_silent_host():
    assert probe_host("192.168.1.151", runner=fake_runner(set())) is None


def test_scan_collects_only_live_hosts():
    devices = scan("192.168.1.0/30", runner=fake_runner({"192.168.1.1"}))
    assert [item.ip for item in devices] == ["192.168.1.1"]


def test_probe_host_without_adb_returns_bare_address():
    def run(argv):
        return subprocess.CompletedProcess(argv, 0 if "ping" in argv else 1, "failed", "")

    device = probe_host("192.168.1.152", runner=run)
    assert device == Discovered("192.168.1.152", "", "", "", "")


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(subprocess.TimeoutExpired(["adb"], 5), id="timeout"),
        pytest.param(FileNotFoundError("adb"), id="missing-adb"),
    ],
)
def test_probe_host_treats_runner_failure_as_host_without_adb(exc):
    def run(argv):
        raise exc

    device = probe_host("192.168.1.152", runner=run)
    assert device == Discovered("192.168.1.152", "", "", "", "")


def test_scan_keeps_hosts_when_runner_fails():
    def run(argv):
        raise subprocess.TimeoutExpired(argv, 5)

    devices = scan("192.168.1.0/30", runner=run)
    assert devices == [
        Discovered("192.168.1.1", "", "", "", ""),
        Discovered("192.168.1.2", "", "", "", ""),
    ]


def test_parse_subnet_explains_bad_value_in_russian():
    with pytest.raises(ValueError, match="Некорректная подсеть"):
        parse_subnet("192.168.1.500")
