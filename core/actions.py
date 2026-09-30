from __future__ import annotations

import copy
import uuid

from .config import validate_settings
from .engine import event
from .models import TASK_FIELDS, now


def create_task(store, title: str, definition: str, priority="P1", domain="strategy", tier="default"):
    task_id = "VM-" + uuid.uuid4().hex[:8]
    if not title.strip() or not definition.strip() or len(title) > 6000 or len(definition) > 6000:
        raise ValueError("Укажите задачу и критерий готовности (до 6000 символов)")
    def add(data):
        task = {key: "" for key in TASK_FIELDS}
        task.update({"ID": task_id, "task": title.strip(), "definition_of_done": definition.strip(),
                     "priority": priority, "domain": domain, "model_tier": tier, "status": "open",
                     "source": "Viktor", "created_at": now(), "updated_at": now()})
        data["backlog"].append(task)
        event(data, "manual", "backlog_updated", f"Виктор создал {task_id}")
    store.transact(add, f"Ангелис: create task {task_id}")
    return task_id


def edit_task(store, task_id: str, *, status=None, priority=None, review_note=""):
    def edit(data):
        task = next(t for t in data["backlog"] if t["ID"] == task_id)
        if task["status"] == "running":
            raise ValueError("Активную задачу сначала нужно остановить")
        if status == "done":
            if task["status"] != "review":
                raise ValueError("Завершить можно только задачу на review")
            artifacts = [data["artifacts"].get(aid) for aid in task["output_artifacts"].split(";")]
            if not any(a and a["content"].strip() for a in artifacts):
                raise ValueError("Для done нужен artifact/evidence")
            if not review_note.strip():
                raise ValueError("Запишите, как выполнен definition_of_done")
            for artifact in artifacts:
                if artifact:
                    artifact["review_status"] = "approved"
        if status:
            task["status"] = status
        if priority:
            task["priority"] = priority
        task["updated_at"] = now()
        event(data, "manual", "backlog_updated", f"Виктор изменил {task_id}: {task['status']}; {task['priority']}. {review_note}")
    store.transact(edit, f"Ангелис: review {task_id}")


def save_settings(store, settings):
    validate_settings(settings)
    def save(data):
        if data.get("lease"):
            raise ValueError("Настройки моделей и бюджета меняются между запусками. Кнопка Pause All доступна сразу.")
        data["settings"] = copy.deepcopy(settings)
        event(data, "settings", "settings_updated", "Виктор изменил модели, бюджеты и настройки расписания.")
    store.transact(save, "Ангелис: update settings")


def reconcile_cost(store, run_id, call_id, amount: float, note: str):
    if amount < 0 or not note.strip():
        raise ValueError("Нужны неотрицательная сумма и основание сверки")
    def reconcile(data):
        run = data["runs"][run_id]
        if run["status"] in {"queued", "running"}:
            raise ValueError("Дождитесь завершения запуска")
        call = next(c for c in run["calls"] if c["id"] == call_id)
        if call["status"] == "settled":
            raise ValueError("Стоимость этого запроса уже учтена")
        call.update({"status": "settled", "cost_usd": amount, "manual_reconciliation": note})
        event(data, run_id, "cost_reconciled", f"Виктор сверил {call_id}: ${amount:.6f}. {note}", model=call["model"])
    store.transact(reconcile, f"Ангелис: reconcile {call_id}")
