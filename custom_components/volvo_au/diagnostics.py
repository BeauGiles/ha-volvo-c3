"""Diagnostics download for Volvo C3: settings, the car's capability flags and the latest snapshot, minus personal data."""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_VIN, DOMAIN
from .redact import redact

# Identifying values in the car record, scrubbed wherever they turn up (raw replies have no key names to go by).
_SECRET_KEYS = ("batteryPackSerialNumber", "plugAndChargePcid", "visualId", "registrationPlate")


async def _extra_reads(client: Any) -> dict[str, Any]:
    """Read-only calls the integration doesn't poll, made once when diagnostics are downloaded.

    Raw gRPC replies are shown by field number (unknown_<n>). The gRPC car record is included because it carries
    fields the REST car record leaves out (for example 43, 44, 45 and 92).
    """
    vin_field = client._pb_len_delim(1, client.vin.encode("ascii"))
    raw = {
        "car_preview": ("/car_information.CarInformation/GetCarPreview", vin_field),
        "car_record_grpc": ("/car_information.CarInformation/GetMyCars", b""),
        "pnc_enabled": ("/pnc_enabled.PncEnabledService/GetPncEnabled", vin_field),
        "connected_car_contract": (
            "/onboarding.ConnectedCarContractStatusService/GetConnectedCarContractStatusByVin",
            vin_field + client._pb_len_delim(2, b"en"),
        ),
    }
    jobs: dict[str, Any] = {name: client.read_raw(path, body) for name, (path, body) in raw.items()}
    # Silent while there are no errors, so a timeout here is normal.
    jobs["chronos_errors"] = asyncio.wait_for(
        client._ndjson_first_frame("/chronos.services.v1.ErrorService/GetErrors", client._chronos_body()), 5
    )
    results = await asyncio.gather(*(asyncio.wait_for(job, 15) for job in jobs.values()), return_exceptions=True)
    out: dict[str, Any] = {}
    for name, result in zip(jobs, results, strict=True):
        if isinstance(result, TimeoutError):
            out[name] = "no reply in time"
        elif isinstance(result, BaseException):
            out[name] = f"{type(result).__name__}: {str(result)[:200]}"
        else:
            out[name] = result
    return out


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    vin = entry.data.get(CONF_VIN)
    streams = {
        name: {"proven": policy.proven, "snapshot_only": policy.snapshot_only}
        for name, policy in coordinator.stream_policies.items()
    }
    interval = coordinator.update_interval
    car = coordinator.car_info or {}
    secrets = tuple(
        s for s in (*(car.get(k) for k in _SECRET_KEYS), coordinator.registration_plate) if isinstance(s, str)
    )
    try:
        extra = await _extra_reads(coordinator.client)
    except Exception as err:  # noqa: BLE001 - diagnostics must still download
        extra = {"_error": f"{type(err).__name__}: {err}"}
    return redact(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "car_record": coordinator.car_info,
            "snapshot": coordinator.data,
            "polling": {
                "update_interval_s": interval.total_seconds() if interval else None,
                "last_update_success": coordinator.last_update_success,
                "live_updates": coordinator._live_updates,
                "streams": streams,
                "driving_journal": coordinator.driving_journal,
            },
            "extra_reads": extra,
        },
        vin=vin,
        secrets=secrets,
    )
