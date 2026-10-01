"""Camera and media tools."""

from __future__ import annotations

from typing import Any

from ..const import GROUP_MEDIA
from ..context import ToolContext
from ..errors import InvalidInput, MCPBridgeError
from ..mcp.results import ImageResult
from ..registry import require, tool
from ..schema import integer, schema, string


@tool(
    name="get_camera_snapshot",
    group=GROUP_MEDIA,
    title="Get a camera snapshot",
    description="""
Fetch a still image from a camera and return it as an image you can look at. Use it
to answer questions about what is actually happening - whether the garage door is
open, whether anyone is at the door - rather than inferring it from sensors.

Treat the result as potentially sensitive: it is a live picture of someone's home.
""",
    input_schema=schema(
        {
            "entity_id": string("The camera entity, e.g. `camera.front_door`."),
            "width": integer("Scale the image to this width in pixels."),
            "height": integer("Scale the image to this height in pixels."),
        },
        ["entity_id"],
    ),
    open_world=True,
)
async def get_camera_snapshot(context: ToolContext, args: dict[str, Any]) -> ImageResult:
    """Fetch a camera image."""
    (entity_id,) = require(args, "entity_id")
    context.check_read(entity_id)
    if not str(entity_id).startswith("camera."):
        raise InvalidInput(f"{entity_id} is not a camera entity")

    try:
        from homeassistant.components.camera import async_get_image  # noqa: PLC0415
    except ImportError as err:  # pragma: no cover
        raise MCPBridgeError("The camera integration is not available") from err

    kwargs: dict[str, Any] = {}
    if args.get("width"):
        kwargs["width"] = int(args["width"])
    if args.get("height"):
        kwargs["height"] = int(args["height"])

    try:
        image = await async_get_image(context.hass, str(entity_id), **kwargs)
    except Exception as err:  # noqa: BLE001 - HomeAssistantError and camera errors
        raise MCPBridgeError(f"Could not get an image from {entity_id}: {err}") from err

    return ImageResult(
        data=image.content,
        mime_type=image.content_type or "image/jpeg",
        text=f"Snapshot from {entity_id}",
    )


@tool(
    name="browse_media",
    group=GROUP_MEDIA,
    title="Browse media",
    description="""
Browse what a media player can play, or the media sources Home Assistant knows about
(local media, TTS, radio). Walk down the tree by passing a child's
`media_content_id` and `media_content_type` back in, then play it with
`call_service` on `media_player.play_media`.
""",
    input_schema=schema(
        {
            "entity_id": string("The media player to browse. Omit to browse media sources."),
            "media_content_id": string("Where to browse. Omit for the top level."),
            "media_content_type": string("The content type of media_content_id."),
        }
    ),
)
async def browse_media(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Browse media."""
    if entity_id := args.get("entity_id"):
        context.check_read(entity_id)
        payload: dict[str, Any] = {"entity_id": entity_id}
        if args.get("media_content_id"):
            payload["media_content_id"] = args["media_content_id"]
            payload["media_content_type"] = args.get("media_content_type", "")
        return await context.ws.call("media_player/browse_media", payload)

    payload = {}
    if args.get("media_content_id"):
        payload["media_content_id"] = args["media_content_id"]
    return await context.ws.call("media_source/browse_media", payload)
