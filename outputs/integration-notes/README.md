# ATX LED integration notes

Updated 2026-09-12. Custom integration: `custom_components/atx_led` (0.2.0, HACS custom repository).

## Start here

- [API findings](API.md): verified HTTP and WebSocket behavior.
- [Brightness mapping](TESTS-AND-BRIGHTNESS.md): locked hub UI conversion and test history.
- [Setup and entities](SETUP-AND-ENTITIES.md): discovery and capability-based lights.
- [Roadmap](ROADMAP.md): shipped work and later items.
- [Operating boundaries](OPERATING-BOUNDARIES.md): live-test constraints.
- [Sources](SOURCES.md): vendor and Home Assistant references.

## Shipped behavior

Setup discovers already commissioned DALI fixtures and creates one light entity per eligible record. It does not commission, randomize, or readdress the network. On/off and brightness use `send-raw`. Color temperature uses the hub device endpoint. State is pushed on `/ws/dali/devices` with HTTP polling as backup.
