"""Provide a minimal amplifier_core stub so the module can be imported in tests."""

import sys
import types


def _install_amplifier_core_stub():
    if "amplifier_core" in sys.modules:
        return
    mod = types.ModuleType("amplifier_core")

    class ToolResult:
        def __init__(self, success=True, output=None, error=None):
            self.success = success
            self.output = output
            self.error = error

    mod.ToolResult = ToolResult
    mod.ModuleCoordinator = type("ModuleCoordinator", (), {})
    sys.modules["amplifier_core"] = mod

_install_amplifier_core_stub()