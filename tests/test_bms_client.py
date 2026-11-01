"""Exercise I/O ordering with mocked helpers only, never a Modbus connection."""

import asyncio
import logging
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("pymodbus")
from byd_under_test.bydboxclient import BydBoxClient
from pymodbus.client import AsyncModbusTcpClient


def make_client(monkeypatch, rounds, hvm=False, failure=None):
    # Deliberately skip __init__: no transport, host, socket or device exists.
    client = BydBoxClient.__new__(BydBoxClient)
    client._client = SimpleNamespace(
        DATATYPE=AsyncModbusTcpClient.DATATYPE,
        convert_from_registers=AsyncModbusTcpClient.convert_from_registers,
    )
    client.data = {}
    client._unit_id = 1
    client._bms_qty = 1
    client._modules, client._cells, client._temps = (8, 16, 8) if hvm else (5, 32, 12)
    client.busy = False
    events = []
    responses = iter([failure != "round1_not_ready", failure != "ready"])
    blocks = deepcopy(rounds[0] + rounds[1])
    if failure == "short":
        blocks[4].pop()
    if failure == "garbled":
        blocks[5][10] = "bad"
    if failure == "unchanged":
        blocks[4][49:65] = blocks[0][49:65]
        blocks[5][1:17] = blocks[1][1:17]
    reads = iter(blocks)

    async def write(*, unit_id, address, payload):
        assert client.busy
        events.append(("write", address, payload))
        if (failure == "unlock" and address == 0x0100) or (failure == "command" and len(events) > 6 and address == 0x0550):
            raise RuntimeError("synthetic write failure")

    async def ready(*, address):
        assert client.busy
        events.append(("ready", address))
        return next(responses)

    async def read(*, address, count):
        assert client.busy
        events.append(("read", address, count))
        if len(events) == 10 and failure == "read_exception":
            raise RuntimeError("synthetic read failure")
        if len(events) == 11 and failure == "missing":
            return None
        return next(reads)

    client.write_registers = write
    client._wait_for_response = ready
    client.get_registers = read
    monkeypatch.setattr("byd_under_test.bydboxclient.asyncio.sleep", AsyncMock())
    return client, events


def expected_round(blocks):
    return [("write", 0x0550, [1, 0x8100]), ("ready", 0x0551)] + [("read", 0x0558, 65)] * blocks


def test_hvs_protocol_and_data_keys(monkeypatch, rounds):
    client, events = make_client(monkeypatch, rounds)
    assert asyncio.run(client.update_all_bms_status_data())
    assert not client.busy
    assert events == expected_round(4) + [("write", 0x0100, [0x4445, 0x4255, 0x4700])] + expected_round(2)
    assert client.data["bms1_cells_complete"]
    assert client.data["bms1_cells_plausible"] is False
    assert client.data["bms1_cell_voltages"][-1]["v"][-1] == 3160
    assert client.data["bms1_max_c_v"] == 3.16
    assert client.data["bms1_min_c_v"] == 3.001
    assert client.data["bms1_max_c_v_id"] == 5
    assert client.data["bms1_min_c_v_id"] == 4


def test_hvm_never_unlocks_or_reads_round2(monkeypatch, rounds):
    client, events = make_client(monkeypatch, rounds, hvm=True)
    assert asyncio.run(client.update_all_bms_status_data())
    assert events == expected_round(4)
    assert client.data["bms1_cells_complete"]
    assert client.data["bms1_cell_voltages"][7]["v"] == list(range(3113, 3129))


@pytest.mark.parametrize("failure", ["unlock", "command", "ready", "read_exception", "missing", "short", "garbled"])
def test_round2_failure_publishes_only_round1_and_warns(monkeypatch, rounds, caplog, failure):
    client, _ = make_client(monkeypatch, rounds, failure=failure)
    assert asyncio.run(client.update_all_bms_status_data())
    assert not client.busy
    assert not client.data["bms1_cells_complete"]
    assert client.data["bms1_cells_plausible"] is None
    assert client.data["bms1_cell_voltages"][-1]["v"] == []
    assert "round 2 failed" in caplog.text


def test_unswitched_round2_publishes_only_round1(monkeypatch, rounds, caplog):
    client, _ = make_client(monkeypatch, rounds, failure="unchanged")
    assert asyncio.run(client.update_all_bms_status_data())
    assert not client.data["bms1_cells_complete"]
    assert client.data["bms1_cell_voltages"][-1]["v"] == []
    assert "round 2 returned round-1 data" in caplog.text


