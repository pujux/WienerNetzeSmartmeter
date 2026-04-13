# `wnsm.import_statistics` Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `wnsm.import_statistics` HA service that lets users re-import energy statistics for a specific Zählpunkt and date range from Developer Tools.

**Architecture:** A new `services.py` module registers a single `wnsm.import_statistics` service on integration load (guarded against duplicate registration). The handler resolves credentials from `hass.data`, fetches the cumulative sum from the recorder just before the requested start date, then calls `Importer._import_statistics()` directly with the provided date range — bypassing the normal 24-hour recency guard. A `services.yaml` descriptor makes the service discoverable and user-friendly in Developer Tools → Actions.

**Tech Stack:** Python 3.10, Home Assistant 2026.4, `homeassistant.components.recorder.statistics`, `voluptuous`, `pytest-homeassistant-custom-component==0.13.322`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `custom_components/wnsm/services.py` | Service registration + handler |
| Create | `custom_components/wnsm/services.yaml` | Developer Tools UI descriptor |
| Modify | `custom_components/wnsm/__init__.py` | Wire `async_setup_services` |
| Create | `tests/test_services.py` | Unit tests for service handler |

---

### Task 1: Write failing tests for the service handler

**Files:**
- Create: `tests/test_services.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for wnsm services."""
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import DOMAIN as HA_DOMAIN, HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.wnsm.const import CONF_ZAEHLPUNKTE, DOMAIN
from custom_components.wnsm.services import async_setup_services

ZAEHLPUNKT = "AT0010000000000000001000012345678"
STATISTIC_ID = f"{DOMAIN}:{ZAEHLPUNKT.lower()}"


@pytest.fixture()
def mock_config(hass: HomeAssistant):
    """Populate hass.data with a fake config entry for ZAEHLPUNKT."""
    hass.data.setdefault(HA_DOMAIN, {})
    hass.data[HA_DOMAIN]["test_entry"] = {
        CONF_USERNAME: "user@example.com",
        CONF_PASSWORD: "secret",
        CONF_ZAEHLPUNKTE: [{"zaehlpunktnummer": ZAEHLPUNKT}],
    }


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
```

- [ ] **Step 2: Run tests — verify they all FAIL**

```bash
cd /Users/julian/Projects/WienerNetzeSmartmeter && python -m pytest tests/test_services.py -v -p no:cov 2>&1 | head -40
```

Expected: `ImportError` or `ModuleNotFoundError` — `custom_components.wnsm.services` does not exist yet.

---

### Task 2: Implement `services.py`

**Files:**
- Create: `custom_components/wnsm/services.py`

- [ ] **Step 1: Create `services.py`**

```python
"""Service definitions for the Wiener Netze Smart Meter integration."""
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, UnitOfEnergy
from homeassistant.core import DOMAIN as HA_DOMAIN, HomeAssistant, ServiceCall
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
        for entry_data in hass.data.get(HA_DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
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
```

- [ ] **Step 2: Run tests — verify they all PASS**

```bash
cd /Users/julian/Projects/WienerNetzeSmartmeter && python -m pytest tests/test_services.py -v -p no:cov
```

Expected output:
```
tests/test_services.py::test_service_is_registered PASSED
tests/test_services.py::test_service_registered_only_once PASSED
tests/test_services.py::test_service_raises_for_unknown_zaehlpunkt PASSED
tests/test_services.py::test_service_calls_import_with_correct_datetimes PASSED
tests/test_services.py::test_service_uses_prior_sum_as_starting_total PASSED
tests/test_services.py::test_service_end_date_defaults_to_today PASSED
6 passed
```

If any test fails, read the error message and fix `services.py` before continuing. Do not proceed to the next task until all 6 pass.

- [ ] **Step 3: Commit**

```bash
git add custom_components/wnsm/services.py tests/test_services.py
git commit -m "feat: add wnsm.import_statistics service with tests"
```

---

### Task 3: Add `services.yaml`

**Files:**
- Create: `custom_components/wnsm/services.yaml`

- [ ] **Step 1: Create `services.yaml`**

```yaml
import_statistics:
  name: Import Statistics
  description: >
    Manually import energy statistics for a specific Zählpunkt and date range
    from the Wiener Netze API. Use this to backfill or repair historical data
    in the Energy dashboard.
  fields:
    zaehlpunkt:
      name: Zählpunkt
      description: The Zählpunkt number to import data for.
      required: true
      example: "AT0010000000000000001000012345678"
      selector:
        text:
    start_date:
      name: Start Date
      description: First day of the range to import (inclusive).
      required: true
      example: "2024-01-01"
      selector:
        date:
    end_date:
      name: End Date
      description: >
        Last day of the range to import (inclusive).
        Defaults to today if not provided.
      required: false
      example: "2024-03-31"
      selector:
        date:
```

- [ ] **Step 2: Verify the file looks correct**

```bash
cat custom_components/wnsm/services.yaml
```

Expected: the YAML above printed to stdout with no parse errors.

- [ ] **Step 3: Commit**

```bash
git add custom_components/wnsm/services.yaml
git commit -m "feat: add services.yaml descriptor for import_statistics"
```

---

### Task 4: Wire up services in `__init__.py`

**Files:**
- Modify: `custom_components/wnsm/__init__.py`

The current `__init__.py` is:

```python
"""Set up the Wiener Netze SmartMeter Integration component."""
from homeassistant import core, config_entries
from homeassistant.core import DOMAIN


async def async_setup_entry(
        hass: core.HomeAssistant,
        entry: config_entries.ConfigEntry
) -> bool:
    """Set up platform from a ConfigEntry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data

    # Forward the setup to the sensor platform.
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    return True
```

- [ ] **Step 1: Add the `async_setup_services` call**

```python
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
```

- [ ] **Step 2: Run the full test suite to check for regressions**

```bash
cd /Users/julian/Projects/WienerNetzeSmartmeter && python -m pytest tests/ -v -p no:cov
```

Expected: all previously passing tests still pass, all 6 service tests pass.

- [ ] **Step 3: Commit**

```bash
git add custom_components/wnsm/__init__.py
git commit -m "feat: wire async_setup_services into async_setup_entry"
```

---

## Verification Checklist

After all tasks complete:

- [ ] `hass.services.has_service("wnsm", "import_statistics")` returns `True` when integration loads
- [ ] Calling with an unknown zaehlpunkt raises `ServiceValidationError` (visible as HA notification)
- [ ] Calling with `start_date` and no `end_date` defaults to today
- [ ] `end_date` is treated as inclusive (internally converted to start of next day)
- [ ] Prior cumulative sum is fetched from recorder before inserting — energy dashboard total is not corrupted
- [ ] All 6 unit tests pass
- [ ] `services.yaml` descriptor is present so the service shows in Developer Tools → Actions with field descriptions
