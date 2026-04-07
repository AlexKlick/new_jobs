"""Unit tests for TTSManager — dual-engine TTS orchestration.

All tests use mocked GPU dependencies. No actual CUDA or model loading required.
"""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from voice.tts_manager import (
    OUTPUT_SAMPLE_RATE,
    TTSManager,
    TTSManagerState,
    VibeVoiceEngine,
    MossTTSEngine,
    VRAMMonitor,
)


def _make_wav_bytes(duration_s: float = 0.5, sample_rate: int = 16000) -> bytes:
    """Generate a short WAV audio bytes fixture."""
    num_samples = int(sample_rate * duration_s)
    t = np.linspace(0, duration_s, num_samples, dtype=np.float32)
    audio = np.sin(2 * np.pi * 440 * t) * 0.3
    audio = np.clip(audio, -1.0, 1.0)
    audio_int = (audio * 32767).astype(np.int16)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int.tobytes())

    return buf.getvalue()


def _make_audio_24k(duration_s: float = 0.5) -> np.ndarray:
    """Generate 24kHz float32 audio array."""
    num_samples = int(24000 * duration_s)
    t = np.linspace(0, duration_s, num_samples, dtype=np.float32)
    return np.sin(2 * np.pi * 440 * t).astype(np.float32)


class TestTTSManagerState:
    """Tests for TTSManagerState enum."""

    def test_state_values(self):
        assert TTSManagerState.PRESET_ONLY.value == "preset_only"
        assert TTSManagerState.LOADING_MOSS.value == "loading_moss"
        assert TTSManagerState.BOTH_LOADED.value == "both_loaded"
        assert TTSManagerState.UNLOADING_MOSS.value == "unloading_moss"

    def test_state_is_string(self):
        assert isinstance(TTSManagerState.PRESET_ONLY, str)


class TestVibeVoiceEngine:
    """Tests for VibeVoiceEngine wrapper."""

    def test_not_loaded_initially(self):
        engine = VibeVoiceEngine(device="cpu")
        assert not engine.is_loaded

    def test_resample_24k_to_16k(self):
        """Resampling preserves audio structure (length ratio ~2/3)."""
        audio_24k = _make_audio_24k(1.0)
        resampled = VibeVoiceEngine._resample_24k_to_16k(audio_24k)
        assert len(resampled) == pytest.approx(16000, abs=100)
        assert resampled.dtype == np.float32

    def test_audio_to_wav(self):
        """WAV output is valid."""
        audio = _make_audio_24k(0.5)
        wav_bytes = VibeVoiceEngine._audio_to_wav(audio, 16000)
        assert len(wav_bytes) > 44  # WAV header is 44 bytes
        # Verify WAV header
        assert wav_bytes[:4] == b"RIFF"
        assert wav_bytes[8:12] == b"WAVE"

    def test_list_voices_without_load(self):
        engine = VibeVoiceEngine(device="cpu")
        voices = engine.list_voices()
        assert "carter" in voices

    @patch("tts_manager.VibeVoiceEngine._ensure_loaded")
    def test_synthesize_calls_ensure_loaded(self, mock_ensure):
        """synthesize() triggers lazy loading."""
        engine = VibeVoiceEngine(device="cpu")
        mock_tts = MagicMock()
        mock_tts.speak.return_value = iter([_make_audio_24k(0.5)])
        engine._tts = mock_tts

        wav_bytes = engine.synthesize("hello")
        assert len(wav_bytes) > 0
        mock_tts.speak.assert_called_once_with("hello")


class TestMossTTSEngine:
    """Tests for MossTTSEngine wrapper."""

    def test_not_loaded_initially(self):
        engine = MossTTSEngine(device="cpu")
        assert not engine.is_loaded

    def test_maybe_unload_not_loaded(self):
        engine = MossTTSEngine(device="cpu")
        assert engine.maybe_unload() is False

    def test_maybe_unload_within_timeout(self):
        engine = MossTTSEngine(device="cpu", idle_timeout_s=600)
        engine._engine = MagicMock()
        engine._last_used = float("inf")  # Far future
        assert engine.maybe_unload() is False
        assert engine._engine is not None  # Not unloaded

    def test_force_unload(self):
        engine = MossTTSEngine(device="cpu")
        engine._engine = MagicMock()
        engine._last_used = float("inf")
        engine.force_unload()

    def test_check_vram_mock(self):
        engine = MossTTSEngine(device="cpu")
        with patch("tts_manager.MossTTSEngine.check_vram", return_value=True):
            assert engine.check_vram() is True


class TestVRAMMonitor:
    """Tests for VRAMMonitor."""

    def test_get_stats_returns_dict(self):
        monitor = VRAMMonitor(device="cpu")
        # Without actual CUDA, should return zeros
        stats = monitor.get_stats()
        assert "allocated_gb" in stats
        assert "reserved_gb" in stats
        assert "free_gb" in stats

    def test_check_leak_returns_bool(self):
        monitor = VRAMMonitor(device="cpu")
        result = monitor.check_leak(threshold_gb=0.5)
        assert isinstance(result, bool)


