"""
Audio Processing Utilities for Voice Pipeline

Provides audio preprocessing and VAD (Voice Activity Detection) utilities:
- preprocess_audio: Convert any audio format to 16kHz mono PCM numpy array
- detect_speech_segments: Use Silero VAD to detect speech segments
- get_audio_duration: Return audio duration in seconds

Constants:
- SAMPLE_RATE: 16000 Hz (standard for VAD/ASR)
- VAD_THRESHOLD: 0.5 (speech probability threshold)
- MIN_SPEECH_DURATION: 0.3s (minimum speech segment duration)
- MIN_SILENCE_DURATION: 0.5s (minimum silence to split segments)
"""

from __future__ import annotations

import io
import logging
from typing import Optional

import numpy as np
import torch

_logger = logging.getLogger(__name__)

# Constants
SAMPLE_RATE = 16000
VAD_THRESHOLD = 0.5
MIN_SPEECH_DURATION = 0.3
MIN_SILENCE_DURATION = 0.5

# Silero VAD model constants
_SILERO_REPO = "snakers4/silero-vad"
_SILERO_MODEL = "silero_vad"


# ---------------------------------------------------------------------------
# Silero VAD Helper
# ---------------------------------------------------------------------------

class _SileroVADHelper:
    """Lazy-loaded Silero VAD model helper."""

    _instance: Optional["_SileroVADHelper"] = None
    _model: Optional[torch.nn.Module] = None
    _utils: Optional[dict] = None

    @classmethod
    def get_instance(cls) -> "_SileroVADHelper":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_model(self) -> None:
        if self._model is None:
            _logger.info("Loading Silero VAD model from torch.hub...")
            self._model, self._utils = torch.hub.load(
                repo_or_dir=_SILERO_REPO,
                model=_SILERO_MODEL,
                force_reload=False,
                trust_repo=True,
            )
            self._model.eval()

    def get_speech_prob(self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
        """
        Get speech probability for an audio chunk.

        Args:
            audio: Audio samples as numpy array (float32, shape [samples])
            sample_rate: Sample rate in Hz

        Returns:
            Speech probability (0.0-1.0)
        """
        self._load_model()

        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        # Convert to torch tensor
        tensor = torch.from_numpy(audio)

        # Silero VAD requires exactly 512 samples for 16kHz (32ms frame)
        expected_samples = 512 if sample_rate == 16000 else 256

        # Handle variable-length input
        if tensor.numel() > expected_samples:
            tensor = tensor[-expected_samples:]
        elif tensor.numel() < expected_samples:
            padding = torch.zeros(expected_samples - tensor.numel(), dtype=tensor.dtype)
            tensor = torch.cat([padding, tensor])

        # Add batch dimension
        if tensor.ndim == 1:
            tensor = tensor.unsqueeze(0)

        with torch.no_grad():
            prob = self._model(tensor, sample_rate).item()

        return float(prob)

    def is_speech(self, audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bool:
        """Return True if audio contains speech above threshold."""
        return self.get_speech_prob(audio, sample_rate) > VAD_THRESHOLD


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess_audio(audio_bytes: bytes) -> np.ndarray:
    """
    Convert uploaded audio (any format) to 16kHz mono PCM numpy array.

    Supports common audio formats by decoding through pydub/soundfile.
    Falls back to raw PCM interpretation if format detection fails.

    Args:
        audio_bytes: Raw audio file bytes (any format: WAV, MP3, OGG, etc.)

    Returns:
        np.ndarray of int16 samples at 16000 Hz (mono)
    """
    try:
        import soundfile as sf

        # Try to decode with soundfile (supports many formats)
        with io.BytesIO(audio_bytes) as bio:
            data, samplerate = sf.read(bio, dtype="int16")
            bio.close()

        # Convert stereo to mono by averaging
        if len(data.shape) > 1 and data.shape[1] > 1:
            data = np.mean(data, axis=1).astype(np.int16)

        # Resample to 16kHz if needed
        if samplerate != SAMPLE_RATE:
            data = _resample(data, samplerate, SAMPLE_RATE)

        return data.astype(np.int16)

    except ImportError:
        _logger.warning("soundfile not available, trying pydub...")
    except Exception as exc:
        _logger.warning(f"soundfile decode failed ({exc}), trying pydub...")

    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        audio = audio.set_frame_rate(SAMPLE_RATE).set_channels(1)
        samples = np.array(audio.get_array_of_samples(), dtype=np.int16)
        return samples

    except ImportError:
        _logger.warning("pydub not available, trying torchaudio...")
    except Exception as exc:
        _logger.warning(f"pydub decode failed ({exc}), trying torchaudio...")

    # Final fallback: try torchaudio
    try:
        import torchaudio

        with io.BytesIO(audio_bytes) as bio:
            waveform, samplerate = torchaudio.load(bio)
            bio.close()

        # Convert stereo to mono
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        # Resample to 16kHz
        if samplerate != SAMPLE_RATE:
            resampler = torchaudio.transforms.Resample(
                orig_freq=samplerate, new_freq=SAMPLE_RATE
            )
            waveform = resampler(waveform)

        waveform = waveform.squeeze().numpy().astype(np.int16)
        return waveform

    except ImportError:
        _logger.error("No audio decoding library available (soundfile, pydub, torchaudio)")
        raise RuntimeError(
            "Cannot decode audio: install soundfile, pydub, or torchaudio"
        )
    except Exception as exc:
        _logger.error(f"torchaudio decode failed: {exc}")
        raise RuntimeError(f"Cannot decode audio: {exc}")


def _resample(data: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """
    Simple linear interpolation resampling.

    Args:
        data: Input audio array (int16)
        from_rate: Original sample rate
        to_rate: Target sample rate

    Returns:
        Resampled audio array (int16)
    """
    if from_rate == to_rate:
        return data

    ratio = to_rate / from_rate
    new_len = max(1, int(len(data) * ratio))
    indices = np.linspace(0, len(data) - 1, new_len)
    resampled = np.interp(indices, np.arange(len(data)), data.astype(np.float64))
    return resampled.astype(np.int16)


def detect_speech_segments(
    audio: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    threshold: float = VAD_THRESHOLD,
    min_speech_duration: float = MIN_SPEECH_DURATION,
    min_silence_duration: float = MIN_SILENCE_DURATION,
) -> list[tuple[float, float]]:
    """
    Detect speech segments using Silero VAD.

    Scans through audio in 32ms frames (512 samples at 16kHz) and identifies
    contiguous speech regions. Merges segments separated by short silence.

    Args:
        audio: Audio samples as numpy array (int16 or float32)
        sample_rate: Sample rate in Hz (default 16000)
        threshold: Speech probability threshold (0.0-1.0), default 0.5
        min_speech_duration: Minimum duration (seconds) for a valid speech segment
        min_silence_duration: Minimum silence duration (seconds) to split segments

    Returns:
        List of (start_time, end_time) tuples in seconds
    """
    # Convert to float32 normalized if int16
    if audio.dtype == np.int16:
        audio_float = audio.astype(np.float32) / 32768.0
    else:
        audio_float = audio.astype(np.float32)

    helper = _SileroVADHelper.get_instance()

    # Frame size: 512 samples at 16kHz = 32ms
    frame_size = 512 if sample_rate == 16000 else 256
    hop_size = frame_size  # No overlap for simplicity
    num_frames = (len(audio_float) - frame_size) // hop_size + 1

    if num_frames <= 0:
        return []

    speech_frames: list[int] = []
    for i in range(num_frames):
        start = i * hop_size
        end = start + frame_size
        frame = audio_float[start:end]
        prob = helper.get_speech_prob(frame, sample_rate)
        if prob > threshold:
            speech_frames.append(i)

    # Convert frame indices to time
    frame_times = [i * hop_size / sample_rate for i in speech_frames]

    if not frame_times:
        return []

    # Build segments by grouping consecutive frames
    segments: list[tuple[float, float]] = []
    seg_start = frame_times[0]
    seg_end = frame_times[0]

    min_silence_frames = int(min_silence_duration * sample_rate / hop_size)

    for i in range(1, len(frame_times)):
        if frame_times[i] - seg_end >= min_silence_duration:
            # End current segment
            segments.append((seg_start, seg_end))
            seg_start = frame_times[i]
        seg_end = frame_times[i]

    # Final segment
    segments.append((seg_start, seg_end))

    # Filter short segments
    filtered = [
        (s, e) for s, e in segments
        if e - s >= min_speech_duration
    ]

    return filtered


def get_audio_duration(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    """
    Return the duration of audio in seconds.

    Args:
        audio: Audio samples as numpy array
        sample_rate: Sample rate in Hz

    Returns:
        Duration in seconds (float)
    """
    return len(audio) / sample_rate


__all__ = [
    "preprocess_audio",
    "detect_speech_segments",
    "get_audio_duration",
    "SAMPLE_RATE",
    "VAD_THRESHOLD",
    "MIN_SPEECH_DURATION",
    "MIN_SILENCE_DURATION",
]
