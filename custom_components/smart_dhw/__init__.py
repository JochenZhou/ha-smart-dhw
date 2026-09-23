"""Smart DHW integration — outdoor-band DHW setpoints with per-band calibration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    BAND_IDS,
    DOMAIN,
    SERVICE_CALIBRATE_BATH,
    SERVICE_CALIBRATE_DAILY,
    SERVICE_RECALCULATE,
    SERVICE_RESET_TABLE,
    SERVICE_SET_BAND,
    SERVICE_SET_OFFSET,
)
from .coordinator import SmartDhwCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

SERVICES = (
    SERVICE_CALIBRATE_BATH,
    SERVICE_CALIBRATE_DAILY,
    SERVICE_RESET_TABLE,
    SERVICE_RECALCULATE,
    SERVICE_SET_OFFSET,
    SERVICE_SET_BAND,
)


def _targets(hass: HomeAssistant, call: ServiceCall) -> list[SmartDhwCoordinator]:
    entry_id = call.data.get("entry_id")
    coordinators: dict[str, SmartDhwCoordinator] = hass.data.get(DOMAIN, {})
    if entry_id:
        if entry_id not in coordinators:
            raise HomeAssistantError(f"智能热水：找不到配置项 {entry_id}")
        return [coordinators[entry_id]]
    return list(coordinators.values())


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Smart DHW from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    coordinator = SmartDhwCoordinator(hass, entry.entry_id, dict(entry.data))
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if not hass.services.has_service(DOMAIN, SERVICE_CALIBRATE_BATH):

        async def _calibrate_bath(call: ServiceCall) -> None:
            for coordinator in _targets(hass, call):
                await coordinator.async_calibrate_bath(float(call.data["temperature"]))

        async def _calibrate_daily(call: ServiceCall) -> None:
            for coordinator in _targets(hass, call):
                await coordinator.async_calibrate_daily(float(call.data["temperature"]))

        async def _reset_table(call: ServiceCall) -> None:
            for coordinator in _targets(hass, call):
                await coordinator.async_reset_table()

        async def _recalculate(call: ServiceCall) -> None:
            for coordinator in _targets(hass, call):
                await coordinator.async_refresh()

        async def _set_offset(call: ServiceCall) -> None:
            kind = str(call.data["kind"])
            offset = int(call.data["offset"])
            band = call.data.get("band")
            for coordinator in _targets(hass, call):
                await coordinator.async_set_offset(kind, offset, band)

        async def _set_band(call: ServiceCall) -> None:
            band = str(call.data["band"])
            for coordinator in _targets(hass, call):
                await coordinator.async_set_band(band)

        temperature_schema = vol.Schema(
            {
                vol.Required("temperature"): vol.Coerce(float),
                vol.Optional("entry_id"): cv.string,
            }
        )
        entry_schema = vol.Schema({vol.Optional("entry_id"): cv.string})

        hass.services.async_register(
            DOMAIN, SERVICE_CALIBRATE_BATH, _calibrate_bath, schema=temperature_schema
        )
        hass.services.async_register(
            DOMAIN, SERVICE_CALIBRATE_DAILY, _calibrate_daily, schema=temperature_schema
        )
        hass.services.async_register(
            DOMAIN, SERVICE_RESET_TABLE, _reset_table, schema=entry_schema
        )
        hass.services.async_register(
            DOMAIN, SERVICE_RECALCULATE, _recalculate, schema=entry_schema
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_OFFSET,
            _set_offset,
            schema=vol.Schema(
                {
                    vol.Required("kind"): vol.In(["bath", "daily"]),
                    vol.Required("offset"): vol.Coerce(int),
                    vol.Optional("band"): vol.In(list(BAND_IDS) + ["all"]),
                    vol.Optional("entry_id"): cv.string,
                }
            ),
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_BAND,
            _set_band,
            schema=vol.Schema(
                {
                    vol.Required("band"): vol.In(list(BAND_IDS)),
                    vol.Optional("entry_id"): cv.string,
                }
            ),
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: SmartDhwCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_unload()
        if not hass.data[DOMAIN]:
            for service in SERVICES:
                hass.services.async_remove(DOMAIN, service)
    return unload_ok
