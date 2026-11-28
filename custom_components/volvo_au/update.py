"""Software update entity: the car's OTA update as the Volvo app shows it, with install now and scheduling.

Matches the Polestar C3 Software update entity (same backend services, same attributes and services).
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import ota
from .const import DOMAIN
from .coordinator import VolvoCoordinator
from .entity import VolvoEntity
from .powertrain import capability
from .volvo_api import VolvoApiError

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: VolvoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([VolvoSoftwareUpdate(coordinator)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "schedule_ota",
        {vol.Optional("delay_minutes", default=0): vol.All(vol.Coerce(int), vol.Range(min=0))},
        "async_schedule_ota",
    )
    platform.async_register_entity_service("cancel_ota", {}, "async_cancel_ota")


class VolvoSoftwareUpdate(VolvoEntity, UpdateEntity, RestoreEntity):
    """The OTA update GetSoftwareInfo advertises; the installed version is tracked across restarts."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_translation_key = "software_update"

    def __init__(self, coordinator: VolvoCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{coordinator.client.vin}_software_update"
        self._installed_cache: str | None = None
        # The car's record says whether the app may start or schedule an install (an XC40 says it may).
        features = UpdateEntityFeature.RELEASE_NOTES
        if capability(coordinator.car_info, "supportsRemoteOtaInstallSchedule") is not False:
            features |= UpdateEntityFeature.INSTALL
        self._attr_supported_features = features

    @property
    def entity_picture(self) -> str | None:
        """No picture, so Home Assistant shows the standard update icon instead of the brand logo.

        UpdateEntity falls back to the brand logo whenever the picture is None, so the property is overridden.
        """
        return None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        version = last.attributes.get("installed_version") if last else None
        if isinstance(version, str) and version:
            self._installed_cache = version

    def _info(self) -> dict[str, Any]:
        info = (self.coordinator.data or {}).get("software_info")
        return info if isinstance(info, dict) and "_error" not in info else {}

    def _schedule(self) -> dict[str, Any]:
        schedule = (self.coordinator.data or {}).get("ota_schedule")
        return schedule if isinstance(schedule, dict) and "_error" not in schedule else {}

    @property
    def installed_version(self) -> str | None:
        version = ota.installed_version(self._info(), self.coordinator.car_info, self._installed_cache)
        if version and ota.advertised_is_installed(self._info()):
            self._installed_cache = version
        return version

    @property
    def latest_version(self) -> str | None:
        # No OTA record: nothing newer is known.
        return self._info().get("version") or self.installed_version

    @property
    def in_progress(self) -> bool:
        return ota.is_in_progress(self._info())

    @property
    def title(self) -> str | None:
        return self._info().get("title")

    @property
    def release_summary(self) -> str | None:
        info = self._info()
        if not info.get("version") or ota.advertised_is_installed(info):
            return None
        summary = " · ".join(p for p in (info.get("title"), info.get("ref_label")) if p)
        return summary[:255] or None

    async def async_release_notes(self) -> str | None:
        """The full release notes the app shows, from the same GetSoftwareInfo reply."""
        return ota.release_notes(self._info().get("release_notes"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info, schedule = self._info(), self._schedule()
        return {
            "software_id": info.get("update_id"),
            "software_state": ota.state_name(info),
            "software_state_timestamp": ota.iso(info.get("timestamp")),
            "scheduled_for": ota.iso(info.get("scheduled_at")),
            "scheduler_status": schedule.get("status"),
            "scheduler_scheduled_time": schedule.get("scheduled_time"),
            "scheduler_set_by": schedule.get("set_by"),
        }

    def _software_id(self) -> str:
        software_id = self._info().get("update_id")
        if not software_id:
            raise HomeAssistantError("Volvo has no software update for this car right now")
        return software_id

    async def _run(self, what: str, call) -> None:
        try:
            await call
        except (VolvoApiError, OSError) as err:
            raise HomeAssistantError(f"{what} failed: {err}") from err
        await self.coordinator.async_request_refresh()

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        """Install the advertised update now, as the app's "Install now"."""
        if version is not None and version != self.latest_version:
            raise HomeAssistantError(f"Version {version} is not the update Volvo offers ({self.latest_version})")
        await self._run("Install now", self.coordinator.client.ota_install_now(self._software_id()))

    async def async_schedule_ota(self, delay_minutes: int = 0) -> None:
        await self._run(
            "Schedule update", self.coordinator.client.ota_schedule(self._software_id(), delay_minutes * 60)
        )

    async def async_cancel_ota(self) -> None:
        await self._run("Cancel scheduled update", self.coordinator.client.ota_cancel_schedule(self._software_id()))
