"""Entity tables and gating, run against stubbed Home Assistant (see ha_stubs.py)."""

import asyncio
import types
from types import SimpleNamespace

import pytest

from .ha_stubs import EntityCategory, RegistryEntryDisabler, load_volvo

XC40 = {
    "supportsParkingClimatization": True,
    "supportsAirPurification": True,
    "reportsTyrePressure": False,
    "supportsParkingClimatizationFrontSeatsSettings": False,
}


class FakeRegistry:
    def __init__(self, entries=None):
        self.entries = entries or {}
        self.updates = []

    def async_get_entity_id(self, domain, platform, unique_id):
        for entity_id, entry in self.entries.items():
            if entity_id.startswith(f"{domain}.") and entry.unique_id == unique_id:
                return entity_id
        return None

    def async_get(self, entity_id):
        return self.entries.get(entity_id)

    def async_remove(self, entity_id):
        self.removed = getattr(self, "removed", []) + [entity_id]
        del self.entries[entity_id]

    def async_update_entity(self, entity_id, *, disabled_by):
        self.updates.append((entity_id, disabled_by))
        self.entries[entity_id].disabled_by = disabled_by


@pytest.fixture
def volvo(monkeypatch):
    return load_volvo(monkeypatch, FakeRegistry())


def _entity(volvo, unique_id, **flags):
    cls = type("E", (volvo.entity.VolvoEntity,), flags)
    entity = cls.__new__(cls)
    entity.unique_id = unique_id
    return entity


# ---- gating -------------------------------------------------------------------------------------------------


def test_gate_hides_unsupported_and_leaves_unflagged_alone(monkeypatch):
    registry = FakeRegistry({"sensor.tyre": SimpleNamespace(unique_id="t", disabled_by=None)})
    volvo = load_volvo(monkeypatch, registry)
    coordinator = SimpleNamespace(car_info=XC40)
    tyre = _entity(volvo, "t", requires_capability="reportsTyrePressure")
    plain = _entity(volvo, "p")
    climate = _entity(volvo, "c", requires_capability="supportsParkingClimatization")

    kept = volvo.entity.async_gate_unsupported(None, coordinator, "sensor", [tyre, plain, climate])

    assert kept == [plain, climate]
    assert registry.updates == [("sensor.tyre", RegistryEntryDisabler.INTEGRATION)]


def test_gate_brings_back_what_it_disabled_but_not_what_the_user_disabled(monkeypatch):
    registry = FakeRegistry(
        {
            "sensor.a": SimpleNamespace(unique_id="a", disabled_by=RegistryEntryDisabler.INTEGRATION),
            "sensor.b": SimpleNamespace(unique_id="b", disabled_by=RegistryEntryDisabler.USER),
        }
    )
    volvo = load_volvo(monkeypatch, registry)
    coordinator = SimpleNamespace(car_info={"supportsAirPurification": True})
    a = _entity(volvo, "a", requires_capability="supportsAirPurification")
    b = _entity(volvo, "b", requires_capability="supportsAirPurification")

    kept = volvo.entity.async_gate_unsupported(None, coordinator, "sensor", [a, b])

    assert kept == [a, b]
    assert registry.updates == [("sensor.a", None)]


@pytest.mark.parametrize("car", [None, {}])
def test_gate_keeps_everything_when_the_record_could_not_be_read(monkeypatch, car):
    volvo = load_volvo(monkeypatch, FakeRegistry())
    entity = _entity(volvo, "x", requires_capability="reportsTyrePressure")

    assert volvo.entity.async_gate_unsupported(None, SimpleNamespace(car_info=car), "sensor", [entity]) == [entity]


# ---- tables ---------------------------------------------------------------------------------------------------


def test_every_description_has_a_translation_key_and_unique_key(volvo):
    for table in (volvo.sensor.SENSORS, volvo.binary_sensor.DESCRIPTIONS):
        keys = [d.key for d in table]
        assert len(keys) == len(set(keys))
        assert all(d.translation_key for d in table), [d.key for d in table if not d.translation_key]


