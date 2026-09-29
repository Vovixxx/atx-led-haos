"""Reconfigure must save the credentials that were actually validated."""

from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from atx_led.client import ATXLEDClient


@pytest.fixture
def config_flow_module(monkeypatch: pytest.MonkeyPatch):
    """Load the flow with minimal Home Assistant interfaces."""
    vol = ModuleType("voluptuous")
    vol.Schema = lambda schema: schema
    vol.Required = lambda key: key
    vol.Optional = lambda key: key

    homeassistant = ModuleType("homeassistant")
    homeassistant.__path__ = []
    config_entries = ModuleType("homeassistant.config_entries")

    class ConfigFlow:
        def __init_subclass__(cls, **_kwargs):
            pass

        def _get_reconfigure_entry(self):
            return self.entry

        def async_update_and_abort(self, entry, *, data):
            if entry.data != data:
                entry.data = data
                for listener in entry.update_listeners:
                    listener(self.hass, entry)
            return {"type": "abort", "reason": "reconfigure_successful"}

    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigFlowResult = dict
    config_entries.OptionsFlow = type("OptionsFlow", (), {})

    const = ModuleType("homeassistant.const")
    const.CONF_HOST = "host"
    const.CONF_USERNAME = "username"
    const.CONF_PASSWORD = "password"
    core = ModuleType("homeassistant.core")
    core.HomeAssistant = type("HomeAssistant", (), {})
    core.callback = lambda fn: fn
    helpers = ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    aiohttp_client = ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda _hass: None
    selector = ModuleType("homeassistant.helpers.selector")
    selector.SelectSelector = lambda config: config
    selector.SelectSelectorConfig = lambda **kwargs: kwargs
    selector.SelectSelectorMode = SimpleNamespace(DROPDOWN="dropdown")
    modules = (
        vol, homeassistant, config_entries, const, core, helpers,
        aiohttp_client, selector,
    )
    with monkeypatch.context() as patch:
        for module in modules:
            patch.setitem(sys.modules, module.__name__, module)
        sys.modules.pop("atx_led.config_flow", None)
        module = importlib.import_module("atx_led.config_flow")
        yield module
        sys.modules.pop("atx_led.config_flow", None)


@pytest.mark.parametrize(
    ("submitted", "expected_username", "expected_password"),
    [
        ({"username": "", "password": ""}, None, None),
        ({}, None, None),
        ({"username": "new-user", "password": "new-secret"}, "new-user", "new-secret"),
    ],
)
async def test_reconfigure_saves_validated_auth_and_reloads(
    config_flow_module,
    monkeypatch: pytest.MonkeyPatch,
    submitted: dict[str, str],
    expected_username: str | None,
    expected_password: str | None,
) -> None:
    entry = SimpleNamespace(
        entry_id="entry-1",
        unique_id="atx_led_old-host",
        data={"host": "old-host", "username": "old-user", "password": "old-secret", "extra": 1},
        update_listeners=(
            lambda hass, updated_entry: hass.config_entries.reloads.append(updated_entry.entry_id),
        ),
    )
    flow = config_flow_module.ATXLEDConfigFlow()
    flow.entry = entry
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(reloads=[]))
    validated = []

    async def validate(_hass, host, username, password):
        validated.append((host, username, password))
        return host, 4

    monkeypatch.setattr(config_flow_module, "_validate_hub", validate)
    result = await flow.async_step_reconfigure({"host": "new-host", **submitted})

    assert result == {"type": "abort", "reason": "reconfigure_successful"}
    assert validated == [("new-host", expected_username, expected_password)]
    assert entry.data["host"] == "new-host"
    assert entry.data["extra"] == 1
    assert entry.unique_id == "atx_led_old-host"
    assert flow.hass.config_entries.reloads == ["entry-1"]
    client = ATXLEDClient(
        host=entry.data["host"], session=None,
        username=entry.data.get("username"), password=entry.data.get("password"),
    )
    assert client._username == expected_username
    assert client._password == expected_password
    if expected_username is None:
        assert "username" not in entry.data
        assert "password" not in entry.data
