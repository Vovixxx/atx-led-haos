# Unsigned Driver Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Home Assistant one-time-tune leftover unsigned DALI drivers (empty `dev_type`, zero serial/firmware) with a Configure form for mode, dim range, and Kelvin ends, without writing config to the hub.

**Architecture:** Classify unsigned fixtures at parse time. Store per-device overrides on the hub config entry options. After each inventory poll, merge those overrides onto unsigned `LightDevice` records only, then run existing group CCT derivation. An options flow lists unsigned leftovers and reloads the entry so light color modes refresh. RGB mode may be stored; the light entity still does not expose an RGB picker.

**Tech Stack:** Home Assistant custom integration (`custom_components/atx_led`), pytest without Home Assistant for model/client tests, voluptuous options flow.

## Global Constraints

- Overrides are Home Assistant-only. Never POST min/max, mode, or color config to the driver or hub.
- Apply overrides only when `LightDevice.unsigned` is true. Known DT8 fixtures keep hub flags and ranges even if options contain their id.
- Unsigned with no override stay brightness-only using hub min/max.
- Classifier: `dev_type` missing/empty/`0` AND `serial_nb` missing/`0` AND `fw_version` missing/`0`. Do not classify from status `03` or names.
- Modes: `dimmer`, `cct`, `rgb`, `rgb_cct`. RGB picker and RGB writes are out of scope.
- Brightness mapping stays `(raw - min) / (max - min)`. Override min `50` is HA 1%.
- Unique entity ids do not change.
- Do not change lights during tests unless a later live-verify step is explicitly approved.
- Tests run with: `.venv/bin/pytest tests -q` (or `python3.12 -m pytest tests -q`).

## File structure

- Create: `custom_components/atx_led/unsigned.py` — classifier helpers live next to parse in `models.py`; this module owns override validation, apply, option merge, and form defaults.
- Modify: `custom_components/atx_led/models.py` — `unsigned` / `unsigned_mode` on `LightDevice`; `is_unsigned_driver()`; set flag in `parse_device`.
- Modify: `custom_components/atx_led/const.py` — option and mode constants.
- Modify: `custom_components/atx_led/coordinator.py` — apply overrides before group derivation.
- Modify: `custom_components/atx_led/__init__.py` — reload on options update.
- Modify: `custom_components/atx_led/config_flow.py` — options flow.
- Modify: `custom_components/atx_led/strings.json` and `translations/en.json`.
- Modify: `custom_components/atx_led/diagnostics.py` — unsigned fields.
- Modify: `custom_components/atx_led/manifest.json` — version `0.4.0`.
- Test: `tests/test_unsigned.py` (new). Existing `tests/test_models.py` / `tests/test_groups.py` should keep passing.
- Docs: `README.md`, `outputs/integration-notes/SETUP-AND-ENTITIES.md`, `outputs/integration-notes/ROADMAP.md`.

`light.py` is unchanged in this plan. CCT continues to follow `has_color_temp` after merge. Do not add `ColorMode.RGB`.

---

### Task 1: Unsigned classifier

**Files:**
- Modify: `custom_components/atx_led/models.py` (`LightDevice`, `parse_device`)
- Modify: `custom_components/atx_led/const.py`
- Test: `tests/test_unsigned.py`

**Interfaces:**
- Consumes: hub device dicts already parsed by `parse_device`
- Produces: `is_unsigned_driver(raw: dict) -> bool`; `LightDevice.unsigned: bool`; `LightDevice.unsigned_mode: str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_unsigned.py`:

