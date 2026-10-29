"""Development workspaces and Supervisor actions for Home Assistant apps."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from .. import addon_projects
from ..const import GROUP_SUPERVISOR
from ..context import ToolContext
from ..errors import InvalidInput, MCPBridgeError
from ..registry import require, tool
from ..schema import boolean, obj, schema, string


async def _project_call(context: ToolContext, func: Any, *args: Any) -> Any:
    context.check_admin()
    try:
        return await context.hass.async_add_executor_job(
            func, context.hass.config.config_dir, *args
        )
    except (addon_projects.ProjectError, OSError) as err:
        raise InvalidInput(str(err)) from err


@tool(
    name="create_addon_project",
    group=GROUP_SUPERVISOR,
    title="Create app project",
    description="Create an editable Home Assistant app repository workspace with repository.yaml, config.yaml, Dockerfile and run.sh. The workspace is under /config, not Supervisor's local_apps folder; publish it to a reachable Git repository or copy the app folder to local_apps before installing.",
    input_schema=schema(
        {
            "slug": string("Lowercase project and app slug."),
            "name": string("Display name."),
            "description": string("Short app description."),
        },
        ["slug", "name", "description"],
    ),
    write=True,
    admin=True,
)
async def create_addon_project(
    context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    slug, name, description = require(args, "slug", "name", "description")
    return await _project_call(
        context, addon_projects.create_project, slug, name, description
    )


@tool(
    name="list_addon_projects",
    group=GROUP_SUPERVISOR,
    description="List MCP Domora app development workspaces under the Home Assistant configuration directory.",
    input_schema=schema({}),
    admin=True,
)
async def list_addon_projects(
    context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    return await _project_call(context, addon_projects.list_projects)


@tool(
    name="list_addon_project_files",
    group=GROUP_SUPERVISOR,
    description="List source files in an MCP Domora app project workspace.",
    input_schema=schema({"slug": string("Project slug.")}, ["slug"]),
    admin=True,
)
async def list_addon_project_files(
    context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    (slug,) = require(args, "slug")
    return await _project_call(context, addon_projects.list_files, slug)


@tool(
    name="read_addon_project_file",
    group=GROUP_SUPERVISOR,
    description="Read one UTF-8 source file from an MCP Domora app project workspace.",
    input_schema=schema(
        {
            "slug": string("Project slug."),
            "path": string("Project-relative file path."),
        },
        ["slug", "path"],
    ),
    admin=True,
)
async def read_addon_project_file(
    context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    slug, path = require(args, "slug", "path")
    return await _project_call(context, addon_projects.read_file, slug, path)


@tool(
    name="write_addon_project_files",
    group=GROUP_SUPERVISOR,
    description="Create or update UTF-8 source files in an MCP Domora app project. Paths are relative to the project root; set overwrite=true to replace existing files. This edits the workspace only and does not deploy it.",
    input_schema=schema(
        {
            "slug": string("Project slug."),
            "files": obj("Map of project-relative paths to complete text contents."),
            "overwrite": boolean("Replace existing files. Default false."),
        },
        ["slug", "files"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def write_addon_project_files(
    context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    slug, files = require(args, "slug", "files")
    return await _project_call(
        context,
        addon_projects.write_files,
        slug,
        files,
        bool(args.get("overwrite", False)),
    )


@tool(
    name="delete_addon_project_file",
    group=GROUP_SUPERVISOR,
    description="Delete one source file from an MCP Domora app project workspace. Read it first if its contents may be needed.",
    input_schema=schema(
        {
            "slug": string("Project slug."),
            "path": string("Project-relative file path."),
        },
        ["slug", "path"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def delete_addon_project_file(
    context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    slug, path = require(args, "slug", "path")
    return await _project_call(context, addon_projects.delete_file, slug, path)


async def _supervisor(
    context: ToolContext,
    endpoint: str,
    method: str = "get",
    data: dict[str, Any] | None = None,
    *,
    timeout: int = 60,
) -> Any:
    context.check_admin()
    if "hassio" not in context.hass.config.components:
        raise MCPBridgeError(
            "Supervisor is unavailable. App installation requires Home Assistant OS or a supervised installation."
        )
    payload: dict[str, Any] = {
        "endpoint": endpoint,
        "method": method,
        "timeout": timeout,
    }
    if data is not None:
        payload["data"] = data
    return await context.ws.call("supervisor/api", payload, timeout=timeout + 10)


@tool(
    name="list_addon_store",
    group=GROUP_SUPERVISOR,
    description="List apps available in the Supervisor store, including local and remote repositories. Use the returned slug for installation.",
    input_schema=schema({}),
    admin=True,
)
async def list_addon_store(context: ToolContext, args: dict[str, Any]) -> Any:
    return await _supervisor(context, "/store/addons")


@tool(
    name="get_addon_info",
    group=GROUP_SUPERVISOR,
    description="Get Supervisor details and runtime state for one installed app or store app.",
    input_schema=schema({"slug": string("App slug from list_addon_store.")}, ["slug"]),
    admin=True,
)
async def get_addon_info(context: ToolContext, args: dict[str, Any]) -> Any:
    (slug,) = require(args, "slug")
    try:
        slug = _addon_slug(slug)
    except addon_projects.ProjectError as err:
        raise InvalidInput(str(err)) from err
    return await _supervisor(context, f"/addons/{slug}/info")


@tool(
    name="add_addon_repository",
    group=GROUP_SUPERVISOR,
    description="Add a Git repository that Supervisor can reach to the app store. First publish the project separately; a workspace under /config is not automatically available to Supervisor.",
    input_schema=schema(
        {
            "repository": string(
                "HTTPS Git repository URL, optionally followed by #branch."
            )
        },
        ["repository"],
    ),
    write=True,
    admin=True,
    destructive=True,
)
async def add_addon_repository(
    context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    (repository,) = require(args, "repository")
    if not isinstance(repository, str):
        raise InvalidInput("Repository must be an HTTPS URL.")
    parsed = urlsplit(repository)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
    ):
        raise InvalidInput(
            "Use an HTTPS repository URL without embedded credentials or query parameters."
        )
    result = await _supervisor(
        context, "/store/repositories", "post", {"repository": repository}
    )
    return {
        "added": True,
        "result": result,
        "next": "Call reload_addon_store, then list_addon_store.",
    }


@tool(
    name="reload_addon_store",
    group=GROUP_SUPERVISOR,
    description="Reload Supervisor's app repositories and local_apps directory after source changes.",
    input_schema=schema({}),
    write=True,
    admin=True,
    idempotent=True,
)
async def reload_addon_store(
    context: ToolContext, args: dict[str, Any]
) -> dict[str, Any]:
    result = await _supervisor(context, "/store/reload", "post")
    return {"reloaded": True, "result": result}


def _addon_slug(value: Any) -> str:
    # Supervisor app slugs are repository-prefixed, for example local_hello_world.
    return addon_projects.validate_slug(value)


@tool(
    name="install_addon",
    group=GROUP_SUPERVISOR,
    description="Install or build an app from the Supervisor store in the background. Pass a slug from list_addon_store and check get_addon_job until it completes before starting the app.",
    input_schema=schema({"slug": string("Supervisor store app slug.")}, ["slug"]),
    write=True,
    admin=True,
    destructive=True,
)
async def install_addon(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    (slug,) = require(args, "slug")
    try:
        slug = _addon_slug(slug)
    except addon_projects.ProjectError as err:
        raise InvalidInput(str(err)) from err
    result = await _supervisor(
        context, f"/store/addons/{slug}/install", "post", {"background": True}
    )
    if isinstance(result, dict) and result.get("job_id"):
        return {
            "requested": True,
            "result": result,
            "next": "Use get_addon_job with the returned job_id; installation is not complete until the job succeeds.",
        }
    return {
        "completed": True,
        "result": result,
        "next": "Check the installed app and start it when ready.",
    }


@tool(
    name="get_addon_job",
    group=GROUP_SUPERVISOR,
    description="Read Supervisor job details for a background app installation.",
    input_schema=schema(
        {"job_id": string("Job ID returned by install_addon.")}, ["job_id"]
    ),
    admin=True,
)
async def get_addon_job(context: ToolContext, args: dict[str, Any]) -> Any:
    (job_id,) = require(args, "job_id")
    try:
        job_id = UUID(str(job_id)).hex
    except (ValueError, AttributeError) as err:
        raise InvalidInput("Invalid Supervisor job ID.") from err
    return await _supervisor(context, f"/jobs/{job_id}")


@tool(
    name="rebuild_addon",
    group=GROUP_SUPERVISOR,
    description="Rebuild and restart a locally built app after its source has been updated in Supervisor's actual local_apps directory or repository. This waits for completion and can take many minutes; configure a suitable MCP client tool timeout.",
    input_schema=schema({"slug": string("Installed app slug.")}, ["slug"]),
    write=True,
    admin=True,
    destructive=True,
)
async def rebuild_addon(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    (slug,) = require(args, "slug")
    try:
        slug = _addon_slug(slug)
    except addon_projects.ProjectError as err:
        raise InvalidInput(str(err)) from err
    result = await _supervisor(
        context, f"/addons/{slug}/rebuild", "post", {}, timeout=1800
    )
    return {"completed": True, "result": result}


@tool(
    name="get_addon_logs",
    group=GROUP_SUPERVISOR,
    description="Read the latest logs of an installed app, including runtime errors.",
    input_schema=schema({"slug": string("Installed app slug.")}, ["slug"]),
    admin=True,
)
async def get_addon_logs(context: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    context.check_admin()
    if "hassio" not in context.hass.config.components:
        raise MCPBridgeError("Supervisor is unavailable on this installation.")
    (slug,) = require(args, "slug")
    try:
        slug = _addon_slug(slug)
    except addon_projects.ProjectError as err:
        raise InvalidInput(str(err)) from err
    from homeassistant.components.hassio.const import DATA_COMPONENT  # noqa: PLC0415

    logs = await context.hass.data[DATA_COMPONENT].send_command(
        f"/addons/{slug}/logs", method="get", return_text=True, timeout=30
    )
    return {"slug": slug, "logs": logs[-50000:], "truncated": len(logs) > 50000}
