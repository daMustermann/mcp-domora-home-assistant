"""Small helpers for building JSON Schema fragments for tool inputs."""

from __future__ import annotations

from typing import Any


def string(description: str, **kwargs: Any) -> dict[str, Any]:
    """A string property."""
    return {"type": "string", "description": description, **kwargs}


def integer(description: str, **kwargs: Any) -> dict[str, Any]:
    """An integer property."""
    return {"type": "integer", "description": description, **kwargs}


def number(description: str, **kwargs: Any) -> dict[str, Any]:
    """A number property."""
    return {"type": "number", "description": description, **kwargs}


def boolean(description: str, **kwargs: Any) -> dict[str, Any]:
    """A boolean property."""
    return {"type": "boolean", "description": description, **kwargs}


def enum(description: str, values: list[str], **kwargs: Any) -> dict[str, Any]:
    """A string property restricted to a set of values."""
    return {"type": "string", "description": description, "enum": values, **kwargs}


def array(description: str, items: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """An array property."""
    return {
        "type": "array",
        "description": description,
        "items": items or {"type": "string"},
        **kwargs,
    }


def obj(description: str, properties: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    """A free-form or structured object property."""
    payload: dict[str, Any] = {"type": "object", "description": description}
    if properties is not None:
        payload["properties"] = properties
    payload.update(kwargs)
    return payload


def anything(description: str) -> dict[str, Any]:
    """A property of any JSON type."""
    return {"description": description}


def entity_id(description: str = "A Home Assistant entity id, e.g. `light.kitchen`.") -> dict[str, Any]:
    """An entity id property."""
    return string(description, pattern=r"^[a-z_0-9]+\.[a-z_0-9]+$")


def schema(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    *,
    additional: bool = False,
) -> dict[str, Any]:
    """Build a top-level input schema object."""
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": additional,
    }