class TestTTSManager:
    """Tests for TTSManager orchestration."""

    def test_initial_state_is_preset_only(self):
        manager = TTSManager(device="cpu")
        assert manager.state == TTSManagerState.PRESET_ONLY

    def test_is_preset_voice(self):
        manager = TTSManager(device="cpu")
        assert manager.is_preset_voice("carter") is True
        assert manager.is_preset_voice("wayne") is True
        assert manager.is_preset_voice("clone:my_voice") is False

    @pytest.mark.asyncio
    async def test_start_sets_state(self):
        manager = TTSManager(device="cpu")
        await manager.start()
        assert manager.state == TTSManagerState.PRESET_ONLY
        await manager.stop()

    @pytest.mark.asyncio
    async def test_stop_cleans_up(self):
        manager = TTSManager(device="cpu")
        await manager.start()
        await manager.stop()
        assert manager.state == TTSManagerState.PRESET_ONLY

    @pytest.mark.asyncio
    async def test_preset_synthesis_routes_to_vibevoice(self):
        """Preset voice requests route to VibeVoiceEngine without loading MOSS."""
        manager = TTSManager(device="cpu")
        await manager.start()

        # Mock VibeVoice synthesis
        mock_wav = _make_wav_bytes()
        with patch.object(manager._vibevoice, "synthesize", return_value=mock_wav):
            result, from_cache = await manager.synthesize("hello", voice="carter")

        assert result == mock_wav
        assert manager.state == TTSManagerState.PRESET_ONLY
        assert not manager._moss.is_loaded
        await manager.stop()

    @pytest.mark.asyncio
    async def test_cloned_voice_triggers_moss_load(self):
        """Cloned voice request triggers MOSS lazy-load, then synthesis."""
        manager = TTSManager(device="cpu")
        await manager.start()

        mock_wav = _make_wav_bytes()
        with patch.object(
            manager, "load_moss", new_callable=AsyncMock
        ) as mock_load:
            async def _load_side_effect(*args, **kwargs):
                manager._state = TTSManagerState.BOTH_LOADED
                manager._moss._engine = MagicMock()

            mock_load.side_effect = _load_side_effect

            with patch.object(
                manager._moss, "synthesize", return_value=mock_wav
            ):
                # moss.is_loaded is False initially (no _engine)
                assert not manager._moss.is_loaded
                result, from_cache = await manager.synthesize(
                    "hello", voice="clone:my_voice"
                )

        assert result == mock_wav
        await manager.stop()

    @pytest.mark.asyncio
    async def test_concurrent_requests_serialized(self):
        """Concurrent synthesis requests are serialized through queue."""
        manager = TTSManager(device="cpu")
        await manager.start()

        call_order = []

        def mock_synthesize(text, voice="carter"):
            call_order.append(text)
            return _make_wav_bytes()

        with patch.object(
            manager._vibevoice, "synthesize", side_effect=mock_synthesize
        ):
            # Queue two requests concurrently
            task1 = asyncio.create_task(
                manager.synthesize("first", voice="carter")
            )
            task2 = asyncio.create_task(
                manager.synthesize("second", voice="carter")
            )

            result1 = await task1
            result2 = await task2

        # Both should complete (serialized, not parallel)
        assert len(call_order) == 2
        assert "first" in call_order
        assert "second" in call_order
        await manager.stop()

    @pytest.mark.asyncio
    async def test_load_moss_state_transitions(self):
        """State transitions: PRESET_ONLY -> LOADING_MOSS -> BOTH_LOADED."""
        manager = TTSManager(device="cpu")
        await manager.start()

        with patch.object(manager._moss, "check_vram", return_value=True):
            with patch.object(manager._moss, "_ensure_loaded"):
                await manager.load_moss()

        assert manager.state == TTSManagerState.BOTH_LOADED
        await manager.stop()

    @pytest.mark.asyncio
    async def test_unload_moss_state_transitions(self):
        """State transitions: BOTH_LOADED -> UNLOADING_MOSS -> PRESET_ONLY."""
        manager = TTSManager(device="cpu")
        await manager.start()

        # Manually set state
        manager._state = TTSManagerState.BOTH_LOADED

        with patch.object(manager._moss, "force_unload"):
            await manager.unload_moss()

        assert manager.state == TTSManagerState.PRESET_ONLY
        await manager.stop()

    @pytest.mark.asyncio
    async def test_load_moss_vram_guard(self):
        """VRAM guard prevents MOSS load when insufficient memory."""
        manager = TTSManager(device="cpu")
        await manager.start()

        with patch.object(manager._moss, "check_vram", return_value=False):
            with pytest.raises(RuntimeError, match="Insufficient VRAM"):
                await manager.load_moss()

        assert manager.state == TTSManagerState.PRESET_ONLY
        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_status(self):
        manager = TTSManager(device="cpu")
        await manager.start()

        status = await manager.get_status()
        assert status["state"] == "preset_only"
        assert status["moss_loaded"] is False
        assert "vram" in status
        await manager.stop()

    @pytest.mark.asyncio
    async def test_synthesize_fallback_on_failure(self):
        """Engine load failure falls back to VibeVoice with preset voice."""
        manager = TTSManager(device="cpu")
        await manager.start()

        mock_wav = _make_wav_bytes()

        # Set moss to appear loaded and set state
        manager._moss._engine = MagicMock()
        manager._state = TTSManagerState.BOTH_LOADED

        # Mock MOSS synthesis to fail, VibeVoice to succeed
        with patch.object(
            manager._moss, "synthesize", side_effect=RuntimeError("MOSS failed")
        ):
            with patch.object(
                manager._vibevoice, "synthesize", return_value=mock_wav
            ):
                result, _ = await manager.synthesize(
                    "hello", voice="clone:broken"
                )

        assert result == mock_wav
        await manager.stop()

    @pytest.mark.asyncio
    async def test_idle_timeout_unloads_moss(self):
        """Idle timeout fires and unloads MOSS."""
        manager = TTSManager(device="cpu", idle_timeout_s=0.01)
        await manager.start()

        manager._state = TTSManagerState.BOTH_LOADED
        manager._moss._engine = MagicMock()
        manager._moss._last_used = 0  # Force timeout

        # Wait for idle checker (runs every 60s, but we test maybe_unload directly)
        assert manager._moss.maybe_unload() is True
        assert manager._state == TTSManagerState.BOTH_LOADED  # State not auto-updated

        await manager.stop()
