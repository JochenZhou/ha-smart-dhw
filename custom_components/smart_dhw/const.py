"""Constants for Smart DHW."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "smart_dhw"
PLATFORMS: Final = ["number", "switch", "sensor", "binary_sensor"]

CONF_NAME: Final = "name"
CONF_OUTDOOR_SENSOR: Final = "outdoor_sensor"
CONF_OUTDOOR_SENSOR_BACKUP: Final = "outdoor_sensor_backup"
CONF_INDOOR_SENSOR: Final = "indoor_sensor"
CONF_INDOOR_SENSOR_BACKUP: Final = "indoor_sensor_backup"
CONF_DEVICE_TARGET: Final = "device_target_entity"
CONF_ENABLE_INDOOR_TRIM: Final = "enable_indoor_trim"
CONF_SYNC_DEVICE: Final = "sync_device"
CONF_HYSTERESIS: Final = "hysteresis"
CONF_BAND_HOLD_MINUTES: Final = "band_hold_minutes"

# Legacy keys (removed from UI; still honoured when migrating old storage)
CONF_BATH_TARGET: Final = "bath_target_entity"
CONF_DAILY_TARGET: Final = "daily_target_entity"
CONF_BATH_MIN: Final = "bath_min"
CONF_BATH_MAX: Final = "bath_max"
CONF_DAILY_MIN: Final = "daily_min"
CONF_DAILY_MAX: Final = "daily_max"

DEFAULT_NAME: Final = "智能热水"
DEFAULT_BATH_MIN: Final = 37
DEFAULT_BATH_MAX: Final = 40
DEFAULT_DAILY_MIN: Final = 35
DEFAULT_DAILY_MAX: Final = 38

# Band switching
DEFAULT_HYSTERESIS: Final = 1.0
DEFAULT_BAND_HOLD_MINUTES: Final = 30
MIN_REFRESH_SECONDS: Final = 60

# Absolute hardware-ish bounds for the limit entities themselves
LIMIT_ENTITY_ABS_MIN: Final = 30
LIMIT_ENTITY_ABS_MAX: Final = 50
# Above this, warn about scalding on the hand-shower
SCALD_WARN_TEMP: Final = 45

# 洗澡水温必须高于日常水温至少这么多（否则两条自动化会互相打架）
MIN_BATH_DAILY_GAP: Final = 1

# 传感器数值合理性窗口（°C）；超出即判定读数无效
TEMP_PLAUSIBLE_MIN: Final = -40.0
TEMP_PLAUSIBLE_MAX: Final = 70.0

# Outdoor temperature lower bounds (high → low). First match wins.
BANDS: Final = (
    {"id": "hot", "outdoor_min": 28.0, "bath": 37, "daily": 35, "label": "盛夏"},
    {"id": "warm", "outdoor_min": 22.0, "bath": 38, "daily": 35, "label": "夏末/初秋"},
    {"id": "mild", "outdoor_min": 15.0, "bath": 39, "daily": 36, "label": "春秋"},
    {"id": "cool", "outdoor_min": 8.0, "bath": 40, "daily": 37, "label": "深秋/初冬"},
    {"id": "cold", "outdoor_min": -100.0, "bath": 40, "daily": 38, "label": "严寒"},
)

BAND_IDS: Final = tuple(str(b["id"]) for b in BANDS)
BAND_LABELS: Final = {str(b["id"]): str(b["label"]) for b in BANDS}
FACTORY_BATH: Final = {str(b["id"]): int(b["bath"]) for b in BANDS}
FACTORY_DAILY: Final = {str(b["id"]): int(b["daily"]) for b in BANDS}

INDOOR_COLD: Final = 18.0
INDOOR_HOT: Final = 28.0
OUTDOOR_FOR_HOT_TRIM: Final = 25.0

STORAGE_VERSION: Final = 3
STORAGE_KEY: Final = "smart_dhw_tables"

ATTR_BAND: Final = "band"
ATTR_BAND_LABEL: Final = "band_label"
ATTR_BAND_PENDING: Final = "band_pending"
ATTR_BAND_HOLD_REMAINING: Final = "band_hold_remaining"
ATTR_BAND_HOLD_MINUTES: Final = "band_hold_minutes"
ATTR_HYSTERESIS: Final = "hysteresis"
ATTR_OUTDOOR: Final = "outdoor_temperature"
ATTR_OUTDOOR_SOURCE: Final = "outdoor_source"
ATTR_INDOOR: Final = "indoor_temperature"
ATTR_INDOOR_SOURCE: Final = "indoor_source"
ATTR_INPUT_VALID: Final = "input_valid"
ATTR_TRIM: Final = "indoor_trim"
ATTR_OFFSET: Final = "calibration_offset"
ATTR_OFFSET_REQUESTED: Final = "requested_offset"
ATTR_OFFSET_APPLIED: Final = "applied_offset"
ATTR_OFFSET_CLAMPED: Final = "offset_clamped"
ATTR_DAILY_OFFSET: Final = "daily_calibration_offset"
ATTR_BATH_OFFSETS: Final = "bath_offsets"
ATTR_DAILY_OFFSETS: Final = "daily_offsets"
ATTR_BATH_TABLE: Final = "bath_table"
ATTR_DAILY_TABLE: Final = "daily_table"
ATTR_FACTORY_BATH: Final = "factory_bath_table"
ATTR_FACTORY_DAILY: Final = "factory_daily_table"
ATTR_DEVICE_MODE: Final = "device_mode"
ATTR_DEVICE_VALUE: Final = "device_target_value"
ATTR_DEVICE_SYNCED: Final = "device_synced"

SERVICE_RESET_TABLE: Final = "reset_table"
SERVICE_RECALCULATE: Final = "recalculate"
SERVICE_CALIBRATE_BATH: Final = "calibrate_bath"
SERVICE_CALIBRATE_DAILY: Final = "calibrate_daily"
SERVICE_SET_OFFSET: Final = "set_offset"
SERVICE_SET_BAND: Final = "set_band"
