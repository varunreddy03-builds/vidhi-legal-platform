"""Voice: speak a question instead of typing it, and listen to an answer. Audio is never stored."""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from lib import aibudget, voice
from lib.ai import ai_failure
from lib.monitoring import error_label
from lib.auth import audit, current_user, entitlement_for
from lib.ratelimit import hit
from lib.uploads import read_limited

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])

# A day's allowance per person. Voice costs money per use, so the free plan gets a modest amount (Recovery users included).
DAILY = {"free": 20, "pro": 200}
AUDIO_TYPES = ("audio/", "video/webm", "video/mp4", "application/ogg")


async def _quota(user: dict, kind: str) -> None:
    await hit(f"voice-{kind}", user["id"], DAILY["pro" if entitlement_for(user)["tier"] in ("pro", "firm") else "free"], 86400)


@router.get("/status")
async def status(user: dict = Depends(current_user)):
    return {"speech_to_text": voice.stt_available(), "text_to_speech": voice.tts_available()}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), user: dict = Depends(current_user)):
    """Turn a short recording into text. Returns {text, language}. Nothing is kept."""
    if not voice.stt_available():
        raise HTTPException(status_code=503, detail="Voice input is not available right now. Please type your question.")
    mime = (file.content_type or "").lower()
    if not mime.startswith(AUDIO_TYPES):
        raise HTTPException(status_code=415, detail="Please send an audio recording.")
    audio = await read_limited(file, voice.MAX_AUDIO_BYTES, "That recording is too long. Please keep it under a few minutes.")
    if len(audio) < 200:
        raise HTTPException(status_code=400, detail="We could not hear anything. Please try again.")
    await aibudget.ensure_available(user)
    await _quota(user, "stt")
    try:
        out = await voice.transcribe(audio, file.filename or "speech.webm", mime or "audio/webm")
    except aibudget.BudgetExceeded as exc:
        raise ai_failure(exc) from exc  # a reached spending cap says so, instead of "we could not understand that"
    except voice.VoiceError as exc:
        logger.warning("transcription failed: %s", error_label(exc))  # the class only: the message can repeat the words spoken
        raise HTTPException(status_code=502, detail="We could not understand that recording. Please try again or type your question.") from exc
    await audit(user, "VOICE_TRANSCRIBE", detail=f"{len(audio)} bytes")  # sizes only, never the words
    return out


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=voice.MAX_SPEAK_CHARS)


@router.post("/speak")
async def speak(body: SpeakIn, user: dict = Depends(current_user)):
    """Read text aloud (MP3). When no voice service is set up, the browser uses its own built-in voice instead."""
    if not voice.tts_available():
        raise HTTPException(status_code=503, detail="Listening is not available right now.")
    await aibudget.ensure_available(user)
    await _quota(user, "tts")
    try:
        mp3 = await voice.speak(body.text)
    except aibudget.BudgetExceeded as exc:
        raise ai_failure(exc) from exc
    except voice.VoiceError as exc:
        logger.warning("text-to-speech failed: %s", error_label(exc))
        raise HTTPException(status_code=502, detail="We could not read that aloud just now.") from exc
    return Response(content=mp3, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})