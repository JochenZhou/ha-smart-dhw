"""Binary sensor platform for Smart DHW."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_INDOOR,
    ATTR_INDOOR_SOURCE,
    ATTR_INPUT_VALID,
    ATTR_OUTDOOR,
    ATTR_OUTDOOR_SOURCE,
    CONF_NAME,
    DEFAULT_NAME,
    DOMAIN,
)
from .coordinator import SmartDhwCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartDhwCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get(CONF_NAME) or DEFAULT_NAME
    async_add_entities([SmartDhwInputOkSensor(coordinator, entry, name)])


class SmartDhwInputOkSensor(CoordinatorEntity[SmartDhwCoordinator], BinarySensorEntity):
    """True while the outdoor temperature is usable."""

    _attr_has_entity_name = True
    _attr_translation_key = "input_ok"
    _attr_icon = "mdi:thermometer-check"

    def __init__(self, coordinator, entry, name) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_input_ok"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": name,
            "manufacturer": "智能热水",
            "model": "分档校准",
        }

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get(ATTR_INPUT_VALID))

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            ATTR_OUTDOOR: data.get(ATTR_OUTDOOR),
            ATTR_OUTDOOR_SOURCE: data.get(ATTR_OUTDOOR_SOURCE),
            ATTR_INDOOR: data.get(ATTR_INDOOR),
            ATTR_INDOOR_SOURCE: data.get(ATTR_INDOOR_SOURCE),
            "hint": "为 off 时保持当前分档与目标水温，不下发设备",
        }
