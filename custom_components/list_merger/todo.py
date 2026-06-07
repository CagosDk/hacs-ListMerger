"""Virtual master todo list entity for List Merger."""
from __future__ import annotations

import logging
import uuid

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.storage import Store

from .const import CONF_MASTER_NAME, CONF_MASTER_TYPE, DOMAIN, MASTER_TYPE_NEW, STORAGE_VERSION
from .coordinator import ListMergerCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up List Merger todo entities from a config entry."""
    coordinator: ListMergerCoordinator = hass.data[DOMAIN][entry.entry_id]

    if entry.data.get(CONF_MASTER_TYPE) == MASTER_TYPE_NEW:
        name = entry.data.get(CONF_MASTER_NAME, "Merged List")
        entity = MasterTodoListEntity(hass, coordinator, entry, name)
        coordinator.set_master_entity(entity)
        async_add_entities([entity])

    # Set up event listeners after entities are registered in HA
    hass.async_create_task(coordinator.async_setup_listeners())


class MasterTodoListEntity(TodoListEntity):
    """A virtual todo list that acts as the merged master list."""

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
    )

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ListMergerCoordinator,
        entry: ConfigEntry,
        name: str,
    ) -> None:
        self.hass = hass
        self._coordinator = coordinator
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_master"
        self._attr_name = name
        self._items: dict[str, TodoItem] = {}
        self._store = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_items_{entry.entry_id}"
        )

    async def async_added_to_hass(self) -> None:
        """Restore persisted items when entity loads."""
        stored = await self._store.async_load()
        if stored:
            for uid, data in stored.items():
                status_str = data.get("status", "needs_action")
                try:
                    status = TodoItemStatus(status_str)
                except ValueError:
                    status = TodoItemStatus.NEEDS_ACTION
                self._items[uid] = TodoItem(
                    uid=uid,
                    summary=data.get("summary", ""),
                    status=status,
                    description=data.get("description"),
                )
        self._refresh()

    def _refresh(self) -> None:
        self._attr_todo_items = list(self._items.values())
        self.async_write_ha_state()

    async def _save(self) -> None:
        await self._store.async_save(
            {
                uid: {
                    "summary": item.summary,
                    "status": item.status.value if item.status else "needs_action",
                    "description": item.description,
                }
                for uid, item in self._items.items()
            }
        )

    # ------------------------------------------------------------------
    # HA todo platform interface (called by services / UI)
    # ------------------------------------------------------------------

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Handle user-created item via HA service or UI."""
        uid = str(uuid.uuid4())
        new_item = TodoItem(
            uid=uid,
            summary=item.summary,
            status=item.status or TodoItemStatus.NEEDS_ACTION,
            description=item.description,
            due=item.due,
        )
        self._items[uid] = new_item
        self._refresh()
        await self._save()
        # Notify coordinator – no source origin, propagate to two-way sources
        self._coordinator.on_master_item_added(uid, item.summary or "")

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Handle deletion of items via HA service or UI."""
        for uid in uids:
            self._items.pop(uid, None)
            self._coordinator.on_master_item_removed(uid)
        self._refresh()
        await self._save()

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Handle updates to an existing item."""
        if item.uid not in self._items:
            return
        existing = self._items[item.uid]
        old_status = existing.status

        updated = TodoItem(
            uid=item.uid,
            summary=item.summary if item.summary is not None else existing.summary,
            status=item.status if item.status is not None else existing.status,
            description=item.description
            if item.description is not None
            else existing.description,
            due=item.due if item.due is not None else existing.due,
        )
        self._items[item.uid] = updated
        self._refresh()
        await self._save()

        if item.status is not None and item.status != old_status:
            self._coordinator.on_master_item_status_changed(
                item.uid, item.status.value
            )

    # ------------------------------------------------------------------
    # Internal methods called by the coordinator
    # ------------------------------------------------------------------

    async def async_create_todo_item_internal(
        self, summary: str, source_entity_id: str, source_uid: str
    ) -> str:
        """Add an item that originated from a source list."""
        uid = str(uuid.uuid4())
        self._items[uid] = TodoItem(
            uid=uid,
            summary=summary,
            status=TodoItemStatus.NEEDS_ACTION,
        )
        self._refresh()
        await self._save()
        self._coordinator.on_master_item_added(uid, summary, source_entity_id, source_uid)
        return uid

    async def async_delete_todo_item_internal(self, uid: str) -> None:
        """Remove an item by UID without triggering coordinator callbacks."""
        self._items.pop(uid, None)
        self._refresh()
        await self._save()

    async def async_update_todo_item_internal(self, uid: str, status: str) -> None:
        """Update item status without triggering coordinator callbacks."""
        if uid not in self._items:
            return
        existing = self._items[uid]
        try:
            new_status = TodoItemStatus(status)
        except ValueError:
            new_status = TodoItemStatus.NEEDS_ACTION
        self._items[uid] = TodoItem(
            uid=uid,
            summary=existing.summary,
            status=new_status,
            description=existing.description,
            due=existing.due,
        )
        self._refresh()
        await self._save()
