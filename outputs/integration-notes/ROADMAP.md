# Integration roadmap

## 1. Protocol foundation — partially complete

Completed: raw control accepted and visually confirmed (percentage mismatch); inventory endpoints verified; direct state/level/min/max queries verified on all 39 known lights; hub color-capability snapshot saved.

Remaining: hub identity and authentication variants. Brightness UI mapping is locked. WebSocket push is verified.

Acceptance: known raw command and displayed percentage agree; readback clearly distinguishes stored versus actual state. Live control tests require approval.

## 2. Async API client — implemented (offline)

HTTP discovery, normalized device data, individual control encoding, error decoding and serialized send-raw requests live in `custom_components/atx_led`. Mock-based pytest coverage is in `tests/`. Live hub identity and authentication variants remain later work.

Acceptance: mock-based tests pass without operating lights; partial device failures do not discard the entire inventory.

## 3. Home Assistant first release — code complete, not installed

Manifest, config flow, hub device registration, automatic light entities, coordinator polling, on/off and brightness are in `custom_components/atx_led`. Color-temperature writes use the hub device endpoint and were confirmed in Home Assistant. Validate against the user's exact installed HA version, which is not yet recorded.

Acceptance: HA OS loads the custom integration, setup creates eligible entities without controlling lights, and approved address-1 tests work.

## 4. State synchronization — implemented

The coordinator listens on `/ws/dali/devices`, merges partial `{addr, data}` patches into known lights, and reconnects without replaying controls. HTTP inventory polling every 15 seconds remains the backup and the path for newly discovered fixtures.

Acceptance: HA reflects external changes and recovery causes no unintended controls.

## 5. Color and expanded features

Add verified color temperature for supported fixtures. Later add groups, scenes and transitions, with separately approved live testing. RGB remains deferred until supported hardware and API behavior can be tested.

## 6. Packaging

Provide an installable custom component, release notes, HA OS installation/removal instructions, redacted diagnostics and compatibility tests. HACS distribution is optional later work.

First-release integration code is in `custom_components/atx_led`. It has not been installed on Home Assistant OS yet. This folder remains the factual discovery record.
