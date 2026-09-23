"""Switch entities for Smart DHW."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DEFAULT_NAME, DOMAIN
from .coordinator import SmartDhwCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartDhwCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get(CONF_NAME) or DEFAULT_NAME
    async_add_entities(
        [
            SmartDhwEnabledSwitch(coordinator, entry, name),
            SmartDhwSyncSwitch(coordinator, entry, name),
        ]
    )


class _BaseSwitch(CoordinatorEntity[SmartDhwCoordinator], SwitchEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, name, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": name,
            "manufacturer": "智能热水",
            "model": "分档校准",
        }


class SmartDhwEnabledSwitch(_BaseSwitch):
    """Enable / disable the weather-driven setpoint. Off = values freeze."""

    _attr_translation_key = "enabled"
    _attr_icon = "mdi:thermometer-water"

    def __init__(self, coordinator, entry, name) -> None:
        super().__init__(coordinator, entry, name, "enabled")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.enabled)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "frozen_bath": None if self.coordinator.enabled else data.get("bath"),
            "frozen_daily": None if self.coordinator.enabled else data.get("daily"),
            "hint": "关闭后水温不再随室外温度变化，仍会按「洗澡/日常」两个固定值切换",
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_enabled(False)


class SmartDhwSyncSwitch(_BaseSwitch):
    """Push the setpoint to the water heater entity."""

    _attr_translation_key = "sync"
    _attr_icon = "mdi:sync"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, entry, name) -> None:
        super().__init__(coordinator, entry, name, "sync")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.sync_device)

    @property
    def extra_state_attributes(self):
        return {
            "device_mode": (self.coordinator.data or {}).get("device_mode"),
            "device_target_value": (self.coordinator.data or {}).get(
                "device_target_value"
            ),
            "hint": "只在设备值仍等于上次下发值时同步；人工/自动化改动不抢",
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_sync(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_sync(False)
