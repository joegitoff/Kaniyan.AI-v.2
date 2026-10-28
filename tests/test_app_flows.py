"""End-to-end Streamlit tests (AppTest). External services are mocked; no network or API key needed."""
import os

import pytest

pytest.importorskip("streamlit")
import streamlit as st
from streamlit.testing.v1 import AppTest

import data_service as ds
import sample_data as sd

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")
LOC = ds.Location("Chennai", 13.08, 80.27, "India", "Tamil Nadu", "Asia/Kolkata")


@pytest.fixture(autouse=True)
def fresh_caches(monkeypatch):
    st.cache_resource.clear()
    st.cache_data.clear()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(ds, "search_locations", lambda q, count=5: [LOC])
    yield
    st.cache_resource.clear()
    st.cache_data.clear()


def mock_providers(monkeypatch, weather_error=None, air_error=None, counter=None):
    def fw(loc, forecast_days=7):
        counter is not None and counter.__setitem__("w", counter["w"] + 1)
        if weather_error:
            raise weather_error
        return ds.parse_weather(sd.make_sample_weather_raw(), loc)

    def fa(loc, forecast_days=5):
        if air_error:
            raise air_error
        return ds.parse_air_quality(sd.make_sample_air_raw(), loc)
    monkeypatch.setattr(ds, "fetch_weather", fw)
    monkeypatch.setattr(ds, "fetch_air_quality", fa)


def run():
    return AppTest.from_file(APP, default_timeout=60).run()


def text(at):
    parts = [m.value for m in at.markdown] + [c.value for c in at.caption] + [w.value for w in at.warning] + [e.value for e in at.error]
    return "\n".join(parts)


def test_live_mode_with_mocked_data_shows_risk_cards_and_live_status(monkeypatch):
    mock_providers(monkeypatch)
    at = run()
    assert not at.exception and len(at.tabs) == 7
    t = text(at)
    assert "Overall environmental risk" in t and "Current conditions" in t and "Next 24 hours at a glance" in t
    assert "Live" in t and "SAMPLE DATA" not in t


def test_weather_failure_keeps_other_sections(monkeypatch):
    mock_providers(monkeypatch, weather_error=ds.NetworkError("Could not connect."))
    at = run()
    assert not at.exception and not at.error
    t = text(at)
    assert "Weather data could not be retrieved" in t and "Air quality (US AQI)" in t


def test_air_failure_keeps_weather_sections(monkeypatch):
    mock_providers(monkeypatch, air_error=ds.RateLimitError("Too many requests"))
    at = run()
    assert not at.exception and "Air-quality data could not be retrieved" in text(at) and "Current conditions" in text(at)


def test_both_failing_shows_helpful_message_not_a_crash(monkeypatch):
    mock_providers(monkeypatch, ds.NetworkError("x"), ds.NetworkError("y"))
    at = run()
    assert not at.exception and any("No data could be retrieved" in e.value for e in at.error)


def test_cached_data_is_reused_and_not_refetched(monkeypatch):
    counter = {"w": 0}
    mock_providers(monkeypatch, counter=counter)
    at = run()
    at.run()
    assert counter["w"] == 1


def test_stale_data_after_failed_refresh_is_shown_as_cached_never_live(monkeypatch):
    from datetime import timedelta
    mock_providers(monkeypatch)
    at = run()                                                    # fills the shared cache
    real_now = ds._now_utc
    monkeypatch.setattr(ds, "_now_utc", lambda: real_now() + timedelta(hours=2))
    mock_providers(monkeypatch, ds.NetworkError("Could not connect."), ds.NetworkError("Could not connect."))
    at.run()
    t = text(at)
    assert not at.exception
    assert "OLDER saved copy" in t and "Cached (stale)" in t and "It is not live" in t
    assert not any("Live" in c.value for c in at.markdown if "kn-chip" in c.value)


def demo_app():
    at = AppTest.from_file(APP, default_timeout=60).run()
    return at.sidebar.toggle[0].set_value(True).run()


def test_demo_mode_shows_banner_and_all_sections():
    at = demo_app()
    assert not at.exception and any("SAMPLE DATA" in e.value for e in at.error)
    t = text(at)
    assert "Overall environmental risk" in t and "Demonstration data" in t and "Moderate" in t


def test_activity_selector_changes_recommendations():
    at = demo_app()
    general = text(at)
    [s for s in at.sidebar.selectbox if s.label == "Activity"][0].select("outdoor_work").run()
    work = text(at)
    assert not at.exception and "Outdoor work" in work and "Outdoor work" not in general
    assert "co-workers" in work and "co-workers" not in general


def test_invalid_thresholds_show_specific_errors_and_pause_alerts_without_silent_defaults():
    at = demo_app()
    at.sidebar.number_input(key="thr_us_aqi_info").set_value(200.0).run()
    assert not at.exception
    t = text(at)
    assert "thresholds in the sidebar are invalid" in t and "must increase strictly" in t
    assert "Overall environmental risk" not in t                    # alerts paused, nothing silently substituted
    [b for b in at.sidebar.button if "Reset" in b.label][0].click().run()
    assert "Overall environmental risk" in text(at)


def test_manual_refresh_is_throttled(monkeypatch):
    counter = {"w": 0}
    mock_providers(monkeypatch, counter=counter)
    at = run()
    refresh = [b for b in at.sidebar.button if "Refresh" in b.label][0]
    refresh.click().run()
    assert counter["w"] == 2                                       # initial fetch + one forced refresh
    [b for b in at.sidebar.button if "Refresh" in b.label][0].click().run()
    assert counter["w"] == 2 and any("Please wait" in i.value for i in at.sidebar.info)


def test_chat_questions_work_without_ai_key_and_use_verified_data():
    at = demo_app()
    at.chat_input[0].set_value("What changes are expected over the next 24 hours?").run()
    assert not at.exception
    reply = at.chat_message[-1].markdown[0].value
    assert "rule-based answer" in reply and "Next 24 hours (forecast)" in reply


def test_suggested_question_and_chart_explanation_buttons():
    at = demo_app()
    [b for b in at.button if b.key == "sq_6"][0].click().run()
    assert "Data status and gaps" in at.chat_message[-1].markdown[0].value
    [b for b in at.button if b.label == "Explain this chart"][0].click().run()
    assert not at.exception and "About Temperature" in at.chat_message[-1].markdown[0].value


def test_overlong_chat_question_is_refused_politely():
    at = demo_app()
    at.chat_input[0].set_value("x" * 700).run()
    assert not at.exception and "Please shorten" in at.chat_message[-1].markdown[0].value


def test_api_key_is_never_rendered(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_TESTSECRETKEY1234567890")
    at = demo_app()
    at.chat_input[0].set_value("Summarize the current alerts.").run()
    assert not at.exception and "gsk_TESTSECRET" not in text(at) and "gsk_TESTSECRET" not in str(at.get("chat_message"))


def test_no_excluded_notification_features_in_source():
    root = os.path.dirname(APP)
    banned = ("smtplib", "twilio", "apscheduler", "plyer", "webpush", "Notification(", "schedule.every", "sched.scheduler")
    for name in os.listdir(root):
        if name.endswith(".py"):
            with open(os.path.join(root, name), encoding="utf-8") as handle:
                src = handle.read()
            assert not [b for b in banned if b in src], name
