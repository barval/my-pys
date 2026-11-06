import subprocess

import pytest

from webui.discovery import Discovered, parse_subnet, probe_host, scan


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