```python
from atx_led.models import is_unsigned_driver, parse_device, reconcile_lights


def test_empty_type_and_zero_serial_firmware_is_unsigned() -> None:
    raw = {
        "channel": 0,
        "short_addr": 16,
        "dev_name": "Kitchen Shade Cove",
        "serial_nb": 0,
        "fw_version": 0,
        "has_color_temp": False,
        "is_button": False,
        "is_io_device": False,
        "is_passive": False,
        "is_relay_device": False,
    }
    assert is_unsigned_driver(raw) is True
    device = parse_device("0_s_16", raw)
    assert device is not None
    assert device.unsigned is True
    assert device.unsigned_mode is None


def test_missing_type_serial_firmware_is_unsigned() -> None:
    raw = {"channel": 0, "short_addr": 11, "dev_name": "Cabinet"}
    assert is_unsigned_driver(raw) is True


def test_dev_type_present_is_known() -> None:
    raw = {
        "channel": 0,
        "short_addr": 1,
        "dev_type": 8,
        "serial_nb": 0,
        "fw_version": 0,
    }
    assert is_unsigned_driver(raw) is False


def test_nonzero_serial_is_known() -> None:
    raw = {"channel": 0, "short_addr": 1, "serial_nb": 2, "fw_version": 0}
    assert is_unsigned_driver(raw) is False


def test_nonzero_firmware_is_known() -> None:
    raw = {"channel": 0, "short_addr": 1, "serial_nb": 0, "fw_version": 12}
    assert is_unsigned_driver(raw) is False


def test_status_03_does_not_classify(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    hall = lights["0_s_1"]
    cabinet = lights["0_s_11"]
    cove = lights["0_s_16"]
    assert hall.unsigned is False
    assert hall.has_color_temp is True
    assert cabinet.unsigned is True
    assert cove.unsigned is True
    assert cabinet.status == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_unsigned.py -q`

Expected: FAIL with `ImportError` or `AttributeError` for `is_unsigned_driver` / `unsigned`.

- [ ] **Step 3: Add constants and classifier**

In `custom_components/atx_led/const.py` add:

```python
CONF_UNSIGNED_OVERRIDES = "unsigned_overrides"
CONF_DEVICE_ID = "device_id"
MODE_DIMMER = "dimmer"
MODE_CCT = "cct"
MODE_RGB = "rgb"
MODE_RGB_CCT = "rgb_cct"
UNSIGNED_MODES = (MODE_DIMMER, MODE_CCT, MODE_RGB, MODE_RGB_CCT)
DEFAULT_KELVIN_MIN = 2700
DEFAULT_KELVIN_MAX = 5000
```

In `LightDevice` add after `available: bool = True`:

```python
    unsigned: bool = False
    unsigned_mode: str | None = None
```

Add `is_unsigned_driver` next to `_as_int` in `models.py`:

```python
def is_unsigned_driver(raw: dict) -> bool:
    """True when the hub could not characterize the fixture."""
    if raw.get("dev_type") not in (None, "", 0):
        return False
    if _as_optional_int(raw.get("serial_nb")) not in (None, 0):
        return False
    if _as_optional_int(raw.get("fw_version")) not in (None, 0):
        return False
    return True
```

In `parse_device`, pass:

```python
        unsigned=is_unsigned_driver(raw),
        unsigned_mode=None,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_unsigned.py tests/test_models.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add custom_components/atx_led/const.py custom_components/atx_led/models.py tests/test_unsigned.py
git commit -m "$(cat <<'EOF'
Identify unsigned leftover drivers from empty type and zero identity.

EOF
)"
```

---

### Task 2: Apply HA-only overrides

**Files:**
- Create: `custom_components/atx_led/unsigned.py`
- Modify: `custom_components/atx_led/coordinator.py` (`_async_update_data`)
- Modify: `custom_components/atx_led/models.py` only if `kelvin_to_mired` should sit beside `mired_to_kelvin` — prefer putting Kelvin conversion in `unsigned.py` to keep apply logic together
- Test: `tests/test_unsigned.py`

