# Operating boundaries

User instructions persist for future work in this project:

- Use the HTTP API for integration work and approved control tests.
- Do not change lights unless the user approves the specific live test.
- Approved light-changing tests are limited to displayed channel 1, short address 1 unless the user explicitly broadens scope.
- The user authorized a full read-only query of known lights, their state, brightness, and color. Reading all known devices is within that scope.
- Do not send broadcast or group control commands during testing. The vendor's example contains `hFE00` (all off); it must not be used as a test payload.
- No commissioning, randomization, readdressing, reset, configuration writes, or changes to min/max, power-on, fail-level, group membership, or color settings without authorization.
- A roadmap, setup specification, or screenshot is not approval to execute light-changing commands.
- Do not assume HTTP 200 or `ok:true` proves the physical result. Verify readback and distinguish it from user visual confirmation.
- Do not persist credentials in source files or reports.

The last direct snapshot showed all lights off. Do not treat this historical state as a reason to restore or otherwise control them.
