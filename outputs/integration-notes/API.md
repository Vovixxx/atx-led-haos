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
- Configuration: `groups`, `fade_up`, `fade_down`, `power_on_level`, `fail_level`, `hue_hidden`.

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

Since 0.5.6 every control is one `POST /dali/api/send-raw` call that ends in DAPC, so level and colour apply in one fade:

```
hA3{mirek LSB}  hC3{mirek MSB}  hC108  h{cmd addr}E7   # DTR0, DTR1, ENABLE DEVICE TYPE 8, SET TEMPORARY COLOUR TEMPERATURE
h{dapc addr}{level}                                   # DAPC applies level and the temporary colour
```

`mirek = round(1_000_000 / kelvin)` after clamping Kelvin to the light's range. Short address `sa`: DAPC byte `sa*2`, command byte `sa*2+1`; DALI group `g`: `0x80+g*2` and `0x81+g*2`. Golden: group 6, 2700 K, level 253 is `["hA372","hC301","hC108","h8DE7","h8CFD"]`. Colour frames are left out when the light has no colour support or the remembered colour already equals the target (a single DAPC). A virtual group sends the same frames per member, all members on one channel in one call. Off is DAPC 0.

Verified 2026-10-10 (driver readback, `docs/superpowers/specs/2026-10-10-dali-turn-on-design.md`): this works on every driver type, including the unsigned MiBoxer drivers, which land exactly on target.

The hub requests are **no longer used for control**:

- `POST /dali/api/devices/{id}` with `color_temp_k` (and the group form that fans out to members): on the spot drivers, sent ~26 ms after a DAPC, it freezes the running fade (lights stay dim while the hub reports full); it takes 0.4–1.0 s and lands off target on the MiBoxer drivers (4500 K became 4292 K).
- `POST /dali/api/devices/{id}` with `level`: gains nothing over raw DAPC (same fade curve on the spot drivers, and it adds ~0.5 s).

The hub does not learn colour from raw DT8 frames: its `color_temp_k` keeps the last value set through its own colour request. So Home Assistant owns colour: the integration keeps a written-colour map (restored through the light entity's last state), reads colour once from the driver at start-up for fixtures never written, and ignores the hub's `color_temp_k`. Level and on/off still come from the hub (WebSocket and the 15 s poll).

Driver readback of colour: DT8 `QUERY COLOUR VALUE` for colour temperature (`["hA302","hC108","h{addr*2+1:02X}FA","h{addr*2+1:02X}98"]`, MSB then DTR0 LSB, in mireds). Readings taken within a second can still be mid-fade.

Observed in web-interface source; not independently used by this integration:

- POST `/dali/api/devices/{id}` with `dev_on`.
- Device controls use debounced writes. Basic view raw slider bounds are 0–254.

GET `/dali/api/scenes` is now requested during inventory. A missing or unusable payload must not fail light or group discovery. Scene records are parsed from an object map, a `Scenes` list, or `{key,value}` items. Recall uses DALI GO TO SCENE (`0x10`–`0x1F`) on a listed group or on member short addresses. Do not send broadcast `hFFxx` or `hFE00`.

GET `/dali/api/groups` is requested best-effort. Records on this hub (and likely others) use `dev_name` such as `Group 5`, a friendlier `hue_name` when Hue is linked, `dev_on`/`level`, and `device_ids` as short addresses rather than `0_s_*` member lists. `/dali/api/devices` may omit group keys entirely. A missing groups endpoint must not fail inventory.

Display names prefer `hue_name`, then `dev_name`, then the `/dali/api/addresses` label. That order is hub-agnostic: Hue-linked installs get room names, others keep `dev_name`.

Group DAPC encoding follows the HAT docs: address byte `group * 2 + 0x80` (0x80–0x9E), command byte `group * 2 + 0x81` (0x81–0x9F). Virtual groups have no DALI group address; they send the same frames per member. Do not treat a virtual group id as interchangeable with the DALI group that shares the same numeric index.

Group records are often missing `has_color_temp`. If member fixtures advertise color temperature, the group light exposes Kelvin. A Kelvin change is part of the group's one send-raw call, and the integration records it on each member; the group shows a colour only while its colour members agree. Hub group `dev_on`/`level` win when present; otherwise on/off is derived from members until `/ws/dali/groups` sends a patch.

Do not present remaining untested source-observed endpoints as integration controls.

## Serial documentation versus HTTP

HAT documentation describes the Pi-to-HAT serial protocol, including lowercase command prefixes, diagnostics, and newline framing. The HTTP endpoint accepts `h` frames without appended newlines. Do not append serial framing or assume every HAT diagnostic command is exposed by HTTP without checking.
