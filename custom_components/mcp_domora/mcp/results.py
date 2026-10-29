"""Tool result wrappers for content that is not plain JSON."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ImageResult:
    """An image returned to the client, e.g. a camera snapshot."""

    data: bytes
    mime_type: str = "image/jpeg"
    text: str | None = None

    def as_content(self) -> list[dict[str, Any]]:
        """MCP content blocks."""
        blocks: list[dict[str, Any]] = []
        if self.text:
            blocks.append({"type": "text", "text": self.text})
        blocks.append(
            {
                "type": "image",
                "data": base64.b64encode(self.data).decode(),
                "mimeType": self.mime_type,
            }
        )
        return blocks


@dataclass(slots=True)
class TextResult:
    """Plain text returned verbatim, without JSON encoding."""

    text: str
    structured: dict[str, Any] | None = None

    def as_content(self) -> list[dict[str, Any]]:
        """MCP content blocks."""
        return [{"type": "text", "text": self.text}]


@dataclass(slots=True)
class MultiResult:
    """Several content blocks at once."""

    blocks: list[dict[str, Any]] = field(default_factory=list)

    def as_content(self) -> list[dict[str, Any]]:
        """MCP content blocks."""
        return self.blocks
