"""Sensor entities for Smart DHW."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_BAND,
    ATTR_BAND_HOLD_MINUTES,
    ATTR_BAND_HOLD_REMAINING,
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
)
from .coordinator import SmartDhwCoordinator

_OUTDOOR_SOURCE_TEXT = {
    "primary": "主传感器",
    "backup": "备用传感器",
    "stale": "上次有效值（已冻结）",
    "none": "不可用",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SmartDhwCoordinator = hass.data[DOMAIN][entry.entry_id]
    name = entry.data.get(CONF_NAME) or DEFAULT_NAME
    async_add_entities(
        [
            SmartDhwBandSensor(coordinator, entry, name),
            SmartDhwOffsetSensor(coordinator, entry, name, "bath"),
            SmartDhwOffsetSensor(coordinator, entry, name, "daily"),
            SmartDhwModeSensor(coordinator, entry, name),
        ]
    )


class _BaseSensor(CoordinatorEntity[SmartDhwCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartDhwCoordinator,
        entry: ConfigEntry,
        name: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": name,
            "manufacturer": "智能热水",
            "model": "分档校准",
        }


class SmartDhwBandSensor(_BaseSensor):
    _attr_translation_key = "band"
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(self, coordinator, entry, name) -> None:
        super().__init__(coordinator, entry, name, "band")

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None
        data = self.coordinator.data
        label = data.get("band_label") or data.get(ATTR_BAND)
        if not data.get(ATTR_INPUT_VALID):
            return f"{label}（输入失效）"
        return label

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "band_id": data.get(ATTR_BAND),
            ATTR_OUTDOOR: data.get(ATTR_OUTDOOR),
            "outdoor_source": _OUTDOOR_SOURCE_TEXT.get(
                str(data.get(ATTR_OUTDOOR_SOURCE)), data.get(ATTR_OUTDOOR_SOURCE)
            ),
            ATTR_INDOOR: data.get(ATTR_INDOOR),
            ATTR_INDOOR_SOURCE: data.get(ATTR_INDOOR_SOURCE),
            ATTR_INPUT_VALID: data.get(ATTR_INPUT_VALID),
            ATTR_TRIM: data.get(ATTR_TRIM),
            "band_pending": data.get(ATTR_BAND_PENDING),
            ATTR_BAND_HOLD_REMAINING: data.get(ATTR_BAND_HOLD_REMAINING),
            ATTR_HYSTERESIS: data.get(ATTR_HYSTERESIS),
            ATTR_BAND_HOLD_MINUTES: data.get(ATTR_BAND_HOLD_MINUTES),
            "bath": data.get("bath"),
            "daily": data.get("daily"),
            "bath_table": data.get("bath_table"),
            "daily_table": data.get("daily_table"),
            "bath_offsets": data.get("bath_offsets"),
            "daily_offsets": data.get("daily_offsets"),
            "bath_min": data.get("bath_min"),
            "bath_max": data.get("bath_max"),
            "daily_min": data.get("daily_min"),
            "daily_max": data.get("daily_max"),
        }


class SmartDhwOffsetSensor(_BaseSensor):
    """Per-band calibration offset vs factory (°C)."""

    def __init__(self, coordinator, entry, name, kind: str) -> None:
        key = "offset" if kind == "bath" else "daily_offset"
        super().__init__(coordinator, entry, name, key)
        self._kind = kind
        self._attr_translation_key = key
        self._attr_icon = "mdi:delta"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        current = self.coordinator.data.get(f"{self._kind}_calibration") or {}
        return float(current.get("applied_offset", 0) or 0)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        calibration = data.get(f"{self._kind}_calibration") or {}
        if self._kind == "bath":
            explanation = "正值=该档洗澡水温高于出厂值（管损/花洒补偿）；逐档独立，改一档不影响其它档"
        else:
            explanation = (
                "正值=该档日常水温高于出厂值；日常表始终不高于洗澡表"
            )
        return {
            "band": data.get(ATTR_BAND),
            "band_label": data.get("band_label"),
            "requested_offset": calibration.get("requested_offset"),
            "applied_offset": calibration.get("applied_offset"),
            "offset_clamped": calibration.get("clamped"),
            "value_clamped": calibration.get("value_clamped"),
            f"{self._kind}_offsets": data.get(f"{self._kind}_offsets"),
            f"factory_{self._kind}_table": data.get(f"factory_{self._kind}_table"),
            f"{self._kind}_table": data.get(f"{self._kind}_table"),
            "explanation": explanation,
        }


class SmartDhwModeSensor(_BaseSensor):
    """What the integration is doing with the water heater right now."""

    _attr_translation_key = "mode"
    _attr_icon = "mdi:transmission-tower"

    def __init__(self, coordinator, entry, name) -> None:
        super().__init__(coordinator, entry, name, "mode")

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        if not data.get("enabled"):
            return "动态已关闭（数值冻结）"
        if not data.get("sync_device"):
            return "未同步设备"
        if not data.get(ATTR_INPUT_VALID):
            return "输入失效，已冻结"
        mode = data.get("device_mode")
        if mode == "bath":
            return "已下发洗澡水温"
        if mode == "daily":
            return "已下发日常水温"
        return "设备为人工设定（不干预）"

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "device_mode": data.get("device_mode"),
            "device_target_value": data.get("device_target_value"),
            "enabled": data.get("enabled"),
            "sync_device": data.get("sync_device"),
            "hint": "集成只在本设备值仍等于上次下发值时同步，人工或自动化改动一律不抢",
        }
