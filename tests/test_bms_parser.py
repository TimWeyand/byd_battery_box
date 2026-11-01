"""Pure synthetic tests: no Home Assistant, Modbus client, or hardware."""

from copy import deepcopy

import pytest
from byd_under_test.bms_parser import parse_bms_status, unpack_blocks, update_cell_history


def test_hvs_160_unique_cells_and_extrema(rounds):
    first, second = rounds
    status = parse_bms_status(first, 5, 32, 12, second)
    assert status.complete
    assert status.round2_error is None
    assert status.cells_mv == list(range(3001, 3161))
    assert len(set(status.cells_mv)) == 160
    for m, module in enumerate(status.cell_voltages):
        assert module == {"m": m + 1, "v": list(range(3001 + m * 32, 3033 + m * 32))}
    assert (status.reported_min_mv, status.reported_max_mv) == (2900, 3400)
    assert (status.reported_min_id, status.reported_max_id) == (4, 5)
    assert (status.computed_min_mv, status.computed_max_mv) == (3001, 3160)
    assert (status.computed_min_id, status.computed_max_id) == (1, 160)


@pytest.mark.parametrize("cell", [16, 17, 64, 65, 80, 81, 128, 129, 144, 145, 160])
def test_cell_boundaries(rounds, cell):
    status = parse_bms_status(rounds[0], 5, 32, 12, rounds[1])
    module, index = divmod(cell - 1, 32)
    assert status.cell_voltages[module]["v"][index] == 3000 + cell


def test_hvs_missing_round2_is_partial_without_padding_or_temperature_as_voltage(rounds):
    status = parse_bms_status(rounds[0], 5, 32, 12)
    assert not status.complete
    assert status.round2_error
    assert status.cells_mv == list(range(3001, 3129))
    assert [len(module["v"]) for module in status.cell_voltages] == [32, 32, 32, 32, 0]
    assert status.cell_balancing[4] == {"m": 5, "b": []}
    assert status.computed_max_id == 128
    assert status.computed_max_mv == 3128
    assert status.reported_min_mv == 2900
    assert status.plausible is None
    assert status.plausibility_reason is None


def test_round2_returning_round1_cells_is_incomplete(rounds):
    first, second = deepcopy(rounds)
    second[0][49:65] = first[0][49:65]
    second[1][1:17] = first[1][1:17]
    status = parse_bms_status(first, 5, 32, 12, second)
    assert not status.complete
    assert status.round2_error == "round 2 returned round-1 data"
    assert status.cells_mv == list(range(3001, 3129))
    assert status.cell_voltages[-1]["v"] == []
    assert status.cell_balancing[-1]["b"] == []
    assert status.plausible is None


@pytest.mark.parametrize("values", [[3300] * 32, [3299, 3300] * 16, [3299, 3300, 3301, 3300] * 8])
def test_identical_round2_needs_at_least_three_distinct_values_to_be_rejected(rounds, values):
    first, second = deepcopy(rounds)
    for blocks in (first, second):
        blocks[0][49:65] = values[:16]
        blocks[1][1:17] = values[16:]
    status = parse_bms_status(first, 5, 32, 12, second)
    if len(set(values)) >= 3:
        assert not status.complete
        assert status.round2_error == "round 2 returned round-1 data"
        assert status.cell_voltages[-1]["v"] == []
    else:
        assert status.complete
        assert status.round2_error is None
        assert status.cell_voltages[-1]["v"] == values


def test_uniform_3300_mv_tower_is_complete_and_plausible(rounds):
    first, second = deepcopy(rounds)
    first[0][1:3] = [3300, 3300]
    for index in range(128):
        block, word = divmod(48 + index, 64)
        first[block][word + 1] = 3300
    second[0][49:65] = [3300] * 16
    second[1][1:17] = [3300] * 16
    status = parse_bms_status(first, 5, 32, 12, second)
    assert status.complete
    assert status.plausible
    assert status.cells_mv == [3300] * 160


@pytest.mark.parametrize("value", [0, 999, 4501, 5001, 0xFFFF])
@pytest.mark.parametrize("cell_index", [0, 127])
def test_invalid_round1_cell_aborts(rounds, value, cell_index):
    first, second = deepcopy(rounds)
    block, word = divmod(48 + cell_index, 64)
    first[block][word + 1] = value
    with pytest.raises(ValueError, match="Round-1 cell voltage"):
        parse_bms_status(first, 5, 32, 12, second)


