"""OTA update state and scheduler replies (the module has no Home Assistant imports)."""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "volvo_ota", Path(__file__).parents[1] / "custom_components" / "volvo_au" / "ota.py"
)
ota = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ota)


def _len(field: int, payload: bytes) -> bytes:
    return bytes([(field << 3) | 2, len(payload)]) + payload


def _var(field: int, value: int) -> bytes:
    out = bytearray([field << 3])
    while True:
        b = value & 0x7F
        value >>= 7
        out.append(b | (0x80 if value else 0))
        if not value:
            return bytes(out)


def test_scheduler_reply_is_decoded():
    scheduler = _var(1, 2) + _var(2, 3600) + _len(3, _var(1, 1_764_201_600)) + _len(4, b"abc-123") + _var(5, 1)
    assert ota.parse_scheduler_reply(_len(1, scheduler)) == {
        "status": "scheduled",
        "relative_time": 3600,
        "scheduled_time": "2025-11-27T00:00:00+00:00",
        "software_id": "abc-123",
        "set_by": "app",
    }
    assert ota.parse_scheduler_reply(b"") is None


def test_installed_version_follows_state():
    car = {"consumerSoftwareVersion": "5.2.16"}
    # Nothing pending: the advertised version is the installed one.
    assert ota.installed_version({"version": "5.2.16", "status": 9}, car, None) == "5.2.16"
    assert ota.installed_version({"version": "5.2.16"}, car, None) == "5.2.16"
    # An update is waiting: keep the last known installed version, else the car record's.
    assert ota.installed_version({"version": "5.3.0", "status": 1}, car, "5.2.15") == "5.2.15"
    assert ota.installed_version({"version": "5.3.0", "status": 1}, car, None) == "5.2.16"
    assert ota.installed_version({}, None, None) is None


def test_states():
    assert ota.state_name({"status": 12}) == "installation_scheduled"
    assert ota.state_name({"status": 99}) == "unknown"
    assert ota.state_name({}) is None
    assert ota.is_in_progress({"status": 6}) and not ota.is_in_progress({"status": 1})
