"""Filesystem operations for add-on development projects.

Projects are stored under the Home Assistant configuration directory, not the
Supervisor's local-apps directory, which is not normally mounted into Core.
"""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any

MAX_FILE_BYTES = 1024 * 1024
MAX_PROJECT_FILES = 200
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class ProjectError(ValueError):
    """An invalid or unsafe project operation."""


def validate_slug(value: Any) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise ProjectError(
            "Project slug must contain only lowercase letters, numbers, underscores or hyphens (max 63 characters)."
        )
    return value


def _root(config_dir: str) -> Path:
    root = Path(config_dir) / "mcp_domora_projects"
    if root.is_symlink():
        raise ProjectError("Project root must not be a symbolic link.")
    return root


def _project(config_dir: str, slug: str, *, must_exist: bool = True) -> Path:
    root = _root(config_dir)
    path = root / validate_slug(slug)
    if path.is_symlink():
        raise ProjectError("Project directory must not be a symbolic link.")
    if must_exist and not path.is_dir():
        raise ProjectError(f"Project {slug!r} does not exist.")
    return path


def _file(project: Path, relative: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise ProjectError("Provide a valid relative POSIX file path.")
    parts = relative.split("/")
    if (
        any(part in ("", ".", "..", ".git") for part in parts)
        or PurePosixPath(relative).is_absolute()
    ):
        raise ProjectError("Absolute paths, traversal and .git paths are not allowed.")
    path = project
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ProjectError("Symbolic links are not allowed in project paths.")
    return path


def create_project(
    config_dir: str, slug: str, name: str, description: str
) -> dict[str, Any]:
    project = _project(config_dir, slug, must_exist=False)
    if project.exists():
        raise ProjectError(f"Project {slug!r} already exists.")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ProjectError("Name must contain 1–120 characters.")
    if (
        not isinstance(description, str)
        or not description.strip()
        or len(description) > 250
    ):
        raise ProjectError("Description must contain 1–250 characters.")
    project.mkdir(parents=True, exist_ok=False)
    files = {
        "repository.yaml": f"name: {json.dumps(name)}\n",
        f"{slug}/config.yaml": (
            f"name: {json.dumps(name)}\ndescription: {json.dumps(description)}\n"
            f'version: "0.1.0"\nslug: {slug}\ninit: false\narch:\n  - aarch64\n  - amd64\n'
        ),
        f"{slug}/Dockerfile": 'FROM ghcr.io/home-assistant/base:3.24\nCOPY run.sh /run.sh\nRUN chmod a+x /run.sh\nCMD ["/run.sh"]\n',
        f"{slug}/run.sh": "#!/command/with-contenv bashio\nbashio::log.info 'App started'\n",
    }
    write_files(config_dir, slug, files, overwrite=False)
    return {
        "project": slug,
        "files": sorted(files),
        "path": str(project),
        "note": "This is a project workspace, not Supervisor's local_apps directory. Publish it to an accessible Git repository or copy the app folder to local_apps before installation.",
    }


def list_projects(config_dir: str) -> dict[str, Any]:
    root = _root(config_dir)
    if not root.exists():
        return {"projects": [], "count": 0}
    projects = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and not path.is_symlink() and _SLUG.fullmatch(path.name)
    )
    return {"projects": projects, "count": len(projects)}


def write_files(
    config_dir: str, slug: str, files: dict[str, str], overwrite: bool = False
) -> dict[str, Any]:
    project = _project(config_dir, slug)
    if not isinstance(files, dict) or not files or len(files) > MAX_PROJECT_FILES:
        raise ProjectError(
            f"Provide 1–{MAX_PROJECT_FILES} files as a path-to-content object."
        )
    prepared: list[tuple[Path, bytes]] = []
    for name, content in files.items():
        path = _file(project, name)
        if not isinstance(content, str):
            raise ProjectError(f"Content for {name!r} must be text.")
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            raise ProjectError(f"File {name!r} exceeds {MAX_FILE_BYTES} bytes.")
        if path.exists() and not overwrite:
            raise ProjectError(
                f"File {name!r} already exists; set overwrite=true to replace it."
            )
        if path.exists() and not path.is_file():
            raise ProjectError(f"Path {name!r} is not a file.")
        prepared.append((path, data))
    for path, data in prepared:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".domora-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
    return {"project": slug, "written": sorted(files), "count": len(files)}


def read_file(config_dir: str, slug: str, name: str) -> dict[str, Any]:
    project = _project(config_dir, slug)
    path = _file(project, name)
    if not path.is_file():
        raise ProjectError(f"File {name!r} not found.")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ProjectError("File is too large to read through MCP.")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise ProjectError("Only UTF-8 text files can be read.") from err
    return {"project": slug, "path": name, "content": content}


def list_files(config_dir: str, slug: str) -> dict[str, Any]:
    project = _project(config_dir, slug)
    files = []
    for directory, dirs, names in os.walk(project, followlinks=False):
        dirs[:] = [
            d for d in dirs if d != ".git" and not (Path(directory) / d).is_symlink()
        ]
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                continue
            files.append(path.relative_to(project).as_posix())
            if len(files) > MAX_PROJECT_FILES:
                raise ProjectError("Project contains too many files to list.")
    return {"project": slug, "files": sorted(files), "count": len(files)}


def delete_file(config_dir: str, slug: str, name: str) -> dict[str, Any]:
    project = _project(config_dir, slug)
    path = _file(project, name)
    if not path.is_file():
        raise ProjectError(f"File {name!r} not found.")
    path.unlink()
    return {"project": slug, "deleted": name}
