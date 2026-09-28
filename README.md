# ATX LED for Home Assistant OS

Home Assistant OS custom integration for a local [ATX LED](https://atxled.com/) DALI hub. Setup discovers already commissioned fixtures, groups, and hub scenes. It does not commission, readdress, or identify devices.

This repository is meant to be added as a **HACS custom repository** until it is submitted to the default HACS store.

Requires Home Assistant 2026.8 or newer.

## Install with HACS (manual repository)

1. HACS → Integrations → the three-dot menu → **Custom repositories**.
2. Repository: `https://github.com/Vovixxx/atx-led-haos`
3. Type: **Integration**.
4. Add, then download **ATX LED**.
5. Restart Home Assistant.
6. Settings → Devices & services → Add integration → **ATX LED**.
7. Enter the hub IP address or hostname, for example `192.168.1.50`. Leave username and password blank unless the hub API requires them.

Setup only uses read-only inventory requests.

## Manual install without HACS

Copy `custom_components/atx_led` to `/config/custom_components/atx_led` on the Home Assistant OS host, restart, then add the integration as above.

## Behavior

- One light entity per commissioned DALI fixture (not buttons, IO, or relays).
- One light entity per DALI group and hub virtual group. The broadcast `all` target is not imported.
- Group display names use the hub `hue_name` when present, then a commissioned `dev_name` or addresses label before a generated `Group N` label. Name changes update existing Home Assistant group devices while user-assigned names remain in Home Assistant.
- One scene entity per hub scene that includes a DALI scene number.
- Fixture on/off uses `POST /dali/api/send-raw` Direct Arc Power Control.
- DALI group on/off uses group DAPC (`group * 2 + 0x80`). Virtual groups use the hub device `level` write.
- Brightness follows the hub UI mapping `(level - min) / (max - min)`.
- Brightness changes while a fixture is on use `POST /dali/api/devices/{id}` with `level` so the hub fade can apply. DALI groups keep using group DAPC.
- Color-temperature fixtures expose a Kelvin slider when `has_color_temp` is set. Groups expose Kelvin when known member fixtures support it; writes go to those members.
- Leftover drivers the hub cannot characterize (empty type, zero serial/firmware) stay dimmers until you open **Configure** on the integration, pick a mode, and set min/max dim and Kelvin by sight. Those values stay in Home Assistant and are not written to the hub.
- Scene recall sends DALI GO TO SCENE to a listed group or to member fixtures on one known channel. Scenes without explicit targets are unavailable for recall.
- State updates immediately from `/ws/dali/devices` and `/ws/dali/groups` when the hub reports a change. HTTP inventory (`addresses`, `devices`, best-effort `groups` and `scenes`) is still polled every 15 seconds as a backup. Failed reads become unavailable, not off.
- Hub identity currently falls back to the host address. Use Reconfigure to change the IP without recreating entities.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install pytest pytest-asyncio aiohttp ruff
.venv/bin/ruff check custom_components tests
.venv/bin/pytest tests -q
```

Discovery notes: [outputs/integration-notes/README.md](outputs/integration-notes/README.md).

## Maintainer release checks

The repository's validation workflow runs unit tests, HACS validation, and Hassfest on pushes and pull requests. Keep `pyproject.toml` and `custom_components/atx_led/manifest.json` at the same version. After validation passes, publish a GitHub release with a matching tag (for example, `v0.4.0`) so HACS can offer a versioned download. HACS can also install the default branch without a release.
