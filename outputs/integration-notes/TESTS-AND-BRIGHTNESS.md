# Brightness mapping

The integration maps Home Assistant brightness to DALI using the hub UI scale, not the DALI logarithmic curve:

`(raw - min_level) / (max_level - min_level)`

Locked after verifying a fixture at raw 185 with min 50 and max 250 displayed as **68%** in the hub UI. 0 is off. 255 is MASK and is never sent.

## Earlier test history

1. Setting a hub UI percentage field to 10 showed on and 10% after reload. That used the hub UI, not this integration.
2. Approved raw API test: POST `{"channel":0,"commands":["h02B9"]}`. Hub returned HTTP 200 and `{"ok":true,"responses":["N"]}`. Raw level was 185. The hub UI showed **68%**.
3. Read-only address inventory GET succeeded.
4. Read-only status/actual/max/min for short address 1 returned `J00,J00,JFA,J32`.
5. Read-only queries of other known light addresses also succeeded. A stored `level` of 0 does not by itself mean the fixture is missing.
6. Home Assistant confirmed the min/max linear mapping against the hub UI.

## Correction to the original brightness assumption

The command at raw level 185 was calculated for approximately 15% physical output under the standard DALI logarithmic curve. It did not match the **hub UI percentage**. These two meanings of percentage must not be conflated.

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

A hub record can retain a last `level` while `dev_on` is false; a direct actual-level query can return 0. Treat stored brightness as last requested/remembered, not proof the lamp is emitting.

Color temperature control uses stored hub Kelvin values and `POST /dali/api/devices/{id}` with `color_temp_k`. DT8 register-level queries remain unused.

Fixtures may report DALI status `03` (driver/lamp-failure bits) and still reply. Do not label those unreachable from the status byte alone.
