# Design: `wnsm.import_statistics` HA Action

**Date:** 2026-04-13

## Overview

Add a Home Assistant action (service) `wnsm.import_statistics` that allows users to manually trigger a data import for a specific date range and a specific Zählpunkt. This enables backfilling or repairing historical energy data via the Developer Tools UI.

## Service Definition

**Service ID:** `wnsm.import_statistics`

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `zaehlpunkt` | `string` | yes | — | The Zählpunkt number to import for (e.g. `AT0010000000000000001000012345678`) |
| `start_date` | `date` | yes | — | First day of the range to import |
| `end_date` | `date` | no | today | Last day of the range to import (inclusive) |

Declared in `services.yaml` so it renders with field labels and descriptions in the HA Developer Tools UI.

## Architecture

### New file: `custom_components/wnsm/services.py`

- `async_setup_services(hass)` — registers the `import_statistics` service with its voluptuous schema
- `async_handle_import_statistics(call)` — the service handler:
  1. Reads `zaehlpunkt`, `start_date`, `end_date` from the service call data
  2. Converts `date` → timezone-aware `datetime`: `start_date` maps to midnight UTC of that day; `end_date` maps to midnight UTC of the **following** day (so `end_date` is inclusive — all data on that day is captured)
  3. Searches `hass.data[DOMAIN]` across all config entries to find credentials for the requested zaehlpunkt
  4. Raises `ServiceValidationError` if no matching config entry is found
  5. Queries the recorder for the last known stat **before** `start_date` to retrieve the running cumulative sum (ensures energy dashboard integrity)
  6. Constructs `Smartmeter` → `AsyncSmartmeter` → `Importer`, then calls `_import_statistics(start, end, total_usage)` directly — bypassing the normal 24h recency guard used in the automatic update flow
  7. Uses `ValueType.QUARTER_HOUR` as granularity (same default as the sensor; not exposed as a parameter)

### Modified file: `custom_components/wnsm/__init__.py`

- Calls `await async_setup_services(hass)` inside `async_setup_entry`
- Guarded with a flag (e.g. checking `hass.services.has_service(DOMAIN, "import_statistics")`) so the service is only registered once even when multiple config entries exist

### New file: `custom_components/wnsm/services.yaml`

- Declares the service with a description, and field-level labels/descriptions/examples for each parameter
- Makes the service discoverable and user-friendly in Developer Tools → Actions

### Unchanged: `custom_components/wnsm/importer.py`

- `_import_statistics(start, end, total_usage)` already accepts all required parameters — no changes needed

## Data Flow

```
Developer Tools → wnsm.import_statistics
    ↓
async_handle_import_statistics(call)
    ↓
Look up credentials from hass.data[DOMAIN]
    ↓
Query recorder: last stat before start_date → get cumulative sum
    ↓
Importer._import_statistics(start, end, total_usage=cumulative_sum)
    ↓
API call → Wiener Netze bewegungsdaten
    ↓
async_add_external_statistics → HA recorder
```

## Error Handling

| Scenario | Behaviour |
|---|---|
| Zählpunkt not found in any config entry | `ServiceValidationError` — shown as HA UI notification |
| `end_date` before `start_date` | Rejected by voluptuous schema before handler runs |
| No prior stat before `start_date` | Cumulative sum starts at `Decimal(0)` — correct for initial import |
| API timeout or runtime error | Existing `try/except` in `_import_statistics` logs a warning; no crash |
| Date range entirely in the future | Existing `start > end` guard in `_import_statistics` logs a warning and returns |

## Out of Scope

- Exposing granularity as a service parameter
- Targeting multiple zaehlpunkte in one call
- Deleting/replacing existing stats before re-import (HA's `async_add_external_statistics` updates in place)
