"""Coordinator for Smart DHW."""

from __future__ import annotations

import inspect
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ATTR_BAND,
    ATTR_BAND_HOLD_MINUTES,
    ATTR_BAND_HOLD_REMAINING,
    ATTR_BAND_LABEL,
    ATTR_BAND_PENDING,
    ATTR_BATH_OFFSETS,
    ATTR_BATH_TABLE,
    ATTR_DAILY_OFFSETS,
    ATTR_DAILY_TABLE,
    ATTR_DEVICE_MODE,
    ATTR_DEVICE_VALUE,
    ATTR_HYSTERESIS,
    ATTR_INDOOR,
    ATTR_INDOOR_SOURCE,
    ATTR_INPUT_VALID,
    ATTR_OUTDOOR,
    ATTR_OUTDOOR_SOURCE,
    ATTR_TRIM,
    BAND_IDS,
    CONF_BAND_HOLD_MINUTES,
    CONF_DEVICE_TARGET,
    CONF_ENABLE_INDOOR_TRIM,
    CONF_HYSTERESIS,
    CONF_INDOOR_SENSOR,
    CONF_INDOOR_SENSOR_BACKUP,
    CONF_OUTDOOR_SENSOR,
    CONF_OUTDOOR_SENSOR_BACKUP,
    CONF_SYNC_DEVICE,
    DEFAULT_BAND_HOLD_MINUTES,
    DEFAULT_HYSTERESIS,
    DOMAIN,
    FACTORY_BATH,
    FACTORY_DAILY,
    LIMIT_ENTITY_ABS_MAX,
    LIMIT_ENTITY_ABS_MIN,
    MIN_REFRESH_SECONDS,
    SCALD_WARN_TEMP,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .table import (
    KIND_BATH,
    KIND_DAILY,
    BandTracker,
    CalibrationResult,
    DhwProfile,
    band_label,
    indoor_trim,
    parse_temperature,
    resolve_band,
)

_LOGGER = logging.getLogger(__name__)

EVAL_INTERVAL = timedelta(minutes=5)


async def _migrate_store(
    old_major_version: int,
    old_minor_version: int | None,
    old_data: dict[str, Any],
) -> dict[str, Any]:
    """v1/v2 (absolute tables) → v3 (per-band offsets + tracker state)."""
    data = dict(old_data or {})
    migrated = DhwProfile.from_dict(data).to_dict()
    for key in ("enabled", "frozen_bath", "frozen_daily"):
        if key in data:
            migrated[key] = data[key]
    band_id = data.get("band_id")
    migrated["band_id"] = band_id if band_id in BAND_IDS else resolve_band(20.0)["id"]
    _LOGGER.info(
        "智能热水：存储已从 v%s 迁移到 v%s（绝对分档表 → 分档偏移）",
        old_major_version,
        STORAGE_VERSION,
    )
    return migrated


class DhwStore(Store[dict[str, Any]]):
    """Store with migration, compatible with both old and new HA Store APIs.

    Home Assistant < 2026.9 passes the migration callable to ``Store(...)``;
    newer versions dropped that keyword and use the ``_async_migrate_func``
    method instead. Supporting both keeps the integration installable on the
    whole range of supported releases.
    """

    def __init__(self, hass: HomeAssistant, version: int, key: str) -> None:
        if "async_migrate_func" in inspect.signature(Store.__init__).parameters:
            super().__init__(hass, version, key, async_migrate_func=_migrate_store)
        else:
            super().__init__(hass, version, key)

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int | None,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        return await _migrate_store(old_major_version, old_minor_version, old_data)


class SmartDhwCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Owns the calibrated band tables, band tracking and optional device sync."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        config: dict[str, Any],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_id}",
            update_interval=EVAL_INTERVAL,
        )
        self.entry_id = entry_id
        self.config = config
        self.profile = DhwProfile()
        self.tracker = BandTracker()
        self.enabled = True
        self.sync_device = bool(config.get(CONF_SYNC_DEVICE, True))
        self._store = DhwStore(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY}_{entry_id}",
        )
        try:
            self.hysteresis = max(0.0, float(config.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)))
        except (TypeError, ValueError):
            self.hysteresis = DEFAULT_HYSTERESIS
        try:
            self.hold_seconds = (
                max(
                    0.0,
                    float(
                        config.get(
                            CONF_BAND_HOLD_MINUTES, DEFAULT_BAND_HOLD_MINUTES
                        )
                    ),
                )
                * 60
            )
        except (TypeError, ValueError):
            self.hold_seconds = DEFAULT_BAND_HOLD_MINUTES * 60

        self._unsubs: list[CALLBACK_TYPE] = []
        self._applying = False
        self._last_outdoor: float | None = None
        self._last_trim = 0
        self._frozen: tuple[int | None, int | None] = (None, None)
        self._last_state_refresh = 0.0
        self._delayed_refresh: CALLBACK_TYPE | None = None
        self._device_mode: str | None = None
        self._device_value: int | None = None
        self._device_manual = False
        self._warned: set[str] = set()
        self._last_calibration: dict[str, CalibrationResult] = {}

    # ------------------------------------------------------------------ setup
    async def async_setup(self) -> None:
        stored = await self._store.async_load()
        if stored:
            self.profile = DhwProfile.from_dict(stored)
            if "enabled" in stored:
                self.enabled = bool(stored["enabled"])
            self.tracker = BandTracker(
                band_id=stored.get("band_id") or self.tracker.band_id,
                pending_id=stored.get("pending_id"),
                pending_since=stored.get("pending_since"),
            )
            frozen = stored.get("frozen") or [None, None]
            self._frozen = (frozen[0], frozen[1])

        watch = [
            entity
            for entity in (
                self.config.get(CONF_OUTDOOR_SENSOR),
                self.config.get(CONF_OUTDOOR_SENSOR_BACKUP),
                self.config.get(CONF_INDOOR_SENSOR),
                self.config.get(CONF_INDOOR_SENSOR_BACKUP),
            )
            if entity
        ]
        if watch:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, watch, self._async_sensor_changed
                )
            )
        await self.async_refresh()
        self._log_table_diagnostics()

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._delayed_refresh is not None:
            self._delayed_refresh()
            self._delayed_refresh = None

    async def async_save(self) -> None:
        data = self.profile.to_dict()
        data.update(
            {
                "enabled": self.enabled,
                "band_id": self.tracker.band_id,
                "pending_id": self.tracker.pending_id,
                "pending_since": self.tracker.pending_since,
                "frozen": [self._frozen[0], self._frozen[1]],
            }
        )
        await self._store.async_save(data)

    # ------------------------------------------------------------------ inputs
    def _warn_once(self, key: str, message: str, *args: Any) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        _LOGGER.warning(message, *args)

    def _read_temperature(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        if entity_id.split(".", 1)[0] == "weather":
            attributes = dict(state.attributes)
            attributes.setdefault("device_class", "temperature")
            return parse_temperature(attributes.get("temperature"), attributes)
        value = parse_temperature(state.state, state.attributes)
        if value is None and state.state not in ("unknown", "unavailable", ""):
            self._warn_once(
                f"unit:{entity_id}",
                "智能热水：%s 不是摄氏温度读数（当前 %s %s），已忽略；请检查传感器配置",
                entity_id,
                state.state,
                state.attributes.get("unit_of_measurement"),
            )
        return value

    def _outdoor(self) -> tuple[float | None, str]:
        for key, source in (
            (CONF_OUTDOOR_SENSOR, "primary"),
            (CONF_OUTDOOR_SENSOR_BACKUP, "backup"),
        ):
            value = self._read_temperature(self.config.get(key))
            if value is not None:
                return value, source
        if self._last_outdoor is not None:
            self._warn_once(
                "outdoor:stale",
                "智能热水：室外温度不可用，暂用上一次有效值 %.1f°C 并冻结输出",
                self._last_outdoor,
            )
            return self._last_outdoor, "stale"
        self._warn_once(
            "outdoor:none", "智能热水：室外温度不可用且无历史值，保持当前分档与输出"
        )
        return None, "none"

    def _indoor(self) -> tuple[float | None, str]:
        for key, source in (
            (CONF_INDOOR_SENSOR, "primary"),
            (CONF_INDOOR_SENSOR_BACKUP, "backup"),
        ):
            value = self._read_temperature(self.config.get(key))
            if value is not None:
                return value, source
        return None, "none"

    @property
    def trim_enabled(self) -> bool:
        return bool(self.config.get(CONF_ENABLE_INDOOR_TRIM, True))

    # ------------------------------------------------------------- evaluation
    def _compute(self) -> dict[str, Any]:
        now = time.time()
        outdoor, outdoor_source = self._outdoor()
        indoor, indoor_source = self._indoor()
        # 只有真实读数才驱动分档与下发；"stale" 仅用于显示与保持
        valid = outdoor is not None and outdoor_source in ("primary", "backup")

        hold_remaining: float | None = None
        if valid:
            self._last_outdoor = outdoor
            changed, hold_remaining = self.tracker.update(
                outdoor, now, self.hysteresis, self.hold_seconds
            )
            if changed:
                _LOGGER.info(
                    "智能热水：分档切换 %s（室外 %.1f°C，迟滞 %.1f，保持 %.0f 分钟）",
                    band_label(self.tracker.band_id),
                    outdoor,
                    self.hysteresis,
                    self.hold_seconds / 60,
                )
                self.hass.async_create_task(self.async_save())
        elif self.tracker.band_id not in BAND_IDS:
            self.tracker.force(resolve_band(20.0)["id"])

        band = self.tracker.band_id
        if valid:
            trim = indoor_trim(indoor, outdoor, self.trim_enabled)
            self._last_trim = trim
        else:
            # 输入失效 → 保持上一次输出，不做任何微调
            trim = self._last_trim

        bath_calc = self.profile.value_for(KIND_BATH, band, trim)
        daily_calc = self.profile.value_for(KIND_DAILY, band)

        if self.enabled:
            bath, daily = bath_calc, daily_calc
            self._frozen = (bath_calc, daily_calc)
        elif self._frozen[0] is None or self._frozen[1] is None:
            self._frozen = (bath_calc, daily_calc)
            bath, daily = bath_calc, daily_calc
        else:
            bath, daily = int(self._frozen[0]), int(self._frozen[1])

        return {
            ATTR_BAND: band,
            ATTR_BAND_LABEL: band_label(band),
            ATTR_BAND_PENDING: self.tracker.pending_id,
            ATTR_BAND_HOLD_REMAINING: None
            if hold_remaining is None
            else round(hold_remaining, 1),
            ATTR_BAND_HOLD_MINUTES: self.hold_seconds / 60,
            ATTR_HYSTERESIS: self.hysteresis,
            ATTR_OUTDOOR: outdoor,
            ATTR_OUTDOOR_SOURCE: outdoor_source,
            ATTR_INDOOR: indoor,
            ATTR_INDOOR_SOURCE: indoor_source,
            ATTR_INPUT_VALID: valid,
            ATTR_TRIM: trim,
            "bath": bath,
            "daily": daily,
            "bath_calculated": bath_calc,
            "daily_calculated": daily_calc,
            ATTR_BATH_TABLE: self.profile.bath_table,
            ATTR_DAILY_TABLE: self.profile.daily_table,
            ATTR_BATH_OFFSETS: dict(self.profile.bath_offsets),
            ATTR_DAILY_OFFSETS: dict(self.profile.daily_offsets),
            "factory_bath_table": dict(FACTORY_BATH),
            "factory_daily_table": dict(FACTORY_DAILY),
            "bath_min": self.profile.bath_min,
            "bath_max": self.profile.bath_max,
            "daily_min": self.profile.daily_min,
            "daily_max": self.profile.daily_max,
            "enabled": self.enabled,
            "sync_device": self.sync_device,
            ATTR_DEVICE_MODE: self._device_mode,
            ATTR_DEVICE_VALUE: self._device_value,
            "bath_calibration": self._calibration_info(KIND_BATH, band),
            "daily_calibration": self._calibration_info(KIND_DAILY, band),
        }

    def _calibration_info(self, kind: str, band: str) -> dict[str, Any]:
        applied = self.profile.offset_for(kind, band)
        result = self._last_calibration.get(kind)
        if result is not None and result.band_id == band:
            return {
                "band": result.band_id,
                "requested_offset": result.requested_offset,
                "applied_offset": result.applied_offset,
                "clamped": result.clamped,
                "value": result.value,
                "value_clamped": result.value_clamped,
            }
        return {
            "band": band,
            "requested_offset": None,
            "applied_offset": applied,
            "clamped": None,
            "value": self.profile.value_for(kind, band),
        }

    async def _async_update_data(self) -> dict[str, Any]:
        if self._applying:
            return self.data or {}
        try:
            data = self._compute()
        except Exception:  # noqa: BLE001 - never take every entity down
            _LOGGER.exception("智能热水：计算异常，保持上一次结果")
            return self.data or {}
        if self.enabled and data[ATTR_INPUT_VALID]:
            await self._async_push_device(int(data["bath"]), int(data["daily"]))
            data[ATTR_DEVICE_MODE] = self._device_mode
            data[ATTR_DEVICE_VALUE] = self._device_value
        return data

    # ------------------------------------------------------------ device sync
    @property
    def _device_target(self) -> str | None:
        return self.config.get(CONF_DEVICE_TARGET)

    async def _async_push_device(self, bath: int, daily: int) -> None:
        """Push the setpoint, never fighting a manual/automation change.

        The integration only writes when the device still holds the value it
        wrote last time (so automations and manual changes are respected) and
        only when the value for the current mode actually changed.
        """
        entity_id = self._device_target
        if not entity_id or not self.sync_device:
            return
        state = self.hass.states.get(entity_id)
        if state is None:
            return
        try:
            current = int(round(float(state.state)))
        except (TypeError, ValueError):
            return

        if self._device_value is None:
            if current == bath:
                self._device_mode, self._device_value = "bath", bath
            elif current == daily:
                self._device_mode, self._device_value = "daily", daily
            elif not self._device_manual:
                self._device_manual = True
                _LOGGER.info(
                    "智能热水：设备目标 %s°C 既不是洗澡值也不是日常值，视为人工设定，停止自动下发",
                    current,
                )
                return
            else:
                return
        elif current != self._device_value:
            if current == bath:
                self._device_mode, self._device_value = "bath", bath
            elif current == daily:
                self._device_mode, self._device_value = "daily", daily
            else:
                self._device_mode = None
                self._device_value = None
                self._device_manual = True
                return

        desired = bath if self._device_mode == "bath" else daily
        if desired == self._device_value:
            return

        # ``number.set_value`` ignores input_number entities, so use the
        # entity's own domain (number.* or input_number.*).
        domain = entity_id.split(".", 1)[0]
        if not self.hass.services.has_service(domain, "set_value"):
            self._warn_once(
                f"device:service:{domain}",
                "智能热水：设备目标实体 %s 所在域 %s 没有 set_value 服务，无法下发",
                entity_id,
                domain,
            )
            return

        self._applying = True
        try:
            await self.hass.services.async_call(
                domain,
                "set_value",
                {"entity_id": entity_id, "value": desired},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - never break the coordinator
            _LOGGER.warning("智能热水：下发设备目标失败（%s）：%s", entity_id, err)
            return
        finally:
            self._applying = False
        _LOGGER.info("智能热水：设备目标下发为 %s°C（%s档）", desired, self._device_mode)
        self._device_value = desired

    # ------------------------------------------------------------ debouncing
    @callback
    def _async_sensor_changed(self, event: Event) -> None:
        now = time.monotonic()
        elapsed = now - self._last_state_refresh
        if elapsed >= MIN_REFRESH_SECONDS:
            self._last_state_refresh = now
            if self._delayed_refresh is not None:
                self._delayed_refresh()
                self._delayed_refresh = None
            self.hass.async_create_task(self.async_request_refresh())
            return
        if self._delayed_refresh is None:
            self._delayed_refresh = async_call_later(
                self.hass,
                MIN_REFRESH_SECONDS - elapsed,
                self._async_delayed_refresh,
            )

    @callback
    def _async_delayed_refresh(self, _now: Any = None) -> None:
        self._delayed_refresh = None
        self._last_state_refresh = time.monotonic()
        self.hass.async_create_task(self.async_request_refresh())

    # ------------------------------------------------------------ public API
    async def async_set_enabled(self, enabled: bool) -> None:
        if enabled == bool(self.enabled):
            return
        if not enabled:
            data = self._compute()
            self._frozen = (int(data["bath_calculated"]), int(data["daily_calculated"]))
            _LOGGER.info(
                "智能热水：动态已关闭，水温冻结为 洗澡 %s°C / 日常 %s°C",
                self._frozen[0],
                self._frozen[1],
            )
        self.enabled = bool(enabled)
        await self.async_save()
        await self.async_refresh()

    async def async_set_sync(self, sync: bool) -> None:
        self.sync_device = bool(sync)
        if not sync:
            self._device_mode = None
            self._device_value = None
        await self.async_save()
        await self.async_refresh()

    async def async_calibrate_bath(self, desired: float) -> CalibrationResult:
        return await self._async_calibrate(KIND_BATH, desired)

    async def async_calibrate_daily(self, desired: float) -> CalibrationResult:
        return await self._async_calibrate(KIND_DAILY, desired)

    async def _async_calibrate(self, kind: str, desired: float) -> CalibrationResult:
        outdoor, _source = self._outdoor()
        if outdoor is None or not self.data or not self.data.get(ATTR_INPUT_VALID):
            raise HomeAssistantError(
                "智能热水：室外温度不可用，无法判断当前分档，已取消校准"
            )
        indoor, _ = self._indoor()
        trim = indoor_trim(indoor, outdoor, self.trim_enabled)
        band = self.tracker.band_id
        if kind == KIND_DAILY:
            trim = 0
        result = self.profile.calibrate(kind, desired, band, trim)
        self._last_calibration[kind] = result
        await self.async_save()
        await self.async_refresh()
        name = "洗澡" if kind == KIND_BATH else "日常"
        _LOGGER.info(
            "智能热水：%s校准 → %s°C（分档=%s，偏移 %+d→%+d%s）",
            name,
            result.value,
            band_label(band),
            result.requested_offset,
            result.applied_offset,
            "，偏移受上下限窗口限制" if result.clamped else "",
        )
        if result.clamped or result.value_clamped:
            _LOGGER.warning(
                "智能热水：期望%s %.0f°C 未能完全生效，实际 %s°C（偏移 %+d，受%s限制）；"
                "如需更高/更低请先调整对应的上下限实体",
                name,
                desired,
                result.value,
                result.applied_offset,
                "偏移窗口" if result.clamped else "上下限",
            )
        return result

    async def async_set_limit(self, kind: str, value: float) -> None:
        key = {
            "bath_min": "bath_min",
            "bath_max": "bath_max",
            "daily_min": "daily_min",
            "daily_max": "daily_max",
        }.get(kind)
        if key is None:
            return
        clamped = max(LIMIT_ENTITY_ABS_MIN, min(LIMIT_ENTITY_ABS_MAX, int(round(value))))
        if clamped != int(round(value)):
            _LOGGER.warning(
                "智能热水：%s=%.0f 超出安全范围 %s-%s，已按 %s 生效",
                kind,
                value,
                LIMIT_ENTITY_ABS_MIN,
                LIMIT_ENTITY_ABS_MAX,
                clamped,
            )
        notes = self.profile.set_limits(**{key: clamped})
        if notes:
            _LOGGER.info("智能热水：调整上下限后重拟合偏移：%s", "；".join(notes))
        if kind == "bath_max" and self.profile.bath_max > SCALD_WARN_TEMP:
            _LOGGER.warning(
                "智能热水：洗澡上限 %s°C 高于 %s°C，注意烫伤风险",
                self.profile.bath_max,
                SCALD_WARN_TEMP,
            )
        await self.async_save()
        await self.async_refresh()
        self._log_table_diagnostics()

    async def async_set_offset(self, kind: str, offset: int, band_id: str | None) -> None:
        self.profile.set_offset(kind, int(offset), band_id)
        await self.async_save()
        await self.async_refresh()
        _LOGGER.info(
            "智能热水：%s偏移设为 %+d（%s）",
            "洗澡" if kind == KIND_BATH else "日常",
            int(offset),
            band_id or "全部档位",
        )

    async def async_set_band(self, band_id: str) -> None:
        if band_id not in BAND_IDS:
            raise HomeAssistantError(f"智能热水：未知分档 {band_id}")
        self.tracker.force(band_id)
        await self.async_save()
        await self.async_refresh()
        _LOGGER.info("智能热水：分档手动锁定为 %s", band_label(band_id))

    async def async_reset_table(self) -> None:
        self.profile.reset()
        await self.async_save()
        await self.async_refresh()
        _LOGGER.info("智能热水：分档表已恢复出厂（偏移全部清零）")

    def _log_table_diagnostics(self) -> None:
        bath_flat, daily_flat = self.profile.flat_tables()
        if bath_flat:
            _LOGGER.warning(
                "智能热水：洗澡分档表已无季节梯度（各档 %s），"
                "多为「洗澡上限」偏低导致；如需按季节区分请上调洗澡上限",
                self.profile.bath_table,
            )
        if daily_flat:
            _LOGGER.info("智能热水：日常分档表各档相同 %s", self.profile.daily_table)
        if FACTORY_BATH["cold"] + self.profile.bath_offsets["cold"] > self.profile.bath_max:
            _LOGGER.info(
                "智能热水：冷天档位受洗澡上限 %s°C 限制", self.profile.bath_max
            )