**Interfaces:**
- Consumes: `is_unsigned_driver`, `LightDevice`, `color_temp_range_kelvin`, `UNSIGNED_MODES`, `DEFAULT_KELVIN_MIN`, `DEFAULT_KELVIN_MAX`
- Produces:
  - `class UnsignedOverrideError(ValueError)` with `.code: str`
  - `kelvin_to_mired(kelvin: int) -> int | None`
  - `normalize_unsigned_override(user_input: dict) -> dict`
  - `apply_unsigned_override(device: LightDevice, override: dict) -> LightDevice`
  - `apply_unsigned_overrides(lights: dict[str, LightDevice], overrides: object) -> dict[str, LightDevice]`
  - `unsigned_device_choices(lights: dict[str, LightDevice]) -> dict[str, str]`
  - `suggested_tune_values(light: LightDevice, override: dict | None) -> dict[str, object]`
  - `merge_unsigned_override(options: dict, device_id: str, override: dict) -> dict`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_unsigned.py`:

```python
from atx_led.brightness import ha_brightness_to_dali
from atx_led.const import MODE_CCT, MODE_DIMMER, MODE_RGB, MODE_RGB_CCT
from atx_led.models import apply_derived_group_states, color_temp_range_kelvin, reconcile_groups
from atx_led.unsigned import (
    UnsignedOverrideError,
    apply_unsigned_overrides,
    merge_unsigned_override,
    normalize_unsigned_override,
    suggested_tune_values,
    unsigned_device_choices,
)


def test_normalize_rejects_inverted_dim_range() -> None:
    try:
        normalize_unsigned_override(
            {"mode": MODE_DIMMER, "min_level": 200, "max_level": 50}
        )
    except UnsignedOverrideError as err:
        assert err.code == "invalid_range"
    else:
        raise AssertionError("expected UnsignedOverrideError")


def test_normalize_requires_kelvin_for_cct() -> None:
    try:
        normalize_unsigned_override(
            {"mode": MODE_CCT, "min_level": 50, "max_level": 254}
        )
    except UnsignedOverrideError as err:
        assert err.code == "invalid_kelvin"
    else:
        raise AssertionError("expected UnsignedOverrideError")


def test_normalize_cct_keeps_typed_ends() -> None:
    assert normalize_unsigned_override(
        {
            "mode": MODE_CCT,
            "min_level": 50,
            "max_level": 254,
            "kelvin_min": 2700,
            "kelvin_max": 5000,
        }
    ) == {
        "mode": MODE_CCT,
        "min_level": 50,
        "max_level": 254,
        "kelvin_min": 2700,
        "kelvin_max": 5000,
    }


