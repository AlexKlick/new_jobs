"""
TTS Manager — Dual-engine TTS orchestration with GPU resource management

Orchestrates VibeVoice (always-loaded, preset voices) and MOSS-TTS
(lazy-loaded, voice cloning) on GPU 1 (RTX 3060 12GB). Uses a 4-state
state machine and async queue for serialized GPU access.

State Machine:
    PRESET_ONLY -> LOADING_MOSS -> BOTH_LOADED -> UNLOADING_MOSS -> PRESET_ONLY

Usage:
    manager = TTSManager(device="cuda:1")
    await manager.start()
    wav_bytes, from_cache = await manager.synthesize("Hello!", voice="carter")
"""

from __future__ import annotations

import asyncio
import gc
import io
import logging
import sys
import time
import wave
from enum import Enum
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

_logger = logging.getLogger(__name__)

# Target output rate for chat playback (16kHz)
OUTPUT_SAMPLE_RATE = 16000
# Native rate of both engines
ENGINE_SAMPLE_RATE = 24000


class TTSManagerState(str, Enum):
    """States for TTS engine lifecycle management."""

    PRESET_ONLY = "preset_only"  # VibeVoice loaded, MOSS unloaded
    LOADING_MOSS = "loading_moss"  # Transitioning MOSS onto GPU
    BOTH_LOADED = "both_loaded"  # Both engines available
    UNLOADING_MOSS = "unloading_moss"  # Transitioning MOSS off GPU


class VibeVoiceEngine:
    """Wrapper around VibeVoice TTS for preset voice synthesis.

    Always loaded on GPU 1. Synthesizes at 24kHz native rate,
    then resamples to 16kHz for output.
    """

    def __init__(self, device: str = "cuda:1", voice_name: str = "carter"):
        self.device = device
        self.voice_name = voice_name
        self._tts = None

    @property
    def is_loaded(self) -> bool:
        return self._tts is not None

    def _ensure_loaded(self):
        """Lazy-load VibeVoice TTS on first synthesis call."""
        if self._tts is not None:
            return

        try:
            # Add vibevoice_agent to path for import
            vibevoice_dir = str(Path(__file__).parent.parent / "vibevoice_agent")
            if vibevoice_dir not in sys.path:
                sys.path.insert(0, vibevoice_dir)

            from vibevoice_tts import VibeVoiceTTS

            self._tts = VibeVoiceTTS(device=self.device, voice_name=self.voice_name)
            _logger.info(f"VibeVoice engine loaded on {self.device}")
        except Exception as exc:
            _logger.error(f"Failed to load VibeVoice engine: {exc}")
            raise

    def synthesize(self, text: str, voice: str = "carter") -> bytes:
        """Synthesize text to WAV bytes at 16kHz.

        Args:
            text: Text to synthesize.
            voice: Voice preset name.

        Returns:
            WAV audio bytes (16kHz mono PCM).
        """
        self._ensure_loaded()

        # Collect audio chunks from streaming generator
        audio_chunks: list[np.ndarray] = []
        for chunk in self._tts.speak(text):
            audio_chunks.append(chunk)

        if not audio_chunks:
            # Return silence if no audio produced
            audio = np.zeros(int(OUTPUT_SAMPLE_RATE * 0.5), dtype=np.float32)
            return self._audio_to_wav(audio, OUTPUT_SAMPLE_RATE)

        audio = np.concatenate(audio_chunks)
        audio = self._resample_24k_to_16k(audio)
        return self._audio_to_wav(audio, OUTPUT_SAMPLE_RATE)

    def list_voices(self) -> list[str]:
        """List available preset voice names."""
        if self._tts is None:
            return ["carter"]
        try:
            return self._tts.list_voices()
        except Exception:
            return ["carter"]

    @staticmethod
    def _resample_24k_to_16k(audio: np.ndarray) -> np.ndarray:
        """Resample from 24kHz to 16kHz using scipy.signal.resample_poly.

        Uses resample_poly for high-quality resampling. NOT np.interp
        which destroys audio quality per CONTEXT.md locked decision.
        """
        from scipy.signal import resample_poly

        # GCD(24000, 16000) = 8000, so up=2, down=3
        return resample_poly(audio, 2, 3).astype(np.float32)

    @staticmethod
    def _audio_to_wav(audio: np.ndarray, sample_rate: int) -> bytes:
        """Convert numpy float32 audio to WAV bytes (int16 mono)."""
        audio = np.clip(audio, -1.0, 1.0)
        audio_int = (audio * 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_int.tobytes())

        return buf.getvalue()


