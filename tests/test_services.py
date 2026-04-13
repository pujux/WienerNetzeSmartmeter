"""Tests for wnsm services."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.wnsm.const import CONF_ZAEHLPUNKTE, DOMAIN
from custom_components.wnsm.services import async_setup_services

ZAEHLPUNKT = "AT0010000000000000001000012345678"
STATISTIC_ID = f"{DOMAIN}:{ZAEHLPUNKT.lower()}"


@pytest.fixture()
def mock_config(hass: HomeAssistant):
    """Mock config entries so the service can find credentials for ZAEHLPUNKT."""
    mock_entry = MagicMock()
    mock_entry.data = {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "secret",
        CONF_ZAEHLPUNKTE: [{"zaehlpunktnummer": ZAEHLPUNKT}],
    }
    hass.config_entries.async_entries = MagicMock(return_value=[mock_entry])


async def test_service_is_registered(hass: HomeAssistant):
    """async_setup_services registers wnsm.import_statistics."""
    await async_setup_services(hass)
    assert hass.services.has_service(DOMAIN, "import_statistics")


async def test_service_registered_only_once(hass: HomeAssistant):
    """Calling async_setup_services twice does not error or double-register."""
    await async_setup_services(hass)
    await async_setup_services(hass)
    assert hass.services.has_service(DOMAIN, "import_statistics")


async def test_service_raises_for_unknown_zaehlpunkt(
    hass: HomeAssistant, mock_config
):
    """ServiceValidationError is raised when zaehlpunkt is not in any config entry."""
    await async_setup_services(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "import_statistics",
            {"zaehlpunkt": "UNKNOWN123", "start_date": date(2024, 1, 1)},
            blocking=True,
        )


async def test_service_calls_import_with_correct_datetimes(
    hass: HomeAssistant, mock_config
):
    """Handler converts start_date/end_date to correct UTC datetimes.

    start_date=2024-01-01 → datetime(2024, 1, 1, tzinfo=utc)
    end_date=2024-01-02   → datetime(2024, 1, 3, tzinfo=utc)  (exclusive upper bound)
    """
    expected_start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    expected_end = datetime(2024, 1, 3, tzinfo=timezone.utc)

    await async_setup_services(hass)

    with patch("custom_components.wnsm.services.get_instance") as mock_gi, \
         patch("custom_components.wnsm.services.AsyncSmartmeter") as mock_asm_cls, \
         patch("custom_components.wnsm.services.Importer") as mock_importer_cls:

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})
        mock_gi.return_value = mock_recorder

        mock_asm = MagicMock()
        mock_asm.login = AsyncMock()
        mock_asm_cls.return_value = mock_asm

        mock_importer = MagicMock()
        mock_importer._import_statistics = AsyncMock(return_value=Decimal("10"))
        mock_importer_cls.return_value = mock_importer

        await hass.services.async_call(
            DOMAIN,
            "import_statistics",
            {
                "zaehlpunkt": ZAEHLPUNKT,
                "start_date": date(2024, 1, 1),
                "end_date": date(2024, 1, 2),
            },
            blocking=True,
        )

    mock_importer._import_statistics.assert_called_once_with(
        start=expected_start,
        end=expected_end,
        total_usage=Decimal(0),
    )


async def test_service_uses_prior_sum_as_starting_total(
    hass: HomeAssistant, mock_config
):
    """Handler reads prior cumulative sum from recorder and passes it to _import_statistics."""
    prior_sum = Decimal("500.123")

    await async_setup_services(hass)

    with patch("custom_components.wnsm.services.get_instance") as mock_gi, \
         patch("custom_components.wnsm.services.AsyncSmartmeter") as mock_asm_cls, \
         patch("custom_components.wnsm.services.Importer") as mock_importer_cls:

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(
            return_value={STATISTIC_ID: [{"sum": float(prior_sum)}]}
        )
        mock_gi.return_value = mock_recorder

        mock_asm = MagicMock()
        mock_asm.login = AsyncMock()
        mock_asm_cls.return_value = mock_asm

        mock_importer = MagicMock()
        mock_importer._import_statistics = AsyncMock(
            return_value=prior_sum + Decimal("10")
        )
        mock_importer_cls.return_value = mock_importer

        await hass.services.async_call(
            DOMAIN,
            "import_statistics",
            {"zaehlpunkt": ZAEHLPUNKT, "start_date": date(2024, 3, 1)},
            blocking=True,
        )

    call_kwargs = mock_importer._import_statistics.call_args.kwargs
    assert call_kwargs["total_usage"] == prior_sum


async def test_service_end_date_defaults_to_today(
    hass: HomeAssistant, mock_config
):
    """When end_date is omitted, end datetime is midnight UTC at start of tomorrow."""
    today = date.today()
    expected_end = datetime(today.year, today.month, today.day, tzinfo=timezone.utc) + timedelta(days=1)

    await async_setup_services(hass)

    with patch("custom_components.wnsm.services.get_instance") as mock_gi, \
         patch("custom_components.wnsm.services.AsyncSmartmeter") as mock_asm_cls, \
         patch("custom_components.wnsm.services.Importer") as mock_importer_cls:

        mock_recorder = MagicMock()
        mock_recorder.async_add_executor_job = AsyncMock(return_value={})
        mock_gi.return_value = mock_recorder

        mock_asm = MagicMock()
        mock_asm.login = AsyncMock()
        mock_asm_cls.return_value = mock_asm

        mock_importer = MagicMock()
        mock_importer._import_statistics = AsyncMock(return_value=Decimal("0"))
        mock_importer_cls.return_value = mock_importer

        await hass.services.async_call(
            DOMAIN,
            "import_statistics",
            {"zaehlpunkt": ZAEHLPUNKT, "start_date": today},
            blocking=True,
        )

    call_kwargs = mock_importer._import_statistics.call_args.kwargs
    assert call_kwargs["end"] == expected_end
