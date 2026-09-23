"""Config flow for Smart DHW."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
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
    DEFAULT_NAME,
    DOMAIN,
)
from .table import parse_temperature

SENSOR_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["sensor", "weather"], multiple=False)
)
OPTIONAL_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["sensor"], multiple=False)
)
NUMBER_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["number", "input_number"], multiple=False)
)

HYSTERESIS_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=5, step=0.5, mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="°C",
    )
)
HOLD_SELECTOR = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0, max=720, step=5, mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="分钟",
    )
)

LEGACY_KEYS = (
    "bath_target_entity",
    "daily_target_entity",
    "bath_min",
    "bath_max",
    "daily_min",
    "daily_max",
)


def _optional_entity_field(key: str, data: dict[str, Any], selector_obj):
    if data.get(key):
        return vol.Optional(key, default=data.get(key)), selector_obj
    return vol.Optional(key), selector_obj


def _looks_like_temperature(
    hass: HomeAssistant, entity_id: str | None, required: bool
) -> bool:
    """Reject entities that are not Celsius temperature readings."""
    if not entity_id:
        return not required
    state = hass.states.get(entity_id)
    if state is None:
        # entity may be temporarily unavailable; allow but it will be ignored
        return True
    if entity_id.split(".", 1)[0] == "weather":
        return True
    if state.state in ("unknown", "unavailable", ""):
        return True
    return parse_temperature(state.state, state.attributes) is not None


class SmartDhwConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Smart DHW."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            checks = (
                (CONF_OUTDOOR_SENSOR, True),
                (CONF_OUTDOOR_SENSOR_BACKUP, False),
                (CONF_INDOOR_SENSOR, False),
                (CONF_INDOOR_SENSOR_BACKUP, False),
            )
            for key, required in checks:
                if not _looks_like_temperature(self.hass, user_input.get(key), required):
                    errors[key] = "not_a_temperature"
            if errors:
                return self.async_show_form(
                    step_id="user",
                    data_schema=self._schema(user_input),
                    errors=errors,
                )
            await self.async_set_unique_id(
                f"{user_input[CONF_OUTDOOR_SENSOR]}_{user_input.get(CONF_DEVICE_TARGET, 'nodev')}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input.get(CONF_NAME) or DEFAULT_NAME,
                data=user_input,
            )

        return self.async_show_form(step_id="user", data_schema=self._schema({}))

    def _schema(self, data: dict[str, Any]) -> vol.Schema:
        def key(name: str):
            if data.get(name):
                return vol.Optional(name, default=data.get(name))
            return vol.Optional(name)

        fields: dict[Any, Any] = {
            vol.Required(CONF_NAME, default=data.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(
                CONF_OUTDOOR_SENSOR, default=data.get(CONF_OUTDOOR_SENSOR)
            ): SENSOR_SELECTOR,
            key(CONF_OUTDOOR_SENSOR_BACKUP): OPTIONAL_SENSOR,
            key(CONF_INDOOR_SENSOR): OPTIONAL_SENSOR,
            key(CONF_INDOOR_SENSOR_BACKUP): OPTIONAL_SENSOR,
            key(CONF_DEVICE_TARGET): NUMBER_SELECTOR,
            vol.Required(
                CONF_ENABLE_INDOOR_TRIM, default=data.get(CONF_ENABLE_INDOOR_TRIM, True)
            ): bool,
            vol.Required(
                CONF_SYNC_DEVICE, default=data.get(CONF_SYNC_DEVICE, True)
            ): bool,
            vol.Required(
                CONF_HYSTERESIS, default=data.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)
            ): HYSTERESIS_SELECTOR,
            vol.Required(
                CONF_BAND_HOLD_MINUTES,
                default=data.get(CONF_BAND_HOLD_MINUTES, DEFAULT_BAND_HOLD_MINUTES),
            ): HOLD_SELECTOR,
        }
        return vol.Schema(fields)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return SmartDhwOptionsFlow()


class SmartDhwOptionsFlow(config_entries.OptionsFlow):
    """Options flow — sensors/device/tuning only; limits are entities."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            for key, required in (
                (CONF_OUTDOOR_SENSOR, True),
                (CONF_OUTDOOR_SENSOR_BACKUP, False),
                (CONF_INDOOR_SENSOR, False),
                (CONF_INDOOR_SENSOR_BACKUP, False),
            ):
                if not _looks_like_temperature(self.hass, user_input.get(key), required):
                    errors[key] = "not_a_temperature"
            if not errors:
                new_data = {**self.config_entry.data}
                for legacy in LEGACY_KEYS:
                    new_data.pop(legacy, None)
                for key, value in user_input.items():
                    if value in (None, "", []):
                        new_data.pop(key, None)
                    else:
                        new_data[key] = value
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(title="", data={})

        data = self.config_entry.data
        fields: dict[Any, Any] = {
            vol.Required(
                CONF_OUTDOOR_SENSOR, default=data.get(CONF_OUTDOOR_SENSOR)
            ): SENSOR_SELECTOR,
        }
        for key, sel in (
            (CONF_OUTDOOR_SENSOR_BACKUP, OPTIONAL_SENSOR),
            (CONF_INDOOR_SENSOR, OPTIONAL_SENSOR),
            (CONF_INDOOR_SENSOR_BACKUP, OPTIONAL_SENSOR),
            (CONF_DEVICE_TARGET, NUMBER_SELECTOR),
        ):
            k, s = _optional_entity_field(key, data, sel)
            fields[k] = s

        fields.update(
            {
                vol.Required(
                    CONF_ENABLE_INDOOR_TRIM,
                    default=data.get(CONF_ENABLE_INDOOR_TRIM, True),
                ): bool,
                vol.Required(
                    CONF_SYNC_DEVICE, default=data.get(CONF_SYNC_DEVICE, True)
                ): bool,
                vol.Required(
                    CONF_HYSTERESIS,
                    default=data.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS),
                ): HYSTERESIS_SELECTOR,
                vol.Required(
                    CONF_BAND_HOLD_MINUTES,
                    default=data.get(
                        CONF_BAND_HOLD_MINUTES, DEFAULT_BAND_HOLD_MINUTES
                    ),
                ): HOLD_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(fields), errors=errors
        )
