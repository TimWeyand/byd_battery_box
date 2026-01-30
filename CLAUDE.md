# BYD Battery Box - Home Assistant Custom Integration

## Project Overview

This is a **Home Assistant Custom Component** for monitoring BYD Battery Box energy storage systems (HVL, HVM, HVS, LVS series) via local **Modbus TCP** connection. It is distributed through **HACS** (Home Assistant Community Store).

- **Domain:** `byd_battery_box`
- **Current Version:** `0.1.31` (defined in `custom_components/byd_battery_box/manifest.json`)
- **License:** Apache 2.0
- **Original Author:** @redpomodoro
- **Current Maintainer:** @TimWeyand
- **IoT Class:** Local Polling (no cloud dependency)
- **Repository:** https://github.com/TimWeyand/byd_battery_box (fork of `redpomodoro/byd_battery_box`)

## Tech Stack

| Component | Version / Details |
|---|---|
| Python | 3.12+ |
| Home Assistant | >= 2025.9.0 (see `hacs.json`) |
| pymodbus | >= 3.11.2 (see `manifest.json`) |
| Communication | Modbus TCP, default port 8080 |
| Default Battery IP | 192.168.16.254 |

## Project Structure

```
byd_battery_box/
├── custom_components/byd_battery_box/   # Main integration code
│   ├── __init__.py                      # Entry point, platform setup (sensor + button)
│   ├── config_flow.py                   # UI-based configuration flow
│   ├── const.py                         # Constants, sensor/button type definitions
│   ├── hub.py                           # Hub class: lifecycle, periodic updates, device info
│   ├── sensor.py                        # Sensor entity definitions
│   ├── button.py                        # Button entity definitions (log history, reset)
│   ├── bydboxclient.py                  # Core Modbus client: data reading & decoding
│   ├── extmodbusclient.py               # Base Modbus TCP client (pymodbus wrapper)
│   ├── bydbox_const.py                  # Hardware constants, error/log code decoders
│   ├── manifest.json                    # HA integration metadata (version, requirements)
│   ├── translations/en.json             # UI strings (English)
│   ├── client_test.py                   # Minimal test file
│   └── logs/                            # Runtime log storage (JSON, CSV, TXT)
├── .github/workflows/
│   └── ci.yaml                          # All CI: lint, syntax, HACS, hassfest, mypy, version bump & release
├── images/                              # README screenshots (BMU, BMS, cells, balancing)
├── pyproject.toml                       # ruff + mypy configuration
├── hacs.json                            # HACS distribution config
├── README.md                            # User-facing documentation
├── LICENSE.md                           # Apache 2.0
└── .gitignore                           # Ignores: __pycache__, .DS_Store, .codegpt
```

## Architecture

### Data Flow

```
User Config (config_flow.py)
    → Hub initialization (__init__.py → hub.py)
        → BydBoxClient connects via Modbus TCP (bydboxclient.py → extmodbusclient.py)
            → Reads holding registers from battery
            → Decodes binary responses using bydbox_const.py
            → Populates self.data dict
        → Hub triggers periodic updates on 3 intervals
        → Sensor/Button entities read from hub.data
            → Home Assistant UI displays values
```

### Key Classes

| Class | File | Responsibility |
|---|---|---|
| `Hub` | `hub.py` | Central manager: creates client, schedules updates, manages entity lifecycle, provides device info |
| `BydBoxClient` | `bydboxclient.py` | Modbus communication: connects to battery, reads registers, decodes binary data, persists logs |
| `ExtModbusClient` | `extmodbusclient.py` | Base class: async Modbus TCP with retry logic, connection management, pymodbus compatibility |
| `BydBoxSensor` | `sensor.py` | HA sensor entity: displays measurement values, supports state restore, provides cell data as attributes |
| `BydBoxConnectionSensor` | `sensor.py` | HA sensor entity for connection health metrics (quality, latency, failures) |
| `BydBoxButton` | `button.py` | HA button entity: triggers log history fetch and cell voltage history reset |
| `ConfigFlow` | `config_flow.py` | HA config flow: validates user input (host, port, intervals), tests connection |
| `ConnectionHealthMonitor` | `bydboxclient.py` | Background async task: periodic latency measurement and connection quality tracking |

### Update Intervals (configurable via config flow)

| Data Type | Default Interval | Description |
|---|---|---|
| BMU Status | 30 seconds | Core battery data (voltage, current, SOC, SOH, temperature, power) |
| BMS Status | 10 minutes | Per-tower detailed data (cell voltages, temperatures, balancing) |
| Log Data | 10 minutes | Event/error log entries |

### Modbus Register Layout

- **Unit ID 0 (BMU):** Registers 2000-2100 for hardware info, 100-200 for real-time status
- **Unit ID 1-3 (BMS):** Registers 100-300 for per-tower data (cell voltages, temperatures, balancing)
- **Logs:** Registers 8000+ for event log with binary-encoded entries

## Sensor Types

### BMU Sensors (defined in `const.py` → `BMU_SENSOR_TYPES`)

Diagnostic: inverter, BMU/BMS versions, towers, modules, application, phase, errors, capacity, param table version, cells per module, temp sensors per module, timestamps, log entries.

Measurement: SOC (%), SOH (%), BMU temperature (C), cell temp min/max (C), cell voltage min/max (V), current (A), battery voltage (V), output voltage (V), power (W), charge/discharge total energy (kWh), efficiency (%).

### BMS Sensors (defined in `const.py` → `BMS_SENSOR_TYPES`)

