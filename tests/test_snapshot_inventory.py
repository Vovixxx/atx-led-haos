import json
from pathlib import Path

import pytest

from atx_led.models import reconcile_lights

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "integration-notes"
ADDRESSES = SNAPSHOT_DIR / "hub-addresses.json"
DEVICES = SNAPSHOT_DIR / "hub-devices.json"


@pytest.mark.skipif(
    not ADDRESSES.exists() or not DEVICES.exists(),
    reason="local hub inventory snapshots are not shipped in the public repo",
)
def test_saved_hub_snapshot_discovers_39_individual_lights() -> None:
    addresses = json.loads(ADDRESSES.read_text())
    devices = json.loads(DEVICES.read_text())
    lights = reconcile_lights(addresses, devices)
    assert len(lights) == 39
    assert sum(light.has_color_temp for light in lights) == 31
    assert sum(light.has_color_rgb for light in lights) == 0
    assert all(not light.is_button for light in lights)
    suffixes = [light.unique_suffix for light in lights]
    assert len(suffixes) == len(set(suffixes))
    assert "0_1" in suffixes
