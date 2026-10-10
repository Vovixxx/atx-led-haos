# One-call turn-on: brightness and colour together

Date: 2026-10-10  
Status: approved, released in 0.5.6  
Integration: `custom_components/atx_led`

## Problem

Since 0.5.4 a Home Assistant turn-on with brightness and colour temperature sends the group level (raw DAPC) and then,
about 26 ms later, the hub colour request `POST /dali/api/devices/{id}` with `color_temp_k`. Adaptive Lighting
(Downstairs profile, `intercept: true`) adds brightness and colour to every turn-on, so wall-button presses take this path.

On the spot drivers (Family Room, and the foyer and kitchen spots with the same settings) the colour request freezes the
running fade. The lights stay dim while the hub, and so Home Assistant, report full. A second press comes on full because
the colour write is skipped when every member already has the target colour.

The hub colour request also takes 0.4–1.0 s, and on the MiBoxer drivers (unsigned DT8 drivers the hub does not
recognise as tunable) it lands off target: 4500 K became 4292 K and 3500 K became 3344 K.

## Goal

Buttons and toggles through Home Assistant, with Adaptive Lighting on, behave like a plain wall switch: the light comes
on at the right brightness and colour in one fade, every time, with no visible colour step and no slower than today.
Reliability comes before speed. The current driver fade (`fade_up` 3, about 1.4 s) stays.

## Owner decisions

- Keep the current fade; reliability over speed.
- Home Assistant is the source of truth for colour. The hub only needs correct level and on/off; the Crestron fallback
  path controls level only.
- MiBoxer colour support through the integration's unsigned overrides is intended
  (`2026-09-12-unsigned-driver-overrides-design.md`). Never derive colour support from the hub's `has_color_temp` flag.
- Out of scope: the Crestron fallback, the ATX app, and Adaptive Lighting settings (no changes needed).

## Evidence (live probe, 2026-10-10)

Actual level and colour were read back from the drivers with DALI queries (`A0` actual level; DT8 `QUERY COLOUR VALUE`
selector 2) three seconds after each command. Two members per driver type.

| Trial, from off unless noted | Spot drivers (group 6: sa 31, 37) | MiBoxer (sa 17, sa 11) |
|---|---|---|
| DAPC full only | 250 / 250 | 254 / 254 |
| DAPC full, hub colour request about 26 ms later | **88 / 118, then 163 / 179 (frozen)** | 254, colour off target |
| DAPC full, wait 2.5 s, hub colour request | 250, colour correct | 254, colour off target |
| One `send-raw`: temporary colour + DAPC full | 250, colour exact (2700, 5000 K) | 254, colour exact |
| Same while on: temporary colour + DAPC 200 | 200, 4000 K exact | 200, 4000 K exact |

Further measurements:

- `send-raw` timing: one frame about 240 ms, four colour frames about 380 ms. So loading colour first delays the start of
  the fade by about 140 ms.
- Dimming while on, 253 to 120, sampled every 240 ms: on the spot drivers raw DAPC fades over about 1.4 s, the same curve
  as the hub level request, and avoids the hub request's 0.5 s delay. The MiBoxer reports the target level at once with
  either method, so the hub request gains nothing there either.
- The hub does not learn colour from raw DT8 frames. Its `color_temp_k` record keeps the last value set through its own
  colour request (sa 17 and 11 read 3500 K while the drivers were at 2703 K).

## Design

### Command model

Every on-command for a fixture, DALI group or virtual group is one `send-raw` call that ends in DAPC:

```
hA3{mirek LSB}  hC3{mirek MSB}  hC108  h{addr cmd}E7   # DTR0, DTR1, ENABLE DEVICE TYPE 8, SET TEMPORARY COLOUR TEMPERATURE
h{addr dapc}{level}                                   # DAPC applies level and the temporary colour in one fade
```

- `mirek = round(1_000_000 / kelvin)`, after clamping Kelvin to the light's range.
- Address bytes: short address `sa*2` (DAPC) and `sa*2+1` (command); DALI group `0x80+g*2` and `0x81+g*2`.
- Golden example, group 6 at 2700 K and level 253: `hA372 hC301 hC108 h8DE7 h8CFD`.

| Call | Frames sent |
|---|---|
| On from off, no brightness | colour (if any, see below) + DAPC at the restore level (`_restore_level`, unchanged) |
| On with brightness | colour (if any) + DAPC at the converted level |
| Colour only, light already on | colour + DAPC at the light's current level (re-sending the same level applies the colour without starting a level fade) |
| Off | DAPC 0 |

- **Colour frames are left out** when the light has no colour support or the remembered colour already equals the target.
  Then the call is a single DAPC, as fast as today.
- **Virtual groups** get the same frames per member. All members on one channel go in one `send-raw` call, in member
  order; a group spanning channels makes one call per channel.
- **The hub colour request (`POST … color_temp_k`) and the hub level request (`POST … level`) are no longer used** for
  control. `async_set_group_color_temp`, `async_set_color_temp_k` and `async_set_device_level` go, together with
  `use_hub_device_level_for_brightness` and the 0.5.5 group-write fallback.