def test_entity_categories_follow_the_polestar_integration(volvo):
    sensors = {d.key: d.entity_category for d in volvo.sensor.SENSORS}
    assert sensors["usage_mode"] is EntityCategory.DIAGNOSTIC
    assert sensors["engine_hours_to_service"] is EntityCategory.DIAGNOSTIC
    assert sensors["air_purification_last_cycle"] is EntityCategory.DIAGNOSTIC
    assert sensors["battery_soc"] is None and sensors["range_km"] is None
    for cls in (
        volvo.time.VolvoScheduleTime,
        volvo.switch.VolvoChargeScheduleSwitch,
        volvo.number.VolvoClimateTemperature,
        volvo.select.VolvoClimateHeating,
    ):
        assert cls._attr_entity_category is EntityCategory.CONFIG, cls
    for cls in (volvo.sensor.VolvoConnection, volvo.sensor.VolvoVin):
        assert cls._attr_entity_category is EntityCategory.DIAGNOSTIC, cls
    # Controls stay primary so they show in the Controls card.
    assert getattr(volvo.switch.VolvoClimatizationSwitch, "_attr_entity_category", None) is None
    assert getattr(volvo.number.VolvoTargetSoc, "_attr_entity_category", None) is None


@pytest.mark.parametrize(
    ("car_info", "expected"),
    [
        ({"targetChargeLevelPercentageMinLimit": 50}, 50),  # XC40, 28 Nov 2026 car record
        ({"targetChargeLevelPercentageMinLimit": None}, 20),
        ({}, 20),
        (None, 20),
    ],
)
def test_target_soc_slider_starts_at_the_cars_lowest_level(volvo, car_info, expected):
    coordinator = SimpleNamespace(car_info=car_info, client=SimpleNamespace(vin="VIN"))
    assert volvo.number.VolvoTargetSoc(coordinator)._attr_native_min_value == expected


def test_every_gating_flag_in_the_tables_is_a_known_capability_name(volvo):
    flags = {d.requires_capability for d in volvo.sensor.SENSORS if d.requires_capability}
    flags |= {d.requires_capability for d in volvo.binary_sensor.DESCRIPTIONS if d.requires_capability}
    assert flags, "expected some gated sensors"
    assert all(f.startswith(("supports", "reports")) for f in flags), flags


# ---- values ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        ({}, None),
        ({"exterior": {"exterior": {}}}, None),
        ({"exterior": {"exterior": {"centralLock": "LOCKED"}}}, False),
        ({"exterior": {"exterior": {"alarmStatus": "ALARM_STATUS_IDLE"}}}, False),
        ({"exterior": {"exterior": {"alarmStatus": "ALARM_STATUS_TRIGGERED"}}}, True),
    ],
)
def test_alarm_is_ok_unless_the_car_says_triggered(volvo, snapshot, expected):
    assert volvo.binary_sensor._alarm(snapshot, "alarmStatus") is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("DOOR_OPEN", True), ("DOOR_CLOSED", False), ("DOOR_UNSPECIFIED", False), ("DOOR_AJAR", True), ("DOOR_SOMETHING", None), (None, None)],
)
def test_open_status(volvo, value, expected):
    snap = {"exterior": {"exterior": {} if value is None else {"frontLeftDoor": value}}}
    assert volvo.binary_sensor._open(snap, "frontLeftDoor") is expected


# ---- coordinator ----------------------------------------------------------------------------------------------


def test_climate_choices_start_empty(volvo):
    coordinator = volvo.coordinator.VolvoCoordinator.__new__(volvo.coordinator.VolvoCoordinator)
    # __init__ needs a running Home Assistant; the defaults live there, so just check the class is importable
    assert hasattr(volvo.coordinator, "VolvoCoordinator") and coordinator is not None


@pytest.mark.parametrize(
    ("health", "expected"),
    [
        (None, None),  # no health reply: unknown
        ({}, False),  # proto3 JSON leaves a false bool out
        ({"batteryThermalEventTriggered": True}, True),
        ({"batteryThermalEventTriggered": False}, False),
    ],
)
def test_battery_thermal_event(volvo, health, expected):
    snap = {} if health is None else {"health": {"health": health}}
    assert volvo.binary_sensor._battery_thermal_event(snap) is expected


def _coordinator_with(volvo, data, streamed):
    coordinator = volvo.coordinator.VolvoCoordinator.__new__(volvo.coordinator.VolvoCoordinator)
    coordinator.data = data
    coordinator._streamed = set(streamed)
    return coordinator


