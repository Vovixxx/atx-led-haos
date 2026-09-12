"""Test path setup that loads atx_led submodules without Home Assistant."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPONENT_DIR = ROOT / "custom_components" / "atx_led"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


def pytest_configure() -> None:
    """Expose custom_components/atx_led as the atx_led package without running HA __init__."""
    if "atx_led" in sys.modules and getattr(sys.modules["atx_led"], "__path__", None):
        return
    pkg = types.ModuleType("atx_led")
    pkg.__path__ = [str(COMPONENT_DIR)]
    pkg.__file__ = str(COMPONENT_DIR / "__init__.py")
    pkg.__package__ = "atx_led"
    sys.modules["atx_led"] = pkg


@pytest.fixture
def fixture_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def addresses_payload() -> dict:
    return json.loads((FIXTURE_DIR / "addresses.json").read_text())


@pytest.fixture
def devices_payload() -> dict:
    return json.loads((FIXTURE_DIR / "devices.json").read_text())