class MossTTSEngine:
    """Wrapper around MOSS-TTS for voice cloning synthesis.

    Lazy-loaded only when a cloned voice is requested. Unloads after
    idle timeout to reclaim VRAM on GPU 1.
    """

    def __init__(self, device: str = "cuda:1", idle_timeout_s: float = 600):
        self.device = device
        self.idle_timeout_s = idle_timeout_s
        self._engine = None
        self._last_used: float = 0.0

    @property
    def is_loaded(self) -> bool:
        return self._engine is not None

    def _ensure_loaded(self):
        """Load MOSS-TTS if not already loaded."""
        if self._engine is not None:
            return

        try:
            # Add moss_tts_realtime to path
            moss_dir = str(Path(__file__).parent.parent / "moss_tts_realtime")
            if moss_dir not in sys.path:
                sys.path.insert(0, moss_dir)

            from scrum_master_tts import ScrumMasterTTS

            self._engine = ScrumMasterTTS(device=self.device)
            self._last_used = time.monotonic()
            _logger.info(f"MOSS-TTS engine loaded on {self.device}")
        except Exception as exc:
            _logger.error(f"Failed to load MOSS-TTS engine: {exc}")
            raise

    def synthesize(self, text: str, voice_path: str | None = None) -> bytes:
        """Synthesize text to WAV bytes at 16kHz.

        Args:
            text: Text to synthesize.
            voice_path: Path to voice reference WAV for cloning.

        Returns:
            WAV audio bytes (16kHz mono PCM).
        """
        self._ensure_loaded()

        if voice_path is not None:
            self._engine.set_voice(voice_path)

        audio = self._engine.synthesize(text)

        # Resample from 24kHz to 16kHz
        from scipy.signal import resample_poly

        audio = resample_poly(audio, 2, 3).astype(np.float32)
        self._last_used = time.monotonic()

        return VibeVoiceEngine._audio_to_wav(audio, OUTPUT_SAMPLE_RATE)

    def set_voice(self, audio_path: str) -> None:
        """Set voice reference for cloning.

        Args:
            audio_path: Path to reference audio WAV file.
        """
        self._ensure_loaded()
        self._engine.set_voice(audio_path)
        self._last_used = time.monotonic()

    def maybe_unload(self) -> bool:
        """Unload MOSS if idle timeout has elapsed.

        Follows ARCHITECTURE.md unload sequence:
        1. Delete model, codec, voice_tokens
        2. gc.collect()
        3. torch.cuda.empty_cache()
        4. torch.cuda.synchronize()

        Returns:
            True if MOSS was unloaded, False if still within idle timeout.
        """
        if self._engine is None:
            return False

        if time.monotonic() - self._last_used <= self.idle_timeout_s:
            return False

        _logger.info("MOSS idle timeout reached, unloading engine...")

        try:
            # Unload sequence per ARCHITECTURE.md
            if hasattr(self._engine, "_model"):
                del self._engine._model
            if hasattr(self._engine, "_codec"):
                del self._engine._codec
            if hasattr(self._engine, "_voice_tokens"):
                del self._engine._voice_tokens
        except Exception as exc:
            _logger.warning(f"Error during MOSS attribute cleanup: {exc}")

        self._engine = None
        gc.collect()

        try:
            import torch

            torch.cuda.empty_cache(torch.device(self.device))
            torch.cuda.synchronize(torch.device(self.device))
        except Exception as exc:
            _logger.warning(f"Error during CUDA cleanup: {exc}")

        _logger.info("MOSS-TTS engine unloaded, VRAM reclaimed")
        return True

    def force_unload(self) -> None:
        """Force unload MOSS regardless of idle timeout."""
        self._last_used = 0.0
        self.maybe_unload()

    def check_vram(self, required_gb: float = 7.0) -> bool:
        """Check if sufficient VRAM is available for MOSS loading.

        Args:
            required_gb: Required VRAM in GB.

        Returns:
            True if enough VRAM is available (with 1GB safety margin).
        """
        try:
            import torch

            free_memory, total_memory = torch.cuda.mem_get_info(self.device)
            free_gb = free_memory / (1024**3)
            return free_gb >= required_gb + 1.0  # 1GB safety margin
        except Exception:
            _logger.warning("Could not check VRAM, assuming available")
            return True