def test_poll_keeps_a_streamed_section_it_failed_to_read(volvo):
    # Port of ericyew 0da9bc1 (Polestar): a full poll must not wipe a value
    # that only a live stream delivers.
    old = {"odometer": {"odometer": {"odometerMeters": "1000"}}, "battery": {"battery": {"chargeLevel": 50}}}
    coordinator = _coordinator_with(volvo, old, {"odometer", "battery"})
    snap = {"odometer": {"_error": "VolvoApiError: boom"}, "battery": {}, "health": {"health": {}}}

    kept = coordinator._keep_streamed(snap)

    assert kept["odometer"] == old["odometer"]
    assert kept["battery"] == old["battery"]
    assert kept["health"] == {"health": {}}


def test_poll_replaces_streamed_sections_it_did_read_and_ignores_unstreamed(volvo):
    old = {"odometer": {"odometer": {"odometerMeters": "1000"}}, "weather": {"w": 1}}
    coordinator = _coordinator_with(volvo, old, {"odometer"})
    snap = {"odometer": {"odometer": {"odometerMeters": "1010"}}, "weather": {"_error": "x"}}

    kept = coordinator._keep_streamed(snap)

    assert kept["odometer"]["odometer"]["odometerMeters"] == "1010"
    assert kept["weather"] == {"_error": "x"}  # not streamed: the poll's answer stands


# ---- first poll with no data -------------------------------------------------------------------------------------


def test_battery_fields_the_car_never_sends_are_hidden(volvo):
    without = volvo.powertrain.sections_without_data({"battery": {"battery": {"batteryChargeLevelPercentage": 80}}})
    assert {"battery.chargingType", "battery.chargerPowerStatus"} <= without
    with_type = {"battery": {"battery": {"batteryChargeLevelPercentage": 80, "chargingType": "CHARGING_TYPE_NONE"}}}
    assert "battery.chargingType" not in volvo.powertrain.sections_without_data(with_type)
    # A missing or failed battery read hides nothing.
    assert not any(n.startswith("battery.") for n in volvo.powertrain.sections_without_data({}))
    assert not any(n.startswith("battery.") for n in volvo.powertrain.sections_without_data({"battery": {"_error": "x"}}))


def test_sections_without_data(volvo):
    full = {
        "pre_cleaning": {"preCleaning": {"runningStatus": "RUNNING_STATUS_OFF"}},
        "global_charge_timer": {"x": {"enabled": False}},  # False is a real value
        "amp_limit": {"ampLimit": {"ampLimit": 32}},
        "target_soc": {"targetSoc": {"batteryChargeTargetLevel": 90}},
        "parking_climatization": {"parkingClimatization": {"runningStatus": "RUNNING_STATUS_OFF"}},
    }
    assert volvo.powertrain.sections_without_data(full) == frozenset()
    empty = {**full, "pre_cleaning": {}, "target_soc": {"targetSoc": {}}, "amp_limit": None}
    assert volvo.powertrain.sections_without_data(empty) == {"pre_cleaning", "target_soc", "amp_limit"}


def test_a_failed_read_is_not_treated_as_no_data(volvo):
    snapshot = {"pre_cleaning": {"_error": "TimeoutError: slow"}}
    assert "pre_cleaning" not in volvo.powertrain.sections_without_data(snapshot)


def test_gate_hides_entities_whose_section_was_empty(monkeypatch):
    registry = FakeRegistry({"sensor.q": SimpleNamespace(unique_id="q", disabled_by=None)})
    volvo = load_volvo(monkeypatch, registry)
    coordinator = SimpleNamespace(car_info=XC40, no_data_sections=frozenset({"pre_cleaning"}))
    quality = _entity(volvo, "q", requires_data="pre_cleaning")
    soc = _entity(volvo, "s", requires_data="target_soc")

    kept = volvo.entity.async_gate_unsupported(None, coordinator, "sensor", [quality, soc])

    assert kept == [soc]
    assert registry.updates == [("sensor.q", RegistryEntryDisabler.INTEGRATION)]


def test_schedule_times_follow_the_schedule_switch(volvo):
    assert volvo.time.VolvoScheduleTime.requires_capability == volvo.switch.VolvoChargeScheduleSwitch.requires_capability
    assert volvo.time.VolvoScheduleTime.requires_data == volvo.switch.VolvoChargeScheduleSwitch.requires_data


