"""Constants for the ATX LED integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "atx_led"
MANUFACTURER = "ATX LED"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=15)
DEFAULT_TIMEOUT = 10.0
HUB_MODEL = "Smart Hub"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

ATTR_DALI_CHANNEL = "dali_channel"
ATTR_DALI_SHORT_ADDRESS = "dali_short_address"
ATTR_DALI_STATUS = "dali_status"
