# Local API findings

## Connection

Base URL: `http://{hub-host}`.

The hub web UI may require HTTP authentication while inventory GET endpoints and `POST /dali/api/send-raw` can still return HTTP 200 without credentials. Auth requirements may vary by endpoint or installation; the integration accepts optional username and password and must not assume every hub is open or every hub requires login.

## Verified GET endpoints

### `/dali/api/addresses`

Returns categorized known addresses: `Lights`, `Groups`, `Buttons`, `All`, `Virtual Devices`, `Virtual Groups`.

Example light: `{"key":"0_s_1","value":"Hall Light"}`.

This is the hub inventory of commissioned gear, not proof that every possible DALI address has been polled or that unaddressed devices have been discovered. Light records use an internal channel index (displayed channel 1 is internal channel 0).

### `/dali/api/devices`

Returns an object keyed by address ID. Relevant fields:

- Identity: `address`, `channel`, `short_addr`, `dev_name`, `hue_name`, `serial_nb`, `upc_code`, firmware/hardware versions.
- State: `dev_on`, `dev_status`, `level`.
- Capabilities: `has_color_temp`, `has_color_rgb`, `is_button`, `is_io_device`, `is_passive`, `is_relay_device`, `dev_type`.
- Dimming limits: `min_level`, `max_level`, `phy_min_level`.
- Color: `color_temp_k`, `color_rgbw`, `phy_warm`, `phy_cool`, `user_warm`, `user_cool`, additional `color_k_*` and `color_cct_*` fields.
- Configuration: `groups`, fades, `power_on_level`, `fail_level`, `hue_hidden`.

Do not interpret `level > 0` alone as on. A fixture can report `dev_on:false` while still storing a last `level`. Direct DALI actual-level queries can return 0 in that case.

Do not expose color just because a color field is populated: records may carry default fields even when the color capability flag is false. `serial_nb` can repeat across fixtures and must not be used as a unique ID. `hue_hidden` must not exclude a fixture from this integration.

## Verified raw-command POST

`POST /dali/api/send-raw`, `Content-Type: application/json`.

Read-only example for displayed channel 1 / short address 1 (status, actual level, maximum, minimum):

```json
{"channel":0,"commands":["h0390","h03A0","h03A1","h03A2"]}
```

Example response:

```json
{"ok":true,"responses":["J00","J00","JFA","J32"]}
```

Decoded: status 0, actual level 0, maximum 250, minimum 50. Other fixtures can report different min/max values.

### Address encoding

Internal channel 0 = displayed channel 1. Hub ID `0_s_1` = channel 0, single address 1. Short addresses are 0–63.

- Direct arc power frame address byte: `short_address * 2`.
- DALI command/query address byte: `short_address * 2 + 1`.
- Prefix `h` sends one 16-bit DALI frame, represented by four hex characters.

Read-only opcodes used: status `90`, actual level `A0`, maximum `A1`, minimum `A2`. Query known fixtures individually and sequentially.

### Responses

- `Jxx`: returned byte in hexadecimal.
- `N`: no DALI reply; normal for brightness writes, not evidence of off or absence by itself when reading.
- HTTP errors, malformed replies, missing responses and collisions must not be translated to brightness zero.
- Status `00`: no bits set. Status `03`: driver/control-gear failure and lamp-failure bits set. A reported flag is not a physical diagnosis and does not mean the fixture is unreachable if it still replies.

Vendor material also describes `X` receive collisions, `Z` transmit collisions, `H` observed 16-bit packets, and other HAT diagnostic packets. Availability of all serial commands through HTTP is not verified.

## Verified WebSocket push

`ws://{hub-host}/ws/dali/devices` and `ws://{hub-host}/ws/dali/groups` return HTTP 101 and stay open. These sockets may not require the same credentials as the web UI.

No first-message subscribe is required. Sending trial payloads (`*`, `all`, `0_s_1`, `{}`, JSON addr objects) produced no replies and did not change fixture state.

`/ws/dali/devices` is idle until a fixture changes. It then sends a JSON **array of patches**, not a full inventory:

```json
[{"addr": "0_s_1", "data": {"channel": 0, "short_addr": 1, "dev_on": true, "level": 86, "address": [0, "single", 1], "dev_name": "Hall Light", "fail_level": 86, "power_on_level": 86}}]
```

Patches are partial: `dev_on` and `level` are typically present; capability flags and min/max are not. `level` can remain the last brightness while `dev_on` is false.

`/ws/dali/groups` uses the same `{addr, data}` array shape (`0_g_0`, `0_g_1`, …). An initial group snapshot may or may not arrive on connect; do not assume one. Group patches can include `dev_on`, `level`, `color_temp_k`, and member lists.

Wrong paths (`/ws/dali/devices/0_s_1`, query strings, trailing slash) drop the connection. Reconnect is a new socket; do not replay light-changing HTTP commands on reconnect.

## Device writes

Verified: `POST /dali/api/devices/{id}` with `color_temp_k` sets Kelvin on color-temperature fixtures.

Observed in web-interface source; not independently used by this integration:

- POST `/dali/api/devices/{id}` with fields such as `dev_on` and `level`.
- GET `/dali/api/scenes`.
- Device controls use debounced writes. Basic view raw slider bounds are 0–254.

Do not present untested source-observed endpoints as integration controls.

## Serial documentation versus HTTP

HAT documentation describes the Pi-to-HAT serial protocol, including lowercase command prefixes, diagnostics, and newline framing. The HTTP endpoint accepts `h` frames without appended newlines. Do not append serial framing or assume every HAT diagnostic command is exposed by HTTP without checking.
