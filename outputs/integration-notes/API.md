# Local API findings

## Connection

Base URL: `http://192.168.1.50`.

The web interface was authenticated in the browser. Unauthenticated GET of `/dali/devices` returned HTTP 401 from the shell. However, the tested API GET endpoints and raw POST endpoint returned HTTP 200 **without credentials** in this environment. Authentication requirements may vary by endpoint or installation; do not assume all API access requires credentials or none ever will.

## Verified GET endpoints

### `/dali/api/addresses`

Returns categorized known addresses: `Lights`, `Groups`, `Buttons`, `All`, `Virtual Devices`, `Virtual Groups`.

Example light: `{"key":"0_s_1","value":"Hall Light"}`.

Snapshot: 39 lights, six groups (0, 1, 5, 6, 12, 15), one virtual group (0); empty Buttons and Virtual Devices. All light records are on internal channel 0. This is the hub inventory, not proof that every possible DALI address has been polled or unaddressed devices discovered.

### `/dali/api/devices`

Returns an object keyed by address ID. Relevant fields:

- Identity: `address`, `channel`, `short_addr`, `dev_name`, `hue_name`, `serial_nb`, `upc_code`, firmware/hardware versions.
- State: `dev_on`, `dev_status`, `level`.
- Capabilities: `has_color_temp`, `has_color_rgb`, `is_button`, `is_io_device`, `is_passive`, `is_relay_device`, `dev_type`.
- Dimming limits: `min_level`, `max_level`, `phy_min_level`.
- Color: `color_temp_k`, `color_rgbw`, `phy_warm`, `phy_cool`, `user_warm`, `user_cool`, additional `color_k_*` and `color_cct_*` fields.
- Configuration: `groups`, fades, `power_on_level`, `fail_level`, `hue_hidden`.

Do not interpret `level > 0` alone as on. Hall Light had `dev_on:false` and stored `level:185`, while a direct DALI query returned actual level 0.

Do not expose color just because a color field is populated: all records may carry default fields, including fixtures whose color capability flag is false.

## Verified raw-command POST

`POST /dali/api/send-raw`, `Content-Type: application/json`.

```json
{"channel":0,"commands":["h0390","h03A0","h03A1","h03A2"]}
```

This exact **read-only** request queries displayed channel 1, short address 1 for status, actual level, maximum, and minimum. Observed response:

```json
{"ok":true,"responses":["J00","J00","JFA","J32"]}
```

Decoded: status 0, actual level 0, maximum 250, minimum 50.

### Address encoding

Internal channel 0 = displayed channel 1. Hub ID `0_s_1` = channel 0, single address 1. Short addresses are 0–63.

- Direct arc power frame address byte: `short_address * 2`.
- DALI command/query address byte: `short_address * 2 + 1`.
- Prefix `h` sends one 16-bit DALI frame, represented by four hex characters.

Read-only opcodes used: status `90`, actual level `A0`, maximum `A1`, minimum `A2`. Each known fixture was queried individually using these four commands in one request; requests were sent sequentially.

### Responses

- `Jxx`: returned byte in hexadecimal.
- `N`: no DALI reply; normal for brightness writes, not evidence of off or absence by itself when reading.
- HTTP errors, malformed replies, missing responses and collisions must not be translated to brightness zero.
- Status `00`: no bits set. Status `03`: driver/control-gear failure and lamp-failure bits set. A reported flag is not a physical diagnosis.

Vendor material also describes `X` receive collisions, `Z` transmit collisions, `H` observed 16-bit packets, and other HAT diagnostic packets. Availability of all serial commands through HTTP is not verified.

## Verified WebSocket push

Unauthenticated `ws://192.168.1.50/ws/dali/devices` and `ws://192.168.1.50/ws/dali/groups` both return HTTP 101 and stay open. The web UI still requires HTTP auth; these sockets do not in this environment.

No first-message subscribe is required. Sending trial payloads (`*`, `all`, `0_s_1`, `{}`, JSON addr objects) produced no replies and did not change Hall Light.

`/ws/dali/devices` is idle until a fixture changes. It then sends a JSON **array of patches**, not a full inventory:

```json
[{"addr": "0_s_1", "data": {"channel": 0, "short_addr": 1, "dev_on": true, "level": 86, "address": [0, "single", 1], "dev_name": "Hall Light", "fail_level": 86, "power_on_level": 86}}]
```

Live observation (external on/off, not a command we sent): Cabinet Light `0_s_11` and Hall Light `0_s_1` each pushed `dev_on` true then false within a few seconds. Patches are partial: `dev_on` and `level` are present; capability flags and min/max are not. `level` can remain the last brightness while `dev_on` is false.

`/ws/dali/groups` uses the same `{addr, data}` array shape (`0_g_0`, `0_g_1`, …). A full group snapshot was seen immediately on one connect and not on a later idle connect, so do not assume an initial snapshot. Group patches include `dev_on`, `level`, `color_temp_k`, and member lists.

Wrong paths (`/ws/dali/devices/0_s_1`, query strings, trailing slash) drop the connection. Reconnect is a new socket; do not replay light-changing HTTP commands on reconnect.

## Observed in web-interface source; not independently API-tested

- POST `/dali/api/devices/{id}` with fields such as `dev_on`, `level`, `color_temp_k`.
- GET `/dali/api/scenes`.
- JSON POST helper serializes the body and uses `Content-Type: application/json`.
- Device controls use debounced writes. Basic view raw slider bounds are 0–254.

Do not present source-observed endpoints as successfully tested controls.

## Serial documentation versus HTTP

The supplied HAT documentation describes the Pi-to-HAT serial protocol, including lowercase command prefixes, diagnostics, and newline framing. The HTTP endpoint successfully accepted `h02B9` and query strings without appended newlines. Do not append serial framing or assume every HAT diagnostic command is exposed by HTTP without checking.
