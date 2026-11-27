"""OTA software update state (ota_mobcache OtaDiscoveryService and SchedulerService), as the Volvo app shows it.

Pure Python (no Home Assistant imports) so it can be tested on its own. The enums and field numbers are the Volvo
app's (com.volvocars.conncar.ota.mobcache) and match the Polestar app's.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# CarSoftwareInfo.state (GetSoftwareInfo field 1.4).
SOFTWARE_STATES: dict[int, str] = {
    0: "unknown",
    1: "download_ready",
    2: "download_started",
    3: "download_completed",
    4: "download_failed",
    5: "installation_initiated",
    6: "installation_started",
    7: "installation_aborted",
    8: "installation_failed",
    9: "installation_completed",
    10: "installation_deferred",
    11: "installation_failed_critical",
    12: "installation_scheduled",
    13: "installation_schedule_triggered",
    14: "installation_unknown",
}
# The advertised version is the one already in the car in these states (nothing pending).
INSTALLED_STATES = frozenset({0, 9, 14})
IN_PROGRESS_STATES = frozenset({2, 3, 5, 6, 12, 13})

SCHEDULE_STATUSES: dict[int, str] = {0: "unknown", 1: "idle", 2: "scheduled", 3: "install"}
SCHEDULE_SET_BY: dict[int, str] = {0: "unknown", 1: "app", 2: "hmi", 3: "cloud"}


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def fields(buf: bytes) -> list[tuple[int, int, Any]]:
    """(field, wire type, value) for each top-level field of a protobuf message; stops at anything malformed."""
    out: list[tuple[int, int, Any]] = []
    pos = 0
    try:
        while pos < len(buf):
            tag, pos = _varint(buf, pos)
            field, wire = tag >> 3, tag & 7
            if wire == 0:
                value, pos = _varint(buf, pos)
            elif wire == 2:
                length, pos = _varint(buf, pos)
                value, pos = buf[pos:pos + length], pos + length
            elif wire == 1:
                value, pos = buf[pos:pos + 8], pos + 8
            elif wire == 5:
                value, pos = buf[pos:pos + 4], pos + 4
            else:
                break
            out.append((field, wire, value))
    except IndexError:
        pass
    return out


def timestamp_seconds(buf: bytes) -> int | None:
    """Seconds from a google.protobuf.Timestamp message (field 1), or None."""
    for field, wire, value in fields(buf):
        if field == 1 and wire == 0:
            return value or None
    return None


def iso(seconds: int | None) -> str | None:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat() if seconds else None


def parse_scheduler(buf: bytes) -> dict[str, Any]:
    """A Scheduler message: status 1, relativeTime 2, scheduledTime 3, softwareId 4, setBy 5."""
    out: dict[str, Any] = {}
    for field, wire, value in fields(buf):
        if field == 1 and wire == 0:
            out["status"] = SCHEDULE_STATUSES.get(value, "unknown")
        elif field == 2 and wire == 0:
            out["relative_time"] = value
        elif field == 3 and wire == 2:
            out["scheduled_time"] = iso(timestamp_seconds(value))
        elif field == 4 and wire == 2:
            out["software_id"] = value.decode("utf-8", "replace")
        elif field == 5 and wire == 0:
            out["set_by"] = SCHEDULE_SET_BY.get(value, "unknown")
    return out


def parse_scheduler_reply(frame: bytes) -> dict[str, Any] | None:
    """GetSchedule, Schedule, InstallNow and CancelSchedule all answer {timer (1): Scheduler}."""
    for field, wire, value in fields(frame):
        if field == 1 and wire == 2:
            return parse_scheduler(value)
    return None


def state_name(info: dict[str, Any] | None) -> str | None:
    status = (info or {}).get("status")
    return SOFTWARE_STATES.get(status, "unknown") if isinstance(status, int) else None


def is_in_progress(info: dict[str, Any] | None) -> bool:
    return (info or {}).get("status") in IN_PROGRESS_STATES


def advertised_is_installed(info: dict[str, Any] | None) -> bool:
    """True when the version GetSoftwareInfo names is already in the car (no update waiting)."""
    info = info or {}
    return bool(info.get("version")) and info.get("status", 0) in INSTALLED_STATES


def installed_version(info: dict[str, Any] | None, car: dict[str, Any] | None, cached: str | None) -> str | None:
    """Best known installed version: the advertised one when nothing is pending, else the last known one."""
    if advertised_is_installed(info):
        return info["version"]
    return cached or (car or {}).get("consumerSoftwareVersion") or None
