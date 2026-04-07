"""Unit tests for TTSCache — SQLite WAL index + disk storage."""

from __future__ import annotations

import io
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from voice.tts_cache import TTSCache, _compute_cache_key


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


@pytest.fixture
def cache(tmp_path: Path) -> TTSCache:
    """Create a TTSCache with isolated temp directories."""
    return TTSCache(
        db_path=tmp_path / ".tts_cache.db",
        cache_dir=tmp_path / ".tts_cache",
    )


class TestCacheKey:
    """Tests for cache key computation."""

    def test_same_input_same_key(self):
        assert _compute_cache_key("hello", "carter", "vibevoice") == _compute_cache_key("hello", "carter", "vibevoice")

    def test_different_voice_different_key(self):
        k1 = _compute_cache_key("hello", "carter", "vibevoice")
        k2 = _compute_cache_key("hello", "wayne", "vibevoice")
        assert k1 != k2

    def test_different_engine_different_key(self):
        k1 = _compute_cache_key("hello", "carter", "vibevoice")
        k2 = _compute_cache_key("hello", "carter", "moss")
        assert k1 != k2

    def test_case_insensitive_text(self):
        k1 = _compute_cache_key("Hello World", "carter", "vibevoice")
        k2 = _compute_cache_key("hello world", "carter", "vibevoice")
        assert k1 == k2

    def test_whitespace_stripped(self):
        k1 = _compute_cache_key("  hello  ", "carter", "vibevoice")
        k2 = _compute_cache_key("hello", "carter", "vibevoice")
        assert k1 == k2


class TestCacheMissAndPut:
    """Tests for cache miss and put operations."""

    def test_cache_miss_returns_none(self, cache: TTSCache):
        result = cache.get("nonexistent text")
        assert result is None

    def test_cache_put_and_get(self, cache: TTSCache):
        audio = _make_wav_bytes()
        cache.put("hello world", voice="carter", engine="vibevoice", audio_bytes=audio)

        result = cache.get("hello world", voice="carter", engine="vibevoice")
        assert result is not None
        assert result == audio

    def test_cache_key_varies_by_voice(self, cache: TTSCache):
        audio1 = _make_wav_bytes(duration_s=0.3)
        audio2 = _make_wav_bytes(duration_s=0.5)

        cache.put("hello", voice="carter", engine="vibevoice", audio_bytes=audio1)
        cache.put("hello", voice="wayne", engine="vibevoice", audio_bytes=audio2)

        r1 = cache.get("hello", voice="carter", engine="vibevoice")
        r2 = cache.get("hello", voice="wayne", engine="vibevoice")

        assert r1 == audio1
        assert r2 == audio2
        assert r1 != r2

    def test_cache_key_varies_by_engine(self, cache: TTSCache):
        audio1 = _make_wav_bytes(duration_s=0.3)
        audio2 = _make_wav_bytes(duration_s=0.5)

        cache.put("hello", voice="carter", engine="vibevoice", audio_bytes=audio1)
        cache.put("hello", voice="carter", engine="moss", audio_bytes=audio2)

        r1 = cache.get("hello", voice="carter", engine="vibevoice")
        r2 = cache.get("hello", voice="carter", engine="moss")

        assert r1 == audio1
        assert r2 == audio2


class TestCacheTTlExpiry:
    """Tests for TTL eviction."""

    def test_cache_ttl_expiry(self, cache: TTSCache, tmp_path: Path):
        audio = _make_wav_bytes()
        cache.put("expire me", voice="carter", engine="vibevoice", audio_bytes=audio)

        # Manually set created_at to 73 hours ago
        import sqlite3
        old_time = time.time() - 73 * 3600
        with sqlite3.connect(cache.db_path) as conn:
            conn.execute(
                "UPDATE tts_cache SET created_at = ? WHERE voice = ?",
                (old_time, "carter"),
            )

        result = cache.get("expire me", voice="carter", engine="vibevoice")
        assert result is None

        # Verify file was deleted
        key = _compute_cache_key("expire me", "carter", "vibevoice")
        file_path = cache.cache_dir / f"{key[:16]}.wav"
        assert not file_path.exists()


