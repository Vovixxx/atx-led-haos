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
- One scene entity per saved hub scene; explicitly numbered DALI scenes are also supported.
- Every turn-on, dim and turn-off is one `POST /dali/api/send-raw` call that ends in Direct Arc Power Control. A colour change puts the temporary-colour frames in front of the same call, so brightness and colour apply in one fade.
- DALI groups use group DAPC (`group * 2 + 0x80`). Virtual groups send the same frames per member.
- Brightness follows the hub UI mapping `(level - min) / (max - min)`.
- A quick second press replaces a command still waiting for the same light or group; the one being sent completes. Toggle follows the intended state, so a fast double press is on, then off.
- Color-temperature fixtures expose a Kelvin slider when `has_color_temp` is set. Home Assistant owns the colour: it remembers what it last wrote (kept across restarts) and reads each never-written fixture once from its driver at start-up; the hub's `color_temp_k` is not used. Groups expose Kelvin when known member fixtures support it, and report a colour while their colour members agree.
- Leftover drivers the hub cannot characterize (empty type, zero serial/firmware) stay dimmers until you open **Configure** on the integration, pick a mode, and set min/max dim and Kelvin by sight. Those values stay in Home Assistant and are not written to the hub.
- Saved hub scenes from `/dali/api/scenes` activate through `POST /dali/api/scenes/{id}/trigger`. Explicitly numbered DALI scenes use GO TO SCENE for their listed group or member fixtures.
- State updates immediately from `/ws/dali/devices` and `/ws/dali/groups` when the hub reports a change. HTTP inventory (`addresses`, `devices`, best-effort `groups` and `scenes`) is still polled every 15 seconds as a backup. The sockets answer the hub's own pings and reconnect after 120 seconds of silence; the hub does not answer client pings. Failed reads become unavailable, not off.
- Hub identity currently falls back to the host address. Use Reconfigure to change the IP without recreating entities.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install pytest pytest-asyncio aiohttp ruff==0.14.6
.venv/bin/ruff check custom_components tests
.venv/bin/pytest tests -q
```

Discovery notes: [outputs/integration-notes/README.md](outputs/integration-notes/README.md).

## Maintainer release checks

The repository's validation workflow runs unit tests, HACS validation, and Hassfest on pushes and pull requests. Keep `pyproject.toml` and `custom_components/atx_led/manifest.json` at the same version. After validation passes, publish a GitHub release with a matching tag (for example, `v0.4.0`) so HACS can offer a versioned download. HACS can also install the default branch without a release.
