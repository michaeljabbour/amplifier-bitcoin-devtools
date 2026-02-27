"""Provide a minimal amplifier_core stub so the module can be imported in tests."""

import sys
import types


def _install_amplifier_core_stub() -> None:
    if "amplifier_core" in sys.modules:
        return
    mod = types.ModuleType("amplifier_core")

    class ToolResult:
        def __init__(
            self,
            success: bool = True,
            output: str | None = None,
            error: dict | None = None,  # noqa: UP006
        ):
            self.success = success
            self.output = output
            self.error = error

    mod.ToolResult = ToolResult  # type: ignore[attr-defined]
    mod.ModuleCoordinator = type("ModuleCoordinator", (), {})  # type: ignore[attr-defined]
    sys.modules["amplifier_core"] = mod


_install_amplifier_core_stub()