class VRAMMonitor:
    """Monitor VRAM usage on a CUDA device for leak detection."""

    def __init__(self, device: str = "cuda:1", poll_interval_s: float = 30):
        self.device = device
        self.poll_interval_s = poll_interval_s

    def get_stats(self) -> dict:
        """Get current VRAM statistics.

        Returns dict with: allocated_gb, reserved_gb, free_gb.
        """
        try:
            import torch

            device = torch.device(self.device)
            allocated = torch.cuda.memory_allocated(device) / (1024**3)
            reserved = torch.cuda.memory_reserved(device) / (1024**3)
            free_memory, _total = torch.cuda.mem_get_info(device)
            free_gb = free_memory / (1024**3)

            return {
                "allocated_gb": round(allocated, 3),
                "reserved_gb": round(reserved, 3),
                "free_gb": round(free_gb, 3),
            }
        except Exception:
            return {"allocated_gb": 0.0, "reserved_gb": 0.0, "free_gb": 0.0}

    def check_leak(self, threshold_gb: float = 0.5) -> bool:
        """Check for potential VRAM leak after engine unload.

        Returns True if allocated memory exceeds threshold (potential leak).
        """
        stats = self.get_stats()
        return stats["allocated_gb"] > threshold_gb


class TTSManager:
    """Orchestrates dual-engine TTS with GPU resource management.

    Uses a 4-state state machine and async queue for serialized GPU access.
    VibeVoice is always loaded for preset voices. MOSS-TTS lazy-loads on
    clone requests and unloads after idle timeout.
    """

    def __init__(
        self,
        device: str = "cuda:1",
        idle_timeout_s: float = 600,
    ):
        self.device = device
        self._state = TTSManagerState.PRESET_ONLY
        self._vibevoice = VibeVoiceEngine(device=device)
        self._moss = MossTTSEngine(device=device, idle_timeout_s=idle_timeout_s)
        self._vram_monitor = VRAMMonitor(device=device)

        self._queue: asyncio.Queue | None = None
        self._worker_task: asyncio.Task | None = None
        self._idle_check_task: asyncio.Task | None = None

    @property
    def state(self) -> TTSManagerState:
        return self._state

    @property
    def vibevoice(self) -> VibeVoiceEngine:
        return self._vibevoice

    @property
    def moss(self) -> MossTTSEngine:
        return self._moss

    async def start(self) -> None:
        """Initialize VibeVoice and start background tasks."""
        self._queue = asyncio.Queue()
        self._worker_task = asyncio.create_task(self._queue_worker())
        self._idle_check_task = asyncio.create_task(self._idle_checker())
        self._state = TTSManagerState.PRESET_ONLY
        _logger.info("TTSManager started in PRESET_ONLY state")

    async def stop(self) -> None:
        """Stop background tasks and unload engines."""
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        if self._idle_check_task:
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass

        # Unload MOSS if loaded
        if self._moss.is_loaded:
            self._moss.force_unload()

        self._state = TTSManagerState.PRESET_ONLY
        _logger.info("TTSManager stopped")

    def is_preset_voice(self, voice: str) -> bool:
        """Check if a voice is a preset (non-cloned) voice.

        Cloned voices have prefix 'clone:' (e.g., 'clone:my_voice').
        """
        return not voice.startswith("clone:")

    async def synthesize(
        self,
        text: str,
        voice: str = "carter",
        voice_path: str | None = None,
    ) -> tuple[bytes, bool]:
        """Synthesize text using the appropriate engine.

        Args:
            text: Text to synthesize.
            voice: Voice name (preset or 'clone:name').
            voice_path: Path to voice reference for cloning.

        Returns:
            Tuple of (wav_bytes, from_cache_hint).
        """
        if self._queue is None:
            raise RuntimeError("TTSManager not started. Call start() first.")

        future = asyncio.get_event_loop().create_future()
        await self._queue.put((text, voice, voice_path, future))
        return await future

    async def load_moss(
        self,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Load MOSS-TTS engine, transitioning state machine.

        Args:
            progress_callback: Optional callback(message, progress_pct).
        """
        if self._state != TTSManagerState.PRESET_ONLY:
            _logger.info(f"Cannot load MOSS in state {self._state}")
            return

        self._state = TTSManagerState.LOADING_MOSS
        _logger.info("Transitioning to LOADING_MOSS state")

        try:
            if progress_callback:
                progress_callback("Checking VRAM...", 0.1)

            if not self._moss.check_vram():
                raise RuntimeError(
                    "Insufficient VRAM to load MOSS-TTS. "
                    f"Required: ~7GB free + 1GB margin on {self.device}"
                )

            if progress_callback:
                progress_callback("Loading MOSS-TTS model...", 0.3)

            self._moss._ensure_loaded()

            if progress_callback:
                progress_callback("MOSS-TTS ready", 1.0)

            self._state = TTSManagerState.BOTH_LOADED
            _logger.info("Transitioned to BOTH_LOADED state")

        except Exception as exc:
            _logger.error(f"Failed to load MOSS: {exc}")
            self._state = TTSManagerState.PRESET_ONLY
            raise

    async def unload_moss(self) -> None:
        """Unload MOSS-TTS engine, transitioning state machine."""
        if self._state != TTSManagerState.BOTH_LOADED:
            _logger.info(f"Cannot unload MOSS in state {self._state}")
            return

        self._state = TTSManagerState.UNLOADING_MOSS
        _logger.info("Transitioning to UNLOADING_MOSS state")

        self._moss.force_unload()

        self._state = TTSManagerState.PRESET_ONLY
        _logger.info("Transitioned back to PRESET_ONLY state")

    async def get_status(self) -> dict:
        """Get current engine status and VRAM stats."""
        return {
            "state": self._state.value,
            "moss_loaded": self._moss.is_loaded,
            "vram": self._vram_monitor.get_stats(),
        }

    async def _queue_worker(self) -> None:
        """Worker that processes synthesis requests one at a time."""
        while True:
            try:
                text, voice, voice_path, future = await self._queue.get()

                try:
                    if self.is_preset_voice(voice):
                        # Route to VibeVoice for preset voices
                        wav_bytes = self._vibevoice.synthesize(text, voice=voice)
                    else:
                        # Route to MOSS for cloned voices
                        if not self._moss.is_loaded:
                            await self.load_moss()

                        wav_bytes = self._moss.synthesize(text, voice_path=voice_path)

                    if not future.done():
                        future.set_result((wav_bytes, False))

                except Exception as exc:
                    if not future.done():
                        # Fallback: try VibeVoice with default voice
                        _logger.warning(
                            f"Synthesis failed, falling back to VibeVoice: {exc}"
                        )
                        try:
                            wav_bytes = self._vibevoice.synthesize(text, voice="carter")
                            future.set_result((wav_bytes, False))
                        except Exception as fallback_exc:
                            future.set_exception(fallback_exc)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.error(f"Queue worker error: {exc}")

    async def _idle_checker(self) -> None:
        """Periodically check if MOSS should be unloaded due to idle."""
        while True:
            try:
                await asyncio.sleep(60)
                if (
                    self._state == TTSManagerState.BOTH_LOADED
                    and self._moss.maybe_unload()
                ):
                    self._state = TTSManagerState.PRESET_ONLY
                    _logger.info("MOSS idle timeout: transitioned to PRESET_ONLY")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.error(f"Idle checker error: {exc}")
