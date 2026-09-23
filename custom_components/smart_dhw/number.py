"""Number entities for Smart DHW.

Auto-generated:
- bath / daily setpoints (writing one calibrates that band only)
- bath/daily min/max limits (runtime config, not config-flow fields)
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_BAND_HOLD_MINUTES,
    ATTR_BAND_LABEL,
    ATTR_BAND_PENDING,
    ATTR_HYSTERESIS,
    ATTR_INDOOR,
    ATTR_INDOOR_SOURCE,
    ATTR_INPUT_VALID,
    ATTR_OUTDOOR,
    ATTR_OUTDOOR_SOURCE,
    ATTR_TRIM,
    CONF_NAME,
    DEFAULT_NAME,
    DOMAIN,
    LIMIT_ENTITY_ABS_MAX,
    LIMIT_ENTITY_ABS_MIN,
)
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
            SmartDhwSetpointNumber(coordinator, entry, name, "bath"),
            SmartDhwSetpointNumber(coordinator, entry, name, "daily"),
            SmartDhwLimitNumber(coordinator, entry, name, "bath_min"),
            SmartDhwLimitNumber(coordinator, entry, name, "bath_max"),
            SmartDhwLimitNumber(coordinator, entry, name, "daily_min"),
            SmartDhwLimitNumber(coordinator, entry, name, "daily_max"),
        ]
    )


class _BaseNumber(CoordinatorEntity[SmartDhwCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_mode = NumberMode.BOX
    _attr_native_step = 1.0

    def __init__(
        self,
        coordinator: SmartDhwCoordinator,
        entry: ConfigEntry,
        name: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": name,
            "manufacturer": "智能热水",
            "model": "分档校准",
        }


class SmartDhwSetpointNumber(_BaseNumber):
    """Bath/daily setpoint — writing it calibrates the *current band* only."""

    def __init__(self, coordinator, entry, name, kind: str) -> None:
        key = "bath_setpoint" if kind == "bath" else "daily_setpoint"
        super().__init__(coordinator, entry, name, key)
        self._kind = kind
        self._attr_translation_key = key
        self._attr_icon = "mdi:shower-head" if kind == "bath" else "mdi:water-thermometer"

    @property
    def _limits(self) -> tuple[int, int]:
        profile = self.coordinator.profile
        if self._kind == "bath":
            return profile.bath_min, profile.bath_max
        return profile.daily_min, profile.daily_max

    @property
    def native_min_value(self) -> float:
        return float(self._limits[0])

    @property
    def native_max_value(self) -> float:
        return float(self._limits[1])

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        key = "bath" if self._kind == "bath" else "daily"
        return float(self.coordinator.data[key])

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        calibration = data.get(f"{self._kind}_calibration") or {}
        name = "洗澡" if self._kind == "bath" else "日常"
        return {
            "band": data.get("band"),
            "band_label": data.get(ATTR_BAND_LABEL),
            ATTR_OUTDOOR: data.get(ATTR_OUTDOOR),
            ATTR_OUTDOOR_SOURCE: data.get(ATTR_OUTDOOR_SOURCE),
            ATTR_INDOOR: data.get(ATTR_INDOOR),
            ATTR_INDOOR_SOURCE: data.get(ATTR_INDOOR_SOURCE),
            ATTR_INPUT_VALID: data.get(ATTR_INPUT_VALID),
            ATTR_TRIM: data.get(ATTR_TRIM) if self._kind == "bath" else 0,
            "band_pending": data.get(ATTR_BAND_PENDING),
            "hysteresis": data.get(ATTR_HYSTERESIS),
            "band_hold_minutes": data.get(ATTR_BAND_HOLD_MINUTES),
            "requested_offset": calibration.get("requested_offset"),
            "applied_offset": calibration.get("applied_offset"),
            "offset_clamped": calibration.get("clamped"),
            "value_clamped": calibration.get("value_clamped"),
            f"{self._kind}_table": data.get(f"{self._kind}_table"),
            f"factory_{self._kind}_table": data.get(f"factory_{self._kind}_table"),
            f"{self._kind}_offsets": data.get(f"{self._kind}_offsets"),
            "hint": (
                f"写入只校准「{name}」当前分档（{data.get(ATTR_BAND_LABEL)}）"
                f"，其余档位不受影响；超出上下限时会被限制并记录"
            ),
        }

    async def async_set_native_value(self, value: float) -> None:
        if self._kind == "bath":
            await self.coordinator.async_calibrate_bath(value)
        else:
            await self.coordinator.async_calibrate_daily(value)


class SmartDhwLimitNumber(_BaseNumber):
    """Runtime min/max limits (config via entity, not config flow)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:thermometer-lines"

    def __init__(self, coordinator, entry, name, kind: str) -> None:
        super().__init__(coordinator, entry, name, kind)
        self._kind = kind
        self._attr_translation_key = kind
        self._attr_native_min_value = float(LIMIT_ENTITY_ABS_MIN)
        self._attr_native_max_value = float(LIMIT_ENTITY_ABS_MAX)

    @property
    def native_value(self) -> float | None:
        p = self.coordinator.profile
        return float(getattr(p, self._kind))

    @property
    def extra_state_attributes(self):
        return {
            "hint": "调整上下限只会重新拟合分档偏移，不会把水温向上顶",
            "bath_table": self.coordinator.profile.bath_table,
            "daily_table": self.coordinator.profile.daily_table,
        }

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_limit(self._kind, value)
