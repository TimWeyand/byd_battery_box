"""Balancing attributes use the same one-based module labels as cell data.

The real client, log decoder, hub data property and sensor attributes are used.
Network constructors and HA setup/polling are deliberately not run.
"""

import socket
from copy import deepcopy

import pytest

from custom_components.byd_battery_box.bydboxclient import BydBoxClient
from custom_components.byd_battery_box.hub import Hub
from custom_components.byd_battery_box.sensor import BydBoxSensor


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    """No helper or sensor read may open a network connection."""
    def fail(*_args, **_kwargs):
        raise AssertionError("This regression must not contact hardware")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket.socket, "connect_ex", fail)
    monkeypatch.setattr(socket.socket, "sendto", fail)
    monkeypatch.setattr(socket, "create_connection", fail)


def make_client(modules, cells=16):
    """Allocate data-only instances without opening a Modbus transport."""
    client = BydBoxClient.__new__(BydBoxClient)
    client._modules = modules
    client._cells = cells
    client._bms_qty = 2
    client.data = {}
    client.log = {}
    return client


def make_sensor(client, key):
    hub = Hub.__new__(Hub)
    hub._bydclient = client
    return BydBoxSensor("byd_test", hub, {}, key, key, None, None, None, None, None)


@pytest.mark.parametrize("modules", [1, 2, 3])
def test_module_labels_and_sparse_counts(modules):
    client = make_client(modules)
    counts = {"0": 3, "15": 2, "16": 7, "31": 5, "32": 11, "47": 13}
    before = deepcopy(counts)

    result = client._get_balancings_totals_per_module(counts)

    expected_counts = [
        [3, *([0] * 14), 2],
        [7, *([0] * 14), 5],
        [11, *([0] * 14), 13],
    ][:modules]
    assert [item["m"] for item in result] == list(range(1, modules + 1))
    assert [item["bct"] for item in result] == expected_counts
    assert counts == before


def test_zero_counts_keep_one_based_labels():
    result = make_client(2)._get_balancings_totals_per_module({})
    assert result == [{"m": 1, "bct": [0] * 16}, {"m": 2, "bct": [0] * 16}]


def test_no_modules_keeps_empty_result():
    assert make_client(0)._get_balancings_totals_per_module({}) == []


def balancing_log(unit, cells):
    """Build synthetic code17 bitmaps for the existing log decoder."""
    payload = bytearray(23)
    for cell in cells:
        payload[cell // 8] |= 1 << (cell % 8)
    return {"ts": 1700000000, "u": unit, "c": 17, "data": payload.hex()}


def test_log_aggregation_reaches_one_based_sensor_attributes():
    client = make_client(2)
    client.log = {
        "first": balancing_log(1, [0, 15, 16]),
        "second": balancing_log(1, [0, 31]),
        "other_tower": balancing_log(2, [1, 17]),
    }
    before = deepcopy(client.log)

    client._update_balancing_cells_totals()

    sensor = make_sensor(client, "bms1_b_total")
    other = make_sensor(client, "bms2_b_total")
    assert sensor.state == 2
    assert sensor.extra_state_attributes == {
        "total_cells": [
            {"m": 1, "bct": [2, *([0] * 14), 1]},
            {"m": 2, "bct": [1, *([0] * 14), 1]},
        ]
    }
    assert other.state == 1
    assert other.extra_state_attributes == {
        "total_cells": [
            {"m": 1, "bct": [0, 1, *([0] * 14)]},
            {"m": 2, "bct": [0, 1, *([0] * 14)]},
        ]
    }
    assert client.log == before


def test_balancing_labels_align_with_cell_attribute_convention():
    client = make_client(2)
    client.data["bms1_b_cells_total"] = client._get_balancings_totals_per_module({"0": 1, "16": 2})
    # Independent synthetic voltage attribute follows the existing one-based
    # module convention from update_bms_status_data and the published UI.
    client.data["bms1_cell_voltages"] = [{"m": 1, "v": [3300] * 16}, {"m": 2, "v": [3301] * 16}]
    balancing = make_sensor(client, "bms1_b_total").extra_state_attributes["total_cells"]
    voltage = make_sensor(client, "bms1_avg_c_v").extra_state_attributes["cell_voltages"]

    assert [item["m"] for item in balancing] == [item["m"] for item in voltage] == [1, 2]
