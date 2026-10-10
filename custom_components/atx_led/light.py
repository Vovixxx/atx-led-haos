"""Light platform for ATX LED."""

from __future__ import annotations

from functools import partial
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .brightness import dali_to_ha_brightness, ha_brightness_to_dali
from .client import ATXLEDError
from .const import (
    ATTR_DALI_CHANNEL,
    ATTR_DALI_COLOR_TEMP_KELVIN,
    ATTR_DALI_GROUP_ADDRESS,
    ATTR_DALI_GROUP_KIND,
    ATTR_DALI_MEMBERS,
    ATTR_DALI_SHORT_ADDRESS,
    ATTR_DALI_STATE_SOURCE,
    ATTR_DALI_STATUS,
)
from .commands import kelvin_limits
from .coordinator import ATXLEDConfigEntry, ATXLEDCoordinator
from .device_info import light_device_registry_info
from .models import GroupDevice, LightDevice
from .protocol import DALI_MAX_ARC_LEVEL

PARALLEL_UPDATES = 1


def _restore_level(device: LightDevice | GroupDevice) -> int:
    if device.stored_level and device.stored_level > 0:
        return min(device.stored_level, DALI_MAX_ARC_LEVEL)
    return min(device.max_level, DALI_MAX_ARC_LEVEL)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ATXLEDConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up ATX LED lights from a config entry."""
    coordinator = entry.runtime_data
    current_ids: set[str] = set()
    update_lights = partial(async_add_new_lights, coordinator, current_ids, async_add_entities)
    entry.async_on_unload(coordinator.async_add_listener(update_lights))
    update_lights()
    # Colour for fixtures never written comes from the driver, once, one fixture at a time.
    entry.async_create_background_task(
        hass, coordinator.async_read_missing_colors(), "atx-led-read-colors"
    )


@callback
def async_add_new_lights(
    coordinator: ATXLEDCoordinator,
    current_ids: set[str],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create entities for newly discovered lights without duplicating existing ones."""
    if coordinator.data is None:
        return
    new_entities = [
        ATXLEDLight(coordinator, device_id)
        for device_id in coordinator.data.lights
        if device_id not in current_ids
    ]
    new_entities.extend(
        ATXLEDGroupLight(coordinator, device_id)
        for device_id in coordinator.data.groups
        if f"group:{device_id}" not in current_ids
    )
    current_ids.update(
        entity.device_id
        if isinstance(entity, ATXLEDLight)
        else f"group:{entity.device_id}"
        for entity in new_entities
    )
    if new_entities:
        async_add_entities(new_entities)


