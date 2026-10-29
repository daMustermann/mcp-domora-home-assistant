"""Tests for integration reauthentication without provider credentials."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

SOURCE = Path(__file__).parents[1] / "custom_components/mcp_bridge/tools/integrations.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
functions = [
    node for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    and node.name in {"_flow_result", "start_reauthentication"}
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
    "require": lambda args, *keys: tuple(args[key] for key in keys),
    "_serialise_schema": lambda schema: schema,
}
exec(compile(module, str(SOURCE), "exec"), namespace)


class ReauthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        entry = SimpleNamespace(
            entry_id="abc", domain="example", title="Example", unique_id="xyz",
            data={"token": "secret"},
        )
        self.manager = SimpleNamespace(
            async_progress=lambda: [],
            async_init=AsyncMock(return_value={"type": "external", "flow_id": "flow-1", "url": "https://example.test/login"}),
        )
        entries = SimpleNamespace(async_get_entry=lambda entry_id: entry, flow=self.manager)
        self.context = SimpleNamespace(
            check_admin=lambda: None,
            hass=SimpleNamespace(config_entries=entries),
            runtime_flows={},
        )

    async def test_reauth_returns_external_url_without_entry_credentials(self):
        result = await namespace["start_reauthentication"](self.context, {"entry_id": "abc"})
        self.assertEqual(result["url"], "https://example.test/login")
        self.assertNotIn("secret", str(result))
        self.assertEqual(self.context.runtime_flows["flow-1"], "config")
        self.assertEqual(self.manager.async_init.await_args.kwargs["context"]["source"], "reauth")

    async def test_existing_flow_does_not_create_duplicate(self):
        self.manager.async_progress = lambda: [{"flow_id": "old", "context": {"entry_id": "abc", "source": "reauth"}}]
        result = await namespace["start_reauthentication"](self.context, {"entry_id": "abc"})
        self.assertEqual(result["flow_id"], "old")
        self.manager.async_init.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
