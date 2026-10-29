"""Exercise backup dispatch without importing or running Home Assistant."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

SOURCE = Path(__file__).parents[1] / "custom_components/mcp_bridge/tools/supervisor.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name in {"create_backup", "restore_backup"}]
for node in functions:
    node.decorator_list = []
module = ast.Module(body=functions, type_ignores=[])
ast.fix_missing_locations(module)


class InvalidInput(Exception):
    pass


def require(args, *keys):
    return tuple(args[key] for key in keys)


namespace = {"ToolContext": object, "Any": object, "InvalidInput": InvalidInput, "require": require}
exec(compile(module, str(SOURCE), "exec"), namespace)


class BackupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ws = SimpleNamespace(call=AsyncMock(return_value={"backup_id": "backup-1"}))
        self.context = SimpleNamespace(check_admin=lambda: None, ws=self.ws)

    async def test_default_uses_automatic_settings(self):
        result = await namespace["create_backup"](self.context, {})
        self.ws.call.assert_awaited_once_with("backup/generate_with_automatic_settings")
        self.assertTrue(result["started"])

    async def test_explicit_needs_real_agent_id(self):
        with self.assertRaises(InvalidInput):
            await namespace["create_backup"](self.context, {"name": "checkpoint"})
        self.ws.call.assert_not_awaited()

    async def test_explicit_backup_forwards_options(self):
        await namespace["create_backup"](self.context, {"name": "checkpoint", "agent_ids": ["hassio.local"], "include_folders": ["ssl"]})
        self.ws.call.assert_awaited_once_with("backup/generate", {"agent_ids": ["hassio.local"], "include_homeassistant": True, "include_all_addons": True, "include_database": True, "include_folders": ["ssl"], "name": "checkpoint"})

    async def test_restore_forwards_exact_backup_and_location(self):
        await namespace["restore_backup"](self.context, {"backup_id": "123", "agent_id": "hassio.local", "restore_database": False})
        self.ws.call.assert_awaited_once_with("backup/restore", {"backup_id": "123", "agent_id": "hassio.local", "restore_database": False}, timeout=120)


if __name__ == "__main__":
    unittest.main()
