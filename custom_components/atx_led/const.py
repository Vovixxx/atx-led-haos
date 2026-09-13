"""Constants for the ATX LED integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "atx_led"
MANUFACTURER = "ATX LED"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=15)
HUB_MODEL = "Smart Hub"

ATTR_DALI_CHANNEL = "dali_channel"
ATTR_DALI_SHORT_ADDRESS = "dali_short_address"
ATTR_DALI_STATUS = "dali_status"
ATTR_DALI_GROUP_ADDRESS = "dali_group_address"
ATTR_DALI_GROUP_KIND = "dali_group_kind"
ATTR_DALI_MEMBERS = "dali_members"
ATTR_DALI_SCENE = "dali_scene"
ATTR_DALI_STATE_SOURCE = "dali_state_source"

CONF_UNSIGNED_OVERRIDES = "unsigned_overrides"
CONF_DEVICE_ID = "device_id"
MODE_DIMMER = "dimmer"
MODE_CCT = "cct"
MODE_RGB = "rgb"
MODE_RGB_CCT = "rgb_cct"
UNSIGNED_MODES = (MODE_DIMMER, MODE_CCT, MODE_RGB, MODE_RGB_CCT)
DEFAULT_KELVIN_MIN = 2700
DEFAULT_KELVIN_MAX = 5000
