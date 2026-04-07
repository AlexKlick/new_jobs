"""
VibeVoice TTS Client

Provides async TTS synthesis using VibeVoice (or fallback to simple audio).
Returns WAV audio bytes (16kHz mono PCM).

Usage:
    client = VibeVoiceTTSClient()
    audio_bytes = await client.synthesize_speech("Hello, how are you?", voice="carter")
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from typing import Optional

import numpy as np
import wave

_logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # 16kHz for output


class VibeVoiceTTSClient:
    """VibeVoice TTS client with fallback for unavailable service."""

    def __init__(
        self,
        voice: str | None = None,
        voice_service_port: int | None = None,
    ):
        self.voice = voice or os.environ.get("VOICE_NAME", "carter")
        self.voice_service_port = voice_service_port or int(
            os.environ.get("VOICE_SERVICE_PORT", "8081")
        )
        self._vibevoice_tts = None
        self._vibevoice_available = self._check_vibevoice()

    def _check_vibevoice(self) -> bool:
        """Check if VibeVoice TTS is available."""
        try:
            from vibevoice_tts import VibeVoiceTTS as _VTS
            return True
        except ImportError:
            _logger.warning("VibeVoice TTS not available, using fallback audio")
            return False

    async def synthesize_speech(
        self,
        text: str,
        voice: str | None = None,
    ) -> bytes:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize
            voice: Voice name (overrides instance voice)

        Returns:
            WAV audio bytes (16kHz mono PCM)
        """
        voice_name = voice or self.voice

        if self._vibevoice_available:
            return await self._synthesize_vibevoice(text, voice_name)
        else:
            return self._synthesize_fallback(text)

    async def _synthesize_vibevoice(self, text: str, voice: str) -> bytes:
        """Synthesize using VibeVoice TTS."""
        try:
            from vibevoice_tts import VibeVoiceTTS as VTS

            tts = VTS(device="cuda", voice_name=voice)

            # Collect audio chunks from streaming generator
            audio_chunks: list[np.ndarray] = []
            for chunk in tts.speak(text):
                audio_chunks.append(chunk)

            if not audio_chunks:
                return self._synthesize_fallback(text)

            # Concatenate all chunks and resample to 16kHz if needed
            audio = np.concatenate(audio_chunks)
            audio = self._resample_if_needed(audio, from_rate=24000, to_rate=SAMPLE_RATE)

            return self._audio_to_wav(audio, SAMPLE_RATE)

        except Exception as exc:
            _logger.warning(f"VibeVoice synthesis failed, using fallback: {exc}")
            return self._synthesize_fallback(text)

    def _synthesize_fallback(self, text: str) -> bytes:
        """Generate simple fallback audio (silent or simple tone).

        When VibeVoice is unavailable, returns a short silent WAV.
        """
        # Generate short silence with a simple beep marker
        duration_s = min(len(text) * 0.05, 3.0)  # ~50ms per char, max 3s
        num_samples = int(SAMPLE_RATE * duration_s)

        # Simple audio: mostly silence with a brief tone at start
        audio = np.zeros(num_samples, dtype=np.float32)

        # Add a brief 440Hz beep at the start (100ms)
        beep_len = int(SAMPLE_RATE * 0.1)
        if beep_len < num_samples:
            t = np.linspace(0, 0.1, beep_len, dtype=np.float32)
            beep = np.sin(2 * np.pi * 440 * t) * 0.1
            audio[:beep_len] = beep

        return self._audio_to_wav(audio, SAMPLE_RATE)

    def _resample_if_needed(
        self, audio: np.ndarray, from_rate: int, to_rate: int
    ) -> np.ndarray:
        """Simple resampling if rates differ."""
        if from_rate == to_rate:
            return audio

        # Simple linear interpolation resampling
        ratio = to_rate / from_rate
        new_len = max(1, int(len(audio) * ratio))
        indices = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(indices, np.arange(len(audio)), audio).astype(np.float32)

    def _audio_to_wav(self, audio: np.ndarray, sample_rate: int) -> bytes:
        """Convert numpy audio array to WAV bytes."""
        # Normalize to [-1, 1] range
        audio = np.clip(audio, -1.0, 1.0)

        # Convert to int16
        audio_int = (audio * 32767).astype(np.int16)

        # Write to WAV in memory
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)  # mono
            wf.setsampwidth(2)  # 2 bytes = 16 bits
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int.tobytes())

        return buffer.getvalue()

    def list_voices(self) -> list[str]:
        """List available voice presets."""
        if not self._vibevoice_available:
            return ["carter"]  # fallback

        try:
            from vibevoice_tts import VibeVoiceTTS as VTS
            tts = VTS(device="cpu")
            return tts.list_voices()
        except Exception as exc:
            _logger.warning(f"Could not list voices: {exc}")
            return ["carter"]


async def synthesize_speech(
    text: str,
    voice: str = "carter",
) -> bytes:
    """Convenience function for synthesizing speech.

    Args:
        text: Text to synthesize
        voice: Voice name

    Returns:
        WAV audio bytes
    """
    client = VibeVoiceTTSClient()
    return await client.synthesize_speech(text, voice)
