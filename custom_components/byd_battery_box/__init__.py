"""The BYD Battery Box integration."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from . import hub
from .const import CONF_BMS_SCAN_INTERVAL, CONF_LOG_SCAN_INTERVAL, CONF_UNIT_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)

# List of platforms to support. There should be a matching .py file for each,
# eg <cover.py> and <sensor.py>
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

type HubConfigEntry = ConfigEntry[hub.Hub]

async def async_setup_entry(hass: HomeAssistant, entry: HubConfigEntry) -> bool:
    """Set up BYD Battery Box from a config entry."""

    # address and intervals can be changed later in the integration's options; options win over the original setup
    settings = {**entry.data, **entry.options}
    name = entry.data[CONF_NAME]
    host = settings[CONF_HOST]
    port = settings[CONF_PORT]
    unit_id = entry.data.get(CONF_UNIT_ID, 1)
    scan_interval = settings[CONF_SCAN_INTERVAL]
    scan_interval_bms = settings[CONF_BMS_SCAN_INTERVAL]
    scan_interval_log = settings[CONF_LOG_SCAN_INTERVAL]

    _LOGGER.debug("Setup %s.%s", DOMAIN, name)

    # Store an instance of the "connecting" class that does the work of speaking
    # with your actual devices.
    entry.runtime_data = hub.Hub(hass = hass, name = name, host = host, port = port, unit_id=unit_id, scan_interval = scan_interval, scan_interval_bms = scan_interval_bms, scan_interval_log=scan_interval_log)

    try:
        await entry.runtime_data.init_data()
    except Exception as err:
        await entry.runtime_data.close(final=True)
        # the BMU accepts one client; if it is still busy (or offline), HA retries the setup later
        raise ConfigEntryNotReady(f"BYD BMU at {host}:{port} not ready: {err}") from err

    # This creates each HA object for each platform your device requires.
    # It's done by calling the `async_setup_entry` function in each platform module.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True

async def _async_options_updated(hass: HomeAssistant, entry: HubConfigEntry) -> None:
    """Apply changed intervals by reloading the entry."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        # Close the Modbus connection now (not in a background task): the BMU accepts only one client,
        # so a reload that connects before the old connection is gone fails to set up.
        await entry.runtime_data.close(final=True)
        await asyncio.sleep(1)

    return unload_ok


