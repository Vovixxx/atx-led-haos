# Setup and automatic entities

## Agreed product behavior

During setup, discover the hub's known DALI devices and automatically create entities according to the results.

## Setup flow

1. Enter the hub host; support credentials only if required by the actual API configuration.
2. Validate connectivity and response structure with read-only GET requests.
3. Read `/dali/api/addresses` and `/dali/api/devices`; reconcile their IDs.
4. Create the hub device, one light entity per eligible light record, one light entity per DALI or virtual group, and one scene entity per named hub scene. Keep channel, short address, and group address as separate fields.
5. Derive capabilities from device flags, not names or merely populated color fields.
6. Read current state. No light state changes during setup.
7. Show discovered-device count and actionable connection or response errors. Support rediscovery later without duplicating entities.

This is discovery of already commissioned gear. Do not invoke physical commissioning, assign addresses, reset, or identify/blink devices as part of setup.

## Entity mapping

- Dimmable, no color capability: brightness light.
- `has_color_temp:true`: brightness + color-temperature light.
- `has_color_rgb:true`: expose an RGB-capable light only after verifying the actual API color representation and commands. Do not assume RGB from populated color fields.
- Explicit relay-only devices: on/off entity behavior after verifying semantics.
- Buttons, IO and passive devices: do not misclassify as ordinary lights; defer dedicated entity platforms.
- Groups and virtual groups: separate light entities (`{hub_id}_g_{channel}_{group}` / `{hub_id}_v_{channel}_{group}`). Do not turn them into individual fixture records or import the broadcast `all` target. If the hub has no group `dev_on`/`level`, derive on/off and brightness from member fixtures so the entity is not left unknown.
- Hub scenes: scene entities when a DALI scene number is present. Recall uses group or per-fixture GO TO SCENE, not broadcast.

Unique IDs for fixtures are `{hub_id}_{channel}_{short_addr}`. Hub identity currently falls back to the host address. Do not use the light name or `serial_nb` alone: serial values can repeat. Reconfigure updates the host without creating new unique IDs.

Use the stored device name as the initial display name. User renames in Home Assistant should persist. Hue discovery visibility (`hue_hidden`) must not prevent native integration discovery.

## Brightness and state

Base on/off on `dev_on`, not raw `level > 0`. Preserve last stored brightness when off. Failed reads mean unknown/unavailable, not off.

Brightness uses the locked hub UI mapping `(raw - min) / (max - min)`. Handle zero, minimum, maximum, rounding, and invalid/equal min/max values explicitly.

On/off uses raw DAPC so the gear/hub fade for switching still applies. Brightness changes while the light is already on use `POST /dali/api/devices/{id}` with `level`, matching the hub UI dim path.

## Color temperature

Expose only when `has_color_temp` is true. The valid Kelvin range comes from `user_warm` / `user_cool` as mireds. Control uses `POST /dali/api/devices/{id}` with `color_temp_k`. Do not interchange physical/user mireds with kelvin or use arbitrary `color_cct_*` defaults.

A stored `color_temp_k` can sit outside the listed user/physical range. Preserve source data and clamp control to the valid range. Do not silently change device configuration to repair the stored value.

## Updates and reliability

The coordinator listens on `/ws/dali/devices` and `/ws/dali/groups` for immediate state. HTTP polling every 15 seconds remains the backup. Reconnect without replaying old light-changing requests. Serialize DALI traffic and avoid overlapping scans. Enable additional entities without controlling them. Scene GET failures must not take lights or groups offline.
