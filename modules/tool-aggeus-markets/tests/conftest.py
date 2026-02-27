"""Provide a minimal amplifier_core stub and coincurve stub for testing."""

import hashlib
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
            error: dict | None = None,
        ):
            self.success = success
            self.output = output
            self.error = error

    mod.ToolResult = ToolResult  # type: ignore[attr-defined]
    mod.ModuleCoordinator = type("ModuleCoordinator", (), {})  # type: ignore[attr-defined]
    sys.modules["amplifier_core"] = mod


def _install_coincurve_stub() -> None:
    """Provide a deterministic coincurve stub for testing crypto functions.

    The stub produces predictable outputs based on inputs so tests can
    assert on exact values without needing the real C library.
    """
    if "coincurve" in sys.modules:
        return

    mod = types.ModuleType("coincurve")

    class _FakePublicKey:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def format(self, compressed: bool = True) -> bytes:
            # Return a deterministic 33-byte compressed pubkey:
            # prefix byte 0x02 + SHA256(privkey_bytes) truncated to 32 bytes
            h = hashlib.sha256(self._data).digest()
            return b"\x02" + h

    class PrivateKey:
        def __init__(self, secret: bytes) -> None:
            self._secret = secret

        @property
        def public_key(self) -> _FakePublicKey:
            return _FakePublicKey(self._secret)

        def sign_schnorr(self, msg: bytes) -> bytes:
            # Deterministic fake signature: SHA256(secret + msg), doubled to 64 bytes
            h = hashlib.sha256(self._secret + msg).digest()
            return h + h  # 64 bytes like a real Schnorr sig

    mod.PrivateKey = PrivateKey  # type: ignore[attr-defined]
    sys.modules["coincurve"] = mod


def _install_websockets_stub() -> None:
    """Provide a minimal websockets stub so client.py can be imported."""
    if "websockets" in sys.modules:
        return
    mod = types.ModuleType("websockets")

    async def connect(*args, **kwargs):
        raise OSError("websockets stub: not a real connection")

    mod.connect = connect  # type: ignore[attr-defined]
    sys.modules["websockets"] = mod


_install_amplifier_core_stub()
_install_coincurve_stub()
_install_websockets_stub()
