"""Set up the Wiener Netze SmartMeter Integration component."""
from homeassistant import core, config_entries
from homeassistant.core import DOMAIN

from .services import async_setup_services


async def async_setup_entry(
        hass: core.HomeAssistant,
        entry: config_entries.ConfigEntry
) -> bool:
    """Set up platform from a ConfigEntry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Forward the setup to the sensor platform.
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    # Register integration-level services (no-op if already registered).
    await async_setup_services(hass)

    return True
