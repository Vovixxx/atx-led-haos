# Operating boundaries

- Use the HTTP API for integration work and approved control tests.
- Do not change lights unless the user approves the specific live test.
- Do not send broadcast or group control commands during testing. Vendor examples may include `hFE00` (all off); never use that as a test payload.
- No commissioning, randomization, readdressing, reset, configuration writes, or changes to min/max, power-on, fail-level, group membership, or color settings without authorization.
- A roadmap, setup specification, or screenshot is not approval to execute light-changing commands.
- Do not assume HTTP 200 or `ok:true` proves the physical result. Verify readback and distinguish it from user visual confirmation.
- Do not persist credentials in source files or reports.
