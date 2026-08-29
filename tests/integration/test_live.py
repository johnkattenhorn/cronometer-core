"""Live integration test — opt-in via ``-m integration``.

Hits the real Cronometer export for today's daily nutrition. Skipped unless
CRONOMETER_USERNAME and CRONOMETER_PASSWORD are present in the actual
environment. Never runs by default because it carries the ``integration``
marker (deselected by the default addopts / marker config).
"""
from __future__ import annotations

import os

import pytest

from cronometer_core.client import CronometerClient
from cronometer_core.config import resolve_auth, resolve_config
from cronometer_core.operations import get_daily_nutrition


@pytest.mark.integration
def test_live_get_daily_nutrition():
    if not (os.environ.get("CRONOMETER_USERNAME") and os.environ.get("CRONOMETER_PASSWORD")):
        pytest.skip("Cronometer credentials not set; skipping live integration test.")
    config = resolve_config()
    auth = resolve_auth(config)
    client = CronometerClient(config, auth=auth, session=auth.session)
    result = get_daily_nutrition(client)
    assert isinstance(result, list)