@pytest.mark.parametrize("value", [0, 999, 4501, 5001, 0xFFFF])
@pytest.mark.parametrize("cell_index", [0, 31])
def test_invalid_round2_cell_discards_entire_extra_round(rounds, value, cell_index):
    first, second = deepcopy(rounds)
    block, word = divmod(48 + cell_index, 64)
    second[block][word + 1] = value
    status = parse_bms_status(first, 5, 32, 12, second)
    assert not status.complete
    assert "Round-2 cell voltage" in status.round2_error
    assert status.cells_mv == list(range(3001, 3129))
    assert status.cell_voltages[-1]["v"] == []
    assert status.cell_balancing[-1]["b"] == []
    assert status.plausible is None


@pytest.mark.parametrize("reported_min,reported_max", [(3000, 5001), (3000, 6000), (0xFFFF, 3400)])
def test_invalid_reported_extrema_abort(rounds, reported_min, reported_max):
    first, second = deepcopy(rounds)
    first[0][1:3] = [reported_max, reported_min]
    with pytest.raises(ValueError, match="Invalid BMS-reported voltage extrema"):
        parse_bms_status(first, 5, 32, 12, second)


def test_hard_validity_limits_are_inclusive(rounds):
    first, second = deepcopy(rounds)
    first[0][1:3] = [5000, 0]
    first[0][49] = 1000
    second[1][16] = 4500
    status = parse_bms_status(first, 5, 32, 12, second)
    assert status.complete
    assert status.computed_min_mv == 1000
    assert status.computed_max_mv == 4500
    assert status.plausible is False


@pytest.mark.parametrize("modules,cells,temps", [(5, 32, 12), (8, 16, 8)])
@pytest.mark.parametrize(
    "reported_min,reported_max,plausible,reason",
    [
        (3000, 3100, True, None),
        (2990, 3110, True, None),  # inclusive 10 mV tolerance
        (3010, 3090, True, None),  # tolerance also applies inside the range
        (2995, 3105, True, None),  # reported values need not occur in cells
        (2989, 3100, False, "reported min differs from computed min"),
        (3011, 3100, False, "reported min differs from computed min"),
        (3000, 3111, False, "reported max differs from computed max"),
        (3000, 3089, False, "reported max differs from computed max"),
        (3100, 3100, False, "reported min differs from computed min"),
        (3000, 3000, False, "reported max differs from computed max"),
    ],
)
def test_reported_extrema_plausibility(rounds, modules, cells, temps, reported_min, reported_max, plausible, reason):
    first, second = deepcopy(rounds)
    # Two distinct levels also avoid triggering duplicate round-2 detection.
    first[0][49:65] = [3000] * 16
    first[1][1:65] = [3000] * 64
    first[2][1:49] = [3000] * 48
    first[2][48] = 3100  # D[175], cell 128
    second[0][49:65] = [3100] * 16
    second[1][1:17] = [3100] * 16
    first[0][1:3] = [reported_max, reported_min]
    status = parse_bms_status(first, modules, cells, temps, second)
    assert status.complete
    assert status.plausible is plausible
    if reason is None:
        assert status.plausibility_reason is None
    else:
        assert reason in status.plausibility_reason
    assert len(status.cells_mv) == modules * cells  # publish all cells even on failure


def test_hvm_8x16_stays_in_round1(rounds):
    # An invalid optional round 2 is ignored when it is not needed.
    status = parse_bms_status(rounds[0], 8, 16, 8, [["unused"]])
    assert status.complete
    assert status.round2_error is None
    assert status.cells_mv == list(range(3001, 3129))
    for m, module in enumerate(status.cell_voltages):
        assert module == {"m": m + 1, "v": list(range(3001 + m * 16, 3017 + m * 16))}


@pytest.mark.parametrize("modules,cells,temps", [(5, 32, 12), (8, 16, 8), (4, 32, 12)])
def test_temperatures_are_signed_pairs_with_no_module_overlap(rounds, modules, cells, temps):
    first, second = rounds
    status = parse_bms_status(first, modules, cells, temps, second)
    for m, module in enumerate(status.cell_temps):
        assert module == {"m": m + 1, "t": list(range(-30 + m * temps, -30 + (m + 1) * temps))}
    assert [t for module in status.cell_temps for t in module["t"]] == list(range(-30, -30 + modules * temps))


def test_temperature_slice_matches_previous_layout(rounds):
    blocks = rounds[0]
    raw = [word for block in blocks for word in block]
    data = unpack_blocks(blocks, 4)
    # Block 3 register 50 (ioBroker byte 103) starts the temperatures.
    assert raw[180:195] + raw[196:213] == data[177:209]


