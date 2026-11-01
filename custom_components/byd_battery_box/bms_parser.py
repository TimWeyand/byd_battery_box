"""Pure decoding of BYD BMS diagnostic blocks, without Modbus or HA imports."""

from collections.abc import Sequence
from dataclasses import dataclass

PARSER_VERSION = "2"


def unpack_blocks(blocks: Sequence[Sequence[int]], expected_blocks: int) -> list[int]:
    """Remove each 65-register block's leading length word, never shift data."""
    if len(blocks) != expected_blocks:
        raise ValueError(f"Expected {expected_blocks} BMS blocks, got {len(blocks)}")
    data: list[int] = []
    for block in blocks:
        if not isinstance(block, Sequence) or len(block) != 65:
            raise ValueError("Each BMS block must contain exactly 65 registers")
        if any(type(word) is not int or not 0 <= word <= 0xFFFF for word in block):
            raise ValueError("BMS registers must be unsigned 16-bit integers")
        data.extend(block[1:])
    return data


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def _balancing(words: Sequence[int], count: int) -> list[int]:
    # ASSUMPTION, still to be verified on hardware: bit n (LSB first) of
    # word k maps to cell k*16+n+1. Round 2 starts at global cell 129.
    return [(words[index // 16] >> (index % 16)) & 1 for index in range(count)]


@dataclass
class BmsStatus:
    """One update; computed extrema refer only to cells actually received."""

    cells_mv: list[int]
    cell_voltages: list[dict]
    cell_temps: list[dict]
    cell_balancing: list[dict]
    complete: bool
    round2_error: str | None
    plausible: bool | None
    plausibility_reason: str | None
    reported_min_mv: int
    reported_max_mv: int
    reported_min_id: int
    reported_max_id: int

    @property
    def computed_min_mv(self) -> int:
        return min(self.cells_mv)

    @property
    def computed_max_mv(self) -> int:
        return max(self.cells_mv)

    @property
    def computed_min_id(self) -> int:
        """Global, one-based cell number; first occurrence on ties."""
        return self.cells_mv.index(self.computed_min_mv) + 1

    @property
    def computed_max_id(self) -> int:
        """Global, one-based cell number; first occurrence on ties."""
        return self.cells_mv.index(self.computed_max_mv) + 1


def parse_bms_status(
    round1_blocks: Sequence[Sequence[int]],
    modules: int,
    cells_per_module: int,
    temps_per_module: int,
    round2_blocks: Sequence[Sequence[int]] | None = None,
) -> BmsStatus:
    """Decode D[48:176], optional E[48:80], and D[177:209] temperatures.

    Invalid round 1 raises ValueError. Missing/invalid round 2 keeps only
    round-1 cells and flags, with complete=False and no fabricated values.
    Reported IDs are the original header bytes, with their wire semantics.
    """
    total = modules * cells_per_module
    if modules <= 0 or cells_per_module <= 0 or total > 160:
        raise ValueError("BMS geometry must have between 1 and 160 cells")
    if temps_per_module <= 0 or temps_per_module % 2 or modules * temps_per_module > 64:
        raise ValueError("BMS temperatures must fit in 32 registers as int8 pairs")

    data = unpack_blocks(round1_blocks, 4)
    first_count = min(total, 128)
    cells = [_signed(word, 16) for word in data[48:48 + first_count]]
    reported_min = _signed(data[1], 16)
    reported_max = _signed(data[0], 16)
    if any(not 1000 <= cell <= 4500 for cell in cells):
        raise ValueError("Round-1 cell voltage outside 1000..4500 mV")
    if reported_max > 5000 or reported_min < 0:
        raise ValueError("Invalid BMS-reported voltage extrema")
    balancing = _balancing(data[6:14], first_count)
    round2_error = None
    if total > 128:
        if round2_blocks is None:
            round2_error = "Round 2 unavailable"
        else:
            try:
                extra = unpack_blocks(round2_blocks, 2)
                extra_cells = [_signed(word, 16) for word in extra[48:48 + total - 128]]
                if any(not 1000 <= cell <= 4500 for cell in extra_cells):
                    raise ValueError("Round-2 cell voltage outside 1000..4500 mV")
                # Uniform (or two-level) cells can legitimately match across
                # rounds. Only a varied identical block indicates no switch.
                if extra[48:80] == data[48:80] and len(set(extra[48:80])) >= 3:
                    raise ValueError("round 2 returned round-1 data")
            except (TypeError, ValueError) as err:
                round2_error = str(err)
            else:
                cells.extend(extra_cells)
                balancing.extend(_balancing(extra[6:14], total - 128))

    complete = len(cells) == total
    # A partial snapshot cannot validate extrema for the entire tower.
    plausible = None
    reasons = []
    if complete:
        # The two rounds are sampled seconds apart, so allow 10 mV drift.
        for name, reported, computed in (("min", reported_min, min(cells)), ("max", reported_max, max(cells))):
            if abs(reported - computed) > 10:
                reasons.append(f"reported {name} differs from computed {name} by more than 10 mV")
        plausible = not reasons

    # Temperatures start at register 50 of the third block (ioBroker.bydhvs:
    # byte 103 of that response), i.e. D[177]; D[176] is not a cell value.
    # This equals the previous regs[180:195] + regs[196:213].
    temperatures = [
        _signed(byte, 8)
        for word in data[177:177 + modules * temps_per_module // 2]
        for byte in (word >> 8, word & 0xFF)
    ]
    return BmsStatus(
        cells_mv=cells,
        cell_voltages=[{"m": m + 1, "v": cells[m * cells_per_module:(m + 1) * cells_per_module]} for m in range(modules)],
        cell_temps=[{"m": m + 1, "t": temperatures[m * temps_per_module:(m + 1) * temps_per_module]} for m in range(modules)],
        cell_balancing=[{"m": m + 1, "b": balancing[m * cells_per_module:(m + 1) * cells_per_module]} for m in range(modules)],
        complete=complete,
        round2_error=round2_error,
        plausible=plausible,
        plausibility_reason="; ".join(reasons) or None,
        reported_min_mv=reported_min,
        reported_max_mv=reported_max,
        reported_min_id=data[2] & 0xFF,
        reported_max_id=data[2] >> 8,
    )


def update_cell_history(history: list[dict] | None, current: list[dict], maximum: bool) -> list[dict]:
    """Keep known history when round 2 is missing; extend it on recovery."""
    if not isinstance(history, list):
        history = []
    valid = all(
        isinstance(item, dict)
        and type(item.get("m")) is int
        and isinstance(item.get("v"), list)
        and all(type(value) is int for value in item["v"])
        for item in history
    )
    previous = {item["m"]: item["v"] for item in history} if valid else {}
    result = []
    extreme = max if maximum else min
    for module in current:
        values = list(previous.get(module["m"], []))
        for index, value in enumerate(module["v"]):
            if index < len(values):
                values[index] = extreme(values[index], value)
            else:
                values.append(value)
        result.append({"m": module["m"], "v": values})
    return result
