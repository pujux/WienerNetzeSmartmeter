"""Service definitions for the Wiener Netze Smart Meter integration."""
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from .AsyncSmartmeter import AsyncSmartmeter
from .api import Smartmeter
from .api.constants import ValueType
from .const import CONF_ZAEHLPUNKTE, DOMAIN
from .importer import Importer

_LOGGER = logging.getLogger(__name__)

SERVICE_IMPORT_STATISTICS = "import_statistics"

_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("zaehlpunkt"): cv.string,
        vol.Required("start_date"): cv.date,
        vol.Optional("end_date"): cv.date,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration-level services. Safe to call multiple times."""
    if hass.services.has_service(DOMAIN, SERVICE_IMPORT_STATISTICS):
        return

    async def _handle_import_statistics(call: ServiceCall) -> None:
        zaehlpunkt: str = call.data["zaehlpunkt"]
        start_date: date = call.data["start_date"]
        end_date: date = call.data.get("end_date", date.today())

        # Convert inclusive date range to exclusive-end UTC datetimes
        start = datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
        )
        end = (
            datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc)
            + timedelta(days=1)
        )

        # Locate credentials for this zaehlpunkt across all config entries
        username: str | None = None
        password: str | None = None
        for entry in hass.config_entries.async_entries(DOMAIN):
            entry_data = entry.data
            if any(
                zp.get("zaehlpunktnummer") == zaehlpunkt
                for zp in entry_data.get(CONF_ZAEHLPUNKTE, [])
            ):
                username = entry_data[CONF_USERNAME]
                password = entry_data[CONF_PASSWORD]
                break

        if username is None:
            raise ServiceValidationError(
                f"Zählpunkt '{zaehlpunkt}' was not found in any configured integration entry."
            )

        # Fetch the running cumulative sum just before start so the energy
        # dashboard total stays correct when inserting mid-range data.
        statistic_id = f"{DOMAIN}:{zaehlpunkt.lower()}"
        prior_stats = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            datetime(2000, 1, 1, tzinfo=timezone.utc),
            start,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        if (
            prior_stats
            and statistic_id in prior_stats
            and prior_stats[statistic_id]
        ):
            total_usage = Decimal(str(prior_stats[statistic_id][-1]["sum"]))
        else:
            total_usage = Decimal(0)

        _LOGGER.info(
            "Manual import triggered: zaehlpunkt=%s start=%s end=%s prior_sum=%s",
            zaehlpunkt,
            start,
            end,
            total_usage,
        )

        smartmeter = Smartmeter(username=username, password=password)
        async_smartmeter = AsyncSmartmeter(hass, smartmeter)
        await async_smartmeter.login()
        importer = Importer(
            hass,
            async_smartmeter,
            zaehlpunkt,
            UnitOfEnergy.KILO_WATT_HOUR,
            ValueType.QUARTER_HOUR,
        )
        await importer._import_statistics(start=start, end=end, total_usage=total_usage)

    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_STATISTICS,
        _handle_import_statistics,
        schema=_SERVICE_SCHEMA,
    )