class ATXLEDLight(CoordinatorEntity[ATXLEDCoordinator], RestoreEntity, LightEntity):
    """A commissioned ATX LED DALI fixture."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: ATXLEDCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        device = coordinator.get_light(device_id)
        suffix = device.unique_suffix if device else device_id
        self._attr_unique_id = f"{coordinator.hub_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            **light_device_registry_info(
                unique_id=self._attr_unique_id,
                name=device.name if device else device_id,
                hub_device_id=coordinator.hub_device_id,
            )
        )
        self._apply_capabilities(device)

    def _apply_capabilities(self, device: LightDevice | None) -> None:
        limits = kelvin_limits(device) if device else None
        if device and device.has_color_temp and limits:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_min_color_temp_kelvin = limits[0]
            self._attr_max_color_temp_kelvin = limits[1]
        else:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS

    @property
    def _device(self) -> LightDevice | None:
        return self.coordinator.get_light(self.device_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        device = self._device
        self._apply_capabilities(device)
        if device is not None and self.device_entry is not None:
            if self.device_entry.name != device.name:
                self.device_entry = dr.async_get(self.hass).async_update_device(
                    self.device_entry.id, name=device.name
                )
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        device = self._device
        return super().available and device is not None and device.available

    @property
    def is_on(self) -> bool | None:
        device = self._device
        if device is None or device.is_on is None:
            return None
        return device.is_on

    @property
    def brightness(self) -> int | None:
        device = self._device
        if device is None or device.stored_level is None:
            return None
        return dali_to_ha_brightness(device.stored_level, device.min_level, device.max_level)

    @property
    def color_temp_kelvin(self) -> int | None:
        device = self._device
        if device is None or not device.has_color_temp:
            return None
        return device.color_temp_k

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device
        if device is None:
            return {}
        attributes: dict[str, Any] = {
            ATTR_DALI_CHANNEL: device.channel,
            ATTR_DALI_SHORT_ADDRESS: device.short_addr,
            ATTR_DALI_STATUS: device.status,
        }
        if device.has_color_temp and device.color_temp_k is not None:
            # Home Assistant drops color_temp_kelvin while the light is off; keep it for restore.
            attributes[ATTR_DALI_COLOR_TEMP_KELVIN] = device.color_temp_k
        return attributes

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None:
            return
        kelvin = last_state.attributes.get(ATTR_DALI_COLOR_TEMP_KELVIN)
        if kelvin is None:
            kelvin = last_state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        try:
            kelvin = int(kelvin) if kelvin is not None else None
        except (TypeError, ValueError):
            kelvin = None
        if kelvin:
            self.coordinator.async_restore_color(self.device_id, kelvin)

    def _intended_on(self, device: LightDevice) -> bool:
        intended = self.coordinator.intended_on(self.device_id)
        return bool(device.is_on) if intended is None else intended

    async def async_turn_on(self, **kwargs: Any) -> None:
        device = self._device
        if device is None:
            raise HomeAssistantError("Light is unavailable")
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN) if device.has_color_temp else None
        if ATTR_BRIGHTNESS in kwargs:
            level = ha_brightness_to_dali(
                int(kwargs[ATTR_BRIGHTNESS]), device.min_level, device.max_level
            )
        elif not self._intended_on(device):
            level = _restore_level(device)
        elif kelvin is None:
            return  # already on, nothing to change
        else:
            level = None  # colour only: the call re-sends the current level
        try:
            await self.coordinator.async_set_light(
                device.device_id, level, None if kelvin is None else int(kelvin)
            )
        except (ATXLEDError, ValueError) as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(str(err)) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        device = self._device
        if device is None:
            raise HomeAssistantError("Light is unavailable")
        try:
            await self.coordinator.async_set_light(device.device_id, 0)
        except (ATXLEDError, ValueError) as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(str(err)) from err

    async def async_toggle(self, **kwargs: Any) -> None:
        device = self._device
        if device is not None and self._intended_on(device):
            await self.async_turn_off()
        else:
            await self.async_turn_on(**kwargs)


class ATXLEDGroupLight(CoordinatorEntity[ATXLEDCoordinator], LightEntity):
    """A commissioned ATX LED DALI group or hub virtual group."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: ATXLEDCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        group = coordinator.get_group(device_id)
        suffix = group.unique_suffix if group else f"g_{device_id}"
        self._attr_unique_id = f"{coordinator.hub_id}_{suffix}"
        self._attr_device_info = DeviceInfo(
            **light_device_registry_info(
                unique_id=self._attr_unique_id,
                name=group.name if group else device_id,
                hub_device_id=coordinator.hub_device_id,
                model="DALI Group" if not group or group.is_dali_group else "Virtual Group",
            )
        )
        self._apply_capabilities(group)

    def _apply_capabilities(self, group: GroupDevice | None) -> None:
        limits = kelvin_limits(group) if group else None
        lights = self.coordinator.data.lights if self.coordinator.data else {}
        has_cct_member = bool(group) and any(
            member_id in lights and lights[member_id].has_color_temp
            for member_id in group.members
        )
        if group and group.has_color_temp and limits and has_cct_member:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_min_color_temp_kelvin = limits[0]
            self._attr_max_color_temp_kelvin = limits[1]
        else:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS

    @property
    def _group(self) -> GroupDevice | None:
        return self.coordinator.get_group(self.device_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        group = self._group
        self._apply_capabilities(group)
        if group is not None and self.device_entry is not None:
            if self.device_entry.name != group.name:
                self.device_entry = dr.async_get(self.hass).async_update_device(
                    self.device_entry.id, name=group.name
                )
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        group = self._group
        return super().available and group is not None and group.available

    @property
    def is_on(self) -> bool | None:
        group = self._group
        if group is None or group.is_on is None:
            return None
        return group.is_on

    @property
    def brightness(self) -> int | None:
        group = self._group
        if group is None or group.stored_level is None:
            return None
        return dali_to_ha_brightness(group.stored_level, group.min_level, group.max_level)

    @property
    def color_temp_kelvin(self) -> int | None:
        group = self._group
        if group is None or not group.has_color_temp:
            return None
        return group.color_temp_k

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        group = self._group
        if group is None:
            return {}
        return {
            ATTR_DALI_CHANNEL: group.channel,
            ATTR_DALI_GROUP_ADDRESS: group.group_addr,
            ATTR_DALI_GROUP_KIND: group.kind,
            ATTR_DALI_MEMBERS: list(group.members),
            ATTR_DALI_STATE_SOURCE: group.state_source,
        }

    def _intended_on(self, group: GroupDevice) -> bool:
        intended = self.coordinator.intended_on(self.device_id)
        return bool(group.is_on) if intended is None else intended

    async def async_turn_on(self, **kwargs: Any) -> None:
        group = self._group
        if group is None:
            raise HomeAssistantError("Group is unavailable")
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN) if group.has_color_temp else None
        if ATTR_BRIGHTNESS in kwargs:
            level = ha_brightness_to_dali(
                int(kwargs[ATTR_BRIGHTNESS]), group.min_level, group.max_level
            )
        elif not self._intended_on(group):
            level = _restore_level(group)
        elif kelvin is None:
            return  # already on, nothing to change
        else:
            level = None  # colour only: the call re-sends the current level
        try:
            await self.coordinator.async_set_group(
                group.device_id, level, None if kelvin is None else int(kelvin)
            )
        except (ATXLEDError, ValueError) as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(str(err)) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        group = self._group
        if group is None:
            raise HomeAssistantError("Group is unavailable")
        try:
            await self.coordinator.async_set_group(group.device_id, 0)
        except (ATXLEDError, ValueError) as err:
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(str(err)) from err

    async def async_toggle(self, **kwargs: Any) -> None:
        group = self._group
        if group is not None and self._intended_on(group):
            await self.async_turn_off()
        else:
            await self.async_turn_on(**kwargs)
