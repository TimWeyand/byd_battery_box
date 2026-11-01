"""Load integration modules without executing Home Assistant's __init__.py."""

import sys
import types
from pathlib import Path

import pytest

package = types.ModuleType("byd_under_test")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components" / "byd_battery_box")]
sys.modules[package.__name__] = package


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """An accidental connection must fail, including in mocked client tests."""
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Network access is forbidden in these tests")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def pack_blocks(data):
    # Distinct non-voltage length placeholders detect accidentally kept headers.
    return [[0xF000 + offset // 64, *data[offset:offset + 64]] for offset in range(0, len(data), 64)]


@pytest.fixture
def rounds():
    data = [0x6EEE] * 256
    extra = [0x6EEE] * 128
    data[0:3] = [3400, 2900, (5 << 8) | 4]
    data[3:6] = [33, 0xFFE2, (3 << 8) | 2]
    data[6:14] = [0] * 8
    extra[6:14] = [0] * 8
    data[14:18] = [1000, 0, 500, 0]  # little-endian lifetime counters
    data[20:30] = [5000, 0, 1560, 5000, 755, 99, 0xFF85, 0, 0, 0]
    data[47] = 0
    data[48:176] = list(range(3001, 3129))
    extra[48:80] = list(range(3129, 3161))
    temps = list(range(-30, 34))
    data[177:209] = [((a & 0xFF) << 8) | (b & 0xFF) for a, b in zip(temps[::2], temps[1::2], strict=True)]
    return pack_blocks(data), pack_blocks(extra)