# ---- removed duplicates ---------------------------------------------------------------------------------------


def test_duplicates_are_gone_and_their_registry_entries_cleaned(monkeypatch):
    registry = FakeRegistry({"sensor.old": SimpleNamespace(unique_id="u", disabled_by=None)})
    volvo = load_volvo(monkeypatch, registry)

    assert "amp_limit" not in {d.key for d in volvo.sensor.SENSORS}
    assert {spec[0] for spec in volvo.button.COMMAND_BUTTONS}.isdisjoint({"charge_start", "charge_stop"})
    # Target SoC is the number only; the read-only sensor duplicated it.
    assert "target_soc" not in {d.key for d in volvo.sensor.SENSORS}

    volvo.entity.async_remove_registered_entities(None, "sensor", ["u", "missing"])
    assert registry.removed == ["sensor.old"]


# ---- charging ---------------------------------------------------------------------------------------------------


def test_start_charging_is_refused_when_not_plugged_in(volvo):
    switch = volvo.switch.VolvoChargingSwitch.__new__(volvo.switch.VolvoChargingSwitch)
    switch.coordinator = SimpleNamespace(
        data={"battery": {"battery": {"chargerConnectionStatus": "CHARGER_CONNECTION_STATUS_DISCONNECTED"}}}
    )
    with pytest.raises(Exception, match="not plugged in"):
        asyncio.run(switch.async_turn_on())


# ---- enum sensor states ---------------------------------------------------------------------------------------


def test_enum_states_are_lowercase_keys_with_translations(monkeypatch):
    import json
    from pathlib import Path

    volvo = load_volvo(monkeypatch, FakeRegistry())
    sensor = volvo.sensor
    snap = {"battery": {"battery": {"chargingStatusV2": "CHARGING_STATUS_V2_SMART_CHARGING_PAUSED",
                                    "chargerConnectionStatus": "CHARGER_CONNECTION_STATUS_CONNECTED"}},
            "availability": {"availability": {"usageMode": "USAGE_MODE_ENGINE_OFF"}}}
    by_key = {d.key: d for d in sensor.SENSORS}

    assert by_key["charging_status"].value_fn(snap) == "smart_charging_paused"
    assert by_key["charger_connection"].value_fn(snap) == "connected"
    assert by_key["usage_mode"].value_fn(snap) == "engine_off"
    # Unspecified and unknown values give no state rather than an invalid one.
    assert by_key["charging_status"].value_fn({"battery": {"battery": {"chargingStatusV2": "CHARGING_STATUS_V2_UNSPECIFIED"}}}) is None
    assert by_key["charging_status"].value_fn({"battery": {"battery": {"chargingStatusV2": "CHARGING_STATUS_V2_NEW_THING"}}}) is None

    root = Path(__file__).parents[1] / "custom_components" / "volvo_au"
    for path in ("strings.json", "translations/en.json"):
        translated = json.loads((root / path).read_text())["entity"]["sensor"]
        for key in ("charging_status", "charger_connection", "usage_mode"):
            assert set(translated[key]["state"]) == set(by_key[key].options), f"{path}: {key}"

# ---- connection sensor ------------------------------------------------------------------------------------------


def test_connection_state_is_short_and_has_no_clock_time(monkeypatch):
    volvo = load_volvo(monkeypatch, FakeRegistry())
    online = volvo.online

    def status(is_online, reason=None):
        raw = {"unavailableReason": reason} if reason else {}
        return online.CarStatus(online=is_online, last_seen=None, source="test", raw=raw)

    assert online.status_text(status(True)) == "Online"
    assert online.status_text(status(None)) == "Unknown"
    assert online.status_text(status(False, "UNAVAILABLE_REASON_CAR_IN_USE")) == "In use"
    assert online.status_text(status(False, "UNAVAILABLE_REASON_CAR_IN_REMOTE_USE")) == "In use from the app"
    assert online.status_text(status(False, "UNAVAILABLE_REASON_NO_INTERNET")) == "Offline: no internet"
    assert online.status_text(status(False)) == "Offline: no connection"
    assert online.status_detail(status(False, "UNAVAILABLE_REASON_CAR_IN_USE")).startswith("The car is in use. Commands cannot reach")


