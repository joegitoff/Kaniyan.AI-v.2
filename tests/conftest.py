"""Makes the project root importable and keeps tests fast/offline."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Retry back-off must not slow the tests down."""
    import data_service
    monkeypatch.setattr(data_service.time, "sleep", lambda s: None)
