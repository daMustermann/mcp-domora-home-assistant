"""Read and write the YAML files behind UI-editable automations, scripts and scenes.

Home Assistant stores these in `automations.yaml`, `scripts.yaml` and
`scenes.yaml` and edits them through REST endpoints that only the frontend uses.
This mirrors that file handling - same paths, same atomic write, same validators -
so configuration written here is indistinguishable from configuration written in
the UI, and stays editable there.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Literal

from homeassistant.core import HomeAssistant
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.yaml import dump as yaml_dump, load_yaml

from .errors import InvalidInput, MCPBridgeError

_LOGGER = logging.getLogger(__name__)

#: One lock per file, so concurrent tool calls cannot interleave read/write cycles.
_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(path: str) -> asyncio.Lock:
    """The mutation lock for a config file."""
    return _LOCKS.setdefault(path, asyncio.Lock())


def new_config_id() -> str:
    """Generate an id the way the Home Assistant frontend does."""
    return str(int(time.time() * 1000))


class YamlConfigStore:
    """A UI-editable YAML config file."""

    def __init__(
        self,
        hass: HomeAssistant,
        filename: str,
        shape: Literal["list", "dict"],
        *,
        label: str,
    ) -> None:
        """Initialise."""
        self.hass = hass
        self.filename = filename
        self.shape = shape
        self.label = label

    @property
    def path(self) -> str:
        """Absolute path of the config file."""
        return self.hass.config.path(self.filename)

    # Raw file access ---------------------------------------------------------
    def _read_sync(self) -> Any:
        """Read the file, returning an empty container when it does not exist."""
        if not os.path.isfile(self.path):
            return [] if self.shape == "list" else {}
        data = load_yaml(self.path)
        if data is None:
            return [] if self.shape == "list" else {}
        expected = list if self.shape == "list" else dict
        if not isinstance(data, expected):
            raise MCPBridgeError(
                f"{self.filename} does not contain a YAML {expected.__name__}; refusing to touch it."
            )
        return data

    def _write_sync(self, data: Any) -> None:
        """Write the file atomically."""
        write_utf8_file_atomic(self.path, yaml_dump(data))

    async def async_read(self) -> Any:
        """Read the whole file."""
        return await self.hass.async_add_executor_job(self._read_sync)

    # Item access ------------------------------------------------------------
    async def async_items(self) -> list[tuple[str, dict[str, Any]]]:
        """Every (key, config) pair in the file."""
        data = await self.async_read()
        if self.shape == "dict":
            return [(str(key), value) for key, value in data.items() if isinstance(value, dict)]
        items: list[tuple[str, dict[str, Any]]] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            items.append((str(item.get("id", f"#{index}")), item))
        return items

    async def async_get(self, key: str) -> dict[str, Any] | None:
        """One config item, or None."""
        for item_key, config in await self.async_items():
            if item_key == key:
                return config
        return None

    async def async_save(
        self, key: str, config: dict[str, Any], *, merge: bool = False
    ) -> dict[str, Any]:
        """Create or replace a config item and return what was written."""
        async with _lock_for(self.path):
            data = await self.async_read()
            if self.shape == "dict":
                existing = data.get(key) if isinstance(data.get(key), dict) else None
                new_value = {**existing, **config} if (merge and existing) else config
                data[key] = new_value
            else:
                new_value = {**config, "id": key}
                for index, item in enumerate(data):
                    if isinstance(item, dict) and str(item.get("id")) == key:
                        if merge:
                            new_value = {**item, **config, "id": key}
                        data[index] = new_value
                        break
                else:
                    data.append(new_value)
            await self.hass.async_add_executor_job(self._write_sync, data)
        _LOGGER.debug("Wrote %s %s", self.label, key)
        return new_value

    async def async_delete(self, key: str) -> bool:
        """Remove a config item."""
        async with _lock_for(self.path):
            data = await self.async_read()
            if self.shape == "dict":
                if key not in data:
                    return False
                del data[key]
            else:
                before = len(data)
                data[:] = [
                    item
                    for item in data
                    if not (isinstance(item, dict) and str(item.get("id")) == key)
                ]
                if len(data) == before:
                    return False
            await self.hass.async_add_executor_job(self._write_sync, data)
        _LOGGER.debug("Deleted %s %s", self.label, key)
        return True


def automation_store(hass: HomeAssistant) -> YamlConfigStore:
    """The automations.yaml store."""
    from homeassistant.config import AUTOMATION_CONFIG_PATH  # noqa: PLC0415

    return YamlConfigStore(hass, AUTOMATION_CONFIG_PATH, "list", label="automation")


def script_store(hass: HomeAssistant) -> YamlConfigStore:
    """The scripts.yaml store."""
    from homeassistant.config import SCRIPT_CONFIG_PATH  # noqa: PLC0415

    return YamlConfigStore(hass, SCRIPT_CONFIG_PATH, "dict", label="script")


def scene_store(hass: HomeAssistant) -> YamlConfigStore:
    """The scenes.yaml store."""
    from homeassistant.config import SCENE_CONFIG_PATH  # noqa: PLC0415

    return YamlConfigStore(hass, SCENE_CONFIG_PATH, "list", label="scene")


async def async_validate(
    hass: HomeAssistant,
    kind: Literal["automation", "script"],
    key: str,
    config: dict[str, Any],
) -> None:
    """Validate a config item with Home Assistant's own validator.

    Raises :class:`InvalidInput` with the validator's message, which is the same
    message the UI editor would show.
    """
    try:
        if kind == "automation":
            from homeassistant.components.automation.config import (  # noqa: PLC0415
                async_validate_config_item,
            )
        else:
            from homeassistant.components.script.config import (  # noqa: PLC0415
                async_validate_config_item,
            )
    except ImportError as err:  # pragma: no cover - component always present
        raise MCPBridgeError(f"Cannot validate {kind} config: {err}") from err

    try:
        await async_validate_config_item(hass, key, config)
    except InvalidInput:
        raise
    except Exception as err:  # noqa: BLE001 - voluptuous and HA errors both land here
        raise InvalidInput(f"Invalid {kind} config: {err}") from err
