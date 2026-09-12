# Brightness mapping

The integration maps Home Assistant brightness to DALI using the hub UI scale, not the DALI logarithmic curve:

`(raw - min_level) / (max_level - min_level)`

Locked after the address-1 185 → 68% observation and user confirmation in Home Assistant. 0 is off. 255 is MASK and is never sent.

## Earlier test history

1. Browser UI test: set Hall Light (channel 1/address 1) percentage field to 10. A page reload showed on and 10%. This used the hub UI, not a Home Assistant integration.
2. User requested API control instead and restricted light-changing tests to address 1 with approval.
3. Approved raw API test: POST `{"channel":0,"commands":["h02B9"]}`. Hub returned HTTP 200 and `{"ok":true,"responses":["N"]}`. Raw level was 185. User reported the UI showed **68%**, then manually turned the light off.
4. Read-only address inventory GET succeeded.
5. Read-only address-1 status/actual/max/min queries returned `J00,J00,JFA,J32`.
6. Full read-only inspection: all 39 known light addresses responded to status/actual/max/min queries. All actual levels were 0. Raw results and per-address timestamps are saved in `../dali-light-query.json`.
7. Home Assistant custom integration confirmed the min/max linear mapping against the hub UI.

## Correction to the original brightness assumption

The command at raw level 185 was calculated for approximately 15% physical output under the standard DALI logarithmic curve. It did not match the user's intended **hub UI percentage**. These two meanings of percentage must not be conflated.

Raw DALI maximum arc level is 254. Value 255 is special (MASK/stop-fade semantics), not normal full brightness. Home Assistant's own 0–255 brightness representation must be translated rather than copied blindly to raw DALI.

An initial explanation using `185/254` was incomplete: it predicts about 73%, not the observed 68%.

The locked mapping uses the fixture's configured minimum and maximum, for example min 50 and max 250:

`(185 - 50) / (250 - 50) * 100 = 67.5%`, rounding to 68%.

## Observed source snippets

The basic-view slider uses raw limits 0–254. The Advanced page source includes presets `[[254,"100%"],[191,"75%"],[127,"50%"],[63,"25%"],[0,"0%"]]`, showing that different UI surfaces may use different mappings.

A function used in estimated power calculation was inspected:

```javascript
function daliOutputPercentage(daliValue) {
  const startingValue = 0.001;
  const growthFactor = 1.0275;
  if (daliValue === 0) return 0;
  if (daliValue === 1) return startingValue;
  if (daliValue === 254) return 1;
  return startingValue * Math.pow(growthFactor, daliValue - 1);
}
```

This is **not** the hub percentage-slider conversion used by this integration.

## State freshness and colors

Hub record for Hall Light retained `level:185` while `dev_on:false`; direct actual level was 0. Treat stored brightness as potentially a last requested/remembered level.

Color temperature control uses stored hub Kelvin values and the hub device endpoint. User confirmed this looks correct in Home Assistant. DT8 register-level queries remain unused.

Eight non-color devices returned `03`: Cabinet Light, Hallway Light, Mirror Light, Cove Light, Arch Light, Atrium Light, Peninsula Light, Ceiling Strip. The flags warrant diagnosis later; do not label them unreachable, because each replied.
