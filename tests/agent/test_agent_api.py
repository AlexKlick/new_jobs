"""Tests for the /api/agent backend contract."""

from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


def test_agent_endpoint_returns_runner_result(monkeypatch, tmp_path):
    """POST /api/agent returns the structured AgentRunner result."""
    import chat.chat_backend as backend
    from agent.agent_runner import AgentResult

    monkeypatch.setattr(backend, "SESSION_DB", tmp_path / "sessions.db")

    fake_runner = MagicMock()

    async def fake_run_async(*, instruction, job_index=None, session_id=None):
        assert instruction == "Update resume.md"
        assert job_index == 1
        assert session_id == "session-123"
        return AgentResult(
            success=True,
            response="Updated resume.md",
            checkpoint_id="run-abc",
            iterations_used=1,
        )

    fake_runner.run_async = fake_run_async
    monkeypatch.setattr(backend, "get_agent_runner", lambda: fake_runner)

    client = TestClient(backend.app)
    resp = client.post(
        "/api/agent",
        json={"instruction": "Update resume.md", "job_index": 1, "session_id": "session-123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["checkpoint_id"] == "run-abc"
    assert body["iterations_used"] == 1


def test_agent_rollback_endpoint_delegates_to_runner(monkeypatch, tmp_path):
    """POST /api/agent/rollback restores via the runner rollback store."""
    import chat_backend as backend

    monkeypatch.setattr(backend, "SESSION_DB", tmp_path / "sessions.db")

    fake_runner = MagicMock()
    fake_runner.rollback.return_value = "restored content"
    monkeypatch.setattr(backend, "get_agent_runner", lambda: fake_runner)

    client = TestClient(backend.app)
    resp = client.post("/api/agent/rollback", json={"checkpoint_id": "run-abc"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["restored_content"] == "restored content"