class TestCacheEviction:
    """Tests for max entries eviction."""

    def test_cache_max_entries_eviction(self, tmp_path: Path):
        cache = TTSCache(
            db_path=tmp_path / ".tts_cache.db",
            cache_dir=tmp_path / ".tts_cache",
            max_entries=2,
        )

        # Put 3 entries; the oldest should be evicted
        audio1 = _make_wav_bytes(duration_s=0.1)
        audio2 = _make_wav_bytes(duration_s=0.2)
        audio3 = _make_wav_bytes(duration_s=0.3)

        cache.put("first", voice="carter", engine="vibevoice", audio_bytes=audio1)
        cache.put("second", voice="carter", engine="vibevoice", audio_bytes=audio2)
        # Access "first" to update last_accessed so "second" becomes LRU
        cache.get("first")

        cache.put("third", voice="carter", engine="vibevoice", audio_bytes=audio3)

        # "first" should still exist (accessed recently)
        assert cache.get("first") is not None
        # "second" should have been evicted (oldest by last_accessed)
        assert cache.get("second") is None
        # "third" should exist
        assert cache.get("third") is not None


class TestCacheStats:
    """Tests for cache statistics."""

    def test_cache_stats(self, cache: TTSCache):
        audio = _make_wav_bytes()

        cache.put("entry1", voice="carter", engine="vibevoice", audio_bytes=audio)
        cache.put("entry2", voice="wayne", engine="vibevoice", audio_bytes=audio)

        stats = cache.stats()
        assert stats["entries"] == 2
        assert stats["total_bytes"] == len(audio) * 2
        assert stats["hit_count"] == 0
        assert stats["oldest_age_hours"] < 1.0


class TestClearVoice:
    """Tests for clearing voice entries."""

    def test_clear_voice(self, cache: TTSCache):
        audio = _make_wav_bytes()

        cache.put("hello", voice="carter", engine="vibevoice", audio_bytes=audio)
        cache.put("world", voice="wayne", engine="vibevoice", audio_bytes=audio)
        cache.put("test", voice="wayne", engine="moss", audio_bytes=audio)

        deleted = cache.clear_voice("wayne")
        assert deleted == 2

        # Carter entries remain
        assert cache.get("hello", voice="carter", engine="vibevoice") is not None
        # Wayne entries deleted
        assert cache.get("world", voice="wayne", engine="vibevoice") is None
        assert cache.get("test", voice="wayne", engine="moss") is None

    def test_clear_voice_with_engine_filter(self, cache: TTSCache):
        audio = _make_wav_bytes()

        cache.put("hello", voice="wayne", engine="vibevoice", audio_bytes=audio)
        cache.put("test", voice="wayne", engine="moss", audio_bytes=audio)

        deleted = cache.clear_voice("wayne", engine="moss")
        assert deleted == 1

        # vibevoice wayne entry remains
        assert cache.get("hello", voice="wayne", engine="vibevoice") is not None
        # moss wayne entry deleted
        assert cache.get("test", voice="wayne", engine="moss") is None


class TestInvalidate:
    """Tests for invalidating specific entries."""

    def test_invalidate_existing(self, cache: TTSCache):
        audio = _make_wav_bytes()
        cache.put("remove me", voice="carter", engine="vibevoice", audio_bytes=audio)

        result = cache.invalidate("remove me", voice="carter", engine="vibevoice")
        assert result is True
        assert cache.get("remove me", voice="carter", engine="vibevoice") is None

    def test_invalidate_nonexistent(self, cache: TTSCache):
        result = cache.invalidate("does not exist", voice="carter", engine="vibevoice")
        assert result is False


class TestIntegration:
    """Integration tests for cache with API endpoint pattern."""

    def test_cache_hit_increments_count(self, cache: TTSCache):
        audio = _make_wav_bytes()
        cache.put("hit test", voice="carter", engine="vibevoice", audio_bytes=audio)

        # Access twice
        cache.get("hit test", voice="carter", engine="vibevoice")
        cache.get("hit test", voice="carter", engine="vibevoice")

        stats = cache.stats()
        assert stats["hit_count"] == 2