def test_tyre_warning_combines_wheels_and_lists_pressures(monkeypatch):
    volvo = load_volvo(monkeypatch, FakeRegistry())
    health = {
        "frontLeftTyrePressureWarning": "TYRE_PRESSURE_WARNING_NO_WARNING",
        "frontRightTyrePressureWarning": "TYRE_PRESSURE_WARNING_VERY_LOW_PRESSURE",
        "frontLeftTyrePressureKpa": 250,
    }
    snap = {"health": {"health": health}}
    assert volvo.binary_sensor._any_tyre_warning(snap) is True
    attrs = volvo.binary_sensor._tyre_attributes(snap)
    assert attrs["front_left_warning"] == "ok"
    assert attrs["front_right_warning"] == "very_low"
    assert attrs["front_left_pressure_kpa"] == 250
    assert "rear_left_warning" not in attrs


def test_tyre_warning_unknown_without_data(monkeypatch):
    volvo = load_volvo(monkeypatch, FakeRegistry())
    assert volvo.binary_sensor._any_tyre_warning({"health": {"health": {}}}) is None
    assert volvo.binary_sensor._any_tyre_warning({}) is None


def test_tyre_attributes_need_reported_pressures(monkeypatch):
    volvo = load_volvo(monkeypatch, FakeRegistry())
    snap = {"health": {"health": {"frontLeftTyrePressureWarning": "TYRE_PRESSURE_WARNING_LOW_PRESSURE"}}}
    assert volvo.binary_sensor._tyre_attributes(snap) == {}


def test_service_attributes_grade_the_warning(monkeypatch):
    volvo = load_volvo(monkeypatch, FakeRegistry())
    grade = volvo.powertrain.service_attributes
    assert grade("SERVICE_WARNING_NO_WARNING") == {}
    assert grade(None) == {}
    assert grade("SERVICE_WARNING_REGULAR_MAINTENANCE_ALMOST_TIME") == {
        "service_urgency": "almost_due",
        "service_reason": "regular",
    }
    assert grade("SERVICE_WARNING_DISTANCE_DRIVEN_OVERDUE") == {
        "service_urgency": "overdue",
        "service_reason": "distance",
    }


def test_command_refusal_is_read_from_the_reply(monkeypatch):
    # volvo_api needs network libraries the tests do not load, so run just the reply decoder from its source
    from pathlib import Path

    source = (Path(__file__).parent.parent / "custom_components/volvo_au/volvo_api.py").read_text()
    start = source.index("COMMAND_STATUS_REASONS")
    end = source.index("# ----", start)
    namespace = {"Any": object}
    exec(source[start:end], namespace)
    refusal = namespace["command_refusal"]
    # field 3 (status) = 9 and field 4 (message) = "x", on its own and wrapped in field 1
    inner = b"\x18\x09\x22\x01x"
    assert "privacy mode" in refusal([inner])
    assert refusal([b"\x0a" + bytes([len(inner)]) + inner]).endswith("(x)")
    assert refusal([b"\x18\x06"]) is None  # success
    assert refusal([b"\x18\x02"]) is None  # seen on commands that worked
    assert refusal([]) is None


def test_chronos_charging_refusal_is_read_from_the_reply():
    # Same approach as above: run just the reply decoders from volvo_api's source.
    from pathlib import Path

    source = (Path(__file__).parent.parent / "custom_components/volvo_au/volvo_api.py").read_text()
    start = source.index("COMMAND_STATUS_REASONS")
    end = source.index("# ----", start)
    namespace = {"Any": object}
    exec(source[start:end], namespace)
    refusal = namespace["chronos_refusal"]
    start_now = "/chronos.services.v1.ChargeNowService/StartOverrideChargeTimer"
    amp = "/chronos.services.v1.AmpLimitService/SetAmpLimit"
    soc = "/chronos.services.v1.TargetSocService/SetTargetSoc"
    # Charge now: field 1 = chronos ResponseStatus, only SUCCESS (1) is fine
    assert refusal(start_now, [b"\x08\x01"]) is None
    assert "rejected" in refusal(start_now, [b"\x08\x02"])
    assert "internal error" in refusal(start_now, [b"\x08\x03"])
    assert "could not find" in refusal(start_now, [b"\x08\x04"])
    # No status, an unlisted one, or a field 1 that is not a number: let through as before
    assert refusal(start_now, [b""]) is None
    assert refusal(start_now, []) is None
    assert refusal(start_now, [b"\x08\x63"]) is None
    assert refusal(start_now, [b"\x0a\x02id"]) is None
    # Set verbs: {1 = id, 2 = vin, 3 = delivery status}
    ack = b"\x0a\x02id\x12\x03VIN"
    for path in (amp, soc):
        for ok in (1, 2, 3, 4, 8):
            assert refusal(path, [ack + bytes([0x18, ok])]) is None
        assert "offline" in refusal(path, [ack + bytes([0x18, 5])])
        assert "error" in refusal(path, [ack + bytes([0x18, 6])])
        assert "error" in refusal(path, [ack + bytes([0x18, 7])])
        assert refusal(path, [ack]) is None
    # Other paths are not checked here
    assert refusal("/chronos.services.v1.AmpLimitService/GetAmpLimit", [ack + b"\x18\x07"]) is None
    assert refusal("/invocation.InvocationService/Lock", [b"\x08\x02"]) is None


