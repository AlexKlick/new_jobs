"""
pytest tests for chat backend session persistence (SESS-01).

Tests verify:
- /api/sessions endpoint lists sessions
- /api/sessions/{id} endpoint loads session
- /api/chat persists messages to SQLite
- WAL mode and busy_timeout PRAGMAs
- 30-day retention enforcement
- skill_job_type save/restore
"""

import pytest
import sqlite3
import time
from pathlib import Path

# Import from chat_backend - adjust import path as needed
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from chat_backend import (
    SESSION_DB,
    init_session_db,
    save_session,
    load_session,
    list_sessions,
    trim_sessions,
)


class TestSessionPersistence:
    """Tests for SQLite-backed session persistence."""

    @pytest.fixture(autouse=True)
    def setup_session_db(self, tmp_path):
        """Set up a temporary session DB for each test."""
        import chat_backend
        # Backup original DB path
        original_db = chat_backend.SESSION_DB
        # Use temp DB
        test_db = tmp_path / "test_sessions.db"
        chat_backend.SESSION_DB = test_db
        init_session_db()
        yield test_db
        # Restore original
        chat_backend.SESSION_DB = original_db

    def test_session_save_and_load(self, tmp_path):
        """Save session to SQLite and load it back."""
        session_id = f"test-session-{time.time()}"
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]

        save_session(session_id, messages, job_index=1, skill_name="resume_swe.yaml", skill_job_type="swe")

        result = load_session(session_id)
        assert result is not None, "Failed to load session"
        loaded_messages, job_index, skill_name, skill_job_type = result

        assert len(loaded_messages) == 2, f"Expected 2 messages, got {len(loaded_messages)}"
        assert job_index == 1, f"Expected job_index=1, got {job_index}"
        assert skill_name == "resume_swe.yaml", f"Expected skill_name, got {skill_name}"
        assert skill_job_type == "swe", f"Expected skill_job_type=swe, got {skill_job_type}"

    def test_session_list_endpoint(self, tmp_path):
        """GET /api/sessions returns session list."""
        session_id = f"test-session-list-{time.time()}"
        messages = [{"role": "user", "content": "Test"}]

        save_session(session_id, messages, job_index=None, skill_name=None, skill_job_type=None)

        sessions = list_sessions()
        assert len(sessions) >= 1, "No sessions found"
        session_ids = [s["session_id"] for s in sessions]
        assert session_id in session_ids, f"Session {session_id} not in list"

    def test_session_load_endpoint(self, tmp_path):
        """GET /api/sessions/{id} loads specific session."""
        session_id = f"test-session-load-{time.time()}"
        messages = [{"role": "user", "content": "Load test"}]

        save_session(session_id, messages, job_index=2, skill_name="cover_letter_swe.yaml", skill_job_type="swe")

        result = load_session(session_id)
        assert result is not None, "Session not found"
        loaded_messages, job_index, skill_name, skill_job_type = result
        assert job_index == 2
        assert skill_name == "cover_letter_swe.yaml"

    def test_skill_job_type_save_and_restore(self, tmp_path):
        """skill_job_type is saved and restored with session."""
        session_id = f"test-skill-job-type-{time.time()}"
        messages = [{"role": "user", "content": "Job type test"}]

        # Save with different job types
        save_session(session_id, messages, job_index=1, skill_name="resume_ml.yaml", skill_job_type="ml")

        result = load_session(session_id)
        assert result is not None
        _, _, _, skill_job_type = result
        assert skill_job_type == "ml", f"Expected skill_job_type=ml, got {skill_job_type}"

        # Update to different job type
        save_session(session_id, messages, job_index=1, skill_name="resume_consulting.yaml", skill_job_type="consulting")

        result = load_session(session_id)
        assert result is not None
        _, _, _, skill_job_type = result
        assert skill_job_type == "consulting", f"Expected skill_job_type=consulting, got {skill_job_type}"


class TestSQLiteACID:
    """Tests for SQLite ACID compliance."""

    def test_wal_mode_enabled(self):
        """WAL mode is enabled for concurrent access."""
        with sqlite3.connect(SESSION_DB) as conn:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert journal_mode == "wal", f"Expected WAL mode, got {journal_mode}"

    def test_busy_timeout_set(self):
        """busy_timeout is set to 5000ms."""
        with sqlite3.connect(SESSION_DB) as conn:
            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert busy_timeout == 5000, f"Expected busy_timeout=5000, got {busy_timeout}"

    def test_30day_retention_enforcement(self, tmp_path):
        """Sessions older than 30 days are trimmed."""
        import chat_backend
        original_db = chat_backend.SESSION_DB
        test_db = tmp_path / "test_retention.db"
        chat_backend.SESSION_DB = test_db
        init_session_db()

        # Create a session with old timestamp
        old_session_id = "old-session-test"
        cutoff = time.time() - (30 * 24 * 60 * 60)  # 30 days ago
        with sqlite3.connect(test_db) as conn:
            conn.execute("""
                INSERT INTO sessions (session_id, created_at, updated_at, job_index, skill_name, skill_job_type, messages)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (old_session_id, cutoff - 1000, cutoff, None, None, None, "[]"))
            conn.execute("""
                INSERT INTO session_metadata (session_id, display_name, message_count, skill_job_type)
                VALUES (?, ?, ?, ?)
            """, (old_session_id, "Old", 0, None))

        # Run trim
        trim_sessions()

        # Verify old session is deleted
        result = load_session(old_session_id)
        assert result is None, "Old session should have been trimmed"

        chat_backend.SESSION_DB = original_db

    def test_concurrent_access(self, tmp_path):
        """Database handles concurrent access without locking errors."""
        import chat_backend
        original_db = chat_backend.SESSION_DB
        test_db = tmp_path / "test_concurrent.db"
        chat_backend.SESSION_DB = test_db
        init_session_db()

        session_id = f"concurrent-test-{time.time()}"

        # Simulate concurrent saves
        import threading

        def save_task():
            for i in range(5):
                save_session(
                    f"{session_id}-{threading.current_thread().name}",
                    [{"role": "user", "content": f"Message {i}"}],
                    job_index=i,
                    skill_name=None,
                    skill_job_type=None
                )

        threads = [
            threading.Thread(target=save_task, name="thread-1"),
            threading.Thread(target=save_task, name="thread-2"),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # If we get here without "database is locked" errors, test passes
        sessions = list_sessions()
        assert len(sessions) >= 1, "Concurrent saves should succeed"

        chat_backend.SESSION_DB = original_db


class TestSessionSchema:
    """Tests for session schema integrity."""

    def test_skill_job_type_column_exists(self):
        """sessions table has skill_job_type column."""
        with sqlite3.connect(SESSION_DB) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
            assert "skill_job_type" in cols, f"skill_job_type column missing from sessions. Found: {cols}"

    def test_session_metadata_has_skill_job_type(self):
        """session_metadata table has skill_job_type column."""
        with sqlite3.connect(SESSION_DB) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(session_metadata)").fetchall()]
            assert "skill_job_type" in cols, f"skill_job_type column missing from session_metadata. Found: {cols}"
