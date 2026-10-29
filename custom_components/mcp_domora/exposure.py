"""Entity exposure filtering.

Which entities an MCP client may see and touch is configured per domain, per
entity, per area and per label in the integration options.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from .const import (
    CONF_ALLOWED_DOMAINS,
    CONF_EXCLUDE_ENTITIES,
    CONF_EXCLUDED_DOMAINS,
    CONF_EXPOSE_HIDDEN,
    CONF_INCLUDE_AREAS,
    CONF_INCLUDE_ENTITIES,
    CONF_INCLUDE_LABELS,
    DEFAULT_EXCLUDED_DOMAINS,
)


@dataclass(slots=True)
class Exposure:
    """Decides whether an entity is visible to MCP clients."""

    hass: HomeAssistant
    allowed_domains: frozenset[str]
    excluded_domains: frozenset[str]
    include_entities: frozenset[str]
    exclude_entities: frozenset[str]
    include_areas: frozenset[str]
    include_labels: frozenset[str]
    expose_hidden: bool

    @classmethod
    def from_options(cls, hass: HomeAssistant, options: dict[str, Any]) -> Exposure:
        """Build from a config entry's options."""
        return cls(
            hass=hass,
            allowed_domains=frozenset(options.get(CONF_ALLOWED_DOMAINS) or ()),
            excluded_domains=frozenset(
                options.get(CONF_EXCLUDED_DOMAINS, DEFAULT_EXCLUDED_DOMAINS) or ()
            ),
            include_entities=frozenset(options.get(CONF_INCLUDE_ENTITIES) or ()),
            exclude_entities=frozenset(options.get(CONF_EXCLUDE_ENTITIES) or ()),
            include_areas=frozenset(options.get(CONF_INCLUDE_AREAS) or ()),
            include_labels=frozenset(options.get(CONF_INCLUDE_LABELS) or ()),
            expose_hidden=bool(options.get(CONF_EXPOSE_HIDDEN, False)),
        )

    def is_exposed(self, entity_id: str) -> bool:
        """Whether `entity_id` may be read or controlled."""
        # An explicit include always wins, so a single entity can be allowed
        # through an otherwise restrictive filter.
        if entity_id in self.include_entities:
            return True
        if entity_id in self.exclude_entities:
            return False

        domain = split_entity_id(entity_id)[0]
        if self.allowed_domains and domain not in self.allowed_domains:
            return False
        if domain in self.excluded_domains:
            return False

        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is not None:
            if not self.expose_hidden and (entry.hidden_by or entry.disabled_by):
                return False
            if self.include_labels and not (set(entry.labels) & self.include_labels):
                return False
            if self.include_areas and self._area_for(entry) not in self.include_areas:
                return False
        elif self.include_labels or self.include_areas:
            # Entities outside the registry (YAML templates, groups, ...) carry
            # no labels or area, so area/label filters exclude them.
            return False

        return True

    def _area_for(self, entry: er.RegistryEntry) -> str | None:
        """Resolve an entity's effective area, falling back to its device."""
        if entry.area_id:
            return entry.area_id
        if entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            if device is not None:
                return device.area_id
        return None

    def area_for_entity_id(self, entity_id: str) -> str | None:
        """The effective area of an entity, via its own setting or its device."""
        entry = er.async_get(self.hass).async_get(entity_id)
        return self._area_for(entry) if entry else None

    def filter_entity_ids(self, entity_ids: list[str]) -> list[str]:
        """Keep only the exposed entity ids."""
        return [eid for eid in entity_ids if self.is_exposed(eid)]

    def exposed_entity_ids(self) -> list[str]:
        """Every exposed entity id currently known to Home Assistant."""
        return [
            state.entity_id
            for state in self.hass.states.async_all()
            if self.is_exposed(state.entity_id)
        ]

    def blocked(self, entity_ids: list[str]) -> list[str]:
        """The subset of `entity_ids` that is not exposed."""
        return [eid for eid in entity_ids if not self.is_exposed(eid)]

    def area_name(self, area_id: str | None) -> str | None:
        """Human readable area name."""
        if not area_id:
            return None
        area = ar.async_get(self.hass).async_get_area(area_id)
        return area.name if area else None
