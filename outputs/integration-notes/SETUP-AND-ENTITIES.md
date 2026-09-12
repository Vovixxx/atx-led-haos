# Setup and automatic entities

## Agreed product behavior

During setup, discover the hub's known DALI devices and automatically create entities according to the results. The user explicitly proposed this behavior after the inventory test.

## Setup flow

1. Enter the hub host; support credentials only if required by the actual API configuration.
2. Validate connectivity and response structure with read-only GET requests.
3. Read `/dali/api/addresses` and `/dali/api/devices`; reconcile their IDs.
4. Create the hub device and one light entity per eligible light record, keeping channel and short address as separate fields.
5. Derive capabilities from device flags, not names or merely populated color fields.
6. Read current state; optionally validate with paced individual DALI queries. No light state changes during setup.
7. Show discovered-device count and actionable connection or response errors. Support rediscovery later without duplicating entities.

This is discovery of already commissioned gear. Do not invoke physical commissioning, assign addresses, reset, or identify/blink devices as part of setup.

## Entity mapping

- Dimmable, no color capability: brightness light.
- `has_color_temp:true`: brightness + color-temperature light.
- `has_color_rgb:true`: expose an RGB-capable light only after verifying the actual API color representation and commands. Current installation has no advertised RGB lights.
- Explicit relay-only devices: on/off entity behavior after verifying semantics.
- Buttons, IO and passive devices: do not misclassify as ordinary lights; defer dedicated entity platforms.
- Groups and virtual groups: separate later feature; do not turn them into individual fixture records or broadcast targets.

Use a stable verified hub identifier plus internal channel and short address for unique IDs. Do not use the light name or `serial_nb` alone: serial values repeat in this inventory. Until hub identity is verified, document the fallback identity strategy and behavior if the IP changes.

Use the stored device name as the initial display name. User renames in HA should persist. Hue discovery visibility (`hue_hidden`) must not prevent native integration discovery.

## Brightness and state

Base on/off on reliable state/readback; raw level > 0 in the hub cache is not enough. Preserve last requested brightness separately if useful. Failed reads mean unknown/unavailable, not off.

Do not finalize percent conversion until the main UI mapping is verified. Handle zero, minimum, maximum, rounding, and invalid/equal min/max values explicitly. The first release should match the user's intended hub-control percentage consistently.

## Color temperature

Expose only when supported. Verify which fields represent the valid range before converting them. `phy_warm`, `phy_cool`, `user_warm`, and `user_cool` resemble reciprocal-megakelvin values; do not interchange them with kelvin or use arbitrary `color_cct_*` defaults.

Some hub records contain values outside their listed user/physical range (for example Office Light stores 2702 K with a 3003 K lower bound). Preserve source data, report inconsistencies, and validate ranges before enabling control. Do not silently change device configuration to repair them.

## Updates and reliability

The coordinator listens on `/ws/dali/devices` for immediate state. HTTP polling every 15 seconds remains the backup. Reconnect without replaying old light-changing requests. Serialize DALI traffic and avoid overlapping scans. Enable additional entities without controlling them.

The development test harness remains restricted to channel 1/address 1 for light-changing tests. Production scope expansion and live tests on other lights require the user's explicit authorization.
