# Unsigned driver overrides

Date: 2026-09-12  
Status: approved  
Integration: `custom_components/atx_led`

## Problem

Some commissioned fixtures look like lights to the hub but cannot be queried or configured over DALI. On this hub they are leftover “dumb DT8” drivers (MiBoxer-style). Inventory shows:

- empty `dev_type`
- `serial_nb`, `fw_version`, and usually `hw_version` of `0`
- `has_color_temp: false` and `has_color_rgb: false`
- DALI status `03` (query/failure bits; not used as the classifier)
- stored `color_temp_k` and default `color_k_min`/`color_k_max` of 2700–5000
- no `user_warm` / `user_cool` / `phy_warm` / `phy_cool`

They still accept on/off, brightness, and color commands. The hub cannot report which mode the hardware is in or the usable dim/Kelvin range. Home Assistant currently treats them as brightness-only lights with min `1` and max `254`, which does not match other fixtures on the same network.

Known DT8 fixtures already come in with hub flags and ranges. Those must not be overridden.

## Goal

After inventory, Home Assistant puts known fixtures back together from hub capabilities. Unsigned leftovers stay dimmers until the user one-time-tunes them in HA by sight. Overrides live only in the integration. HA never writes min/max, CCT limits, or mode into the driver or hub device record.

## Unsigned classifier

A fixture is **unsigned** when all of the following are true on the hub device record:

1. `dev_type` is missing, empty, or `0`
2. `serial_nb` is missing or `0`
3. `fw_version` is missing or `0`

`hw_version` is often also `0` on these leftovers. It is not part of the classifier.

A fixture is **known** otherwise. Known fixtures never appear in the override form. If an override exists for a device id that later becomes known, ignore that override. Do not apply it on top of hub capabilities.

Status `03` is diagnostic only. Do not classify from status, name, `color_temp_k`, or populated `color_rgbw`.

Store `unsigned: bool` on `LightDevice` at parse time from the raw record so later inventory steps do not need serial/firmware fields.

## Options storage

Save overrides on the hub config entry options, keyed by hub device id:

```json
{
  "unsigned_overrides": {
    "0_s_16": {
      "mode": "cct",
      "min_level": 50,
      "max_level": 254,
      "kelvin_min": 2700,
      "kelvin_max": 5000
    }
  }
}
```

Field rules:

| Field | Required | Meaning |
|---|---|---|
| `mode` | yes | `dimmer`, `cct`, `rgb`, or `rgb_cct` |
| `min_level` | yes | raw DALI level that maps to HA 1% (`1`–`254`) |
| `max_level` | yes | raw DALI level that maps to HA 100% (`1`–`254`, must be greater than min) |
| `kelvin_min` | if mode includes CCT | warm slider end, Kelvin |
| `kelvin_max` | if mode includes CCT | cool slider end, Kelvin, must be greater than `kelvin_min` |

Unique entity ids do not change. Overrides for missing devices stay in options and do nothing.

## Apply pipeline

1. Discover inventory as today (`addresses`, `devices`, best-effort `groups`/`scenes`).
2. Parse lights. Mark `unsigned` from the classifier.
3. In the coordinator, after discover and before `apply_derived_group_states`, merge `entry.options["unsigned_overrides"]` onto lights where `unsigned` is true.
4. Derive group on/off, limits, and CCT from the merged lights.

Merge behavior for an unsigned light with an override:

- Replace `min_level` / `max_level` with the override values. Existing brightness mapping `(raw - min) / (max - min)` is unchanged.
- `dimmer`: `has_color_temp=false`, `has_color_rgb=false`
- `cct`: `has_color_temp=true`, `has_color_rgb=false`
- `rgb`: `has_color_temp=false`, `has_color_rgb=true`
- `rgb_cct`: both true
- When mode includes CCT, convert typed Kelvin to `user_warm` / `user_cool` mireds (`round(1000000 / kelvin)`, warm is the larger mired) so `color_temp_range_kelvin` and the light entity keep working.

Unsigned with no override: leave hub parse as-is (brightness only, hub min/max).

WebSocket patches already keep capabilities and dimming limits. Do not let a patch strip an applied override. HTTP poll reapplies overrides from options.

The client stays unaware of Home Assistant options.

## Configure flow

Add an options flow. Reconfigure remains host/login only.

Settings → Devices & services → ATX LED → Configure:

1. Dropdown of current unsigned lights, label `"{name} ({device_id})"`. Already-tuned leftovers stay listed.
2. Form: mode, min dim, max dim, warm Kelvin, cool Kelvin. Kelvin values are required and used only when mode is `cct` or `rgb_cct`; otherwise they are ignored.
3. Defaults: existing override if present, else hub `min_level` / `max_level` and hub `color_k_min` / `color_k_max` when those are usable Kelvin values, otherwise `2700` / `5000`.
4. Save writes that device id into `unsigned_overrides` and reloads the config entry so color modes and Kelvin limits refresh.

If there are no unsigned lights, show a message and no form. Validation errors stay on the form: min/max in `1`–`254` with min below max; when CCT is selected, warm Kelvin below cool Kelvin.

Changing mode later, including back to dimmer, is allowed. Dimmer clears color controls on that fixture after reload.

## Entity behavior

On/off and brightness paths stay the same (`send-raw` DAPC, hub `level` write while on). Override min/max only change the HA percentage mapping.

CCT writes stay `POST /dali/api/devices/{id}` with `color_temp_k`. Displayed Kelvin is hub `color_temp_k` when `has_color_temp` is true after merge.

Groups have no override form. Existing member-based group CCT applies: once a leftover member is `cct` or `rgb_cct`, the group may expose Kelvin and write members.

HA does not POST min/max, power-on, fail-level, or color config to the driver. Failed commands stay failed; they are not translated to off.

RGB: the mode may be stored. Do not expose an RGB color picker or send RGB writes in this change. `has_color_rgb` on the merged model is allowed for diagnostics, but `LightEntity` supported color modes stay brightness and/or color-temp until a hub RGB write is live-verified in a later change.

## Diagnostics

Redacted diagnostics include, per light: `unsigned`, and when an override was applied, `unsigned_mode`, `min_level`, `max_level`, and Kelvin ends. No credentials.

## Tests

- Classifier: zeros + empty type → unsigned; `dev_type` 8 or non-zero serial/firmware → known.
- Apply override only to unsigned ids; known fixtures unchanged even if options contain their id.
- Brightness mapping uses override min (for example min `50` → HA 1%).
- CCT override sets Kelvin slider ends from typed warm/cool.
- Group CCT appears after an unsigned member is marked `cct`.
- Options flow lists only unsigned ids; empty unsigned set has no device picker.
- Form rejects min ≥ max and CCT warm ≥ cool.
- Saving `rgb` or `rgb_cct` does not add an RGB color mode to the light entity in this change.

## Docs to update after implementation

- `README.md` — Configure unsigned leftovers.
- `outputs/integration-notes/SETUP-AND-ENTITIES.md` — unsigned classifier and HA-only ranges.
- `outputs/integration-notes/ROADMAP.md` — this work vs later RGB picker.

## Out of scope

- Writing DALI/hub configuration (min, max, mode, CCT physics).
- RGB color picker and RGB command verification.
- Repair issues or always-on tuner helper entities.
- Overriding known DT8 fixtures.
- Buttons, IO, relays, hub identity.
