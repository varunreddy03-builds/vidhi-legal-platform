"""Voice: speech to text, text to speech, quotas, and the providers' request shapes. Audio is never stored."""

import asyncio

import httpx
import pytest

from lib import voice
from tests.conftest import mongo, set_plan

AUDIO = b"\x1aE\xdf\xa3" + b"opus-audio-bytes" * 40  # looks like a short webm recording


def test_status(user_a):
    assert user_a.get("/voice/status").json() == {"speech_to_text": True, "text_to_speech": True}


def test_a_recording_becomes_text(user_a):
    mongo().voice_stub.insert_one({"kind": "stt", "text": "मेरे ग्राहक ने भुगतान नहीं किया", "language": "hi"})
    r = user_a.post("/voice/transcribe", files={"file": ("q.webm", AUDIO, "audio/webm")})
    assert r.status_code == 200 and r.json() == {"text": "मेरे ग्राहक ने भुगतान नहीं किया", "language": "hi"}


def test_only_audio_of_sensible_size_is_accepted(user_a):
    assert user_a.post("/voice/transcribe", files={"file": ("a.txt", b"hello" * 100, "text/plain")}).status_code == 415
    assert user_a.post("/voice/transcribe", files={"file": ("q.webm", b"tiny", "audio/webm")}).status_code == 400
    big = b"x" * (voice.MAX_AUDIO_BYTES + 10)
    assert user_a.post("/voice/transcribe", files={"file": ("q.webm", big, "audio/webm")}).status_code == 413


def test_a_failed_transcription_is_a_plain_error(user_a):
    mongo().voice_stub.insert_one({"kind": "stt", "fail": True})
    r = user_a.post("/voice/transcribe", files={"file": ("q.webm", AUDIO, "audio/webm")})
    assert r.status_code == 502 and "type your question" in r.json()["detail"]


def test_text_is_read_aloud_as_mp3(user_a):
    r = user_a.post("/voice/speak", json={"text": "Your notice is ready."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg" and r.content.startswith(b"ID3")
    assert r.headers["cache-control"] == "no-store"
    assert user_a.post("/voice/speak", json={"text": ""}).status_code == 422
    assert user_a.post("/voice/speak", json={"text": "x" * (voice.MAX_SPEAK_CHARS + 1)}).status_code == 422


def test_voice_needs_sign_in(anon):
    assert anon.post("/voice/speak", json={"text": "hi"}).status_code in (401, 403)
    assert anon.post("/voice/transcribe", files={"file": ("q.webm", AUDIO, "audio/webm")}).status_code in (401, 403)


def test_the_free_plan_has_a_daily_allowance_and_pro_has_more(user_a):
    set_plan(user_a, "FREE")
    codes = [user_a.post("/voice/speak", json={"text": "hello"}).status_code for _ in range(24)]
    assert codes[:20] == [200] * 20 and 429 in codes[20:]
    set_plan(user_a, "PRO")
    assert user_a.post("/voice/speak", json={"text": "hello"}).status_code == 200  # the allowance for Pro is separate and larger


def test_the_words_are_never_logged(user_a):
    secret = "UNIQUE-SPOKEN-WORDS-5521"  # secret-scan: ok (fake test value)
    mongo().voice_stub.insert_one({"kind": "stt", "text": secret})
    user_a.post("/voice/transcribe", files={"file": ("q.webm", AUDIO, "audio/webm")})
    user_a.post("/voice/speak", json={"text": secret})
    assert mongo().audit_events.count_documents({"detail": {"$regex": secret}}) == 0
    assert mongo().audit_events.find_one({"operation": "VOICE_TRANSCRIBE"})  # the event exists, with sizes only


# ---- providers' request shapes (ElevenLabs replaced by a recorded transport) ----
def run(c):
    return asyncio.run(c)


@pytest.fixture
def eleven(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/speech-to-text"):
            return httpx.Response(200, json={"text": " नमस्ते ", "language_code": "hin"})
        return httpx.Response(200, content=b"MP3DATA", headers={"content-type": "audio/mpeg"})

    monkeypatch.setattr(voice, "_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setenv("VOICE_STUB", "false")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "xi-test")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice123")
    return calls


def test_elevenlabs_speech_to_text_request(eleven):
    out = run(voice.transcribe(AUDIO, "q.webm", "audio/webm"))
    assert out == {"text": "नमस्ते", "language": "hin"}
    req = eleven[0]
    assert req.url.path == "/v1/speech-to-text" and req.headers["xi-api-key"] == "xi-test" and b"scribe_v1" in req.content


def test_elevenlabs_text_to_speech_request(eleven):
    assert run(voice.speak("नमस्ते")) == b"MP3DATA"
    req = eleven[0]
    assert req.url.path == "/v1/text-to-speech/voice123" and req.url.params["output_format"] == "mp3_44100_128"
    assert b"eleven_multilingual_v2" in req.content and req.headers["xi-api-key"] == "xi-test"


def test_a_provider_error_falls_through_then_fails_plainly(monkeypatch):
    monkeypatch.setattr(voice, "_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(500, json={})))
    monkeypatch.setenv("VOICE_STUB", "false")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "xi-test")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(voice.VoiceError):
        run(voice.transcribe(AUDIO))
    with pytest.raises(voice.VoiceError):
        run(voice.speak("hello"))


def test_provider_order(monkeypatch):
    monkeypatch.setenv("VOICE_STUB", "false")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    assert voice.stt_providers() == ["elevenlabs", "gemini"]
    monkeypatch.setenv("STT_PROVIDER", "gemini")
    assert voice.stt_providers() == ["gemini", "elevenlabs"]
    monkeypatch.delenv("ELEVENLABS_API_KEY")
    assert voice.stt_providers() == ["gemini"] and not voice.tts_available()