Per-tower (up to 3 towers): cell voltage min/max (V) with cell IDs, cell temp min/max (C) with cell IDs, SOC (%), SOH (%), current (A), battery/output voltage (V), charge/discharge total energy (kWh), efficiency (%), cells balancing count, warnings, errors, average cell voltage (V), average cell temperature (C), max/min history cell voltage (V), balancing totals, timestamps, last log.

### Button Types (defined in `const.py` → `BMU_BUTTON_TYPES`)

- `update_log_history_100/500/1000/2000` - Fetch historical log entries
- `reset_history_cell_voltage` - Reset cell voltage history tracking

## Configuration Parameters

| Parameter | Default | Validation |
|---|---|---|
| Name | "BYD Battery Box" | Optional |
| Host (IP) | - | Required, min 3 chars |
| Port | 8080 | Required, 1-65535 |
| Unit ID | 1 | Required |
| BMU Scan Interval | 30s | Min 10s |
| BMS Scan Interval | 600s (10min) | Min 60s |
| Log Scan Interval | 600s (10min) | Min 120s |

## Version Management

Version is tracked in **three files** (all automatically updated by CI):
- `custom_components/byd_battery_box/manifest.json` - primary source of truth
- `pyproject.toml` - for tooling (ruff, mypy)
- `CLAUDE.md` - this file

On every push to `main`, after all CI checks pass, the `release` job automatically:
1. Increments the patch version (last digit) in all three files
2. Commits and tags the version bump (`v0.1.x`)
3. Creates a GitHub Release with a changelog of all commits since the last release

### Recursion Prevention (4 layers)

1. **GITHUB_TOKEN behavior** - Commits pushed by `github-actions[bot]` via `GITHUB_TOKEN` do NOT trigger new workflow runs (built-in GitHub protection)
2. **Commit message guard** - The release job skips if the commit message contains `[skip-version]` or `chore: bump version`
3. **Tag existence check** - Before bumping, checks if the target version tag already exists
4. **Commit tag check** - Checks if the current commit is already tagged with the current version

## CI/CD

All CI/CD is consolidated in a single workflow: `.github/workflows/ci.yaml`

### Jobs (on Pull Requests)

| Job | Blocking | Purpose |
|---|---|---|
| **Ruff Lint** | Yes | Syntax errors, undefined names, unused imports, code style (`pyproject.toml`) |
| **Python Syntax Check** | Yes | `py_compile` on all `.py` files |
| **HACS Validation** | Yes | Validates HACS metadata (`manifest.json`, `hacs.json`) |
| **Hassfest Validation** | Yes | Validates Home Assistant integration manifest |
| **MyPy Type Check** | No | Informational type checking (`continue-on-error: true`) |
| **Bandit Security Scan** | No | Security vulnerability scanning (`continue-on-error: true`) |

### Additional Job (on Push to main only)

| Job | Depends on | Purpose |
|---|---|---|
| **Version Bump & Release** | lint, syntax-check, hacs-validation, hassfest | Bumps patch version, creates git tag, publishes GitHub Release with changelog |

### Important: Fork-specific Notes

This repo is a fork of `redpomodoro/byd_battery_box`. GitHub disables Actions on forks by default. To enable:
1. Go to https://github.com/TimWeyand/byd_battery_box/settings/actions
2. Select "Allow all actions and reusable workflows"
3. Save

### Running Checks Locally

```bash
# Lint
pip install ruff
ruff check custom_components/

# Auto-fix lint issues
ruff check --fix custom_components/

# Syntax check
python -m py_compile custom_components/byd_battery_box/*.py

# Type check (informational)
pip install mypy
mypy custom_components/
```

## Log Data Storage

Log data is persisted to `custom_components/byd_battery_box/logs/`:
- `byd_logs.json` - Primary storage format
- `byd_logs.csv` - Convenience export
- `byd.log` - Text log

The `logs/` directory is created at runtime. Log entries contain timestamp, unit, code, description, and detail fields.

## Development Notes

### Known Issues in Code

- ~~`config_flow.py:123-126` has a bug~~ — **FIXED**: `InvalidPort` and `InvalidHost` exception handlers now have correct error keys
- ~~README sensor tables are empty ("To come!")~~ — **FIXED**: All sensor tables populated
- `client_test.py` is minimal, no comprehensive test suite exists
- `bydboxclient.py` — `get_log_list()` dict key renamed from duplicate `'data'` to `'hexdata'` for raw hex data

### Concurrency Safety

- `bydboxclient.py` uses a `ClientBusyLock` async context manager to prevent concurrent Modbus operations
- `hub.py` uses a `BusyLock` async context manager for the same purpose
- Hub manages multiple update timers that could overlap; the busy lock prevents conflicts
- `hub.close()` is async — stops the `ConnectionHealthMonitor` task before disconnecting the client
- `ConnectionHealthMonitor.stop_monitoring()` is async — properly awaits task cancellation with `CancelledError` handling

### Binary Data Handling

- Modbus responses are decoded using custom binary parsing in `bydboxclient.py` and `bydbox_const.py`
- BMU/BMS log codes (0x00-0x7F) are mapped to human-readable descriptions
- Cell data is structured as nested arrays: modules -> cells -> voltages/temperatures

## References

- https://github.com/sarnau/BYD-Battery-Box-Infos/blob/main/Read_Modbus.py
- https://github.com/christianh17/ioBroker.bydhvs/blob/master/docs/byd-hexstructure.md
- https://github.com/smarthomeNG/plugins/tree/develop/byd_bat
