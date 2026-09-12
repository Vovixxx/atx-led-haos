"""Scene platform for ATX LED."""

from __future__ import annotations

from functools import partial
from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import ATXLEDError
from .const import (
    ATTR_DALI_CHANNEL,
    ATTR_DALI_GROUP_ADDRESS,
    ATTR_DALI_MEMBERS,
    ATTR_DALI_SCENE,
    DOMAIN,
)
from .coordinator import ATXLEDConfigEntry, ATXLEDCoordinator
from .models import SceneDevice

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ATXLEDConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up ATX LED scenes from a config entry."""
    coordinator = entry.runtime_data
    current_ids: set[str] = set()
    update_scenes = partial(
        async_add_new_scenes, coordinator, current_ids, async_add_entities
    )
    entry.async_on_unload(coordinator.async_add_listener(update_scenes))
    update_scenes()


@callback
def async_add_new_scenes(
    coordinator: ATXLEDCoordinator,
    current_ids: set[str],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create entities for newly discovered scenes without duplicating existing ones."""
    if coordinator.data is None:
        return
    new_entities = [
        ATXLEDScene(coordinator, scene_id)
        for scene_id in coordinator.data.scenes
        if scene_id not in current_ids
    ]
    current_ids.update(entity.scene_id for entity in new_entities)
    if new_entities:
        async_add_entities(new_entities)


class ATXLEDScene(CoordinatorEntity[ATXLEDCoordinator], Scene):
    """A named hub scene recalled with individual or group GO TO SCENE."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: ATXLEDCoordinator, scene_id: str) -> None:
        super().__init__(coordinator)
        self.scene_id = scene_id
        scene = coordinator.get_scene(scene_id)
        suffix = scene.unique_suffix if scene else f"scene_{scene_id}"
        self._attr_unique_id = f"{coordinator.hub_id}_{suffix}"
        self._attr_name = scene.name if scene else scene_id
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.hub_id)})

    @property
    def _scene(self) -> SceneDevice | None:
        return self.coordinator.get_scene(self.scene_id)

    @property
    def available(self) -> bool:
        scene = self._scene
        return super().available and scene is not None and scene.dali_scene is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        scene = self._scene
        if scene is None:
            return {}
        attrs: dict[str, Any] = {ATTR_DALI_SCENE: scene.dali_scene}
        if scene.channel is not None:
            attrs[ATTR_DALI_CHANNEL] = scene.channel
        if scene.group_addr is not None:
            attrs[ATTR_DALI_GROUP_ADDRESS] = scene.group_addr
        if scene.members:
            attrs[ATTR_DALI_MEMBERS] = list(scene.members)
        return attrs

    async def async_activate(self, **kwargs: Any) -> None:
        scene = self._scene
        if scene is None:
            raise HomeAssistantError("Scene is unavailable")
        lights = self.coordinator.data.lights if self.coordinator.data else {}
        try:
            await self.coordinator.client.async_recall_scene(scene, lights)
        except ATXLEDError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
