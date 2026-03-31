"""Tests for workspace backlog manager."""

import threading

import pytest

from agentos.kernel.event_log import SQLiteEventLog
from agentos.kernel.seq import SeqCounter
from agentos.schemas.events import EventType
from agentos.workspace.backlog import BacklogManager
from agentos.workspace.schemas import BacklogTask, BacklogTaskStatus


@pytest.fixture
def bl(tmp_path):
    el = SQLiteEventLog(str(tmp_path / "test.db"))
    seq = SeqCounter()
    return BacklogManager(el, seq, "wf-test")


def _task(title="Test", **kw):
    return BacklogTask(title=title, **kw)


class TestCreateAndClaim:
    def test_create_task(self, bl):
        tid = bl.create_task(_task("Research"))
        assert tid
        task = bl.get_task(tid)
        assert task.title == "Research"
        assert task.status == BacklogTaskStatus.OPEN

    def test_claim_task(self, bl):
        tid = bl.create_task(_task())
        bl.claim_task(tid, "agent-a")
        task = bl.get_task(tid)
        assert task.status == BacklogTaskStatus.CLAIMED
        assert task.assigned_to == "agent-a"
        assert task.claimed_at is not None

    def test_claim_already_claimed_fails(self, bl):
        tid = bl.create_task(_task())
        bl.claim_task(tid, "a")
        with pytest.raises(ValueError, match="Cannot claim"):
            bl.claim_task(tid, "b")

    def test_claim_blocked_fails(self, bl):
        t1 = bl.create_task(_task("dep"))
        t2 = bl.create_task(_task("blocked", depends_on=[t1]))
        assert bl.get_task(t2).status == BacklogTaskStatus.BLOCKED
        with pytest.raises(ValueError, match="Cannot claim"):
            bl.claim_task(t2, "a")


class TestLifecycle:
    def test_full_lifecycle(self, bl):
        tid = bl.create_task(_task())
        bl.claim_task(tid, "a")
        bl.start_task(tid)
        assert bl.get_task(tid).status == BacklogTaskStatus.IN_PROGRESS

        bl.submit_for_review(tid, {"summary": "done"})
        assert bl.get_task(tid).status == BacklogTaskStatus.IN_REVIEW
        assert bl.get_task(tid).review_count == 1

        bl.approve_task(tid, "reviewer")
        assert bl.get_task(tid).status == BacklogTaskStatus.DONE
        assert bl.get_task(tid).completed_at is not None

    def test_revision_flow(self, bl):
        tid = bl.create_task(_task())
        bl.claim_task(tid, "a")
        bl.start_task(tid)
        bl.submit_for_review(tid, {"summary": "draft"})
        bl.request_revision(tid, "needs more data")
        assert bl.get_task(tid).status == BacklogTaskStatus.REVISION_NEEDED

        bl.start_task(tid)  # Can restart after revision
        bl.submit_for_review(tid, {"summary": "v2"})
        assert bl.get_task(tid).review_count == 2

    def test_direct_complete(self, bl):
        tid = bl.create_task(_task())
        bl.claim_task(tid, "a")
        bl.start_task(tid)
        bl.complete_task(tid, {"summary": "done"})
        assert bl.get_task(tid).status == BacklogTaskStatus.DONE

    def test_cancel(self, bl):
        tid = bl.create_task(_task())
        bl.cancel_task(tid, "no longer needed")
        assert bl.get_task(tid).status == BacklogTaskStatus.CANCELLED


class TestDependencies:
    def test_auto_blocks(self, bl):
        t1 = bl.create_task(_task("first"))
        t2 = bl.create_task(_task("second", depends_on=[t1]))
        assert bl.get_task(t2).status == BacklogTaskStatus.BLOCKED

    def test_unblock_on_complete(self, bl):
        t1 = bl.create_task(_task("first"))
        t2 = bl.create_task(_task("second", depends_on=[t1]))
        bl.claim_task(t1, "a")
        bl.start_task(t1)
        bl.complete_task(t1)
        assert bl.get_task(t2).status == BacklogTaskStatus.OPEN

    def test_multi_dependency(self, bl):
        t1 = bl.create_task(_task("dep1"))
        t2 = bl.create_task(_task("dep2"))
        t3 = bl.create_task(_task("needs both", depends_on=[t1, t2]))
        assert bl.get_task(t3).status == BacklogTaskStatus.BLOCKED

        bl.claim_task(t1, "a"); bl.start_task(t1); bl.complete_task(t1)
        assert bl.get_task(t3).status == BacklogTaskStatus.BLOCKED  # still blocked

        bl.claim_task(t2, "b"); bl.start_task(t2); bl.complete_task(t2)
        assert bl.get_task(t3).status == BacklogTaskStatus.OPEN  # now unblocked

    def test_check_dependencies(self, bl):
        t1 = bl.create_task(_task("dep"))
        t2 = bl.create_task(_task("blocked", depends_on=[t1]))
        assert bl.check_dependencies(t2) is False
        bl.claim_task(t1, "a"); bl.start_task(t1); bl.complete_task(t1)
        assert bl.check_dependencies(t2) is True


