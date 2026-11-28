"""Charge-now state, the chronos error stream and raw protobuf helpers (pure Python, no Home Assistant imports).

Field numbers come from the Volvo and Polestar apps; the shapes were checked against an XC40 on 28 Nov 2026.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# ----- charge now (ChargeNowService/GetEnabledOverrideChargeTimerAction, gateway JSON) -----

_ACTIVE_STATES = ("STATE_OVERRIDE_ACTIVE", "STATE_OVERRIDE_ACTIVE_PENDING")


def charge_now_active(reply: dict[str, Any] | None) -> bool | None:
    """True while charge now overrides the charge timer (or is about to), None when unknown.

    An XC40 parked and unplugged sends ``STATE_OVERRIDE_NOT_ACTIVE``.
    """
    state = (reply or {}).get("overrideChargeTimerState")
    if not isinstance(state, str) or state.endswith("_UNSPECIFIED"):
        return None
    return state in _ACTIVE_STATES


def charge_now_attributes(reply: dict[str, Any] | None) -> dict[str, Any]:
    """{"state": "override_not_active", "app_offers": "not_applicable"} from the gateway reply."""
    reply = reply or {}
    state = reply.get("overrideChargeTimerState")
    action = reply.get("enabledOverrideChargeTimerAction")
    attrs: dict[str, Any] = {}
    if isinstance(state, str):
        attrs["state"] = state.removeprefix("STATE_").lower()
    if isinstance(action, str):
        # Which charge-now button the app offers now: charge_now, resume_schedule or not_applicable.
        attrs["app_offers"] = action.removeprefix("ACTION_").lower()
    return attrs


# ----- chronos errors (ErrorService/GetErrors, gateway JSON) -----

# Gateway key -> (setting name, the key of its action enum or None).
_ERROR_DOMAINS: tuple[tuple[str, str, str | None], ...] = (
    ("ampLimitError", "amp_limit", None),
    ("chargeLocationError", "charge_location", "chargeLocationAction"),
    ("chargeNowError", "charge_now", "chargeNowAction"),
    ("globalChargeTimerError", "global_charge_timer", None),
    ("parkingClimateTimerError", "parking_climate_timer", "parkingClimateTimerAction"),
    ("targetSocError", "target_soc", None),
)
_ACTION_PREFIXES = ("CHARGE_LOCATION_ACTION_", "CHARGE_NOW_ACTION_", "PARKING_CLIMATE_TIMER_ACTION_")


def error_time(frame: dict[str, Any] | None) -> datetime | None:
    """When the error happened. The gateway sends a Timestamp as {seconds, nanos} (or an ISO string)."""
    value = (frame or {}).get("errorTime")
    if isinstance(value, dict):
        try:
            seconds = int(value.get("seconds") or 0)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(seconds, tz=UTC) if seconds > 0 else None
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def error_attributes(frame: dict[str, Any] | None) -> dict[str, Any]:
    """What failed and why, e.g. {"setting": "charge_now", "error": "car", "action": "start_override_charge_timer"}."""
    for key, setting, action_key in _ERROR_DOMAINS:
        detail = (frame or {}).get(key)
        if not isinstance(detail, dict):
            continue
        attrs: dict[str, Any] = {"setting": setting}
        error = detail.get("error")
        # The gateway leaves out the first enum value (ERROR_UNSPECIFIED), so a missing error is "unspecified".
        attrs["error"] = error.removeprefix("ERROR_").lower() if isinstance(error, str) else "unspecified"
        action = detail.get(action_key) if action_key else None
        if isinstance(action, str):
            for prefix in _ACTION_PREFIXES:
                action = action.removeprefix(prefix)
            attrs["action"] = action.lower()
        return attrs
    return {}


# ----- raw protobuf (for replies outside the JSON gateway) -----


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return result, pos


def fields(data: bytes) -> list[tuple[int, int, Any]]:
    """[(field number, wire type, value)]: varints as int, length-delimited as bytes, fixed as raw bytes.

    Raises ValueError when ``data`` isn't a valid message.
    """
    out: list[tuple[int, int, Any]] = []
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        num, wire = key >> 3, key & 7
        if num == 0:
            raise ValueError("field 0")
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 2:
            length, pos = _varint(data, pos)
            if pos + length > len(data):
                raise ValueError("truncated bytes")
            value, pos = data[pos:pos + length], pos + length
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if pos + size > len(data):
                raise ValueError("truncated fixed")
            value, pos = data[pos:pos + size], pos + size
        else:
            raise ValueError(f"wire type {wire}")
        out.append((num, wire, value))
    return out


def describe(data: bytes, depth: int = 0) -> Any:
    """Best guess for a raw message with no schema: {"unknown_<n>": value}, text, or hex. For diagnostics."""
    if not data:
        return ""
    try:
        text = data.decode("utf-8")
        if text.isprintable():
            return text
    except UnicodeDecodeError:
        pass
    if depth < 8:
        try:
            out: dict[str, Any] = {}
            for num, wire, value in fields(data):
                shown = describe(value, depth + 1) if wire == 2 else (value if wire == 0 else "hex:" + value.hex())
                key = f"unknown_{num}"
                if key in out:
                    prev = out[key]
                    out[key] = (prev if isinstance(prev, list) else [prev]) + [shown]
                else:
                    out[key] = shown
            return out
        except ValueError:
            pass
    return "hex:" + data.hex()


def installed_at_from_my_cars(reply: bytes | None, vin: str) -> int | None:
    """Car record field 92 (taken to be the software install time, epoch seconds) for ``vin`` in a raw GetMyCars reply.

    GetMyCarsResponse: 1 = repeated MyCar; MyCar: 1 = car; car: 1 = vin, 92 = {1: seconds}. Neither app names
    field 92. An XC40 sends it about 47 s after its last OTA install finished; a car with no OTA yet doesn't.
    """
    if not reply:
        return None
    try:
        for num, wire, my_car in fields(reply):
            if num != 1 or wire != 2:
                continue
            car = next((v for n, w, v in fields(my_car) if n == 1 and w == 2), None)
            if car is None:
                continue
            car_fields = fields(car)
            car_vin = next((v for n, w, v in car_fields if n == 1 and w == 2), b"")
            if car_vin.decode("utf-8", "replace") != vin:
                continue
            stamp = next((v for n, w, v in car_fields if n == 92 and w == 2), None)
            if stamp is None:
                return None
            seconds = next((v for n, w, v in fields(stamp) if n == 1 and w == 0), 0)
            return seconds if seconds > 0 else None
    except ValueError:
        return None
    return None


def data_sharing_from_reply(reply: bytes | None) -> dict[str, bool] | None:
    """{"enabled", "car_in_sync", "read_only"} from a raw GetRemoteFunctionDataSharing reply (fields 1, 2, 3).

    Proto3 leaves out false values, so a missing field is false. An XC40 sends all three true.
    """
    if reply is None:
        return None
    try:
        values = {n: bool(v) for n, w, v in fields(reply) if w == 0}
    except ValueError:
        return None
    return {"enabled": values.get(1, False), "car_in_sync": values.get(2, False), "read_only": values.get(3, False)}
