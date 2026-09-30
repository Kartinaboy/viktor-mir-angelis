from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .engine import Busy, Cancelled, execute_run, start_run

INSTRUCTIONS = {
    "morning": "Подготовь утренний обзор STATE: что стратегически не решено, 3 приоритета, какие доказательства отсутствуют. Не создавай контент ради объёма. Файл STATE_DELTA.md; критерий: конкретные изменения и следующая задача.",
    "report": "Создай вечерний DAILY_REPORT по шаблону spec/DAILY_REPORT_TEMPLATE.md. Только реальные события, файлы и решения из входа. Не выдумывай работу. Укажи изменения, главный вывод, выполненное, гипотезы, отклонённые идеи, вопросы Виктору, следующие задачи и расходы.",
    "maintenance": "Сделай короткий текстовый аудит STATE/BACKLOG: возможные дубликаты, теги и указатели. Ничего не удаляй и не меняй миссию. Создай JSON/Markdown с предлагаемыми действиями и явными основаниями.",
}


def due_jobs(data, current=None):
    settings = data["settings"]
    if not settings["scheduler_enabled"] or not settings["autonomous_mode"]:
        return []
    current = (current or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings["timezone"]))
    due = []
    for job in settings["jobs"]:
        hour, minute = map(int, job["time"].split(":"))
        scheduled = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        key = f"{current.date().isoformat()}:{job['id']}"
        # Don't replay a whole missed day after downtime. Allow normal Actions delays (up to 2 hours).
        if job["enabled"] and scheduled <= current < scheduled + timedelta(hours=2) and key not in data["schedule_last"]:
            due.append((scheduled, job, key))
    return sorted(due, key=lambda row: row[0])


def next_jobs(data):
    settings = data["settings"]
    if not settings["scheduler_enabled"] or not settings["autonomous_mode"]:
        return []
    current = datetime.now(timezone.utc).astimezone(ZoneInfo(settings["timezone"]))
    upcoming = []
    for job in settings["jobs"]:
        if not job["enabled"]:
            continue
        hour, minute = map(int, job["time"].split(":"))
        dt = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if dt <= current or f"{current.date().isoformat()}:{job['id']}" in data["schedule_last"]:
            dt += timedelta(days=1)
        upcoming.append({"job": job["title"], "at": dt.isoformat()})
    return sorted(upcoming, key=lambda row: row["at"])


def tick(store, llm):
    for _, job, key in due_jobs(store.load()):
        try:
            run_id = start_run(store, instruction=INSTRUCTIONS.get(job["id"], ""), schedule_key=key,
                               custom_domain="archive" if job["id"] == "maintenance" else "report",
                               custom_tier="cheap" if job["id"] == "maintenance" else "default")
        except (Busy, Cancelled):
            return
        except ValueError:
            continue
        execute_run(store, run_id, llm)
