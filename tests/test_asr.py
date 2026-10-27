import httpx
import pytest

from qulaq import asr
from qulaq.config import Settings
from qulaq.metrics import cer

S = Settings(api_key="k", api_base="https://api.test/v1", asr_model="m", llm_model="l")


def _wav(tmp_path):
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF....WAVE")
    return p


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_success(tmp_path):
    seen = {}

    def handler(req):
        seen["auth"] = req.headers["authorization"]
        seen["url"] = str(req.url)
        return httpx.Response(200, json={"transcript": " привет ", "turns": [{"transcript": "привет"}]})

    t = asr.transcribe_wav(_wav(tmp_path), client=_client(handler), settings=S)
    assert t.text == "привет" and len(t.turns) == 1
    assert seen["auth"] == "Bearer k" and seen["url"] == "https://api.test/v1/asr/transcribe"


def test_400_raises_with_body(tmp_path):
    c = _client(lambda r: httpx.Response(400, text="bad field"))
    with pytest.raises(asr.ASRError) as ei:
        asr.transcribe_wav(_wav(tmp_path), client=c, settings=S)
    assert ei.value.status == 400 and "bad field" in ei.value.body


def test_retry_on_500(tmp_path):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500) if len(calls) == 1 else httpx.Response(200, json={"transcript": "ok"})

    t = asr.transcribe_wav(_wav(tmp_path), client=_client(handler), settings=S, backoff_s=0)
    assert t.text == "ok" and len(calls) == 2


def test_missing_key(tmp_path):
    s = Settings(api_key="", api_base="x", asr_model="m", llm_model="l")
    with pytest.raises(asr.ASRError):
        asr.transcribe_wav(_wav(tmp_path), settings=s)


def test_cer():
    assert cer("Привет, мир!", "привет мир") == 0.0
    assert cer("abc", "abd") == pytest.approx(1 / 3)
    assert cer("", "") == 0.0 and cer("", "x") == 1.0


def test_request_has_audio_and_json_request_parts(tmp_path):
    seen = {}

    def handler(req):
        seen["body"] = req.read()
        return httpx.Response(200, json={"transcript": "ok"})

    asr.transcribe_wav(_wav(tmp_path), language_bias=["Russian"], client=_client(handler), settings=S)
    body = seen["body"].decode("latin-1")
    assert 'name="audio"' in body and 'name="request"' in body
    assert "application/json" in body and '"languageBias": ["Russian"]' in body
