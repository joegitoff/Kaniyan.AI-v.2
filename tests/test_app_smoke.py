"""Smoke test: the Streamlit app starts in Demo mode (sample data) without exceptions."""
import os

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def test_app_runs_in_demo_mode():
    at = AppTest.from_file(APP_PATH, default_timeout=30).run()
    at.sidebar.toggle[0].set_value(True).run()
    assert not at.exception
    assert any("SAMPLE DATA" in e.value for e in at.error)
