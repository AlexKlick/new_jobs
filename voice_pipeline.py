"""
Voice Pipeline - FastAPI Voice Processing Server

HTTP/WebSocket proxy for the voice pipeline with VAD + ASR integration.
Handles audio input through Silero VAD and faster-whisper ASR to produce text,
then optionally routes to LLM + TTS for full voice conversation.

Endpoints:
- POST /api/voice  : Upload audio, get transcription + LLM response + TTS audio
- WebSocket /ws/voice : Real-time voice streaming with same pipeline
- GET  /health      : Health check

Port: 8081 (separate from chat_backend port 8080)

Latency Targets:
- VAD detection: <500ms
- ASR transcription: <2s for 30s audio
- Total release-to-text: <3s

Usage:
    uvicorn voice_pipeline:app --port 8081 --host 0.0.0.0
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import uuid
from typing import Optional

import numpy as np
import wave
from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from audio_processing import (
    SAMPLE_RATE,
    detect_speech_segments,
    get_audio_duration,
    preprocess_audio,
)
from llm_client import VLLMClient, VLLMCircuitOpenError

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore

try:
    import requests
except ImportError:
    requests = None  # type: ignore

_logger = logging.getLogger(__name__)

# Configuration
PORT = int(os.environ.get("VOICE_PIPELINE_PORT", "8081"))
CHAT_BACKEND_URL = os.environ.get("CHAT_BACKEND_URL", "http://localhost:8080")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")
MAX_TTS_DURATION = 30.0  # seconds

# Global clients (lazy-loaded)
_whisper_model: Optional[WhisperModel] = None
_llm_client: Optional[VLLMClient] = None


# ---------------------------------------------------------------------------
# Model lazy-loaders
# ---------------------------------------------------------------------------

def _get_whisper() -> WhisperModel:
    """Lazy-load faster-whisper model."""
    global _whisper_model
    if _whisper_model is None:
        if WhisperModel is None:
            raise RuntimeError(
                "faster-whisper not installed. Install with: pip install faster-whisper"
            )
        _logger.info(f"Loading faster-whisper model '{WHISPER_MODEL}' on CPU...")
        _whisper_model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        )
        _logger.info("Whisper model loaded")
    return _whisper_model


def _get_llm() -> VLLMClient:
    """Get or create the global LLM client."""
    global _llm_client
    if _llm_client is None:
        _llm_client = VLLMClient()
    return _llm_client


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class VoiceRequest(BaseModel):
    """Request for /api/voice (JSON variant)."""
    audio_base64: str | None = None  # base64-encoded audio bytes
    job_index: int | None = None
    include_tts: bool = Field(default=False, description="Include TTS audio in response")


class VoiceResponse(BaseModel):
    """Response for /api/voice endpoint."""
    transcription: str
    llm_response: str | None = None
    audio_url: str | None = None
    duration_s: float = 0.0
    segments: list[dict] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Response for /health endpoint."""
    status: str
    whisper_loaded: bool
    llm_healthy: bool


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Voice Pipeline",
    description="VAD + ASR + LLM + TTS voice processing pipeline",
    version="1.0.0",
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health check endpoint."""
    whisper_ok = _whisper_model is not None
    llm_ok = False
    try:
        llm = _get_llm()
        llm_ok = await asyncio.wait_for(llm.health(), timeout=5.0)
    except asyncio.TimeoutError:
        _logger.warning("LLM health check timed out")
    except Exception as exc:
        _logger.warning(f"LLM health check failed: {exc}")

    return HealthResponse(
        status="ok" if (whisper_ok and llm_ok) else "degraded",
        whisper_loaded=whisper_ok,
        llm_healthy=llm_ok,
    )


# ---------------------------------------------------------------------------
# POST /api/voice
# ---------------------------------------------------------------------------

@app.post("/api/voice", response_model=VoiceResponse)
async def process_voice(
    file: UploadFile | None = None,
    job_index: int | None = None,
    include_tts: bool = False,
) -> VoiceResponse:
    """
    Process voice audio and return transcription + optional LLM response + TTS.

    Accepts either:
    - Multipart file upload (file field)
    - JSON body with base64-encoded audio

    Args:
        file: Audio file upload (WAV, MP3, OGG, etc.)
        job_index: Optional job index to inject context into LLM call
        include_tts: If True, synthesize TTS for the LLM response

    Returns:
        VoiceResponse with transcription, llm_response, audio_url
    """
    audio_bytes: bytes | None = None

    # --- 1. Receive audio bytes ---
    if file is not None:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Empty audio file")
        audio_bytes = content
    else:
        raise HTTPException(
            status_code=400,
            detail="No audio file provided. Send as multipart/form-data with 'file' field.",
        )

    # --- 2. Preprocess to 16kHz mono ---
    try:
        audio_np = preprocess_audio(audio_bytes)
    except Exception as exc:
        _logger.error(f"Audio preprocessing failed: {exc}")
        raise HTTPException(status_code=400, detail=f"Audio preprocessing failed: {exc}")

    duration_s = get_audio_duration(audio_np, SAMPLE_RATE)

    # --- 3. Run Silero VAD to detect speech segments ---
    try:
        segments = detect_speech_segments(audio_np, SAMPLE_RATE)
    except Exception as exc:
        _logger.error(f"VAD detection failed: {exc}")
        raise HTTPException(status_code=500, detail=f"VAD detection failed: {exc}")

    # --- 4. If speech found, run faster-whisper on speech segments ---
    transcription = ""
    segment_results: list[dict] = []

    if segments:
        try:
            whisper = _get_whisper()

            for i, (start_s, end_s) in enumerate(segments):
                start_sample = int(start_s * SAMPLE_RATE)
                end_sample = int(end_s * SAMPLE_RATE)
                segment_np = audio_np[start_sample:end_sample].astype(np.float32) / 32768.0

                # Skip very short segments
                if len(segment_np) < SAMPLE_RATE * 0.1:
                    continue

                segments_out, _ = whisper.transcribe(
                    segment_np,
                    language="en",
                    beam_size=3,
                )
                text = "".join(s.text for s in segments_out).strip()
                if text:
                    transcription += (" " if transcription else "") + text
                    segment_results.append({
                        "start": start_s,
                        "end": end_s,
                        "text": text,
                    })

        except Exception as exc:
            _logger.error(f"ASR transcription failed: {exc}")
            raise HTTPException(status_code=500, detail=f"ASR transcription failed: {exc}")

    # Handle no speech detected
    if not transcription.strip():
        return VoiceResponse(
            transcription="",
            llm_response=None,
            audio_url=None,
            duration_s=duration_s,
            segments=[],
        )

    # --- 5. Call LLM with transcription + job context ---
    llm_response: str | None = None
    audio_url: str | None = None

    try:
        llm = _get_llm()

        # Build context messages for LLM
        context: list[dict[str, str]] = []
        if job_index is not None:
            # Try to get job context from chat backend
            try:
                if requests is not None:
                    ctx_url = f"{CHAT_BACKEND_URL}/api/jobs/{job_index}/context"
                    ctx_resp = requests.get(ctx_url, timeout=10)
                    if ctx_resp.status_code == 200:
                        ctx_data = ctx_resp.json()
                        ctx_parts = []
                        if ctx_data.get("resume"):
                            ctx_parts.append(f"RESUME:\n{ctx_data['resume']}")
                        if ctx_data.get("cover_letter"):
                            ctx_parts.append(f"COVER LETTER:\n{ctx_data['cover_letter']}")
                        if ctx_parts:
                            context.append({
                                "role": "system",
                                "content": f"You are helping with a job application for '{ctx_data.get('job_name', 'Unknown')}'. "
                                           f"Here are the applicant's documents:\n\n" + "\n\n".join(ctx_parts)
                            })
            except Exception as exc:
                _logger.warning(f"Could not fetch job context: {exc}")

        context.append({"role": "user", "content": transcription})
        llm_response = await llm.complete_text(
            user_text=transcription,
            context=context if len(context) > 1 else None,
        )

    except VLLMCircuitOpenError:
        _logger.warning("vLLM circuit breaker open, skipping LLM call")
        llm_response = None
    except Exception as exc:
        _logger.error(f"LLM call failed: {exc}")
        llm_response = None

    # --- 6. Optionally synthesize TTS ---
    if include_tts and llm_response:
        try:
            from tts_client import synthesize_speech
            tts_audio = await synthesize_speech(llm_response[:1000])  # Cap at 1000 chars
            # For now, we don't have a file storage URL, so return null
            # In production, save to temp file and return URL
            audio_url = None  # TODO: save to temp file and return URL
            _logger.debug(f"TTS audio generated ({len(tts_audio)} bytes)")
        except Exception as exc:
            _logger.warning(f"TTS synthesis failed: {exc}")
            audio_url = None

    return VoiceResponse(
        transcription=transcription,
        llm_response=llm_response,
        audio_url=audio_url,
        duration_s=duration_s,
        segments=segment_results,
    )


# ---------------------------------------------------------------------------
# WebSocket /ws/voice
# ---------------------------------------------------------------------------

class ConnectionState:
    """State for a WebSocket voice connection."""

    def __init__(self, websocket: WebSocket, job_index: int | None = None):
        self.websocket = websocket
        self.job_index = job_index
        self.audio_buffer: list[bytes] = []
        self.sample_rate = SAMPLE_RATE
        self.chunk_size = 512  # 32ms at 16kHz

    async def send_text(self, data: str) -> None:
        await self.websocket.send_text(data)

    async def send_json(self, data: dict) -> None:
        await self.websocket.send_json(data)


@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket, job_index: int | None = None):
    """
    WebSocket endpoint for real-time voice streaming.

    Protocol:
    1. Client sends audio chunks (PCM 16kHz mono int16)
    2. Server accumulates and runs VAD
    3. On silence detection, server transcribes and responds

    Client messages:
    - {"type": "audio", "data": "<base64>"} : Audio chunk
    - {"type": "done"} : Signal end of speaking turn

    Server messages:
    - {"type": "transcription", "text": "...", "done": true}
    - {"type": "llm_response", "text": "..."}
    - {"type": "error", "message": "..."}
    """
    await websocket.accept()
    state = ConnectionState(websocket, job_index)
    silence_threshold = 3.0  # seconds of silence to trigger transcription
    max_buffer_duration = 60.0  # seconds

    try:
        # Accumulate audio until silence or done
        last_speech_time: float | None = None
        buffer_samples: list[np.ndarray] = []

        while True:
            msg = await websocket.receive()

            # Handle text messages
            if "text" in msg:
                text_data = msg["text"]
                if text_data == "done":
                    break

            # Handle binary audio chunks
            if "bytes" in msg:
                audio_bytes = msg["bytes"]

                # Decode int16 PCM
                try:
                    chunk_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                except Exception:
                    continue

                buffer_samples.append(chunk_np)

                # Check VAD on recent buffer
                if len(buffer_samples) >= 16:  # At least 512ms
                    recent = np.concatenate(buffer_samples[-16:])
                    from audio_processing import _SileroVADHelper
                    helper = _SileroVADHelper.get_instance()
                    is_speech = helper.get_speech_prob(recent[-512:]) > 0.5

                    if is_speech:
                        last_speech_time = asyncio.get_event_loop().time()
                    elif last_speech_time is not None:
                        silence_duration = asyncio.get_event_loop().time() - last_speech_time
                        if silence_duration >= silence_threshold:
                            # Trigger transcription
                            break

                # Safety: max buffer
                total_duration = sum(len(s) for s in buffer_samples) / SAMPLE_RATE
                if total_duration > max_buffer_duration:
                    _logger.warning("WebSocket buffer exceeded max duration")
                    break

        # Transcribe accumulated audio
        if buffer_samples:
            full_audio = np.concatenate(buffer_samples)
            full_audio_int16 = (full_audio * 32768).astype(np.int16)

            # Run VAD
            segments = detect_speech_segments(full_audio_int16, SAMPLE_RATE)

            if segments:
                transcription = ""
                try:
                    whisper = _get_whisper()
                    for start_s, end_s in segments:
                        start_sample = int(start_s * SAMPLE_RATE)
                        end_sample = int(end_s * SAMPLE_RATE)
                        segment_np = full_audio_int16[start_sample:end_sample].astype(np.float32) / 32768.0
                        if len(segment_np) < SAMPLE_RATE * 0.1:
                            continue
                        segs_out, _ = whisper.transcribe(
                            segment_np, language="en", beam_size=3
                        )
                        text = "".join(s.text for s in segs_out).strip()
                        if text:
                            transcription += (" " if transcription else "") + text
                except Exception as exc:
                    await state.send_json({"type": "error", "message": str(exc)})
                    return

                await state.send_json({
                    "type": "transcription",
                    "text": transcription,
                    "done": True,
                })

                # Call LLM
                if transcription.strip():
                    try:
                        llm = _get_llm()
                        llm_response = await llm.complete_text(transcription)
                        await state.send_json({
                            "type": "llm_response",
                            "text": llm_response,
                        })
                    except VLLMCircuitOpenError:
                        _logger.warning("vLLM circuit breaker open")
                    except Exception as exc:
                        _logger.error(f"LLM error: {exc}")
            else:
                await state.send_json({
                    "type": "transcription",
                    "text": "",
                    "done": True,
                })
        else:
            await state.send_json({
                "type": "transcription",
                "text": "",
                "done": True,
            })

    except WebSocketDisconnect:
        _logger.debug("WebSocket client disconnected")
    except Exception as exc:
        _logger.error(f"WebSocket error: {exc}")
        try:
            await state.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
