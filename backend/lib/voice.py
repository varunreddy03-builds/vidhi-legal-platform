"""Speech to text and text to speech.

Speech to text (people speak a question in their own language):
  1. ElevenLabs Scribe (ELEVENLABS_API_KEY) - many Indian languages, auto-detects the language
  2. Gemini audio understanding (GEMINI_API_KEY) - used when ElevenLabs is not configured or fails
  STT_PROVIDER=elevenlabs|gemini chooses which is tried first.
Text to speech (answers read aloud):
  ElevenLabs multilingual voices (ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_TTS_MODEL). When it is not configured the
  browser falls back to its own built-in voices (free, on the person's device).
Privacy: audio and the text to be spoken are handled in memory and never stored; only a usage counter is kept.
VOICE_STUB=true is for tests/dev only (no network)."""

import logging
import os

from lib import aibudget

logger = logging.getLogger(__name__)

_TRANSPORT = None  # tests inject an httpx.MockTransport here
ELEVEN = "https://api.elevenlabs.io"
DEFAULT_VOICE = "EXAVITQu4vr4xnSDxMaL"  # "Sarah", a calm premade voice that works on ElevenLabs' free plan; set ELEVENLABS_VOICE_ID to choose another
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_SPEAK_CHARS = 2000
STUB_MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00stub-audio"


class VoiceError(Exception):
    """No provider could do it. Callers turn this into a plain 502/503."""


def stub_enabled() -> bool:
    return os.environ.get("VOICE_STUB", "false").lower() == "true"


def _eleven_key() -> str:
    return os.environ.get("ELEVENLABS_API_KEY", "")


def stt_providers() -> list[str]:
    avail = (["elevenlabs"] if _eleven_key() else []) + (["gemini"] if os.environ.get("GEMINI_API_KEY") else [])
    first = os.environ.get("STT_PROVIDER", "").lower()
    return sorted(avail, key=lambda p: p != first) if first in avail else avail


def stt_available() -> bool:
    return stub_enabled() or bool(stt_providers())


def tts_available() -> bool:
    return stub_enabled() or bool(_eleven_key())


async def _eleven_stt(audio: bytes, filename: str, mime: str) -> dict:
    import httpx

    async with aibudget.fixed("stt", len(audio), task="stt"), httpx.AsyncClient(timeout=60.0, transport=_TRANSPORT) as c:
        r = await c.post(
            f"{ELEVEN}/v1/speech-to-text", headers={"xi-api-key": _eleven_key()},
            data={"model_id": os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v1")}, files={"file": (filename, audio, mime)},
        )
    if r.status_code >= 400:
        raise VoiceError(f"ElevenLabs speech-to-text failed with {r.status_code}")
    j = r.json()
    return {"text": (j.get("text") or "").strip(), "language": j.get("language_code")}


async def _gemini_stt(audio: bytes, mime: str) -> dict:
    from google.genai import types

    from lib.ai import _client, model_name

    prompt = (
        "Transcribe this speech exactly as spoken, in the language spoken, using that language's own script. "
        "Reply with the transcript only: no translation, no notes, no quotation marks. If there is no speech, reply with nothing."
    )
    async with aibudget.fixed("stt", len(audio), task="stt"):
        client = _client()  # keep it referenced for the whole call (see lib/ai.py)
        resp = await client.aio.models.generate_content(
            model=model_name("free"), contents=[types.Part.from_bytes(data=audio, mime_type=mime.split(";")[0]), prompt],
        )
    return {"text": (getattr(resp, "text", "") or "").strip(), "language": None}


async def transcribe(audio: bytes, filename: str = "speech.webm", mime: str = "audio/webm") -> dict:
    """{'text', 'language'} - the words spoken (empty text if nothing was said)."""
    if stub_enabled():
        from lib.db import db

        row = await db.voice_stub.find_one_and_delete({"kind": "stt"})
        if row and row.get("fail"):
            raise VoiceError("stub: scripted failure")
        return {"text": (row or {}).get("text", "stub transcript"), "language": (row or {}).get("language", "en")}
    tried = []
    for p in stt_providers():
        tried.append(p)
        try:
            return await (_eleven_stt(audio, filename, mime) if p == "elevenlabs" else _gemini_stt(audio, mime))
        except aibudget.BudgetExceeded:
            raise  # a spending cap is a hard stop: do not try the next provider
        except Exception as exc:  # noqa: BLE001 - try the next provider
            from lib.ai import failure_label

            logger.warning("speech-to-text provider=%s failed: %s", p, failure_label(exc))  # the class and status only, never the message
    raise VoiceError(f"no provider could transcribe the audio (tried: {', '.join(tried) or 'none configured'})")


async def speak(text: str) -> bytes:
    """MP3 bytes of the text read aloud (the voice reads in the language of the text)."""
    text = text.strip()[:MAX_SPEAK_CHARS]
    if stub_enabled():
        return STUB_MP3
    if not _eleven_key():
        raise VoiceError("text-to-speech is not configured")
    import httpx

    voice = os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
    async with aibudget.fixed("tts", len(text), task="tts"), httpx.AsyncClient(timeout=60.0, transport=_TRANSPORT) as c:
        r = await c.post(
            f"{ELEVEN}/v1/text-to-speech/{voice}", params={"output_format": "mp3_44100_128"}, headers={"xi-api-key": _eleven_key()},
            json={"text": text, "model_id": os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")},
        )
    if r.status_code >= 400 or not r.content:
        raise VoiceError(f"ElevenLabs text-to-speech failed with {r.status_code}")
    return r.content