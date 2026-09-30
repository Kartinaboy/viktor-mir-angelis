import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from core.actions import create_task, edit_task, reconcile_cost
from core.engine import Busy, budget_totals, eligible_tasks, execute_run, pause_all, recover_expired, role_plan, start_run
from core.llm import MockLLM
from core.models import parse_backlog, safe_path, validate_state, write_backlog
from core.scheduler import due_jobs
from core.storage import LocalStore, MemoryStore, projections, seed


def test_backlog_roundtrip_with_bom_quotes_and_multiline():
    tasks = seed()["backlog"]
    tasks[0]["task"] = 'Текст, "цитата"\nдругая строка'
    assert parse_backlog("\ufeff" + write_backlog(tasks)) == tasks


def test_state_rejects_media_or_missing_identity():
    state = seed()["state"]
    validate_state(state)
    state["constraints"]["image_generation"] = True
    with pytest.raises(ValueError):
        validate_state(state)
    with pytest.raises(ValueError):
        validate_state({})


@pytest.mark.parametrize("path", ["../secrets.toml", "data/../../key.json", "/data/file.md", "data\\file.md", "data/file.py", "data/a;cmd.md", "data/sub/../a.md"])
def test_path_sanitization(path):
    with pytest.raises(ValueError):
        safe_path(path)
    assert safe_path("data/strategy/test.md") == "data/strategy/test.md"


def test_mocked_complete_cycle_has_artifacts_audit_cost_and_review():
    store = MemoryStore()
    original_identity = copy.deepcopy(store.load()["state"]["identity"])
    run_id = start_run(store, mock=True)
    execute_run(store, run_id, MockLLM())
    data = store.load()
    run = data["runs"][run_id]
    assert run["status"] == "completed"
    assert data["backlog"][0]["status"] == "review"
    assert len(run["artifacts"]) >= 1
    assert any(a["path"].endswith(".md") for a in data["artifacts"].values())
    assert all(c["status"] == "settled" and c["usage"]["output_tokens"] > 0 for c in run["calls"])
    assert data["state"]["identity"] == original_identity
    assert {e["event"] for e in data["journal"]} >= {"run_started", "state_loaded", "task_selected", "role_started", "role_completed", "artifact_written", "backlog_updated", "run_completed"}
    assert all(path.startswith("data/") for path in projections(data))
    assert budget_totals(data)["daily"] == 0  # Explicit mock is never billed as a real call.


def test_dry_run_has_zero_calls_and_unchanged_state_backlog():
    store = MemoryStore()
    before = store.load()
    run_id = start_run(store, mode="dry")
    execute_run(store, run_id)
    after = store.load()
    assert after["runs"][run_id]["status"] == "completed"
    assert after["runs"][run_id]["calls"] == []
    assert after["state"] == before["state"]
    assert after["backlog"] == before["backlog"]
    assert not after["artifacts"]


def test_model_routing_astra_only_once_for_deep_strategy():
    data = seed()
    normal = role_plan(data["backlog"][0], data["settings"], "normal")
    assert all(p["tier"] != "strategic" for p in normal)
    deep = role_plan(data["backlog"][0], data["settings"], "deep")
    assert len([p for p in deep if p["tier"] == "strategic"]) == 1
    assert next(p for p in deep if p["tier"] == "strategic")["astra_reason"]
    archive = next(t for t in data["backlog"] if t["domain"] == "archive")
    assert all(p["tier"] == "cheap" for p in role_plan(archive, data["settings"], "deep"))


def test_budget_blocks_before_api_and_keeps_task_ready():
    store = MemoryStore()
    store.transact(lambda d: d["settings"].update({"run_budget": 0.000001}))
    class MustNotCall:
        def complete(self, **kwargs):
            pytest.fail("API must not run beyond budget")
    run_id = start_run(store)
    execute_run(store, run_id, MustNotCall())
    data = store.load()
    assert data["runs"][run_id]["status"] == "failed"
    assert not data["runs"][run_id]["calls"]
    assert data["backlog"][0]["status"] == "ready"
    assert any(e["event"] == "budget_warning" for e in data["journal"])


def test_provider_failure_preserves_state_and_unknown_reservation():
    store = MemoryStore()
    before = store.load()["state"]
    class Failure:
        def complete(self, **kwargs):
            raise TimeoutError("Mock timeout")
    run_id = start_run(store)
    execute_run(store, run_id, Failure())
    data = store.load()
    assert data["state"] == before
    assert data["runs"][run_id]["calls"][0]["status"] == "unknown"
    assert budget_totals(data)["unknown"] > 0
    call = data["runs"][run_id]["calls"][0]
    reconcile_cost(store, run_id, call["id"], 0.012, "Проверено в тестовом Usage")
    assert budget_totals(store.load())["unknown"] == 0


def test_interrupted_run_recovery_retains_reserve_and_never_resumes_api():
    store = MemoryStore()
    run_id = start_run(store)
    def break_run(data):
        data["lease"]["until"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        data["runs"][run_id]["calls"].append({"id": "pending", "status": "pending", "reserved_usd": 0.04, "timestamp": datetime.now(timezone.utc).isoformat(), "model": "gpt-6-sol"})
    store.transact(break_run)
    store.transact(recover_expired)
    data = store.load()
    assert data["runs"][run_id]["status"] == "interrupted"
    assert data["runs"][run_id]["calls"][0]["status"] == "unknown"
    assert data["backlog"][0]["status"] == "ready"
    assert data["lease"] is None


def test_live_run_is_not_marked_interrupted_and_second_run_is_blocked():
    store = MemoryStore()
    run_id = start_run(store)
    store.transact(recover_expired)
    assert store.load()["runs"][run_id]["status"] == "queued"
    with pytest.raises(Busy):
        start_run(store)


def test_pause_prevents_next_api_and_disables_scheduler():
    store = MemoryStore()
    run_id = start_run(store)
    pause_all(store)
    execute_run(store, run_id, MockLLM())
    data = store.load()
    assert data["runs"][run_id]["status"] == "cancelled"
    assert not data["runs"][run_id]["calls"]
    assert not data["settings"]["scheduler_enabled"]
    assert not data["settings"]["autonomous_mode"]


def test_persistence_and_human_review_survive_restart(tmp_path):
    store = LocalStore(tmp_path)
    run_id = start_run(store, mock=True)
    execute_run(store, run_id, MockLLM())
    task_id = store.load()["backlog"][0]["ID"]
    with pytest.raises(ValueError):
        edit_task(store, task_id, status="done")
    edit_task(store, task_id, status="done", review_note="Тестовый результат проверен по критерию")
    restarted = LocalStore(tmp_path)
    data = restarted.load()
    assert data["runs"][run_id]["status"] == "completed"
    assert data["backlog"][0]["status"] == "done"
    assert data["artifacts"]
    assert (tmp_path / "journal/JOURNAL.jsonl").read_text()
    assert any(tmp_path.glob("strategy/*.md"))


def test_dependencies_and_scheduler_window():
    data = seed()
    data["backlog"][0]["dependencies"] = data["backlog"][1]["ID"]
    assert data["backlog"][0]["ID"] not in {t["ID"] for t in eligible_tasks(data)}
    current = datetime(2026, 9, 30, 6, 17, tzinfo=timezone.utc)  # 09:17 Moscow
    assert not due_jobs(data, current)
    data["settings"].update({"scheduler_enabled": True, "autonomous_mode": True})
    due = due_jobs(data, current)
    assert any(job["id"] == "backlog" for _, job, _ in due)
    for _, _, key in due:
        data["schedule_last"][key] = current.isoformat()
    assert not due_jobs(data, current)
