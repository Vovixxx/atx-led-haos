# ATX LED integration notes

Updated 2026-09-12. Custom integration: `custom_components/atx_led` (0.3.0, HACS custom repository).

## Start here

- [API findings](API.md): verified HTTP and WebSocket behavior.
- [Brightness mapping](TESTS-AND-BRIGHTNESS.md): locked hub UI conversion and test history.
- [Setup and entities](SETUP-AND-ENTITIES.md): discovery and capability-based lights.
- [Roadmap](ROADMAP.md): shipped work and later items.
- [Operating boundaries](OPERATING-BOUNDARIES.md): live-test constraints.
- [Sources](SOURCES.md): vendor and Home Assistant references.

## Shipped behavior

Setup discovers already commissioned DALI fixtures, groups, and hub scenes. It creates one light entity per eligible fixture and group, and one scene entity per named scene. Group names prefer `hue_name` when the hub provides one. Group on/off comes from `/dali/api/groups` or member fixtures. Group Kelvin is exposed when members support color temperature. Fixture and DALI-group on/off use `send-raw`. Fixture color temperature and dim-while-on use the hub device endpoint. State is pushed on `/ws/dali/devices` and `/ws/dali/groups` with HTTP polling as backup.
