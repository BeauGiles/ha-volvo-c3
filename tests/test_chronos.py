"""Charge now, chronos errors and raw protobuf helpers (pure module, no Home Assistant needed)."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "volvo_au"
_SPEC = importlib.util.spec_from_file_location("chronos", ROOT / "chronos.py")
chronos = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(chronos)


def _varint(n):
    out = bytearray()
    while True:
        out.append(n & 0x7F | (0x80 if n > 0x7F else 0))
        n >>= 7
        if not n:
            return bytes(out)


def _f(num, value):
    if isinstance(value, int):
        return _varint(num << 3) + _varint(value)
    value = value.encode() if isinstance(value, str) else value
    return _varint(num << 3 | 2) + _varint(len(value)) + value


XC40_CHARGE_NOW = {  # 28 Nov 2026, parked and unplugged
    "status": "SUCCESS",
    "enabledOverrideChargeTimerAction": "ACTION_NOT_APPLICABLE",
    "overrideChargeTimerState": "STATE_OVERRIDE_NOT_ACTIVE",
}


def test_charge_now_as_the_xc40_sends_it():
    assert chronos.charge_now_active(XC40_CHARGE_NOW) is False
    assert chronos.charge_now_attributes(XC40_CHARGE_NOW) == {
        "state": "override_not_active",
        "app_offers": "not_applicable",
    }


def test_charge_now_active_and_unknown():
    assert chronos.charge_now_active({"overrideChargeTimerState": "STATE_OVERRIDE_ACTIVE"}) is True
    assert chronos.charge_now_active({"overrideChargeTimerState": "STATE_OVERRIDE_ACTIVE_PENDING"}) is True
    assert chronos.charge_now_active({"_error": "VolvoApiError: x"}) is None
    assert chronos.charge_now_active(None) is None


def test_an_error_names_the_setting_and_the_reason():
    frame = {
        "id": "x",
        "chargeNowError": {"error": "ERROR_CAR", "chargeNowAction": "CHARGE_NOW_ACTION_START_OVERRIDE_CHARGE_TIMER"},
        "errorTime": {"seconds": "1795851836", "nanos": 5},
    }
    assert chronos.error_attributes(frame) == {
        "setting": "charge_now",
        "error": "car",
        "action": "start_override_charge_timer",
    }
    assert chronos.error_time(frame) == datetime.fromtimestamp(1795851836, tz=UTC)


def test_an_error_the_gateway_sent_with_default_values():
    # The gateway leaves out ERROR_UNSPECIFIED and empty actions.
    assert chronos.error_attributes({"targetSocError": {}}) == {"setting": "target_soc", "error": "unspecified"}
    assert chronos.error_attributes({}) == {}
    assert chronos.error_time({"errorTime": "2026-11-28T07:43:56Z"}) == datetime(2026, 11, 28, 7, 43, 56, tzinfo=UTC)
    assert chronos.error_time({}) is None


def _my_cars(vin, *car_fields):
    return _f(1, _f(1, _f(1, vin) + b"".join(car_fields)))


def test_install_time_is_read_from_the_grpc_car_record():
    # XC40, 28 Nov 2026: field 92 = {1: 1791102281}, 47 s after its 5.2.16 install finished.
    reply = _my_cars("OTHERVIN", _f(92, _f(1, 5))) + _my_cars("MYVIN", _f(5, "536"), _f(92, _f(1, 1791102281)))
    assert chronos.installed_at_from_my_cars(reply, "MYVIN") == 1791102281


def test_no_install_time_before_a_first_ota():
    assert chronos.installed_at_from_my_cars(_my_cars("MYVIN", _f(5, "534")), "MYVIN") is None
    assert chronos.installed_at_from_my_cars(None, "MYVIN") is None
    assert chronos.installed_at_from_my_cars(b"\xff", "MYVIN") is None


def test_data_sharing_as_the_xc40_sends_it():
    assert chronos.data_sharing_from_reply(_f(1, 1) + _f(2, 1) + _f(3, 1)) == {
        "enabled": True, "car_in_sync": True, "read_only": True,
    }
    assert chronos.data_sharing_from_reply(b"") == {"enabled": False, "car_in_sync": False, "read_only": False}
    assert chronos.data_sharing_from_reply(None) is None


def test_raw_replies_are_described_by_field_number():
    assert chronos.describe(_f(1, _f(10, "536") + _f(2, 1))) == {"unknown_1": {"unknown_10": "536", "unknown_2": 1}}
    assert chronos.describe(b"\xff\xfe") == "hex:fffe"


def test_sync_and_updated_at_attributes():
    # As an XC40 sends them (28 Nov 2026).
    metadata = {"id": "x", "updatedAt": "1791043227747", "source": "car",
                "syncStatus": {"status": "SYNCED", "message": ""}, "sourceTimestamp": "0"}
    assert chronos.sync_attributes(metadata) == {
        "updated_at": "2026-10-03T16:00:27.747000+00:00", "changed_by": "car", "sync_status": "synced"}
    pending = {"syncStatus": {"status": "RETRYING_CAR_OFFLINE", "message": "car offline"}}
    assert chronos.sync_attributes(pending) == {"sync_status": "retrying_car_offline", "sync_message": "car offline"}
    assert chronos.sync_attributes(None) == {} and chronos.sync_attributes({}) == {}

    target_soc = {"batteryChargeTargetLevel": 100, "updatedAt": "1795436583461", "source": "mapp"}
    assert chronos.updated_at_attributes(target_soc) == {
        "updated_at": "2026-11-23T12:23:03.461000+00:00", "changed_by": "mapp"}
    assert chronos.updated_at_attributes({"updatedAt": "0"}) == {}
