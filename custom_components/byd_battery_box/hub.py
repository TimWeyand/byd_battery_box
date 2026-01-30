"""BYD Battery Box Hub."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from packaging import version as pkg_version

from .bydboxclient import BydBoxClient
from .const import ATTR_MANUFACTURER, DEVICE_TYPES, DOMAIN

_LOGGER = logging.getLogger(__name__)

class Hub:
    """Hub for BYD Battery Box Interface"""

    PYMODBUS_VERSION = '3.11.2'

    def __init__(self, hass: HomeAssistant, name: str, host: str, port: int, unit_id: int, scan_interval: int, scan_interval_bms: int = 600, scan_interval_log: int = 600) -> None:
        """Init hub."""
        self._hass = hass
        self._name = name
        self._id = f'{name.lower()}_{host.lower().replace('.','')}'
        self._last_full_update = datetime(2000,1,1)
        self._last_log_update = datetime(2000,1,1)
        self._last_update = datetime(2000,1,1)
        self._unsub_interval_method = None
        self._entities = []
        self._min_update_interval = timedelta(seconds=1)
        self._scan_interval = timedelta(seconds=scan_interval)
        self._scan_interval_bms = timedelta(seconds=scan_interval_bms)
        self._scan_interval_log = timedelta(seconds=scan_interval_log)
        self._bydclient = BydBoxClient(host=host, port=port, unit_id=unit_id, timeout=max(3, (scan_interval - 1)))
        self.online = True
        self._busy = False
        self._update_log_history_depth = [0,0]

    class BusyLock:
        """Async context manager for managing busy state."""

        def __init__(self, hub):
            self.hub = hub

        async def __aenter__(self):
            while self.hub._busy:
                await asyncio.sleep(0.1)
            self.hub._busy = True
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            self.hub._busy = False


    @property
    def data(self):
        return self._bydclient.data

    @property
    def device_info_bmu(self) -> dict:
        return {
            "identifiers": {(DOMAIN, f'{self._name}_byd_bmu')},
            "name": 'Battery Management Unit',
            "manufacturer": ATTR_MANUFACTURER,
            "model": self._bydclient.data.get('model'),
            "serial_number": self._bydclient.data.get('serial'),
            "sw_version": self._bydclient.data.get('bmu_v'),
        }

    def get_device_info_bms(self,id) -> dict:
        return {
            "identifiers": {(DOMAIN, f'{self._name}_byd_bms_{id}')},
            "name": f'Battery Management System {id}',
            "manufacturer": ATTR_MANUFACTURER,
            "model": self._bydclient.data.get('model'),
            #"serial_number": self._bydclient.data.get('serial'),
            "sw_version": self._bydclient.data.get('bms_v'),
        }

    @property
    def hub_id(self) -> str:
        """ID for hub."""
        return self._id

    @callback
    def async_add_hub_entity(self, update_callback):
        """Listen for data updates."""
        # This is the first entity, set up interval.
        if not self._entities:
            self._unsub_interval_method = async_track_time_interval(
                self._hass, self.async_update_data, self._scan_interval
            )
        self._entities.append(update_callback)

    @callback
    def async_remove_hub_entity(self, update_callback):
        """Remove data update."""
        self._entities.remove(update_callback)

        if not self._entities:
            """stop the interval timer upon removal of last entity"""
            self._unsub_interval_method()
            self._unsub_interval_method = None
            asyncio.create_task(self.close())

    async def init_data(self, close = False):
        async with self.BusyLock(self):
            await self._hass.async_add_executor_job(self.check_pymodbus_version)
            await self._hass.async_add_executor_job(self._bydclient.update_log_from_file)
            await self._bydclient.init_data(close = close)
            # Start connection health monitoring
            self._bydclient.health_monitor.start_monitoring()
            self.update_entities()

    def check_pymodbus_version(self):
        try:
            current_version = version('pymodbus')
        except PackageNotFoundError:
            _LOGGER.error("pymodbus is not installed")
            raise

        try:
            current = pkg_version.parse(current_version)
            required = pkg_version.parse(self.PYMODBUS_VERSION)
        except Exception as e:
            _LOGGER.error(f"Error parsing pymodbus version string: {e}")
            raise

        if current < required:
            raise Exception(f"pymodbus {current_version} found, please update to {self.PYMODBUS_VERSION} or higher")
        elif current > required:
            _LOGGER.warning(f"newer pymodbus {current_version} found")
        _LOGGER.debug(f"pymodbus {current_version}")

    async def async_update_data(self, _now: int | None = None) -> dict:
        """Time to update."""
        if not self._bydclient.initialized:
            return

        if ((datetime.now()-self._last_update) < self._min_update_interval):
            #_LOGGER.debug(f"Skip update give system a break ;-)")
            return

        async with self.BusyLock(self):
            # update log history
            unit_id = self._update_log_history_depth[0]
            log_depth = self._update_log_history_depth[1]
            if self._update_log_history_depth[1] > 0:
                prev_len_log = len(self._bydclient.log)
                _LOGGER.warning(f"Started loading {DEVICE_TYPES[unit_id]} log history; all other data updates will be suspended!")
                try:
                    await self._bydclient.update_log_data(unit_id, log_depth=log_depth)
                    self._last_log_update = datetime.now()
                    self._last_update = datetime.now()
                except Exception as e:
                    _LOGGER.error(f'Failed updating {DEVICE_TYPES[unit_id]} log history {self._update_log_history_depth} {e}', exc_info=True)
                    return False
                self._update_log_history_depth[1] = 0
                if prev_len_log != len(self._bydclient.log):
                    result : bool = await self._hass.async_add_executor_job(self._bydclient.save_log_entries)
                return True

            # update last log data
            if ((datetime.now()-self._last_log_update) > self._scan_interval_log):
                #_LOGGER.debug(f"start update log data")
                prev_len_log = len(self._bydclient.log)
                result = await self._bydclient.update_all_log_data()
                self._last_log_update = datetime.now()
                self._last_update = datetime.now()
                if result:
                    self.update_entities()
                    if prev_len_log != len(self._bydclient.log):
                        result : bool = await self._hass.async_add_executor_job(self._bydclient.save_log_entries)
                    _LOGGER.debug("updated log data")
                else:
                    _LOGGER.error("update log data failed")
                    await asyncio.sleep(5)

            # update bms data
            if ((datetime.now()-self._last_full_update) > self._scan_interval_bms):
                #_LOGGER.debug(f"start update BMS status")
                result = await self._bydclient.update_all_bms_status_data()
                if result:
                    self._last_full_update = datetime.now()
                    self._last_update = datetime.now()
                    self.update_entities()
                    _LOGGER.debug("updated BMS status")
                else:
                    _LOGGER.error("update BMS status data failed")
                    await asyncio.sleep(5)

            # update bmu
            try:
                #_LOGGER.debug(f"start update BMU status")
                result = await self._bydclient.update_bmu_status_data()
            except Exception as e:
                _LOGGER.error(f"Error reading BMU status data connection {self._bydclient.connected} error: {e} ", exc_info=True)
                return False
            if result:
                self._last_update = datetime.now()
                self.update_entities()
                _LOGGER.debug("updated BMU status")
            else:
                _LOGGER.warning(f"update BMU status data failed {self._bydclient.connected}")
                return False

            return True

    def update_entities(self):
        for update_callback in self._entities:
            update_callback()

    async def close(self):
        """Disconnect client."""
        await self._bydclient.health_monitor.stop_monitoring()
        self._bydclient.close()
        _LOGGER.debug("close hub")

    async def test_connection(self) -> bool:
        """Test connectivity"""
        _LOGGER.debug("test connection")
        try:
            return await self._bydclient.connect()
        except Exception:
            _LOGGER.exception("Error connecting to the device")
            return False

    def start_update_log_history(self, unit_id, log_depth):
         _LOGGER.info(f"Scheduled {DEVICE_TYPES[unit_id]} log update for up to {log_depth*20} log entries.")
         self._update_log_history_depth = [unit_id, log_depth]

    def reset_history_cell_voltage(self, unit_id:int):
         """Reset stored per-cell min/max history for one BMS or all (unit_id=0)."""
         if unit_id == 0:
             ids = range(1, self._bydclient._bms_qty + 1)
         else:
             ids = [unit_id]
         for bms_id in ids:
             for suffix in [
                 '_max_history_cell_voltage',
                 '_max_history_cell_voltage_cells',
                 '_min_history_cell_voltage',
                 '_min_history_cell_voltage_cells',
             ]:
                 key = f'bms{bms_id}{suffix}'
                 if key in self._bydclient.data:
                     try:
                         del self._bydclient.data[key]
                     except Exception:
                         self._bydclient.data[key] = None
         self.update_entities()
