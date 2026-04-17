import logging
import math
from datetime import datetime, timedelta
from typing import Any, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    ENTITY_ID_FORMAT
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfEnergy
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .AsyncSmartmeter import AsyncSmartmeter
from .api import Smartmeter
from .api.constants import ValueType
from .const import DEFAULT_SCAN_INTERVAL, DEFAULT_START_TIME
from .importer import Importer
from .utils import before, today

_LOGGER = logging.getLogger(__name__)


def next_scheduled_time(start_time: str, interval_hours: int) -> datetime:
    now = dt_util.now()
    h, m = map(int, start_time.split(":"))
    start_today = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if start_today > now:
        return start_today
    elapsed_secs = (now - start_today).total_seconds()
    interval_secs = timedelta(hours=interval_hours).total_seconds()
    n = math.ceil(elapsed_secs / interval_secs)
    return start_today + timedelta(hours=interval_hours) * max(n, 1)


class WNSMSensor(SensorEntity):
    """
    Representation of a Wiener Smartmeter sensor
    for measuring total increasing energy consumption for a specific zaehlpunkt
    """

    def _icon(self) -> str:
        return "mdi:flash"

    def __init__(self, username: str, password: str, zaehlpunkt: str, scan_interval_hours: int = DEFAULT_SCAN_INTERVAL, start_time: str = DEFAULT_START_TIME) -> None:
        super().__init__()
        self.username = username
        self.password = password
        self.zaehlpunkt = zaehlpunkt
        self._scan_interval_hours = scan_interval_hours
        self._start_time = start_time

        self._attr_native_value: int | float | None = 0
        self._attr_extra_state_attributes = {}
        self._attr_name = zaehlpunkt
        self._attr_icon = self._icon()
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

        self.attrs: dict[str, Any] = {}
        self._name: str = zaehlpunkt
        self._available: bool = True
        self._updatets: str | None = None
        self._unsub_update = None

    @property
    def get_state(self) -> Optional[str]:
        return f"{self._attr_native_value:.3f}"

    @property
    def _id(self):
        return ENTITY_ID_FORMAT.format(slugify(self._name).lower())

    @property
    def icon(self) -> str:
        return self._attr_icon

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return self.zaehlpunkt

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    def granularity(self) -> ValueType:
        return ValueType.from_str(self._attr_extra_state_attributes.get("granularity", "QUARTER_HOUR"))

    async def async_added_to_hass(self) -> None:
        self._schedule_next_update()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub_update:
            self._unsub_update()
            self._unsub_update = None

    def _schedule_next_update(self) -> None:
        if self._unsub_update:
            self._unsub_update()
        next_time = next_scheduled_time(self._start_time, self._scan_interval_hours)
        self._unsub_update = async_track_point_in_time(
            self.hass, self._scheduled_update, next_time
        )

    async def _scheduled_update(self, now: datetime) -> None:
        await self.async_update()
        self.async_write_ha_state()
        self._schedule_next_update()

    async def async_update(self):
        """
        update sensor
        """
        try:
            smartmeter = Smartmeter(username=self.username, password=self.password)
            async_smartmeter = AsyncSmartmeter(self.hass, smartmeter)
            await async_smartmeter.login()
            zaehlpunkt_response = await async_smartmeter.get_zaehlpunkt(self.zaehlpunkt)
            self._attr_extra_state_attributes = zaehlpunkt_response

            if async_smartmeter.is_active(zaehlpunkt_response):
                # Since the update is not exactly at midnight, both yesterday and the day before are tried to make sure a meter reading is returned
                reading_dates = [before(today(), 1), before(today(), 2)]
                for reading_date in reading_dates:
                    meter_reading = await async_smartmeter.get_meter_reading_from_historic_data(self.zaehlpunkt, reading_date, datetime.now())
                    self._attr_native_value = meter_reading
                importer = Importer(self.hass, async_smartmeter, self.zaehlpunkt, self.unit_of_measurement, self.granularity())
                await importer.async_import()
            self._available = True
            self._updatets = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        except TimeoutError as e:
            self._available = False
            _LOGGER.warning(
                "Error retrieving data from smart meter api - Timeout: %s" % e)
        except RuntimeError as e:
            self._available = False
            _LOGGER.exception(
                "Error retrieving data from smart meter api - Error: %s" % e)
