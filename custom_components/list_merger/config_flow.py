"""Config flow for List Merger."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.todo import DOMAIN as TODO_DOMAIN
from homeassistant.helpers import selector

from .const import (
    COMPLETED_DELETE_BOTH,
    COMPLETED_MASTER_ONLY,
    COMPLETED_SYNC_BACK,
    CONF_COMPLETED_BEHAVIOR,
    CONF_DELETE_ON_MERGE,
    CONF_DIRECTION,
    CONF_DUPLICATE_HANDLING,
    CONF_MASTER_ENTITY_ID,
    CONF_MASTER_NAME,
    CONF_MASTER_TYPE,
    CONF_SOURCE_ENTITY_ID,
    CONF_SOURCES,
    DIRECTION_ONE_WAY,
    DIRECTION_TWO_WAY,
    DOMAIN,
    DUPLICATE_DEDUPLICATE,
    DUPLICATE_KEEP_ALL,
    MASTER_TYPE_EXISTING,
    MASTER_TYPE_NEW,
)

_DIRECTION_OPTIONS = [
    selector.SelectOptionDict(value=DIRECTION_ONE_WAY, label="One-way (source → master)"),
    selector.SelectOptionDict(value=DIRECTION_TWO_WAY, label="Two-way (source ↔ master)"),
]

_DUPLICATE_OPTIONS = [
    selector.SelectOptionDict(value=DUPLICATE_DEDUPLICATE, label="Deduplicate (recommended)"),
    selector.SelectOptionDict(value=DUPLICATE_KEEP_ALL, label="Keep duplicates"),
]

_COMPLETED_OPTIONS = [
    selector.SelectOptionDict(value=COMPLETED_SYNC_BACK, label="Sync completion back to source"),
    selector.SelectOptionDict(value=COMPLETED_MASTER_ONLY, label="Mark complete on master only"),
    selector.SelectOptionDict(value=COMPLETED_DELETE_BOTH, label="Delete from both when completed"),
]

_MASTER_TYPE_OPTIONS = [
    selector.SelectOptionDict(value=MASTER_TYPE_NEW, label="Create a new virtual list"),
    selector.SelectOptionDict(value=MASTER_TYPE_EXISTING, label="Use an existing list as master"),
]


class ListMergerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for List Merger."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._pending_sources: list[str] = []
        self._configured_sources: list[dict] = []
        self._current_source: str = ""

    # ------------------------------------------------------------------
    # Step 1 – basic settings
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data.update(user_input)
            if user_input[CONF_MASTER_TYPE] == MASTER_TYPE_EXISTING:
                return await self.async_step_existing_master()
            return await self.async_step_select_sources()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MASTER_NAME, default="Merged List"): str,
                    vol.Required(
                        CONF_MASTER_TYPE, default=MASTER_TYPE_NEW
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_MASTER_TYPE_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_DUPLICATE_HANDLING, default=DUPLICATE_DEDUPLICATE
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_DUPLICATE_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_COMPLETED_BEHAVIOR, default=COMPLETED_SYNC_BACK
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_COMPLETED_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    # ------------------------------------------------------------------
    # Step 2a – pick existing master entity
    # ------------------------------------------------------------------

    async def async_step_existing_master(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._data[CONF_MASTER_ENTITY_ID] = user_input[CONF_MASTER_ENTITY_ID]
            return await self.async_step_select_sources()

        return self.async_show_form(
            step_id="existing_master",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MASTER_ENTITY_ID): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=TODO_DOMAIN)
                    ),
                }
            ),
        )

    # ------------------------------------------------------------------
    # Step 2b – select source entities
    # ------------------------------------------------------------------

    async def async_step_select_sources(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            selected: list[str] = user_input.get("source_entities", [])
            master_id = self._data.get(CONF_MASTER_ENTITY_ID, "")
            # Filter out master if user accidentally included it
            sources = [s for s in selected if s != master_id]
            if not sources:
                errors["base"] = "no_sources"
            else:
                self._pending_sources = sources
                self._configured_sources = []
                self._current_source = self._pending_sources.pop(0)
                return await self.async_step_configure_source()

        return self.async_show_form(
            step_id="select_sources",
            data_schema=vol.Schema(
                {
                    vol.Required("source_entities"): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=TODO_DOMAIN,
                            multiple=True,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 3+ – configure each source one by one
    # ------------------------------------------------------------------

    async def async_step_configure_source(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._configured_sources.append(
                {
                    CONF_SOURCE_ENTITY_ID: self._current_source,
                    CONF_DIRECTION: user_input[CONF_DIRECTION],
                    CONF_DELETE_ON_MERGE: user_input[CONF_DELETE_ON_MERGE],
                }
            )
            if self._pending_sources:
                self._current_source = self._pending_sources.pop(0)
                return await self.async_step_configure_source()

            self._data[CONF_SOURCES] = self._configured_sources
            title = self._data.get(CONF_MASTER_NAME, "Merged List")
            return self.async_create_entry(title=title, data=self._data)

        return self.async_show_form(
            step_id="configure_source",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DIRECTION, default=DIRECTION_ONE_WAY
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_DIRECTION_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_DELETE_ON_MERGE, default=False
                    ): selector.BooleanSelector(),
                }
            ),
            description_placeholders={"entity_id": self._current_source},
        )

    # ------------------------------------------------------------------
    # Options flow
    # ------------------------------------------------------------------

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ListMergerOptionsFlow:
        return ListMergerOptionsFlow(config_entry)


class ListMergerOptionsFlow(config_entries.OptionsFlow):
    """Allow reconfiguring sources and global settings after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._data = dict(config_entry.data)
        self._pending_sources: list[str] = []
        self._configured_sources: list[dict] = []
        self._current_source: str = ""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            selected: list[str] = user_input.get("source_entities", [])
            master_id = self._data.get(CONF_MASTER_ENTITY_ID, "")
            sources = [s for s in selected if s != master_id]
            if not sources:
                errors["base"] = "no_sources"
            else:
                self._data[CONF_DUPLICATE_HANDLING] = user_input[CONF_DUPLICATE_HANDLING]
                self._data[CONF_COMPLETED_BEHAVIOR] = user_input[CONF_COMPLETED_BEHAVIOR]
                self._pending_sources = sources
                self._configured_sources = []
                self._current_source = self._pending_sources.pop(0)
                return await self.async_step_configure_source()

        current_sources = self._data.get(CONF_SOURCES, [])
        current_ids = [s[CONF_SOURCE_ENTITY_ID] for s in current_sources]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "source_entities", default=current_ids
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=TODO_DOMAIN,
                            multiple=True,
                        )
                    ),
                    vol.Required(
                        CONF_DUPLICATE_HANDLING,
                        default=self._data.get(
                            CONF_DUPLICATE_HANDLING, DUPLICATE_DEDUPLICATE
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_DUPLICATE_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_COMPLETED_BEHAVIOR,
                        default=self._data.get(
                            CONF_COMPLETED_BEHAVIOR, COMPLETED_SYNC_BACK
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_COMPLETED_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_configure_source(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._configured_sources.append(
                {
                    CONF_SOURCE_ENTITY_ID: self._current_source,
                    CONF_DIRECTION: user_input[CONF_DIRECTION],
                    CONF_DELETE_ON_MERGE: user_input[CONF_DELETE_ON_MERGE],
                }
            )
            if self._pending_sources:
                self._current_source = self._pending_sources.pop(0)
                return await self.async_step_configure_source()

            new_data = {**self._data, CONF_SOURCES: self._configured_sources}
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})

        # Pre-fill with existing settings for this source if available
        existing = next(
            (
                s
                for s in self._data.get(CONF_SOURCES, [])
                if s[CONF_SOURCE_ENTITY_ID] == self._current_source
            ),
            {},
        )

        return self.async_show_form(
            step_id="configure_source",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DIRECTION,
                        default=existing.get(CONF_DIRECTION, DIRECTION_ONE_WAY),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_DIRECTION_OPTIONS,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(
                        CONF_DELETE_ON_MERGE,
                        default=existing.get(CONF_DELETE_ON_MERGE, False),
                    ): selector.BooleanSelector(),
                }
            ),
            description_placeholders={"entity_id": self._current_source},
        )