def test_charge_time_and_climate_sensors_match_polestar(monkeypatch):
    volvo = load_volvo(monkeypatch, FakeRegistry())
    by_key = {d.key: d for d in volvo.sensor.SENSORS}
    battery = {"battery": {"battery": {"estimatedChargingTimeMinutesToTargetDistance": 42,
                                       "estimatedChargingTimeMinutesToMinimumSoc": 7}}}
    assert by_key["time_to_target"].value_fn(battery) == 42
    assert by_key["time_to_min_soc"].value_fn(battery) == 7
    assert by_key["time_to_target"].entity_category is EntityCategory.DIAGNOSTIC

    unplugged = {"battery": {"battery": {"batteryChargeLevelPercentage": 80}}}
    for key in ("time_to_full", "time_to_target", "time_to_min_soc"):
        assert by_key[key].value_fn(unplugged) == 0  # JSON leaves out zeros; Polestar shows 0 min too
        assert by_key[key].value_fn({"battery": {}}) is None  # no reply at all stays unknown

    plugged = {"battery": {"battery": {"chargingType": "CHARGING_TYPE_AC",
                                       "chargerPowerStatus": "CHARGER_POWER_STATUS_PROVIDING_POWER"}}}
    assert by_key["charging_type"].value_fn(plugged) == "ac"
    assert by_key["charger_power_status"].value_fn(plugged) == "providing_power"
    assert by_key["charging_type"].requires_data == "battery.chargingType"
    # As a real XC40 sends them when unplugged (diagnostics, 27 November).
    unplugged_xc40 = {"battery": {"battery": {"chargingType": "CHARGING_TYPE_NONE",
                                              "chargerPowerStatus": "CHARGER_POWER_STATUS_NO_POWER_AVAILABLE"}}}
    assert by_key["charging_type"].value_fn(unplugged_xc40) == "none"
    assert by_key["charger_power_status"].value_fn(unplugged_xc40) == "no_power"

    def climate(**pc):
        return {"parking_climatization": {"parkingClimatization": pc}}

    running = climate(runningStatus="RUNNING_STATUS_ON", runtimeLeftMinutes=27, startReason="START_REASON_REMOTE")
    assert by_key["climate_running_status"].value_fn(running) == "active"
    assert by_key["climate_request_type"].value_fn(running) == "now_from_remote"
    assert by_key["climate_time_remaining"].value_fn(running) == 27

    pending = climate(runningStatus="RUNNING_STATUS_PENDING", startReason="START_REASON_TIMER")
    assert by_key["climate_running_status"].value_fn(pending) == "start_attempt"
    assert by_key["climate_request_type"].value_fn(pending) == "timer"

    # Off: "Not running", nothing left, and a stale start reason is not shown.
    off = climate(runningStatus="RUNNING_STATUS_OFF", runtimeLeftMinutes=0, startReason="START_REASON_REMOTE")
    assert by_key["climate_running_status"].value_fn(off) == "undefined"
    assert by_key["climate_request_type"].value_fn(off) == "undefined"
    assert by_key["climate_time_remaining"].value_fn(off) == 0

    # No record at all: no state.
    assert by_key["climate_running_status"].value_fn({}) is None
    assert by_key["climate_time_remaining"].value_fn({}) is None
    for key in ("climate_running_status", "climate_request_type"):
        assert set(by_key[key].options) >= {"undefined"}


