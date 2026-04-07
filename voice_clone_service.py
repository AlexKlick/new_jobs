"""
Voice Clone Service — Audio validation, processing, and storage for voice cloning

Validates uploaded 24kHz WAV recordings (3-10 seconds), applies 80Hz high-pass
filter to remove room hum, and stores processed files for MOSS-TTS voice cloning.

Usage:
    service = VoiceCloneService()
    path = service.process_and_store(wav_bytes, name="my_voice")
    clones = service.list_clones()
"""

from __future__ import annotations

import io
import logging
import re
import wave
from pathlib import Path

import numpy as np

_logger = logging.getLogger(__name__)


class VoiceCloneService:
    """Service for processing and storing voice clone recordings.

    Validates duration (3-10s), sample rate (24kHz), mono channel,
    applies 80Hz high-pass filter, and stores to disk.
    """

    def __init__(self, storage_dir: Path | None = None):
        self.storage_dir = storage_dir or Path(".voice_clones")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def validate_audio(wav_bytes: bytes) -> tuple[np.ndarray, int]:
        """Validate and parse WAV audio bytes.

        Args:
            wav_bytes: Raw WAV file bytes.

        Returns:
            Tuple of (float32 audio array, sample_rate).

        Raises:
            ValueError: If validation fails (wrong rate, duration, etc.).
        """
        buf = io.BytesIO(wav_bytes)
        try:
            with wave.open(buf, "rb") as wf:
                nchannels = wf.getnchannels()
                sample_rate = wf.getframerate()
                nframes = wf.getnframes()
                frames = wf.readframes(nframes)
        except wave.Error as exc:
            raise ValueError(f"Invalid WAV file: {exc}") from exc

        # Convert to float32
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32767.0

        # Handle stereo -> mono conversion
        if nchannels > 1:
            audio = audio.reshape(-1, nchannels).mean(axis=1)
            _logger.warning("Converting stereo to mono")

        # Validate sample rate
        if sample_rate != 24000:
            raise ValueError(
                f"Expected 24kHz, got {sample_rate}Hz. "
                "Voice cloning requires 24kHz audio."
            )

        # Validate duration
        duration = len(audio) / sample_rate
        if duration < 3.0:
            raise ValueError(
                "Recording too short. Please record at least 3 seconds."
            )
        if duration > 10.0:
            raise ValueError(
                "Recording exceeds 10 seconds. Please try again."
            )

        return audio, sample_rate

    @staticmethod
    def apply_highpass_filter(
        audio: np.ndarray,
        sample_rate: int,
        cutoff_hz: float = 80.0,
    ) -> np.ndarray:
        """Apply high-pass filter to remove low-frequency noise (room hum).

        Args:
            audio: Float32 audio array.
            sample_rate: Audio sample rate.
            cutoff_hz: Cutoff frequency in Hz (default 80Hz).

        Returns:
            Filtered audio array.
        """
        from scipy.signal import butter, filtfilt

        b, a = butter(2, cutoff_hz, btype="high", fs=sample_rate)
        filtered = filtfilt(b, a, audio)
        return filtered.astype(np.float32)

    def process_and_store(self, wav_bytes: bytes, name: str) -> Path:
        """Validate, process, and store a voice clone recording.

        Args:
            wav_bytes: Raw WAV file bytes.
            name: Name for the voice clone.

        Returns:
            Path to stored WAV file.
        """
        # Validate
        audio, sr = self.validate_audio(wav_bytes)

        # Apply high-pass filter
        audio = self.apply_highpass_filter(audio, sr)

        # Sanitize name
        sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "", name.strip())
        if not sanitized:
            sanitized = "user_voice"

        # Save to disk
        file_path = self.storage_dir / f"{sanitized}.wav"
        self._save_wav(audio, sr, file_path)

        _logger.info(f"Voice clone stored: {file_path}")
        return file_path

    @staticmethod
    def _save_wav(
        audio: np.ndarray, sample_rate: int, path: Path
    ) -> None:
        """Save float32 audio as int16 WAV file."""
        audio = np.clip(audio, -1.0, 1.0)
        audio_int = (audio * 32767).astype(np.int16)

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int.tobytes())

    def list_clones(self) -> list[dict]:
        """List all stored voice clones.

        Returns:
            List of dicts with name, path, size_kb, sorted by mtime (newest first).
        """
        clones = []
        for path in self.storage_dir.glob("*.wav"):
            stat = path.stat()
            clones.append(
                {
                    "name": path.stem,
                    "path": str(path),
                    "size_kb": round(stat.st_size / 1024, 1),
                    "mtime": stat.st_mtime,
                }
            )
        clones.sort(key=lambda c: c["mtime"], reverse=True)

        # Remove mtime from output
        for c in clones:
            del c["mtime"]

        return clones

    def delete_clone(self, name: str) -> bool:
        """Delete a stored voice clone.

        Args:
            name: Clone name (will be sanitized).

        Returns:
            True if deleted, False if not found.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "", name.strip())
        path = self.storage_dir / f"{sanitized}.wav"

        if path.exists():
            path.unlink()
            _logger.info(f"Voice clone deleted: {path}")
            return True
        return False

    def get_clone_path(self, name: str) -> Path | None:
        """Get the path to a stored voice clone.

        Args:
            name: Clone name (will be sanitized).

        Returns:
            Path if exists, None otherwise.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "", name.strip())
        path = self.storage_dir / f"{sanitized}.wav"
        return path if path.exists() else None
