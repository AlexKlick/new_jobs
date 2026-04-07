"""Unit tests for VoiceCloneService — audio validation, processing, storage."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
import pytest

from voice.voice_clone_service import VoiceCloneService


def _make_wav(
    duration_s: float = 5.0,
    sample_rate: int = 24000,
    nchannels: int = 1,
    frequency: float = 440.0,
) -> bytes:
    """Generate WAV bytes fixture for testing.

    Args:
        duration_s: Duration in seconds.
        sample_rate: Sample rate in Hz.
        nchannels: Number of channels (1=mono, 2=stereo).
        frequency: Tone frequency in Hz.

    Returns:
        WAV file bytes.
    """
    num_samples = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, num_samples, dtype=np.float32)
    audio_mono = np.sin(2 * np.pi * frequency * t).astype(np.float32)

    if nchannels > 1:
        audio = np.column_stack([audio_mono] * nchannels).flatten()
    else:
        audio = audio_mono

    audio = np.clip(audio, -1.0, 1.0)
    audio_int = (audio * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int.tobytes())

    return buf.getvalue()


@pytest.fixture
def service(tmp_path: Path) -> VoiceCloneService:
    """Create a VoiceCloneService with isolated temp storage."""
    return VoiceCloneService(storage_dir=tmp_path / "voice_clones")


@pytest.fixture
def valid_wav() -> bytes:
    """Valid 24kHz mono WAV, 5 seconds."""
    return _make_wav(duration_s=5.0, sample_rate=24000)


class TestValidateAudio:
    """Tests for audio validation."""

    def test_valid_wav_passes(self, service: VoiceCloneService, valid_wav: bytes):
        audio, sr = service.validate_audio(valid_wav)
        assert sr == 24000
        assert len(audio) > 0
        assert audio.dtype == np.float32

    def test_validate_duration_too_short(self, service: VoiceCloneService):
        wav = _make_wav(duration_s=2.0, sample_rate=24000)
        with pytest.raises(ValueError, match="too short"):
            service.validate_audio(wav)

    def test_validate_duration_too_long(self, service: VoiceCloneService):
        wav = _make_wav(duration_s=11.0, sample_rate=24000)
        with pytest.raises(ValueError, match="exceeds 10 seconds"):
            service.validate_audio(wav)

    def test_validate_wrong_sample_rate(self, service: VoiceCloneService):
        wav = _make_wav(duration_s=5.0, sample_rate=16000)
        with pytest.raises(ValueError, match="Expected 24kHz"):
            service.validate_audio(wav)

    def test_validate_stereo_converted_to_mono(self, service: VoiceCloneService):
        wav = _make_wav(duration_s=5.0, sample_rate=24000, nchannels=2)
        # Should not raise — stereo is converted to mono
        audio, sr = service.validate_audio(wav)
        assert sr == 24000
        # Duration should be correct after mono conversion
        duration = len(audio) / sr
        assert 4.9 < duration < 5.1


class TestHighpassFilter:
    """Tests for high-pass filter application."""

    def test_highpass_removes_low_frequencies(self):
        """Verify that 80Hz high-pass filter removes sub-80Hz content."""
        sr = 24000
        duration = 1.0
        t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)

        # Mix 30Hz (below cutoff) and 440Hz (above cutoff)
        audio = np.sin(2 * np.pi * 30 * t) + np.sin(2 * np.pi * 440 * t)

        filtered = VoiceCloneService.apply_highpass_filter(audio, sr, cutoff_hz=80.0)

        # After filtering, the 30Hz component should be greatly attenuated
        # Check via FFT
        fft = np.fft.rfft(filtered)
        freqs = np.fft.rfftfreq(len(filtered), d=1.0 / sr)

        # Power in 30Hz bin region should be much lower
        low_mask = freqs < 60  # Below cutoff
        high_mask = (freqs > 400) & (freqs < 500)  # Around 440Hz

        low_power = np.sum(np.abs(fft[low_mask]) ** 2)
        high_power = np.sum(np.abs(fft[high_mask]) ** 2)

        # High frequency should dominate after filtering
        assert high_power > low_power * 10


class TestProcessAndStore:
    """Tests for processing and storing voice clones."""

    def test_process_and_store_valid(self, service: VoiceCloneService, valid_wav: bytes):
        path = service.process_and_store(valid_wav, name="test_voice")
        assert path.exists()
        assert path.name == "test_voice.wav"
        assert path.parent == service.storage_dir

    def test_stored_file_path_pattern(self, service: VoiceCloneService, valid_wav: bytes):
        path = service.process_and_store(valid_wav, name="my_voice")
        assert str(path).endswith(".voice_clones/my_voice.wav") or "voice_clones" in str(path)

    def test_name_sanitization(self, service: VoiceCloneService, valid_wav: bytes):
        path = service.process_and_store(valid_wav, name="Test Voice 123!")
        assert path.name == "TestVoice123.wav"

    def test_empty_name_uses_default(self, service: VoiceCloneService, valid_wav: bytes):
        path = service.process_and_store(valid_wav, name="!!!")
        assert path.name == "user_voice.wav"

    def test_path_traversal_prevention(self, service: VoiceCloneService, valid_wav: bytes):
        path = service.process_and_store(valid_wav, name="../../../etc/passwd")
        assert ".." not in path.name
        assert path.name == "etcpasswd.wav"


class TestListClones:
    """Tests for listing voice clones."""

    def test_list_clones_empty(self, service: VoiceCloneService):
        clones = service.list_clones()
        assert clones == []

    def test_list_clones_returns_stored(self, service: VoiceCloneService, valid_wav: bytes):
        service.process_and_store(valid_wav, name="voice_a")
        service.process_and_store(valid_wav, name="voice_b")

        clones = service.list_clones()
        names = [c["name"] for c in clones]
        assert "voice_a" in names
        assert "voice_b" in names

    def test_list_clones_has_size(self, service: VoiceCloneService, valid_wav: bytes):
        service.process_and_store(valid_wav, name="sized")
        clones = service.list_clones()
        assert len(clones) == 1
        assert clones[0]["size_kb"] > 0

    def test_list_clones_sorted_newest_first(
        self, service: VoiceCloneService, valid_wav: bytes
    ):
        import time

        service.process_and_store(valid_wav, name="old")
        time.sleep(0.05)
        service.process_and_store(valid_wav, name="new")

        clones = service.list_clones()
        assert clones[0]["name"] == "new"
        assert clones[1]["name"] == "old"


class TestDeleteClone:
    """Tests for deleting voice clones."""

    def test_delete_existing(self, service: VoiceCloneService, valid_wav: bytes):
        service.process_and_store(valid_wav, name="to_delete")
        result = service.delete_clone("to_delete")
        assert result is True
        assert service.get_clone_path("to_delete") is None

    def test_delete_nonexistent(self, service: VoiceCloneService):
        result = service.delete_clone("does_not_exist")
        assert result is False

    def test_delete_clears_from_disk(self, service: VoiceCloneService, valid_wav: bytes):
        path = service.process_and_store(valid_wav, name="clear_me")
        assert path.exists()
        service.delete_clone("clear_me")
        assert not path.exists()


class TestGetClonePath:
    """Tests for getting clone path."""

    def test_get_existing_path(self, service: VoiceCloneService, valid_wav: bytes):
        service.process_and_store(valid_wav, name="find_me")
        path = service.get_clone_path("find_me")
        assert path is not None
        assert path.exists()

    def test_get_nonexistent_path(self, service: VoiceCloneService):
        path = service.get_clone_path("no_such_clone")
        assert path is None
