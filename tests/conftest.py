"""Stub amplifier_core so the module can be imported without the real framework."""

import sys
import types
from dataclasses import dataclass, field
from typing import Any

# Create a fake amplifier_core module with the symbols the production code imports.
_mod = types.ModuleType("amplifier_core")


class _ModuleCoordinator:
    async def mount(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        pass


@dataclass
class _ToolResult:
    success: bool = True
    output: str = ""
    error: dict[str, Any] = field(default_factory=dict)


_mod.ModuleCoordinator = _ModuleCoordinator  # type: ignore[attr-defined]
_mod.ToolResult = _ToolResult  # type: ignore[attr-defined]

sys.modules.setdefault("amplifier_core", _mod)
