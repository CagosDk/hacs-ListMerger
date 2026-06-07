"""Coordinator for List Merger: handles all sync logic between todo lists."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store

from .const import (
    COMPLETED_DELETE_BOTH,
    COMPLETED_MASTER_ONLY,
    COMPLETED_SYNC_BACK,
    CONF_COMPLETED_BEHAVIOR,
    CONF_DELETE_ON_MERGE,
    CONF_DIRECTION,
    CONF_DUPLICATE_HANDLING,
    CONF_MASTER_ENTITY_ID,
    CONF_MASTER_TYPE,
    CONF_SOURCE_ENTITY_ID,
    CONF_SOURCES,
    DIRECTION_TWO_WAY,
    DOMAIN,
    DUPLICATE_DEDUPLICATE,
    MASTER_TYPE_NEW,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    from .todo import MasterTodoListEntity

_LOGGER = logging.getLogger(__name__)


class ListMergerCoordinator:
    """Coordinates syncing between multiple todo lists and the master list."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{entry.entry_id}")
        self._unsub_listeners: list = []
        # Tracks which entity IDs we are currently processing to prevent loops
        self._processing: set[str] = set()

        # source_snapshots: {entity_id: {uid: {"summary": str, "status": str}}}
        self._source_snapshots: dict[str, dict[str, dict]] = {}
        # master_snapshot: {master_uid: {"summary": str, "status": str, "origins": [...]}}
        self._master_snapshot: dict[str, dict] = {}

        self._master_entity: MasterTodoListEntity | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> dict:
        return self.entry.data

    @property
    def master_type(self) -> str:
        return self.config.get(CONF_MASTER_TYPE, MASTER_TYPE_NEW)

    @property
    def sources(self) -> list[dict]:
        return self.config.get(CONF_SOURCES, [])

    @property
    def duplicate_handling(self) -> str:
        return self.config.get(CONF_DUPLICATE_HANDLING, DUPLICATE_DEDUPLICATE)

    @property
    def completed_behavior(self) -> str:
        return self.config.get(CONF_COMPLETED_BEHAVIOR, COMPLETED_SYNC_BACK)

    def set_master_entity(self, entity: MasterTodoListEntity) -> None:
        """Register the virtual master todo entity."""
        self._master_entity = entity

    # ------------------------------------------------------------------
    # Setup / teardown
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load persisted state. Listeners are set up after entities are ready."""
        stored = await self._store.async_load()
        if stored:
            self._source_snapshots = stored.get("source_snapshots", {})
            self._master_snapshot = stored.get("master_snapshot", {})

    async def async_setup_listeners(self) -> None:
        """Register state-change listeners and run initial sync."""
        entity_ids = [src[CONF_SOURCE_ENTITY_ID] for src in self.sources]

        if self.master_type != MASTER_TYPE_NEW:
            master_id = self.config.get(CONF_MASTER_ENTITY_ID)
            if master_id:
                entity_ids.append(master_id)

        if entity_ids:
            self._unsub_listeners.append(
                async_track_state_change_event(
                    self.hass,
                    entity_ids,
                    self._async_on_state_changed,
                )
            )

        await self._async_initial_sync()

    async def async_unload(self) -> None:
        """Remove all listeners."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    @callback
    def _async_on_state_changed(self, event: Event) -> None:
        entity_id: str | None = event.data.get("entity_id")
        if entity_id and entity_id not in self._processing:
            self.hass.async_create_task(self._async_handle_state_change(entity_id))

    async def _async_handle_state_change(self, entity_id: str) -> None:
        if entity_id in self._processing:
            return

        source_config = self._get_source_config(entity_id)
        if source_config:
            await self._async_sync_source_to_master(entity_id)
            return

        if (
            self.master_type != MASTER_TYPE_NEW
            and entity_id == self.config.get(CONF_MASTER_ENTITY_ID)
        ):
            await self._async_sync_existing_master_to_sources(entity_id)

    # ------------------------------------------------------------------
    # Initial sync
    # ------------------------------------------------------------------

    async def _async_initial_sync(self) -> None:
        for source in self.sources:
            entity_id = source[CONF_SOURCE_ENTITY_ID]
            try:
                await self._async_sync_source_to_master(entity_id)
            except Exception as err:
                _LOGGER.error("Initial sync error for %s: %s", entity_id, err)

    # ------------------------------------------------------------------
    # Core sync: source → master
    # ------------------------------------------------------------------

    async def _async_sync_source_to_master(self, source_entity_id: str) -> None:
        source_config = self._get_source_config(source_entity_id)
        if not source_config:
            return

        self._processing.add(source_entity_id)
        try:
            current_items = await self._async_get_todo_items(source_entity_id)
        finally:
            self._processing.discard(source_entity_id)

        current_by_uid: dict[str, dict] = {
            item["uid"]: item for item in current_items if item.get("uid")
        }
        old_snapshot = self._source_snapshots.get(source_entity_id, {})

        new_uids = set(current_by_uid) - set(old_snapshot)
        removed_uids = set(old_snapshot) - set(current_by_uid)
        changed_uids = {
            uid
            for uid in current_by_uid
            if uid in old_snapshot
            and current_by_uid[uid].get("status") != old_snapshot[uid].get("status")
        }

        delete_on_merge = source_config.get(CONF_DELETE_ON_MERGE, False)
        merged_and_deleted: set[str] = set()

        # New items → add to master
        for uid in new_uids:
            item = current_by_uid[uid]
            summary = item.get("summary", "")
            if not summary:
                continue

            existing_master_uid = self._find_master_uid_by_name(summary)
            if existing_master_uid and self.duplicate_handling == DUPLICATE_DEDUPLICATE:
                # Merge origins rather than creating duplicate
                self._add_origin(existing_master_uid, source_entity_id, uid)
            else:
                await self._async_add_to_master(summary, source_entity_id, uid)

            if delete_on_merge:
                self._processing.add(source_entity_id)
                try:
                    await self._async_service_remove_item(source_entity_id, [uid])
                finally:
                    self._processing.discard(source_entity_id)
                merged_and_deleted.add(uid)

        # Removed items → remove from master if no other origins remain
        for uid in removed_uids:
            master_uid = self._find_master_uid_by_origin(source_entity_id, uid)
            if not master_uid:
                continue
            remaining = [
                o
                for o in self._master_snapshot[master_uid].get("origins", [])
                if not (o["entity_id"] == source_entity_id and o["uid"] == uid)
            ]
            if remaining:
                self._master_snapshot[master_uid]["origins"] = remaining
            else:
                await self._async_remove_from_master(master_uid, propagate=False)

        # Status changes → completed handling
        for uid in changed_uids:
            item = current_by_uid[uid]
            new_status = item.get("status", "needs_action")
            if new_status != "completed":
                continue

            master_uid = self._find_master_uid_by_origin(source_entity_id, uid)
            if not master_uid:
                continue

            if self.completed_behavior == COMPLETED_SYNC_BACK:
                await self._async_update_master_status(master_uid, "completed", propagate=False)
            elif self.completed_behavior == COMPLETED_DELETE_BOTH:
                await self._async_remove_from_master(master_uid, propagate=False)
                self._processing.add(source_entity_id)
                try:
                    await self._async_service_remove_item(source_entity_id, [uid])
                finally:
                    self._processing.discard(source_entity_id)
                merged_and_deleted.add(uid)

        # Update source snapshot (exclude items we deleted)
        self._source_snapshots[source_entity_id] = {
            uid: {"summary": item.get("summary", ""), "status": item.get("status", "needs_action")}
            for uid, item in current_by_uid.items()
            if uid not in merged_and_deleted
        }
        await self._async_save()

    # ------------------------------------------------------------------
    # Core sync: existing master → two-way sources
    # ------------------------------------------------------------------

    async def _async_sync_existing_master_to_sources(self, master_entity_id: str) -> None:
        self._processing.add(master_entity_id)
        try:
            current_items = await self._async_get_todo_items(master_entity_id)
        finally:
            self._processing.discard(master_entity_id)

        current_by_uid: dict[str, dict] = {
            item["uid"]: item for item in current_items if item.get("uid")
        }
        tracked_uids = set(self._master_snapshot)

        for uid, item in current_by_uid.items():
            if uid in tracked_uids:
                continue
            summary = item.get("summary", "")
            if not summary:
                continue

            # New item added directly to the existing master – propagate to two-way sources
            self._master_snapshot[uid] = {
                "summary": summary,
                "status": item.get("status", "needs_action"),
                "origins": [],
            }
            for source in self.sources:
                if source.get(CONF_DIRECTION) != DIRECTION_TWO_WAY:
                    continue
                source_id = source[CONF_SOURCE_ENTITY_ID]
                if self.duplicate_handling == DUPLICATE_DEDUPLICATE:
                    snap = self._source_snapshots.get(source_id, {})
                    if any(v.get("summary", "").lower() == summary.lower() for v in snap.values()):
                        continue
                self._processing.add(source_id)
                try:
                    await self._async_service_add_item(source_id, summary)
                finally:
                    self._processing.discard(source_id)

        await self._async_save()

    # ------------------------------------------------------------------
    # Callbacks from the virtual master entity
    # ------------------------------------------------------------------

    def on_master_item_added(
        self,
        uid: str,
        summary: str,
        source_entity_id: str | None = None,
        source_uid: str | None = None,
    ) -> None:
        """Called when an item is added to the virtual master list."""
        origins: list[dict] = []
        if source_entity_id and source_uid:
            origins = [{"entity_id": source_entity_id, "uid": source_uid}]

        self._master_snapshot[uid] = {
            "summary": summary,
            "status": "needs_action",
            "origins": origins,
        }

        # Propagate user-added items to two-way sources
        if not source_entity_id:
            self.hass.async_create_task(
                self._async_propagate_new_master_item(uid, summary)
            )
        self.hass.async_create_task(self._async_save())

    async def _async_propagate_new_master_item(self, master_uid: str, summary: str) -> None:
        for source in self.sources:
            if source.get(CONF_DIRECTION) != DIRECTION_TWO_WAY:
                continue
            source_id = source[CONF_SOURCE_ENTITY_ID]
            if self.duplicate_handling == DUPLICATE_DEDUPLICATE:
                snap = self._source_snapshots.get(source_id, {})
                if any(v.get("summary", "").lower() == summary.lower() for v in snap.values()):
                    continue
            self._processing.add(source_id)
            try:
                await self._async_service_add_item(source_id, summary)
            finally:
                self._processing.discard(source_id)

    def on_master_item_removed(self, uid: str) -> None:
        """Called when an item is removed from the virtual master list."""
        item = self._master_snapshot.pop(uid, None)
        if item:
            self.hass.async_create_task(self._async_propagate_master_removal(item))
            self.hass.async_create_task(self._async_save())

    async def _async_propagate_master_removal(self, item: dict) -> None:
        for origin in item.get("origins", []):
            source_id = origin["entity_id"]
            source_uid = origin["uid"]
            if not source_uid:
                continue
            source_config = self._get_source_config(source_id)
            if not source_config:
                continue
            if source_config.get(CONF_DIRECTION) == DIRECTION_TWO_WAY:
                self._processing.add(source_id)
                try:
                    await self._async_service_remove_item(source_id, [source_uid])
                finally:
                    self._processing.discard(source_id)

    def on_master_item_status_changed(self, uid: str, new_status: str) -> None:
        """Called when an item's status changes on the virtual master list."""
        if uid in self._master_snapshot:
            self._master_snapshot[uid]["status"] = new_status
            self.hass.async_create_task(
                self._async_propagate_status_change(uid, new_status)
            )
            self.hass.async_create_task(self._async_save())

    async def _async_propagate_status_change(self, master_uid: str, new_status: str) -> None:
        if self.completed_behavior == COMPLETED_MASTER_ONLY:
            return

        item = self._master_snapshot.get(master_uid, {})
        for origin in item.get("origins", []):
            source_id = origin["entity_id"]
            source_uid = origin["uid"]
            if not source_uid:
                continue

            self._processing.add(source_id)
            try:
                if self.completed_behavior == COMPLETED_SYNC_BACK:
                    await self._async_service_update_item(source_id, source_uid, new_status)
                elif self.completed_behavior == COMPLETED_DELETE_BOTH:
                    await self._async_service_remove_item(source_id, [source_uid])
            finally:
                self._processing.discard(source_id)

    # ------------------------------------------------------------------
    # Master list helpers
    # ------------------------------------------------------------------

    async def _async_add_to_master(
        self, summary: str, source_entity_id: str, source_uid: str
    ) -> None:
        if self.master_type == MASTER_TYPE_NEW:
            if self._master_entity:
                await self._master_entity.async_create_todo_item_internal(
                    summary, source_entity_id, source_uid
                )
        else:
            master_id = self.config.get(CONF_MASTER_ENTITY_ID, "")
            self._processing.add(master_id)
            try:
                await self._async_service_add_item(master_id, summary)
            finally:
                self._processing.discard(master_id)
            # Track with a placeholder UID (we can't retrieve the real UID from the service)
            import uuid
            fake_uid = str(uuid.uuid4())
            self._master_snapshot[fake_uid] = {
                "summary": summary,
                "status": "needs_action",
                "origins": [{"entity_id": source_entity_id, "uid": source_uid}],
            }

    async def _async_remove_from_master(self, master_uid: str, propagate: bool = True) -> None:
        item = self._master_snapshot.pop(master_uid, None)
        if not item:
            return

        if self.master_type == MASTER_TYPE_NEW and self._master_entity:
            await self._master_entity.async_delete_todo_item_internal(master_uid)
        elif self.master_type != MASTER_TYPE_NEW:
            master_id = self.config.get(CONF_MASTER_ENTITY_ID, "")
            if master_id and master_uid:
                self._processing.add(master_id)
                try:
                    await self._async_service_remove_item(master_id, [master_uid])
                finally:
                    self._processing.discard(master_id)

        if propagate:
            await self._async_propagate_master_removal(item)

    async def _async_update_master_status(
        self, master_uid: str, status: str, propagate: bool = True
    ) -> None:
        if master_uid not in self._master_snapshot:
            return
        self._master_snapshot[master_uid]["status"] = status

        if self.master_type == MASTER_TYPE_NEW and self._master_entity:
            await self._master_entity.async_update_todo_item_internal(master_uid, status)
        elif self.master_type != MASTER_TYPE_NEW:
            master_id = self.config.get(CONF_MASTER_ENTITY_ID, "")
            if master_id:
                self._processing.add(master_id)
                try:
                    await self._async_service_update_item(master_id, master_uid, status)
                finally:
                    self._processing.discard(master_id)

        if propagate:
            await self._async_propagate_status_change(master_uid, status)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def _get_source_config(self, entity_id: str) -> dict | None:
        return next(
            (s for s in self.sources if s[CONF_SOURCE_ENTITY_ID] == entity_id), None
        )

    def _find_master_uid_by_origin(
        self, source_entity_id: str, source_uid: str
    ) -> str | None:
        for master_uid, item in self._master_snapshot.items():
            for origin in item.get("origins", []):
                if (
                    origin["entity_id"] == source_entity_id
                    and origin["uid"] == source_uid
                ):
                    return master_uid
        return None

    def _find_master_uid_by_name(self, summary: str) -> str | None:
        summary_lower = summary.lower().strip()
        for uid, item in self._master_snapshot.items():
            if item.get("summary", "").lower().strip() == summary_lower:
                return uid
        return None

    def _add_origin(
        self, master_uid: str, source_entity_id: str, source_uid: str
    ) -> None:
        if master_uid not in self._master_snapshot:
            return
        origins: list[dict] = self._master_snapshot[master_uid].setdefault("origins", [])
        if not any(
            o["entity_id"] == source_entity_id and o["uid"] == source_uid
            for o in origins
        ):
            origins.append({"entity_id": source_entity_id, "uid": source_uid})

    # ------------------------------------------------------------------
    # HA service wrappers
    # ------------------------------------------------------------------

    async def _async_get_todo_items(self, entity_id: str) -> list[dict]:
        try:
            result = await self.hass.services.async_call(
                "todo",
                "get_items",
                {"entity_id": entity_id, "status": ["needs_action", "completed"]},
                blocking=True,
                return_response=True,
            )
            if result and entity_id in result:
                return result[entity_id].get("items", [])
        except Exception as err:
            _LOGGER.error("Error fetching items from %s: %s", entity_id, err)
        return []

    async def _async_service_add_item(self, entity_id: str, summary: str) -> None:
        try:
            await self.hass.services.async_call(
                "todo",
                "add_item",
                {"entity_id": entity_id, "item": summary},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Error adding '%s' to %s: %s", summary, entity_id, err)

    async def _async_service_remove_item(
        self, entity_id: str, uids: list[str]
    ) -> None:
        try:
            await self.hass.services.async_call(
                "todo",
                "remove_item",
                {"entity_id": entity_id, "item": uids},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error("Error removing items %s from %s: %s", uids, entity_id, err)

    async def _async_service_update_item(
        self, entity_id: str, uid: str, status: str
    ) -> None:
        try:
            await self.hass.services.async_call(
                "todo",
                "update_item",
                {"entity_id": entity_id, "item": uid, "status": status},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.error(
                "Error updating item %s on %s: %s", uid, entity_id, err
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "source_snapshots": self._source_snapshots,
                "master_snapshot": self._master_snapshot,
            }
        )