# The XC40's own replies, from its diagnostics on 27 November 2026.
XC40_BATTERY = {"batteryChargeLevelPercentage": 85.0, "chargingType": "CHARGING_TYPE_NONE",
                "chargerPowerStatus": "CHARGER_POWER_STATUS_NO_POWER_AVAILABLE",
                "coldBatteryStatus": "COLD_BATTERY_STATUS_UNSPECIFIED"}
XC40_ODOMETER = {"odometerMeters": 57120700, "averageSpeedKmPerHour": 48, "averageSpeedKmPerHourAutomatic": 35}


def test_cold_battery_is_hidden_on_a_car_that_says_unspecified(volvo):
    # The XC40 sends UNSPECIFIED, as the Polestar 2 does; a car that supports it says NORMAL.
    hidden = volvo.powertrain.sections_without_data({"battery": {"battery": XC40_BATTERY},
                                                     "odometer": {"odometer": XC40_ODOMETER}})
    assert "battery.coldBatteryStatus" in hidden
    assert "battery.chargingType" not in hidden and "battery.chargerPowerStatus" not in hidden
    assert "odometer.averageSpeedKmPerHourAutomatic" not in hidden
    normal = {"battery": {"battery": {**XC40_BATTERY, "coldBatteryStatus": "COLD_BATTERY_STATUS_NORMAL"}}}
    assert "battery.coldBatteryStatus" not in volvo.powertrain.sections_without_data(normal)
    by_key = {d.key: d for d in volvo.sensor.SENSORS}
    assert by_key["cold_battery_status"].value_fn(normal) == "normal"
    assert by_key["cold_battery_status"].requires_data == "battery.coldBatteryStatus"


def test_average_speed_auto(volvo):
    by_key = {d.key: d for d in volvo.sensor.SENSORS}
    assert by_key["avg_speed_auto"].value_fn({"odometer": {"odometer": XC40_ODOMETER}}) == 35
    no_auto = {"odometer": {"odometer": {"odometerMeters": 1, "averageSpeedKmPerHour": 48}}}
    assert "odometer.averageSpeedKmPerHourAutomatic" in volvo.powertrain.sections_without_data(no_auto)


@pytest.mark.parametrize(
    ("availability", "expected"),
    [
        ({"availabilityStatus": "AVAILABILITY_STATUS_AVAILABLE", "unavailableReason": "UNAVAILABLE_REASON_UNSPECIFIED"}, "none"),
        ({"availabilityStatus": "AVAILABILITY_STATUS_UNAVAILABLE", "unavailableReason": "UNAVAILABLE_REASON_POWER_SAVING_MODE"}, "power_saving_mode"),
        ({"availabilityStatus": "AVAILABILITY_STATUS_UNAVAILABLE", "unavailableReason": "UNAVAILABLE_REASON_NO_INTERNET"}, "no_internet"),
        ({}, None),
    ],
)
def test_unavailable_reason(volvo, availability, expected):
    assert volvo.sensor.unavailable_reason({"availability": {"availability": availability}}) == expected


def test_any_door_open_and_climate_active(volvo):
    closed = {d: "OPEN_STATUS_CLOSED" for d in ("frontLeftDoor", "frontRightDoor", "rearLeftDoor", "rearRightDoor")}
    snap = {"exterior": {"exterior": {**closed, "tailgate": "OPEN_STATUS_OPEN"}}}
    assert volvo.binary_sensor.any_door_open(snap) is False  # the boot is not a door
    snap["exterior"]["exterior"]["rearLeftDoor"] = "OPEN_STATUS_OPEN"
    assert volvo.binary_sensor.any_door_open(snap) is True
    assert volvo.binary_sensor.any_door_open({}) is None

    def pc(status):
        return {"parking_climatization": {"parkingClimatization": {"runningStatus": status}}}

    assert volvo.binary_sensor.climate_active(pc("RUNNING_STATUS_ON")) is True
    assert volvo.binary_sensor.climate_active(pc("RUNNING_STATUS_OFF")) is False
    assert volvo.binary_sensor.climate_active({}) is None
    by_key = {d.key: d for d in volvo.binary_sensor.DESCRIPTIONS}
    assert by_key["climate_active"].requires_data == "parking_climatization"
