"""Durable worker tests using a simulated provider protocol; no real AI or desktop calls."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from desktop_service import db as models
from desktop_service import worker
from desktop_service.security import seal

SECRET = "test-provider-secret-never-in-user-events"
LEASE = "worker-lease"


@pytest.fixture
def run_state(db, monkeypatch):
    monkeypatch.setattr(worker, "Session", models.Session)
    monkeypatch.setattr(worker.runtime, "keep_alive", AsyncMock())
    monkeypatch.setattr(worker.runtime, "tool", AsyncMock(return_value="verified result"))
    db.add(
        models.Computer(
            id="agent-computer",
            workspace_id="w",
            request_id="computer-request",
            name="Worker test",
            status="running",
            sandbox_id="sandbox-test",
            controller="agent",
            metered_at=models.now(),
            last_active=models.now(),
        )
    )
    db.flush()
    run = models.Run(
        id="agent-run",
        computer_id="agent-computer",
        request_id="run-request",
        prompt="Inspect files",
        status="running",
        lease=LEASE,
        heartbeat=models.now(),
        started_at=models.now(),
    )
    db.add(run)
    db.add(models.Credential(workspace_id="w", encrypted_key=seal(SECRET), suffix="ents"))
    db.commit()
    return run.id


def use(name, tid="tool-1", **inputs):
    return {"type": "tool_use", "id": tid, "name": name, "input": inputs}


def provider(monkeypatch, *turns, on_create=None):
    captured = []
    responses = iter(turns)

    async def create(**kwargs):
        captured.append(deepcopy(kwargs))
        if on_create:
            on_create()
        return SimpleNamespace(
            content=[SimpleNamespace(model_dump=lambda block=block, **_: deepcopy(block)) for block in next(responses)]
        )

    messages = SimpleNamespace(create=AsyncMock(side_effect=create))
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages), close=AsyncMock())

    def construct(**kwargs):
        assert kwargs["api_key"] == SECRET
        return client

    monkeypatch.setattr(worker.anthropic, "AsyncAnthropic", construct)
    return captured, client


def assert_no_secret_events(db):
    assert all(SECRET not in row.text for row in db.scalars(select(models.Event)))


async def test_tool_turn_is_durable_before_execution_and_result_survives(db, monkeypatch, run_state):
    calls, client = provider(monkeypatch, [use("bash", command="pwd")], [{"type": "text", "text": "Verified files."}])

    async def execute(sid, name, inputs):
        with models.Session() as inspection:
            saved = inspection.get(models.Run, run_state)
            assert saved.pending_tools == [use("bash", command="pwd")]
            assert saved.messages[-1]["role"] == "assistant"
        assert (sid, name, inputs) == ("sandbox-test", "bash", {"command": "pwd"})
        return "/home/desktop"

    worker.runtime.tool.side_effect = execute
    await worker.agent(run_state, LEASE)
    db.expire_all()
    saved = db.get(models.Run, run_state)
    assert saved.status == "completed" and saved.lease is None and saved.steps == 2
    assert saved.pending_tools == []
    assert calls[1]["messages"][-1]["content"][0]["content"] == "/home/desktop"
    assert client.close.await_count == 2
    assert_no_secret_events(db)


@pytest.mark.parametrize("decision", ["approve", "decline"])
async def test_approval_pauses_all_actions_and_resume_never_replays_old_tools(db, monkeypatch, run_state, decision):
    actions = [use("bash", command="send-message"), use("request_approval", "approve-1", action="Send message to Alex")]
    provider(monkeypatch, actions)
    await worker.agent(run_state, LEASE)
    db.expire_all()
    saved = db.get(models.Run, run_state)
    assert saved.status == "awaiting_approval" and saved.lease is None
    assert saved.approval == {"action": "Send message to Alex", "decision": None}
    worker.runtime.tool.assert_not_awaited()
    saved.approval = {"action": "Send message to Alex", "decision": decision}
    saved.status = "running"
    saved.lease = "resumed"
    db.commit()
    calls, _ = provider(monkeypatch, [{"type": "text", "text": "Rechecking current state."}])
    await worker.agent(run_state, "resumed")
    worker.runtime.tool.assert_not_awaited()
    results = calls[0]["messages"][-1]["content"]
    assert "not executed" in results[0]["content"]
    assert ("User approved" in results[1]["content"]) == (decision == "approve")
    assert_no_secret_events(db)


@pytest.mark.parametrize("control", ["cancel", "takeover"])
async def test_control_change_between_tools_prevents_remaining_actions(db, monkeypatch, run_state, control):
    provider(monkeypatch, [use("bash", "first", command="pwd"), use("bash", "second", command="touch later")])

    async def execute(*_):
        with models.Session() as session:
            run = session.get(models.Run, run_state)
            computer = session.get(models.Computer, run.computer_id)
            run.status = "canceled" if control == "cancel" else "paused"
            if control == "takeover":
                computer.controller = "pending:local-user"
            session.commit()
        return "first action finished"

    worker.runtime.tool.side_effect = execute
    await worker.agent(run_state, LEASE)
    db.expire_all()
    saved = db.get(models.Run, run_state)
    assert saved.lease is None and saved.pending_tools == []
    worker.runtime.tool.assert_awaited_once()
    results = saved.messages[-1]["content"]
    assert [result["tool_use_id"] for result in results] == ["first", "second"]
    assert results[0]["content"] == "first action finished"
    assert "Not executed" in results[1]["content"]
    if control == "takeover":
        assert db.get(models.Computer, saved.computer_id).controller == "local-user"
    assert_no_secret_events(db)


async def test_takeover_while_provider_is_thinking_prevents_any_action(db, monkeypatch, run_state):
    def takeover():
        with models.Session() as session:
            session.get(models.Run, run_state).status = "paused"
            session.get(models.Computer, "agent-computer").controller = "pending:local-user"
            session.commit()

    provider(monkeypatch, [use("bash", command="touch later")], on_create=takeover)
    await worker.agent(run_state, LEASE)
    worker.runtime.tool.assert_not_awaited()
    db.expire_all()
    assert db.get(models.Computer, "agent-computer").controller == "local-user"
    assert db.get(models.Run, run_state).lease is None


async def test_stale_heartbeat_interrupts_uncertain_action_without_replay(db, monkeypatch, run_state):
    saved = db.get(models.Run, run_state)
    saved.heartbeat = models.now() - timedelta(minutes=3)
    saved.pending_tools = [use("bash", command="uncertain-command")]
    db.get(models.Computer, "agent-computer").controller = "pending:local-user"
    db.commit()
    await worker.reconcile()
    db.expire_all()
    assert db.get(models.Run, run_state).status == "interrupted"
    assert db.get(models.Run, run_state).lease is None
    assert db.get(models.Computer, "agent-computer").controller == "local-user"
    worker.runtime.tool.assert_not_awaited()
    assert any("avoid repeating" in e.text for e in db.scalars(select(models.Event)))
    assert_no_secret_events(db)


async def test_provider_failure_does_not_expose_key_in_user_events(db, monkeypatch, run_state):
    _, client = provider(monkeypatch)
    client.beta.messages.create.side_effect = RuntimeError(SECRET)
    await worker.agent(run_state, LEASE)
    db.expire_all()
    assert db.get(models.Run, run_state).status == "interrupted"
    assert_no_secret_events(db)
    worker.runtime.tool.assert_not_awaited()


async def test_superseded_worker_cannot_clear_replacement_lease(db, monkeypatch, run_state):
    def replace_lease():
        with models.Session() as session:
            session.get(models.Run, run_state).lease = "replacement-worker-lease"
            session.commit()

    provider(monkeypatch, [use("bash", command="touch later")], on_create=replace_lease)
    await worker.agent(run_state, LEASE)
    worker.runtime.tool.assert_not_awaited()
    db.expire_all()
    assert db.get(models.Run, run_state).lease == "replacement-worker-lease"


async def test_superseded_inflight_tool_cannot_overwrite_new_worker_state(db, monkeypatch, run_state):
    provider(monkeypatch, [use("bash", command="pwd")])
    replacement_messages = [{"role": "user", "content": "Replacement worker owns this state"}]
    replacement_tools = [use("bash", "replacement-tool", command="ls")]

    async def replace_during_action(*_):
        with models.Session() as session:
            saved = session.get(models.Run, run_state)
            saved.lease = "replacement-worker-lease"
            saved.messages = replacement_messages
            saved.pending_tools = replacement_tools
            session.commit()
        return "old action result"

    worker.runtime.tool.side_effect = replace_during_action
    await worker.agent(run_state, LEASE)
    db.expire_all()
    saved = db.get(models.Run, run_state)
    assert saved.lease == "replacement-worker-lease"
    assert saved.messages == replacement_messages
    assert saved.pending_tools == replacement_tools
