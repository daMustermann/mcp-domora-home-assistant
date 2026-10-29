"""Check Supervisor request routing without contacting an actual system."""

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).parents[1] / "custom_components/mcp_domora"
spec = importlib.util.spec_from_file_location(
    "addon_projects", ROOT / "addon_projects.py"
)
projects = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projects)
tree = ast.parse((ROOT / "tools/addon_development.py").read_text(encoding="utf-8"))
names = {
    "_supervisor",
    "_addon_slug",
    "install_addon",
    "get_addon_job",
    "rebuild_addon",
    "add_addon_repository",
}
functions = [
    node
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names
]
for node in functions:
    node.decorator_list = []
module = ast.Module(body=functions, type_ignores=[])
ast.fix_missing_locations(module)


class InvalidInput(Exception):
    pass


class MCPBridgeError(Exception):
    pass


namespace = {
    "ToolContext": object,
    "Any": object,
    "InvalidInput": InvalidInput,
    "MCPBridgeError": MCPBridgeError,
    "addon_projects": projects,
    "UUID": UUID,
    "urlsplit": urlsplit,
    "require": lambda args, *keys: tuple(args[key] for key in keys),
}
exec(compile(module, str(ROOT / "tools/addon_development.py"), "exec"), namespace)


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ws = SimpleNamespace(
            call=AsyncMock(return_value={"job_id": "c8e9e82951314fbba247de3519f992f3"})
        )
        self.context = SimpleNamespace(
            check_admin=lambda: None,
            hass=SimpleNamespace(config=SimpleNamespace(components={"hassio"})),
            ws=self.ws,
        )

    async def test_install_uses_supervisor_background_job(self):
        result = await namespace["install_addon"](self.context, {"slug": "local_hello"})
        self.assertTrue(result["requested"])
        self.ws.call.assert_awaited_once_with(
            "supervisor/api",
            {
                "endpoint": "/store/addons/local_hello/install",
                "method": "post",
                "timeout": 60,
                "data": {"background": True},
            },
            timeout=70,
        )

    async def test_rebuild_waits_for_supervisor_without_background_flag(self):
        await namespace["rebuild_addon"](self.context, {"slug": "local_hello"})
        self.ws.call.assert_awaited_once_with(
            "supervisor/api",
            {
                "endpoint": "/addons/local_hello/rebuild",
                "method": "post",
                "timeout": 1800,
                "data": {},
            },
            timeout=1810,
        )

    async def test_job_id_and_slug_reject_path_injection(self):
        with self.assertRaises(InvalidInput):
            await namespace["install_addon"](self.context, {"slug": "../../other"})
        with self.assertRaises(InvalidInput):
            await namespace["get_addon_job"](self.context, {"job_id": "../other"})
        self.ws.call.assert_not_awaited()

    async def test_repositories_reject_embedded_credentials(self):
        with self.assertRaises(InvalidInput):
            await namespace["add_addon_repository"](
                self.context, {"repository": "https://user:password@example.com/repo"}
            )
        self.ws.call.assert_not_awaited()

    async def test_unsupervised_install_fails_clearly(self):
        self.context.hass.config.components = set()
        with self.assertRaises(MCPBridgeError):
            await namespace["install_addon"](self.context, {"slug": "local_hello"})


if __name__ == "__main__":
    unittest.main()
