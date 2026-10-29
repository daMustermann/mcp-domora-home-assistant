"""Ensure the setup flow displays a local connection address."""

import ast
from pathlib import Path
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).parents[1] / "custom_components/mcp_domora/config_flow.py"
tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
function = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "_mcp_url"
)
module = ast.Module(body=[function], type_ignores=[])
ast.fix_missing_locations(module)


class NoURLAvailableError(Exception):
    pass


get_url = Mock()
namespace = {
    "Any": object,
    "get_url": get_url,
    "NoURLAvailableError": NoURLAvailableError,
    "MCP_PATH": "/mcp_domora/mcp",
}
exec(compile(module, str(SOURCE), "exec"), namespace)


class ConnectionURLTests(unittest.TestCase):
    def setUp(self):
        get_url.reset_mock(return_value=True, side_effect=True)

    def test_uses_only_local_url(self):
        hass = object()
        get_url.return_value = "http://homeassistant:8123/"
        self.assertEqual(
            namespace["_mcp_url"](hass), "http://homeassistant:8123/mcp_domora/mcp"
        )
        get_url.assert_called_once_with(
            hass, allow_internal=True, allow_external=False, allow_cloud=False
        )

    def test_returns_relative_path_if_local_url_is_not_available(self):
        get_url.side_effect = NoURLAvailableError()
        self.assertEqual(namespace["_mcp_url"](object()), "/mcp_domora/mcp")


if __name__ == "__main__":
    unittest.main()
