"""LLM tests use a fake Groq client; no key or network needed."""
from datetime import date
import alert_engine as ae
import llm_service as ls
import sample_data as sd

START = date(2026, 10, 20)
def setup_objects():
    w, a = sd.load_sample_weather(START), sd.load_sample_air_quality(START)
    return w, a, ae.evaluate_alerts(w, a)

class FakeClient:
    def __init__(self, text=None, error=None): self.text, self.error = text, error; self.chat = self; self.completions = self
    def create(self, **kwargs):
        if self.error: raise self.error
        return type('Response', (), {'choices': [type('Choice', (), {'message': type('Message', (), {'content': self.text})()})()]})()

def test_llm_off_uses_fallback():
    w, a, alerts = setup_objects(); r = ls.explain('X', w, a, alerts, use_llm=False)
    assert r.source == 'Python fallback' and '[SAMPLE DATA]' in r.text

def test_no_api_key_uses_fallback(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    r = ls.explain('X', *setup_objects()[::2], use_llm=True) if False else None
    w, a, alerts = setup_objects(); r = ls.explain('X', w, a, alerts, use_llm=True)
    assert r.source == 'Python fallback' and 'GROQ_API_KEY' in r.note

def test_llm_success():
    w, a, alerts = setup_objects(); r = ls.explain('X', w, a, alerts, client=FakeClient('Please take care and check official updates.'))
    assert r.source == 'Groq AI' and 'official updates' in r.text

def test_llm_exception_falls_back():
    w, a, alerts = setup_objects(); r = ls.explain('X', w, a, alerts, client=FakeClient(error=RuntimeError('boom')))
    assert r.source == 'Python fallback' and 'RuntimeError' in r.note

def test_fallback_with_no_alerts():
    assert 'no configured alert rule' in ls.fallback_explanation('Somewhere', [])

def test_payload_has_real_values():
    w, a, alerts = setup_objects(); p = ls.build_payload('X', w, a, alerts)
    assert p['current_weather']['temperature_c'] == 34.2 and p['data_is_sample_demo'] is True

def test_chat_fallback_when_key_missing(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    w, a, alerts = setup_objects(); r = ls.chat_answer('What should I do?', 'X', w, a, alerts)
    assert r.source == 'Python fallback' and 'GROQ_API_KEY' in r.note

def test_chat_success():
    w, a, alerts = setup_objects(); r = ls.chat_answer('What should I do?', 'X', w, a, alerts, client=FakeClient('Check official updates and follow listed precautions.'))
    assert r.source == 'Groq AI' and 'precautions' in r.text


def test_default_model_is_not_retired_llama():
    assert ls.DEFAULT_MODEL == "openai/gpt-oss-120b"

def test_model_env_override(monkeypatch):
    monkeypatch.setenv("KANIYAN_LLM_MODEL", "qwen/qwen3.6-27b")
    assert ls._get_model() == "qwen/qwen3.6-27b"

def test_chat_sends_context_history_and_model(monkeypatch):
    monkeypatch.delenv("KANIYAN_LLM_MODEL", raising=False)
    seen = {}
    class Spy(FakeClient):
        def create(self, **kw): seen.update(kw); return super().create(**kw)
    w, a, alerts = setup_objects()
    hist = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    r = ls.chat_answer("Is it hot?", "X", w, a, alerts, history=hist, client=Spy("Yes, quite warm."))
    assert r.source == "Groq AI"
    assert seen["model"] == "openai/gpt-oss-120b"
    assert seen["messages"][0]["role"] == "system" and "temperature_c" in seen["messages"][0]["content"]
    assert [m["role"] for m in seen["messages"]] == ["system", "user", "assistant", "user"]

def test_bad_request_retries_without_reasoning_effort():
    calls = []
    class BadRequestError(Exception): pass
    class Flaky(FakeClient):
        def create(self, **kw):
            calls.append(kw)
            if "reasoning_effort" in kw: raise BadRequestError("unsupported")
            return super().create(**kw)
    w, a, alerts = setup_objects()
    r = ls.chat_answer("Q?", "X", w, a, alerts, client=Flaky("ok answer"))
    assert r.source == "Groq AI" and len(calls) == 2


def test_payload_includes_forecast_and_rain_chance():
    w, a, alerts = setup_objects(); p = ls.build_payload('X', w, a, alerts)
    assert len(p['daily_forecast']) == 7 and '(today)' in p['daily_forecast'][0]['date']
    assert 'rain_chance_max_percent' in p['daily_forecast'][0]
    assert p['next_24h_rain'] is not None and 'total_rain_mm' in p['next_24h_rain']
    import json; json.dumps(p)  # must be JSON-serialisable