- **Colour support comes from the fixture:**
  - known DT8 fixtures: from the hub capabilities, as today;
  - unsigned fixtures: from the unsigned override mode;
  - DALI groups: any colour-capable member.
- Scenes are unchanged.

### State

- **Colour belongs to Home Assistant.**
  - The coordinator keeps a written-colour map per fixture.
  - A group write also records the colour on each member.
  - This map overrides the hub's `color_temp_k` in every poll and push merge.
- **The map survives restarts.** It is restored through the light entity's last state (`RestoreEntity`).
- **Fixtures never written** get their colour once at start-up from the driver (`QUERY COLOUR VALUE`, queried one fixture
  at a time), never from the hub record. If the query fails, the colour shows as unknown until the first write.
- **Level and on/off still come from the hub:** WebSocket patches and the 15 s poll. The hub tracks DAPC sent by anyone,
  including the Crestron fallback.
- **The display updates immediately:**
  - After the hub accepts a call, the entity shows the intended level and colour at once.
  - A poll or patch that started before that write cannot overwrite it. Each write records a timestamp; older data is
    ignored for that light.
- **Group colour:** a group shows the colour it last wrote. After a single-member write, it shows a colour only while all
  members agree (the 0.5.2 rule, now applied to the written-colour map).
- **Failure:**
  - A refused or timed-out call raises `HomeAssistantError` and leaves the written-colour map unchanged.
  - The level is then refreshed from the hub.
  - Each press is one call, so the hub never holds half of a command.

### Press handling

- **One queue per target** (fixture or group id), in order.
  - A newer command for the same target replaces one still waiting to go out.
  - A command already being sent completes.
- **The client's hub lock stays** (the hub sends one frame at a time). With the slow requests gone, the longest wait
  behind another light is about 0.4 s.
- **Toggle reads the intended state**, so a quick double press is on, then off.
- **Adaptive Lighting:**
  - Its injected brightness and colour use the same one-call path.
  - Periodic adapts are usually DAPC-only, because the colour skip applies.
  - Its `transition` is ignored as today (`supported_features` stays 0); the driver fade applies.

## Testing

Unit tests (pytest, existing `tests/` layout):

- Frame builder: the golden frames from the probe for group, short address, Kelvin clamping and mirek rounding.
- One test per command-table row, for fixtures, DALI groups and virtual groups.
- Colour skip when the remembered colour matches; no colour frames for non-colour lights.
- The written-colour map beats a stale hub `color_temp_k` in poll and WebSocket merges.
- A stale poll cannot overwrite the immediate state; restore after restart.
- A failed call leaves the written-colour map unchanged and refreshes the level.
- Queue: latest waiting command wins, the in-flight one completes; double-press toggle gives on, then off.
- Remove tests for the deleted hub-request paths.

Live acceptance after release (owner yes; the 2026-10-10 probe method):

- **Lights:** Family Room spots (group 6), foyer spots, kitchen arch (sa 17) and glass cabinet (sa 11); this covers all
  three driver types.
- **Before the run:** pause Adaptive Lighting on these lights with `set_manual_control`, and hand control back afterwards.
- **The run:** from off, `light.turn_on` with brightness and Kelvin through Home Assistant, then read back the actual level
  and colour from the drivers. Five times per light at different Kelvin values, plus one colour-only change while on and a
  double-press toggle.
- **Pass:** full level and target colour (±1 mirek) every time; Home Assistant state matches the drivers.
- **With the owner:** the owner presses Family Room Button 1 several times. Each press must show one `send-raw` call in the
  hub log (`DALI-7f59` in Graylog). Report the time from the button event to the hub call.

## Open check

- The owner confirms by eye whether the MiBoxer strips (arch, cabinet) fade or jump when dimmed while on. Their query
  reports the target at once with both methods, so this does not change the design. It only tells us whether they have a
  fade at all.

## Tasks

Test first, one commit per task. Run `uv run --extra dev pytest -q` and `uv run --extra dev ruff check custom_components tests`.

1. **Frame builder** (`protocol.py`): temporary-colour frames for a short address and a DALI group, Kelvin clamp and mirek
   rounding, and a builder that returns the full frame list for one command. Golden tests from the probe.
2. **Client call** (`client.py`): one method that sends a built frame list through `send-raw` under the existing lock;
   remove `async_set_color_temp_k`, `async_set_group_color_temp`, `async_set_device_level` and their helpers.
3. **Lights and groups** (`light.py`, `brightness.py`): fixture, DALI group and virtual group turn-on and turn-off use the
   command table and the colour skip; remove `use_hub_device_level_for_brightness`.
4. **Colour state** (`coordinator.py`, `models.py`, `light.py`): the written-colour map overrides the hub colour in poll
   and push merges; start-up driver colour read for never-written fixtures; restore through `RestoreEntity`; write
   timestamps so older hub data cannot overwrite the immediate state; failure handling.
5. **Queue and toggle**: per-target queue (latest waiting command wins), toggle from the intended state.
6. **Docs and release prep**: `outputs/integration-notes/API.md` (raw colour path, the hub requests no longer used and
   why), `README.md` if behaviour text changes, version 0.5.6 in `manifest.json` and `pyproject.toml`.