def test_plausibility_warns_only_when_reason_changes_or_recurs_after_recovery(monkeypatch, rounds, caplog):
    client, _ = make_client(monkeypatch, rounds)
    for reported_min, reported_max, plausible, warning_count in (
        (2900, 3400, False, 1),
        (2890, 3410, False, 1),  # varying values with the same fault do not spam
        (2990, 3410, False, 1),  # min still differs by more than 10 mV
        (2991, 3410, False, 2),  # min is now within the 10 mV tolerance
        (2991, 3410, False, 2),
        (3001, 3160, True, 2),
        (2991, 3410, False, 3),
        (2991, 5000, False, 3),  # valid but implausible header still publishes data
    ):
        first, second = deepcopy(rounds)
        first[0][1:3] = [reported_max, reported_min]
        monkeypatch.setattr(client, "_read_bms_status_round", AsyncMock(side_effect=[first, second]))
        assert asyncio.run(client.update_all_bms_status_data())
        assert client.data["bms1_cells_complete"]
        assert client.data["bms1_cells_plausible"] is plausible
        assert client.data["bms1_cell_voltages"][-1]["v"][-1] == 3160
        warnings = [record for record in caplog.records if "cell voltages implausible" in record.message]
        assert len(warnings) == warning_count
        assert all(record.levelno == logging.WARNING and record.exc_info is None for record in warnings)


def test_round1_not_ready_warns_without_error_traceback(monkeypatch, rounds, caplog):
    client, events = make_client(monkeypatch, rounds, failure="round1_not_ready")
    assert not asyncio.run(client.update_all_bms_status_data())
    assert not client.busy
    assert client.data == {}
    assert events == expected_round(0)
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert record.exc_info is None
    assert "BMS 1 status not ready" in record.message


def test_other_round1_exceptions_keep_error_traceback(monkeypatch, rounds, caplog):
    client, _ = make_client(monkeypatch, rounds)
    monkeypatch.setattr(client, "get_registers", AsyncMock(side_effect=RuntimeError("synthetic read failure")))
    assert not asyncio.run(client.update_all_bms_status_data())
    assert not client.busy
    assert client.data == {}
    record = caplog.records[-1]
    assert record.levelno == logging.ERROR
    assert record.exc_info[0] is RuntimeError


def test_malformed_round1_aborts_without_publishing(monkeypatch, rounds):
    first, second = deepcopy(rounds)
    first[0].pop()
    client, events = make_client(monkeypatch, (first, second))
    assert not asyncio.run(client.update_all_bms_status_data())
    assert not client.busy
    assert client.data == {}
    assert events == expected_round(1)


@pytest.mark.parametrize("field,value", [(49, 999), (49, 4501), (49, 0xFFFF), (1, 5001), (2, 0xFFFF)])
@pytest.mark.parametrize("has_history", [False, True])
def test_invalid_round1_publishes_nothing_and_preserves_history(monkeypatch, rounds, field, value, has_history):
    client, _ = make_client(monkeypatch, rounds)
    if has_history:
        assert asyncio.run(client.update_all_bms_status_data())
    before = deepcopy(client.data)
    first, second = deepcopy(rounds)
    first[0][field] = value
    invalid_client, _ = make_client(monkeypatch, (first, second))
    invalid_client.data = client.data
    assert not asyncio.run(invalid_client.update_all_bms_status_data())
    assert not invalid_client.busy
    assert invalid_client.data == before


@pytest.mark.parametrize("value", [999, 4501, 0xFFFF])
def test_invalid_round2_preserves_history_and_publishes_only_round1(monkeypatch, rounds, caplog, value):
    client, _ = make_client(monkeypatch, rounds)
    assert asyncio.run(client.update_all_bms_status_data())
    before = deepcopy(client.data)
    first, second = deepcopy(rounds)
    second[1][16] = value
    invalid_client, _ = make_client(monkeypatch, (first, second))
    invalid_client.data = client.data
    assert asyncio.run(invalid_client.update_all_bms_status_data())
    assert not invalid_client.busy
    assert invalid_client.data["bms1_cells_complete"] is False
    assert invalid_client.data["bms1_cells_plausible"] is None
    assert invalid_client.data["bms1_cell_voltages"][-1]["v"] == []
    assert invalid_client.data["bms1_max_c_v"] == 3.128
    assert invalid_client.data["bms1_cell_balancing"][-1]["b"] == []
    for suffix in ("cell_voltages_max_history", "cell_voltages_min_history", "max_history_cell_voltage_cells", "min_history_cell_voltage_cells"):
        assert invalid_client.data[f"bms1_{suffix}"] == before[f"bms1_{suffix}"]
    assert "round 2 invalid" in caplog.text


def test_partial_to_full_and_back_does_not_break_or_erase_history(monkeypatch, rounds):
    client, _ = make_client(monkeypatch, rounds, failure="unlock")
    assert asyncio.run(client.update_all_bms_status_data())
    assert client.data["bms1_max_history_cell_voltage_cells"][-1]["v"] == []
    good_client, _ = make_client(monkeypatch, rounds)
    good_client.data = client.data
    assert asyncio.run(good_client.update_all_bms_status_data())
    for suffix in ("cell_voltages_max_history", "cell_voltages_min_history", "max_history_cell_voltage_cells", "min_history_cell_voltage_cells"):
        assert len(good_client.data[f"bms1_{suffix}"][-1]["v"]) == 32
    partial_client, _ = make_client(monkeypatch, rounds, failure="unlock")
    partial_client.data = good_client.data
    assert asyncio.run(partial_client.update_all_bms_status_data())
    assert len(partial_client.data["bms1_min_history_cell_voltage_cells"][-1]["v"]) == 32
