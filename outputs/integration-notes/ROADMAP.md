# Integration roadmap

Shipped in **0.3.0** as a HACS custom repository: https://github.com/Vovixxx/atx-led-haos

## Done

1. **Protocol** — verified HTTP inventory, `send-raw` DAPC, brightness mapping locked to hub UI `(level - min) / (max - min)`, color temperature via the hub device endpoint, `/ws/dali/devices` push verified. Dimming while on uses the hub `level` write so configured fade applies.
2. **Client** — async discovery, encoding/decoding, serialized control, error handling, mock tests.
3. **Home Assistant first release** — config flow, hub device, automatic light entities, on/off, brightness, Kelvin for supported fixtures.
4. **State sync** — live WebSocket patches plus 15-second HTTP poll backup. Reconnect does not replay controls. `iot_class` is `local_push`.
5. **Packaging (manual)** — HACS custom-repo layout, brand icons, install docs, redacted diagnostics.
6. **Groups and scenes** — DALI groups and virtual groups as lights, `/ws/dali/groups` push, hub scene entities recalled without broadcast.

## Later

- Live-verify group DAPC, virtual-group device writes, and GET `/dali/api/scenes` payload shape on a hub.
- RGB, if a hub advertises supported fixtures.
- Buttons, IO, and relay platforms.
- Diagnose DALI status flags when fixtures report driver or lamp-failure bits.
- Stable hub identity that is not the IP address.
- Default HACS store listing.
