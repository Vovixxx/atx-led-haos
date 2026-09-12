# ATX LED for Home Assistant OS

Home Assistant OS custom integration for a local [ATX LED](https://atxled.com/) DALI hub. Setup discovers already commissioned lights and creates one light entity per fixture. It does not commission, readdress, or identify devices.

This repository is meant to be added as a **HACS custom repository** until it is submitted to the default HACS store.

## Install with HACS (manual repository)

1. HACS → Integrations → the three-dot menu → **Custom repositories**.
2. Repository: `https://github.com/Vovixxx/atx-led-haos`
3. Type: **Integration**.
4. Add, then download **ATX LED**.
5. Restart Home Assistant.
6. Settings → Devices & services → Add integration → **ATX LED**.
7. Enter the hub host, for example `192.168.1.50`. Leave username and password blank unless the hub API requires them.

Setup only uses read-only inventory requests.

## Manual install without HACS

Copy `custom_components/atx_led` to `/config/custom_components/atx_led` on the Home Assistant OS host, restart, then add the integration as above.

## Behavior

- One light entity per commissioned DALI fixture (not groups, buttons, IO, or relays).
- On/off and brightness use `POST /dali/api/send-raw` Direct Arc Power Control.
- Brightness follows the hub UI mapping `(level - min) / (max - min)`.
- Color-temperature fixtures expose a Kelvin slider.
- State is polled from `/dali/api/devices` every 15 seconds. Failed reads become unavailable, not off.
- Hub identity currently falls back to the host address. Use Reconfigure to change the IP without recreating entities.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install pytest pytest-asyncio aiohttp
.venv/bin/pytest tests -q
```

Discovery notes: [outputs/integration-notes/README.md](outputs/integration-notes/README.md).