@pytest.mark.parametrize("cell", [1, 16, 17, 32, 33, 64, 65, 80, 81, 128, 129, 144, 145, 160])
def test_assumed_balancing_bits_cover_all_cells_without_overlap(rounds, cell):
    first, second = deepcopy(rounds)
    local = cell - 1 if cell <= 128 else cell - 129
    block = first[0] if cell <= 128 else second[0]
    block[7 + local // 16] = 1 << (local % 16)
    status = parse_bms_status(first, 5, 32, 12, second)
    flags = [bit for module in status.cell_balancing for bit in module["b"]]
    assert len(flags) == 160
    assert sum(flags) == 1
    assert flags[cell - 1] == 1


@pytest.mark.parametrize("kind", ["missing_block", "short", "long", "bad_word", "negative", "overflow", "boolean", "none"])
@pytest.mark.parametrize("round_number", [1, 2])
def test_malformed_blocks_never_shift_cells(rounds, kind, round_number):
    first, second = deepcopy(rounds)
    blocks = first if round_number == 1 else second
    if kind == "missing_block":
        blocks.pop()
    elif kind == "short":
        blocks[0].pop()
    elif kind == "long":
        blocks[0].append(0)
    elif kind == "none":
        blocks[0] = None
    else:
        blocks[0][50] = {"bad_word": "3000", "negative": -1, "overflow": 65536, "boolean": True}[kind]
    if round_number == 1:
        with pytest.raises(ValueError):
            parse_bms_status(first, 5, 32, 12, second)
    else:
        status = parse_bms_status(first, 5, 32, 12, second)
        assert not status.complete
        assert status.round2_error
        assert status.cells_mv == list(range(3001, 3129))
        assert status.cell_voltages[-1]["v"] == []


def test_computed_extremum_ids_use_first_occurrence(rounds):
    first, second = deepcopy(rounds)
    first[0][50] = 3001
    second[1][16] = 3001  # global cell 160
    status = parse_bms_status(first, 5, 32, 12, second)
    assert status.cells_mv[:2] == [3001, 3001]
    assert status.computed_min_id == 1
    assert status.computed_max_id == 159


def test_both_computed_extrema_can_be_in_round2(rounds):
    first, second = deepcopy(rounds)
    second[0][49] = 2700  # E[48], cell 129
    second[1][16] = 3500  # E[79], cell 160
    status = parse_bms_status(first, 5, 32, 12, second)
    assert (status.computed_min_mv, status.computed_min_id) == (2700, 129)
    assert (status.computed_max_mv, status.computed_max_id) == (3500, 160)
    assert (status.reported_min_mv, status.reported_max_mv) == (2900, 3400)


@pytest.mark.parametrize("maximum", [True, False])
def test_history_preserves_missing_cells_and_extends_after_recovery(rounds, maximum):
    full = parse_bms_status(rounds[0], 5, 32, 12, rounds[1]).cell_voltages
    partial = parse_bms_status(rounds[0], 5, 32, 12).cell_voltages
    initial = update_cell_history(None, partial, maximum)
    assert initial[-1]["v"] == []
    recovered = update_cell_history(initial, full, maximum)
    assert recovered == full
    assert initial[-1]["v"] == []  # no mutation of previous snapshots
    assert update_cell_history(recovered, partial, maximum) == full
    changed = deepcopy(full)
    changed[-1]["v"][0] += 10 if maximum else -10
    assert update_cell_history(recovered, changed, maximum) == changed


@pytest.mark.parametrize("maximum", [True, False])
@pytest.mark.parametrize(
    "history",
    [
        None, {}, "bad", 42, [None], [1], [[3000]], [{}],
        [{"m": 1}], [{"v": [3000]}], [{"m": "1", "v": [3000]}],
        [{"m": True, "v": [3000]}], [{"m": [], "v": [3000]}],
        [{"m": 1, "v": None}], [{"m": 1, "v": 3000}], [{"m": 1, "v": "3000"}],
        [{"m": 1, "v": [None]}], [{"m": 1, "v": ["3000"]}],
        [{"m": 1, "v": [3000.0]}], [{"m": 1, "v": [True]}],
        [{"m": 1, "v": [9000]}, {"m": 2, "v": [None]}],
    ],
)
def test_malformed_history_reinitialises_all_modules(history, maximum):
    before = deepcopy(history)
    current = [{"m": 1, "v": [3000, 3100]}, {"m": 2, "v": []}]
    result = update_cell_history(history, current, maximum)
    assert result == current
    assert result is not current
    assert result[0]["v"] is not current[0]["v"]
    assert history == before


@pytest.mark.parametrize("geometry", [(0, 32, 12), (6, 32, 12), (5, 0, 12), (5, 32, 11), (5, 32, 14)])
def test_invalid_geometry_is_rejected(rounds, geometry):
    with pytest.raises(ValueError):
        parse_bms_status(rounds[0], *geometry)