class TestChaining:
    def test_chain_next(self, bl):
        t1 = bl.create_task(_task("first", next_task={
            "title": "Follow-up",
            "description": "Continue work",
            "suggested_for": "agent-b",
        }))
        bl.claim_task(t1, "a"); bl.start_task(t1); bl.complete_task(t1)
        # chain_next was called by complete_task → approve_task internally
        all_tasks = bl.get_all_tasks()
        assert len(all_tasks) == 2
        follow_up = [t for t in all_tasks if t.title == "Follow-up"][0]
        assert follow_up.suggested_for == "agent-b"
        assert t1 in follow_up.depends_on


class TestPriority:
    def test_recompute(self, bl):
        t1 = bl.create_task(_task("blocks many", priority="normal"))
        t2 = bl.create_task(_task("downstream 1", depends_on=[t1]))
        t3 = bl.create_task(_task("downstream 2", depends_on=[t1]))
        bl.recompute_priorities()
        assert bl.get_task(t1).computed_priority > bl.get_task(t2).computed_priority

    def test_open_tasks_sorted_by_priority(self, bl):
        bl.create_task(_task("low", priority="low"))
        bl.create_task(_task("high", priority="high"))
        bl.recompute_priorities()
        tasks = bl.get_open_tasks()
        assert tasks[0].title == "high"


class TestHealth:
    def test_flag_long_tasks(self, bl):
        bl.create_task(_task("short", estimated_minutes=10))
        bl.create_task(_task("long", estimated_minutes=60))
        flagged = bl.flag_long_tasks()
        assert len(flagged) == 1

    def test_stall_tracking(self, bl):
        tid = bl.create_task(_task())
        bl.claim_task(tid, "a"); bl.start_task(tid)
        bl.increment_stall(tid)
        bl.increment_stall(tid)
        stalled = bl.flag_stalled_tasks(max_stall_cycles=2)
        assert tid in stalled
        bl.reset_stall(tid)
        assert bl.flag_stalled_tasks() == []


class TestQueries:
    def test_get_all(self, bl):
        bl.create_task(_task("a"))
        bl.create_task(_task("b"))
        assert len(bl.get_all_tasks()) == 2

    def test_get_tasks_for(self, bl):
        tid = bl.create_task(_task())
        bl.claim_task(tid, "agent-x")
        assert len(bl.get_tasks_for("agent-x")) == 1
        assert len(bl.get_tasks_for("agent-y")) == 0

    def test_get_blocked(self, bl):
        t1 = bl.create_task(_task("dep"))
        bl.create_task(_task("blocked", depends_on=[t1]))
        assert len(bl.get_blocked_tasks()) == 1


class TestEvents:
    def test_events_logged(self, bl):
        tid = bl.create_task(_task())
        bl.claim_task(tid, "a")
        bl.start_task(tid)
        bl.complete_task(tid)

        events = bl._event_log.query(workflow_id="wf-test")
        types = [e.event_type for e in events]
        assert EventType.BACKLOG_TASK_CREATED in types
        assert EventType.BACKLOG_TASK_CLAIMED in types
        assert EventType.BACKLOG_TASK_STARTED in types
        assert EventType.BACKLOG_TASK_APPROVED in types


class TestConcurrency:
    def test_concurrent_claims(self, bl):
        tids = [bl.create_task(_task(f"t-{i}")) for i in range(10)]
        errors = []

        def claim_batch(agent, ids):
            for tid in ids:
                try:
                    bl.claim_task(tid, agent)
                except ValueError:
                    pass
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=claim_batch, args=("a", tids)),
            threading.Thread(target=claim_batch, args=("b", tids)),
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors
        # Each task should be claimed by exactly one agent
        for tid in tids:
            assert bl.get_task(tid).assigned_to in ("a", "b")
