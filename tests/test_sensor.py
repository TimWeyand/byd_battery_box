"""Sensor history restore and metadata without a running HA instance."""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from byd_under_test.bms_parser import PARSER_VERSION, update_cell_history

pytest.importorskip("homeassistant")
pytest.importorskip("pymodbus")


@pytest.fixture
def make_sensor(monkeypatch):
    import byd_under_test

    # The package stub deliberately skips the integration's HA entry point.
    monkeypatch.setattr(byd_under_test, "HubConfigEntry", object, raising=False)
    sensor_module = importlib.import_module("byd_under_test.sensor")

    def make(key, data=None):
        hub = SimpleNamespace(data={} if data is None else data, async_add_hub_entity=Mock())
        return sensor_module.BydBoxSensor("byd", hub, {}, "test", key, None, None, "V", None, None)

    return make


@pytest.mark.parametrize("kind", ["min", "max"])
@pytest.mark.parametrize("version", [None, "1", 2, PARSER_VERSION])
def test_history_restore_requires_current_parser_version(make_sensor, monkeypatch, kind, version):
    sensor = make_sensor(f"bms1_{kind}_history_cell_voltage")
    history = [{"m": 1, "v": [1000 if kind == "min" else 9000]}]
    attrs = {"cell_voltages": history}
    if version is not None:
        attrs["parser_version"] = version
    monkeypatch.setattr(sensor, "async_get_last_state", AsyncMock(return_value=SimpleNamespace(state="3.1", attributes=attrs)))
    asyncio.run(sensor.async_added_to_hass())
    sensor._hub.async_add_hub_entity.assert_called_once()
    assert sensor.state == 3.1
    restored = sensor._hub.data.get(f"{sensor._key}_cells")
    if version == PARSER_VERSION:
        assert restored == history
    else:
        assert restored is None
        current = [{"m": 1, "v": [3100]}]
        assert update_cell_history(restored, current, kind == "max") == current


@pytest.mark.parametrize("suffix", ["avg_c_v", "max_history_c_v", "min_history_c_v", "max_history_cell_voltage", "min_history_cell_voltage"])
def test_voltage_history_and_average_attributes_include_parser_version(make_sensor, suffix):
    sensor = make_sensor(f"bms1_{suffix}")
    assert sensor.extra_state_attributes["parser_version"] == PARSER_VERSION


@pytest.mark.parametrize("suffix", ["avg_c_v", "balancing_qty"])
@pytest.mark.parametrize("plausible", [True, False, None])
def test_cell_attributes_include_plausibility_next_to_completeness(make_sensor, suffix, plausible):
    sensor = make_sensor(f"bms1_{suffix}", {"bms1_cells_complete": plausible is not None, "bms1_cells_plausible": plausible})
    assert sensor.extra_state_attributes["cells_complete"] is (plausible is not None)
    assert sensor.extra_state_attributes["cells_plausible"] is plausible
