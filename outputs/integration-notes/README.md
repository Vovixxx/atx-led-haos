# ATX LED Home Assistant integration starter

Updated 2026-09-12. Target: local ATX LED hub at `http://192.168.1.50`, Home Assistant OS (user describes version as latest; exact Core version not recorded).

This folder is the discovery record and development specification. The first-release custom integration lives in `custom_components/atx_led`. It has not yet been installed on the Home Assistant OS host.

## Start here

- [API findings](API.md): verified endpoints, request formats, response decoding, and source-code observations.
- [Test history and brightness](TESTS-AND-BRIGHTNESS.md): what actually happened, corrections, and open questions.
- [Setup and entity specification](SETUP-AND-ENTITIES.md): automatic discovery and capability-based entity creation.
- [Roadmap](ROADMAP.md): implementation and acceptance milestones.
- [Operating boundaries](OPERATING-BOUNDARIES.md): required constraints for future live tests.
- [Sources](SOURCES.md): official references and saved user screenshots.
- [Full inventory report](../dali-light-inventory.html).
- [Full query snapshot](../dali-light-query.json): raw hub objects, per-address readbacks, timestamps, and normalized summaries.
- [Hub device snapshot](hub-devices.json) and [address inventory](hub-addresses.json).

## Confirmed foundation

The hub's HTTP API accepts raw DALI commands. GET endpoints expose the known light inventory, names, capabilities, and stored state. All 39 known lights on displayed channel 1 replied to direct read-only status/level queries. This is enough to begin a native local integration without Hue.

During initial setup, read the known inventory and automatically create light entities with capabilities derived from each device record. This means discovery of already commissioned devices; do not automatically commission, randomize, or readdress the DALI network.

## Snapshot findings

39 lights responded; all directly reported actual level 0 (off). 31 advertise color-temperature control, none advertise RGB. Stored temperatures: eight at 4065 K, 22 at 2702 K, one at 4716 K. Eight non-color lights returned status 03 (driver/lamp fault bits). These are historical snapshot findings, not live status.
