"""
TTS Cache — SQLite WAL index + disk storage

Caches TTS synthesis results keyed by (text, voice, engine) to avoid
redundant GPU synthesis. Uses SHA256 voice-aware keys, SQLite WAL mode
for concurrent read safety, and triple eviction (LRU + TTL + size).

Usage:
    cache = TTSCache()
    audio = cache.get("Hello world", voice="carter", engine="vibevoice")
    if audio is None:
        audio = await synthesize("Hello world")
        cache.put("Hello world", voice="carter", engine="vibevoice", audio_bytes=audio)
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
import unicodedata
from pathlib import Path

_logger = __import__("logging").getLogger(__name__)


def _compute_cache_key(text: str, voice: str, engine: str) -> str:
    """Compute SHA256 cache key from text, voice, and engine.

    Key formula: SHA256(NFKC(text.casefold().strip()) + '\\x00' + voice + '\\x00' + engine)
    """
    normalized = unicodedata.normalize("NFKC", text.casefold().strip())
    raw = f"{normalized}\x00{voice}\x00{engine}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TTSCache:
    """TTS audio cache with SQLite WAL index and disk storage.

    Attributes:
        db_path: Path to SQLite database file.
        cache_dir: Directory for cached WAV files.
        max_entries: Maximum number of cache entries.
        max_disk_bytes: Maximum total disk usage in bytes.
        ttl_seconds: Time-to-live for cache entries in seconds.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        cache_dir: Path | None = None,
        max_entries: int = 200,
        max_disk_bytes: int = 100 * 1024 * 1024,
        ttl_seconds: float = 72 * 3600,
    ):
        self.db_path = db_path or Path(__file__).parent / ".tts_cache.db"
        self.cache_dir = cache_dir or Path(__file__).parent / ".tts_cache"
        self.max_entries = max_entries
        self.max_disk_bytes = max_disk_bytes
        self.ttl_seconds = ttl_seconds

        # Create cache directory
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    def _init_db(self) -> None:
        """Create cache table and indexes if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tts_cache (
                    cache_key TEXT PRIMARY KEY,
                    text_hash TEXT NOT NULL,
                    voice TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    hit_count INTEGER DEFAULT 0
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_last_accessed ON tts_cache(last_accessed)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_voice_engine ON tts_cache(voice, engine)"
            )

    def _disk_path(self, cache_key: str) -> Path:
        """Get disk file path for a cache key."""
        return self.cache_dir / f"{cache_key[:16]}.wav"

    def get(
        self, text: str, voice: str = "carter", engine: str = "vibevoice"
    ) -> bytes | None:
        """Look up cached audio for (text, voice, engine).

        Returns audio bytes on hit, None on miss or expired entry.
        Deletes expired entries and their files.
        """
        key = _compute_cache_key(text, voice, engine)
        now = time.time()

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            row = conn.execute(
                "SELECT file_path, created_at FROM tts_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()

            if row is None:
                return None

            file_path_str, created_at = row

            # Check TTL expiry
            if now - created_at > self.ttl_seconds:
                # Expired — delete entry and file
                conn.execute(
                    "DELETE FROM tts_cache WHERE cache_key = ?", (key,)
                )
                file_path = Path(file_path_str)
                if file_path.exists():
                    file_path.unlink()
                return None

            # Read from disk
            file_path = Path(file_path_str)
            if not file_path.exists():
                # File missing — clean up DB entry
                conn.execute(
                    "DELETE FROM tts_cache WHERE cache_key = ?", (key,)
                )
                return None

            audio_bytes = file_path.read_bytes()

            # Update access stats
            conn.execute(
                "UPDATE tts_cache SET last_accessed = ?, hit_count = hit_count + 1 WHERE cache_key = ?",
                (now, key),
            )

            return audio_bytes

    def put(
        self,
        text: str,
        voice: str,
        engine: str,
        audio_bytes: bytes,
    ) -> None:
        """Store audio bytes in cache for (text, voice, engine).

        Writes file to disk, inserts/updates row in SQLite,
        then triggers eviction if needed.
        """
        key = _compute_cache_key(text, voice, engine)
        now = time.time()
        file_path = self._disk_path(key)

        # Write to disk
        file_path.write_bytes(audio_bytes)
        file_size = len(audio_bytes)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            # Upsert: insert or replace
            conn.execute(
                """
                INSERT OR REPLACE INTO tts_cache
                    (cache_key, text_hash, voice, engine, file_path, file_size, created_at, last_accessed, hit_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (key, key[:16], voice, engine, str(file_path), file_size, now, now),
            )

        # Evict if needed
        self._evict_if_needed()

    def invalidate(
        self, text: str, voice: str, engine: str
    ) -> bool:
        """Delete a specific cache entry and its file.

        Returns True if an entry was deleted, False otherwise.
        """
        key = _compute_cache_key(text, voice, engine)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            row = conn.execute(
                "SELECT file_path FROM tts_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()

            if row is None:
                return False

            file_path = Path(row[0])
            conn.execute(
                "DELETE FROM tts_cache WHERE cache_key = ?", (key,)
            )

        if file_path.exists():
            file_path.unlink()

        return True

    def clear_voice(
        self, voice: str, engine: str | None = None
    ) -> int:
        """Delete all cache entries for a voice (optionally filtered by engine).

        Returns count of deleted entries.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")

            if engine is not None:
                rows = conn.execute(
                    "SELECT file_path FROM tts_cache WHERE voice = ? AND engine = ?",
                    (voice, engine),
                ).fetchall()
                conn.execute(
                    "DELETE FROM tts_cache WHERE voice = ? AND engine = ?",
                    (voice, engine),
                )
            else:
                rows = conn.execute(
                    "SELECT file_path FROM tts_cache WHERE voice = ?",
                    (voice,),
                ).fetchall()
                conn.execute(
                    "DELETE FROM tts_cache WHERE voice = ?", (voice,)
                )

        # Delete files
        for (file_path_str,) in rows:
            file_path = Path(file_path_str)
            if file_path.exists():
                file_path.unlink()

        return len(rows)

    def stats(self) -> dict:
        """Return cache statistics.

        Returns dict with: entries, total_bytes, hit_count, oldest_age_hours.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            row = conn.execute(
                """
                SELECT
                    COUNT(*) as entries,
                    COALESCE(SUM(file_size), 0) as total_bytes,
                    COALESCE(SUM(hit_count), 0) as hit_count,
                    COALESCE(MIN(created_at), 0) as oldest_created
                FROM tts_cache
                """
            ).fetchone()

        entries, total_bytes, hit_count, oldest_created = row
        now = time.time()
        oldest_age_hours = (now - oldest_created) / 3600 if oldest_created > 0 else 0.0

        return {
            "entries": entries,
            "total_bytes": total_bytes,
            "hit_count": hit_count,
            "oldest_age_hours": round(oldest_age_hours, 2),
        }

    def _evict_if_needed(self) -> None:
        """Check and enforce eviction constraints.

        Order: (1) TTL expiry, (2) max entries (LRU), (3) max disk size (LRU).
        """
        now = time.time()
        cutoff = now - self.ttl_seconds

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")

            # 1. TTL eviction
            expired = conn.execute(
                "SELECT file_path FROM tts_cache WHERE created_at < ?",
                (cutoff,),
            ).fetchall()
            if expired:
                conn.execute(
                    "DELETE FROM tts_cache WHERE created_at < ?", (cutoff,)
                )

            # 2. Max entries eviction (LRU)
            count = conn.execute("SELECT COUNT(*) FROM tts_cache").fetchone()[0]
            if count > self.max_entries:
                excess = count - self.max_entries
                evicted = conn.execute(
                    "SELECT file_path FROM tts_cache ORDER BY last_accessed ASC LIMIT ?",
                    (excess,),
                ).fetchall()
                conn.execute(
                    """
                    DELETE FROM tts_cache WHERE cache_key IN (
                        SELECT cache_key FROM tts_cache ORDER BY last_accessed ASC LIMIT ?
                    )
                    """,
                    (excess,),
                )
                expired.extend(evicted)

            # 3. Max disk size eviction (LRU)
            total = conn.execute(
                "SELECT COALESCE(SUM(file_size), 0) FROM tts_cache"
            ).fetchone()[0]
            if total > self.max_disk_bytes:
                needed = total - self.max_disk_bytes
                # Delete oldest until under limit
                oversized = conn.execute(
                    "SELECT cache_key, file_path, file_size FROM tts_cache ORDER BY last_accessed ASC"
                ).fetchall()
                freed = 0
                keys_to_delete = []
                for ck, fp, fs in oversized:
                    if freed >= needed:
                        break
                    freed += fs
                    keys_to_delete.append(ck)
                    expired.append((fp,))

                if keys_to_delete:
                    placeholders = ",".join("?" for _ in keys_to_delete)
                    conn.execute(
                        f"DELETE FROM tts_cache WHERE cache_key IN ({placeholders})",
                        keys_to_delete,
                    )

        # Delete files outside of transaction
        for (file_path_str,) in expired:
            file_path = Path(file_path_str)
            if file_path.exists():
                try:
                    file_path.unlink()
                except OSError:
                    pass