def test_override_min_maps_one_percent(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    updated = apply_unsigned_overrides(
        lights,
        {
            "0_s_16": {
                "mode": MODE_DIMMER,
                "min_level": 50,
                "max_level": 254,
            }
        },
    )
    cove = updated["0_s_16"]
    assert cove.min_level == 50
    assert cove.max_level == 254
    assert cove.has_color_temp is False
    assert ha_brightness_to_dali(1, cove.min_level, cove.max_level) == 50


def test_cct_override_sets_slider_ends(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    updated = apply_unsigned_overrides(
        lights,
        {
            "0_s_16": {
                "mode": MODE_CCT,
                "min_level": 50,
                "max_level": 254,
                "kelvin_min": 2700,
                "kelvin_max": 5000,
            }
        },
    )
    cove = updated["0_s_16"]
    assert cove.has_color_temp is True
    assert cove.has_color_rgb is False
    assert cove.unsigned_mode == MODE_CCT
    minimum, maximum = color_temp_range_kelvin(cove.user_warm, cove.user_cool)
    assert minimum is not None and maximum is not None
    assert minimum < maximum
    assert abs(minimum - 2700) <= 5
    assert abs(maximum - 5000) <= 5


def test_known_fixture_override_is_ignored(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    hall_before = lights["0_s_1"]
    updated = apply_unsigned_overrides(
        lights,
        {
            "0_s_1": {
                "mode": MODE_DIMMER,
                "min_level": 1,
                "max_level": 10,
            }
        },
    )
    assert updated["0_s_1"] is hall_before
    assert updated["0_s_1"].min_level == 50
    assert updated["0_s_1"].has_color_temp is True


def test_rgb_mode_sets_flag_but_not_cct(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    updated = apply_unsigned_overrides(
        lights,
        {"0_s_11": {"mode": MODE_RGB, "min_level": 1, "max_level": 254}},
    )
    cabinet = updated["0_s_11"]
    assert cabinet.has_color_rgb is True
    assert cabinet.has_color_temp is False
    assert cabinet.unsigned_mode == MODE_RGB


def test_group_gains_cct_after_unsigned_member_override() -> None:
    addresses = {
        "Groups": [{"key": "0_g_1", "value": "Group 1"}],
        "Lights": [{"key": "0_s_11", "value": "Cabinet"}],
        "Virtual Groups": [],
    }
    devices = {
        "0_s_11": {
            "channel": 0,
            "short_addr": 11,
            "dev_name": "Cabinet",
            "serial_nb": 0,
            "fw_version": 0,
            "dev_on": False,
            "groups": [1],
            "has_color_temp": False,
            "level": 0,
            "is_button": False,
            "is_io_device": False,
            "is_passive": False,
            "is_relay_device": False,
        },
        "0_g_1": {
            "address": [0, "group", 1],
            "channel": 0,
            "dev_name": "Group 1",
            "device_ids": [11],
        },
    }
    lights = {light.device_id: light for light in reconcile_lights(addresses, devices)}
    groups = {
        group.device_id: group
        for group in reconcile_groups(addresses, devices, list(lights.values()))
    }
    assert groups["0_g_1"].has_color_temp is False
    lights = apply_unsigned_overrides(
        lights,
        {
            "0_s_11": {
                "mode": MODE_CCT,
                "min_level": 50,
                "max_level": 254,
                "kelvin_min": 2700,
                "kelvin_max": 5000,
            }
        },
    )
    groups = apply_derived_group_states(groups, lights)
    assert groups["0_g_1"].has_color_temp is True


def test_choices_list_only_unsigned(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    choices = unsigned_device_choices(lights)
    assert "0_s_11" in choices
    assert "0_s_16" in choices
    assert "0_s_1" not in choices
    assert choices["0_s_16"] == "Cove Light (0_s_16)"


def test_merge_override_preserves_other_devices() -> None:
    options = merge_unsigned_override(
        {"unsigned_overrides": {"0_s_11": {"mode": MODE_DIMMER, "min_level": 1, "max_level": 254}}},
        "0_s_16",
        {"mode": MODE_CCT, "min_level": 50, "max_level": 254, "kelvin_min": 2700, "kelvin_max": 5000},
    )
    assert set(options["unsigned_overrides"]) == {"0_s_11", "0_s_16"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_unsigned.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'atx_led.unsigned'`.

- [ ] **Step 3: Implement `unsigned.py`**

```python
"""Home Assistant-only overrides for unsigned leftover drivers."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .const import (
    CONF_UNSIGNED_OVERRIDES,
    DEFAULT_KELVIN_MAX,
    DEFAULT_KELVIN_MIN,
    MODE_CCT,
    MODE_DIMMER,
    MODE_RGB,
    MODE_RGB_CCT,
    UNSIGNED_MODES,
)
from .models import LightDevice, color_temp_range_kelvin
from .protocol import DALI_MAX_ARC_LEVEL

_CCT_MODES = {MODE_CCT, MODE_RGB_CCT}
_RGB_MODES = {MODE_RGB, MODE_RGB_CCT}


class UnsignedOverrideError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def kelvin_to_mired(kelvin: int) -> int | None:
    if kelvin <= 0:
        return None
    return round(1_000_000 / kelvin)


def normalize_unsigned_override(user_input: dict[str, Any]) -> dict[str, Any]:
    mode = str(user_input.get("mode") or "")
    if mode not in UNSIGNED_MODES:
        raise UnsignedOverrideError("invalid_range")
    try:
        min_level = int(user_input["min_level"])
        max_level = int(user_input["max_level"])
    except (KeyError, TypeError, ValueError) as err:
        raise UnsignedOverrideError("invalid_range") from err
    if not 1 <= min_level <= DALI_MAX_ARC_LEVEL or not 1 <= max_level <= DALI_MAX_ARC_LEVEL:
        raise UnsignedOverrideError("invalid_range")
    if min_level >= max_level:
        raise UnsignedOverrideError("invalid_range")
    result: dict[str, Any] = {
        "mode": mode,
        "min_level": min_level,
        "max_level": max_level,
    }
    if mode in _CCT_MODES:
        try:
            kelvin_min = int(user_input["kelvin_min"])
            kelvin_max = int(user_input["kelvin_max"])
        except (KeyError, TypeError, ValueError) as err:
            raise UnsignedOverrideError("invalid_kelvin") from err
        if kelvin_min < 1000 or kelvin_max > 20000 or kelvin_min >= kelvin_max:
            raise UnsignedOverrideError("invalid_kelvin")
        result["kelvin_min"] = kelvin_min
        result["kelvin_max"] = kelvin_max
    return result


def apply_unsigned_override(device: LightDevice, override: dict) -> LightDevice:
    try:
        normalized = normalize_unsigned_override(override)
    except UnsignedOverrideError:
        return device
    mode = normalized["mode"]
    updates: dict[str, Any] = {
        "min_level": normalized["min_level"],
        "max_level": normalized["max_level"],
        "unsigned_mode": mode,
        "has_color_temp": mode in _CCT_MODES,
        "has_color_rgb": mode in _RGB_MODES,
    }
    if mode in _CCT_MODES:
        warm = kelvin_to_mired(normalized["kelvin_min"])
        cool = kelvin_to_mired(normalized["kelvin_max"])
        if warm is None or cool is None:
            return device
        updates["user_warm"] = max(warm, cool)
        updates["user_cool"] = min(warm, cool)
    else:
        updates["user_warm"] = None
        updates["user_cool"] = None
    return replace(device, **updates)


def apply_unsigned_overrides(
    lights: dict[str, LightDevice], overrides: object
) -> dict[str, LightDevice]:
    if not isinstance(overrides, dict) or not overrides:
        return lights
    updated = dict(lights)
    changed = False
    for device_id, override in overrides.items():
        device = updated.get(str(device_id))
        if device is None or not device.unsigned or not isinstance(override, dict):
            continue
        merged = apply_unsigned_override(device, override)
        if merged is not device:
            updated[str(device_id)] = merged
            changed = True
    return updated if changed else lights


def unsigned_device_choices(lights: dict[str, LightDevice]) -> dict[str, str]:
    return {
        device_id: f"{light.name} ({device_id})"
        for device_id, light in lights.items()
        if light.unsigned
    }


def suggested_tune_values(
    light: LightDevice, override: dict | None
) -> dict[str, object]:
    source = override if isinstance(override, dict) else {}
    values: dict[str, object] = {
        "mode": source.get("mode") or light.unsigned_mode or MODE_DIMMER,
        "min_level": source.get("min_level", light.min_level),
        "max_level": source.get("max_level", light.max_level),
        "kelvin_min": source.get("kelvin_min", DEFAULT_KELVIN_MIN),
        "kelvin_max": source.get("kelvin_max", DEFAULT_KELVIN_MAX),
    }
    if not source and light.has_color_temp:
        minimum, maximum = color_temp_range_kelvin(light.user_warm, light.user_cool)
        if minimum and maximum:
            values["kelvin_min"] = minimum
            values["kelvin_max"] = maximum
    return values


def merge_unsigned_override(
    options: dict, device_id: str, override: dict
) -> dict:
    merged = dict(options)
    overrides = dict(merged.get(CONF_UNSIGNED_OVERRIDES) or {})
    overrides[device_id] = override
    merged[CONF_UNSIGNED_OVERRIDES] = overrides
    return merged
```

- [ ] **Step 4: Apply overrides in the coordinator**

In `coordinator.py` import `CONF_UNSIGNED_OVERRIDES` and `apply_unsigned_overrides`.

Replace the lights/groups assembly in `_async_update_data` with:

```python
        lights_map = {light.device_id: light for light in lights}
        lights_map = apply_unsigned_overrides(
            lights_map,
            self.config_entry.options.get(CONF_UNSIGNED_OVERRIDES),
        )
        discovered_groups = {group.device_id: group for group in groups}
        previous_groups = self.data.groups if self.data is not None else {}
        groups_map = preserve_group_live_state(previous_groups, discovered_groups)
        groups_map = apply_derived_group_states(groups_map, lights_map)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests -q`

Expected: PASS (existing suite plus new unsigned tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/atx_led/unsigned.py custom_components/atx_led/coordinator.py tests/test_unsigned.py
git commit -m "$(cat <<'EOF'
Apply Home Assistant-only dim and CCT overrides to unsigned drivers.

EOF
)"
```

---

### Task 3: Configure options flow

**Files:**
- Modify: `custom_components/atx_led/config_flow.py`
- Modify: `custom_components/atx_led/__init__.py`
- Modify: `custom_components/atx_led/strings.json`
- Modify: `custom_components/atx_led/translations/en.json`

**Interfaces:**
- Consumes: `unsigned_device_choices`, `suggested_tune_values`, `normalize_unsigned_override`, `merge_unsigned_override`, `CONF_DEVICE_ID`, `CONF_UNSIGNED_OVERRIDES`, `UNSIGNED_MODES`
- Produces: `ATXLEDOptionsFlow` via `ATXLEDConfigFlow.async_get_options_flow`; `async_reload_entry` update listener

- [ ] **Step 1: Add options strings**

In both `strings.json` and `translations/en.json`, add a sibling of `"config"`:

```json
  "options": {
    "step": {
      "init": {
        "title": "Unsigned leftover drivers",
        "description": "Pick a driver the hub could not characterize. Home Assistant stores mode and ranges locally and does not write them to the hub.",
        "data": {
          "device_id": "Driver"
        }
      },
      "tune": {
        "title": "Tune leftover driver",
        "description": "Match min/max dim and Kelvin by sight. Min dim is Home Assistant 1%. RGB mode is stored but color picker waits until the hub RGB write is verified.",
        "data": {
          "mode": "Mode",
          "min_level": "Min dim (raw 1-254)",
          "max_level": "Max dim (raw 1-254)",
          "kelvin_min": "Warm Kelvin",
          "kelvin_max": "Cool Kelvin"
        }
      }
    },
    "error": {
      "invalid_range": "Min dim must be below max dim, each between 1 and 254",
      "invalid_kelvin": "Warm Kelvin must be below cool Kelvin"
    },
    "abort": {
      "no_unsigned": "This hub has no unsigned leftover drivers to tune"
    }
  }
```

- [ ] **Step 2: Reload when options change**

In `__init__.py` add:

```python
async def async_reload_entry(hass: HomeAssistant, entry: ATXLEDConfigEntry) -> None:
    """Reload so unsigned override color modes refresh."""
    await hass.config_entries.async_reload(entry.entry_id)
```

At the end of `async_setup_entry`, before `return True`:

```python
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
```

- [ ] **Step 3: Implement the options flow**

Update `config_flow.py` imports and add `async_get_options_flow` plus `ATXLEDOptionsFlow`. Keep `STEP_USER_DATA_SCHEMA` and the existing user/reconfigure steps.

```python
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

from .const import (
    CONF_DEVICE_ID,
    CONF_UNSIGNED_OVERRIDES,
    DOMAIN,
    MODE_CCT,
    MODE_DIMMER,
    MODE_RGB,
    MODE_RGB_CCT,
)
from .unsigned import (
    UnsignedOverrideError,
    merge_unsigned_override,
    normalize_unsigned_override,
    suggested_tune_values,
    unsigned_device_choices,
)

_MODE_OPTIONS = [
    {"value": MODE_DIMMER, "label": "Dimmer"},
    {"value": MODE_CCT, "label": "CCT"},
    {"value": MODE_RGB, "label": "RGB"},
    {"value": MODE_RGB_CCT, "label": "RGB+CCT"},
]
```

On `ATXLEDConfigFlow`:

```python
    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return ATXLEDOptionsFlow()
```

Then:

```python
class ATXLEDOptionsFlow(OptionsFlow):
    """Tune unsigned leftover drivers without writing hub configuration."""

    def __init__(self) -> None:
        self._device_id: str | None = None

    def _unsigned_lights(self) -> dict:
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None or coordinator.data is None:
            return {}
        return {
            device_id: light
            for device_id, light in coordinator.data.lights.items()
            if light.unsigned
        }

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        lights = self._unsigned_lights()
        choices = unsigned_device_choices(lights)
        if not choices:
            return self.async_abort(reason="no_unsigned")
        if user_input is not None:
            self._device_id = str(user_input[CONF_DEVICE_ID])
            return await self.async_step_tune()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": device_id, "label": label}
                                for device_id, label in choices.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_tune(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        lights = self._unsigned_lights()
        device_id = self._device_id
        if device_id is None or device_id not in lights:
            return await self.async_step_init()
        light = lights[device_id]
        stored = (self.config_entry.options.get(CONF_UNSIGNED_OVERRIDES) or {}).get(device_id)
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                override = normalize_unsigned_override(user_input)
            except UnsignedOverrideError as err:
                errors["base"] = err.code
            else:
                options = merge_unsigned_override(
                    dict(self.config_entry.options), device_id, override
                )
                return self.async_create_entry(title="", data=options)
        suggested = suggested_tune_values(light, stored if isinstance(stored, dict) else None)
        return self.async_show_form(
            step_id="tune",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required("mode"): SelectSelector(
                            SelectSelectorConfig(
                                options=_MODE_OPTIONS,
                                mode=SelectSelectorMode.DROPDOWN,
                            )
                        ),
                        vol.Required("min_level"): int,
                        vol.Required("max_level"): int,
                        vol.Optional("kelvin_min"): int,
                        vol.Optional("kelvin_max"): int,
                    }
                ),
                suggested,
            ),
            errors=errors,
            description_placeholders={"name": light.name, "device_id": device_id},
        )
```

Config flow tests are not added: this repo loads `atx_led` without Home Assistant. Behavior of choices/normalize/merge is covered in Task 2.

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest tests -q`

Expected: PASS. `config_flow.py` is imported only under Home Assistant, so pytest will not import it.

- [ ] **Step 5: Commit**

```bash
git add custom_components/atx_led/config_flow.py custom_components/atx_led/__init__.py custom_components/atx_led/strings.json custom_components/atx_led/translations/en.json
git commit -m "$(cat <<'EOF'
Add a Configure flow to tune unsigned leftover drivers.

EOF
)"
```

---

### Task 4: Diagnostics

**Files:**
- Modify: `custom_components/atx_led/diagnostics.py`
- Test: `tests/test_unsigned.py`

**Interfaces:**
- Consumes: `LightDevice.unsigned`, `unsigned_mode`, `min_level`, `max_level`, `user_warm`, `user_cool`
- Produces: `unsigned_diagnostics(light: LightDevice) -> dict[str, object]` used by `async_get_config_entry_diagnostics`

- [ ] **Step 1: Write the failing test**

```python
from atx_led.unsigned import unsigned_diagnostics


def test_diagnostics_include_applied_override(
    addresses_payload: dict, devices_payload: dict
) -> None:
    lights = {light.device_id: light for light in reconcile_lights(addresses_payload, devices_payload)}
    updated = apply_unsigned_overrides(
        lights,
        {
            "0_s_16": {
                "mode": MODE_CCT,
                "min_level": 50,
                "max_level": 254,
                "kelvin_min": 2700,
                "kelvin_max": 5000,
            }
        },
    )
    payload = unsigned_diagnostics(updated["0_s_16"])
    assert payload["unsigned"] is True
    assert payload["unsigned_mode"] == MODE_CCT
    assert payload["min_level"] == 50
    assert payload["max_level"] == 254
    assert "kelvin_min" in payload
    assert "kelvin_max" in payload
    hall = unsigned_diagnostics(updated["0_s_1"])
    assert hall == {"unsigned": False}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_unsigned.py::test_diagnostics_include_applied_override -q`

Expected: FAIL with `ImportError` for `unsigned_diagnostics`.

- [ ] **Step 3: Implement diagnostics helper and wire it**

Add to `unsigned.py`:

```python
def unsigned_diagnostics(light: LightDevice) -> dict[str, object]:
    payload: dict[str, object] = {"unsigned": light.unsigned}
    if not light.unsigned_mode:
        return payload
    payload["unsigned_mode"] = light.unsigned_mode
    payload["min_level"] = light.min_level
    payload["max_level"] = light.max_level
    if light.has_color_temp:
        minimum, maximum = color_temp_range_kelvin(light.user_warm, light.user_cool)
        if minimum and maximum:
            payload["kelvin_min"] = minimum
            payload["kelvin_max"] = maximum
    return payload
```

In `diagnostics.py`, merge `**unsigned_diagnostics(light)` into each light dict.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add custom_components/atx_led/unsigned.py custom_components/atx_led/diagnostics.py tests/test_unsigned.py
git commit -m "$(cat <<'EOF'
Include unsigned driver mode and ranges in diagnostics.

EOF
)"
```

---

### Task 5: Docs and version

**Files:**
- Modify: `custom_components/atx_led/manifest.json` (`version` → `0.4.0`)
- Modify: `README.md`
- Modify: `outputs/integration-notes/SETUP-AND-ENTITIES.md`
- Modify: `outputs/integration-notes/ROADMAP.md`
- Modify: `outputs/integration-notes/README.md` (version line)
- Modify: `docs/superpowers/specs/2026-09-12-unsigned-driver-overrides-design.md` status to `approved`

- [ ] **Step 1: Update product docs**

`manifest.json` version: `"0.4.0"`.

README Behavior, add after the color-temperature bullet:

```markdown
- Leftover drivers the hub cannot characterize (empty type, zero serial/firmware) stay dimmers until you open **Configure** on the integration, pick a mode, and set min/max dim and Kelvin by sight. Those values stay in Home Assistant and are not written to the hub.
```

In `SETUP-AND-ENTITIES.md` Entity mapping, after the RGB bullet, add:

```markdown
- Unsigned leftovers (`dev_type` empty and serial/firmware zero): brightness-only until Configure sets a Home Assistant-only override (`dimmer` / `cct` / `rgb` / `rgb_cct`, raw min/max, optional Kelvin ends). Do not write those values to the hub. RGB picker remains deferred until the color write is verified.
```

In `ROADMAP.md` Done, add item 7:

```markdown
7. **Unsigned leftovers** — Configure flow stores HA-only mode, dim range, and Kelvin ends for drivers the hub cannot characterize. RGB picker still unverified.
```

In Later, keep RGB as a later item (picker/write verification).

Set spec status to `approved`.

- [ ] **Step 2: Run tests once more**

Run: `.venv/bin/pytest tests -q`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add custom_components/atx_led/manifest.json README.md outputs/integration-notes/SETUP-AND-ENTITIES.md outputs/integration-notes/ROADMAP.md outputs/integration-notes/README.md docs/superpowers/specs/2026-09-12-unsigned-driver-overrides-design.md
git commit -m "$(cat <<'EOF'
Document unsigned leftover Configure tuning for 0.4.0.

EOF
)"
```

---

## Spec coverage

| Spec section | Task |
|---|---|
| Unsigned classifier | Task 1 |
| Options storage | Task 2 (`merge_unsigned_override`) + Task 3 |
| Apply pipeline / coordinator | Task 2 |
| Configure form | Task 3 |
| Entity CCT/dim behavior | Task 2 apply + existing `light.py` |
| RGB stored, no picker | Task 2 `test_rgb_mode_sets_flag_but_not_cct`; no `light.py` RGB |
| Known override ignored | Task 2 |
| Group CCT after member override | Task 2 |
| Diagnostics | Task 4 |
| Docs | Task 5 |
| No hub config writes | Global constraint; no new device POSTs |

## Manual check after merge (not part of pytest)

After Home Assistant loads `0.4.0`: Configure → pick Kitchen Shade Cove → mode CCT, min 50, max 254, Kelvin by sight → reload → entity shows Kelvin and 1% maps to raw 50. Do not send RGB writes in this change.
